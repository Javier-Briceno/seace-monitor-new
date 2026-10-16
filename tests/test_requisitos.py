from decimal import Decimal

import pytest

from seace_monitor import requisitos

# the standard bases describe each factor first and close the chapter with the CUADRO RESUMEN
CHAPTER_IV = ("CAPÍTULO IV\nFACTORES DE EVALUACIÓN\n" + "x\n" * 30 + "\f"
              "A. EXPERIENCIA ESPECÍFICA ADICIONAL DEL PERSONAL CLAVE\nEvaluación: un año adicional ...\n\f"
              "M. EXPERIENCIA ADICIONAL DEL POSTOR EN LA ESPECIALIDAD\nS/ 5,575,000.00 a más: 60 puntos\n" + "y\n" * 800 +
              "CUADRO RESUMEN FACTORES DE EVALUACIÓN\nA. EXPERIENCIA ESPECÍFICA ADICIONAL DEL PERSONAL CLAVE   40 puntos\n"
              "M. EXPERIENCIA ADICIONAL DEL POSTOR EN LA ESPECIALIDAD   60 puntos\nPUNTAJE TOTAL   100 puntos\n"
              "4.1. EVALUACIÓN ECONÓMICA (Puntaje Máximo: 100 Puntos)\n")
CHAPTER_III = ("CAPÍTULO III\nREQUISITOS DE CALIFICACIÓN\nB.2 EXPERIENCIA DEL PERSONAL CLAVE\n"
               "Residente de obra   24 meses\nCAPÍTULO IV\n")
SUMMARY = {"factores": [{"factor": "Experiencia específica adicional del personal clave", "puntos": 40},
                        {"factor": "Experiencia adicional del postor en la especialidad", "puntos": 60}]}


def files_with(tmp_path, text):
    path = tmp_path / "BASES.pdf"
    path.write_bytes(b"")
    requisitos.ia_path(path).write_text(text, encoding="utf-8")
    return [path]


def answer_for(factors, personal):
    def ask(key, prompt):
        if "capítulo IV" in prompt:
            return {"factores": factors}, Decimal("0.004")
        return {"personal": personal}, Decimal("0.002")
    return ask


def test_factors_match_the_summary_table_and_get_their_own_page(tmp_path):
    factors = [{"letra": "A", "nombre": "EXPERIENCIA ESPECÍFICA ADICIONAL DEL PERSONAL CLAVE", "puntaje_maximo": 40},
               {"letra": "M", "nombre": "EXPERIENCIA ADICIONAL DEL POSTOR EN LA ESPECIALIDAD", "puntaje_maximo": 50}]
    charged = []
    result = requisitos.read_files(files_with(tmp_path, CHAPTER_IV), "clave", SUMMARY, None,
                                   answer_for(factors, []), charged.append)
    assert [(f["factor"], f["comprobado"], f["pagina"]) for f in result["factores"]] == [
        ("Experiencia específica adicional del personal clave", True, 2),
        ("Experiencia adicional del postor en la especialidad", False, 3)]
    assert charged == [Decimal("0.004")] and result["pagina_factores"] == 1
    assert result["archivo_factores"] == "BASES.pdf"


def test_personal_is_checked_by_its_months_in_order(tmp_path):
    reading = {"personal": [{"cargo": "Residente de obra", "meses": 24}]}
    ok = requisitos.read_files(files_with(tmp_path, CHAPTER_III), "clave", None, reading,
                               answer_for([], [{"cargo": "Residente de obra", "experiencia_meses": 24}]))
    off = requisitos.read_files(files_with(tmp_path, CHAPTER_III), "clave", None, reading,
                                answer_for([], [{"cargo": "Residente de obra", "experiencia_meses": 36}]))
    assert ok["personal_comprobado"] and not off["personal_comprobado"]
    assert ok["factores"] == [] and ok["pagina_personal"] == 1 and ok["archivo_personal"] == "BASES.pdf"


def test_bases_without_either_chapter_ask_nothing(tmp_path):
    def ask(key, prompt):
        raise AssertionError("asked without a chapter")
    result = requisitos.read_files(files_with(tmp_path, "ANEXO N° 1\n" * 50), "clave", None, None, ask)
    assert result["revisar"] == requisitos.NOT_FOUND


def test_an_unusable_answer_is_charged_and_leaves_the_bases_for_later(tmp_path):
    charged = []
    with pytest.raises(requisitos.RequisitosError):
        requisitos.read_files(files_with(tmp_path, CHAPTER_IV), "clave", SUMMARY, None,
                              lambda key, prompt: (None, Decimal("0.003")), charged.append)
    assert charged == [Decimal("0.003")]


def test_a_chapter_answered_with_nothing_goes_to_a_person(tmp_path):
    result = requisitos.read_files(files_with(tmp_path, CHAPTER_IV), "clave", SUMMARY, None, answer_for([], []))
    assert result["revisar"] == requisitos.EMPTY


def test_no_request_once_the_cap_is_reached(tmp_path):
    def ask(key, prompt):
        raise AssertionError("asked over the cap")
    with pytest.raises(requisitos.SpendingCap):
        requisitos.read_files(files_with(tmp_path, CHAPTER_IV + CHAPTER_III), "clave", SUMMARY, None, ask,
                              may_spend=lambda: False)


def test_the_general_sections_chapter_iii_is_not_the_requirements(tmp_path):
    general = ("CAPÍTULO III\nDEL CONTRATO\nEl reemplazo del personal clave procede por caso fortuito.\n" + "z\n" * 40 +
               "CAPÍTULO IV\nCONFORMIDAD\n\f")
    asked = []

    def ask(key, prompt):
        asked.append(prompt)
        return {"personal": [{"cargo": "Residente de obra", "experiencia_meses": 24}]}, Decimal("0.002")

    requisitos.read_files(files_with(tmp_path, general + CHAPTER_III), "clave", None, None, ask)
    assert len(asked) == 1 and "B.2 EXPERIENCIA DEL PERSONAL CLAVE" in asked[0] and "caso fortuito" not in asked[0]


def test_a_bases_once_started_is_finished_even_if_the_cap_is_reached_between_chapters(tmp_path):
    room = iter([True, False])
    asked = []

    def ask(key, prompt):
        asked.append(prompt)
        if "capítulo IV" in prompt:
            return {"factores": [{"nombre": "GESTIÓN DE CALIDAD", "puntaje_maximo": 10}]}, Decimal("0.004")
        return {"personal": [{"cargo": "Residente de obra", "experiencia_meses": 24}]}, Decimal("0.002")

    result = requisitos.read_files(files_with(tmp_path, CHAPTER_IV + CHAPTER_III), "clave", None, None, ask,
                                   may_spend=lambda: next(room))
    assert len(asked) == 2 and result["factores"] and result["personal"]


def test_chapter_iii_starts_near_the_personal_clave_after_a_long_requerimiento(tmp_path):
    text = ("CAPÍTULO III\nREQUERIMIENTO\nREQUISITOS DE CALIFICACIÓN del contratista ...\n" + "especificación técnica\n" * 4000
            + "B. CAPACIDAD TÉCNICA Y PROFESIONAL\nB.1 CALIFICACIONES DEL PERSONAL CLAVE\nIngeniero civil\n"
            "B.2 EXPERIENCIA DEL PERSONAL CLAVE\nResidente de obra   24 meses\nCAPÍTULO IV\n")
    start, stop = requisitos.chapter_iii(text)
    assert text[start:].startswith("CAPACIDAD TÉCNICA") and "B.2 EXPERIENCIA" in requisitos.marked(text, start, stop)
