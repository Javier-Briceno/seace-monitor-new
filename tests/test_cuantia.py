from decimal import Decimal
from pathlib import Path

import pytest

from seace_monitor.bases_text import ToolMissing, pdftotext
from seace_monitor.ocr import OcrError
from seace_monitor.cuantia import (
    DESIGN, NO_SECTION, SCANNED, TEMPLATE, lower_limit, money, read, read_files, upper_limit,
)

FIXTURES = Path(__file__).parent / "fixtures" / "cuantia"
PDFS = Path(__file__).parent / "fixtures"


def has_pdftotext() -> bool:
    try:
        return bool(pdftotext())
    except ToolMissing:
        return False


needs_pdftotext = pytest.mark.skipif(not has_pdftotext(), reason="pdftotext not installed")


def bases(nid: str) -> str:
    """Section 1.4 and chapter IV's offer type of a real bases, as pdftotext -layout gives them."""
    return (FIXTURES / f"{nid}.txt").read_text(encoding="utf-8")


def warnings(result: dict) -> list[dict]:
    return result["avisos"]


@pytest.mark.parametrize("written, value", [
    ("3,522,447.65", "3522447.65"), ("2´996,729.85", "2996729.85"), ("6’590,038.42", "6590038.42"),
    ("2, 216, 331.39", "2216331.39"), ("5,895 503.74", "5895503.74"), ("1,111.161.86", "1111161.86"),
    ("842.979,99", "842979.99"),
])
def test_amounts_as_entities_write_them(written, value):
    assert money(written) == Decimal(value)


def test_lower_limit_rounds_up_and_upper_limit_cuts():
    # 127,019.94 x 0.95 = 120,668.943 and x 1.10 = 139,721.934
    assert lower_limit(Decimal("127019.94")) == Decimal("120668.95")
    assert upper_limit(Decimal("127019.94")) == Decimal("139721.93")
    # an exact cent stays as it is
    assert lower_limit(Decimal("100.00")) == Decimal("95.00")


def test_limits_on_the_page_after_the_footnote_are_read():
    # Alto Trujillo: the footnote of 1.4 sits between the cuantía and the límites table.
    result = read(bases("1218514"))
    assert (result["cuantia"], result["limite_inferior"], result["limite_superior"]) == (
        "3020598.92", "2869568.98", "3322658.81")
    assert result["tipo_oferta"] == "limitada"
    assert warnings(result) == [] and result["revisar"] is None


def test_lower_limit_one_cent_short():
    assert warnings(read(bases("1252316"))) == [
        {"aviso": "limite_inferior", "bases": "120668.94", "exacto": "120668.95"}]


def test_lower_limit_above_the_exact_figure_is_also_wrong():
    # Digits swapped: offers between 587,464.47 and 587,646.46 would be disqualified.
    assert warnings(read(bases("1255911"))) == [
        {"aviso": "limite_inferior", "bases": "587646.47", "exacto": "587464.47"}]


def test_lower_limit_at_90_percent_is_read_from_its_column():
    assert warnings(read(bases("1239040"))) == [
        {"aviso": "limite_inferior", "bases": "689757.19", "exacto": "728077.03"}]


def test_typo_in_the_upper_limit():
    # Also: the cuantía stands right next to the lower límite and must not be taken for it.
    result = read(bases("1253422"))
    assert result["limite_inferior"] == "1435914.92"
    assert warnings(result) == [{"aviso": "limite_superior", "bases": "1622638.31", "exacto": "1662638.31"}]


@pytest.mark.parametrize("nid, low, high", [("1253596", "3835250.54", "4440816.41"),
                                            ("1251678", "45795975.67", "53026919.18")])
def test_limits_are_the_con_igv_columns(nid, low, high):
    # "Con IGV" and "Sin IGV" under each límite: the sin-IGV lower figure sits between the two límites.
    result = read(bases(nid))
    assert (result["limite_inferior"], result["limite_superior"]) == (low, high)
    assert warnings(result) == []


def test_unfilled_limits_table_of_a_fixed_offer_is_no_table():
    result = read(bases("1240782"))
    assert result["cuantia"] == "1736041.78"
    assert warnings(result) == [] and result["revisar"] is None


def test_limit_on_its_own_line_still_belongs_to_its_column():
    result = read(bases("1252404"))
    assert result["limite_inferior"] == "292823.88"
    assert warnings(result) == [{"aviso": "limite_superior", "bases": "339059.23", "exacto": "339059.22"}]


def test_amazonia_table_is_not_taken_for_the_limits():
    # Jaén: apostrophe for millions, and a second table without IGV for Ley 27037 below the first.
    result = read(bases("1253306"))
    assert (result["cuantia"], result["limite_inferior"], result["limite_superior"]) == (
        "16825967.17", "15984668.82", "18508563.88")
    assert warnings(result) == []


def test_limits_split_over_several_lines():
    result = read(bases("1230542"))
    assert (result["limite_inferior"], result["limite_superior"]) == ("545393.86", "631508.68")


def test_fixed_offer_with_a_limits_table():
    assert warnings(read(bases("1253988"))) == [{"aviso": "fija_con_limites"}]


def test_fixed_offer_with_limits_at_90_percent():
    assert warnings(read(bases("1220796"))) == [
        {"aviso": "fija_con_limites"},
        {"aviso": "limite_inferior", "bases": "152249.35", "exacto": "160707.65"},
    ]


def test_limited_offer_without_a_limits_table():
    result = read(bases("1235247"))
    assert result["cuantia"] == "71107.05"
    assert warnings(result) == [{"aviso": "limitada_sin_limites"}]


@pytest.mark.parametrize("nid", ["1255541", "1212216", "1249332"])
def test_design_and_build_goes_to_a_person(nid):
    # 1212216 writes the component amounts without "S/"; 1249332 (a DOCX) only has the budget per component.
    assert read(bases(nid))["revisar"] == DESIGN


def test_instruction_left_around_a_chosen_offer_type():
    # "[SEÑALAR ... : FIJA DE CONFORMIDAD ...]": the choice was made, only the instruction stayed.
    assert read(bases("1219930"))["tipo_oferta"] == "fija"


def test_choice_written_before_the_template_brackets():
    assert read(bases("1251115"))["tipo_oferta"] == "fija"


def test_template_tables_left_in_do_not_hide_a_filled_cuantia():
    # Salpo kept every example table of the standard bases, empty, also the diseño y construcción one.
    result = read(bases("1254879"))
    assert (result["cuantia"], result["tipo_oferta"], result["revisar"]) == ("910557.87", "fija", None)
    assert warnings(result) == []


def test_unfilled_cuantia_goes_to_a_person():
    text = ("1.4. CUANTÍA DE LA CONTRATACIÓN\n La cuantía de la contratación asciende a "
            "[CONSIGNAR EN NÚMEROS Y LETRAS LA CUANTÍA], incluidos los impuestos de ley")
    assert read(text)["revisar"] == TEMPLATE


def test_upper_limit_one_cent_over():
    assert warnings(read(bases("1253964"))) == [
        {"aviso": "limite_superior", "bases": "619312.61", "exacto": "619312.60"}]


def test_rounding_rule_is_not_a_limits_table():
    # SEDALIB kept the sentence "si el límite inferior tiene más de dos (2) decimales ... límite superior".
    result = read(bases("1236464"))
    assert result["tipo_oferta"] == "fija"
    assert warnings(result) == [] and result["revisar"] is None


@pytest.mark.parametrize("nid", ["1226928", "1232788"])
def test_offer_type_left_as_the_template_choice(nid):
    result = read(bases(nid))
    assert result["tipo_oferta"] == "sin rellenar"
    assert {"aviso": "tipo_oferta_sin_rellenar"} in warnings(result)


def test_cuantia_differing_from_seace():
    result = read(bases("1218514"), valor_seace=Decimal("3020598.82"))
    assert warnings(result) == [{"aviso": "cuantia_distinta_seace", "bases": "3020598.92", "seace": "3020598.82"}]
    assert warnings(read(bases("1218514"), valor_seace=Decimal("3020598.92"))) == []


def test_title_in_the_index_is_not_the_section():
    index = "1.4. CUANTÍA DE LA CONTRATACIÓN ........ 19\n1.5. EXPEDIENTE DE CONTRATACIÓN ........ 20\n"
    assert read(index)["revisar"] == NO_SECTION


@needs_pdftotext
def test_the_file_with_the_section_is_read_among_annexes(tmp_path):
    annex = tmp_path / "anexos.docx"
    annex.write_bytes(b"not a docx")
    result = read_files([PDFS / "bases_scanned_page.pdf", annex, PDFS / "bases_cuantia_alto_trujillo.pdf"])
    assert result["archivo"] == "bases_cuantia_alto_trujillo.pdf"
    assert (result["cuantia"], result["limite_inferior"]) == ("3020598.92", "2869568.98")
    assert result["pagina"] == 1


@needs_pdftotext
def test_bases_that_are_only_a_scan():
    result = read_files([PDFS / "bases_scanned_page.pdf"])
    assert result["revisar"] == SCANNED and result["archivo"] == "bases_scanned_page.pdf"
    assert result["ocr"] is False


@needs_pdftotext
def test_scanned_bases_are_read_from_their_ocr_copy_and_say_so():
    # The copy stands in for an OCRed one: any PDF with a text layer.
    result = read_files([PDFS / "bases_scanned_page.pdf"], ocr=lambda path, pages: PDFS / "bases_cuantia_alto_trujillo.pdf")
    assert (result["cuantia"], result["archivo"], result["ocr"]) == ("3020598.92", "bases_scanned_page.pdf", True)


@needs_pdftotext
def test_files_named_as_bases_are_ocred_first_and_only_a_few(tmp_path):
    names = ["ACTA.pdf", "PLANOS 1.pdf", "PLANOS 2.pdf", "BASES PALMIRA.pdf"]
    for name in names:
        (tmp_path / name).write_bytes((PDFS / "bases_scanned_page.pdf").read_bytes())
    asked = []

    def ocr(path, pages):
        asked.append(path.name)
        return PDFS / "bases_scanned_page.pdf"  # nothing found: every allowed file is tried

    read_files([tmp_path / n for n in names], ocr=ocr)
    assert asked == ["BASES PALMIRA.pdf", "ACTA.pdf"]


@needs_pdftotext
def test_failed_ocr_leaves_the_bases_for_a_person():
    def fails(path, pages):
        raise OcrError("ocrmypdf exit 2")
    result = read_files([PDFS / "bases_scanned_page.pdf"], ocr=fails)
    assert result["revisar"] == SCANNED


def test_document_without_pdf_or_docx():
    assert read_files([])["revisar"] == "sin PDF ni DOCX"


def test_cuantia_after_the_amount_in_words():
    text = ("1.4. CUANTÍA DE LA CONTRATACIÓN\n La cuantía de la contratación asciende a la suma de doscientos "
            "sesenta y seis mil ochocientos diecisiete con 69/100 soles (S/ 266,817.69), incluidos los impuestos")
    assert read(text)["cuantia"] == "266817.69"
