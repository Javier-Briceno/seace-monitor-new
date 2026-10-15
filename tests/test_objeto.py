from pathlib import Path

from seace_monitor import objeto


def section(body: str) -> str:
    return f"1.2. DOMICILIO LEGAL\nJr. Bolognesi 123\n\f1.3. OBJETO DE LA CONVOCATORIA\n\n{body}\n\n1.4. CUANTÍA DE LA CONTRATACIÓN\n"


def test_the_quoted_name_and_its_cui_with_the_page():
    r = objeto.read(section(
        "El presente procedimiento de selección tiene por objeto la contratación de la ejecución de la obra "
        "correspondiente a: “MEJORAMIENTO DEL SERVICIO DE PROVISIÓN DE AGUA PARA RIEGO EN EL CANAL REPRESA HUANCHACO\n"
        "EN EL CASERIO DE HUARANA DISTRITO DE MOLLEPATA DE LA PROVINCIA DE SANTIAGO DE CHUCO DEL DEPARTAMENTO DE LA "
        "LIBERTAD” con CUI 2719000"))
    assert r["obra"].startswith("MEJORAMIENTO DEL SERVICIO DE PROVISIÓN DE AGUA")
    assert r["obra"].endswith("DEL DEPARTAMENTO DE LA LIBERTAD")
    assert "\n" not in r["obra"]
    assert r["cui"] == "2719000" and r["pagina"] == 2 and r["revisar"] is None


def test_the_page_is_the_sections_not_the_table_of_contents():
    text = ("ÍNDICE\n1.3. OBJETO DE LA CONVOCATORIA ........ 2\n1.4. CUANTÍA ........ 2\n\f"
            "1.3. OBJETO DE LA CONVOCATORIA\nEl presente procedimiento de selección tiene por objeto la ejecución de "
            "la obra “CREACION DE LOSA DEPORTIVA EN EL CASERIO DE COCHAMARCA” con CUI 2719412\n")
    assert objeto.read(text)["pagina"] == 2


def test_a_template_bracket_around_the_quotes_is_left_out():
    r = objeto.read(section(
        "El presente procedimiento de selección tiene por objeto la contratación de la ejecución de la obra "
        "correspondiente a [Ejecución de la IOARR “Renovación de Puente; en el camino vecinal R020138: Emp. AN–1115 "
        "(Puente Chaquecyaco), en el caserío de Chaquecyaco, distrito de Jangas, provincia de Huaraz, departamento "
        "de Áncash”, con CUI N° 2661466”]"))
    assert r["obra"].startswith("Renovación de Puente") and r["obra"].endswith("departamento de Áncash")
    assert r["cui"] == "2661466"


def test_the_template_note_after_the_name_is_not_part_of_it():
    r = objeto.read(section(
        "El presente procedimiento de selección tiene por objeto la contratación de la ejecución de la obra "
        "correspondiente a la: “RENOVACION DE PUENTE PEATONAL; EN EL(LA) CAMINO DE HERRADURA LLAMA GARPANAN, "
        "DISTRITO DE PAUCAS, PROVINCIA HUARI, DEPARTAMENTO ANCASH” CON CÓDIGO ÚNICO DE INVERSIONES N°2724989\n"
        "Importante para la entidad contratante\n• En caso de procedimientos de selección según relación de ítems"))
    assert r["obra"].endswith("DEPARTAMENTO ANCASH")
    assert r["cui"] == "2724989"
    assert "Importante" not in r["texto"]


def test_the_running_header_beside_the_text_is_dropped():
    r = objeto.read(section(
        "El presente procedimiento de selección tiene por objeto la contratación de la ejecución de la obra:\n"
        "“MEJORAMIENTO Y AMPLIACION DE LOS SERVICIOS          LICITACIÓN PÚBLICA PARA OBRAS\n"
        "EDUCATIVOS DE LAS INSTITUCIONES EDUCATIVAS N 570 Y N 84140 DE PALLAHUASI, DISTRITO DE CASCA”"))
    assert r["obra"] == ("MEJORAMIENTO Y AMPLIACION DE LOS SERVICIOS EDUCATIVOS DE LAS INSTITUCIONES EDUCATIVAS "
                         "N 570 Y N 84140 DE PALLAHUASI, DISTRITO DE CASCA")


def test_a_quoted_name_inside_the_obra_name_is_not_taken_for_it():
    r = objeto.read(section(
        "El presente procedimiento de selección tiene por objeto la contratación de la ejecución de la obra: "
        "MEJORAMIENTO DEL SERVICIO EDUCATIVO EN LA I.E. \"SAN MARTIN DE PORRES\", DISTRITO DE PATAZ, "
        "DEPARTAMENTO LA LIBERTAD, con CUI 2634231"))
    assert r["obra"] == ("MEJORAMIENTO DEL SERVICIO EDUCATIVO EN LA I.E. \"SAN MARTIN DE PORRES\", DISTRITO DE PATAZ, "
                         "DEPARTAMENTO LA LIBERTAD")


def test_the_name_starts_after_the_last_words_that_open_it():
    r = objeto.read(section(
        "El presente procedimiento de selección tiene por objeto la ejecución de la obra correspondiente a: "
        "CONTRATACIÓN DEL PAQUETE 5 PARA LA EJECUCIÓN DE LA OBRA IOARR: “REMODELACION DE LOSA DEPORTIVA; EN EL(LA) "
        "I.E. 80658 EN EL CENTRO POBLADO CRUZ DE MAYO, DISTRITO DE MACHE, PROVINCIA OTUZCO”"))
    assert r["obra"].startswith("REMODELACION DE LOSA DEPORTIVA")


def test_a_name_running_onto_the_next_page_loses_the_footer_and_header():
    r = objeto.read(section(
        "El presente procedimiento de selección tiene por objeto la ejecución de la obra: MEJORAMIENTO DEL SERVICIO "
        "DE TRANSITABILIDAD VIAL INTERURBANA EN EMP LI 610 - EL CERRITO DISTRITO DE PAIJAN DE LA PROVINCIA DE ASCOPE "
        "DEL DEPARTAMENTO DE LA\n                19\n\fMUNICIPALIDAD DISTRITAL DE PAIJAN\nLICITACION PUBLICA "
        "ABREVIADA DE OBRAS N° 3-2026\nLIBERTAD, con CUI N° 2655948"))
    assert r["obra"].endswith("DEL DEPARTAMENTO DE LA LIBERTAD")


def test_straight_quotes_inside_a_straight_quoted_name_do_not_close_it():
    r = objeto.read(section(
        "El presente procedimiento de selección tiene por objeto la ejecución de la obra: \"MEJORAMIENTO DEL SERVICIO "
        "EDUCATIVO EN LA I.E. \"SAN MARTIN DE PORRES\", DISTRITO DE PATAZ, DEPARTAMENTO LA LIBERTAD\" con CUI 2634231"))
    assert r["obra"] == ("MEJORAMIENTO DEL SERVICIO EDUCATIVO EN LA I.E. \"SAN MARTIN DE PORRES\", DISTRITO DE PATAZ, "
                         "DEPARTAMENTO LA LIBERTAD")


def test_a_cui_inside_the_quotes_is_cut_off_the_name():
    r = objeto.read(section(
        "El presente procedimiento de selección tiene por objeto la contratación de la ejecución de la obra "
        "\"RENOVACION DE PUENTE; EN EL (LA) VIA VECINAL R022043 PUENTE HUICHCANA DISTRITO DE MANCOS, PROVINCIA "
        "YUNGAY, DEPARTAMENTO ANCASH. CON CUI: 2693255\""))
    assert r["obra"].endswith("DEPARTAMENTO ANCASH") and r["cui"] == "2693255"


def test_without_quotes_the_name_runs_up_to_the_cui():
    r = objeto.read(section(
        "El presente procedimiento de selección tiene por objeto la contratación de la ejecución de la obra "
        "correspondiente: MEJORAMIENTO DEL SERVICIO DE MOVILIDAD URBANA EN SECTOR NUEVA ESPERANZA, DISTRITO DE VIRU, "
        "con CUI N° 2626796"))
    assert r["obra"] == "MEJORAMIENTO DEL SERVICIO DE MOVILIDAD URBANA EN SECTOR NUEVA ESPERANZA, DISTRITO DE VIRU"


def test_no_section_and_no_readable_name_go_to_a_person():
    assert objeto.read("CAPÍTULO I\nGENERALIDADES\n")["revisar"] == objeto.NOT_FOUND
    unread = objeto.read(section("El presente procedimiento de selección tiene por objeto la contratación de [ ]"))
    assert unread["revisar"] == objeto.NO_NAME and unread["obra"] is None


def write(tmp_path: Path, text: str) -> list[Path]:
    path = tmp_path / "bases.txt"
    path.write_text(text, encoding="utf-8")
    return [path]


BASES = section("El presente procedimiento de selección tiene por objeto la contratación de la ejecución de la obra "
                "“MEJORAMIENTO Y AMPLIACION DEL SERVICIO DE ALCANTARILLADO EN EL SECTOR CARHUABAMBA, DISTRITO DE "
                "PATAZ” CON CUI 2634231")


def test_a_cui_that_is_not_seaces_is_a_warning(monkeypatch, tmp_path):
    monkeypatch.setattr(objeto.reading, "text_of", lambda path: path.read_text(encoding="utf-8"))
    r = objeto.read_files(write(tmp_path, BASES), "EJECUCION DE LA OBRA MOVILIDAD URBANA ... CON CUI 2623287")
    assert r["avisos"] == [{"aviso": "cui_distinto_seace", "bases": "2634231", "seace": "2623287"}]


def test_a_paquete_naming_the_bases_cui_among_several_is_no_warning(monkeypatch, tmp_path):
    monkeypatch.setattr(objeto.reading, "text_of", lambda path: path.read_text(encoding="utf-8"))
    r = objeto.read_files(write(tmp_path, BASES), "PAQUETE 5 ... CUI N° 2556200, N° 2634231, N° 2683978 Y N° 2709843")
    assert r["avisos"] == []


def test_names_split_or_without_accents_in_tesseract_are_the_same_name():
    alike = objeto.ALIKE["obra"]
    assert alike("AMPLIACIÓN DEL SERVICIO DE AGUA") == alike("AMPLIACION DEL SERVIC IO DE AGUA")
    assert alike("RENOVACIÓN DE PUENTE") != alike("RENOVAC CISCO DE SUCRE")
