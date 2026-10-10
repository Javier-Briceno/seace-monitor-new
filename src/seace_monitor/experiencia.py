"""The requisito de calificación "Experiencia del postor en la especialidad" in chapter III of the bases.

The bases ask for a monto facturado acumulado, as an amount or as times the cuantía, earned in
obras of a especialidad and subespecialidades within a number of years, counted from the acta de
recepción or from the conformidad. Many bases carry chapter III as scanned pages; those are read
from the OCRed copy.
"""

import re
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path

from . import reading
from .bases_text import page_of
from .cuantia import ANY_NUMBER, money

VERSION = "experiencia-1"

# The requirement, not the scoring factor of chapter IV ("Experiencia adicional ... PUNTAJE").
REQUIREMENT = re.compile(r"EXPERIENCIA\s+DEL\s+POSTOR\s+EN\s+LA\s+ESPECIALIDAD(?:(?!PUNTAJE|Evaluaci[oó]n\s*:).){0,400}?"
                         r"Requisitos?\s*:", re.I | re.S)
END = re.compile(r"Acreditaci[oó]n\s*:", re.I)
MAX_BLOCK = 6000
AMOUNT_AFTER = re.compile(r"equivalente\s+a\s*(?:un\s+m[ií]nimo\s+de\s*)?(.{0,160})", re.I | re.S)
# "una (1) vez la cuantía", "2.5 VECES LA CUANTÍA", "[01 Una Vez La Cuantía ...]"
TIMES = re.compile(r"\b(\d+(?:[.,]\d+)?|una|dos|tres)\s*(?:\(\s*\d+\s*\))?\s*VE(?:CES|Z)\b", re.I)
TIMES_WORDS = {"una": "1", "dos": "2", "tres": "3"}
YEARS = re.compile(r"durante\s+(?:los\s+)?(?:[uú]ltimos\s+)?(\w+)\s*(?:\((\d+)\))?\s*a[ñn]os", re.I)
YEARS_WORDS = {"diez": 10, "quince": 15, "veinte": 20, "veinticinco": 25, "treinta": 30}
SPECIALTY = re.compile(r"^\s*Especialidad(?:es)?\s*:\s*(.+)$", re.I | re.M)
SUBSPECIALTY = re.compile(r"^\s*Sub\s*-?\s*especialidad(?:es)?\s*:\s*(.+)$", re.I | re.M)

NOT_FOUND = "sin requisito de experiencia del postor"
NO_AMOUNT = "experiencia sin monto legible"


def squeeze(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def years_of(block: str) -> int | None:
    m = YEARS.search(block)
    if not m:
        return None
    if m.group(2):
        return int(m.group(2))
    word = m.group(1).lower()
    return int(word) if word.isdigit() else YEARS_WORDS.get(word)


def read(text: str, cuantia: Decimal | None = None) -> dict:
    """What the requirement asks for; `veces_cuantia` relates the monto to the cuantía of 1.4."""
    result = {"pagina": None, "monto": None, "veces": None, "veces_cuantia": None, "anios": None,
              "cuenta_desde": None, "especialidad": None, "subespecialidades": None, "cita": None,
              "revisar": None}
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
    after = after.group(1) if after else block[:400]
    times = TIMES.search(after)
    if times:
        word = times.group(1).lower().replace(",", ".")
        result["veces"] = TIMES_WORDS.get(word, word)
        if cuantia is not None:
            result["monto"] = str((Decimal(result["veces"]) * cuantia).quantize(Decimal("0.01")))
    elif amount := ANY_NUMBER.search(after):
        result["monto"] = str(money(amount.group(1)))
    if result["monto"] is None and result["veces"] is None:
        result["revisar"] = NO_AMOUNT
    if result["monto"] and cuantia:
        result["veces_cuantia"] = str((Decimal(result["monto"]) / cuantia).quantize(Decimal("0.001")))

    result["anios"] = years_of(block)
    if re.search(r"acta\s+de\s+recepci", block, re.I):
        result["cuenta_desde"] = "acta de recepción"
    elif re.search(r"conformidad|comprobante\s+de\s+pago", block, re.I):
        result["cuenta_desde"] = "conformidad o comprobante de pago"
    if specialty := SPECIALTY.search(block):
        result["especialidad"] = squeeze(specialty.group(1))[:160]
    if sub := SUBSPECIALTY.search(block):
        result["subespecialidades"] = [s.strip() for s in re.split(r"\s*/\s*|\s*;\s*", squeeze(sub.group(1))) if s.strip()]
    return result


def read_files(files: list[Path], cuantia: Decimal | None = None,
               ocr: Callable[[Path, list[int]], Path] | None = None) -> dict:
    return reading.read_files(files, lambda text: read(text, cuantia), NOT_FOUND, ocr)
