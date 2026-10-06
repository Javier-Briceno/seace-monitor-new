import re
from datetime import datetime
from pathlib import Path

import pytest

from seace_monitor.ficha import FichaError, has_bases, parse_deadline, parse_documents, parse_estados
from seace_monitor.search import LIMA

FIXTURES = Path(__file__).parent / "fixtures"


def read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_documents_read_by_column_title():
    documents = parse_documents(read("ficha_two_documents.html"))
    assert [d["tipo"] for d in documents] == [
        "Informe que sustenta la declaratoria de Desierto",
        "Bases Administrativas",
    ]
    bases = documents[1]
    assert bases["etapa"] == "Convocatoria"
    assert re.fullmatch(r"[0-9a-f-]{36}", bases["uuid"])
    assert bases["nombre_archivo"].endswith(".pdf")
    assert bases["publicado_en"] == datetime(2026, 9, 29, 17, 6, tzinfo=LIMA)


def test_archive_is_listed_like_any_document():
    [bases] = parse_documents(read("ficha_rar.html"))
    assert bases["nombre_archivo"] == "BASES.rar"


def without_link(page: str) -> str:
    return re.sub(r"<a id=\"tbFicha:dtDocumentos:0:j_idt397\".*?</a></a>", "BASES.rar", page, flags=re.S)


def test_document_without_link_is_kept_without_uuid():
    [bases] = parse_documents(without_link(read("ficha_rar.html")))
    assert bases["uuid"] is None
    assert bases["tipo"] == "Bases Administrativas"
    assert bases["nombre_archivo"] == "BASES.rar"


def test_bases_without_link_do_not_count():
    assert not has_bases(parse_documents(without_link(read("ficha_rar.html"))))


def test_empty_table_gives_no_documents():
    page = re.sub(r"<tr[^>]*data-ri.*?</tr>", "", read("ficha_rar.html"), flags=re.S)
    assert parse_documents(page) == []


def test_bases_detected_by_document_type():
    assert has_bases(parse_documents(read("ficha_two_documents.html")))
    assert not has_bases([{"tipo": "Informe que sustenta la declaratoria de Desierto", "uuid": "x"}])


def test_page_without_document_table_is_an_error():
    with pytest.raises(FichaError, match="document table"):
        parse_documents("<html>session expired</html>")


def test_deadline_is_the_end_of_the_offer_stage():
    # Stage name arrives with a broken accent ("Presentaci�n de propuestas") in these pages.
    assert parse_deadline(read("ficha_two_documents.html")) == datetime(2026, 10, 9, 23, 59, tzinfo=LIMA)
    assert parse_deadline(read("ficha_rar.html")) == datetime(2026, 10, 29, 23, 59, tzinfo=LIMA)


def test_date_without_time_lasts_until_the_end_of_the_day():
    page = read("ficha_rar.html").replace("29/10/2026 23:59", "29/10/2026", 1)
    assert parse_deadline(page) == datetime(2026, 10, 29, 23, 59, tzinfo=LIMA)


def test_no_offer_stage_gives_none():
    page = re.sub(r"Presentaci\S* de propuestas", "Otra etapa", read("ficha_rar.html"))
    assert parse_deadline(page) is None


def test_missing_cronograma_is_an_error():
    with pytest.raises(FichaError):
        parse_deadline("<html></html>")


def test_estado_of_the_item():
    assert parse_estados(read("ficha_two_documents.html")) == ["Convocado"]


def test_each_item_keeps_its_own_estado():
    page = read("ficha_two_documents.html")
    item = re.search(r'<td><span style="font-weight:bold;">Estado:</span></td>\s*<td>Convocado</td>', page).group(0)
    two = page.replace(item, item + item.replace("Convocado", "Retrotra&iacute;do por resoluci&oacute;n"))
    assert parse_estados(two) == ["Convocado", "Retrotraído por resolución"]


def test_ficha_without_item_estado_is_an_error():
    with pytest.raises(FichaError, match="estado"):
        parse_estados("<html>session expired</html>")
