"""How the bases of the open obras were read: per value, from the PDF's own text, from the vision model's
transcription with Tesseract agreeing or not, from one of the two only, or not at all; and what the vision
model cost per month. Learning from this whether Tesseract still adds anything is why both readings are kept."""

import psycopg

READERS = (("cuantia", "Cuantía"), ("experiencia", "Experiencia del postor"), ("factores", "Factores"),
           ("personal", "Personal clave"), ("objeto", "Nombre de la obra"))
KINDS = ("texto del PDF", "Haiku y Tesseract coinciden", "Haiku y Tesseract difieren", "solo Haiku",
         "solo Tesseract", "sin leer")


def kind(campos: dict) -> str:
    if campos.get("revisar"):
        return "sin leer"
    if not campos.get("ocr"):
        return "texto del PDF"
    if not campos.get("ia"):
        return "solo Tesseract"
    second = campos.get("segunda_lectura") or {}
    if second.get("tesseract") is None:
        return "solo Haiku"
    return "Haiku y Tesseract difieren" if second.get("difieren") else "Haiku y Tesseract coinciden"


def readings(conn: psycopg.Connection) -> dict[str, dict[str, int]]:
    """For the newest bases of each open obra, the latest reading of each reader, counted by how it was read."""
    out = {}
    for reader, _ in READERS:
        rows = conn.execute(
            """WITH newest AS (
                   SELECT DISTINCT ON (d.nid_proceso) d.id FROM documentos d
                   JOIN licitaciones l USING (nid_proceso)
                   WHERE l.seguimiento = 'abierta' AND d.estado = 'done' AND d.tipo ILIKE 'bases%%'
                   ORDER BY d.nid_proceso, (d.tipo ILIKE '%%integrad%%') DESC, d.publicado_en DESC NULLS LAST, d.id DESC)
               SELECT (SELECT e.campos FROM extracciones e WHERE e.documento_id = n.id
                         AND e.version_extractor LIKE %s ORDER BY e.creado_en DESC LIMIT 1)
               FROM newest n""", [reader + "-%"]).fetchall()
        counts = dict.fromkeys(KINDS, 0)
        for (campos,) in rows:
            counts[kind(campos) if campos else "sin leer"] += 1
        out[reader] = counts
    return out


def spending(conn: psycopg.Connection) -> list[tuple]:
    return conn.execute("SELECT mes, usd, paginas FROM gasto_ia ORDER BY mes DESC LIMIT 6").fetchall()


def text(conn: psycopg.Connection) -> str:
    lines = ["Lectura de las bases de las obras abiertas (la base más nueva de cada una)", ""]
    counts = readings(conn)
    for reader, label in READERS:
        lines.append(f"{label}: " + ", ".join(f"{k} {v}" for k, v in counts[reader].items() if v))
    lines += ["", "Gasto del modelo de visión por mes"]
    lines += [f"{mes:%Y-%m}: {usd:.2f} USD, {paginas} páginas" for mes, usd, paginas in spending(conn)] or ["sin gasto"]
    return "\n".join(lines)
