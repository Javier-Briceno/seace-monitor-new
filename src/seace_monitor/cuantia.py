"""Section 1.4 of the bases: cuantía, límites of a limited economic offer, and what is wrong with them.

The type of economic offer (fija or limitada) is stated in chapter IV. A limited offer must lie
between 95 % and 110 % of the cuantía: the lower límite is rounded up to the cent, the upper one
cut at the cent. An entity that states another figure moves the range offers are judged by, so
any difference is a warning, also a single cent. When the bases and SEACE disagree on the
cuantía, the bases prevail.
"""

import re
from collections.abc import Callable
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from pathlib import Path

from .bases_text import TextError, is_scanned, page_of, text_of
from .ocr import OcrError

VERSION = "cuantia-2"

TITLE = re.compile(r"CUANT[IÍ]A\s+DE\s+LA\s+CONTRATACI[OÓ]N", re.I)
# Not the footnote of 1.4 ("indicada en esta sección"): it can fall between the cuantía and the límites table.
SECTION_END = re.compile(r"OBLIGACIONES|FUENTE\s+DE\s+FINANCIAMIENTO|\n\s*1\.5\b", re.I)
OPENING = re.compile(r"asciende|contrataci[oó]n\s+es\b", re.I)
# A number as entities write it: "3,522,447.65", "2´996,729.85", "2, 216, 331.39", "5,895 503.74", "1,111.161.86".
NUMBER = r"(\d[\d,.’'´ ]{0,22}?[.,]\d{2})(?!\d)"
AMOUNT = re.compile(r"S/\.?\s*" + NUMBER, re.I)
ANY_NUMBER = re.compile(NUMBER)
# The first number after the opening words, also when an extra "a" or the amount in words comes first.
FIRST_AMOUNT = re.compile(r"(?:asciende|contrataci[oó]n\s+es)[^\d\[]{0,250}?" + NUMBER, re.I | re.S)
LOWER = re.compile(r"L[IÍ]MITE\s+INFERIOR", re.I)
UPPER = re.compile(r"L[IÍ]MITE\s+SUPERIOR", re.I)
# The two headers of the límites table; the rounding rule names both límites in one sentence too.
TABLE_HEADER = re.compile(r"L[IÍ]MITE\s+INFERIOR(?:(?!decimal|tiene|L[IÍ]MITE).){0,200}?L[IÍ]MITE\s+SUPERIOR"
                          r"|L[IÍ]MITE\s+SUPERIOR(?:(?!decimal|tiene|L[IÍ]MITE).){0,200}?L[IÍ]MITE\s+INFERIOR", re.I | re.S)
CUANTIA_HEADER = re.compile(r"CUANT[IÍ]A\s+DE\s+LA|VALOR\s+REFERENCIAL", re.I)
WITH_IGV = re.compile(r"con\s+IGV", re.I)
WITHOUT_IGV = re.compile(r"sin\s+IGV", re.I)
PLACEHOLDER = "[CONSIGNAR"
UNFILLED = "sin rellenar"
# The amounts table of a diseño y construcción obra; its general rules ("Advertencia") also stay
# in many solo construcción bases, so the words alone say nothing.
DESIGN_AND_BUILD = re.compile(r"cuant[ií]a\s+del\s+componente", re.I)
# The budget table below the cuantía ("A. COMPONENTE DISEÑO ...") runs to 1.5, which a DOCX leaves unnumbered.
DESIGN_BUDGET = re.compile(r"COMPONENTE\s+(?:DE\s+)?DISE[ÑN]O", re.I)
BUDGET_END = re.compile(r"\n\s*1\.5\b|EXPEDIENTE\s+DE\s+CONTRATACI[OÓ]N", re.I)
TYPE = re.compile(r"presente\s+procedimiento\s+de\s+selecci[oó]n\s+es\s*:?(.{0,200})", re.I | re.S)
# The límites table sits right under its header; further down come the Amazonía table and the budget.
TABLE_LINES = 14
# Scanned files of one bases document that are OCRed in search of 1.4.
OCR_FILES = 2
# A límite this far from the cuantía is a misread column, not a figure an entity would write.
PLAUSIBLE = (Decimal("0.70"), Decimal("1.30"))

# Why a person has to read the section instead.
SCANNED = "escaneado"
NO_SECTION = "sin sección 1.4"
NO_AMOUNT = "1.4 sin monto legible"
DESIGN = "diseño y construcción: montos por componente"
TEMPLATE = "plantilla sin rellenar"
UNREADABLE_LIMITS = "cuadro de límites ilegible"


def money(text: str) -> Decimal:
    """The last separator before two digits is the decimal point; every other separator groups thousands."""
    digits = re.sub(r"[^\d.,]", "", text)
    return Decimal(re.sub(r"[.,]", "", digits[:-3]) + "." + digits[-2:])


def lower_limit(cuantia: Decimal) -> Decimal:
    return round(cuantia * Decimal("0.95"), 6).quantize(Decimal("0.01"), rounding=ROUND_CEILING)


def upper_limit(cuantia: Decimal) -> Decimal:
    return round(cuantia * Decimal("1.10"), 6).quantize(Decimal("0.01"), rounding=ROUND_FLOOR)


def section(text: str) -> tuple[int, str] | None:
    """Where 1.4 starts and its text: its title soon followed by 'asciende' or 'es' and an amount.

    The index and the general rules name the title too, but never with an amount after it.
    """
    for m in TITLE.finditer(text):
        after = text[m.end(): m.end() + 3500]
        if not OPENING.search(after[:700]):
            continue
        if not (FIRST_AMOUNT.search(after[:900]) or AMOUNT.search(after[:900]) or PLACEHOLDER in after[:900].upper()):
            continue
        end = SECTION_END.search(after)
        return m.start(), after[: end.start() if end else 3000]
    return None


def first_amount(block: str) -> Decimal | None:
    """The first number after the opening words, else the first S/ amount soon after them
    (the amount in words can come first and carry its own "69/100")."""
    m = FIRST_AMOUNT.search(block)
    if m:
        return money(m.group(1))
    opening = OPENING.search(block)
    if opening:
        m = AMOUNT.search(block[opening.end(): opening.end() + 350])
        if m:
            return money(m.group(1))
    return None


def offer_type(text: str) -> str:
    """'limitada', 'fija', UNFILLED when chapter IV kept the template's choice, or '' when it does not say."""
    for m in TYPE.finditer(text):
        words = m.group(1).upper()
        # A choice written before the template's brackets wins: "Fija [SEÑALAR ... FIJA O LIMITADA ...]".
        before = words.split("[")[0]
        for choice in ("LIMITADA", "FIJA"):
            if choice in before:
                return choice.lower()
        # Some fill the choice in and keep the brackets or the instruction: "[SEÑALAR ...: FIJA DE CONFORMIDAD ...]".
        if re.search(r"FIJA\s+O\s+LIMITADA", words):
            return UNFILLED
        if "LIMITADA" in words:
            return "limitada"
        if "FIJA" in words:
            return "fija"
    return ""


def limits_by_column(block: str) -> tuple[Decimal | None, Decimal | None] | None:
    """The first amount under each of the LÍMITE INFERIOR and LÍMITE SUPERIOR headers.

    None when no line carries both headers (a DOCX has no layout). An amount belongs to the
    header whose centre is nearest to its own; one left of the límites columns is the cuantía.
    """
    lines = block.splitlines()
    for i, line in enumerate(lines):
        low, high = LOWER.search(line), UPPER.search(line)
        if not (low and high and low.start() < high.start()):
            continue
        centres = {"low": centre_of(low), "high": centre_of(high)}
        # "Con IGV" and "Sin IGV" under each límite (Ley 27037): the límite is the con-IGV figure.
        sub = next((line for line in lines[i + 1: i + 3] if len(WITH_IGV.findall(line)) >= 2), None)
        if sub:
            with_igv = [centre_of(m) for m in WITH_IGV.finditer(sub)]
            centres = {"low": with_igv[0], "high": with_igv[1]}
            centres.update({f"sin{n}": centre_of(m) for n, m in enumerate(WITHOUT_IGV.finditer(sub))})
        # The cuantía column has its header on this line or the one above; an amount nearer to it is the cuantía.
        heading = next((CUANTIA_HEADER.search(h) for h in (line, lines[i - 1] if i else "") if CUANTIA_HEADER.search(h)), None)
        if heading:
            centres["cuantia"] = centre_of(heading)
        cuantia_edge = centres["low"] - (centres["high"] - centres["low"]) / 2 if not heading else -1
        found = {"low": None, "high": None}
        for below in lines[i + 1: i + 1 + TABLE_LINES]:
            if LOWER.search(below):
                break  # the next table
            for m in ANY_NUMBER.finditer(below):
                centre = centre_of(m)
                if centre < cuantia_edge:
                    continue
                column = min(centres, key=lambda c: abs(centres[c] - centre))
                if column in found and found[column] is None:
                    found[column] = money(m.group(1))
            if all(found.values()):
                break
        return found["low"], found["high"]
    return None


def squeeze(text: str) -> str:
    """Layout text pads columns with runs of spaces."""
    return re.sub(r"\s+", " ", text)


def centre_of(m: re.Match) -> float:
    return (m.start() + m.end()) / 2


def nearest(amounts: list[Decimal], target: Decimal, spread: Decimal) -> Decimal | None:
    close = [a for a in amounts if abs(a - target) <= spread]
    return min(close, key=lambda a: abs(a - target)) if close else None


def read_files(files: list[Path], valor_seace: Decimal | None = None,
               ocr: Callable[[Path], Path] | None = None) -> dict:
    """The reading of the first file that holds section 1.4; an archive also carries annexes and plans.

    A scanned file is read from its OCRed copy when `ocr` makes one; that reading says `ocr: true`.
    No file with 1.4 and a scanned file among them: the bases are that scan.
    """
    scanned, unreadable = [], []
    for path in files:
        try:
            text = text_of(path)
        except TextError as error:
            unreadable.append(f"{path.name}: {error}")
            continue
        if is_scanned(text):
            scanned.append(path)
            continue
        result = read(text, valor_seace)
        if result["revisar"] != NO_SECTION:
            return {**result, "archivo": path.name, "ocr": False}
    # OCR costs minutes per file: the files named as bases first, and only a few of an archive's scans.
    for path in sorted(scanned, key=lambda p: "BASE" not in p.name.upper())[:OCR_FILES if ocr else 0]:
        try:
            text = text_of(ocr(path))
        except (OcrError, TextError) as error:
            unreadable.append(f"{path.name}: {error}")
            continue
        result = read(text, valor_seace)
        if result["revisar"] != NO_SECTION:
            return {**result, "archivo": path.name, "ocr": True}
    result = {**read("", valor_seace), "ocr": False}
    result["archivo"] = scanned[0].name if scanned else ""
    if scanned:
        result["revisar"] = SCANNED
    elif unreadable:
        result["revisar"] = "ilegible: " + "; ".join(unreadable)[:300]
    elif not files:
        result["revisar"] = "sin PDF ni DOCX"
    return result


def read(text: str, valor_seace: Decimal | None = None) -> dict:
    """What section 1.4 and chapter IV say, the exact límites, and the warnings.

    `revisar` names why a person has to read the section; the other fields are then partial.
    """
    result = {"pagina": None, "cuantia": None, "tipo_oferta": offer_type(text), "limite_inferior": None,
              "limite_superior": None, "inferior_exacto": None, "superior_exacto": None, "valor_seace": None,
              "avisos": [], "revisar": None}
    if valor_seace is not None:
        result["valor_seace"] = str(valor_seace)
    found = section(text)
    if found is None:
        result["revisar"] = NO_SECTION
        return result
    start, block = found
    result["pagina"] = page_of(text, start)
    # Only in the cuantía sentence: a fixed-offer bases may leave the unused límites table unfilled.
    if PLACEHOLDER in block[:900].upper():
        result["revisar"] = TEMPLATE
        return result
    # A filled amounts table per component; the standard bases' empty one is a leftover.
    budget = text[start: start + 8000]
    end = BUDGET_END.search(budget, 200)
    budget = budget[: end.start() if end else len(budget)]
    windows = [squeeze(block[m.end(): m.end() + 1500])[:250] for m in DESIGN_AND_BUILD.finditer(block)]
    windows += [squeeze(budget[m.end(): m.end() + 1500])[:250] for m in DESIGN_BUDGET.finditer(budget)]
    if any(ANY_NUMBER.search(w) and PLACEHOLDER not in w.upper() for w in windows):
        result["revisar"] = DESIGN
        return result
    cuantia = first_amount(block)
    if cuantia is None:
        result["revisar"] = NO_AMOUNT
        return result
    result["cuantia"] = str(cuantia)
    warnings = result["avisos"]
    if valor_seace is not None and valor_seace != cuantia:
        warnings.append({"aviso": "cuantia_distinta_seace", "bases": str(cuantia), "seace": str(valor_seace)})

    # The standard bases' own table left with "[CONSIGNAR ...]" in it is no table.
    table = TABLE_HEADER.search(block)
    has_table = bool(table) and PLACEHOLDER not in block[table.start(): table.start() + 900].upper()
    if result["tipo_oferta"] == UNFILLED:
        warnings.append({"aviso": "tipo_oferta_sin_rellenar"})
    if result["tipo_oferta"] == "fija" and has_table:
        warnings.append({"aviso": "fija_con_limites"})
    if result["tipo_oferta"] == "limitada" and not has_table:
        warnings.append({"aviso": "limitada_sin_limites"})
    if not has_table:
        return result

    exact = {"inferior": lower_limit(cuantia), "superior": upper_limit(cuantia)}
    result["inferior_exacto"], result["superior_exacto"] = str(exact["inferior"]), str(exact["superior"])
    columns = limits_by_column(block)
    if columns is None or None in columns:
        amounts = [money(a) for a in ANY_NUMBER.findall(block)]
        spread = cuantia * Decimal("0.01")
        columns = (nearest(amounts, exact["inferior"], spread), nearest(amounts, exact["superior"], spread))
    for side, stated in zip(("inferior", "superior"), columns):
        if stated is None or not PLAUSIBLE[0] <= stated / cuantia <= PLAUSIBLE[1]:
            result["revisar"] = UNREADABLE_LIMITS
            continue
        result[f"limite_{side}"] = str(stated)
        if stated != exact[side]:
            warnings.append({"aviso": f"limite_{side}", "bases": str(stated), "exacto": str(exact[side])})
    return result
