"""Section 1.3 "Objeto de la convocatoria" of the bases: the obra's full name and its CUI.

SEACE cuts its description at 300 characters; the bases name the obra in full, usually in quotes after
"tiene por objeto la contratación de la ejecución de la obra", followed by its CUI (código único de
inversiones). What follows the name can be a template note ("Importante para la entidad") or the next
section, so the name ends at its closing quote or at the CUI.
"""

import re
from collections.abc import Callable
from pathlib import Path

from . import reading
from .bases_text import page_of

VERSION = "objeto-1"

HEADING = re.compile(r"objeto\s+de\s+la\s+convocatoria", re.I)
# Where the section ends when the obra's name has no closing quote.
END = re.compile(r"\n\s*1\.4\b|\bcuant[ií]a\s+de\s+la\s+contrataci|importante\s+para\s+la\s+entidad", re.I)
# Quote pairs; a bracket is the template's placeholder, used only when no quote is there.
CLOSE = {"«": "»", "“": "”", '"': '"', "„": "“", "[": "]"}
STRIP = " ,;:-\"'«»“”[]�"
CUI = re.compile(r"\b(?:C\.?\s?U\.?\s?I\.?|c[oó]digo\s+[uú]nico\s+de\s+inversi[oó]n(?:es)?)\s*(?:N\s*[°º.o*]*\s*)?:?\s*(\d{7})\b",
                 re.I)
MAX_BLOCK = 2500
# The page's running header printed beside the text ("...SERVICIOS      LICITACIÓN PÚBLICA PARA OBRAS"):
# in the layout text it sits after a wide gap.
BESIDE = re.compile(r"[ \t]{4,}(?=[^\n]*(?:LICITACI|BASES\s|SECCI[OÓ]N|CONCURSO|ADJUDICACI))[^\n]*", re.I)

NOT_FOUND = "sin sección 1.3"
NO_NAME = "1.3 sin nombre de obra legible"


def squeeze(text: str) -> str:
    return " ".join(text.split())


def read(text: str) -> dict:
    result = {"pagina": None, "obra": None, "cui": None, "texto": None, "revisar": None}
    for m in HEADING.finditer(text):
        rest = text[m.end(): m.end() + MAX_BLOCK]
        start = re.search(r"tiene\s+por\s+objeto", rest, re.I)
        if start:
            break
    else:
        result["revisar"] = NOT_FOUND
        return result
    # the page of the sentence itself: a table of contents can name the heading just before the section
    result["pagina"] = page_of(text, m.end() + start.start())
    body = BESIDE.sub("", rest[start.start():])
    end = END.search(body)
    body = body[: end.start()] if end else body
    if cui := CUI.search(body):
        result["cui"] = cui.group(1)
    name = quoted(body)
    if name is None and cui:
        # "... la ejecución de la obra: MEJORAMIENTO ... DEPARTAMENTO DE ANCASH, con CUI 2724989"
        after = re.search(r"(?:obra|ioarr)\s*(?:correspondiente\s*(?:a\s*(?:la)?)?)?\s*:?", body[: cui.start()], re.I)
        if after:
            name = squeeze(body[after.end(): cui.start()]).strip(STRIP)
            name = re.sub(r",?\s*con$", "", name, flags=re.I).strip(STRIP) or None
    if name and (inside := CUI.search(name)):
        # "... DEPARTAMENTO ANCASH. CON CUI: 2693255" inside the quotes
        name = re.sub(r"[\s,.;:-]*(?:con\s*)?$", "", name[: inside.start()], flags=re.I).strip(STRIP)
    result["obra"] = name
    result["texto"] = squeeze(body)[:1500]
    if not name or len(name) < 15:
        result["obra"], result["revisar"] = None, NO_NAME
    return result


def quoted(body: str) -> str | None:
    """The text between the first quote and its own closing quote, in one line; a bracket only without quotes."""
    found = []
    for opening, closing in CLOSE.items():
        start = body.find(opening)
        end = body.find(closing, start + 1) if start >= 0 else -1
        if end > start + 15:
            found.append((opening == "[", start, end))
    if not found:
        return None
    bracket, start, end = min(found)
    inner = body[start + 1: end]
    if bracket and (q := quoted(inner)):  # "[Ejecución de la IOARR “Renovación ...”, con CUI ...]"
        return q
    return squeeze(inner).strip(STRIP)


def read_files(files: list[Path], descripcion: str | None = None,
               ocr: Callable[[Path, list[int]], Path] | None = None) -> dict:
    """With SEACE's description: a CUI there that is not the bases' one is a question for the entity."""
    result = reading.read_files(files, read, NOT_FOUND, ocr)
    result["avisos"] = []
    # A paquete names several CUIs: "CUI N° 2556200, N° 2721620, N° 2683978 Y N° 2709843".
    seace = re.findall(r"\b(\d{7})\b", descripcion[CUI.search(descripcion).start():]) \
        if descripcion and CUI.search(descripcion) else []
    if result.get("cui") and seace and result["cui"] not in seace:
        result["avisos"].append({"aviso": "cui_distinto_seace", "bases": result["cui"], "seace": seace[0]})
    return result
