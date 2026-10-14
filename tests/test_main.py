import sys

import pytest

from seace_monitor import __main__ as monitor


@pytest.fixture
def calls(monkeypatch, tmp_path):
    """Run main with every part replaced by a recorder; the report is never sent."""
    seen = []
    config = tmp_path / "config.toml"
    config.write_text('[search]\nobjeto = "Obra"\ndepartamentos = ["LA LIBERTAD"]\ndias = 3\n', encoding="utf-8")
    monkeypatch.setattr(monitor.db, "connect", lambda: None)
    monkeypatch.setattr(monitor.db, "migrate", lambda conn: [])
    monkeypatch.setattr(monitor, "run_notices", lambda *a: seen.append("notices"))
    monkeypatch.setattr(monitor, "run_reading", lambda *a: seen.append("reading"))
    monkeypatch.setattr(monitor.manual, "import_ready", lambda conn, folder: ([], []))
    monkeypatch.setattr(monitor.report, "build", lambda *a, **k: seen.append("report") or monitor.report.Report("x", [], []))
    monkeypatch.setattr(monitor.obra_page, "write", lambda *a: tmp_path / "page.html")

    def run(*flags):
        monkeypatch.setattr(sys, "argv", ["seace_monitor", "--config", str(config), "--no-mail", *flags])
        assert monitor.main() == 0
        return seen
    return run


def test_notices_never_download_or_read(calls):
    assert calls("--avisos") == ["notices", "report"]


def test_reading_sends_no_report(calls):
    assert calls("--lectura") == ["reading"]


def test_without_a_part_both_run_before_the_report(calls):
    assert calls() == ["notices", "reading", "report"]


def test_an_untrusted_cronograma_keeps_the_stored_one_and_the_documents_are_still_saved(conn, monkeypatch, capsys):
    from pathlib import Path
    from seace_monitor.store import save_new_licitaciones
    page = (Path(__file__).parent / "fixtures" / "ficha_two_documents.html").read_text(encoding="utf-8")
    page = page.replace('<td role="gridcell">29/09/2026 </td>', "", 1)  # a cronograma row loses a cell
    nid = 999001
    save_new_licitaciones(conn, [{
        "nid_proceso": nid, "nomenclatura": "LP-ABR-8-2026-MDS-CS-2", "entidad": "MUNICIPALIDAD DE PRUEBA",
        "objeto": "Obra", "descripcion": "obra de prueba", "fecha_publicacion": None, "valor_referencial": None,
        "moneda": None, "cui": None, "reiniciado_desde": None, "departamentos": ["LA LIBERTAD"],
        "ubicacion_fuente": "text", "departamento_busqueda": "LA LIBERTAD"}])
    conn.execute("INSERT INTO cronograma (nid_proceso, orden, etapa, inicio, fin) VALUES (%s, 1, 'Convocatoria', "
                 "'28/09/2026', '28/09/2026')", [nid])
    monkeypatch.setattr(monitor, "open_ficha", lambda *a: page)
    assert monitor.read_ficha(conn, None, None, {"nid_proceso": nid}, "line")
    assert "cronograma and deadline kept as stored" in capsys.readouterr().out
    assert conn.execute("SELECT count(*) FROM documentos WHERE nid_proceso = %s", [nid]).fetchone()[0] == 2
    assert conn.execute("SELECT etapa FROM cronograma WHERE nid_proceso = %s", [nid]).fetchall() == [("Convocatoria",)]
