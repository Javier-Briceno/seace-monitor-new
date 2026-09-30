"""Write search results to Postgres."""

import psycopg

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

    Known rows are left as they are: changes to them are track's job, which
    records them in historial instead of overwriting. All rows of one search
    are written in one transaction, so a failing row stores none of them.
    """
    new = []
    with conn.transaction():
        for row in rows:
            inserted = conn.execute(INSERT, [row[c] for c in COLUMNS]).fetchone()
            if inserted:
                new.append(inserted[0])
    return new
