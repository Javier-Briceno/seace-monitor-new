"""Read the list of documents from a convocatoria's ficha.

The ficha only opens from a search: its button posts the search form with the
row's own parameters and the ViewState of that search, and SEACE redirects to
a page tied to the session. Opened later in another session it comes back empty.
"""

import re
from datetime import datetime

import requests

from .search import BASE, FORM, LIMA, SearchResult, access_error, cell_text, normalize

COLUMNS = {
    "etapa": "etapa",
    "tipo": "documento",
    "archivo": "archivo",
    "publicado_en": "fecha y hora de publicacion",
}
DOWNLOAD_LINK = re.compile(r"descargaDocGeneral\('([^']+)','([^']+)','([^']+)'\)")


class FichaError(Exception):
    pass


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


def parse_documents(page: str) -> list[dict]:
    body = page.find("tbFicha:dtDocumentos_data")
    if body < 0:
        raise FichaError("document table missing from the ficha")
    table = page[page.rfind("<table", 0, body) : page.index("</table>", body)]

    headers = [normalize(cell_text(th)) for th in re.findall(r"<th[^>]*>(.*?)</th>", table, re.S)]
    index = {}
    for key, header in COLUMNS.items():
        if header not in headers:
            raise FichaError(f"document column {header!r} missing; the ficha changed")
        index[key] = headers.index(header)

    documents = []
    for raw in re.findall(r"<tr[^>]*data-ri[^>]*>(.*?)</tr>", table, re.S):
        cells = re.findall(r"<td[^>]*>(.*?)</td>", raw, re.S)
        link = DOWNLOAD_LINK.search(cells[index["archivo"]])
        if not link:
            raise FichaError(f"document without download link: {cell_text(cells[index['tipo']])}")
        uuid, _, nombre = link.groups()
        fecha = cell_text(cells[index["publicado_en"]])
        documents.append({
            "uuid": uuid,
            "etapa": cell_text(cells[index["etapa"]]),
            "tipo": cell_text(cells[index["tipo"]]),
            "nombre_archivo": nombre,
            "publicado_en": datetime.strptime(fecha, "%d/%m/%Y %H:%M").replace(tzinfo=LIMA) if fecha else None,
        })
    return documents


def parse_deadline(page: str) -> datetime | None:
    """End of the offer stage in the ficha's cronograma, or None if the ficha has no such stage.

    The stage is matched without its accent, which some pages send broken.
    """
    body = page.find("tbFicha:dtCronograma_data")
    if body < 0:
        raise FichaError("cronograma missing from the ficha")
    table = page[body : page.index("</tbody>", body)]
    for raw in re.findall(r"<tr[^>]*data-ri[^>]*>(.*?)</tr>", table, re.S):
        cells = [cell_text(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", raw, re.S)]
        if len(cells) < 3 or not re.match(r"presentaci\S* de (propuestas|ofertas)", normalize(cells[0])):
            continue
        end = cells[2]
        if re.fullmatch(r"\d\d/\d\d/\d{4}", end):  # a date without time lasts until the end of the day
            end += " 23:59"
        return datetime.strptime(end, "%d/%m/%Y %H:%M").replace(tzinfo=LIMA)
    return None


def has_bases(documents: list[dict]) -> bool:
    return any("bases" in normalize(d["tipo"]) for d in documents)
