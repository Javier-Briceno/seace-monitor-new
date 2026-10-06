"""Read and write pipeline state in Postgres."""

from datetime import datetime

import psycopg

from .ficha import has_bases

# After this many failures an item stays in error and is only reported.
MAX_ATTEMPTS = 3

COLUMNS = (
    "nid_proceso", "nomenclatura", "entidad", "objeto", "descripcion",
    "fecha_publicacion", "valor_referencial", "moneda", "cui", "reiniciado_desde",
    "departamentos", "ubicacion_fuente",
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
    licitaciones will record their changes in historial instead of overwriting. All rows of one search
    are written in one transaction, so a failing row stores none of them.
    """
    new = []
    with conn.transaction():
        for row in rows:
            inserted = conn.execute(INSERT, [row[c] for c in COLUMNS]).fetchone()
            if inserted:
                new.append(inserted[0])
    return new


def fichas_to_read(conn: psycopg.Connection, nids: list[int]) -> set[int]:
    """Of these licitaciones, the ones whose document list is still missing."""
    rows = conn.execute(
        "SELECT nid_proceso FROM licitaciones WHERE nid_proceso = ANY(%s) AND ficha_estado = 'pending'",
        [nids],
    ).fetchall()
    return {r[0] for r in rows}


def save_ficha(conn: psycopg.Connection, nid: int, documents: list[dict], deadline: datetime | None = None) -> int:
    """Store a ficha's documents and offer deadline; return how many documents were new.

    The ficha counts as read only once it lists a bases. Until then it stays
    pending without spending attempts, since entities often publish it later.
    A stored deadline is never overwritten: a postponement is a change for historial.
    """
    new = 0
    with conn.transaction():
        if deadline:
            conn.execute(
                "UPDATE licitaciones SET fecha_limite_ofertas = COALESCE(fecha_limite_ofertas, %s) WHERE nid_proceso = %s",
                [deadline, nid],
            )
        for d in documents:
            inserted = conn.execute(
                """INSERT INTO documentos (nid_proceso, uuid, etapa, tipo, nombre_archivo, publicado_en, estado)
                   VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING RETURNING id""",
                [nid, d["uuid"], d["etapa"], d["tipo"], d["nombre_archivo"], d["publicado_en"],
                 "pending" if d["uuid"] else "sin_enlace"],
            ).fetchone()
            new += inserted is not None
        if has_bases(documents):
            conn.execute(
                "UPDATE licitaciones SET ficha_estado = 'done', ficha_ultimo_error = NULL WHERE nid_proceso = %s",
                [nid],
            )
    return new


def ficha_failed(conn: psycopg.Connection, nid: int, error: str) -> None:
    with conn.transaction():
        conn.execute(
            """UPDATE licitaciones
               SET ficha_intentos = ficha_intentos + 1, ficha_ultimo_error = %s,
                   ficha_estado = CASE WHEN ficha_intentos + 1 >= %s THEN 'error' ELSE 'pending' END
               WHERE nid_proceso = %s""",
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


def mark_reported(conn: psycopg.Connection, nids: list[int]) -> None:
    """Call only after the report was accepted by the mail server: a crash before
    this line sends the same obras again tomorrow, which is better than losing them."""
    with conn.transaction():
        conn.execute("UPDATE licitaciones SET informado_en = now() WHERE nid_proceso = ANY(%s)", [nids])


def mark_extractions_reported(conn: psycopg.Connection, ids: list[int]) -> None:
    with conn.transaction():
        conn.execute("UPDATE extracciones SET informado_en = now() WHERE id = ANY(%s)", [ids])
