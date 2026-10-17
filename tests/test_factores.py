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


def test_a_figure_below_a_factor_that_does_not_apply_is_not_its_own():
    # 1256463: Seguridad y salud's "[15] PUNTOS" sits on the line above its name, below "NO CORRESPONDE"
    text = ("      CUADRO RESUMEN FACTORES DE EVALUACIÓN\n"
            " A. EXPERIENCIA ESPECÍFICA ADICIONAL DEL PERSONAL CLAVE     [85] PUNTOS   COMITÉ\n"
            " J. PLANIFICACIÓN DETALLADA        NO CORRESPONDE   JURADO\n"
            "                                   [15] PUNTOS\n"
            " K. SEGURIDAD Y SALUD                               COMITÉ34\n"
            " PUNTAJE TOTAL                                      100 puntos\n")
    result = read(text)
    assert [(f["factor"], f["puntos"]) for f in result["factores"]] == [
        ("Experiencia específica adicional del personal clave", 85), ("Seguridad y salud", 15)]
    assert (result["suma"], result["avisos"]) == (100, [])


def test_bases_without_chapter_iv():
    assert read("CAPÍTULO III REQUERIMIENTO")["revisar"] == NOT_FOUND


def test_rows_marked_with_bullets():
    # 1243793: the entity's own text layer turned the letters into "o"
    text = ("RESUMEN FACTORES DE EVALUACIÓN\n FACTORES DE EVALUACIÓN PUNTAJE TIPO DE EVALUADOR\n FACULTATIVOS\n"
            " A. EXPERIENCIA ESPECÍFICA 30 puntos COMITÉ\n ADICIONAL DEL PERSONAL\n CLAVE\n"
            " B. SOSTENIBILIDAD AMBIENTAL 5 puntos COMITÉ\n o INTEGRIDAD EN LA 5 puntos COMITÉ\n CONTRATACION PÚBLICA\n"
            " o GESTIÓN DE CALIDAD 30 puntos COMITÉ\n o SEGURIDAD Y SALUD 15 puntos COMITÉ\n"
            " o EXPERIENCIA ADICIONAL DEL 15 puntos COMITÉ\n POSTOR EN LA ESPECIALIDAD\n PUNTAJE TOTAL 100 puntos26\n")
    result = read(text)
    assert [f["puntos"] for f in result["factores"]] == [30, 5, 5, 30, 15, 15]
    assert result["factores"][5]["factor"] == "Experiencia adicional del postor en la especialidad"
    assert (result["suma"], result["revisar"]) == (100, None)


def test_row_letters_as_ocr_leaves_them():
    # 1255060 and 1239090: "A EXPERIENCIA" without its dot, "lA." and "|F." with a stray stroke, "Dal puntos"
    text = ("4.1. EVALUACIÓN TÉCNICA\n G. EXPERIENCIA ADICIONAL DEL POSTOR EN LA ESPECIALIDAD   PUNTAJE\n"
            " Evaluación:   30 puntos\n"
            "RESUMEN FACTORES DE EVALUACIÓN\n FACTORES DE EVALUACIÓN TIPO DE\n FACULTATIVOS PUNTAJE EVALUADOR\n"
            " lA. EXPERIENCIA ESPECÍFICA\n ADICIONAL DEL PERSONAL [40] puntos COMITÉ\n"
            " B SOSTENIBILIDAD AMBIENTAL\n CLAVE\n [5] puntos COMITÉ\n"
            " |F. GESTIÓN DE CALIDAD* 15] puntos COMITÉ\n F. SEGURIDAD Y SALUD [10] puntos COMITÉ\n"
            " G EXPERIENCIA ADICIONAL\n POSTOR EN LA ESPECIALIDAD\n DEL\n Dal puntos CONITE\n"
            " PUNTAJE TOTAL 100 puntos*\n")
    result = read(text)
    assert [(f["letra"], f["puntos"]) for f in result["factores"]] == [("A", 40), ("B", 5), ("F", 15), ("F", 10), ("G", 30)]
    assert (result["suma"], result["revisar"]) == (100, None)


def test_a_header_line_naming_bim_is_no_row():
    # 1253468: the rows add up to 115; the header "OBLIGATORIO EN CASO DE USAR BIM" must not make it unreadable
    text = ("      CUADRO RESUMEN FACTORES DE EVALUACIÓN\n"
            " A. EXPERIENCIA ESPECÍFICA ADICIONAL DEL PERSONAL CLAVE     65 puntos   COMITÉ\n"
            " K. SEGURIDAD Y SALUD                                       50 puntos   COMITÉ\n"
            " M. EXPERIENCIA ADICIONAL DEL\n NO CORRESPONDE COMITÉ/JURADO\n POSTOR EN LA ESPECIALIDAD\n"
            " FACTOR DE EVALUACIÓN\n OBLIGATORIO EN CASO DE USAR BIM\n"
            " N. PLAN DE EJECUCIÓN BIM     NO CORRESPONDE   COMITÉ\n"
            " PUNTAJE TOTAL                                              100 puntos\n")
    assert read(text)["avisos"] == [{"aviso": "suma_distinta_total", "suma": 115, "total": 100}]


def test_a_word_table_that_lost_only_some_letters():
    # 1249332 (DOCX): "A." and "B.1" kept, the rows below them without a letter
    text = ("RESUMEN FACTORES DE EVALUACIÓN\nFACTOR DE EVALUACIÓN OBLIGATORIO \nPUNTAJE \n"
            "A. EXPERIENCIA EN LA ESPECIALIDAD ADICIONAL DEL PERSONAL CLAVE \n35 puntos \n"
            "FACTORES DE EVALUACIÓN FACULTATIVOS \nPUNTAJE \nB.1 FORMACIÓN ACADÉMICA ADICIONAL DEL PERSONAL CLAVE \n"
            "35 puntos\nC. SOSTENIBILIDAD AMBIENTAL \nNO CORRESPONDE \nINTEGRIDAD EN LA CONTRATACION PÚBLICA   \n"
            "20 puntos \nCAPACITACIÓN  \nNO CORRESPONDE \nGESTIÓN DE CALIDAD \n10 puntos\nPUNTAJE TOTAL\n100 puntos\n")
    result = read(text)
    assert [(f["factor"], f["puntos"]) for f in result["factores"]] == [
        ("Experiencia específica adicional del personal clave", 35),
        ("Formación académica adicional del personal clave", 35),
        ("Integridad en la contratación pública", 20), ("Gestión de calidad", 10)]
    assert (result["suma"], result["revisar"]) == (100, None)


def test_the_table_is_found_without_the_chapter_title():
    # Word files lose "4.2." and OCR can miss the title page
    text = bases("1252316").replace("CAPÍTULO IV", "").replace("4.2.", "")
    assert read(text)["suma"] == 100


def test_a_row_whose_letter_lost_its_dot_after_a_blank_line():
    # OCR of 1255060: "B SOSTENIBILIDAD" was taken as a row twice, once from the blank line before it
    text = ("CUADRO RESUMEN FACTORES DE EVALUACIÓN\n\n"
            "                 FACULTATIVOS                  PUNTAJE        EVALUADOR\n\n"
            "   A EXPERIENCIA ESPECÍFICA\n\n"
            "      ADICIONAL DEL PERSONAL                   [90] puntos     COMITÉ\n\n"
            "   B SOSTENIBILIDAD AMBIENTAL\n\n"
            "                                               [10] puntos     COMITÉ\n\n"
            "            PUNTAJE TOTAL                      100 puntos\n")
    result = read(text)
    assert [(f["letra"], f["puntos"]) for f in result["factores"]] == [("A", 90), ("B", 10)]
    assert (result["suma"], result["revisar"]) == (100, None)


def test_a_row_crossed_out_by_hand_gives_no_points():
    # obra 1247797 as a vision model transcribes it: the entity struck sostenibilidad social out
    text = ("CUADRO RESUMEN FACTORES DE EVALUACIÓN\n"
            "FACTORES DE EVALUACIÓN FACULTATIVOS   PUNTAJE   TIPO DE EVALUADOR\n"
            "A. EXPERIENCIA ESPECÍFICA ADICIONAL DEL PERSONAL CLAVE   [35] puntos   COMITÉ/JURADO\n"
            "B. SOSTENIBILIDAD AMBIENTAL   [5] puntos   COMITÉ/JURADO\n"
            "[TACHADO] C. SOSTENIBILIDAD SOCIAL   [5] puntos   COMITÉ/JURADO\n"
            "D. INTEGRIDAD EN LA CONTRATACION PÚBLICA   [5] puntos   COMITÉ/JURADO\n"
            "F. GESTIÓN DE CALIDAD   [5] puntos   COMITÉ/JURADO\n"
            "K. SEGURIDAD Y SALUD   [10] puntos   COMITÉ/JURADO\n"
            "M. EXPERIENCIA ADICIONAL DEL POSTOR EN LA ESPECIALIDAD   [40] puntos   COMITÉ/JURADO\n"
            "PUNTAJE TOTAL   100 puntos\n")
    result = read(text)
    assert result["revisar"] is None and result["suma"] == 100
    assert "Sostenibilidad social" not in [f["factor"] for f in result["factores"]]


def test_points_written_without_the_word_puntos_in_one_line_rows():
    # obra 1233127
    text = ("CUADRO RESUMEN FACTORES DE EVALUACIÓN\n"
            "FACTORES DE EVALUACIÓN FACULTATIVOS   PUNTAJE   TIPO DE EVALUADOR\n"
            "A. EXPERIENCIA ESPECIFICA ADICIONAL DEL PERSONAL CLAVE   40   COMITÉ\n"
            "B. SOSTENIBILIDAD AMBIENTAL   5   COMITÉ\n"
            "C. INTEGRIDAD EN LA CONTRATACION PÚBLICA   5   COMITÉ\n"
            "D. GESTIÓN DE CALIDAD33   5   COMITÉ\n"
            "E. SEGURIDAD Y SALUD   20   COMITÉ\n"
            "F. EXPERIENCIA ADICIONAL DEL POSTOR EN LA ESPECIALIDAD   25   COMITÉ\n"
            "PUNTAJE TOTAL   100 puntos\n")
    result = read(text)
    assert [f["puntos"] for f in result["factores"]] == [40, 5, 5, 5, 20, 25] and result["suma"] == 100


def test_a_total_whose_figure_sits_above_its_words():
    # obra 1250792: the layout put "100" above "PUNTAJE TOTAL" and "puntos" below it
    text = ("                         CUADRO RESUMEN FACTORES DE EVALUACIÓN\n"
            "          FACTORES DE EVALUACIÓN FACULTATIVOS                               PUNTAJE          EVALUADOR\n"
            "  A. EXPERIENCIA ESPECÍFICA ADICIONAL DEL PERSONAL CLAVE                   40 puntos           COMITÉ\n"
            "  B. SOSTENIBILIDAD AMBIENTAL                                               10 puntos           COMITÉ\n"
            "  C. CAPACITACIÓN                                                           10 puntos           COMITÉ\n"
            "  D. GESTIÓN DE CALIDAD                                                     10 puntos           COMITÉ\n"
            "  E. EXPERIENCIA ADICIONAL DEL POSTOR EN LA ESPECIALIDAD                    30 puntos           COMITÉ\n"
            "                                                                               100\n"
            "     PUNTAJE TOTAL\n"
            "                                                                             puntos28\n")
    result = read(text)
    assert (result["revisar"], result["total"], result["suma"]) == (None, 100, 100)


def test_a_figure_with_a_stray_dot_before_puntos():
    # obra 1223633: "PUNTAJE TOTAL   100. puntos"
    text = ("CUADRO RESUMEN FACTORES DE EVALUACIÓN\n"
            "A. EXPERIENCIA ESPECÍFICA ADICIONAL DEL PERSONAL CLAVE   60 puntos   COMITÉ\n"
            "B. EXPERIENCIA ADICIONAL DEL POSTOR EN LA ESPECIALIDAD   40. puntos   COMITÉ\n"
            "PUNTAJE TOTAL   100. puntos\n")
    result = read(text)
    assert (result["revisar"], result["total"], result["suma"]) == (None, 100, 100)


def test_a_footnote_number_glued_to_the_evaluator_is_no_figure_and_como_maximo_completes_the_total():
    # 1251959: "COMITÉ/JURADO24" above "puntos", and "[Como máximo 05]" rows whose "puntos" sits lines apart
    text = ("EVALUACIÓN TÉCNICA\n    B. SOSTENIBILIDAD AMBIENTAL\n    Evaluación:\n    Se evaluará la certificación. 5 puntos\n"
            "CUADRO RESUMEN FACTORES DE EVALUACIÓN\n"
            "    A. EXPERIENCIA ESPECÍFICA\n"
            "       ADICIONAL DEL PERSONAL                     [50] puntos      COMITÉ/JURADO\n"
            "       CLAVE\n"
            "                                             [Como máximo 05]\n"
            "    B. SOSTENIBILIDAD AMBIENTAL                                    COMITÉ/JURADO24\n"
            "                                                  puntos\n"
            "    C. SOSTENIBILIDAD SOCIAL                 NO CORRESPONDE        COMITÉ/JURADO25\n"
            "    D. INTEGRIDAD       EN       LA          [Como máximo 05]\n"
            "                                                                   COMITÉ/JURADO\n"
            "       CONTRATACION PÚBLICA                       puntos\n"
            "    E. CAPACITACIÓN                              [10] puntos       COMITÉ/JURADO\n"
            "    F. GESTIÓN DE CALIDAD26                      [30] puntos       COMITÉ/JURADO\n"
            "    PUNTAJE TOTAL                                100 puntos\n")
    result = read(text)
    assert points(result) == [("Experiencia específica adicional del personal clave", 50),
                              ("Sostenibilidad ambiental", 5), ("Integridad en la contratación pública", 5),
                              ("Capacitación", 10), ("Gestión de calidad", 30)]
    assert result["avisos"] == [] and result["revisar"] is None



def test_both_template_choices_left_in_a_row_count_only_when_the_table_needs_them():
    # 1255735: "[Como máximo 5] puntos / NO CORRESPONDE", neither struck out, and the other rows add up to 100
    table = ("CUADRO RESUMEN FACTORES DE EVALUACIÓN\n"
             "A. EXPERIENCIA ESPECÍFICA ADICIONAL DEL PERSONAL CLAVE   50 puntos   COMITÉ\n"
             "B. SOSTENIBILIDAD AMBIENTAL   5 puntos   COMITÉ\n"
             "C. SOSTENIBILIDAD SOCIAL   [Como máximo 5] puntos / NO CORRESPONDE   COMITÉ/JURADO28\n"
             "D. INTEGRIDAD EN LA CONTRATACION PÚBLICA   5 puntos   COMITÉ\n"
             "E. CAPACITACIÓN   [...] puntos / NO CORRESPONDE   COMITÉ/JURADO\n"
             "F. GESTIÓN DE CALIDAD29   5 puntos   COMITÉ\n"
             "K. SEGURIDAD Y SALUD   5 puntos   COMITÉ\n"
             "M. EXPERIENCIA ADICIONAL DEL POSTOR EN LA ESPECIALIDAD   30 puntos   COMITÉ\n"
             "PUNTAJE TOTAL   100 puntos30\n")
    result = read(table)
    assert "Sostenibilidad social" not in dict(points(result)) and result["suma"] == 100
    assert result["avisos"] == [{"aviso": "factor_sin_rellenar", "factores": ["Sostenibilidad social"]}]
    needed = read(table.replace("30 puntos   COMITÉ", "25 puntos   COMITÉ"))
    assert dict(points(needed))["Sostenibilidad social"] == 5 and needed["suma"] == 100


def test_a_name_cut_by_a_page_break_is_not_taken_from_the_footnotes():
    # 1249275: "A. EXPERIENCIA ESPECÍFICA  35 puntos", then footnotes that name "el propio postor"
    text = ("CUADRO RESUMEN FACTORES DE EVALUACIÓN\n"
            "    A. EXPERIENCIA         ESPECÍFICA              35 puntos       COMITÉ\n\n"
            "24 El solo sello de cancelado, cuando ha sido colocado por el propio postor, no puede ser\n"
            "   considerado como una acreditación. Es válido el sello colocado por el cliente del postor\n"
            "MUNICIPALIDAD DISTRITAL DE PONTO\n"
            "       ADICIONAL DEL PERSONAL CLAVE\n"
            "    B. EXPERIENCIA ADICIONAL DEL\n\n"
            "MUNICIPALIDAD DISTRITAL DE PONTO\n"
            "       POSTOR EN LA ESPECIALIDAD                   65 puntos       COMITÉ\n"
            "    PUNTAJE TOTAL                                 100 puntos\n")
    assert points(read(text)) == [("Experiencia específica adicional del personal clave", 35),
                                  ("Experiencia adicional del postor en la especialidad", 65)]
