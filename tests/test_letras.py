from decimal import Decimal

import pytest

from seace_monitor.letras import amount_in_words, check, words_around


@pytest.mark.parametrize("words, amount", [
    # real phrases of the bases, OCR slips included
    ("Cuatro Millones Ochocientos Veintinueve Mil Ciento Treinta con 42100 Soles", "4829130.42"),
    ("Setecientos Sesenta y Sels MII Trescientos Noventa y Seis con 87/100 Soles", "766396.87"),
    ("UN MILLÓN SETENTA Y UN MIL OCHOCIENTOS OCHENTA Y DOS CON CUARENTA Y CINCO 45/100 SOLES", "1071882.45"),
    ("un millón setecientos dieciséis mil ochenta y ocho con 80/100 soles", "1716088.80"),
    ("doscientos sesenta y seis mil ochocientos diecisiete con 69/100 soles", "266817.69"),
    ("CIEN MIL CON 00/100 SOLES", "100000.00"),
    ("TRESCIENTOS OCHO MIL DOSCIENTOS TREINTA Y CINCO Y 66/100 SOLES", "308235.66"),
    ("Dos cientos Nueve Mil Cuatrocientos Cincuenta y Nueve con 58/100 Soles", "209459.58"),
    ("SEIS CIENTOS QUINCE MIL CUATROCIENTOS CINCUENTA Y SEIS CON 52/100 SOLES", "615456.52"),
    ("DOS MILLONES CUATROCIENTOS TREINTA Y OCHO MIL TREINTAYCINCO CON 30/100 SOLES", "2438035.30"),
    ("OCHOCIENTOS MIL Y 00/100 SOLES", "800000.00"),
    ("CUARENTA Y DOS MILLONES SEISCIENTOS NOVENTA Y SEIS MIL CUATROCIENTOS NOVENTA CON 33/100 SOLES", "42696490.33"),
])
def test_amounts_in_words(words, amount):
    assert amount_in_words(words) == Decimal(amount)


@pytest.mark.parametrize("words, amount", [
    ("Ciento Treintaicuatro Mil ciento veintinueve con 45/100 Soles", "134129.45"),
    ("Son: CUATROCIENTOS TREINTA Y SIETE MIL SEIS CIENTOS OCHENTA Y UNO CON 38/100 SOLES", "437681.38"),
    ("SEISCIENTOS CUATRO MIL TRESCIENTOS VEINTI CUATRO CON 50/100 SOLES", "604324.50"),
    ("seis cientos echenta y cinco mil seiscientos ochenta y dos con 75/100 soles", "685682.75"),
    ("UN M!LLÓN SEISCIENTOS CUARENTA Y DOS MIL SEISCIENTOS NOVENTA CON 61/100 SOLES", "1642690.61"),
])
def test_spellings_of_real_bases(words, amount):
    assert amount_in_words(words) == Decimal(amount)


def test_ocr_bracket_inside_the_parentheses():
    text = ("asciende a la suma de s/ 457,991.62 (cuatrocientos ]\n cincuenta y siete mil novecientos noventa y uno "
            "con 62/100 soles), incluidos")
    start = text.index("457")
    assert check(text, start, start + len("457,991.62"), Decimal("457991.62")) is None


@pytest.mark.parametrize("words", [
    "TRESCIENTOS DIECIOCHO MIL SEISCIENTOS NOVENTA Y CINCO MIL CON 96/100 SOLES",  # "mil" twice in the bases
    "SETECIENTOS OCHENTA Y OCHO DOSCIENTOS TREINTA Y NUEVE CON 56/100 SOLES",      # "mil" missing
    "SIECIENTOS CINCO MIL CUARENTA Y SEIS CON 06/100 SOLES",                       # seis- or setecientos?
    "incluidos los impuestos de ley",
    "Ver Anexo N° 3",
])
def test_words_that_are_no_amount_give_nothing(words):
    assert amount_in_words(words) is None


def test_words_after_the_figure():
    text = "equivalente a Si 4,823,130.47\n (Cuatro Millones Ochocientos Veintinueve Mil Ciento Treinta con 42100 Soles), en la"
    start = text.index("4,823")
    assert check(text, start, start + len("4,823,130.47"), Decimal("4823130.47")) == Decimal("4829130.42")


def test_words_before_the_figure():
    text = ("asciende a la suma de doscientos sesenta y seis mil ochocientos diecisiete con 69/100 soles "
            "(S/ 266,817.69), incluidos los impuestos")
    start = text.index("266,817")
    assert words_around(text, start, start + 10).startswith("doscientos")
    assert check(text, start, start + 10, Decimal("266817.69")) is None


def test_unreadable_cents_compare_only_the_soles():
    text = "equivalente a SI. 574, 098.80\n (Quinientos Setenta y Cuatro mil Noventa y Ocho Con 801 00 Soles),enla"
    start = text.index("574")
    assert check(text, start, start + len("574, 098.80"), Decimal("574098.80")) is None
    assert check(text, start, start + len("574, 098.80"), Decimal("574099.80")) == Decimal("574098")


def test_figure_without_words():
    text = "La cuantía asciende a S/ 266,817.69 (incluido IGV). El plazo"
    start = text.index("266")
    assert check(text, start, start + 10, Decimal("266817.69")) is None
