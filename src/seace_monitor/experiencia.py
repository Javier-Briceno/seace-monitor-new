"""The requisito de calificación "Experiencia del postor en la especialidad" in chapter III of the bases.

The bases ask for a monto facturado acumulado, as an amount or as times the cuantía, earned in
obras of a especialidad and subespecialidades within a number of years, counted from the acta de
recepción or from the conformidad. Many bases carry chapter III as scanned pages; those are read
from the OCRed copy.
"""

import difflib
import re
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path

from . import letras, reading
from .bases_text import page_of
from .cuantia import ANY_NUMBER, money

VERSION = "experiencia-3"

# The requirement, not the scoring factor of chapter IV ("Experiencia adicional ... PUNTAJE"). OCR
# turns "Requisitos:" into "Reguisitos:" or "Regquisios:", or loses it; the sentence that follows stays.
# A title in quotes is chapter IV citing the requirement; "requisito" alone is any sentence.
REQUIREMENT = re.compile(r"EXPERIENCIA\s+DEL\s+POSTOR\s+EN\s+LA\s+ESPECIALIDAD(?![”\"])"
                         r"(?:(?!PUNTAJE|Evaluaci[oó]n\s*:).){0,400}?"
                         r"(?:\bRe\w{4,8}\s*:|\bRequisitos?[ \t]*\r?\n|(?=El\s+postor\s+debe\s+acreditar\s+un\s+monto))",
                         re.I | re.S)
# The requirement's own sentence; without it the block is OCR noise and no figure in it is the monto.
SENTENCE = re.compile(r"monto\s+factura|equivalen|acumulado", re.I)
END = re.compile(r"Acreditaci[oó]n\s*:", re.I)
MAX_BLOCK = 6000
AMOUNT_AFTER = re.compile(r"equivalente\s+a\s*(?:un\s+m[ií]nimo\s+de\s*)?(.{0,160})", re.I | re.S)
# "una (1) vez la cuantía", "2.5 VECES LA CUANTÍA", "[01 Una Vez La Cuantía ...]"
TIMES = re.compile(r"\b(\d+(?:[.,]\d+)?|una|dos|tres)\s*(?:\(\s*\d+\s*\))?\s*VE(?:CES|Z)\b", re.I)
TIMES_WORDS = {"una": "1", "dos": "2", "tres": "3"}
YEARS = re.compile(r"durante\s+(?:los\s+)?(?:[uú]ltimos\s+)?(\w+)\s*(?:\((\d+)\))?\s*a[ñn]os", re.I)
YEARS_WORDS = {"diez": 10, "quince": 15, "veinte": 20, "veinticinco": 25, "treinta": 30}
# The colon comes out of OCR as ". |", "|:" or "-"; "Especialidad" as "Espacialidad".
SEPARATOR = r"\s*[:|.\-–—]+[\s:|.+\-–—]*"
# A table without colon: "Especialidad          Represas, irrigaciones y afines"; never its header row
# ("Especialidad   Subespecialidad   Tipologías").
CELL = r"(?:" + SEPARATOR + r"|[ \t]{2,}(?-i:(?=[A-ZÁÉÍÓÚÑ])))(?!Sub\s*-?\s*esp|Tipolog)"
SPECIALTY = re.compile(r"^\s*Esp[ae]cialidad(?:es)?" + CELL + r"(\w.+)$", re.I | re.M)
SUBSPECIALTY = re.compile(r"^\s*Sub\s*-?\s*esp[ae]cialidad(?:es)?" + CELL + r"(?!Tipolog)(\w.+)$", re.I | re.M)

NOT_FOUND = "sin requisito de experiencia del postor"
NO_AMOUNT = "experiencia sin monto legible"
# Real bases ask from about half the cuantía up to three times it; a figure outside is a misread one (OCR).
PLAUSIBLE = (Decimal("0.25"), Decimal("3.0"))
DOUBTFUL = "monto de experiencia fuera de rango"


def squeeze(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def years_of(block: str) -> int | None:
    m = YEARS.search(block)
    if not m:
        return None
    if m.group(2):
        return int(m.group(2))
    word = m.group(1).lower()
    if word.isdigit():
        return int(word)
    # "veinficinco" from OCR
    close = difflib.get_close_matches(word, YEARS_WORDS, n=1, cutoff=0.8)
    return YEARS_WORDS[close[0]] if close else None


def read(text: str, cuantia: Decimal | None = None) -> dict:
    """What the requirement asks for; `veces_cuantia` relates the monto to the cuantía of 1.4."""
    result = {"pagina": None, "monto": None, "veces": None, "veces_cuantia": None, "anios": None,
              "cuenta_desde": None, "especialidad": None, "subespecialidades": None, "cita": None,
              "monto_letras": None, "monto_de_letras": False, "revisar": None}
    m = REQUIREMENT.search(text)
    if not m:
        result["revisar"] = NOT_FOUND
        return result
    end = END.search(text, m.end())
    block = text[m.end(): end.start() if end and end.start() - m.end() < MAX_BLOCK else m.end() + 3000]
    result["pagina"] = page_of(text, m.start())
    first = squeeze(block)
    result["cita"] = first[: first.find(".", 80) + 1 or 400][:500]

    after = AMOUNT_AFTER.search(block)
    after = after.group(1) if after else first[:400] if SENTENCE.search(first[:600]) else ""
    times = TIMES.search(after)
    if times:
        word = times.group(1).lower().replace(",", ".")
        result["veces"] = TIMES_WORDS.get(word, word)
        if cuantia is not None:
            result["monto"] = str((Decimal(result["veces"]) * cuantia).quantize(Decimal("0.01")))
    elif amount := ANY_NUMBER.search(after):
        result["monto"] = str(money(amount.group(1)))
        in_words = letras.check(after, amount.start(1), amount.end(1), money(amount.group(1)))
        if in_words is not None:
            result["monto_letras"] = str(in_words)
    elif in_words := letras.first_in_words(after):
        # "S/ 2476 757 90 (Dos millones cuatrocientos ...)": the digits are unreadable, the words are not
        result["monto"], result["monto_de_letras"] = str(in_words), True
    if result["monto"] is None and result["veces"] is None:
        result["revisar"] = NO_AMOUNT
    if result["monto"] and cuantia:
        result["veces_cuantia"] = str((Decimal(result["monto"]) / cuantia).quantize(Decimal("0.001")))
        if not PLAUSIBLE[0] <= Decimal(result["veces_cuantia"]) <= PLAUSIBLE[1]:
            result["revisar"] = DOUBTFUL

    result["anios"] = years_of(block)
    if re.search(r"acta\s+de\s+recepci", block, re.I):
        result["cuenta_desde"] = "acta de recepción"
    elif re.search(r"conformidad|comprobante\s+de\s+pago", block, re.I):
        result["cuenta_desde"] = "conformidad o comprobante de pago"
    if specialty := SPECIALTY.search(block):
        result["especialidad"] = squeeze(specialty.group(1)).rstrip(" |>]*")[:160]
    if sub := SUBSPECIALTY.search(block):
        result["subespecialidades"] = [s.strip() for s in re.split(r"\s*/\s*|\s*;\s*", squeeze(sub.group(1))) if s.strip()]
    return result


def read_files(files: list[Path], cuantia: Decimal | None = None,
               ocr: Callable[[Path, list[int]], Path] | None = None) -> dict:
    return reading.read_files(files, lambda text: read(text, cuantia), NOT_FOUND, ocr)
