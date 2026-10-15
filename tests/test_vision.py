from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest

from seace_monitor import vision
from seace_monitor.bases_text import ToolMissing, pdftotext, text_of
from seace_monitor.ocr import ia_path
from seace_monitor.search import LIMA

SCAN = Path(__file__).parent / "fixtures" / "bases_scanned_page.pdf"


def has_pdftotext() -> bool:
    try:
        return bool(pdftotext())
    except ToolMissing:
        return False


needs_pdftotext = pytest.mark.skipif(not has_pdftotext(), reason="pdftotext not installed")


def fake_render(path, page, folder):
    return b"png"


@needs_pdftotext
def test_every_image_page_takes_its_transcription_and_the_file_is_shaped_like_the_ocr_copy(tmp_path):
    path = tmp_path / "BASES.pdf"
    path.write_bytes(SCAN.read_bytes())
    asked = []

    def ask(key, image):
        asked.append(key)
        return "1.4 LA CUANTIA ES S/ 1,250,000.00\r\nfin de pagina", Decimal("0.0011")

    out, cost, pages = vision.transcribe(path, "clave", ask, fake_render)
    assert out == ia_path(path) and pages == len(asked) and cost == Decimal("0.0011") * pages
    text = text_of(out)
    assert "1.4 LA CUANTIA ES S/ 1,250,000.00\nfin de pagina\n" in text and "\r" not in text
    assert set(asked) == {"clave"}


@needs_pdftotext
def test_a_failed_page_writes_nothing(tmp_path):
    path = tmp_path / "BASES.pdf"
    path.write_bytes(SCAN.read_bytes())

    def ask(key, image):
        raise vision.VisionError("OpenRouter answered 500")

    with pytest.raises(vision.VisionError):
        vision.transcribe(path, "clave", ask, fake_render)
    assert not ia_path(path).exists()


def test_spending_adds_up_per_month(conn):
    october, november = datetime(2026, 10, 15, tzinfo=LIMA), datetime(2026, 11, 2, tzinfo=LIMA)
    vision.add_spending(conn, october, Decimal("1.5"), 100)
    vision.add_spending(conn, october, Decimal("0.25"), 20)
    vision.add_spending(conn, november, Decimal("0.1"), 5)
    assert vision.spent(conn, october) == Decimal("1.75")
    assert vision.spent(conn, november) == Decimal("0.1")
    assert conn.execute("SELECT paginas FROM gasto_ia WHERE mes = '2026-10-01'").fetchone()[0] == 120


def test_without_a_cap_or_a_key_nothing_is_sent(conn, monkeypatch, capsys):
    from seace_monitor import __main__ as main
    monkeypatch.setattr(vision, "transcribe", lambda *a, **k: pytest.fail("sent without a cap or a key"))
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    main.run_transcription(conn, {"vision": {"tope_mensual_usd": 35}}, [1])
    main.run_transcription(conn, {}, [1])
    assert "OPENROUTER_API_KEY not set" in capsys.readouterr().out


@needs_pdftotext
def test_no_file_is_started_once_the_month_reached_the_cap(conn, monkeypatch, tmp_path):
    from seace_monitor import __main__ as main
    path = tmp_path / "BASES.pdf"
    path.write_bytes(SCAN.read_bytes())
    monkeypatch.setenv("OPENROUTER_API_KEY", "clave")
    monkeypatch.setattr(main, "newest_bases", lambda conn, nids: [
        {"id": 1, "nid_proceso": 1, "ruta_local": str(path), "contents": []}])
    vision.add_spending(conn, datetime.now(LIMA), Decimal("35"), 30000)
    monkeypatch.setattr(vision, "transcribe", lambda *a, **k: pytest.fail("sent over the cap"))
    main.run_transcription(conn, {"vision": {"tope_mensual_usd": 35}}, [1])

    sent = []
    def transcribe(p, key, charge):
        sent.append(p)
        charge(Decimal("0.01"))
        return ia_path(p), Decimal("0.01"), 1

    monkeypatch.setattr(vision, "transcribe", transcribe)
    main.run_transcription(conn, {"vision": {"tope_mensual_usd": 36}}, [1])
    assert sent == [path] and vision.spent(conn, datetime.now(LIMA)) == Decimal("35.01")


def test_a_malformed_answer_or_a_slow_render_is_a_vision_error(monkeypatch, tmp_path):
    class Answer:
        status_code, text = 200, "<html>gateway</html>"

        def json(self):
            raise ValueError("not json")

    monkeypatch.setattr(vision.requests, "post", lambda *a, **k: Answer())
    with pytest.raises(vision.VisionError):
        vision.ask("clave", b"png")

    def slow(*a, **k):
        raise vision.subprocess.TimeoutExpired("pdftoppm", 300)

    monkeypatch.setattr(vision.subprocess, "run", slow)
    with pytest.raises(vision.VisionError):
        vision.render(SCAN, 1, tmp_path)


def test_pages_paid_before_a_failed_one_are_charged(monkeypatch, tmp_path):
    path = tmp_path / "BASES.pdf"
    path.write_bytes(SCAN.read_bytes())
    monkeypatch.setattr(vision, "image_pages", lambda text: [1, 2])
    monkeypatch.setattr(vision, "text_of", lambda p: "")
    answers = iter([("pagina uno", Decimal("0.002"))])

    def ask(key, image):
        try:
            return next(answers)
        except StopIteration:
            raise vision.VisionError("OpenRouter answered 502") from None

    charged = []
    with pytest.raises(vision.VisionError):
        vision.transcribe(path, "clave", ask, fake_render, charged.append)
    assert charged == [Decimal("0.002")] and not ia_path(path).exists()


def test_an_empty_answer_is_a_blank_page_only_when_the_model_finished(monkeypatch):
    class Answer:
        status_code, text = 200, ""

        def __init__(self, reason):
            self.reason = reason

        def json(self):
            return {"choices": [{"message": {"content": ""}, "finish_reason": self.reason}], "usage": {"cost": 0.001}}

    monkeypatch.setattr(vision.requests, "post", lambda *a, **k: Answer("stop"))
    assert vision.ask("clave", b"png") == ("", Decimal("0.001"))
    monkeypatch.setattr(vision.requests, "post", lambda *a, **k: Answer("length"))
    with pytest.raises(vision.VisionError):
        vision.ask("clave", b"png")
