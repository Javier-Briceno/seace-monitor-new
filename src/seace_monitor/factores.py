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

VERSION = "factores-6"
# each factor by its standard name with its points, not by letter: entities reletter the factors between the
# summary table and the detail, and two readings may give the same points to different factors
VALUES = {"total": lambda r: r.get("total"),
          "puntos": lambda r: sorted(f"{f['factor']} {f['puntos']}" for f in r.get("factores") or []
                                     if f.get("puntos") is not None)}

TECHNICAL = re.compile(r"EVALUACI[OÓ]N\s+T[EÉ]CNICA\s*\n", re.I)
# Not the "CUADRO RESUMEN DEL PAGO AL CONTRATISTA" of the contract chapter; OCR can lose "CUADRO".
SUMMARY = re.compile(r"(?:CUADRO\s+)?RESUMEN\W{0,5}(?:DE\s+)?(?:LOS\s+)?FACTORES\s+DE\s+EVALUACI", re.I)
# "40 puntos", "[5] puntos", "05.00 puntos", "100.0 puntos", "100. puntos"; never the "0" of "05.00"
FIGURE = r"\[?\s*(?<![\d.,])(\d{1,3})(?:[.,]\d{0,2})?\s*\]?\s*puntos"
# Word puts each table cell on its own line
# Layout text can put the figure on the line above "PUNTAJE TOTAL" and "puntos" on the line below it.
TOTAL = re.compile(r"PUNTAJE\s+TOTAL[^\n]*?(?:\n[^\n\d]{0,20})?" + FIGURE
                   + r"|(?<![\d.,])(\d{1,3})[^\S\n]*\n[^\S\n]*PUNTAJE\s+TOTAL[^\S\n]*\n[^\S\n]*puntos", re.I)
# "A. EXPERIENCIA ...", sub-factors "B.1 FORMACIÓN ACADÉMICA ...", and OCR's "[E. GESTIÓN DE CALIDAD?",
# "lA. EXPERIENCIA", "|F. GESTIÓN" (a stray stroke before the letter), "A EXPERIENCIA" (the dot lost)
FIRST_WORD = r"(?:EXPERIENCIA|SOSTENIBILIDAD|INTEGRIDAD|GESTI|CAPACITACI|MEJORA|PLANIFICACI|SEGURIDAD|TECNOLOG|PLAN\b|FORMACI|CERTIFICACI)"
ROW = re.compile(r"^[^\w\n]{0,30}[lI|]?([A-P](?:\.\d)?)(?:\s*[.)]\s*|(?<=\d)\s+|\s+(?=" + FIRST_WORD + r"))"
                 r"([A-ZÁÉÍÓÚÑ].*)$", re.M)
# Rows without a letter (group 1 stays empty): a bullet ("o INTEGRIDAD EN LA  5 puntos"), or in Word, which
# loses the list letters, a short line in capitals.
BULLETED = re.compile(r"^()[^\w\n]{0,30}[o•·]\s+([A-ZÁÉÍÓÚÑ].*)$", re.M)
# Blanks but not the line break (\r and no-break spaces count): a match must not start on the blank line
# above the same row read with its letter.
UNLETTERED = re.compile(r"^()[^\S\n]*([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ ,/\-]{5,75})[^\S\n]*$", re.M)
# What the line before an unlettered row ends with: the previous row's figure, "NO CORRESPONDE" or evaluator
# (COMITÉ, JURADO), or a header
ROW_BEFORE = re.compile(r"puntos|CORRESPONDE|COMIT|JURADO|EVALUADOR|PUNTAJE|FACULTATIVOS|OBLIGATORIO", re.I)
HEADER = re.compile(r"FACTOR|OBLIGATORIO|FACULTATIVO|PUNTAJE|EVALUADOR|EN\s+CASO\s+DE", re.I)
POINTS = re.compile(FIGURE, re.I)
STRUCK = re.compile(r"^[^\S\n]*\[TACHADO\][^\n]*(?:\n|$)", re.M)
CELLS = re.compile(r" {3,}")
BARE = re.compile(r"\[?\s*(\d{1,3})\s*\]?")
NOT_USED = re.compile(r"NO\s+CORRESPONDE", re.I)
TEMPLATE = re.compile(r"\[\s*Como\s+m[aá]ximo", re.I)
# "[Como máximo 05]" is the standard's own cell for a factor of fixed points, "puntos" sometimes lines apart
TEMPLATE_FIGURE = re.compile(r"\[\s*Como\s+m[aá]ximo\s+(\d{1,3})\s*\]", re.I)
# a footnote at a page break inside the table: "24 El solo sello de cancelado ..."
FOOTNOTE = re.compile(r"^\s*\d{1,3}\s+[A-ZÁÉÍÓÚ][a-záéíóúñ]")
SPECIFIC = re.compile(r"EXPERIENCIA\s+ESPEC[IÍ]FICA", re.I)
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
    """Rows of the CUADRO RESUMEN: a letter starts a row, the lines below it until the next one belong to it.
    A bullet starts one too, and so does a short line in capitals naming a factor right after the previous row
    ended (Word loses list letters, sometimes only some of them)."""
    starts = list(ROW.finditer(table)) + list(BULLETED.finditer(table))
    for m in UNLETTERED.finditer(table):
        # not a header such as "FACTOR DE EVALUACIÓN OBLIGATORIO EN CASO DE USAR BIM"
        if not factor_name(m.group(2)) or HEADER.search(m.group(2)):
            continue
        before = [line for line in table[: m.start()].splitlines() if line.strip()]
        previous = max((s.start() for s in starts if s.start() < m.start()), default=None)
        # "A. EXPERIENCIA ESPECÍFICA / 40 PUNTOS / ADICIONAL DEL PERSONAL CLAVE" is one row, not two
        complete = previous is None or factor_name(table[previous: m.start()])
        if complete and (not before or ROW_BEFORE.search(before[-1])):
            starts.append(m)
    unique = {}
    for m in starts:  # a lettered row wins over the same line read as unlettered
        unique.setdefault(m.start(), m)
    starts = sorted(unique.values(), key=lambda m: m.start())
    rows = []
    carried = None
    for n, m in enumerate(starts):
        body = table[m.start(): starts[n + 1].start() if n + 1 < len(starts) else len(table)]
        # A page break inside the table brings footnotes and the page header; the name is in the first lines.
        lines = [line for line in body.splitlines() if line.strip()]
        # "A. EXPERIENCIA ESPECÍFICA" with "ADICIONAL DEL PERSONAL CLAVE" past a page break and its footnotes
        name = factor_name(lines[0]) or (SPECIFIC.search(lines[0]) and "Experiencia específica adicional del personal clave")
        if not name:
            kept = [line for line in lines if not FOOTNOTE.match(line)]
            name = factor_name(" ".join(kept[:3])) or factor_name(" ".join(kept[:12]))
        points = next((p for p in POINTS.finditer(body) if not glued_footnote(body, p)), None)
        figure = int(points.group(1)) if points else None
        # a table written one row a line whose points cell has no "puntos": "B. SOSTENIBILIDAD AMBIENTAL   5   COMITÉ"
        if figure is None and (bare := next((c for c in CELLS.split(lines[0].strip())[1:] if BARE.fullmatch(c)), None)):
            figure = int(BARE.fullmatch(bare).group(1))
        # "J. PLANIFICACIÓN DETALLADA  NO CORRESPONDE" with the next row's figure on the line below it
        not_used = NOT_USED.search(body)
        if not_used and points and not_used.start() < points.start():
            carried, figure = figure, None
        elif figure is None and carried is not None and not not_used:
            figure, carried = carried, None
        else:
            carried = None
        if name is None and figure is None:
            continue
        # a row OCR left without a readable name still counts in the sum
        rows.append({"letra": m.group(1), "factor": name or UNNAMED, "puntos": figure,
                     "no_corresponde": bool(not_used) and figure is None,
                     "plantilla": bool(TEMPLATE.search(body)) and figure is None,
                     "eleccion": bool(TEMPLATE.search(body)) and bool(not_used) and figure is not None,
                     "maximo": int(fixed.group(1)) if (fixed := TEMPLATE_FIGURE.search(body)) else None})
    return rows


def glued_footnote(body: str, points: re.Match) -> bool:
    """ "COMITÉ/JURADO24" with "puntos" on a line below: a footnote's number glued to the evaluator, not the figure."""
    start = points.start(1)
    return start > 0 and body[start - 1].isalpha() and "\n" in body[points.end(1): points.end()]


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
    result["total"] = int(total.group(1) or total.group(2))
    # a row the entity crossed out by hand, as a vision model marks it, gives no points
    table = STRUCK.sub("", text[table_end: total.start()])
    rows = [r for r in summary_rows(table) if not r["no_corresponde"]]
    described = described_points(before)
    # "[Como máximo 05]" without "puntos" is the factor's fixed figure when, with it, the table adds up to its total;
    # otherwise ("E. CAPACITACIÓN [Como máximo 10]" beside rows that already add up) the template left unfilled
    if (template := [r for r in rows if r["plantilla"]]) and all(r["maximo"] is not None for r in template):
        others = [r["puntos"] if r["puntos"] is not None else described.get(r["factor"])
                  for r in rows if not r["plantilla"]]
        if None not in others and sum(others) + sum(r["maximo"] for r in template) == result["total"] \
                and sum(others) != result["total"]:
            for r in template:
                r["puntos"], r["plantilla"] = r["maximo"], False
    # "C. SOSTENIBILIDAD SOCIAL [Como máximo 5] puntos / NO CORRESPONDE": both of the template's choices left;
    # the factor is left out when the table adds up to its total without it
    chosen = [r for r in rows if r["eleccion"]]
    rest = [r["puntos"] for r in rows if not r["eleccion"] and not r["plantilla"]]
    if not chosen or None in rest or sum(rest) != result["total"]:
        chosen = []
    # "E. CAPACITACIÓN [Como máximo 10]": the template's text left in the table, no points given
    if template := [r["factor"] for r in rows if r["plantilla"] or r in chosen]:
        result["avisos"].append({"aviso": "factor_sin_rellenar", "factores": template})
        rows = [r for r in rows if not r["plantilla"] and r not in chosen]
    # More figures in the table than rows read: a row lost its letter ("o INTEGRIDAD ..."), the sum would lie.
    figures = sum(1 for p in POINTS.finditer(table) if not glued_footnote(table, p))
    if figures > len(chosen) + sum(1 for r in rows if r["puntos"] is not None):
        result["revisar"] = UNREADABLE
        return result
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
    result = reading.read_files(files, read, NOT_FOUND, ocr, VALUES)
    if not result["ocr"] or result.get("ia") or result["revisar"]:
        return result
    # From Tesseract a sum that is not the total is nearly always a row it lost, and a description that differs
    # from a table adding up to the total a misread digit: not the entity's mistake. A vision model's text is
    # checked against Tesseract's reading instead.
    if any(w["aviso"] == "suma_distinta_total" for w in result["avisos"]):
        result["avisos"] = [w for w in result["avisos"] if w["aviso"] not in ("suma_distinta_total", "puntaje_distinto")]
        result["revisar"] = UNREADABLE
    else:
        result["avisos"] = [w for w in result["avisos"] if w["aviso"] != "puntaje_distinto"]
    return result
