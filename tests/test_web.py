import contextlib
import json
import re
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from seace_monitor.store import save_cronograma
from seace_monitor.web import auth, data
from seace_monitor.web.app import COOKIE, create_app

from test_obra_page import bases, reading
from test_report import NOW, add

ALLOWED = "persona@example.com"


@pytest.fixture
def web(conn, tmp_path):
    sent = []
    settings = {"search": {"departamentos": ["LA LIBERTAD"]}, "download": {"dir": str(tmp_path)},
                "web": {"url": "https://buscador.example.com", "correos": [ALLOWED]}}
    app = create_app(settings, connect=lambda: contextlib.nullcontext(conn),
                     send=lambda subject, body, files, to: sent.append((subject, body, to)) or to, clock=lambda: NOW)
    client = TestClient(app, base_url="https://buscador.example.com")
    client.sent = sent
    client.root = tmp_path
    return client


def signed_in(web, conn) -> dict:
    session = auth.use_link(conn, auth.new_link(conn, ALLOWED, NOW), NOW)
    web.cookies.set(COOKIE, session)
    return auth.session_of(conn, session, NOW)


def text(page: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", page))


def test_without_a_session_every_page_asks_to_sign_in(web):
    for path in ("/", "/obras/1", "/obras/1/documentos/1", "/obras/1/bases/1/BASES.pdf"):
        response = web.get(path, follow_redirects=False)
        assert response.status_code == 303 and response.headers["location"] == "/entrar"


def test_a_link_goes_only_to_allowed_addresses_and_the_answer_is_the_same(web):
    other = web.post("/entrar", data={"correo": "otra@example.com"})
    allowed = web.post("/entrar", data={"correo": " Persona@Example.com "})
    assert len(web.sent) == 1 and web.sent[0][2] == [ALLOWED]
    assert "https://buscador.example.com/entrar/" in web.sent[0][1]
    assert text(other.text).replace("otra@example.com", "X") == text(allowed.text).replace("persona@example.com", "X")


def test_a_link_signs_in_once_after_a_button(web, conn):
    web.post("/entrar", data={"correo": ALLOWED})
    token = web.sent[0][1].split("/entrar/")[1].split()[0]
    assert "Entrar" in web.get(f"/entrar/{token}").text          # opening it spends nothing
    response = web.post(f"/entrar/{token}", follow_redirects=False)
    assert response.headers["location"] == "/" and COOKIE in response.cookies
    assert "secure" in response.headers["set-cookie"].lower() and "httponly" in response.headers["set-cookie"].lower()
    web.cookies.clear()
    again = web.post(f"/entrar/{token}", follow_redirects=False)
    assert COOKIE not in again.cookies
    assert "ya no sirve" in web.get(f"/entrar/{token}").text


def test_an_address_gets_few_links_per_hour(web):
    for _ in range(auth.LINKS_PER_HOUR + 2):
        web.post("/entrar", data={"correo": ALLOWED})
    assert len(web.sent) == auth.LINKS_PER_HOUR


def test_simultaneous_requests_still_get_few_links(test_dbname):
    from concurrent.futures import ThreadPoolExecutor
    from seace_monitor import db

    def ask(_):
        with db.connect(test_dbname) as own:
            return auth.new_link(own, "simultanea@example.com", NOW)
    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            tokens = [t for t in pool.map(ask, range(16)) if t]
        assert len(tokens) == auth.LINKS_PER_HOUR
    finally:
        with db.connect(test_dbname) as own:
            own.execute("DELETE FROM web_accesos WHERE correo = 'simultanea@example.com'")


def test_the_list_shows_open_obras_and_finds_by_text(web, conn):
    signed_in(web, conn)
    add(conn, 1, ["LA LIBERTAD"], NOW + timedelta(days=2))
    add(conn, 2, ["LA LIBERTAD"], NOW - timedelta(days=1))
    conn.execute("UPDATE licitaciones SET descripcion = 'MEJORAMIENTO DEL ESTADIO' WHERE nid_proceso = 1")
    page = text(web.get("/").text)
    assert "Estadio" in page.title() and "LP-ABR-2" not in page and "1 obra abierta para ofertas" in page
    assert "Ninguna obra cumple" in text(web.get("/", params={"q": "colegio"}).text)
    assert "1 obra" in text(web.get("/", params={"q": "estadio"}).text)
    assert "Cerradas" in text(web.get("/", params={"cerradas": "1"}).text)


def test_a_requisito_filter_keeps_unread_bases_apart(web, conn):
    signed_in(web, conn)
    for nid, monto in ((1, "500000.00"), (2, "3000000.00"), (3, None)):
        add(conn, nid, ["LA LIBERTAD"], NOW + timedelta(days=2))
        doc = bases(conn, nid, lectura=reading())
        if monto:
            conn.execute("INSERT INTO extracciones (documento_id, version_extractor, campos, estado) "
                         "VALUES (%s, 'experiencia-3', %s, 'done')",
                         [doc, f'{{"monto": "{monto}", "revisar": null, "pagina": 40, "archivo": "BASES.pdf"}}'])
    page = web.get("/", params={"exp_max": "1,000,000"}).text
    found, unread = page.split("Sin leer en las bases")
    assert "/obras/1" in found and "/obras/2" not in page and "/obras/3" in unread


def test_matching_reads_amounts_and_words_as_people_type_them():
    assert data.amount("S/ 1,500,000.50") == Decimal("1500000.50") and data.amount("1 500 000") == Decimal("1500000")
    assert data.amount("mucho") is None and data.amount("-5") is None
    assert data.amount("NaN") is None and data.amount("Infinity") is None
    assert data.plain("Edificación") == "edificacion"


@pytest.mark.parametrize("seace, shown", [
    ("REMODELACION DE INFRAESTRUCTURA DEPORTIVA; EN EL(LA) SECTOR VI-D SANTA CAMILA DISTRITO DE HUANCHACO",
     "Remodelacion de infraestructura deportiva, en el sector VI-D Santa Camila distrito de Huanchaco"),
    ("CONSTRUCCIÓN DE COBERTURA EN LA I.E. 80666 DEPARTAMENTO LA LIBERTAD¿ ¿ II ETAPA",
     "Construcción de cobertura en la I.E. 80666 departamento La Libertad II etapa"),
    ("CENTRO POBLADO CAÑA BRAVA DISTRITO DE ONGÓN DE LA PROVINCIA DE PATAZ",
     "Centro poblado Caña Brava distrito de Ongón de la provincia de Pataz"),
    ("Ya escrito en minúsculas; por la entidad", "Ya escrito en minúsculas, por la entidad"),
])
def test_seace_descriptions_read_as_sentences(seace, shown):
    assert data.sentence(seace) == shown


def test_dates_are_written_out():
    from seace_monitor.search import LIMA
    from datetime import datetime
    assert data.long_date(datetime(2026, 10, 13, 23, 59, tzinfo=LIMA)) == "martes 13 de octubre, 23:59"
    assert data.short_date(datetime(2026, 10, 1, 9, 0, tzinfo=LIMA)) == "1 oct 2026"


def test_several_departamentos_and_a_removable_chip_per_filter(web, conn):
    signed_in(web, conn)
    add(conn, 1, ["LA LIBERTAD"], NOW + timedelta(days=2))
    add(conn, 2, ["ANCASH"], NOW + timedelta(days=2))
    add(conn, 3, ["CAJAMARCA"], NOW + timedelta(days=2))
    web_page = web.get("/", params=[("dep", "LA LIBERTAD"), ("dep", "ANCASH"), ("q", "prueba")])
    # only LA LIBERTAD is watched in this app, so only obra 1 is listed at all
    assert "/obras/1" in web_page.text and "/obras/3" not in web_page.text
    assert 'href="/?dep=LA+LIBERTAD&amp;dep=ANCASH"' in web_page.text   # the chip that removes «prueba»
    assert 'href="/?dep=ANCASH&amp;q=prueba"' in web_page.text          # the chip that removes La Libertad


def test_a_typed_nonsense_amount_is_ignored_not_an_error(web, conn):
    signed_in(web, conn)
    assert web.get("/", params={"cuantia_min": "NaN", "exp_max": "inf"}).status_code == 200


def test_an_address_taken_off_the_list_loses_its_session_and_its_links(conn, tmp_path):
    session = auth.use_link(conn, auth.new_link(conn, ALLOWED, NOW), NOW)
    pending = auth.new_link(conn, ALLOWED, NOW)
    settings = {"search": {"departamentos": ["LA LIBERTAD"]}, "download": {"dir": str(tmp_path)},
                "web": {"url": "https://buscador.example.com", "correos": []}}
    app = create_app(settings, connect=lambda: contextlib.nullcontext(conn), send=lambda *a, **k: [],
                     clock=lambda: NOW)
    client = TestClient(app, base_url="https://buscador.example.com")
    client.cookies.set(COOKIE, session)
    assert client.get("/", follow_redirects=False).headers["location"] == "/entrar"
    assert COOKIE not in client.post(f"/entrar/{pending}", follow_redirects=False).cookies


def test_following_needs_the_form_token(web, conn):
    session = signed_in(web, conn)
    add(conn, 1, ["LA LIBERTAD"], NOW + timedelta(days=2))
    assert web.post("/obras/1/seguir", data={"accion": "seguir", "csrf": "otro"}).status_code == 403
    response = web.post("/obras/1/seguir", data={"accion": "seguir", "csrf": session["csrf"],
                                                "volver": "https://otro.example.com/"}, follow_redirects=False)
    assert response.headers["location"] == "/obras/1"
    assert "Siguiendo" in web.get("/", params={"seguidas": "1"}).text
    web.post("/obras/1/seguir", data={"accion": "dejar", "csrf": session["csrf"]})
    assert "Ninguna obra cumple" in text(web.get("/", params={"seguidas": "1"}).text)


def test_the_obra_page_links_each_value_to_its_page(web, conn):
    signed_in(web, conn)
    add(conn, 1, ["LA LIBERTAD"], NOW + timedelta(days=2))
    bases(conn, 1, lectura=reading(avisos=[{"aviso": "fija_con_limites"}], tipo_oferta="fija"))
    page = web.get("/obras/1").text
    assert "Para consultar con la entidad" in page and "pág. 21" in page
    assert re.search(r'href="/obras/1/bases/\d+/BASES.pdf#page=21"', page)
    assert web.get("/obras/999").status_code == 404


def test_each_value_links_to_its_own_page_and_an_old_reading_gives_the_offer_none(web, conn):
    signed_in(web, conn)
    add(conn, 1, ["LA LIBERTAD"], NOW + timedelta(days=2))
    add(conn, 2, ["LA LIBERTAD"], NOW + timedelta(days=2))
    bases(conn, 1, lectura=reading(paginas={"cuantia": 21, "limites": 22, "tipo_oferta": 64}))
    bases(conn, 2, lectura=reading())
    rows = {r[0]: r[1] for r in re.findall(r'<th scope="row">([^<]+)</th>.*?#page=(\d+)', web.get("/obras/1").text, re.S)}
    assert (rows["Cuantía"], rows["Límites con IGV"], rows["Oferta económica"]) == ("21", "22", "64")
    old = web.get("/obras/2").text
    offer_row = old[old.index('<th scope="row">Oferta económica</th>'):].split("</tr>")[0]
    assert "#page=" not in offer_row


def test_the_obra_page_shows_the_cronograma_with_moved_dates_struck(web, conn):
    signed_in(web, conn)
    add(conn, 1, ["LA LIBERTAD"], NOW + timedelta(days=2))
    stages = [{"etapa": "Convocatoria", "lugar": None, "inicio": "28/09/2026", "fin": "28/09/2026"},
              {"etapa": "Absolución de consultas", "lugar": "SEACE", "inicio": "12/10/2026", "fin": "12/10/2026"}]
    save_cronograma(conn, 1, stages)
    save_cronograma(conn, 1, [stages[0], {**stages[1], "inicio": "19/10/2026", "fin": "19/10/2026"}])
    conn.execute("INSERT INTO historial (nid_proceso, campo, valor_anterior, valor_nuevo) VALUES (1, %s, %s, %s)",
                 ["cronograma", "Absolución de consultas: 12/10/2026", "19/10/2026"])
    page = text(web.get("/obras/1").text)
    assert "Convocatoria 28/09/2026" in page
    assert "Absolución de consultas SEACE 19/10/2026 12/10/2026 cambió el" in page
    assert "<del>12/10/2026</del>" in web.get("/obras/1").text


def test_files_come_only_from_the_download_folder(web, conn, tmp_path):
    signed_in(web, conn)
    add(conn, 1, ["LA LIBERTAD"], NOW + timedelta(days=2))
    inside = web.root / "1" / "BASES.pdf"
    inside.parent.mkdir()
    inside.write_bytes(b"%PDF-1.4 prueba")
    outside = tmp_path.parent / "fuera.pdf"
    outside.write_bytes(b"%PDF-1.4 fuera")
    good = bases(conn, 1, archivo="BASES.pdf")
    conn.execute("UPDATE documentos SET ruta_local = %s WHERE id = %s", [str(inside), good])
    bad = bases(conn, 1, tipo="Bases Integradas", archivo="fuera.pdf")
    conn.execute("UPDATE documentos SET ruta_local = %s WHERE id = %s", [str(outside), bad])
    shown = web.get(f"/obras/1/bases/{good}/BASES.pdf")
    assert shown.status_code == 200 and shown.headers["content-type"] == "application/pdf"
    assert "inline" in shown.headers["content-disposition"]
    assert web.get(f"/obras/1/documentos/{good}").headers["content-type"] == "application/octet-stream"
    assert web.get(f"/obras/1/bases/{bad}/fuera.pdf").status_code == 404
    assert web.get(f"/obras/1/documentos/{bad}").status_code == 404
    assert web.get(f"/obras/2/documentos/{good}").status_code == 404   # another obra's document


@pytest.mark.parametrize("answer, expected", [
    ("https://alfprod.seace.gob.pe/alfresco/service/api/node/content/x/BASES.pdf", 302),
    ("https://otro.example.com/alfresco/BASES.pdf", 404),
    (None, 404)])
def test_a_file_no_longer_here_is_fetched_from_seace(conn, tmp_path, answer, expected):
    def resolve(uuid):
        if answer is None:
            raise ConnectionError("VPN down")
        return answer
    settings = {"search": {"departamentos": ["LA LIBERTAD"]}, "download": {"dir": str(tmp_path)},
                "web": {"url": "https://buscador.example.com", "correos": [ALLOWED]}}
    client = TestClient(create_app(settings, connect=lambda: contextlib.nullcontext(conn), send=lambda *a, **k: [],
                                   clock=lambda: NOW, resolve=resolve), base_url="https://buscador.example.com")
    signed_in(client, conn)
    add(conn, 1, ["LA LIBERTAD"], NOW - timedelta(days=20))
    doc = bases(conn, 1, archivo="BASES.pdf")   # its file is not in the download folder
    response = client.get(f"/obras/1/documentos/{doc}", follow_redirects=False)
    assert response.status_code == expected
    if expected == 302:
        assert response.headers["location"] == answer


def test_signing_out_needs_the_form_token(web, conn):
    session = signed_in(web, conn)
    forged = web.post("/salir", data={"csrf": "otro"}, follow_redirects=False)
    assert forged.status_code == 403 and "set-cookie" not in forged.headers
    assert web.get("/", follow_redirects=False).status_code == 200      # still signed in
    out = web.post("/salir", data={"csrf": session["csrf"]}, follow_redirects=False)
    assert out.headers["location"] == "/entrar" and COOKIE in out.headers["set-cookie"]
    assert auth.session_of(conn, None, NOW) is None
    web.cookies.clear()
    assert "set-cookie" not in web.post("/salir", data={"csrf": "x"}, follow_redirects=False).headers


def test_pages_carry_security_headers(web):
    headers = web.get("/entrar").headers
    assert headers["x-frame-options"] == "DENY" and "frame-ancestors 'none'" in headers["content-security-policy"]


def test_the_obra_page_names_the_obra_as_its_bases_do_and_warns_of_another_cui(web, conn):
    signed_in(web, conn)
    add(conn, 1, ["LA LIBERTAD"], NOW + timedelta(days=2))
    doc = bases(conn, 1, lectura=reading())
    full = "MEJORAMIENTO DEL SERVICIO DE AGUA POTABLE DEL CASERIO LA VIÑA, DISTRITO DE COCHORCO, PROVINCIA SANCHEZ CARRION"
    conn.execute("INSERT INTO extracciones (documento_id, version_extractor, campos, estado) VALUES (%s, 'objeto-1', %s, 'done')",
                 [doc, json.dumps({"obra": full, "cui": "2485259", "pagina": 20, "ocr": False, "revisar": None,
                                   "archivo": "BASES.pdf",
                                   "avisos": [{"aviso": "cui_distinto_seace", "bases": "2485259", "seace": "2400000"}]})])
    page = text(web.get("/obras/1").text)
    assert f"Nombre completo en las bases pág. 20 {full} CUI 2485259" in page
    assert "El CUI de las bases (2485259) no es el que nombra la descripción del SEACE (2400000)" in page
    found = next(o for o in data.op.obras(conn, ["LA LIBERTAD"], NOW) if o["nid_proceso"] == 1)
    assert data.consult_count(found) == 1


def test_a_scan_whose_two_readings_differ_asks_for_a_look_at_the_page(web, conn):
    signed_in(web, conn)
    add(conn, 1, ["LA LIBERTAD"], NOW + timedelta(days=2))
    add(conn, 2, ["LA LIBERTAD"], NOW + timedelta(days=2))
    bases(conn, 1, lectura=reading(ocr=True, ia=True, segunda_lectura={
        "ia": {"cuantia": "127019.94", "tipo_oferta": "limitada"},
        "tesseract": {"cuantia": "127019.84", "tipo_oferta": "limitada"}, "difieren": ["cuantia"]}))
    bases(conn, 2, lectura=reading(ocr=True, ia=True, segunda_lectura={
        "ia": {"cuantia": "127019.94"}, "tesseract": {"cuantia": "127019.94"}, "difieren": []}))
    page = text(web.get("/obras/1").text)
    assert "Las dos lecturas del escaneo no coinciden en la cuantía: S/ 127,019.94 y S/ 127,019.84. Mirar la página." in page
    assert "sin observaciones" not in page
    assert "Las dos lecturas" not in text(web.get("/obras/2").text)


def test_a_name_unlike_the_seace_description_asks_for_a_look_not_a_consult(web, conn):
    signed_in(web, conn)
    add(conn, 1, ["LA LIBERTAD"], NOW + timedelta(days=2))
    doc = bases(conn, 1, lectura=reading())
    conn.execute("INSERT INTO extracciones (documento_id, version_extractor, campos, estado) VALUES (%s, 'objeto-3', %s, 'done')",
                 [doc, json.dumps({"obra": "CONSIGNAR NOMBRE DE LA OBRA A EJECUTAR", "cui": None, "pagina": 20,
                                   "ocr": False, "revisar": None, "archivo": "BASES.pdf",
                                   "avisos": [{"aviso": "nombre_distinto_seace", "parecido": 0.08}]})])
    page = text(web.get("/obras/1").text)
    assert "no se parece a la descripción del SEACE" in page
    found = next(o for o in data.op.obras(conn, ["LA LIBERTAD"], NOW) if o["nid_proceso"] == 1)
    assert data.consult_count(found) == 0


def extraction(conn, doc, version, campos):
    conn.execute("INSERT INTO extracciones (documento_id, version_extractor, campos, estado) VALUES (%s, %s, %s, 'done')",
                 [doc, version, json.dumps(campos)])


QUALITY = {"letra": "F", "factor": "Gestión de calidad", "nombre": "GESTIÓN DE CALIDAD", "pagina": 55,
           "puntaje_maximo": 10, "comprobado": True,
           "que_se_evalua": "Certificación ISO 9001:2015 vigente con alcance en ejecución de obras.",
           "como_se_acredita": "Copia simple del certificado.",
           "tramos": [{"condicion": "Con alcance en obras", "puntos": 10}, {"condicion": "No presenta", "puntos": 0}]}
RESIDENTE = {"cargo": "Residente de Obra", "formacion": "Ingeniero Civil o Agrícola", "colegiatura": True,
             "experiencia_meses": 12, "experiencia_en": "Residente o supervisor en obras de riego", "capacitacion": None}


def test_the_obra_page_shows_what_each_factor_asks_and_each_cargos_profile_with_its_page(web, conn):
    signed_in(web, conn)
    add(conn, 1, ["LA LIBERTAD"], NOW + timedelta(days=2))
    doc = bases(conn, 1, lectura=reading())
    extraction(conn, doc, "requisitos-1", {"factores": [QUALITY], "personal": [RESIDENTE], "pagina_factores": 53,
                                           "pagina_personal": 40, "personal_comprobado": True, "revisar": None,
                                           "archivo_factores": "BASES.pdf", "archivo_personal": "BASES.pdf"})
    html = web.get("/obras/1").text
    page = text(html)
    assert "F. GESTIÓN DE CALIDAD 10 pts pág. 55" in page.replace("Gestión de calidad", "GESTIÓN DE CALIDAD")
    assert "ISO 9001:2015 vigente" in page and "Se acredita con: Copia simple del certificado." in page
    assert "10 pts Con alcance en obras" in page
    assert "Perfil del personal clave pág. 40" in page
    assert re.search(r"Residente de Obra Ingeniero Civil o Agrícola\s*, colegiado y habilitado 12 Residente o supervisor",
                     page)
    assert "/bases/" in html and "BASES.pdf#page=55" in html
    assert "no se pudieron comprobar" not in page


def test_an_old_requirements_row_takes_its_file_from_the_rule_reader(conn):
    obra = {"nid_proceso": 1, "bases_id": 7, "factores": {"archivo": "BASES.pdf", "factores": []},
            "personal": None, "requisitos": {"factores": [{**QUALITY, "comprobado": False}], "personal": []}}
    found = data.requirements(obra)
    assert found["factores"][0]["enlace"] == "/obras/1/bases/7/BASES.pdf#page=55"
    assert found["factores"][0]["comprobado"] is False


def test_a_factor_with_other_points_in_its_description_than_in_the_summary_asks_for_a_look(web, conn):
    signed_in(web, conn)
    add(conn, 1, ["LA LIBERTAD"], NOW + timedelta(days=2))
    doc = bases(conn, 1, lectura=reading())
    extraction(conn, doc, "factores-5", {"factores": [{"factor": "Gestión de calidad", "puntos": "5"},
                                                      {"factor": "Sostenibilidad social", "puntos": "5"}],
                                         "total": "10", "pagina": 60, "ocr": False, "revisar": None, "avisos": [],
                                         "archivo": "BASES.pdf"})
    extraction(conn, doc, "requisitos-1", {"factores": [{**QUALITY, "comprobado": False}], "personal": [],
                                           "revisar": None, "archivo_factores": "BASES.pdf"})
    page = text(web.get("/obras/1").text)
    assert "El factor Gestión de calidad da 10 puntos en su descripción y 5 en el cuadro resumen. Mirar la página." in page
    assert "El factor Sostenibilidad social está en el cuadro resumen, pero no se encontró su descripción." in page
    assert "Los puntos no se pudieron comprobar con el cuadro resumen." in page
    found = next(o for o in data.op.obras(conn, ["LA LIBERTAD"], NOW) if o["nid_proceso"] == 1)
    assert data.consult_count(found) == 0


def test_factors_that_agree_ask_for_nothing(conn):
    obra = {"nid_proceso": 1, "bases_id": 7, "factores": {"factores": [{"factor": "Gestión de calidad", "puntos": "10"}]},
            "requisitos": {"factores": [QUALITY]}}
    look = []
    data.factors_disagree(obra, look)
    assert look == []


def test_a_summary_row_without_a_readable_name_matches_the_described_factor_with_its_points(conn):
    from seace_monitor.factores import UNNAMED
    obra = {"nid_proceso": 1, "bases_id": 7,
            "factores": {"factores": [{"factor": UNNAMED, "puntos": "10"}, {"factor": UNNAMED, "puntos": "10"}]},
            "requisitos": {"factores": [QUALITY, {**QUALITY, "factor": "Capacitación", "puntaje_maximo": 10},
                                        {**QUALITY, "factor": "Plan BIM", "puntaje_maximo": None}]}}
    look = []
    data.factors_disagree(obra, look)
    assert look == []
