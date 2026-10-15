"""Read the list of documents from a convocatoria's ficha.

The ficha only opens from a search: its button posts the search form with the
row's own parameters and the ViewState of that search, and SEACE redirects to
a page tied to the session. Opened later in another session it comes back empty.
"""

import re
from datetime import datetime

import requests

from .search import AJAX_HEADERS, BASE, FORM, LIMA, SearchResult, access_error, cell_text, normalize, parse_viewstate

FICHA_FORM = "tbFicha:idFormFichaSeleccion"
DOCUMENT_TABLE = "tbFicha:dtDocumentos"
DOCUMENT_PAGINATOR = re.compile(r'id:"tbFicha:dtDocumentos",paginator:\{[^}]*?rows:(\d+),rowCount:(\d+)')
COLUMNS = {
    "etapa": "etapa",
    "tipo": "documento",
    "archivo": "archivo",
    "publicado_en": "fecha y hora de publicacion",
}
ITEM_ESTADO = re.compile(r"Estado:</span></td>\s*<td>(.*?)</td>", re.S)
# The file name runs to the end of the call: names can hold an apostrophe ("OBRA S'.pdf").
DOWNLOAD_LINK = re.compile(r"descargaDocGeneral\('([^']+)','([^']+)','(.+?)'\);")


class FichaError(Exception):
    pass


class CronogramaError(FichaError):
    """The cronograma table is there but cannot be trusted; the stored one is kept."""


class StaleTable(FichaError):
    """The portal answered with the document table of a ficha paged earlier in this session."""


def open_ficha(session: requests.Session, result: SearchResult, row: dict) -> str:
    if not row.get("ficha_params"):
        raise FichaError("the result row has no ficha button")
    data = dict(result.form.fields)
    data.update(row["ficha_params"])
    data["javax.faces.ViewState"] = result.viewstate
    data[FORM] = FORM
    try:
        response = session.post(BASE + result.form.action, data=data, timeout=60)
        response.raise_for_status()
    except requests.RequestException as error:
        raise access_error(session, error) or FichaError(f"ficha request failed: {error}") from error
    response.encoding = "utf-8"
    if normalize(row["nomenclatura"]) not in normalize(cell_text(response.text)):
        raise FichaError("the ficha does not show this convocatoria's nomenclatura")
    return response.text


def read_documents(session: requests.Session, page: str) -> list[dict]:
    """Every document of the ficha, also those on the table's further pages.

    The table shows a few rows per page; the rest are asked for in the same session.
    The portal can answer a ficha's page requests with the table of a ficha paged
    earlier in the same session, so the first page is asked for again and
    must match the ficha's own, else StaleTable. Fewer rows than the ficha counts
    is an error, so the ficha is read again instead of being stored with documents missing.
    """
    paginator = DOCUMENT_PAGINATOR.search(page)
    if not paginator:
        raise FichaError("document count missing from the ficha")
    per_page, total = int(paginator.group(1)), int(paginator.group(2))
    index = document_columns(page)
    documents = parse_documents(page)
    if len(documents) < total:
        action = re.search(rf'<form id="{FICHA_FORM}"[^>]*action="([^"]+)"', page)
        viewstate = re.search(r'name="javax.faces.ViewState"[^>]*value="([^"]+)"', page)
        if not action or not viewstate:
            raise FichaError("the ficha has no form to ask for further document pages")
        action, viewstate = action.group(1), viewstate.group(1)
        check = document_page(session, action, viewstate, 0, per_page)
        if answer_rows(check, index) != documents:
            raise StaleTable("the document table answered belongs to another ficha")
        viewstate = parse_viewstate(check) or viewstate
    while len(documents) < total:
        answer = document_page(session, action, viewstate, len(documents), per_page)
        more = answer_rows(answer, index)
        if not more:
            break
        documents += more
        viewstate = parse_viewstate(answer) or viewstate
    if len(documents) != total:
        raise FichaError(f"read {len(documents)} of {total} documents")
    return documents


def document_page(session: requests.Session, action: str, viewstate: str, first: int, rows: int) -> str:
    try:
        response = session.post(BASE + action, headers=AJAX_HEADERS, timeout=60, data={
            FICHA_FORM: FICHA_FORM,
            "javax.faces.ViewState": viewstate,
            "javax.faces.partial.ajax": "true",
            "javax.faces.source": DOCUMENT_TABLE,
            "javax.faces.partial.execute": DOCUMENT_TABLE,
            "javax.faces.partial.render": DOCUMENT_TABLE,
            "javax.faces.behavior.event": "page",
            "javax.faces.partial.event": "page",
            f"{DOCUMENT_TABLE}_pagination": "true",
            f"{DOCUMENT_TABLE}_first": str(first),
            f"{DOCUMENT_TABLE}_rows": str(rows),
            f"{DOCUMENT_TABLE}_encodeFeature": "true",
        })
        response.raise_for_status()
    except requests.RequestException as error:
        raise access_error(session, error) or FichaError(f"document page request failed: {error}") from error
    response.encoding = "utf-8"
    return response.text


def answer_rows(answer: str, index: dict[str, int]) -> list[dict]:
    rows = re.search(rf'<update id="{DOCUMENT_TABLE}"><!\[CDATA\[(.*?)\]\]></update>', answer, re.S)
    return document_rows(rows.group(1) if rows else "", index)


def document_table(page: str) -> str:
    body = page.find("tbFicha:dtDocumentos_data")
    if body < 0:
        raise FichaError("document table missing from the ficha")
    return page[page.rfind("<table", 0, body) : page.index("</table>", body)]


def document_columns(page: str) -> dict[str, int]:
    table = document_table(page)
    headers = [normalize(cell_text(th)) for th in re.findall(r"<th[^>]*>(.*?)</th>", table, re.S)]
    index = {}
    for key, header in COLUMNS.items():
        if header not in headers:
            raise FichaError(f"document column {header!r} missing; the ficha changed")
        index[key] = headers.index(header)
    return index


def parse_documents(page: str) -> list[dict]:
    """The documents on the ficha's first page of the table."""
    return document_rows(document_table(page), document_columns(page))


def document_rows(table: str, index: dict[str, int]) -> list[dict]:
    documents = []
    for raw in re.findall(r"<tr[^>]*data-ri[^>]*>(.*?)</tr>", table, re.S):
        cells = re.findall(r"<td[^>]*>(.*?)</td>", raw, re.S)
        # A row without link is kept: the entity listed it, but there is nothing to download.
        link = DOWNLOAD_LINK.search(cells[index["archivo"]])
        uuid, _, nombre = link.groups() if link else (None, None, cell_text(cells[index["archivo"]]))
        fecha = cell_text(cells[index["publicado_en"]])
        documents.append({
            "uuid": uuid,
            "etapa": cell_text(cells[index["etapa"]]),
            "tipo": cell_text(cells[index["tipo"]]),
            "nombre_archivo": nombre,
            "publicado_en": datetime.strptime(fecha, "%d/%m/%Y %H:%M").replace(tzinfo=LIMA) if fecha else None,
        })
    return documents


def parse_cronograma(page: str) -> list[dict]:
    """Every stage of the ficha's cronograma in order, with inicio and fin written as the ficha writes them.

    Under the stage name the ficha sometimes adds where it takes place ("SEACE" or an office address).
    Storing it replaces the old stages, so a row that is not a stage, a repeated stage name or rows that
    vanish without the portal's empty-table message stop it here.
    """
    body = page.find("tbFicha:dtCronograma_data")
    if body < 0:
        raise FichaError("cronograma missing from the ficha")
    table = page[body : page.index("</tbody>", body)]
    stages = []
    for raw in re.findall(r"<tr[^>]*data-ri[^>]*>(.*?)</tr>", table, re.S):
        cells = re.findall(r"<td[^>]*>(.*?)</td>", raw, re.S)
        if len(cells) < 3:
            raise CronogramaError(f"cronograma row with {len(cells)} cells")
        name, _, place = cells[0].partition("<br")
        stages.append({
            "etapa": cell_text(name),
            "lugar": cell_text(place.partition(">")[2]) or None,
            "inicio": cell_text(cells[1]) or None,
            "fin": cell_text(cells[2]) or None,
        })
    names = [s["etapa"] for s in stages]
    if not all(names) or len(set(names)) < len(names):
        raise CronogramaError("cronograma stage without a name or named twice")
    if not stages and "ui-datatable-empty-message" not in table:
        raise CronogramaError("cronograma without rows and without the empty-table message")
    return stages


def is_offer_stage(stage: dict) -> bool:
    """Matched without its accent, which some pages send broken."""
    return bool(re.match(r"presentaci\S* de (propuestas|ofertas)", normalize(stage["etapa"])))


def offer_deadline(stages: list[dict]) -> datetime | None:
    """End of the offer stage, or None if the cronograma has no such stage."""
    for stage in stages:
        if not is_offer_stage(stage) or not stage["fin"]:
            continue
        end = stage["fin"]
        if re.fullmatch(r"\d\d/\d\d/\d{4}", end):  # a date without time lasts until the end of the day
            end += " 23:59"
        return datetime.strptime(end, "%d/%m/%Y %H:%M").replace(tzinfo=LIMA)
    return None


def parse_estados(page: str) -> list[str]:
    """Estado of each item, in the order the ficha lists the items."""
    estados = [cell_text(e) for e in ITEM_ESTADO.findall(page)]
    if not estados or not all(estados):
        raise FichaError("item estado missing from the ficha")
    return estados


def has_bases(documents: list[dict]) -> bool:
    """A bases without download link does not count, so its ficha is read again."""
    return any("bases" in normalize(d["tipo"]) and d["uuid"] for d in documents)
