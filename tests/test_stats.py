import json
from datetime import datetime
from decimal import Decimal

from seace_monitor import stats, vision
from seace_monitor.search import LIMA

from test_obra_page import bases, reading
from test_report import NOW, add


def test_each_reading_is_counted_by_how_it_was_read():
    agree = {"ocr": True, "ia": True, "revisar": None,
             "segunda_lectura": {"ia": {"cuantia": "1"}, "tesseract": {"cuantia": "1"}, "difieren": []}}
    assert stats.kind({"ocr": False, "revisar": None}) == "texto del PDF"
    assert stats.kind(agree) == "Haiku y Tesseract coinciden"
    assert stats.kind({**agree, "segunda_lectura": {"ia": {}, "tesseract": {}, "difieren": ["cuantia"]}}) \
        == "Haiku y Tesseract difieren"
    assert stats.kind({**agree, "segunda_lectura": {"ia": None, "tesseract": None, "difieren": []}}) == "solo Haiku"
    assert stats.kind({"ocr": True, "revisar": None}) == "solo Tesseract"
    assert stats.kind({"ocr": True, "ia": True, "revisar": "sin sección 1.4"}) == "sin leer"


def test_the_summary_counts_the_open_obras_newest_bases_and_the_months_spending(conn):
    add(conn, 1, ["LA LIBERTAD"], NOW)
    conn.execute("UPDATE licitaciones SET seguimiento = 'abierta'")
    bases(conn, 1, lectura=reading(ocr=True, ia=True, segunda_lectura={
        "ia": {"cuantia": "1"}, "tesseract": {"cuantia": "1"}, "difieren": []}), version="cuantia-7")
    vision.add_spending(conn, datetime(2026, 10, 5, tzinfo=LIMA), Decimal("1.25"), 1000)
    text = stats.text(conn)
    assert "Cuantía: Haiku y Tesseract coinciden 1" in text and "Experiencia del postor: sin leer 1" in text
    assert "2026-10: 1.25 USD, 1000 páginas" in text
