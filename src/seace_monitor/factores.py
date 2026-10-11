"""The factores de evaluación of chapter IV: which ones the entity chose and how many points each gives.

Chapter IV describes each factor ("A. EXPERIENCIA ESPECÍFICA ADICIONAL DEL PERSONAL CLAVE ... Evaluación:
40 puntos") and closes the evaluación técnica with a CUADRO RESUMEN that lists them again with the
PUNTAJE TOTAL. The table is read first; a figure it leaves unreadable (OCR) comes from the description,
and a figure that differs from the description is a warning.
The points must add up to the total and the total to 100; any other sum is a warning.
"""

import re
from collections.abc import Callable
from pathlib import Path

from . import reading
from .bases_text import page_of

VERSION = "factores-1"

TECHNICAL = re.compile(r"EVALUACI[OÓ]N\s+T[EÉ]CNICA\s*\n", re.I)
# Not the "CUADRO RESUMEN DEL PAGO AL CONTRATISTA" of the contract chapter; OCR can lose "CUADRO".
SUMMARY = re.compile(r"(?:CUADRO\s+)?RESUMEN\W{0,5}(?:DE\s+)?(?:LOS\s+)?FACTORES\s+DE\s+EVALUACI", re.I)
# "40 puntos", "[5] puntos", "05.00 puntos", "100.0 puntos"; never the "0" of "05.00"
FIGURE = r"\[?\s*(?<![\d.,])(\d{1,3})(?:[.,]\d{1,2})?\s*\]?\s*puntos"
# Word puts each table cell on its own line
TOTAL = re.compile(r"PUNTAJE\s+TOTAL[^\n]*?(?:\n[^\n\d]{0,20})?" + FIGURE, re.I)
# "A. EXPERIENCIA ...", OCR's "[E. GESTIÓN DE CALIDAD?", sub-factors "B.1 FORMACIÓN ACADÉMICA ..."
ROW = re.compile(r"^[^\w\n]{0,30}([A-P](?:\.\d)?)(?:\s*[.)]\s*|(?<=\d)\s+)([A-ZÁÉÍÓÚÑ].*)$", re.M)
# group 1 stays empty: these rows have no letter
UNLETTERED = re.compile(r"^()\s*([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ ,/\-]{5,75})\s*$", re.M)
POINTS = re.compile(FIGURE, re.I)
NOT_USED = re.compile(r"NO\s+CORRESPONDE", re.I)
TEMPLATE = re.compile(r"\[\s*Como\s+m[aá]ximo", re.I)
EVALUATION = re.compile(r"Evaluaci[oó]n\s*:(.{0,300}?)" + FIGURE, re.I | re.S)
MINIMUM = re.compile(r"puntaje\s+t[eé]cnico\s+m[ií]nimo\s+de\s+(\w+)", re.I)
MINIMUM_WORDS = {"setenta": 70, "sesenta": 60, "ochenta": 80, "cincuenta": 50}

# The factors of the standard bases, by a word of their name that OCR leaves alone; most specific first.
FACTORS = (
    ("FORMACI", "Formación académica adicional del personal clave"),
    ("CERTIFICACIONES", "Certificaciones adicionales del personal clave"),
    ("PERSONAL", "Experiencia específica adicional del personal clave"),
    ("POSTOR", "Experiencia adicional del postor en la especialidad"),
    ("AMBIENTAL", "Sostenibilidad ambiental"),
    ("SOCIAL", "Sostenibilidad social"),
    ("INTEGRIDAD", "Integridad en la contratación pública"),
    ("CALIDAD", "Gestión de calidad"),
    ("SEGURIDAD", "Seguridad y salud"),
    ("CAPACITACI", "Capacitación"),
    ("MEJORA", "Mejora al requerimiento"),
    ("RIESGO", "Gestión de riesgos"),
    ("PROCURA", "Gestión de procura"),
    ("PLANIFICACI", "Planificación detallada"),
    ("BIM", "Plan de ejecución BIM"),
    ("TECNOLOG", "Tecnología y métodos innovadores"),
)

UNNAMED = "factor de nombre ilegible"

NOT_FOUND = "sin cuadro resumen de factores"
UNREADABLE = "puntajes ilegibles"


def factor_name(words: str) -> str | None:
    words = words.upper()
    return next((name for key, name in FACTORS if key in words), None)


def summary_table(text: str) -> tuple[int, int, re.Match] | None:
    """Where the CUADRO RESUMEN starts and ends, and its PUNTAJE TOTAL. Its title is the landmark: the
    chapter title and the numbering ("4.2.") get lost in Word files and in OCR."""
    for m in SUMMARY.finditer(text):
        total = TOTAL.search(text, m.end(), m.end() + 5000)
        if total and len(summary_rows(text[m.end(): total.start()])) >= 1:
            return m.start(), m.end(), total
    return None


def descriptions(text: str, table_start: int) -> str:
    """The evaluación técnica before the table: from its heading, else the 40,000 characters before it."""
    heading = list(TECHNICAL.finditer(text, max(0, table_start - 60000), table_start))
    return text[heading[-1].start() if heading else max(0, table_start - 40000): table_start]


def summary_rows(table: str) -> list[dict]:
    """Rows of the CUADRO RESUMEN: a letter starts a row, the lines below it until the next letter belong to it.
    A Word file loses the list letters; there a short line in capitals naming a factor starts the row."""
    starts = list(ROW.finditer(table))
    if not starts:
        starts = [m for m in UNLETTERED.finditer(table) if factor_name(m.group(2))]
    rows = []
    for n, m in enumerate(starts):
        body = table[m.start(): starts[n + 1].start() if n + 1 < len(starts) else len(table)]
        # A page break inside the table brings footnotes and the page header; the name is in the first lines.
        lines = [line for line in body.splitlines() if line.strip()]
        name = factor_name(lines[0]) or factor_name(" ".join(lines[:3]))
        points = POINTS.search(body)
        if name is None and not points:
            continue
        # a row OCR left without a readable name still counts in the sum
        name = name or UNNAMED
        rows.append({"letra": m.group(1), "factor": name, "puntos": int(points.group(1)) if points else None,
                     "no_corresponde": bool(NOT_USED.search(body)) and not points,
                     "plantilla": bool(TEMPLATE.search(body)) and not points})
    return rows


def described_points(block: str) -> dict[str, int]:
    """Points of each factor as its own description states them ("Evaluación: 40 puntos"), by factor name."""
    found = {}
    heads = [(m, name) for m in ROW.finditer(block) if (name := heading_name(block, m))]
    for n, (m, name) in enumerate(heads):
        end = heads[n + 1][0].start() if n + 1 < len(heads) else len(block)
        evaluation = EVALUATION.search(block, m.end(), min(end, m.end() + 1500))
        # "0 puntos" is the scale's "No acredita", reached when the figure sits away from "Evaluación:"
        if evaluation and name not in found and int(evaluation.group(2)) > 0:
            found[name] = int(evaluation.group(2))
    return found


def heading_name(block: str, m: re.Match) -> str | None:
    """The factor a heading names; a name broken over two lines ("M. EXPERIENCIA ADICIONAL DEL POSTOR EN /
    LA ESPECIALIDAD") is completed by the next line, never by the description below it."""
    following = next((line for line in block[m.end():].splitlines() if line.strip()), "")
    return factor_name(m.group(2)) or factor_name(m.group(2) + " " + following[:60])


def read(text: str) -> dict:
    """The factors with their points, the total and the minimum technical score; `avisos` when they do not add up."""
    result = {"pagina": None, "factores": [], "total": None, "suma": None, "minimo_tecnico": None, "avisos": [],
              "revisar": None}
    found = summary_table(text)
    if found is None:
        result["revisar"] = NOT_FOUND
        return result
    table_start, table_end, total = found
    result["pagina"] = page_of(text, table_start)
    before = descriptions(text, table_start)
    if minimum := MINIMUM.search(before):
        word = minimum.group(1).lower()
        result["minimo_tecnico"] = int(word) if word.isdigit() else MINIMUM_WORDS.get(word)
    result["total"] = int(total.group(1))
    table = text[table_end: total.start()]
    rows = [r for r in summary_rows(table) if not r["no_corresponde"]]
    # "E. CAPACITACIÓN [Como máximo 10]": the template's text left in the table, no points given
    if template := [r["factor"] for r in rows if r["plantilla"]]:
        result["avisos"].append({"aviso": "factor_sin_rellenar", "factores": template})
        rows = [r for r in rows if not r["plantilla"]]
    # More figures in the table than rows read: a row lost its letter ("o INTEGRIDAD ..."), the sum would lie.
    if len(POINTS.findall(table)) > sum(1 for r in rows if r["puntos"] is not None):
        result["revisar"] = UNREADABLE
        return result
    described = described_points(before)
    for row in rows:
        if row["puntos"] is not None and row["puntos"] > result["total"]:
            row["puntos"] = None  # OCR's "130" for "|30": no factor gives more than the total
        if row["puntos"] is None:
            row["puntos"] = described.get(row["factor"])
    differ = [r for r in rows if r["factor"] in described and described[r["factor"]] != r["puntos"]]
    repaired = False
    if differ and None not in (r["puntos"] for r in rows):
        # The figures whose sum is the total win: a misread digit (OCR) leaves the sum off.
        with_described = sum(described[r["factor"]] if r in differ else r["puntos"] for r in rows)
        repaired = sum(r["puntos"] for r in rows) != result["total"] and with_described == result["total"]
    # A factor of several practices states the points of the first one only ("k.1 ... Evaluación: 5 puntos",
    # then k.3 with 10 more): a description below the table is no contradiction unless it fixes the sum.
    for r in differ:
        if repaired or (r["puntos"] is not None and described[r["factor"]] > r["puntos"]):
            result["avisos"].append({"aviso": "puntaje_distinto", "factor": r["factor"], "cuadro": r["puntos"],
                                     "descripcion": described[r["factor"]]})
        if repaired:
            r["puntos"] = described[r["factor"]]
    # A row without a figure next to rows that already add up to the total gives no points.
    if sum(r["puntos"] or 0 for r in rows) == result["total"]:
        rows = [r for r in rows if r["puntos"] is not None]
    result["factores"] = [{"letra": r["letra"], "factor": r["factor"], "puntos": r["puntos"]} for r in rows]
    if not rows or any(r["puntos"] is None for r in rows):
        result["revisar"] = UNREADABLE
        return result
    result["suma"] = sum(r["puntos"] for r in rows)
    if result["suma"] != result["total"]:
        result["avisos"].append({"aviso": "suma_distinta_total", "suma": result["suma"], "total": result["total"]})
    if result["total"] != 100:
        result["avisos"].append({"aviso": "total_distinto_100", "total": result["total"]})
    return result


def read_files(files: list[Path], ocr: Callable[[Path, list[int]], Path] | None = None) -> dict:
    result = reading.read_files(files, read, NOT_FOUND, ocr)
    if not result["ocr"] or result["revisar"]:
        return result
    # From OCR a sum that is not the total is nearly always a row it lost, and a description that differs
    # from a table adding up to the total a misread digit: not the entity's mistake.
    if any(w["aviso"] == "suma_distinta_total" for w in result["avisos"]):
        result["avisos"] = [w for w in result["avisos"] if w["aviso"] not in ("suma_distinta_total", "puntaje_distinto")]
        result["revisar"] = UNREADABLE
    else:
        result["avisos"] = [w for w in result["avisos"] if w["aviso"] != "puntaje_distinto"]
    return result
