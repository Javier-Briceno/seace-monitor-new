import zipfile
from pathlib import Path

import pytest

from seace_monitor.bases_text import (
    TextError, ToolMissing, bases_files, docx_text, is_scanned, page_of, pdftotext, text_of,
)

FIXTURES = Path(__file__).parent / "fixtures"

try:
    pdftotext()
except ToolMissing:
    pytest.skip("pdftotext not installed", allow_module_level=True)


def test_layout_keeps_a_table_row_together():
    # Section 1.4 of the Alto Trujillo bases: cuantía on one page, the límites table on the next.
    text = text_of(FIXTURES / "bases_cuantia_alto_trujillo.pdf")
    row = next(line for line in text.splitlines() if "2,869,568.98" in line)
    assert "3,020,598.92" in row and "3,322,658.81" in row
    assert page_of(text, text.index("2,869,568.98")) == 2


def test_file_past_the_windows_path_limit_is_read(tmp_path):
    deep = tmp_path / "-".join(["carpeta de anexos"] * 6) / "-".join(["bases integradas y absolución"] * 5)
    deep.mkdir(parents=True)
    path = deep / "bases.pdf"
    path.write_bytes((FIXTURES / "bases_cuantia_alto_trujillo.pdf").read_bytes())
    assert len(str(path.resolve())) > 260
    assert "3,020,598.92" in text_of(path)


def test_pages_with_text_are_not_a_scan():
    assert not is_scanned(text_of(FIXTURES / "bases_cuantia_alto_trujillo.pdf"))


def test_page_without_a_text_layer_is_a_scan():
    assert is_scanned(text_of(FIXTURES / "bases_scanned_page.pdf"))


def test_a_typed_cover_does_not_hide_a_scan():
    cover = "BASES INTEGRADAS " * 20
    assert is_scanned("\f".join([cover] + [""] * 9))
    assert not is_scanned("\f".join([cover] * 3 + [""] * 7))


def test_docx_paragraphs_become_lines(tmp_path):
    path = tmp_path / "bases.docx"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", "<w:body><w:p><w:t>1.4. CUANTÍA</w:t></w:p><w:p><w:t>S/ 1.00</w:t></w:p></w:body>")
    assert docx_text(path).splitlines() == ["1.4. CUANTÍA", "S/ 1.00"]


def test_broken_docx_is_a_text_error(tmp_path):
    path = tmp_path / "bases.docx"
    path.write_bytes(b"not a zip")
    with pytest.raises(TextError):
        docx_text(path)


def test_files_of_a_document_or_of_its_archive():
    assert bases_files("data/documentos/1/bases.pdf", []) == [Path("data/documentos/1/bases.pdf")]
    assert bases_files("data/documentos/1/BASES.rar", ["bases/bases.pdf", "planos.dwg", "anexos.DOCX"]) == [
        Path("data/documentos/1/BASES.rar_contenido/bases/bases.pdf"),
        Path("data/documentos/1/BASES.rar_contenido/anexos.DOCX"),
    ]
