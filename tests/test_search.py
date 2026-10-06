from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from seace_monitor import config
from seace_monitor import search as search_module
from seace_monitor.search import (
    ALL_DEPARTAMENTOS, FORM, LIMA, RESULT_CAP, TABLE, Query, SearchError, SearchResult, make_session, page_fields, parse_form,
    parse_results, parse_rows, search, search_fields, search_pages,
)

FIXTURES = Path(__file__).parent / "fixtures"


def read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def form():
    return parse_form(read("buscador.html"))


def test_labels_resolve_to_codes_whatever_the_select_id(form):
    fields = search_fields(form, Query(objeto="obra", departamento="La Libertad", anio=2026, version_seace="Seace 3"))
    assert fields[f"{FORM}:j_idt192_input"] == "64"
    assert fields[f"{FORM}:departamento_input"] == "14"
    assert fields[f"{FORM}:anioConvocatoria_input"] == "2026"
    assert fields[f"{FORM}:j_idt218_input"] == "3"


def test_accents_are_optional(form):
    fields = search_fields(form, Query(objeto="Consultoria de Obra"))
    assert fields[f"{FORM}:j_idt192_input"] == "63"


def test_unset_filters_stay_empty(form):
    fields = search_fields(form, Query(objeto="Obra"))
    assert fields[f"{FORM}:departamento_input"] == ""
    assert fields[f"{FORM}:anioConvocatoria_input"] == ""


def test_dates_use_portal_format(form):
    fields = search_fields(form, Query(objeto="Obra", desde=date(2026, 9, 1), hasta=date(2026, 9, 29)))
    assert fields[f"{FORM}:dfechaInicio_input"] == "01/09/2026"
    assert fields[f"{FORM}:dfechaFin_input"] == "29/09/2026"


def test_unknown_label_lists_valid_options(form):
    with pytest.raises(SearchError, match="LA LIBERTAD"):
        search_fields(form, Query(objeto="Obra", departamento="Libertad"))


def test_rows_parsed_by_column_title():
    result = parse_results(read("search_page1.xml"))
    assert result.total == 499
    assert len(result.rows) == 15
    first = result.rows[0]
    assert first["nid_proceso"] == 1250328
    assert first["nomenclatura"] == "LP-ABR-10-2026-MPO/C-1"
    assert first["entidad"] == "MUNICIPALIDAD PROVINCIAL DE OTUZCO"
    assert first["fecha_publicacion"] == datetime(2026, 9, 28, 20, 40, tzinfo=LIMA)
    assert first["valor_referencial"] == Decimal("3522447.65")
    assert first["moneda"] == "Soles"
    assert first["objeto"] == "Obra"
    assert first["reiniciado_desde"] is None
    assert first["descripcion"].startswith("RENOVACION DE PUENTE")


def test_nid_proceso_is_unique_within_a_page():
    rows = parse_results(read("search_page1.xml")).rows
    assert len({r["nid_proceso"] for r in rows}) == len(rows)


def test_missing_column_is_an_error_not_an_empty_field():
    xml = read("search_page1.xml").replace("Moneda", "Divisa")
    with pytest.raises(SearchError, match="moneda"):
        parse_results(xml)


def test_response_without_total_is_an_error():
    with pytest.raises(SearchError, match="count"):
        parse_results("<partial-response></partial-response>")


def test_config_builds_one_query_per_departamento():
    cfg = {"search": {"objeto": "Obra", "departamentos": ["LA LIBERTAD", "ANCASH"], "anio": 2026, "dias": 3}}
    queries = config.queries(cfg, today=date(2026, 9, 30))
    assert [q.departamento for q in queries] == ["LA LIBERTAD", "ANCASH"]
    assert queries[0].desde == date(2026, 9, 27)
    assert queries[0].hasta == date(2026, 9, 30)
    assert queries[0].version_seace is None


def test_dashes_mean_no_amount():
    rows = parse_results(read("search_page1.xml")).rows
    assert rows[10]["valor_referencial"] is None


def test_unreadable_amount_is_an_error():
    xml = read("search_page1.xml").replace("3,522,447.65", "S/ 3.5 M")
    with pytest.raises(SearchError, match="1250328"):
        parse_results(xml)


def test_proxy_switch():
    assert config.proxy({"network": {"proxy": "http://127.0.0.1:8888"}}) == "http://127.0.0.1:8888"
    assert config.proxy({"network": {"proxy": ""}}) is None
    assert config.proxy({}) is None


def test_session_ignores_proxy_environment(monkeypatch):
    monkeypatch.setenv("NO_PROXY", "*")
    session = make_session("http://127.0.0.1:8888")
    assert session.trust_env is False
    assert session.proxies["https"] == "http://127.0.0.1:8888"


def test_dead_proxy_fails_instead_of_going_direct():
    # Port 9 on localhost has nothing listening, like a stopped VPN container.
    with pytest.raises(SearchError, match="VPN proxy"):
        search(Query(objeto="Obra"), make_session("http://127.0.0.1:9"))


def test_later_page_rows_use_the_first_page_layout():
    first = parse_results(read("search_page1.xml"))
    rows = parse_rows(read("search_page2.xml"), first.columns)
    assert len(rows) == 15
    assert rows[0]["nid_proceso"] == 1252893
    assert rows[0]["nomenclatura"] == "LP-ABR-11-2026-MPV/COM-1"
    assert rows[0]["valor_referencial"] == Decimal("4529980.34")
    assert all(r["ficha_params"] for r in rows)


def test_page_request_asks_for_the_next_offset(form):
    fields = page_fields(form, "vs", 30)
    assert fields[f"{TABLE}_first"] == "30"
    assert fields[f"{TABLE}_rows"] == "15"
    assert fields["javax.faces.ViewState"] == "vs"


class FakeResponse:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        pass


class FakeSession:
    """Answers every page request with the next prepared page."""

    def __init__(self, pages):
        self.pages = list(pages)
        self.offsets = []

    def post(self, url, data, headers, timeout):
        self.offsets.append(data[f"{TABLE}_first"])
        return FakeResponse(self.pages.pop(0))


def first_page(form, total, query):
    page = parse_results(read("search_page1.xml"))
    search_module.mark_search(page.rows, query)
    return SearchResult(page.rows, total, form, "vs", page.columns)


def pages_of(monkeypatch, form, total, later, query=Query(objeto="Obra")):
    monkeypatch.setattr(search_module, "search", lambda query, session: first_page(form, total, query))
    session = FakeSession(later)
    return session, search_pages(query, session)


def test_every_page_is_read_until_the_total(monkeypatch, form):
    session, pages = pages_of(monkeypatch, form, 30, [read("search_page2.xml")])
    rows = [r["nid_proceso"] for page in pages for r in page.rows]
    assert len(rows) == len(set(rows)) == 30
    assert session.offsets == ["15"]


def test_a_cut_list_stops_the_search(monkeypatch, form):
    _, pages = pages_of(monkeypatch, form, RESULT_CAP, [])
    with pytest.raises(SearchError, match="stops at 499"):
        next(pages)


def test_rows_read_twice_while_paging_stop_the_search(monkeypatch, form):
    # The same page twice is what a list shifted by new publications looks like.
    _, pages = pages_of(monkeypatch, form, 30, [read("search_page1.xml")])
    with pytest.raises(SearchError, match="15 different rows of 30"):
        list(pages)


def test_an_empty_page_before_the_total_stops_the_search(monkeypatch, form):
    empty = '<?xml version="1.0"?><partial-response><changes></changes></partial-response>'
    _, pages = pages_of(monkeypatch, form, 30, [empty])
    with pytest.raises(SearchError, match="15 different rows of 30"):
        list(pages)


def test_every_row_says_which_departamento_was_searched(monkeypatch, form):
    _, pages = pages_of(monkeypatch, form, 30, [read("search_page2.xml")], Query(objeto="Obra", departamento="ANCASH"))
    assert {r["departamento_busqueda"] for page in pages for r in page.rows} == {"ANCASH"}


def test_search_without_departamento_is_marked_as_all(monkeypatch, form):
    _, pages = pages_of(monkeypatch, form, 30, [read("search_page2.xml")])
    assert {r["departamento_busqueda"] for page in pages for r in page.rows} == {ALL_DEPARTAMENTOS}


def test_rows_outside_the_dates_stop_the_search(monkeypatch, form):
    query = Query(objeto="Obra", desde=date(2026, 1, 1), hasta=date(2026, 1, 31))
    _, pages = pages_of(monkeypatch, form, 30, [], query)
    with pytest.raises(SearchError, match="answered an earlier search"):
        next(pages)


def test_rows_within_the_dates_pass(monkeypatch, form):
    query = Query(objeto="Obra", desde=date(2026, 9, 1), hasta=date(2026, 10, 31))
    _, pages = pages_of(monkeypatch, form, 30, [read("search_page2.xml")], query)
    assert sum(len(page.rows) for page in pages) == 30


class SearchSession:
    """Serves the buscador page and one results page; records the cookies each request saw."""

    def __init__(self):
        import requests
        self.cookies = requests.cookies.RequestsCookieJar()
        self.cookies.set("JSESSIONID", "from-the-last-search")
        self.seen = []

    def get(self, url, timeout):
        self.seen.append(dict(self.cookies))
        response = FakeResponse(read("buscador.html"))
        return response

    def post(self, url, data, headers, timeout):
        self.seen.append(dict(self.cookies))
        return FakeResponse(read("search_page1.xml"))


def test_every_search_starts_a_new_portal_session():
    session = SearchSession()
    search(Query(objeto="Obra"), session)
    assert session.seen[0] == {}
