"""Search SEACE's public buscador (prod2) with plain HTTP requests.

The portal blocks non-Peruvian IPs, so requests must leave through a Peruvian
exit (VPN). Query values are given as the labels the portal shows and are
resolved to option codes on every page load.
"""

import html
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

import requests

BASE = "https://prod2.seace.gob.pe"
PAGE = BASE + "/seacebus-uiwd-pub/buscadorPublico/buscadorPublico.xhtml"
FORM = "tbBuscador:idFormBuscarProceso"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"
)
LIMA = timezone(timedelta(hours=-5))  # Peru has no daylight saving time

# Some selects have generated ids (j_idtNNN) that change between renders,
# so they are found by an option only they contain.
SELECTS = {
    "objeto": {"anchor": "Consultoría de Obra"},
    "version_seace": {"anchor": "Seace 2"},
    "departamento": {"name": f"{FORM}:departamento_input"},
    "anio": {"name": f"{FORM}:anioConvocatoria_input"},
}

COLUMNS = {
    "entidad": "nombre o sigla de la entidad",
    "fecha_publicacion": "fecha y hora de publicacion",
    "nomenclatura": "nomenclatura",
    "reiniciado_desde": "reiniciado desde",
    "objeto": "objeto de contratacion",
    "descripcion": "descripcion de objeto",
    "cui": "codigo unico de inversion",
    "valor_referencial": "vr / ve / cuantia de la contratacion",
    "moneda": "moneda",
}


class SearchError(Exception):
    pass


@dataclass(frozen=True)
class Query:
    objeto: str
    departamento: str | None = None
    anio: int | None = None
    version_seace: str | None = None
    desde: date | None = None
    hasta: date | None = None


@dataclass
class Form:
    action: str
    fields: dict[str, str]
    selects: dict[str, list[tuple[str, str]]] = field(default_factory=dict)


@dataclass
class SearchResult:
    rows: list[dict]
    total: int


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join(text.casefold().split())


def cell_text(cell: str) -> str:
    cell = re.sub(r"<script.*?</script>", "", cell, flags=re.S)
    cell = re.sub(r"<[^>]+>", " ", cell)
    return " ".join(html.unescape(cell).split())


def parse_form(page: str) -> Form:
    start = page.find(f'<form id="{FORM}"')
    if start < 0:
        raise SearchError("search form not found in the page")
    form = page[start : page.index("</form>", start)]

    action = re.search(r'action="([^"]+)"', form).group(1)
    fields = {}
    for tag in re.findall(r"<input[^>]*>", form):
        name = re.search(r'name="([^"]+)"', tag)
        kind = re.search(r'type="([^"]+)"', tag)
        if not name or (kind and kind.group(1) in ("submit", "button", "image", "checkbox", "radio")):
            continue
        value = re.search(r'value="([^"]*)"', tag)
        fields[name.group(1)] = html.unescape(value.group(1)) if value else ""

    selects = {}
    for name, body in re.findall(r'<select[^>]*name="([^"]+)"[^>]*>(.*?)</select>', form, re.S):
        options = re.findall(r'<option value="([^"]*)"[^>]*>([^<]*)</option>', body)
        selects[name] = [(value, html.unescape(label).strip()) for value, label in options]
        fields[name] = ""
    return Form(html.unescape(action), fields, selects)


def find_select(form: Form, filter_name: str) -> str:
    spec = SELECTS[filter_name]
    if "name" in spec:
        if spec["name"] not in form.selects:
            raise SearchError(f"select for {filter_name} not found")
        return spec["name"]
    anchor = normalize(spec["anchor"])
    for name, options in form.selects.items():
        if any(normalize(label) == anchor for _, label in options):
            return name
    raise SearchError(f"select for {filter_name} not found")


def resolve_option(form: Form, filter_name: str, label: str) -> tuple[str, str]:
    select = find_select(form, filter_name)
    options = form.selects[select]
    for value, option_label in options:
        if value and normalize(option_label) == normalize(label):
            return select, value
    valid = ", ".join(option_label for value, option_label in options if value)
    raise SearchError(f"{filter_name} {label!r} is not a portal option. Valid: {valid}")


def search_fields(form: Form, query: Query) -> dict[str, str]:
    fields = dict(form.fields)
    wanted = {
        "objeto": query.objeto,
        "departamento": query.departamento,
        "anio": str(query.anio) if query.anio else None,
        "version_seace": query.version_seace,
    }
    for filter_name, label in wanted.items():
        if label:
            select, value = resolve_option(form, filter_name, label)
            fields[select] = value
    if query.desde:
        fields[f"{FORM}:dfechaInicio_input"] = query.desde.strftime("%d/%m/%Y")
    if query.hasta:
        fields[f"{FORM}:dfechaFin_input"] = query.hasta.strftime("%d/%m/%Y")

    fields[f"{FORM}:tokenBusProSel"] = ""  # the reCAPTCHA token is not checked (U1, A2b)
    fields[FORM] = FORM
    fields.update({
        "javax.faces.partial.ajax": "true",
        "javax.faces.source": f"{FORM}:btnBuscarSel",
        "javax.faces.partial.execute": "@all",
        "javax.faces.partial.render": (
            f"{FORM}:pnlGrdResultadosProcesos {FORM}:footerBuscador "
            f"frmMesajes:gPrincipal {FORM}:btnBuscarSel {FORM}:pnlBuscarProceso"
        ),
        f"{FORM}:btnBuscarSel": f"{FORM}:btnBuscarSel",
        "submit": "S",
    })
    return fields


def parse_amount(text: str | None, nid: int) -> Decimal | None:
    if text in (None, "---"):  # the list shows "---" when no amount is published
        return None
    try:
        return Decimal(text.replace(",", ""))
    except InvalidOperation:
        raise SearchError(f"unreadable amount {text!r} in nidProceso {nid}") from None


def parse_results(xml: str) -> SearchResult:
    total = re.search(r"del total (\d+)", xml)
    if not total:
        raise SearchError("result count not found in the response")

    headers = [normalize(cell_text(th)) for th in re.findall(r"<th[^>]*>(.*?)</th>", xml, re.S)]
    index = {}
    for key, header in COLUMNS.items():
        if header not in headers:
            raise SearchError(f"column {header!r} missing; the results table changed")
        index[key] = headers.index(header)

    rows = []
    for raw in re.split(r'(?=<tr data-ri=")', xml)[1:]:
        cells = [cell_text(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", raw, re.S)]
        nid = re.search(r"nidProceso',value:'(\d+)'", raw)
        if not nid:
            raise SearchError(f"row without nidProceso: {cells[:4]}")
        row = {key: cells[i] or None for key, i in index.items()}
        row["nid_proceso"] = int(nid.group(1))
        row["fecha_publicacion"] = datetime.strptime(
            row["fecha_publicacion"], "%d/%m/%Y %H:%M"
        ).replace(tzinfo=LIMA)
        row["valor_referencial"] = parse_amount(row["valor_referencial"], row["nid_proceso"])
        rows.append(row)
    return SearchResult(rows, int(total.group(1)))


def search(query: Query, session: requests.Session | None = None) -> SearchResult:
    """First results page for one query."""
    session = session or requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    try:
        page = session.get(PAGE, timeout=60)
        page.raise_for_status()
        page.encoding = "utf-8"  # the page declares UTF-8; do not rely on the HTTP header
        form = parse_form(page.text)
        response = session.post(
            BASE + form.action,
            data=search_fields(form, query),
            headers={"Faces-Request": "partial/ajax", "X-Requested-With": "XMLHttpRequest"},
            timeout=60,
        )
        response.raise_for_status()
        response.encoding = "utf-8"
    except requests.RequestException as error:
        raise SearchError(f"portal not reachable (is the Peruvian VPN on?): {error}") from error
    return parse_results(response.text)
