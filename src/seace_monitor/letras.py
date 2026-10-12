"""Amounts written out in words, as the bases repeat every figure: "(UN MILLÓN SETENTA Y UN MIL ... CON 45/100 SOLES)".

Comparing the words with the digits catches digits misread by OCR and typos of the entity. Words that
cannot be parsed give None: no comparison, never a guess.
"""

import difflib
import re
import unicodedata
from decimal import Decimal

UNITS = {"cero": 0, "un": 1, "uno": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6, "siete": 7,
         "ocho": 8, "nueve": 9, "diez": 10, "once": 11, "doce": 12, "trece": 13, "catorce": 14, "quince": 15,
         "dieciseis": 16, "diecisiete": 17, "dieciocho": 18, "diecinueve": 19, "veinte": 20, "veintiun": 21,
         "veintiuno": 21, "veintiuna": 21, "veintidos": 22, "veintitres": 23, "veinticuatro": 24, "veinticinco": 25,
         "veintiseis": 26, "veintisiete": 27, "veintiocho": 28, "veintinueve": 29, "treinta": 30, "cuarenta": 40,
         "cincuenta": 50, "sesenta": 60, "setenta": 70, "ochenta": 80, "noventa": 90, "cien": 100, "ciento": 100,
         "doscientos": 200, "doscientas": 200, "trescientos": 300, "trescientas": 300, "cuatrocientos": 400,
         "cuatrocientas": 400, "quinientos": 500, "quinientas": 500, "seiscientos": 600, "seiscientas": 600,
         "setecientos": 700, "setecientas": 700, "ochocientos": 800, "ochocientas": 800, "novecientos": 900,
         "novecientas": 900}
SCALES = {"mil": 1000, "millon": 1_000_000, "millones": 1_000_000}
FILLER = {"y", "de", "soles", "sol", "nuevos", "son"}
WORDS = list(UNITS) + list(SCALES) + list(FILLER)
CENTS = re.compile(r"(\d{1,2})\s*/?\s*100\b")


def plain(text: str) -> str:
    text = unicodedata.normalize("NFD", text.lower())
    text = re.sub(r"(?<=[a-z])!(?=[a-z])", "i", text)  # OCR's "M!LLÓN"
    return "".join(c for c in text if unicodedata.category(c) != "Mn")


def known(word: str) -> str | None:
    """The number word OCR made this from ("sels" -> "seis", "mii" -> "mil"); None if it is none."""
    if word in UNITS or word in SCALES or word in FILLER:
        return word
    if len(word) < 3:
        return None
    scored = sorted(((difflib.SequenceMatcher(None, word, w).ratio(), w) for w in WORDS), reverse=True)
    (best, match), (second, other) = scored[0], scored[1]
    if best < (0.66 if len(word) == 3 else 0.75):
        return None
    # "siecientos" is as near to seiscientos as to setecientos: no guess
    if best - second < 0.05 and UNITS.get(match) != UNITS.get(other):
        return None
    return match


def integer(words: list[str]) -> int | None:
    total = group = 0
    smallest = None  # each number word of a group of three digits is smaller than the one before it
    seen = False
    for word in words:
        word = known(word)
        if word is None:
            return None
        if word in FILLER:
            continue
        seen = True
        if word in UNITS:
            if smallest is not None and UNITS[word] >= smallest:
                return None  # "ochenta y ocho doscientos": the bases dropped a "mil", no guess
            group += UNITS[word]
            smallest = UNITS[word]
        elif word == "mil":
            if group >= 1000:
                return None  # "seiscientos noventa y cinco mil" after a thousand already: a typo, no guess
            group = (group or 1) * 1000
            smallest = None
        else:
            total += (group or 1) * 1_000_000
            group = 0
            smallest = None
    return total + group if seen else None


def parts(text: str) -> tuple[int, int | None] | None:
    """Soles and céntimos the words state; céntimos None when they cannot be read ("con 801 00")."""
    text = plain(text)
    # "Dos cientos", "SEIS CIENTOS", "VEINTI CUATRO"; "TREINTAYCINCO", "Treintaicuatro"
    text = re.sub(r"\b(dos|tres|cuatro|seis|sete|ocho|nove)\s+cient", r"\1cient", text)
    text = re.sub(r"\bveinti\s+(?=[a-z])", "veinti", text)
    text = re.sub(r"\b(treinta|cuarenta|cincuenta|sesenta|setenta|ochenta|noventa)[yi](?=[a-z])", r"\1 y ", text)
    hundredths = None
    if cents := CENTS.search(text):
        # "... CON 45/100", "... Y 66/100", "... CON CUARENTA Y CINCO 45/100", OCR's "con 42100"
        head = text[: cents.start()]
        joins = list(re.finditer(r"\bcon\b", head))
        whole = head[: joins[-1].start()] if joins else re.sub(r"\by\s*$", "", head.strip())
        hundredths = int(cents.group(1))
    else:
        whole = re.split(r"\bcon\b|\bsoles\b", text)[0]
    value = integer(re.findall(r"[a-z]+", whole))
    return None if value is None else (value, hundredths)


def amount_in_words(text: str) -> Decimal | None:
    """'cuatro millones ochocientos veintinueve mil ciento treinta con 42/100 soles' -> 4829130.42"""
    found = parts(text)
    return None if found is None else Decimal(found[0]) + Decimal(found[1] or 0) / 100


def words_around(text: str, start: int, end: int) -> str | None:
    """The words that repeat the amount at text[start:end]: in parentheses right after it, or before it
    when the amount itself is in parentheses ("la suma de doscientos ... con 69/100 soles (S/ 266,817.69)")."""
    # "(cuatrocientos ] cincuenta ...)": OCR leaves stray brackets inside the parentheses
    after = re.match(r"\s*\)?\s*(?:\(\s*([^()]{8,300}?)\s*\)|\[\s*([^\[\]]{8,300}?)\s*\])", text[end: end + 320])
    if after:
        words = after.group(1) or after.group(2)
        if re.search(r"[a-zA-Z]{3}", words) and not re.match(r"\s*incluid", words, re.I):
            return words
    before = text[max(0, start - 320): start]
    opening = before.rfind("(")
    if opening != -1 and re.fullmatch(r"\(\s*(?:S/\.?|S\s*/)?\s*", before[opening:], re.I):
        anchor = list(re.finditer(r"(?:suma\s+de|equivalente\s+a|asciende\s+a)\s+", before[:opening], re.I))
        if anchor:
            return before[anchor[-1].end(): opening]
    return None


def first_in_words(text: str) -> Decimal | None:
    """The first amount written in words in parentheses, for a figure whose digits cannot be read."""
    for m in re.finditer(r"\(([^()]{8,300})\)", text):
        found = parts(m.group(1))
        if found is not None and found[0] >= 1000:
            return (Decimal(found[0]) + Decimal(found[1] or 0) / 100).quantize(Decimal("0.01"))
    return None


def check(text: str, start: int, end: int, amount: Decimal) -> Decimal | None:
    """The amount the words state, when it differs from the digits; None when they agree or cannot be read."""
    words = words_around(text, start, end)
    found = parts(words) if words else None
    if found is None:
        return None
    soles, cents = found
    if cents is None:
        return Decimal(soles) if soles != int(amount) else None
    stated = Decimal(soles) + Decimal(cents) / 100
    return stated if stated != amount else None
