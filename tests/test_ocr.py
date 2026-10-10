from pathlib import Path

import pytest

from seace_monitor.bases_text import ToolMissing, is_scanned, text_of
from seace_monitor.ocr import make_ocr, ocr_path, ocrmypdf

FIXTURES = Path(__file__).parent / "fixtures"

try:
    ocrmypdf()
except ToolMissing:
    pytest.skip("ocrmypdf not installed", allow_module_level=True)


def test_scanned_page_gets_a_text_layer_next_to_the_original(tmp_path):
    original = tmp_path / "bases.pdf"
    original.write_bytes((FIXTURES / "bases_scanned_page.pdf").read_bytes())
    before = original.read_bytes()
    out = make_ocr(original)
    assert out == ocr_path(original) == tmp_path / "bases-ocr.pdf"
    assert not is_scanned(text_of(out))
    assert original.read_bytes() == before
    assert not list(tmp_path.glob("*.part"))


def test_an_existing_copy_is_not_made_again(tmp_path):
    original = tmp_path / "bases.pdf"
    original.write_bytes((FIXTURES / "bases_scanned_page.pdf").read_bytes())
    ocr_path(original).write_bytes(b"made before")
    assert make_ocr(original).read_bytes() == b"made before"
