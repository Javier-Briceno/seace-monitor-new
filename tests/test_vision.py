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

    out, cost, pages, reused = vision.transcribe(path, "clave", ask, fake_render)
    assert out == ia_path(path) and pages == len(asked) and cost == Decimal("0.0011") * pages and reused == 0
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
    def transcribe(p, key, charge, known):
        sent.append(p)
        charge(Decimal("0.01"))
        return ia_path(p), Decimal("0.01"), 1, 0

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
    monkeypatch.setattr(vision, "text_of", lambda p: "\f\f")
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


def pages_of(*texts):
    """A file's pdftotext text: pages split by form feeds, ending with one."""
    return "\f".join(texts) + "\f"


def scanned(monkeypatch, *texts, marks=None):
    """transcribe on a made-up file whose pages are these texts; '' is a scanned page. One page at a time, so the
    pages sent are exactly the ones a heading or the proforma leaves."""
    monkeypatch.setattr(vision, "WORKERS", 1)
    monkeypatch.setattr(vision, "text_of", lambda p: pages_of(*texts))
    monkeypatch.setattr(vision, "fingerprints", lambda p: marks or [None] * len(texts))


def answering(sent, texts=None):
    def ask(key, image):
        sent.append(image)
        return (texts or {}).get(image, f"pagina {image.decode()}"), Decimal("0.001")
    return ask


def numbered_render(path, page, folder):
    return str(page).encode()


def test_cyrillic_look_alikes_become_latin(monkeypatch, tmp_path):
    scanned(monkeypatch, "")
    path = tmp_path / "BASES.pdf"
    vision.transcribe(path, "clave", lambda k, i: ("LICITACIÓN PÚBLICА САРACITACIÓN", Decimal(0)), numbered_render)
    assert ia_path(path).read_text(encoding="utf-8").startswith("LICITACIÓN PÚBLICA CAPACITACIÓN\n")


def test_a_page_already_transcribed_in_another_file_is_not_paid_again(monkeypatch, tmp_path):
    scanned(monkeypatch, "", "", marks=["igual", "nueva"])
    sent = []
    out, cost, pages, reused = vision.transcribe(tmp_path / "INTEGRADAS.pdf", "clave", answering(sent), numbered_render,
                                                 known={"igual": "texto de la administrativa\n"})
    assert sent == [b"2"] and (pages, reused, cost) == (1, 1, Decimal("0.001"))
    assert out.read_text(encoding="utf-8").split("\f")[:2] == ["texto de la administrativa\n", "pagina 2\n"]


def test_the_seccion_general_is_skipped_until_the_seccion_especifica(monkeypatch, tmp_path):
    scanned(monkeypatch, "", "", "", "", "", "")
    texts = {b"2": "SECCIÓN GENERAL\nDISPOSICIONES COMUNES"}
    probed = []

    def probe(path, page):
        probed.append(page)
        return "SECCION ESPECIFICA\nCAPITULO I" if page == 5 else "texto estandar"

    sent = []
    vision.transcribe(tmp_path / "BASES.pdf", "clave", answering(sent, texts), numbered_render, probe=probe)
    assert sent == [b"1", b"2", b"5", b"6"] and probed == [3, 4, 5]
    assert ia_path(tmp_path / "BASES.pdf").read_text(encoding="utf-8").split("\f")[2:4] == ["", ""]


def test_a_seccion_general_without_an_end_is_sent_whole(monkeypatch, tmp_path):
    monkeypatch.setattr(vision, "GENERAL_PAGES", 3)
    scanned(monkeypatch, *[""] * 8)
    sent = []
    vision.transcribe(tmp_path / "BASES.pdf", "clave", answering(sent, {b"1": "x", b"2": "SECCIÓN GENERAL"}),
                      numbered_render, probe=lambda path, page: "")
    assert sorted(sent, key=int) == [str(n).encode() for n in range(1, 9)]


CHAPTERS = ("CAPÍTULO III\nREQUISITOS DE CALIFICACIÓN\nEXPERIENCIA DEL POSTOR EN LA ESPECIALIDAD\nRequisitos:\n"
            "El postor debe acreditar un monto facturado acumulado equivalente a S/ 100.00\n"
            "B.2 EXPERIENCIA DEL PERSONAL CLAVE\nRequisitos:\nResidente de obra 24 meses\n")
FACTORS = "CAPÍTULO IV\nFACTORES DE EVALUACIÓN\n" + "A. PLAZO\n" * 300
PROFORMA = "PROFORMA DEL CONTRATO\nCLÁUSULA PRIMERA: ANTECEDENTES\n"


def test_transcription_stops_at_the_proforma_once_chapters_iii_and_iv_are_behind(monkeypatch, tmp_path):
    scanned(monkeypatch, "", "", "", "", "", "")
    sent = []
    vision.transcribe(tmp_path / "BASES.pdf", "clave",
                      answering(sent, {b"2": CHAPTERS, b"3": FACTORS, b"4": PROFORMA}), numbered_render)
    assert sent == [b"1", b"2", b"3", b"4"]


def test_a_chapter_iii_behind_the_anexos_keeps_the_transcription_going(monkeypatch, tmp_path):
    scanned(monkeypatch, "", "", "", "", "", "")
    sent = []
    vision.transcribe(tmp_path / "BASES.pdf", "clave",
                      answering(sent, {b"2": FACTORS, b"3": PROFORMA, b"5": CHAPTERS}), numbered_render)
    assert sent == [str(n).encode() for n in range(1, 7)]


def test_an_unpacked_file_is_the_bases_by_its_name_or_its_first_pages(monkeypatch, tmp_path):
    texts = {"PLANO A-01.pdf": pages_of("PLANTA GENERAL"), "DOCUMENTOS.pdf": pages_of("", ""),
             "LPA_06.pdf": pages_of("BASES ESTÁNDAR DE LICITACIÓN PÚBLICA ABREVIADA")}
    monkeypatch.setattr(vision, "text_of", lambda p: texts[p.name])
    probe = lambda path, page: "BASES INTEGRADAS" if page == 2 else ""
    assert vision.is_bases(tmp_path / "Bases_Integradas.pdf")
    assert vision.is_bases(tmp_path / "LPA_06.pdf") and vision.is_bases(tmp_path / "DOCUMENTOS.pdf", probe)
    assert not vision.is_bases(tmp_path / "PLANO A-01.pdf", lambda path, page: "PLANTA")


def image_pdf(path, image_bytes, overlay=b""):
    import pikepdf
    pdf = pikepdf.new()
    image = pikepdf.Stream(pdf, image_bytes)
    image.Type, image.Subtype, image.Width, image.Height = pikepdf.Name.XObject, pikepdf.Name.Image, 1, 1
    image.ColorSpace, image.BitsPerComponent = pikepdf.Name.DeviceGray, 8
    pdf.add_blank_page(page_size=(100, 100))
    page = pdf.pages[0]
    page.Resources = pikepdf.Dictionary(XObject=pikepdf.Dictionary(Im0=image))
    page.Contents = pikepdf.Stream(pdf, b"q 100 0 0 100 0 0 cm /Im0 Do Q " + overlay)
    pdf.save(path)
    return path


def test_two_pages_are_the_same_only_when_they_draw_the_same_scan_and_the_same_on_top(tmp_path):
    one = vision.fingerprints(image_pdf(tmp_path / "a.pdf", b"\x80"))
    assert one == vision.fingerprints(image_pdf(tmp_path / "b.pdf", b"\x80")) and one[0]
    assert vision.fingerprints(image_pdf(tmp_path / "c.pdf", b"\x81")) != one
    # a line drawn over the same scan, as a correction would be
    struck = vision.fingerprints(image_pdf(tmp_path / "d.pdf", b"\x80", b"0 0 m 50 50 l S"))
    assert struck[0] and struck != one
    assert struck == vision.fingerprints(image_pdf(tmp_path / "e.pdf", b"\x80", b"0 0 m 50 50 l S"))


def test_known_pages_come_from_the_obras_other_transcribed_files(tmp_path):
    image_pdf(tmp_path / "ADMIN.pdf", b"\x80")
    ia_path(tmp_path / "ADMIN.pdf").write_bytes("texto de la pagina\n\f".encode())
    image_pdf(tmp_path / "SIN_IA.pdf", b"\x81")
    integradas = image_pdf(tmp_path / "INTEGRADAS.pdf", b"\x80")
    known = vision.known_pages(tmp_path, integradas)
    assert list(known.values()) == ["texto de la pagina\n"]
    assert vision.fingerprints(integradas)[0] in known


def test_the_night_reading_transcribes_only_the_bases_inside_an_archive(conn, monkeypatch, tmp_path):
    from seace_monitor import __main__ as main
    archive = tmp_path / "BASES.zip"
    folder = tmp_path / "BASES.zip_contenido"
    folder.mkdir()
    for name in ("bases integradas.pdf", "PLANO.pdf"):
        (folder / name).write_bytes(SCAN.read_bytes())
    monkeypatch.setenv("OPENROUTER_API_KEY", "clave")
    monkeypatch.setattr(main, "newest_bases", lambda conn, nids: [
        {"id": 1, "nid_proceso": 1, "ruta_local": str(archive), "contents": ["bases integradas.pdf", "PLANO.pdf"]}])
    monkeypatch.setattr(main, "bases_files", lambda ruta, contents: [folder / c for c in contents])
    monkeypatch.setattr(main, "image_pages", lambda text: [1])
    monkeypatch.setattr(main, "text_of", lambda p: "")
    monkeypatch.setattr(vision, "text_of", lambda p: pages_of(""))
    monkeypatch.setattr(vision, "tesseract_page", lambda p, n: "PLANTA")
    sent = []
    monkeypatch.setattr(vision, "transcribe", lambda p, key, charge, known: sent.append(p.name) or (p, 0, 1, 0))
    main.run_transcription(conn, {"vision": {"tope_mensual_usd": 35}}, [1])
    assert sent == ["bases integradas.pdf"]


def test_a_scan_under_the_entitys_invisible_ocr_is_transcribed_too(monkeypatch, tmp_path):
    ocr_layer = image_pdf(tmp_path / "PUQUIO.pdf", b"\x80", b"BT 3 Tr /F1 12 Tf 10 10 Td (CUANTIA S/ 1,250,000.00) Tj ET")
    plain = image_pdf(tmp_path / "TEXTO.pdf", b"\x80", b"BT /F1 12 Tf 10 10 Td (CUANTIA) Tj ET")
    assert vision.invisible_text_pages(ocr_layer) == [1] and vision.invisible_text_pages(plain) == []
    monkeypatch.setattr(vision, "text_of", lambda p: pages_of("1.4 LA CUANTIA ES S/ 1,25O,OOO.OO " * 30))
    sent = []
    vision.transcribe(ocr_layer, "clave", answering(sent), numbered_render)
    assert sent == [b"1"]


def test_pages_go_out_several_at_once_and_each_paid_one_is_charged_when_another_fails(monkeypatch, tmp_path):
    scanned(monkeypatch, "", "", "", "")
    monkeypatch.setattr(vision, "WORKERS", 4)

    def ask(key, image):
        if image == b"3":
            raise vision.VisionError("OpenRouter answered 502")
        return "texto", Decimal("0.001")

    charged = []
    with pytest.raises(vision.VisionError):
        vision.transcribe(tmp_path / "BASES.pdf", "clave", ask, numbered_render, charged.append)
    assert charged == [Decimal("0.001")] * 3 and not ia_path(tmp_path / "BASES.pdf").exists()
    out, cost, pages, reused = vision.transcribe(tmp_path / "BASES.pdf", "clave", answering([]), numbered_render)
    assert (pages, cost) == (4, Decimal("0.004")) and out.read_text(encoding="utf-8").count("pagina") == 4


def test_an_unexpected_failure_of_one_page_still_charges_the_others(monkeypatch, tmp_path):
    scanned(monkeypatch, "", "", "")
    monkeypatch.setattr(vision, "WORKERS", 3)

    def ask(key, image):
        if image == b"1":
            raise KeyError("bug")
        return "texto", Decimal("0.001")

    charged = []
    with pytest.raises(KeyError):
        vision.transcribe(tmp_path / "BASES.pdf", "clave", ask, numbered_render, charged.append)
    assert charged == [Decimal("0.001")] * 2
