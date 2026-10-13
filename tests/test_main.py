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
