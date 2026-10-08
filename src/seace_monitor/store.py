"""Read and write pipeline state in Postgres."""

from datetime import date, datetime, timedelta

import psycopg

from .archives import ARCHIVE_SUFFIXES
from .ficha import has_bases
from .search import LIMA
from .track import closes

# After this many failures an item stays in error and is only reported.
MAX_ATTEMPTS = 3

# An obra without any change for this long is stalled and no longer tracked.
STALLED_DAYS = 60

COLUMNS = (
    "nid_proceso", "nomenclatura", "entidad", "objeto", "descripcion",
    "fecha_publicacion", "valor_referencial", "moneda", "cui", "reiniciado_desde",
    "departamentos", "ubicacion_fuente", "departamento_busqueda",
)

INSERT = f"""
    INSERT INTO licitaciones ({", ".join(COLUMNS)})
    VALUES ({", ".join("%s" for _ in COLUMNS)})
    ON CONFLICT (nid_proceso) DO NOTHING
    RETURNING nid_proceso
"""


def save_new_licitaciones(conn: psycopg.Connection, rows: list[dict]) -> list[int]:
    """Insert rows whose nid_proceso is not stored yet; return those nid_proceso.

    Known rows are left as they are: a later step that re-reads known
    licitaciones will record their changes in historial instead of overwriting. All rows passed
    in (one results page) are written in one transaction, so a failing row stores none of them.
    """
    new = []
    with conn.transaction():
        for row in rows:
            inserted = conn.execute(INSERT, [row[c] for c in COLUMNS]).fetchone()
            if inserted:
                new.append(inserted[0])
    return new


def link_restarts(conn: psycopg.Connection) -> list[tuple[int, int]]:
    """Link each obra not linked yet to the latest earlier one with the same entidad and nomenclatura.

    The nomenclatura alone repeats across entidades. A higher nid_proceso is a later
    publication, so the earlier obra is the one with the highest lower nid. It stops being
    tracked if it still was. Returns the (earlier, later) pairs linked now.
    """
    pairs = conn.execute(
        """SELECT o.nid_proceso, o.estado_items, n.nid_proceso, n.reiniciado_desde
           FROM licitaciones n
           JOIN LATERAL (
               SELECT nid_proceso, estado_items FROM licitaciones o
               WHERE o.entidad = n.entidad AND o.nomenclatura = n.nomenclatura AND o.nid_proceso < n.nid_proceso
                 -- an earlier obra already restarted by another one is not linked twice
                 AND NOT EXISTS (SELECT 1 FROM licitaciones x WHERE x.reinicio_de = o.nid_proceso)
               ORDER BY o.nid_proceso DESC LIMIT 1
           ) o ON true
           WHERE n.reinicio_de IS NULL
           ORDER BY n.nid_proceso"""
    ).fetchall()
    for old, estados, new, desde in pairs:
        with conn.transaction():
            conn.execute("UPDATE licitaciones SET reinicio_de = %s WHERE nid_proceso = %s", [old, new])
            stage = f" desde {desde}" if desde else ""
            estado = " / ".join(estados) if estados else "sin leer"
            record_changes(conn, new, [("reinicio", None, f"reiniciada{stage}; antes nid {old}, estado {estado}")])
            stopped = conn.execute(
                """UPDATE licitaciones SET seguimiento = 'reiniciada', seguimiento_hasta = now()
                   WHERE nid_proceso = %s AND seguimiento = 'abierta' RETURNING 1""",
                [old],
            ).fetchone()
            if stopped:
                record_changes(conn, old, [("seguimiento", "abierta", "reiniciada")])
    return [(old, new) for old, _, new, _ in pairs]


def fichas_to_read(conn: psycopg.Connection, nids: list[int]) -> set[int]:
    """Of these licitaciones, the ones whose document list is still missing or that are still tracked."""
    rows = conn.execute(
        """SELECT nid_proceso FROM licitaciones WHERE nid_proceso = ANY(%s)
           AND (ficha_estado = 'pending' OR (ficha_estado = 'done' AND seguimiento = 'abierta'))""",
        [nids],
    ).fetchall()
    return {r[0] for r in rows}


def open_since(conn: psycopg.Connection) -> dict[str, date]:
    """Per search departamento, the publication date (Lima) of the oldest obra still tracked."""
    rows = conn.execute(
        """SELECT departamento_busqueda, min(fecha_publicacion) FROM licitaciones
           WHERE seguimiento = 'abierta' AND departamento_busqueda IS NOT NULL AND fecha_publicacion IS NOT NULL
           GROUP BY 1"""
    ).fetchall()
    return {d: since.astimezone(LIMA).date() for d, since in rows}


def tracked(conn: psycopg.Connection) -> list[int]:
    return [r[0] for r in conn.execute(
        "SELECT nid_proceso FROM licitaciones WHERE seguimiento = 'abierta' ORDER BY nid_proceso"
    ).fetchall()]


def mark_stalled(conn: psycopg.Connection, now: datetime, days: int = STALLED_DAYS) -> list[int]:
    """Stop tracking obras without any change for this many days; until a first change, since publication."""
    with conn.transaction():
        nids = [r[0] for r in conn.execute(
            """UPDATE licitaciones SET seguimiento = 'parada', seguimiento_hasta = %s
               WHERE seguimiento = 'abierta' AND COALESCE(ultimo_cambio_en, fecha_publicacion) < %s
               RETURNING nid_proceso""",
            [now, now - timedelta(days=days)],
        ).fetchall()]
        for nid in nids:
            record_changes(conn, nid, [("seguimiento", "abierta", "parada")])
    return sorted(nids)


def save_ficha(conn: psycopg.Connection, nid: int, documents: list[dict], deadline: datetime | None = None,
               estados: list[str] | None = None) -> int:
    """Store a ficha's documents, offer deadline and item estados; return how many documents were new.

    The ficha counts as read only once it lists a bases. Until then it stays
    pending without spending attempts, since entities often publish it later.
    The licitación keeps the current values. Once a ficha has been read, every later
    difference (estados, deadline, a new document, the obra closing) also becomes a historial row.
    """
    new = 0
    with conn.transaction():
        stored_estados, stored_deadline = conn.execute(
            "SELECT estado_items, fecha_limite_ofertas FROM licitaciones WHERE nid_proceso = %s", [nid]
        ).fetchone()
        read_before = stored_estados is not None
        changes = []
        if estados and estados != stored_estados:
            if read_before:
                changes.append(("estado_items", " / ".join(stored_estados), " / ".join(estados)))
            conn.execute("UPDATE licitaciones SET estado_items = %s WHERE nid_proceso = %s", [estados, nid])
        if deadline and deadline != stored_deadline:
            if stored_deadline:
                changes.append(("fecha_limite_ofertas", lima_text(stored_deadline), lima_text(deadline)))
            conn.execute("UPDATE licitaciones SET fecha_limite_ofertas = %s WHERE nid_proceso = %s", [deadline, nid])
        for d in documents:
            inserted = conn.execute(
                """INSERT INTO documentos (nid_proceso, uuid, etapa, tipo, nombre_archivo, publicado_en, estado)
                   VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING RETURNING id""",
                [nid, d["uuid"], d["etapa"], d["tipo"], d["nombre_archivo"], d["publicado_en"],
                 "pending" if d["uuid"] else "sin_enlace"],
            ).fetchone()
            new += inserted is not None
            if inserted and read_before:
                changes.append(("documento", None, f"{d['tipo']}: {d['nombre_archivo']}"))
        if has_bases(documents):
            conn.execute(
                "UPDATE licitaciones SET ficha_estado = 'done', ficha_ultimo_error = NULL WHERE nid_proceso = %s",
                [nid],
            )
        if closes(estados, documents):
            closed = conn.execute(
                """UPDATE licitaciones SET seguimiento = 'cerrada', seguimiento_hasta = now()
                   WHERE nid_proceso = %s AND seguimiento = 'abierta' RETURNING 1""",
                [nid],
            ).fetchone()
            if closed and read_before:
                changes.append(("seguimiento", "abierta", "cerrada"))
        record_changes(conn, nid, changes)
    return new


def lima_text(moment: datetime) -> str:
    return moment.astimezone(LIMA).strftime("%d/%m/%Y %H:%M")


def record_changes(conn: psycopg.Connection, nid: int, changes: list[tuple[str, str | None, str | None]]) -> None:
    """Write (campo, valor_anterior, valor_nuevo) rows to historial and note when the obra last changed."""
    if not changes:
        return
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO historial (nid_proceso, campo, valor_anterior, valor_nuevo) VALUES (%s, %s, %s, %s)",
            [(nid, *change) for change in changes],
        )
    conn.execute("UPDATE licitaciones SET ultimo_cambio_en = now() WHERE nid_proceso = %s", [nid])


def ficha_failed(conn: psycopg.Connection, nid: int, error: str) -> None:
    """Count a failed first reading. A tracked ficha read before is simply read again on the next run."""
    with conn.transaction():
        conn.execute(
            """UPDATE licitaciones
               SET ficha_intentos = ficha_intentos + 1, ficha_ultimo_error = %s,
                   ficha_estado = CASE WHEN ficha_intentos + 1 >= %s THEN 'error' ELSE 'pending' END
               WHERE nid_proceso = %s AND ficha_estado = 'pending'""",
            [error, MAX_ATTEMPTS, nid],
        )


def pending_documents(conn: psycopg.Connection, nids: list[int]) -> list[dict]:
    """Pending documents of these licitaciones only; each caller says which obras it needs."""
    rows = conn.execute(
        "SELECT id, nid_proceso, uuid, nombre_archivo FROM documentos"
        " WHERE estado = 'pending' AND nid_proceso = ANY(%s) ORDER BY id",
        [nids],
    ).fetchall()
    return [dict(zip(("id", "nid_proceso", "uuid", "nombre_archivo"), r)) for r in rows]


def document_done(conn: psycopg.Connection, doc_id: int, ruta_local: str, tamano_bytes: int) -> None:
    with conn.transaction():
        conn.execute(
            """UPDATE documentos SET estado = 'done', ruta_local = %s, tamano_bytes = %s, ultimo_error = NULL
               WHERE id = %s""",
            [ruta_local, tamano_bytes, doc_id],
        )


def document_failed(conn: psycopg.Connection, doc_id: int, error: str) -> None:
    with conn.transaction():
        conn.execute(
            """UPDATE documentos
               SET intentos = intentos + 1, ultimo_error = %s,
                   estado = CASE WHEN intentos + 1 >= %s THEN 'error' ELSE 'pending' END
               WHERE id = %s""",
            [error, MAX_ATTEMPTS, doc_id],
        )



def archives_to_unpack(conn: psycopg.Connection, nids: list[int] | None = None) -> list[dict]:
    """Downloaded ZIP, RAR and 7z documents not unpacked yet; None means of every obra."""
    sql = ("SELECT id, ruta_local FROM documentos"
           " WHERE estado = 'done' AND contenido_estado IS NULL AND lower(ruta_local) LIKE ANY(%s)")
    params = [[f"%{s}" for s in sorted(ARCHIVE_SUFFIXES)]]
    if nids is not None:
        sql += " AND nid_proceso = ANY(%s)"
        params.append(nids)
    rows = conn.execute(sql + " ORDER BY id", params).fetchall()
    return [dict(zip(("id", "ruta_local"), r)) for r in rows]


def contents_done(conn: psycopg.Connection, doc_id: int, files: list[dict]) -> None:
    """Replace what is stored of this archive's contents, so unpacking it again is safe."""
    with conn.transaction():
        conn.execute("DELETE FROM documento_contenido WHERE documento_id = %s", [doc_id])
        with conn.cursor() as cur:
            cur.executemany(
                """INSERT INTO documento_contenido (documento_id, ruta, tamano_bytes, dentro_de, error)
                   VALUES (%s, %s, %s, %s, %s)""",
                [(doc_id, f["ruta"], f["tamano_bytes"], f["dentro_de"], f["error"]) for f in files],
            )
        conn.execute(
            "UPDATE documentos SET contenido_estado = 'done', contenido_error = NULL WHERE id = %s", [doc_id]
        )


def contents_failed(conn: psycopg.Connection, doc_id: int, error: str) -> None:
    # Not retried: a broken or protected archive stays broken until it is downloaded again.
    with conn.transaction():
        conn.execute(
            "UPDATE documentos SET contenido_estado = 'error', contenido_error = %s WHERE id = %s", [error, doc_id]
        )

def mark_reported(conn: psycopg.Connection, nids: list[int]) -> None:
    """Call only after the report was accepted by the mail server: a crash before
    this line sends the same obras again tomorrow, which is better than losing them."""
    with conn.transaction():
        conn.execute("UPDATE licitaciones SET informado_en = now() WHERE nid_proceso = ANY(%s)", [nids])


def mark_extractions_reported(conn: psycopg.Connection, ids: list[int]) -> None:
    with conn.transaction():
        conn.execute("UPDATE extracciones SET informado_en = now() WHERE id = ANY(%s)", [ids])
