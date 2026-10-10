from decimal import Decimal
from pathlib import Path

import pytest

from seace_monitor.experiencia import NOT_FOUND, read

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


def test_ten_years_in_words():
    assert read(bases("1256289"), Decimal("443276.42"))["anios"] == 10


def test_scoring_factor_of_chapter_iv_is_not_the_requirement():
    factor = ("F. EXPERIENCIA ADICIONAL DEL POSTOR EN LA ESPECIALIDAD   PUNTAJE / METODOLOGÍA\n Evaluación: [45] puntos\n"
              " El postor debe acreditar un monto facturado acumulado equivalente a S/ 300,000.00")
    assert read(factor)["revisar"] == NOT_FOUND
