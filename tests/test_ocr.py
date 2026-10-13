from pathlib import Path

import pytest

from seace_monitor.bases_text import ToolMissing, is_scanned, text_of
from seace_monitor.ocr import image_pages, make_ocr, ocr_path, ocr_pdf_path, ocrmypdf, page_ranges

FIXTURES = Path(__file__).parent / "fixtures"

HEADER = "MUNICIPALIDAD DISTRITAL DE QUILLO\nLICITACIÓN PÚBLICA DE OBRAS N°01-2026-MDQ-C-1 – PRIMERA CONVOCATORIA\n27\n"


def test_pages_with_only_the_typed_header_are_images():
    body = "1.4. CUANTÍA DE LA CONTRATACIÓN La cuantía de la contratación asciende a la suma de S/ 1.00 " * 8
    assert image_pages("\f".join([HEADER + body, HEADER, "", HEADER + body])) == [2, 3]


def test_page_ranges_are_compact():
    assert page_ranges([1, 2, 3, 7, 9, 10]) == "1-3,7,9-10"
    assert page_ranges([5]) == "5"


try:
    ocrmypdf()
    has_ocr = True
except ToolMissing:
    has_ocr = False
needs_ocr = pytest.mark.skipif(not has_ocr, reason="ocrmypdf not installed")


@needs_ocr
def test_scanned_page_gets_a_text_layer_next_to_the_original(tmp_path):
    original = tmp_path / "bases.pdf"
    original.write_bytes((FIXTURES / "bases_scanned_page.pdf").read_bytes())
    before = original.read_bytes()
    out = make_ocr(original, [1])
    assert out == ocr_path(original) == tmp_path / "bases-ocr.txt"
    assert not is_scanned(text_of(out))
    assert original.read_bytes() == before
    assert sorted(f.name for f in tmp_path.iterdir()) == ["bases-ocr.txt", "bases.pdf"]


@needs_ocr
def test_pages_with_text_keep_their_own_text(tmp_path):
    original = tmp_path / "bases.pdf"
    original.write_bytes((FIXTURES / "bases_cuantia_alto_trujillo.pdf").read_bytes())
    out = make_ocr(original, [2])
    assert text_of(out).split("\f")[0] == text_of(original).split("\f")[0]


@needs_ocr
def test_a_signed_bases_is_recognized_and_the_original_keeps_its_signature(tmp_path):
    original = tmp_path / "bases.pdf"
    original.write_bytes((FIXTURES / "bases_scanned_page_signed.pdf").read_bytes())
    before = original.read_bytes()
    assert not is_scanned(text_of(make_ocr(original, [1])))
    assert original.read_bytes() == before


@needs_ocr
def test_an_existing_copy_is_not_made_again(tmp_path):
    original = tmp_path / "bases.pdf"
    original.write_bytes((FIXTURES / "bases_scanned_page.pdf").read_bytes())
    ocr_path(original).write_bytes(b"made before")
    assert make_ocr(original, [1]).read_bytes() == b"made before"


def test_an_ocred_pdf_of_an_earlier_run_gives_its_text_without_recognizing_again(tmp_path):
    original = tmp_path / "bases.pdf"
    original.write_bytes((FIXTURES / "bases_scanned_page.pdf").read_bytes())
    earlier = ocr_pdf_path(original)
    earlier.write_bytes((FIXTURES / "bases_cuantia_alto_trujillo.pdf").read_bytes())
    out = make_ocr(original, [1])
    assert text_of(out) == text_of(earlier)
    assert earlier.exists()


def test_the_saved_text_reads_byte_for_byte_like_the_pdf(tmp_path):
    # pdftotext ends lines with CR LF on Windows; the readers must get them unchanged
    original = tmp_path / "bases.pdf"
    original.write_bytes(b"")
    ocr_pdf_path(original).write_bytes((FIXTURES / "bases_cuantia_alto_trujillo.pdf").read_bytes())
    assert make_ocr(original, [1]).read_bytes().decode("utf-8") == text_of(ocr_pdf_path(original))
