"""Runs against a test database in the Docker Postgres (see conftest.py)."""

from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

import psycopg
import pytest

from seace_monitor import db
from seace_monitor.locate import locate
from seace_monitor.search import LIMA, parse_results
from seace_monitor.ficha import parse_documents
from seace_monitor.store import (
    MAX_ATTEMPTS, STALLED_DAYS, archives_to_unpack, contents_done, contents_failed, document_done, document_failed,
    ficha_failed, fichas_to_read, link_restarts, mark_stalled, open_since, pending_documents, save_ficha,
    save_new_licitaciones, tracked,
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


def test_ficha_with_bases_is_done_and_read_again_only_while_tracked(conn, rows, documents):
    save_new_licitaciones(conn, rows[:1])
    nid = rows[0]["nid_proceso"]
    assert save_ficha(conn, nid, documents, estados=["Convocado"]) == 2
    assert ficha_state(conn, nid) == ("done", 0)
    assert fichas_to_read(conn, [nid]) == {nid}
    assert save_ficha(conn, nid, documents, estados=["Desierto"]) == 0
    assert fichas_to_read(conn, [nid]) == set()


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


def tracking(conn, nid):
    return conn.execute(
        "SELECT seguimiento, seguimiento_hasta IS NOT NULL FROM licitaciones WHERE nid_proceso = %s", [nid]
    ).fetchone()


def test_new_obra_is_tracked(conn, rows, documents):
    save_new_licitaciones(conn, rows[:1])
    nid = rows[0]["nid_proceso"]
    save_ficha(conn, nid, documents, estados=["Convocado"])
    assert tracking(conn, nid) == ("abierta", False)


def test_obra_closes_when_no_item_is_convocado(conn, rows, documents):
    save_new_licitaciones(conn, rows[:1])
    nid = rows[0]["nid_proceso"]
    save_ficha(conn, nid, documents, estados=["Convocado", "Desierto"])
    assert tracking(conn, nid) == ("abierta", False)
    save_ficha(conn, nid, documents, estados=["Adjudicado", "Desierto"])
    assert tracking(conn, nid) == ("cerrada", True)


def test_obra_closes_when_offers_are_published(conn, rows, documents):
    save_new_licitaciones(conn, rows[:1])
    nid = rows[0]["nid_proceso"]
    offers = {**documents[0], "uuid": "offers", "tipo": "Documentos de Presentación de Propuestas"}
    save_ficha(conn, nid, documents + [offers], estados=["Convocado"])
    assert tracking(conn, nid) == ("cerrada", True)


def test_closed_obra_does_not_reopen(conn, rows, documents):
    save_new_licitaciones(conn, rows[:1])
    nid = rows[0]["nid_proceso"]
    save_ficha(conn, nid, documents, estados=["Nulo"])
    save_ficha(conn, nid, documents, estados=["Convocado"])
    assert tracking(conn, nid) == ("cerrada", True)


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


def history(conn, nid):
    return conn.execute(
        "SELECT campo, valor_anterior, valor_nuevo FROM historial WHERE nid_proceso = %s ORDER BY id", [nid]
    ).fetchall()


def last_change(conn, nid):
    return conn.execute("SELECT ultimo_cambio_en FROM licitaciones WHERE nid_proceso = %s", [nid]).fetchone()[0]


def test_postponed_deadline_keeps_the_old_one_in_historial(conn, rows, documents):
    save_new_licitaciones(conn, rows[:1])
    nid = rows[0]["nid_proceso"]
    later = datetime(2026, 10, 20, 23, 59, tzinfo=LIMA)
    save_ficha(conn, nid, documents, datetime(2026, 10, 9, 23, 59, tzinfo=LIMA), ["Convocado"])
    save_ficha(conn, nid, documents, later, ["Convocado"])
    stored = conn.execute("SELECT fecha_limite_ofertas FROM licitaciones WHERE nid_proceso = %s", [nid]).fetchone()[0]
    assert stored == later
    assert history(conn, nid) == [("fecha_limite_ofertas", "09/10/2026 23:59", "20/10/2026 23:59")]
    assert last_change(conn, nid) is not None


def test_first_reading_is_not_a_change(conn, rows, documents):
    save_new_licitaciones(conn, rows[:1])
    nid = rows[0]["nid_proceso"]
    save_ficha(conn, nid, documents, datetime(2026, 10, 9, 23, 59, tzinfo=LIMA), ["Convocado"])
    assert history(conn, nid) == []
    assert last_change(conn, nid) is None


def test_same_ficha_again_is_not_a_change(conn, rows, documents):
    save_new_licitaciones(conn, rows[:1])
    nid = rows[0]["nid_proceso"]
    deadline = datetime(2026, 10, 9, 23, 59, tzinfo=LIMA)
    save_ficha(conn, nid, documents, deadline, ["Convocado"])
    save_ficha(conn, nid, documents, deadline, ["Convocado"])
    assert history(conn, nid) == []


def test_estado_change_and_closing_go_to_historial(conn, rows, documents):
    save_new_licitaciones(conn, rows[:1])
    nid = rows[0]["nid_proceso"]
    save_ficha(conn, nid, documents, estados=["Convocado", "Convocado"])
    save_ficha(conn, nid, documents, estados=["Adjudicado", "Desierto"])
    assert history(conn, nid) == [
        ("estado_items", "Convocado / Convocado", "Adjudicado / Desierto"),
        ("seguimiento", "abierta", "cerrada"),
    ]


def restart_of(rows, base, nid, **changes):
    return {**base, "nid_proceso": nid, **changes}


def links(conn):
    return conn.execute(
        "SELECT nid_proceso, reinicio_de, seguimiento FROM licitaciones ORDER BY nid_proceso"
    ).fetchall()


def test_restart_links_to_the_earlier_obra_and_stops_tracking_it(conn, rows, documents):
    old = rows[0]
    save_new_licitaciones(conn, [old])
    save_ficha(conn, old["nid_proceso"], documents, estados=["Convocado"])
    new = restart_of(rows, old, old["nid_proceso"] + 1000, reiniciado_desde="Registro de puntaje técnico")
    save_new_licitaciones(conn, [new])
    assert link_restarts(conn) == [(old["nid_proceso"], new["nid_proceso"])]
    assert links(conn) == [(old["nid_proceso"], None, "reiniciada"), (new["nid_proceso"], old["nid_proceso"], "abierta")]
    assert history(conn, new["nid_proceso"]) == [
        ("reinicio", None, f"reiniciada desde Registro de puntaje técnico; antes nid {old['nid_proceso']}, estado Convocado")
    ]
    assert history(conn, old["nid_proceso"]) == [("seguimiento", "abierta", "reiniciada")]
    assert link_restarts(conn) == []


def test_closed_earlier_obra_stays_closed(conn, rows, documents):
    old = rows[0]
    save_new_licitaciones(conn, [old])
    save_ficha(conn, old["nid_proceso"], documents, estados=["Nulo"])
    save_new_licitaciones(conn, [restart_of(rows, old, old["nid_proceso"] + 1000)])
    link_restarts(conn)
    assert links(conn)[0] == (old["nid_proceso"], None, "cerrada")
    assert history(conn, old["nid_proceso"]) == []


def test_chain_of_restarts_links_each_to_the_one_before(conn, rows):
    a = rows[0]
    b, c = (restart_of(rows, a, a["nid_proceso"] + k) for k in (1000, 2000))
    save_new_licitaciones(conn, [a, b, c])
    link_restarts(conn)
    assert [l[:2] for l in links(conn)] == [(a["nid_proceso"], None), (b["nid_proceso"], a["nid_proceso"]),
                                            (c["nid_proceso"], b["nid_proceso"])]


def test_same_nomenclatura_of_another_entidad_is_not_a_restart(conn, rows):
    a = rows[0]
    save_new_licitaciones(conn, [a, restart_of(rows, a, a["nid_proceso"] + 1000, entidad="OTRA ENTIDAD")])
    assert link_restarts(conn) == []


def test_obra_found_late_does_not_link_an_obra_twice(conn, rows):
    a = rows[0]
    b, c = (restart_of(rows, a, a["nid_proceso"] + k) for k in (1000, 2000))
    save_new_licitaciones(conn, [a, c])
    link_restarts(conn)
    save_new_licitaciones(conn, [b])
    assert link_restarts(conn) == []


def test_tracked_obras_are_read_again_and_closed_ones_are_not(conn, rows, documents):
    a, b = rows[0]["nid_proceso"], rows[1]["nid_proceso"]
    save_new_licitaciones(conn, rows[:2])
    save_ficha(conn, a, documents, estados=["Convocado"])
    save_ficha(conn, b, documents, estados=["Contratado"])
    assert fichas_to_read(conn, [a, b]) == {a}
    assert tracked(conn) == [a]


def test_failed_re_reading_keeps_the_ficha_done(conn, rows, documents):
    save_new_licitaciones(conn, rows[:1])
    nid = rows[0]["nid_proceso"]
    save_ficha(conn, nid, documents, estados=["Convocado"])
    for _ in range(MAX_ATTEMPTS):
        ficha_failed(conn, nid, "timeout")
    assert ficha_state(conn, nid) == ("done", 0)
    assert fichas_to_read(conn, [nid]) == {nid}


def test_search_range_starts_at_the_oldest_tracked_obra(conn, rows, documents):
    save_new_licitaciones(conn, rows)
    oldest = min(rows, key=lambda r: r["fecha_publicacion"])
    save_ficha(conn, oldest["nid_proceso"], documents, estados=["Nulo"])
    still = min((r for r in rows if r is not oldest), key=lambda r: r["fecha_publicacion"])
    assert open_since(conn) == {"LA LIBERTAD": still["fecha_publicacion"].date()}


def test_obra_without_change_for_60_days_stops_being_tracked(conn, rows, documents):
    save_new_licitaciones(conn, rows[:2])
    a, b = rows[0]["nid_proceso"], rows[1]["nid_proceso"]
    published = rows[0]["fecha_publicacion"]
    save_ficha(conn, b, documents, datetime(2026, 10, 9, 23, 59, tzinfo=LIMA), ["Convocado"])
    save_ficha(conn, b, documents, datetime(2026, 10, 20, 23, 59, tzinfo=LIMA), ["Convocado"])  # a change today
    later = max(published, rows[1]["fecha_publicacion"]) + timedelta(days=STALLED_DAYS, minutes=1)
    assert mark_stalled(conn, later) == [a]
    assert tracking(conn, a) == ("parada", True)
    assert history(conn, a) == [("seguimiento", "abierta", "parada")]
    assert tracking(conn, b) == ("abierta", False)
    assert mark_stalled(conn, later) == []


def test_new_document_goes_to_historial(conn, rows, documents):
    save_new_licitaciones(conn, rows[:1])
    nid = rows[0]["nid_proceso"]
    save_ficha(conn, nid, documents, estados=["Convocado"])
    integradas = {**documents[0], "uuid": "integradas", "tipo": "Bases Integradas", "nombre_archivo": "bi.pdf"}
    assert save_ficha(conn, nid, documents + [integradas], estados=["Convocado"]) == 1
    assert history(conn, nid) == [("documento", None, "Bases Integradas: bi.pdf")]
