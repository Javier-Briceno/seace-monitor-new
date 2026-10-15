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
# Older bases call 1.4 "valor referencial".
END = re.compile(r"\n\s*1\.4\b|\bcuant[ií]a\s+de\s+la\s+contrataci|\bvalor\s+referencial\b|importante\s+para\s+la\s+entidad",
                 re.I)
# Quote pairs; a bracket is the template's placeholder, used only when no quote is there.
CLOSE = {"«": "»", "“": "”", '"': '"', "„": "“", "�": "�", "[": "]"}  # �: a quote the text lost
# Footer and header lines of a bases page: the entity, the procedure, the page number.
EDGE = re.compile(r"LICITACI|MUNICIPALIDAD|GOBIERNO\s+REGIONAL|BASES\s+(?:INTEGRADAS|EST[AÁ]NDAR|ADMINISTRATIVAS)"
                  r"|P[aá]gina\s+\d|^\s*\d{1,3}\s*$", re.I)
STRIP = " ,;:-–—\"'«»“”‘’[]�"
# "CUI N° 2719000", "Código Único de Inversiones N°2724989", "CODIGO UNICO 2720300", "COD. UNICO N*2725321"
CUI = re.compile(r"\b(?:C\.?\s?U\.?\s?I\.?|c[oó]d(?:igo|\.)\s*[uú]nico(?:\s+de\s+inversi[oó]n(?:es)?)?)"
                 r"\s*(?:N\s*[°º.o*]*\s*)?:?\s*(\d{7})\b", re.I)
CUI_WORD = re.compile(r"\b(?:C\.?\s?U\.?\s?I\b|c[oó]d(?:igo|\.)\s*[uú]nico)", re.I)
MAX_BLOCK = 2500
# The words that open the obra's name, and how far after them its quote may open.
INTRO = re.compile(r"\b(?:obra|ioarr|inversi[oó]n)\b(?:\s*(?:denominada|correspondiente))?(?:\s*a(?:l|\s+la)?\b)?\s*:?", re.I)
NEAR = 40
MAX_NAME = 800
# The page's running header printed beside the text ("...SERVICIOS      LICITACIÓN PÚBLICA PARA OBRAS"):
# in the layout text it sits after a wide gap.
BESIDE = re.compile(r"[ \t]{4,}(?=[^\n]*(?:LICITACI|BASES\s|SECCI[OÓ]N|CONCURSO|ADJUDICACI))[^\n]*", re.I)

NOT_FOUND = "sin sección 1.3"
NO_NAME = "1.3 sin nombre de obra legible"


def squeeze(text: str) -> str:
    return " ".join(text.split())


def without_page_edges(text: str) -> str:
    """A name that runs onto the next page loses the footer and header lines around the page break."""
    pages = text.split("\f")
    for i, page in enumerate(pages):
        lines = page.split("\n")
        if i > 0:
            while lines and (not lines[0].strip() or EDGE.search(lines[0])):
                lines.pop(0)
        if i < len(pages) - 1:
            while lines and (not lines[-1].strip() or EDGE.search(lines[-1])):
                lines.pop()
        pages[i] = "\n".join(lines)
    return "\n".join(pages)


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
    body = without_page_edges(BESIDE.sub("", rest[start.start():]))
    end = END.search(body)
    body = body[: end.start()] if end else body
    if cui := CUI.search(body):
        result["cui"] = cui.group(1)
    name = None
    intros = list(INTRO.finditer(body))
    found = quoted(body)
    if found:
        # The quote must open right after "la obra"; one further on is a name inside the obra's own name:
        # "la obra: MEJORAMIENTO ... EN LA I.E. "SAN MARTIN DE PORRES", DISTRITO DE PATAZ"
        before = [i for i in intros if i.end() <= found[0]]
        if not intros or (before and found[0] - before[-1].end() <= NEAR):
            name = found[1]
    if name is None and intros:
        # "la obra correspondiente a: CONTRATACIÓN DEL PAQUETE 5 PARA LA EJECUCIÓN DE LA OBRA IOARR: REMODELACION ...,
        # con CUI 2724989": the name starts after the last such words before the CUI
        stop = cui.start() if cui else len(body)
        lead = [i for i in intros if i.end() <= stop] or intros
        start = lead[-1].end()
        name = squeeze(body[start: min(stop, start + MAX_NAME)]).strip(STRIP)
        name = re.sub(r",?\s*con$", "", name, flags=re.I).strip(STRIP) or None
    if name and (inside := CUI.search(name)):
        # "... DEPARTAMENTO ANCASH. CON CUI: 2693255" inside the quotes
        name = re.sub(r"[\s,.;:-]*(?:con\s*)?$", "", name[: inside.start()], flags=re.I).strip(STRIP)
    result["obra"] = name
    result["texto"] = squeeze(body)[:1500]
    if not name or len(name) < 15:
        result["obra"], result["revisar"] = None, NO_NAME
    return result


def quoted(body: str) -> tuple[int, str] | None:
    """Where the first quote opens and the text up to its own closing quote, in one line; a bracket only
    without quotes.

    A straight quote closes with the same mark, so a school's name in quotes inside the obra's name would close
    it early ("... I.E. "SAN MARTIN DE PORRES", DISTRITO ..."): it closes at the last such mark before the CUI.
    """
    found = []
    cui = CUI_WORD.search(body)  # even when OCR garbled its number ("CUI N22727736")
    limit = cui.start() if cui else len(body)
    for opening, closing in CLOSE.items():
        start = body.find(opening)
        if start < 0:
            continue
        end = body.rfind(closing, start + 1, limit) if opening == closing else -1
        if end <= start + 15:  # a pair of its own, or the CUI sits inside the quotes
            end = body.find(closing, start + 1)
        if end > start + 15:
            found.append((opening == "[", start, end))
    if not found:
        return None
    bracket, start, end = min(found)
    inner = body[start + 1: end]
    if bracket and (q := quoted(inner)):  # "[Ejecución de la IOARR “Renovación ...”, con CUI ...]"
        return start + 1 + q[0], q[1]
    return start, squeeze(inner).strip(STRIP)


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
