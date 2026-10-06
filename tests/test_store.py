"""Runs against a test database in the Docker Postgres (see conftest.py)."""

from datetime import datetime
from decimal import Decimal
from pathlib import Path

import psycopg
import pytest

from seace_monitor import db
from seace_monitor.locate import locate
from seace_monitor.search import LIMA, parse_results
from seace_monitor.ficha import parse_documents
from seace_monitor.store import (
    MAX_ATTEMPTS, archives_to_unpack, contents_done, contents_failed, document_done, document_failed,
    ficha_failed, fichas_to_read, pending_documents, save_ficha, save_new_licitaciones,
)

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def rows():
    rows = parse_results((FIXTURES / "search_page1.xml").read_text(encoding="utf-8")).rows
    for row in rows:
        row["departamentos"], row["ubicacion_fuente"] = locate(row["descripcion"])
        row["departamento_busqueda"] = "LA LIBERTAD"
    return rows


def test_first_save_inserts_every_row(conn, rows):
    new = save_new_licitaciones(conn, rows)
    assert sorted(new) == sorted(r["nid_proceso"] for r in rows)


def test_second_save_inserts_nothing(conn, rows):
    save_new_licitaciones(conn, rows)
    assert save_new_licitaciones(conn, rows) == []
    assert conn.execute("SELECT count(*) FROM licitaciones").fetchone()[0] == len(rows)


def test_known_row_is_not_overwritten(conn, rows):
    save_new_licitaciones(conn, rows)
    changed = dict(rows[0], valor_referencial=Decimal("1.00"))
    save_new_licitaciones(conn, [changed])
    stored = conn.execute(
        "SELECT valor_referencial FROM licitaciones WHERE nid_proceso = %s", [changed["nid_proceso"]]
    ).fetchone()[0]
    assert stored == rows[0]["valor_referencial"]


def test_values_round_trip(conn, rows):
    save_new_licitaciones(conn, rows[:1])
    stored = conn.execute(
        "SELECT nomenclatura, fecha_publicacion, valor_referencial, moneda FROM licitaciones"
    ).fetchone()
    first = rows[0]
    assert stored == (first["nomenclatura"], first["fecha_publicacion"], first["valor_referencial"], first["moneda"])


def test_one_bad_row_stores_none_of_the_search(conn, rows):
    broken = dict(rows[1], entidad=None)
    with pytest.raises(psycopg.errors.NotNullViolation):
        save_new_licitaciones(conn, [rows[0], broken])
    assert conn.execute("SELECT count(*) FROM licitaciones").fetchone()[0] == 0


def test_departamentos_stored_as_list(conn, rows):
    save_new_licitaciones(conn, rows[:1])
    stored = conn.execute("SELECT departamentos, ubicacion_fuente FROM licitaciones").fetchone()
    assert stored == (rows[0]["departamentos"], rows[0]["ubicacion_fuente"])



def test_search_departamento_is_stored(conn, rows):
    save_new_licitaciones(conn, rows[:1])
    assert conn.execute("SELECT departamento_busqueda FROM licitaciones").fetchone() == ("LA LIBERTAD",)

def ficha_state(conn, nid):
    return conn.execute(
        "SELECT ficha_estado, ficha_intentos FROM licitaciones WHERE nid_proceso = %s", [nid]
    ).fetchone()


@pytest.fixture(scope="module")
def documents():
    return parse_documents((FIXTURES / "ficha_two_documents.html").read_text(encoding="utf-8"))


def test_new_rows_need_their_ficha(conn, rows):
    save_new_licitaciones(conn, rows)
    nids = [r["nid_proceso"] for r in rows]
    assert fichas_to_read(conn, nids) == set(nids)


def test_ficha_with_bases_is_done_and_not_read_again(conn, rows, documents):
    save_new_licitaciones(conn, rows[:1])
    nid = rows[0]["nid_proceso"]
    assert save_ficha(conn, nid, documents) == 2
    assert ficha_state(conn, nid) == ("done", 0)
    assert fichas_to_read(conn, [nid]) == set()
    assert save_ficha(conn, nid, documents) == 0


def test_ficha_without_bases_stays_pending_without_spending_attempts(conn, rows, documents):
    save_new_licitaciones(conn, rows[:1])
    nid = rows[0]["nid_proceso"]
    save_ficha(conn, nid, documents[:1])
    assert ficha_state(conn, nid) == ("pending", 0)


def test_failed_ficha_is_retried_until_the_limit(conn, rows):
    save_new_licitaciones(conn, rows[:1])
    nid = rows[0]["nid_proceso"]
    for _ in range(MAX_ATTEMPTS - 1):
        ficha_failed(conn, nid, "timeout")
    assert ficha_state(conn, nid) == ("pending", MAX_ATTEMPTS - 1)
    ficha_failed(conn, nid, "timeout")
    assert ficha_state(conn, nid) == ("error", MAX_ATTEMPTS)
    assert fichas_to_read(conn, [nid]) == set()



def test_item_estados_are_replaced_by_each_reading(conn, rows, documents):
    save_new_licitaciones(conn, rows[:1])
    nid = rows[0]["nid_proceso"]
    save_ficha(conn, nid, documents, estados=["Convocado"])
    save_ficha(conn, nid, documents, estados=["Adjudicado", "Desierto"])
    stored = conn.execute("SELECT estado_items FROM licitaciones WHERE nid_proceso = %s", [nid]).fetchone()
    assert stored == (["Adjudicado", "Desierto"],)

def test_document_states(conn, rows, documents):
    save_new_licitaciones(conn, rows[:1])
    save_ficha(conn, rows[0]["nid_proceso"], documents)
    nid = rows[0]["nid_proceso"]
    first, second = pending_documents(conn, [nid])
    document_done(conn, first["id"], "data/x.pdf", 10)
    for _ in range(MAX_ATTEMPTS):
        document_failed(conn, second["id"], "hangs")
    assert pending_documents(conn, [nid]) == []
    assert conn.execute("SELECT estado FROM documentos ORDER BY id").fetchall() == [("done",), ("error",)]


def test_document_without_link_is_stored_once_and_never_downloaded(conn, rows, documents):
    save_new_licitaciones(conn, rows[:1])
    nid = rows[0]["nid_proceso"]
    linkless = [{**d, "uuid": None} for d in documents]
    assert save_ficha(conn, nid, linkless) == 2
    assert save_ficha(conn, nid, linkless) == 0
    assert pending_documents(conn, [nid]) == []
    assert ficha_state(conn, nid) == ("pending", 0)
    assert conn.execute("SELECT estado FROM documentos").fetchall() == [("sin_enlace",), ("sin_enlace",)]


def test_pending_documents_only_of_the_obras_asked_for(conn, rows, documents):
    save_new_licitaciones(conn, rows[:2])
    wanted, other = rows[0]["nid_proceso"], rows[1]["nid_proceso"]
    save_ficha(conn, wanted, documents)
    save_ficha(conn, other, [{**d, "uuid": d["uuid"] + "-other"} for d in documents])
    assert {d["nid_proceso"] for d in pending_documents(conn, [wanted])} == {wanted}
    assert pending_documents(conn, []) == []



def downloaded(conn, rows, documents, *paths):
    save_new_licitaciones(conn, rows[:1])
    save_ficha(conn, rows[0]["nid_proceso"], documents)
    ids = [d["id"] for d in pending_documents(conn, [rows[0]["nid_proceso"]])]
    for doc_id, path in zip(ids, paths):
        document_done(conn, doc_id, path, 10)
    return ids


def test_only_downloaded_archives_are_unpacked(conn, rows, documents):
    archive, _ = downloaded(conn, rows, documents, "data/BASES.RAR", "data/bases.pdf")
    assert archives_to_unpack(conn) == [{"id": archive, "ruta_local": "data/BASES.RAR"}]
    assert archives_to_unpack(conn, [rows[0]["nid_proceso"]]) == archives_to_unpack(conn)
    assert archives_to_unpack(conn, [rows[1]["nid_proceso"]]) == []


def test_unpacked_archive_is_not_unpacked_again(conn, rows, documents):
    archive, _ = downloaded(conn, rows, documents, "data/BASES.zip")
    files = [
        {"ruta": "bases.pdf", "tamano_bytes": 9, "dentro_de": "", "error": None},
        {"ruta": "planos.zip", "tamano_bytes": 5, "dentro_de": "", "error": "Wrong password"},
    ]
    contents_done(conn, archive, files)
    contents_done(conn, archive, files[:1])
    assert archives_to_unpack(conn) == []
    assert conn.execute("SELECT ruta, dentro_de FROM documento_contenido").fetchall() == [("bases.pdf", "")]


def test_broken_archive_keeps_its_error_and_is_not_retried(conn, rows, documents):
    archive, _ = downloaded(conn, rows, documents, "data/BASES.7z")
    contents_failed(conn, archive, "Wrong password")
    assert archives_to_unpack(conn) == []
    assert conn.execute("SELECT contenido_estado, contenido_error FROM documentos WHERE id = %s",
                        [archive]).fetchone() == ("error", "Wrong password")

def test_writes_survive_the_connection(test_dbname, rows, documents):
    """A read before a write must not leave the write uncommitted."""
    nid = rows[0]["nid_proceso"]
    try:
        with db.connect(test_dbname) as first:
            save_new_licitaciones(first, rows[:1])
            fichas_to_read(first, [nid])
            save_ficha(first, nid, documents)
        with db.connect(test_dbname) as second:
            assert ficha_state(second, nid) == ("done", 0)
            assert second.execute("SELECT count(*) FROM documentos WHERE nid_proceso = %s", [nid]).fetchone()[0] == 2
    finally:
        with db.connect(test_dbname) as cleanup:
            cleanup.execute("DELETE FROM documentos WHERE nid_proceso = %s", [nid])
            cleanup.execute("DELETE FROM licitaciones WHERE nid_proceso = %s", [nid])


def test_deadline_is_stored_once_and_never_overwritten(conn, rows, documents):
    save_new_licitaciones(conn, rows[:1])
    nid = rows[0]["nid_proceso"]
    first = datetime(2026, 10, 9, 23, 59, tzinfo=LIMA)
    save_ficha(conn, nid, documents, first)
    save_ficha(conn, nid, documents, datetime(2026, 10, 20, 23, 59, tzinfo=LIMA))
    stored = conn.execute("SELECT fecha_limite_ofertas FROM licitaciones WHERE nid_proceso = %s", [nid]).fetchone()[0]
    assert stored == first
