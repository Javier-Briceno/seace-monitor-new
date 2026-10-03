"""Runs against the test database (see conftest.py)."""

import csv
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

from seace_monitor.report import TOP, build, pending, summary
from seace_monitor.search import LIMA

NOW = datetime(2026, 10, 3, 9, 0, tzinfo=LIMA)


def add(conn, nid, departamentos, limite, informado=None, valor=Decimal("1500000.00")):
    conn.execute(
        """INSERT INTO licitaciones (nid_proceso, nomenclatura, entidad, objeto, descripcion, fecha_publicacion,
               valor_referencial, moneda, departamentos, ubicacion_fuente, fecha_limite_ofertas, informado_en)
           VALUES (%s, %s, 'MUNICIPALIDAD DE PRUEBA', 'Obra', 'OBRA DE PRUEBA', %s, %s, 'Soles', %s, %s, %s, %s)""",
        [nid, f"LP-ABR-{nid}", NOW - timedelta(days=1), valor, departamentos,
         "text" if departamentos else "unknown", limite, informado],
    )


def test_only_watched_or_unlocated_unreported_obras(conn):
    add(conn, 1, ["LA LIBERTAD"], NOW + timedelta(days=5))
    add(conn, 2, ["ANCASH"], NOW + timedelta(days=5))  # listed by the entity's seat, built elsewhere
    add(conn, 3, [], NOW + timedelta(days=5))
    add(conn, 4, ["LA LIBERTAD"], NOW + timedelta(days=5), informado=NOW - timedelta(days=1))
    add(conn, 5, ["ANCASH", "LA LIBERTAD"], NOW + timedelta(days=5))  # a road across two
    nids = {i["nid_proceso"] for i in pending(conn, ["La Libertad"], Path("data/documentos"), NOW)}
    assert nids == {1, 3, 5}


def test_most_urgent_first_and_state(conn):
    add(conn, 1, ["LA LIBERTAD"], NOW + timedelta(days=9))
    add(conn, 2, ["LA LIBERTAD"], NOW + timedelta(hours=10))
    add(conn, 3, ["LA LIBERTAD"], NOW - timedelta(days=30))  # restarted proceso, deadline long gone
    add(conn, 4, ["LA LIBERTAD"], None)
    items = pending(conn, ["LA LIBERTAD"], Path("data/documentos"), NOW)
    assert [(i["nid_proceso"], i["estado"], i["dias_restantes"]) for i in items] == [
        (3, "plazo vencido", -30), (2, "abierta", 0), (1, "abierta", 9), (4, "sin fecha límite", None),
    ]


def test_summary_lists_open_obras_and_counts_the_rest(conn):
    add(conn, 1, ["LA LIBERTAD"], NOW + timedelta(days=4))
    add(conn, 2, [], NOW + timedelta(days=6))
    add(conn, 3, ["LA LIBERTAD"], NOW - timedelta(days=30))
    text = summary(pending(conn, ["LA LIBERTAD"], Path("data/documentos"), NOW), NOW, ["LA LIBERTAD"])
    assert "Obras nuevas abiertas: 2, de ellas 1 sin ubicar" in text
    assert "07/10 (cierra en 4 días) | S/ 1.500.000 | MUNICIPALIDAD DE PRUEBA | LP-ABR-1" in text
    assert "[sin ubicar]" in text
    assert "Sin plazo para ofertar (reiniciadas, vencidas o sin fecha): 1" in text


def test_summary_is_cut_at_top_and_points_to_the_csv(conn):
    for nid in range(TOP + 3):
        add(conn, nid + 1, ["LA LIBERTAD"], NOW + timedelta(days=nid + 1))
    text = summary(pending(conn, ["LA LIBERTAD"], Path("data/documentos"), NOW), NOW, ["LA LIBERTAD"])
    assert text.count("\n- ") == TOP
    assert "... y 3 más en el CSV adjunto." in text


def test_empty_report_still_says_so(conn):
    text = summary([], NOW, ["LA LIBERTAD"])
    assert "Ninguna obra nueva desde el último informe." in text


def test_build_writes_summary_and_a_csv_excel_can_read(conn, tmp_path):
    add(conn, 1, ["LA LIBERTAD"], NOW + timedelta(days=4))
    text, csv_path, nids = build(conn, ["LA LIBERTAD"], Path("data/documentos"), tmp_path, NOW)
    assert nids == [1]
    assert (tmp_path / "2026-10-03.md").read_text(encoding="utf-8") == text
    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f, delimiter=";"))
    assert rows[0]["nomenclatura"] == "LP-ABR-1"
    assert rows[0]["valor_referencial"] == "1500000,00"
    assert rows[0]["fecha_limite_ofertas"] == "07/10/2026 09:00"
    assert rows[0]["carpeta"].endswith("1")
