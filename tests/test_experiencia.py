from decimal import Decimal
from pathlib import Path

import pytest

from seace_monitor.experiencia import DOUBTFUL, NOT_FOUND, read

FIXTURES = Path(__file__).parent / "fixtures" / "experiencia"


def bases(nid: str) -> str:
    """The requisito "Experiencia del postor en la especialidad" of a real bases, as pdftotext -layout gives it."""
    return (FIXTURES / f"{nid}.txt").read_text(encoding="utf-8")


def test_amount_years_count_and_specialty():
    result = read(bases("1224622"), Decimal("416563.59"))
    assert (result["monto"], result["veces_cuantia"], result["anios"]) == ("416563.59", "1.000", 20)
    assert result["cuenta_desde"] == "acta de recepción"
    assert (result["especialidad"], result["subespecialidades"]) == ("Viales, Puertos y afines", ["Obras rurales"])
    assert result["cita"].startswith("El postor debe acreditar un monto facturado acumulado")
    assert result["revisar"] is None


def test_specialty_in_a_table_without_colons():
    text = ("EXPERIENCIA DEL POSTOR EN LA ESPECIALIDAD\n Requisitos:\n"
            " El postor debe acreditar un monto facturado acumulado equivalente a S/ 1,000,000.00, en la ejecución\n"
            " de obras en la especialidad durante los veinte años anteriores.\n"
            " Se considera la siguiente especialidad y subespecialidades como experiencia del postor:\n"
            "      Especialidad              Subespecialidad             Tipologías\n"
            "      Especialidad        Represas, irrigaciones y afines\n"
            "      Subespecialidad     Infraestructura de Riego\n"
            "Acreditación:\n")
    result = read(text, Decimal("1000000.00"))
    assert (result["especialidad"], result["subespecialidades"]) == (
        "Represas, irrigaciones y afines", ["Infraestructura de Riego"])


def test_several_subspecialties():
    assert read(bases("1233771"), Decimal("4373954.19"))["subespecialidades"] == ["OBRAS VIALES", "OBRAS RURALES"]


@pytest.mark.parametrize("nid, cuantia", [("1247680", "9435623.66"), ("1256289", "443276.42")])
def test_times_the_cuantia(nid, cuantia):
    # "UNA (1) VEZ LA CUANTÍA DE LA CONTRATACIÓN", "[01 Una Vez La Cuantía De La Contratación]"
    result = read(bases(nid), Decimal(cuantia))
    assert (result["veces"], result["monto"], result["veces_cuantia"]) == ("1", cuantia, "1.000")


def test_times_without_a_cuantia_keeps_the_times():
    result = read(bases("1247680"))
    assert (result["veces"], result["monto"], result["revisar"]) == ("1", None, None)


@pytest.mark.parametrize("nid, cuantia, monto, veces", [
    ("1219930", "1254597.62", "1254597.62", "1.000"),  # "[1’254,597.62 (UN MILLON ...]" without S/
    ("1252080", "753950.56", "678555.50", "0.900"),    # the amount in words first
    ("1252370", "6256173.91", "4200806.25", "0.671"),  # "S/ 4 200 806.25"
    ("1242539", "788239.56", "800000.00", "1.015"),    # more than the cuantía
])
def test_amounts_as_the_bases_write_them(nid, cuantia, monto, veces):
    result = read(bases(nid), Decimal(cuantia))
    assert (result["monto"], result["veces_cuantia"]) == (monto, veces)


@pytest.mark.parametrize("nid, cuantia, monto, anios, especialidad", [
    ("1255957", "318695.96", "318695.96", 25, "Represas, Irrigaciones."),  # "Reguisitos:", "Especialidad . |"
    ("1239040", "766396.87", "766396.87", 25, "SANEAMIENTO Y AFINES"),     # no "Requisitos", "5/ 766,396.87"
    ("1234676", "4829130.42", "4823130.47", 25, "wiales, Puertos"),       # "Regquisios:", "Si 4,823,130.47"
    ("1243139", "1071882.45", "1071882.45", 25, "EDIFICACIONES Y AFINES"),
])
def test_chapter_iii_read_by_ocr(nid, cuantia, monto, anios, especialidad):
    result = read(bases(nid), Decimal(cuantia))
    assert (result["monto"], result["anios"], result["especialidad"]) == (monto, anios, especialidad)
    assert result["cuenta_desde"] == "acta de recepción"


def test_digits_misread_by_ocr_are_caught_by_the_words():
    result = read(bases("1234676"), Decimal("4829130.42"))
    assert (result["monto"], result["monto_letras"]) == ("4823130.47", "4829130.42")
    assert read(bases("1243139"), Decimal("1071882.45"))["monto_letras"] is None


def test_a_figure_far_from_the_cuantia_goes_to_a_person():
    # 1240273: OCR read "2´338,423.65" as 2,338.42
    result = read(bases("1224622"), Decimal("416563590.00"))
    assert (result["monto"], result["revisar"]) == ("416563.59", DOUBTFUL)


def test_unreadable_digits_are_taken_from_the_words():
    text = ("EXPERIENCIA DEL POSTOR EN LA ESPECIALIDAD.\n Requisitos:\n El postor debe acreditar un monto facturado "
            "acumulado no menor a S/ 2476 757 90 (Dos\n millones cuatrocientos setenta y seis mil setecientos cincuenta "
            "y siete con 90/100 soles),\n correspondiente a la ... de obras")  # 1253839, OCR
    result = read(text, Decimal("2476757.90"))
    assert (result["monto"], result["monto_de_letras"], result["revisar"]) == ("2476757.90", True, None)


def test_a_space_after_the_decimal_point():
    text = ("EXPERIENCIA DEL POSTOR EN LA ESPECIALIDAD\n Requisitos:\n El postor debe acreditar un monto facturado "
            "acumulado equivalente a S/ 491, 212. 88 (Cuatrocientos\n Noventa y Un Mil Doscientos Doce con 88/100 "
            "Soles), en la ejecución")  # 1252377
    assert read(text, Decimal("491212.88"))["monto"] == "491212.88"


def test_ten_years_in_words():
    assert read(bases("1256289"), Decimal("443276.42"))["anios"] == 10


def test_acreditacion_of_the_scoring_factor_is_not_requisitos():
    # 1248264: chapter IV quotes the requirement's name and ends its block with "Acreditación:"
    factor = ("se considera la “Experiencia del Postor en la especialidad”,\n durante veinticinco años anteriores "
              "40 puntos\n fecha de la conformidad M>= S/ 2,671,056.04 y < S/ 4,006,584.06:\n\n Acreditación: 30 puntos")
    assert read(factor)["revisar"] == NOT_FOUND


def test_chapter_iv_quoting_the_requirement_is_not_it():
    # 1252300: the factor cites "requisito de calificación “Experiencia del Postor en la Especialidad”"
    factor = ("requisito de calificación “Experiencia del Postor en la Especialidad”,\n durante los veinticinco (25) "
              "años M>= S/ 5,500,000.00 y <\n Dicho monto debe ser en exceso al acreditado para\n cumplir el requisito "
              "de calificación obligatoria.")
    assert read(factor)["revisar"] == NOT_FOUND


def test_the_sentence_after_many_blank_layout_lines():
    # 1238269: the layout pads the block with blank lines before the sentence
    text = ("EXPERIENCIA DEL POSTOR\n EN LA ESPECIALIDAD\n\n\n Requisitos:\n" + "\n" * 12 + " " * 700 +
            "\n El postor debe acreditar un monto facturad\n o acumulado equivalenie a S/ 2,246,870.83 en la ejecución")
    assert read(text, Decimal("2246870.83"))["monto"] == "2246870.83"


def test_ocr_noise_under_the_title_gives_no_amount():
    noise = "EXPERIENCIA DEL POSTOR EN LA ESPECIALIDAD\n Reguisitos\n '¡X=_,o_gg'mf¡ ;\n 77 E ve <y 7A 1,832,698.69\n"
    assert read(noise)["monto"] is None


def test_scoring_factor_of_chapter_iv_is_not_the_requirement():
    factor = ("F. EXPERIENCIA ADICIONAL DEL POSTOR EN LA ESPECIALIDAD   PUNTAJE / METODOLOGÍA\n Evaluación: [45] puntos\n"
              " El postor debe acreditar un monto facturado acumulado equivalente a S/ 300,000.00")
    assert read(factor)["revisar"] == NOT_FOUND
