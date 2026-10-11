from pathlib import Path

import pytest

from seace_monitor.factores import NOT_FOUND, read

FIXTURES = Path(__file__).parent / "fixtures" / "factores"


def bases(nid: str) -> str:
    """Chapter IV (evaluación de ofertas) of a real bases up to 4.2, as pdftotext -layout gives it."""
    return (FIXTURES / f"{nid}.txt").read_text(encoding="utf-8")


def points(result: dict) -> list[tuple[str, int]]:
    return [(f["factor"], f["puntos"]) for f in result["factores"]]


def test_factors_of_the_summary_table():
    result = read(bases("1252316"))  # the table runs over a page break with footnotes
    assert points(result) == [
        ("Experiencia específica adicional del personal clave", 40), ("Sostenibilidad ambiental", 5),
        ("Integridad en la contratación pública", 5), ("Gestión de calidad", 10), ("Seguridad y salud", 5),
        ("Experiencia adicional del postor en la especialidad", 35)]
    assert (result["total"], result["suma"], result["minimo_tecnico"], result["avisos"], result["revisar"]) == (
        100, 100, 70, [], None)


def test_a_factor_that_does_not_apply_is_left_out():
    result = read(bases("1214818"))  # OCR; "H. PLAN DE EJECUCIÓN BIM  NO CORRESPONDE", "[E. GESTIÓN DE CALIDAD?"
    assert [f["letra"] for f in result["factores"]] == list("ABCDEFG")
    assert (result["suma"], result["revisar"]) == (100, None)


def test_points_unreadable_in_the_table_come_from_the_description():
    result = read(bases("1211449"))  # OCR left "[; puntos" and "|ag puntos" in the table
    assert dict(points(result))["Experiencia específica adicional del personal clave"] is not None
    assert (result["suma"], result["total"]) == (100, 100)


@pytest.mark.parametrize("nid", ["1211842", "1212945"])
def test_more_real_tables(nid):
    result = read(bases(nid))
    assert result["suma"] == result["total"] == 100 and result["revisar"] is None


def test_a_sum_that_is_not_the_total():
    text = ("4.1. EVALUACIÓN TÉCNICA\n"
            " A. EXPERIENCIA ESPECÍFICA ADICIONAL DEL PERSONAL CLAVE     PUNTAJE\n Evaluación:   60 puntos\n"
            " B. SOSTENIBILIDAD AMBIENTAL\n Evaluación:   50 puntos\n"
            "      CUADRO RESUMEN FACTORES DE EVALUACIÓN\n"
            " A. EXPERIENCIA ESPECÍFICA ADICIONAL DEL PERSONAL CLAVE     60 puntos   COMITÉ\n"
            " B. SOSTENIBILIDAD AMBIENTAL                                50 puntos   COMITÉ\n"
            " PUNTAJE TOTAL                                              100 puntos\n")
    assert read(text)["avisos"] == [{"aviso": "suma_distinta_total", "suma": 110, "total": 100}]


def test_table_and_description_disagree():
    # the description says 10; the table's 15 leaves the sum at 105, so the description's figure is used
    text = bases("1252316").replace("10 PUNTOS                          COMITÉ", "15 PUNTOS                          COMITÉ")
    result = read(text)
    assert result["avisos"] == [{"aviso": "puntaje_distinto", "factor": "Gestión de calidad", "cuadro": 15,
                                 "descripcion": 10}]
    assert result["suma"] == 100


def test_sub_factors_of_the_personal_clave():
    result = read(bases("1240182"))  # "B.1 FORMACIÓN ACADÉMICA ADICIONAL", "B.2 CERTIFICACIONES ADICIONALES"
    assert [(f["letra"], f["puntos"]) for f in result["factores"]][:3] == [("A", 20), ("B.1", 5), ("B.2", 5)]
    assert result["factores"][1]["factor"] == "Formación académica adicional del personal clave"
    assert (result["suma"], result["total"], result["avisos"]) == (100, 100, [])


def test_the_payment_summary_of_the_contract_is_not_the_factors_table():
    text = "CUADRO RESUMEN DEL PAGO AL CONTRATISTA\n A. FACTURA  10 puntos\n PUNTAJE TOTAL 100 puntos\n"
    assert read(text)["revisar"] == NOT_FOUND


TEMPLATE_TABLE = (
    "      CUADRO RESUMEN FACTORES DE EVALUACIÓN\n"
    " A. EXPERIENCIA ESPECÍFICA ADICIONAL DEL PERSONAL CLAVE     40 puntos   COMITÉ\n"
    " E. CAPACITACIÓN                                            [Como máximo 10]   COMITÉ\n"  # 1236706
    " G. MEJORA AL REQUERIMIENTO                                 [Como máximo 15]   COMITÉ\n"
    " K. SEGURIDAD Y SALUD                                       60 puntos   COMITÉ\n"
    " N. PLAN DE EJECUCIÓN BIM\n"
    " PUNTAJE TOTAL                                              100 puntos\n")


def test_factors_left_with_the_template_text():
    result = read(TEMPLATE_TABLE)
    assert [f["letra"] for f in result["factores"]] == ["A", "K"]
    assert result["avisos"] == [{"aviso": "factor_sin_rellenar", "factores": ["Capacitación", "Mejora al requerimiento"]}]
    assert (result["suma"], result["revisar"]) == (100, None)


def test_a_word_table_without_letters():
    # 1214109 (DOCX): every cell on its own line, the list letters gone
    text = ("CUADRO RESUMEN FACTORES DE EVALUACIÓN\nFACTORES DE EVALUACIÓN FACULTATIVOS\nPUNTAJE\nTIPO DE EVALUADOR\n"
            "EXPERIENCIA ESPECÍFICA ADICIONAL DEL PERSONAL CLAVE\n[35] puntos\nCOMITÉ\n"
            "SOSTENIBILIDAD AMBIENTAL\n[05] puntos\nCOMITÉ\nSOSTENIBILIDAD SOCIAL\nNO CORRESPONDE\nNO CORRESPONDE\n"
            "GESTIÓN DE CALIDAD \n[60] puntos\nCOMITÉ\nPUNTAJE TOTAL\n100 puntos\n")
    result = read(text)
    assert [(f["factor"], f["puntos"]) for f in result["factores"]] == [
        ("Experiencia específica adicional del personal clave", 35), ("Sostenibilidad ambiental", 5),
        ("Gestión de calidad", 60)]
    assert (result["suma"], result["revisar"]) == (100, None)


def test_figures_with_decimals():
    # 1256527: "05.00 puntos", "100.0 puntos"
    text = ("      CUADRO RESUMEN FACTORES DE EVALUACIÓN\n"
            " B. SOSTENIBILIDAD AMBIENTAL                05.00 puntos   COMITÉ\n"
            " D. INTEGRIDAD EN LA CONTRATACION PÚBLICA   05.00 Puntos   COMITÉ\n"
            " F. GESTIÓN DE CALIDAD                      45.00 Puntos   COMITÉ\n"
            " K. SEGURIDAD Y SALUD                       45.00 Puntos   COMITÉ\n"
            " PUNTAJE TOTAL                              100.0 puntos\n")
    result = read(text)
    assert [f["puntos"] for f in result["factores"]] == [5, 5, 45, 45]
    assert (result["total"], result["suma"], result["avisos"]) == (100, 100, [])


def test_a_factor_of_several_practices_states_only_the_first_in_its_description():
    # 1255892: k.1 "Evaluación: [5] puntos", k.3 another 10; the table gives 15
    text = ("4.1. EVALUACIÓN TÉCNICA\n E. SEGURIDAD Y SALUD   PARA SU ASIGNACIÓN\n Evaluación: [5] puntos\n"
            " k.3 Uso de Tecnología   [10] puntos\n"
            "      CUADRO RESUMEN FACTORES DE EVALUACIÓN\n"
            " A. EXPERIENCIA ESPECÍFICA ADICIONAL DEL PERSONAL CLAVE     85 puntos   COMITÉ\n"
            " E. SEGURIDAD Y SALUD                                       15 puntos   COMITÉ\n"
            " PUNTAJE TOTAL                                              100 puntos\n")
    assert read(text)["avisos"] == []


def test_bases_without_chapter_iv():
    assert read("CAPÍTULO III REQUERIMIENTO")["revisar"] == NOT_FOUND


def test_the_table_is_found_without_the_chapter_title():
    # Word files lose "4.2." and OCR can miss the title page
    text = bases("1252316").replace("CAPÍTULO IV", "").replace("4.2.", "")
    assert read(text)["suma"] == 100
