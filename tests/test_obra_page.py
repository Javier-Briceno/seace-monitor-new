import json
import re
from datetime import timedelta
from decimal import Decimal

from seace_monitor.obra_page import build, warning_text

from test_report import NOW, add


def bases(conn, nid, tipo="Bases Administrativas", archivo="0f1e2d3c-1111-2222-3333-444455556666_BASES.pdf",
          lectura=None, version="cuantia-2"):
    doc = conn.execute(
        """INSERT INTO documentos (nid_proceso, uuid, etapa, tipo, nombre_archivo, estado, ruta_local)
           VALUES (%s, %s, 'Convocatoria', %s, %s, 'done', %s) RETURNING id""",
        [nid, f"u{nid}{tipo}", tipo, archivo, f"data/{nid}/{archivo}"],
    ).fetchone()[0]
    if lectura is not None:
        conn.execute("INSERT INTO extracciones (documento_id, version_extractor, campos, estado) VALUES (%s, %s, %s, 'done')",
                     [doc, version, json.dumps(lectura)])
    return doc


def reading(**values):
    base = {"pagina": 21, "cuantia": "127019.94", "tipo_oferta": "limitada", "limite_inferior": "120668.94",
            "limite_superior": "139721.93", "avisos": [], "revisar": None, "archivo": "BASES.pdf", "ocr": False}
    return {**base, **values}


def text(page: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", page))


def test_only_obras_still_open_for_offers_in_the_watched_departamentos(conn):
    add(conn, 1, ["LA LIBERTAD"], NOW + timedelta(days=2))
    add(conn, 2, ["LA LIBERTAD"], NOW - timedelta(hours=1))  # offers closed
    add(conn, 3, ["ANCASH"], NOW + timedelta(days=2))
    page = text(build(conn, ["LA LIBERTAD"], NOW))
    assert "LP-ABR-1" in page and "LP-ABR-2" not in page and "LP-ABR-3" not in page
    assert "1 obras abiertas para ofertas en La Libertad" in page
    assert "Bases todavía no descargadas" in page


def test_nearest_deadline_first(conn):
    add(conn, 1, ["LA LIBERTAD"], NOW + timedelta(days=9))
    add(conn, 2, ["LA LIBERTAD"], NOW + timedelta(days=1))
    page = text(build(conn, ["LA LIBERTAD"], NOW))
    assert page.index("LP-ABR-2") < page.index("LP-ABR-1")
    assert "(mañana)" in page


def test_reading_of_the_newest_bases_with_its_warning(conn):
    add(conn, 1, ["LA LIBERTAD"], NOW + timedelta(days=3))
    bases(conn, 1, lectura=reading(cuantia="1.00"))
    bases(conn, 1, tipo="Bases Integradas", lectura=reading(
        avisos=[{"aviso": "limite_inferior", "bases": "120668.94", "exacto": "120668.95"}]))
    page = text(build(conn, ["LA LIBERTAD"], NOW))
    assert "Cuantía: S/ 127,019.94" in page and "S/ 1.00" not in page
    assert "Límites en las bases: S/ 120,668.94 a S/ 139,721.93" in page
    assert ("Límite inferior: las bases dicen S/ 120,668.94; el 95 % de la cuantía, redondeado hacia arriba, "
            "es S/ 120,668.95. Con el de las bases, una oferta de S/ 120,668.94 queda por debajo del 95 %.") in page
    assert "Bases Integradas, archivo «BASES.pdf», pág. 21" in page
    assert "1 con algo que revisar" in page


def test_no_all_clear_without_the_offer_type(conn):
    add(conn, 1, ["LA LIBERTAD"], NOW + timedelta(days=3))
    add(conn, 2, ["LA LIBERTAD"], NOW + timedelta(days=4))
    bases(conn, 1, lectura=reading())
    bases(conn, 2, lectura=reading(tipo_oferta=""))
    page = text(build(conn, ["LA LIBERTAD"], NOW))
    assert page.count("Cuantía y límites sin observaciones") == 1
    assert "no se encontró en el capítulo IV" in page


def test_scanned_bases_ask_for_a_person(conn):
    add(conn, 1, ["LA LIBERTAD"], NOW + timedelta(days=3))
    bases(conn, 1, lectura=reading(cuantia=None, tipo_oferta="", limite_inferior=None, limite_superior=None,
                                   revisar="escaneado", archivo="BASES.pdf"))
    page = text(build(conn, ["LA LIBERTAD"], NOW))
    assert "Bases escaneadas, todavía sin leer: revisar a mano." in page
    assert "Cuantía en la ficha del SEACE: S/ 1,500,000.00" in page


def test_ocr_reading_asks_to_check_the_figures(conn):
    add(conn, 1, ["LA LIBERTAD"], NOW + timedelta(days=3))
    bases(conn, 1, lectura=reading(ocr=True))
    assert "verificar las cifras en la página" in text(build(conn, ["LA LIBERTAD"], NOW))


def test_warnings_read_through_ocr_ask_for_a_look_first(conn):
    # 1216921: OCR read 206,938.97 where the page says 206,338.97, the exact 95 %
    add(conn, 1, ["LA LIBERTAD"], NOW + timedelta(days=3))
    bases(conn, 1, lectura=reading(ocr=True, pagina=22, avisos=[
        {"aviso": "limite_inferior", "bases": "206938.97", "exacto": "206338.97"}]))
    page = text(build(conn, ["LA LIBERTAD"], NOW))
    assert "Leído con OCR; antes de consultarlo, comprobar en la página 22:" in page
    assert "Para revisar o consultar" not in page and "0 con algo que revisar" in page


def test_experience_asked_by_the_bases(conn):
    add(conn, 1, ["LA LIBERTAD"], NOW + timedelta(days=3))
    add(conn, 2, ["LA LIBERTAD"], NOW + timedelta(days=4))
    doc = bases(conn, 1, lectura=reading())
    conn.execute("INSERT INTO extracciones (documento_id, version_extractor, campos, estado) VALUES (%s, 'experiencia-1', %s, 'done')",
                 [doc, json.dumps({"monto": "800000.00", "veces": None, "veces_cuantia": "1.015", "anios": 20,
                                   "cuenta_desde": "acta de recepción", "especialidad": "Edificaciones y Afines",
                                   "subespecialidades": ["Establecimientos de salud"], "pagina": 57, "revisar": None,
                                   "ocr": False})])
    doc = bases(conn, 2, lectura=reading())
    conn.execute("INSERT INTO extracciones (documento_id, version_extractor, campos, estado) VALUES (%s, 'experiencia-1', %s, 'done')",
                 [doc, json.dumps({"monto": None, "veces": None, "revisar": "sin requisito de experiencia del postor",
                                   "pagina": None, "ocr": False})])
    page = text(build(conn, ["LA LIBERTAD"], NOW))
    assert ("Experiencia del postor: S/ 800,000.00, 1,02 veces la cuantía, en Edificaciones y Afines — "
            "Establecimientos de salud, en los últimos 20 años, contados desde acta de recepción (pág. 57).") in page
    assert "Experiencia del postor: no se pudo leer, revisar a mano." in page


def test_downloaded_bases_not_read_yet(conn):
    add(conn, 1, ["LA LIBERTAD"], NOW + timedelta(days=3))
    bases(conn, 1)
    assert "Bases descargadas, todavía sin leer." in text(build(conn, ["LA LIBERTAD"], NOW))


def test_a_lower_limit_above_the_exact_figure_says_who_it_disqualifies():
    sentence = warning_text({"aviso": "limite_inferior", "bases": "587646.47", "exacto": "587464.47"})
    assert "una oferta desde S/ 587,464.47 hasta S/ 587,646.46 cumple el 95 % y aun así quedaría descalificada" in sentence


def test_an_upper_limit_below_the_exact_figure_says_who_it_disqualifies():
    sentence = warning_text({"aviso": "limite_superior", "bases": "1622638.31", "exacto": "1662638.31"})
    assert "una oferta desde S/ 1,622,638.32 hasta S/ 1,662,638.31 cumple el 110 %" in sentence


def test_figures_that_disagree_with_their_words():
    sentence = warning_text({"aviso": "cuantia_distinta_letras", "cifra": "4823130.47", "letras": "4829130.42"})
    assert "La cuantía en cifras (S/ 4,823,130.47) no es la que dicen las letras (S/ 4,829,130.42)" in sentence


def test_experience_whose_words_say_another_amount(conn):
    add(conn, 1, ["LA LIBERTAD"], NOW + timedelta(days=3))
    doc = bases(conn, 1, lectura=reading())
    conn.execute("INSERT INTO extracciones (documento_id, version_extractor, campos, estado) VALUES (%s, 'experiencia-2', %s, 'done')",
                 [doc, json.dumps({"monto": "4823130.47", "monto_letras": "4829130.42", "veces": None, "pagina": 30,
                                   "revisar": None, "ocr": True})])
    assert "El monto en letras dice S/ 4,829,130.42: mirar la página." in text(build(conn, ["LA LIBERTAD"], NOW))


def test_experience_figure_out_of_range(conn):
    add(conn, 1, ["LA LIBERTAD"], NOW + timedelta(days=3))
    doc = bases(conn, 1, lectura=reading())
    conn.execute("INSERT INTO extracciones (documento_id, version_extractor, campos, estado) VALUES (%s, 'experiencia-2', %s, 'done')",
                 [doc, json.dumps({"monto": "2338.42", "veces_cuantia": "0.001", "veces": None, "pagina": 44,
                                   "revisar": "monto de experiencia fuera de rango", "ocr": True})])
    assert ("Experiencia del postor: se leyó S/ 2,338.42, que no cuadra con la cuantía; puede ser una cifra mal leída "
            "(pág. 44): revisar a mano.") in text(build(conn, ["LA LIBERTAD"], NOW))


def test_factors_with_their_points_and_warnings(conn):
    add(conn, 1, ["LA LIBERTAD"], NOW + timedelta(days=3))
    add(conn, 2, ["LA LIBERTAD"], NOW + timedelta(days=4))
    doc = bases(conn, 1, lectura=reading())
    conn.execute("INSERT INTO extracciones (documento_id, version_extractor, campos, estado) VALUES (%s, 'factores-1', %s, 'done')",
                 [doc, json.dumps({"pagina": 67, "total": 100, "suma": 105, "revisar": None, "factores": [
                     {"letra": "A", "factor": "Experiencia específica adicional del personal clave", "puntos": 60},
                     {"letra": "B", "factor": "Sostenibilidad ambiental", "puntos": 45}],
                     "avisos": [{"aviso": "suma_distinta_total", "suma": 105, "total": 100}]})])
    doc = bases(conn, 2, lectura=reading())
    conn.execute("INSERT INTO extracciones (documento_id, version_extractor, campos, estado) VALUES (%s, 'factores-1', %s, 'done')",
                 [doc, json.dumps({"pagina": None, "factores": [], "avisos": [], "revisar": "sin cuadro resumen de factores"})])
    page = text(build(conn, ["LA LIBERTAD"], NOW))
    assert ("Factores de evaluación (pág. 67): Experiencia específica adicional del personal clave 60, "
            "Sostenibilidad ambiental 45. Total 100.") in page
    assert "Los puntajes del cuadro resumen suman 105, pero el puntaje total dice 100." in page
    assert "Factores de evaluación: no se pudo leer el cuadro resumen, revisar a mano." in page
    assert "1 con algo que revisar" in page


def test_personal_clave_with_its_times(conn):
    add(conn, 1, ["LA LIBERTAD"], NOW + timedelta(days=3))
    add(conn, 2, ["LA LIBERTAD"], NOW + timedelta(days=4))
    add(conn, 3, ["LA LIBERTAD"], NOW + timedelta(days=5))
    add(conn, 4, ["LA LIBERTAD"], NOW + timedelta(days=6))
    readings = {
        4: {"pagina": None, "ocr": False, "revisar": "sin requisito de personal clave", "avisos": [], "personal": []},
        1: {"pagina": 58, "ocr": False, "revisar": None, "personal": [
                {"cargo": "Ingeniero Residente de Obra", "tiempo": "24 meses", "meses": 24},
                {"cargo": "Especialista en Seguridad", "tiempo": "1 año", "meses": 12}],
            "avisos": [{"aviso": "tiempo_distinto_letras", "cargo": "Ingeniero Residente de Obra", "cifra": 24, "letras": 36}]},
        2: {"pagina": 44, "ocr": False, "revisar": "cargos ilegibles", "avisos": [], "personal": [
                {"cargo": None, "tiempo": "36 meses", "meses": 36}]},
        3: {"pagina": 61, "ocr": True, "revisar": None, "personal": [
                {"cargo": "Residente de Obra", "tiempo": "24 meses", "meses": 24}],
            "avisos": [{"aviso": "tiempo_distinto_letras", "cargo": "Residente de Obra", "cifra": 24, "letras": 34}]},
    }
    for nid, found in readings.items():
        doc = bases(conn, nid, lectura=reading())
        conn.execute("INSERT INTO extracciones (documento_id, version_extractor, campos, estado) VALUES (%s, 'personal-1', %s, 'done')",
                     [doc, json.dumps(found)])
    page = text(build(conn, ["LA LIBERTAD"], NOW))
    assert "Personal clave (pág. 58): Ingeniero Residente de Obra 24 meses; Especialista en Seguridad 1 año." in page
    assert "Ingeniero Residente de Obra: el tiempo en cifras (24) no es el que dicen las letras (36)." in page
    assert "Personal clave: no se pudo leer el cuadro de cargos (pág. 44), revisar a mano." in page
    assert "Personal clave: no se encontró en el texto de las bases, revisar a mano." in page
    assert "Personal clave (pág. 61, leído con OCR): Residente de Obra 24 meses." in page
    assert "Leído con OCR; antes de consultarlo, comprobar en la página 61:" in page
    assert "1 con algo que revisar" in page  # the warning read through OCR waits for a look at the page


def test_page_escapes_what_comes_from_seace(conn):
    add(conn, 1, ["LA LIBERTAD"], NOW + timedelta(days=3))
    conn.execute("UPDATE licitaciones SET descripcion = 'OBRA <script>x</script>'")
    assert "<script>" not in build(conn, ["LA LIBERTAD"], NOW)
