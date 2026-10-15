"""Locate an obra from its description text.

SEACE descriptions of investment projects usually end with
"DISTRITO DE X, PROVINCIA DE Y, DEPARTAMENTO DE Z". A name after the word
DEPARTAMENTO (or REGION) is taken as certain. Only when no such marker exists
are bare mentions used, skipping names that follow a street prefix such as
"JR. LA LIBERTAD". Every departamento found is kept: a road can span two.
For municipalidades and gobiernos regionales see place().
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
# Entities that build where they sit; ministries and national programs build anywhere.
LOCAL_ENTITY = re.compile(r"^(?:municipalidad\s+(?:distrital|provincial|del\s+centro\s+poblado)|gobierno\s+regional)\b")


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


def place(descripcion: str, entidad: str, searched: str | None) -> tuple[list[str], str]:
    """Like locate(), but an obra of a municipalidad or gobierno regional without a marked departamento is placed
    in the departamento the search ran in, the entity's own.

    Measured on 1,813 such obras: a marked departamento named the searched one in 1,607 of 1,608 (the other a real
    obra elsewhere); bare mentions alone agreed in 81 of 85, the 4 others street or village names ("PJE. SAN
    MARTIN DE PORRES", "SANTA ROSA DE LIMA"); 120 named none.
    """
    found = locate(descripcion)
    if not LOCAL_ENTITY.search(normalize(entidad)) or not searched or searched not in DEPARTAMENTOS:
        return found
    if _MARKED.search(normalize(descripcion)) or found[0] == [searched]:
        return found
    return [searched], "entity"
