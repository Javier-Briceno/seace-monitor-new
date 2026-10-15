import re
from pathlib import Path

import pytest

from seace_monitor import reading
from seace_monitor.bases_text import ToolMissing, pdftotext
from seace_monitor.ocr import OcrError, ia_path

SCAN = Path(__file__).parent / "fixtures" / "bases_scanned_page.pdf"
MISSING = "not here"
VALUES = {"cuantia": lambda r: r.get("cuantia")}


def has_pdftotext() -> bool:
    try:
        return bool(pdftotext())
    except ToolMissing:
        return False


needs_pdftotext = pytest.mark.skipif(not has_pdftotext(), reason="pdftotext not installed")


def read(text: str) -> dict:
    found = re.search(r"CUANTIA ES S/ ([\d,.]+)", text)
    return {"cuantia": found.group(1), "revisar": None} if found else {"cuantia": None, "revisar": MISSING}


def scan(tmp_path: Path, ia: str | None = None) -> Path:
    path = tmp_path / "BASES.pdf"
    path.write_bytes(SCAN.read_bytes())
    if ia is not None:
        ia_path(path).write_text(ia, encoding="utf-8")
    return path


def tesseract(tmp_path: Path, text: str):
    out = tmp_path / "tesseract.txt"
    out.write_text(text, encoding="utf-8")
    return lambda path, pages: out


@needs_pdftotext
def test_the_model_text_is_read_before_tesseract_and_both_agreeing_is_kept(tmp_path):
    path = scan(tmp_path, "1.4 LA CUANTIA ES S/ 1,250,000.00")
    result = reading.read_files([path], read, MISSING, tesseract(tmp_path, "1.4 LA CUANTIA ES S/ 1,250,000.00"), VALUES)
    assert (result["cuantia"], result["ocr"], result["ia"]) == ("1,250,000.00", True, True)
    assert result["segunda_lectura"] == {"ia": {"cuantia": "1,250,000.00"}, "tesseract": {"cuantia": "1,250,000.00"},
                                         "difieren": []}


@needs_pdftotext
def test_values_both_readings_hold_differently_are_named(tmp_path):
    path = scan(tmp_path, "1.4 LA CUANTIA ES S/ 1,250,000.00")
    result = reading.read_files([path], read, MISSING, tesseract(tmp_path, "1.4 LA CUANTIA ES S/ 1,258,000.00"), VALUES)
    assert result["cuantia"] == "1,250,000.00"
    assert result["segunda_lectura"]["difieren"] == ["cuantia"]
    assert result["segunda_lectura"]["tesseract"] == {"cuantia": "1,258,000.00"}


@needs_pdftotext
def test_a_value_only_the_model_read_is_no_difference(tmp_path):
    path = scan(tmp_path, "1.4 LA CUANTIA ES S/ 1,250,000.00")
    result = reading.read_files([path], read, MISSING, tesseract(tmp_path, "1.4 LA CUANT1A E5 5/ ..."), VALUES)
    assert result["segunda_lectura"] == {"ia": None, "tesseract": None, "difieren": []}


@needs_pdftotext
def test_the_model_text_is_read_where_no_ocr_is_allowed(tmp_path):
    path = scan(tmp_path, "1.4 LA CUANTIA ES S/ 1,250,000.00")
    result = reading.read_files([path], read, MISSING, None, VALUES)
    assert (result["cuantia"], result["ia"]) == ("1,250,000.00", True)
    assert result["segunda_lectura"]["tesseract"] is None


@needs_pdftotext
def test_a_failed_tesseract_copy_leaves_the_model_reading(tmp_path):
    def fails(path, pages):
        raise OcrError("ocrmypdf exit 2")
    path = scan(tmp_path, "1.4 LA CUANTIA ES S/ 1,250,000.00")
    result = reading.read_files([path], read, MISSING, fails, VALUES)
    assert result["cuantia"] == "1,250,000.00" and result["segunda_lectura"]["difieren"] == []


@needs_pdftotext
def test_a_model_text_without_the_section_is_not_a_scan_any_more(tmp_path):
    path = scan(tmp_path, "CAPITULO II DEL PROCEDIMIENTO DE SELECCION. " * 3)
    assert reading.read_files([path], read, MISSING, None, VALUES)["revisar"] == MISSING


@needs_pdftotext
def test_without_a_model_text_tesseract_reads_as_before(tmp_path):
    path = scan(tmp_path)
    result = reading.read_files([path], read, MISSING, tesseract(tmp_path, "1.4 LA CUANTIA ES S/ 9.00"), VALUES)
    assert (result["cuantia"], result["ocr"]) == ("9.00", True) and "ia" not in result


def test_a_compared_value_can_ignore_what_is_noise():
    name = {"obra": lambda r: r.get("obra")}
    squeezed = {"obra": lambda v: v.replace(" ", "")}
    first, second = {"obra": "AMPLIACION DEL SERVICIO", "revisar": None}, {"obra": "AMPLIACION DEL SERVIC IO", "revisar": None}
    assert reading.second_reading(first, second, name, MISSING)["difieren"] == ["obra"]
    assert reading.second_reading(first, second, name, MISSING, squeezed)["difieren"] == []
