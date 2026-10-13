import contextlib
import re
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

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
    assert "Para consultar con la entidad" in page and "Ver pág. 21" in page
    assert re.search(r'href="/obras/1/bases/\d+/BASES.pdf#page=21"', page)
    assert web.get("/obras/999").status_code == 404


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
