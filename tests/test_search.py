from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from seace_monitor import config
from seace_monitor.search import (
    FORM, LIMA, Query, SearchError, make_session, parse_form, parse_results, search, search_fields,
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
