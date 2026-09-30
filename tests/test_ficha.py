import re
from datetime import datetime
from pathlib import Path

import pytest

from seace_monitor.ficha import FichaError, has_bases, parse_documents
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


def test_empty_table_gives_no_documents():
    page = re.sub(r"<tr[^>]*data-ri.*?</tr>", "", read("ficha_rar.html"), flags=re.S)
    assert parse_documents(page) == []


def test_bases_detected_by_document_type():
    assert has_bases(parse_documents(read("ficha_two_documents.html")))
    assert not has_bases([{"tipo": "Informe que sustenta la declaratoria de Desierto"}])


def test_page_without_document_table_is_an_error():
    with pytest.raises(FichaError, match="document table"):
        parse_documents("<html>session expired</html>")
