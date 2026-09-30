"""Locate an obra from its description text.

SEACE descriptions of investment projects usually end with
"DISTRITO DE X, PROVINCIA DE Y, DEPARTAMENTO DE Z". A name after the word
DEPARTAMENTO (or REGION) is taken as certain. Only when no such marker exists
are bare mentions used, skipping names that follow a street prefix such as
"JR. LA LIBERTAD". Every departamento found is kept: a road can span two.
"""

import re

from .search import normalize

DEPARTAMENTOS = (
    "AMAZONAS", "ANCASH", "APURIMAC", "AREQUIPA", "AYACUCHO", "CAJAMARCA",
    "CALLAO", "CUSCO", "HUANCAVELICA", "HUANUCO", "ICA", "JUNIN", "LA LIBERTAD",
    "LAMBAYEQUE", "LIMA", "LORETO", "MADRE DE DIOS", "MOQUEGUA", "PASCO",
    "PIURA", "PUNO", "SAN MARTIN", "TACNA", "TUMBES", "UCAYALI",
)

_NAMES = "|".join(re.escape(d.lower()) for d in sorted(DEPARTAMENTOS, key=len, reverse=True))
_MARKED = re.compile(rf"\b(?:departamento|region)\s+(?:de\s+|del\s+)?({_NAMES})\b")
_BARE = re.compile(rf"\b({_NAMES})\b")
_STREET_BEFORE = re.compile(r"\b(?:jr|jiron|av|avenida|calle|ca|psje|pasaje|urb|urbanizacion)\.?\s*$")


def locate(descripcion: str) -> tuple[list[str], str]:
    """Return (departamentos, ubicacion_fuente) for the schema columns."""
    text = normalize(descripcion)
    found = [m.group(1) for m in _MARKED.finditer(text)]
    if not found:
        found = [
            m.group(1) for m in _BARE.finditer(text)
            if not _STREET_BEFORE.search(text[: m.start()])
        ]
    departamentos = sorted({name.upper() for name in found})
    return departamentos, "text" if departamentos else "unknown"
