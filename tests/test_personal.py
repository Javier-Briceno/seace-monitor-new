from pathlib import Path

import pytest

from seace_monitor.personal import NOT_FOUND, NO_TIME, UNREADABLE, read, unknown_words

FIXTURES = Path(__file__).parent / "fixtures" / "personal"


def bases(nid: str) -> str:
    """The personal clave requirement of a real bases, as pdftotext -layout gives it."""
    return (FIXTURES / f"{nid}.txt").read_text(encoding="utf-8")


def cargos(result: dict) -> list[tuple[str, str]]:
    return [(p["cargo"], p["tiempo"]) for p in result["personal"]]


@pytest.mark.parametrize("nid, expected", [
    # the cargo in a column of short lines left of a long description that starts with the time
    ("1246310", [("Ing. Residente de Obra", "36 meses"),
                 ("Ing. Especialista de Seguridad y Prevención de Riesgos", "24 meses"), ("Ing. Ambiental", "12 meses")]),
    # the time in its own column, a page header inside the second row
    ("1221379", [("INGENIERO RESIDENTE DE OBRA", "36 meses"),
                 ("INGENIERO ESPECIALISTA DE SEGURIDAD EN OBRA Y SALUD EN EL TRABAJO", "12 meses"),
                 ("INGENIERO ESPECIALISTA EN CALIDAD", "12 meses")]),
    # "veinticuatro (24)" at the end of a line, "meses" at the start of the next
    ("1253813", [("RESIDENTE DE OBRA", "24 meses"), ("ESPECIALISTA EN SEGURIDAD Y SALUD OCUPACIONAL", "12 meses"),
                 ("ESPECIALISTA AMBIENTAL", "12 meses")]),
    # a column of professions next to the cargos
    ("1251235", [("Residente de Obra", "36 meses"), ("Especialista en Seguridad y Salud", "24 meses")]),
    ("1252080", [("Residente de Obra", "24 meses")]),
    # years, not months
    ("1233771", [("Residente de Obra", "3 años"), ("Especialista en Estructuras", "2 años"),
                 ("Especialista en Seguridad Salud y Medio Ambiente", "2 años")]),
    # one small table per cargo under "1. Residente de Obra"
    ("1244710", [("Residente de Obra", "24 meses"), ("Especialista en SSOMA", "12 meses")]),
    # the time in its own column and again in the description
    ("1224679", [("RESIDENTE DE OBRA", "24 meses")]),
    ("1223329", [("Residente de Obra", "24 meses"), ("Especialista en Seguridad y Salud Ocupacional", "12 meses")]),
    # "(12)" ends a line, "meses" opens the next after the profession column; the profession header on its own line
    ("1247868", [("RESIDENTE DE OBRA", "24 meses"),
                 ("ESPECIALISTA DE SEGURIDAD EN OBRA Y SALUD EN EL TRABAJO", "12 meses")]),
    # every time in its own column and again in the description ("doce (12) meses"), the rows a few lines apart
    ("1223688", [("RESIDENTE DE OBRA", "24 meses"), ("INGENIERO SSOMA", "12 meses"),
                 ("INGENIERO AMBIENTAL", "12 meses"), ("INGENIERO DE CALIDAD", "12 meses")]),
    # digital signature stamps (names replaced) in the cargo column
    ("1228370", [("RESIDENTE DE OBRA", "36 meses"), ("ESPECIALISTA DE CALIDAD", "12 meses"),
                 ("ESPECIALISTA AMBIENTAL", "12 meses"),
                 ("ESPECIALISTA DE SEGURIDAD EN OBRA Y SALUD EN EL TRABAJO", "12 meses"),
                 ("ESPECIALISTA SANITARIO", "12 meses")]),
    # "Se computa desde la colegiatura." of the time column, one word a line, inside the cargo column
    # a Word file: one cell a line, the cargo above the description that opens with the time
    ("1217898", [("Residente de Obra", "5 años"), ("Especialista en Seguridad en Obra y Salud Ocupacional", "4 años"),
                 ("Especialista Ambiental", "3 años"), ("Especialista en Calidad", "2 años")]),
    # "Desde la / Colegiatura" of the time column: its "la" lands inside "ESPECIALISTA DE SEGURIDAD"
    ("1255068", [("RESIDENTE DE OBRA", "2 años"), ("ESPECIALISTA DE CALIDAD", "1 año"),
                 ("ESPECIALISTA DE SEGURIDAD EN OBRA", "1 año")]),
    # "Especialis" on one line, "ta en" on the next
    ("1255345", [("Residente de Obra", "36 meses"), ("Especialista en Medio Ambiente", "12 meses"),
                 ("Especialista en Calidad", "12 meses"), ("Especialista en Seguridad", "12 meses")]),
    ("1235753", [("Residente de Obra", "36 meses"), ("Especialista Ambiental", "12 meses"),
                 ("Especialista de Seguridad en Obra y Salud en el Trabajo", "12 meses"),
                 ("Especialista en Calidad", "12 meses")]),
])
def test_cargos_and_times(nid, expected):
    result = read(bases(nid))
    assert cargos(result) == expected
    assert result["revisar"] is None


def test_a_table_over_two_pages_is_read_to_its_end():
    # OCR text: six cargos over a page break, far more than a few thousand characters of -layout lines
    result = read(bases("1252048"))
    assert [p["tiempo"] for p in result["personal"]] == ["2 años"] + ["1 año"] * 5
    assert result["personal"][-1]["cargo"] == "ESPECIALISTA EN SEGURIDAD EN OBRA"


def test_column_headers_and_project_title_repeated_on_every_page():
    result = read(bases("1254298"))  # "PRESUPUESTOS" holds "PUESTO", which once made its line a column header
    assert len(result["personal"]) == 11
    assert result["personal"][5]["cargo"] == "ESPECIALISTA EN COSTOS Y PRESUPUESTOS Y PROGRAMACION DE OBRA"
    assert result["personal"][-1] == {"cargo": "ARQUEOLOGO", "tiempo": "24 meses", "meses": 24}


def test_ten_cargos_over_two_pages():
    result = read(bases("1252956"))  # checked against the page images
    assert cargos(result) == [
        ("GERENTE DE OBRA", "36 meses"), ("RESIDENTE DE OBRA", "36 meses"), ("ESPECIALISTA EN ESTRUCTURAS", "24 meses"),
        ("ESPECIALISTA EN ARQUITECTURA", "24 meses"), ("ESPECIALISTA EN INSTALACIONES SANITARIAS", "18 meses"),
        ("ESPECIALISTA EN INSTALACIONES ELÉCTRICAS", "18 meses"),
        ("ESPECIALISTA EN ESTUDIO E IMPACTO AMBIENTAL, SEGURIDAD Y SALUD", "24 meses"),
        ("ESPECIALISTA EN COSTOS Y PRESUPUESTOS", "18 meses"), ("ARQUEÓLOGO", "18 meses"),
        ("ESPECIALISTA EN CONTROL DE CALIDAD", "24 meses")]


def test_words_that_say_another_time_than_the_digits():
    result = read(bases("1245936"))  # "treinta y seis (24) meses", "treinta y seis (12) meses"
    assert [p["tiempo"] for p in result["personal"]] == ["24 meses", "12 meses", "12 meses"]
    assert [(w["cifra"], w["letras"]) for w in result["avisos"]] == [(24, 36), (12, 36)]


def test_cargo_words_on_the_lines_of_a_description():
    result = read(bases("1248566"))  # "Residente de   Asistente de Residente o Supervisión, en ejecución de"
    assert cargos(result) == [("Residente de Obra", "24 meses"),
                              ("Especialista en Seguridad en Obra y Salud Ocupacional", "12 meses"),
                              ("Especialista Ambiental", "12 meses"), ("Especialista Calidad", "12 meses")]


def test_cargos_that_do_not_pair_with_the_times_go_to_a_person():
    text = ("B.2 EXPERIENCIA DEL PERSONAL CLAVE\n  Requisitos:\n"
            "   CARGO                 EXPERIENCIA\n"
            "   Residente de obra     36 meses como residente o supervisor, y 12 meses como\n"
            "                         asistente en obras de la especialidad.\n"
            "   Especialista en       24 meses como especialista en seguridad.\n"
            "   seguridad\n"
            "Acreditación:\n")
    result = read(text)
    assert result["revisar"] == UNREADABLE
    assert [(p["cargo"], p["tiempo"]) for p in result["personal"]] == [
        (None, "36 meses"), (None, "12 meses"), (None, "24 meses")]


def test_two_cargos_run_together_by_ocr_go_to_a_person():
    # OCR lost the second row's time: its cargo joined the first, and every pairing below would be off
    assert read(bases("1252164"))["revisar"] == UNREADABLE


def test_the_page_of_the_requirement():
    assert read(bases("1246310"))["pagina"] == 1


def test_without_the_requirement():
    text = "La experiencia del personal clave corresponde a la especialidad y subespecialidad de la obra.\n"
    assert read(text)["revisar"] == NOT_FOUND


def test_a_sentence_citing_the_requirement_is_not_it():
    text = ("haya sido exigida solo como requisito de calificación (Experiencia del Personal Clave). En caso dicha\n"
            "experiencia también haya sido establecida como factor de evaluación, Requisitos: ninguno\n")
    assert read(text)["revisar"] == NOT_FOUND


def test_a_requirement_without_times():
    text = "B.2 EXPERIENCIA DEL PERSONAL CLAVE\n  Requisitos:\n   Residente de obra con experiencia.\nAcreditación:\n"
    assert read(text)["revisar"] == NO_TIME


def test_heading_with_ocr_noise_and_requisitos_on_the_same_line():
    text = ("  de .B.2 EXPERIENCIA DEL PERSONAL CLAVE   Requisitos:\n"
            "   CARGO                 EXPERIENCIA\n"
            "   Residente de obra     Experiencia mínima de veinticuatro (24) meses como residente o supervisor\n"
            "                         en obras de la especialidad.\n"
            "Acreditación:\n")
    result = read(text)
    assert cargos(result) == [("Residente de obra", "24 meses")]


def test_words_no_cargo_has_through_ocr():
    assert unknown_words("Ingeniero Especialista en Suelos y Pavimentos") == []
    assert unknown_words("Residente de Obra Especialats SOOMA") == ["especialats", "sooma"]


def test_a_profession_in_the_cargo_column_goes_to_a_person():
    text = ("B.2 EXPERIENCIA DEL PERSONAL CLAVE\n  Requisitos:\n"
            "   CARGO                    EXPERIENCIA\n"
            "   RESIDENTE DE OBRA        36 meses como residente o supervisor en obras de la especialidad y\n"
            "   INGENIERO CIVIL          subespecialidad indicadas en el requisito de calificación.\n"
            "Acreditación:\n")
    assert read(text)["revisar"] == UNREADABLE


def test_words_of_the_description_inside_the_cargo_go_to_a_person():
    text = ("B.2 EXPERIENCIA DEL PERSONAL CLAVE\n  Requisitos:\n"
            "   CARGO                    EXPERIENCIA\n"
            "   Ingeniero Residente      12 meses como residente y/o supervisor y/o inspector en obras de la\n"
            "   y/o jefe de Obra         especialidad y subespecialidad.\n"
            "Acreditación:\n")
    assert read(text)["revisar"] == UNREADABLE


def test_heading_indented_and_with_de_instead_of_del():
    text = ("                    Experiencia de personal clave\n"
            "                    Requisitos:\n"
            "   CARGO                 EXPERIENCIA\n"
            "   Residente de obra     Mínimo 36 meses de experiencia acumulada en la ejecución de obras.\n"
            "Acreditación:\n")
    assert cargos(read(text)) == [("Residente de obra", "36 meses")]


def test_works_older_than_twenty_years_is_no_time():
    text = ("B.2 EXPERIENCIA DEL PERSONAL CLAVE\n  Requisitos:\n"
            "   CARGO                 EXPERIENCIA\n"
            "   Residente de obra     36 meses como residente; no se considera la experiencia con una antigüedad\n"
            "                         mayor a veinte (20) años.\n"
            "Acreditación:\n")
    assert cargos(read(text)) == [("Residente de obra", "36 meses")]


def test_lettered_cargos_above_their_paragraphs():
    # obra 1255553 as a vision model transcribes it
    text = ("B.2 EXPERIENCIA DEL PERSONAL CLAVE\n\nRequisitos:\n\na) Residente de Obra\n\n"
            "Acreditar experiencia efectiva mínima de VEINTICUATRO (24) MESES, computados desde la colegiatura, "
            "como Residente o Supervisor o Inspector.\n\nb) Ingeniero Estructurista\n\n"
            "Acreditar experiencia efectiva mínima de DOCE (12) MESES, computados desde la colegiatura, como "
            "Especialista.\n\nAcreditación:\n")
    assert cargos(read(text)) == [("Residente de Obra", "24 meses"), ("Ingeniero Estructurista", "12 meses")]


def test_a_table_one_row_a_line_takes_the_cargo_cell_whatever_its_words():
    # obra 1245329: the third cargo does not open with a cargo word, the CARGO header says it is one
    text = ("B.2 EXPERIENCIA DEL PERSONAL CLAVE\nRequisitos:\nPLANTEL PROFESIONAL CLAVE\nCARGO   EXPERIENCIA\n"
            "Residente de obra   Experiencia mínima 24 meses como Residente en la ejecución de obra\n"
            "Especialista de suelos y pavimentos   Experiencia mínima 12 meses como especialista en suelos\n"
            "Seguridad, Salud y Medio Ambiente   Experiencia mínima 12 meses como especialista en seguridad\n"
            "Acreditación:\n")
    assert cargos(read(text)) == [("Residente de obra", "24 meses"), ("Especialista de suelos y pavimentos", "12 meses"),
                                  ("Seguridad, Salud y Medio Ambiente", "12 meses")]


def test_numbered_rows_and_bulleted_cargos_with_a_colon():
    numbered = ("B.2 EXPERIENCIA DEL PERSONAL CLAVE\nRequisitos:\nN°   PERSONAL   EXPERIENCIA\n"
                "1   INGENIERO RESIDENTE DE OBRA   Deberá acreditar una experiencia mínima de veinticuatro (24) meses\n"
                "2   ARQUITECTO ESPECIALISTA EN ARQUITECTURA   Acreditar experiencia efectiva mínima de doce (12) meses\n"
                "Acreditación:\n")
    assert cargos(read(numbered)) == [("INGENIERO RESIDENTE DE OBRA", "24 meses"),
                                      ("ARQUITECTO ESPECIALISTA EN ARQUITECTURA", "12 meses")]
    bulleted = ("B.2 EXPERIENCIA DEL PERSONAL CLAVE\nRequisitos:\n"
                "• Residente de Obra: Experiencia mínima de veinticuatro (24) meses en la especialidad.\n"
                "Acreditación:\n")
    assert cargos(read(bulleted)) == [("Residente de Obra", "24 meses")]


def test_a_cargo_before_debe_acreditar_and_a_cargo_cell_with_y_o():
    # obras 1246433 and 1254052
    listed = ("B.2 EXPERIENCIA DEL PERSONAL CLAVE\nRequisitos:\n"
              "➢ Residente de Obra, debe acreditar Doce (12) meses, computados desde la colegiatura, como Residente.\n"
              "Acreditación:\n")
    assert cargos(read(listed)) == [("Residente de Obra", "12 meses")]
    table = ("B.2 EXPERIENCIA DEL PERSONAL CLAVE\nRequisitos:\nCargo   N°   Profesión   Experiencia\n"
             "Residente de Obra   01   Ingeniero Civil   24 meses contabilizados desde la colegiatura\n"
             "Especialista de Seguridad en Obra y Salud Ocupacional y/o SSOMA   01   Ingeniero Industrial   "
             "24 meses contabilizados desde la colegiatura\nAcreditación:\n")
    assert cargos(read(table)) == [("Residente de Obra", "24 meses"),
                                   ("Especialista de Seguridad en Obra y Salud Ocupacional y/o SSOMA", "24 meses")]


def test_a_table_headed_especialidad_with_cargos_like_capacitador_and_gestor():
    # obra 1251310
    text = ("B.2 EXPERIENCIA DEL PERSONAL CLAVE\nRequisitos:\nN°   ESPECIALIDAD   EXPERIENCIA REQUERIDA\n"
            "1   Residente de Obra   48 meses de experiencia como: Residente o supervisor\n"
            "5   Capacitador Técnico   Contar con 24 meses como Capacitador Técnico\n"
            "6   Gestor Social   Contar con 18 meses como Gestor Social\nAcreditación:\n")
    assert cargos(read(text)) == [("Residente de Obra", "48 meses"), ("Capacitador Técnico", "24 meses"),
                                  ("Gestor Social", "18 meses")]


def test_debe_acreditar_wins_over_a_colon_later_in_the_line():
    # obra 1252970
    text = ("B.2 EXPERIENCIA DEL PERSONAL CLAVE\nRequisitos:\n"
            "➢ INGENIERO RESIDENTE DE OBRA, debe acreditar el tiempo de experiencia mínimo de veinticuatro (24) meses.\n"
            "➢ ESPECIALISTA EN SEGURIDAD Y SALUD EN OBRA, debe acreditar seis (06) meses como especialista, en: "
            "seguridad y salud ocupacional.\nAcreditación:\n")
    assert cargos(read(text)) == [("INGENIERO RESIDENTE DE OBRA", "24 meses"),
                                  ("ESPECIALISTA EN SEGURIDAD Y SALUD EN OBRA", "6 meses")]
