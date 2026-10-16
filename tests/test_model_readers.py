from pathlib import Path

import pytest

from seace_monitor import factores, personal, reading
from seace_monitor.ocr import ia_path


def read_source(monkeypatch, tmp_path, reader, text, source):
    original = tmp_path / "bases.pdf"
    model = ia_path(original)
    tesseract = tmp_path / "bases-ocr.txt"
    if source == "ia":
        model.write_text(text, encoding="utf-8")
    monkeypatch.setattr(reading, "text_of", lambda path: text if path != original or source == "digital" else "")
    monkeypatch.setattr(reading, "image_pages", lambda text: [1] if not text else [])
    return reader.read_files([original], ocr=lambda path, pages: tesseract)


@pytest.mark.parametrize("source", ["ia", "tesseract", "digital"])
def test_personal_keeps_word_digit_warning_except_for_tesseract(monkeypatch, tmp_path, source):
    text = ("B.2 EXPERIENCIA DEL PERSONAL CLAVE\nRequisitos:\n"
            "   CARGO                 EXPERIENCIA\n"
            "   Residente de obra     veinticuatro (36) meses como residente en obras.\n"
            "Acreditación:\n")
    before = personal.read(text)
    assert before["revisar"] is None and before["avisos"]
    result = read_source(monkeypatch, tmp_path, personal, text, source)
    if source == "tesseract":
        assert result["revisar"] == personal.UNREADABLE
        assert result["personal"][0]["cargo"] is None
        assert result["avisos"] == []
    else:
        assert result["revisar"] is None
        assert result["personal"] == before["personal"]
        assert result["avisos"] == before["avisos"]


@pytest.mark.parametrize("source", ["ia", "tesseract", "digital"])
def test_personal_unknown_cargo_words_are_suppressed_only_for_tesseract(monkeypatch, tmp_path, source):
    text = ("B.2 EXPERIENCIA DEL PERSONAL CLAVE\nRequisitos:\n"
            "   CARGO                 EXPERIENCIA\n"
            "   Especialista Zorpal   24 meses como especialista en obras.\n"
            "Acreditación:\n")
    before = personal.read(text)
    assert before["revisar"] is None
    assert personal.unknown_words(before["personal"][0]["cargo"])
    result = read_source(monkeypatch, tmp_path, personal, text, source)
    assert result["revisar"] == (personal.UNREADABLE if source == "tesseract" else None)
    assert result["personal"][0]["cargo"] == (None if source == "tesseract" else before["personal"][0]["cargo"])


@pytest.mark.parametrize("source", ["ia", "tesseract", "digital"])
def test_factor_sum_warning_is_preserved_except_for_tesseract(monkeypatch, tmp_path, source):
    text = ("CUADRO RESUMEN FACTORES DE EVALUACIÓN\n"
            " A. EXPERIENCIA ESPECÍFICA ADICIONAL DEL PERSONAL CLAVE     65 puntos   COMITÉ\n"
            " K. SEGURIDAD Y SALUD                                       50 puntos   COMITÉ\n"
            " PUNTAJE TOTAL                                              100 puntos\n")
    before = factores.read(text)
    assert before["revisar"] is None
    assert before["avisos"] == [{"aviso": "suma_distinta_total", "suma": 115, "total": 100}]
    result = read_source(monkeypatch, tmp_path, factores, text, source)
    assert result["factores"] == before["factores"]
    assert result["revisar"] == (factores.UNREADABLE if source == "tesseract" else None)
    assert result["avisos"] == ([] if source == "tesseract" else before["avisos"])


@pytest.mark.parametrize("source", ["ia", "tesseract", "digital"])
def test_factor_description_warning_is_preserved_except_for_tesseract(monkeypatch, tmp_path, source):
    fixture = Path(__file__).parent / "fixtures" / "factores" / "1252316.txt"
    text = fixture.read_text(encoding="utf-8").replace(
        "10 PUNTOS                          COMITÉ", "15 PUNTOS                          COMITÉ")
    before = factores.read(text)
    assert before["revisar"] is None and before["suma"] == 100
    assert before["avisos"] == [{"aviso": "puntaje_distinto", "factor": "Gestión de calidad",
                                 "cuadro": 15, "descripcion": 10}]
    result = read_source(monkeypatch, tmp_path, factores, text, source)
    assert result["revisar"] is None
    assert result["avisos"] == ([] if source == "tesseract" else before["avisos"])
