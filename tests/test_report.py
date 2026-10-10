"""Runs against the test database (see conftest.py)."""

import csv
import json
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

from seace_monitor.fields import KEYS, NAMES
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
    rep = build(conn, ["LA LIBERTAD"], Path("data/documentos"), tmp_path, NOW)
    assert rep.nids == [1] and rep.extraction_ids == []
    assert (tmp_path / "2026-10-03.md").read_text(encoding="utf-8") == rep.text
    assert rep.files == [tmp_path / "2026-10-03.csv"]  # no extractions, no second CSV
    with open(rep.files[0], encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f, delimiter=";"))
    assert rows[0]["nomenclatura"] == "LP-ABR-1"
    assert rows[0]["valor_referencial"] == "1500000,00"
    assert rows[0]["fecha_limite_ofertas"] == "07/10/2026 09:00"
    assert rows[0]["carpeta"].endswith("1")


def add_extraction(conn, nid, **values):
    campos = {k: {"valor": values.get(k, ""), "pagina": "12" if k in values else ""} for k in KEYS}
    doc = conn.execute(
        """INSERT INTO documentos (nid_proceso, uuid, etapa, tipo, nombre_archivo)
           VALUES (%s, %s, 'Convocatoria', 'Bases Administrativas', 'BASES.pdf') RETURNING id""", [nid, f"u{nid}"]
    ).fetchone()[0]
    conn.execute("INSERT INTO extracciones (documento_id, version_extractor, campos, estado) VALUES (%s, 'manual', %s, 'done')",
                 [doc, json.dumps(campos)])


def test_extraction_of_an_already_reported_obra_gets_its_own_section(conn, tmp_path):
    add(conn, 1, ["LA LIBERTAD"], NOW + timedelta(days=4), informado=NOW - timedelta(days=2))
    add_extraction(conn, 1, plazo_ejecucion_dias="120", factores_subjetivos="ninguno")
    rep = build(conn, ["LA LIBERTAD"], Path("data/documentos"), tmp_path, NOW)
    assert rep.nids == [] and len(rep.extraction_ids) == 1
    assert "Extraídas a mano desde el último informe: 1" in rep.text
    assert "MUNICIPALIDAD DE PRUEBA (LP-ABR-1)\n  Plazo: 120 días\n  Consultas: 0\n" in rep.text
    with open(rep.files[1], encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f, delimiter=";"))
    assert len(rows) == len(KEYS)
    assert {"obra": "MUNICIPALIDAD DE PRUEBA (LP-ABR-1)", "campo": "Plazo", "valor": "120", "página": "12"} in rows


def test_key_personnel_rows_get_one_csv_row_each(conn, tmp_path):
    add(conn, 1, ["LA LIBERTAD"], NOW + timedelta(days=4), informado=NOW - timedelta(days=2))
    add_extraction(conn, 1)
    residente = {"cargo": "Residente de obra", "cantidad": 1, "profesiones": ["Ingeniero civil", "Arquitecto"],
                 "grado": "título profesional", "colegiado": False, "meses": 24, "desde_colegiatura": True,
                 "roles": ["Residente de obra", "Inspector de obra"], "areas": [], "ambito": "subespecialidad",
                 "ventana_anios": 25, "cita": "Residente de Obra", "pagina": "56"}
    calidad = dict(residente, cargo="Ingeniero de calidad", meses=12, roles=["Jefe", "Coordinador"], areas=["Calidad"],
                   ambito="obras en general", pagina="57")
    conn.execute("UPDATE extracciones SET campos = jsonb_set(campos, '{personal_clave}', %s)",
                 [json.dumps({"filas": [residente, calidad]})])
    rep = build(conn, ["LA LIBERTAD"], Path("data/documentos"), tmp_path, NOW)
    with open(rep.files[1], encoding="utf-8-sig", newline="") as f:
        rows = [r for r in csv.DictReader(f, delimiter=";") if r["campo"] == "Personal clave"]
    assert [r["página"] for r in rows] == ["56", "57"]
    assert rows[0]["valor"] == ("Residente de obra (1): Ingeniero civil o Arquitecto, título profesional; 24 meses desde "
                                "la colegiatura como Residente de obra o Inspector de obra; en la especialidad y "
                                "subespecialidad; últimos 25 años")
    assert "como Jefe o Coordinador en Calidad; en obras en general" in rows[1]["valor"]


def test_bidder_experience_in_the_mail_and_the_csv(conn, tmp_path):
    add(conn, 1, ["LA LIBERTAD"], NOW + timedelta(days=4), informado=NOW - timedelta(days=2))
    add_extraction(conn, 1)
    bloque = {"monto": 436482.01, "veces_cuantia": 1, "especialidad": "Edificaciones y afines",
              "subespecialidades": ["Establecimientos o espacios deportivos"],
              "tipologias": ["Instalaciones deportivas recreativas"], "ventana_anios": 20,
              "cuenta_desde": "acta de recepción", "cita": "UNA VEZ LA CUANTÍA", "pagina": "49"}
    conn.execute("UPDATE extracciones SET campos = jsonb_set(campos, '{experiencia_requerida}', %s)",
                 [json.dumps({"bloque": bloque})])
    rep = build(conn, ["LA LIBERTAD"], Path("data/documentos"), tmp_path, NOW)
    assert "  Experiencia pedida: S/ 436,482.01 (1 vez la cuantía)\n" in rep.text
    with open(rep.files[1], encoding="utf-8-sig", newline="") as f:
        row = next(r for r in csv.DictReader(f, delimiter=";") if r["campo"] == "Experiencia pedida")
    assert row["página"] == "49"
    assert row["valor"] == ("S/ 436,482.01 (1 vez la cuantía) en Edificaciones y afines: Establecimientos o espacios "
                            "deportivos (tipología Instalaciones deportivas recreativas); últimos 20 años desde el acta "
                            "de recepción")


def test_factors_in_the_csv_and_judged_ones_in_the_mail(conn, tmp_path):
    add(conn, 1, ["LA LIBERTAD"], NOW + timedelta(days=4), informado=NOW - timedelta(days=2))
    add_extraction(conn, 1)
    common = {"nombre": "Gestión de calidad", "letra": "E", "puntos_max": 10, "cita": "x", "pagina": "57"}
    filas = [
        dict(common, parte="e.1", tipo="herramienta", herramienta="Software de gestión de proyectos",
             escala=[{"nivel": "avanzada", "puntos": 5}]),
        dict(common, parte="e.2", tipo="juicio_comite", que_se_juzga="Ishikawa, Pareto y plan de calidad",
             escala=[{"nivel": "procedimientos documentados", "puntos": 5}]),
        {"letra": "G", "nombre": "Experiencia adicional del postor en la especialidad", "parte": "G", "puntos_max": 15,
         "cita": "x", "pagina": "59", "tipo": "experiencia_adicional", "ventana_anios": 25,
         "cuenta_desde": "conformidad o comprobante de pago",
         "escala": [{"monto_minimo": 1309446.03, "estricto": False, "puntos": 15},
                    {"monto_minimo": 436482.01, "estricto": True, "puntos": 5}]},
    ]
    conn.execute("UPDATE extracciones SET campos = jsonb_set(campos, '{factores}', %s)", [json.dumps({"filas": filas})])
    rep = build(conn, ["LA LIBERTAD"], Path("data/documentos"), tmp_path, NOW)
    assert "  Factores subjetivos: E. Gestión de calidad (Ishikawa, Pareto y plan de calidad)\n" in rep.text
    with open(rep.files[1], encoding="utf-8-sig", newline="") as f:
        rows = [r["valor"] for r in csv.DictReader(f, delimiter=";") if r["campo"] == "Factores de evaluación"]
    assert rows == [
        "E. Gestión de calidad, e.1 (máx. 10): Software de gestión de proyectos; avanzada → 5",
        "E. Gestión de calidad, e.2 (máx. 10): lo juzga el comité: Ishikawa, Pareto y plan de calidad; "
        "procedimientos documentados → 5",
        "G. Experiencia adicional del postor en la especialidad (máx. 15): desde S/ 1,309,446.03 → 15; "
        "más de S/ 436,482.01 → 5 (últimos 25 años desde la conformidad o el pago)",
    ]


def test_consultas_count_incongruence_rows_and_the_csv_shows_the_other_reading(conn, tmp_path):
    add(conn, 1, ["LA LIBERTAD"], NOW + timedelta(days=4), informado=NOW - timedelta(days=2))
    add_extraction(conn, 1)
    common = {"cita": "x", "paginas": "57-58, 60", "lectura_usada": "se suman (el cuadro resumen dice 10)"}
    filas = [
        dict(common, descripcion="E no dice si 5 + 5 se suman", consulta=True, campo="factores", fila="E",
             columna="puntos_max", valor=5),
        dict(common, descripcion="El terreno no dice si hay libre disponibilidad", consulta=True, campo="", fila="",
             columna="", valor=""),
        dict(common, descripcion="La numeración salta", consulta=False, campo="", fila="", columna="", valor=""),
    ]
    conn.execute("UPDATE extracciones SET campos = campos || %s", [json.dumps({"incongruencias": {"filas": filas}})])
    rep = build(conn, ["LA LIBERTAD"], Path("data/documentos"), tmp_path, NOW)
    assert "  Consultas: 2\n" in rep.text
    with open(rep.files[1], encoding="utf-8-sig", newline="") as f:
        rows = [r for r in csv.DictReader(f, delimiter=";") if r["campo"] == "Incongruencias"]
    assert rows[0]["página"] == "57-58, 60"
    assert rows[0]["valor"] == ("Consulta: E no dice si 5 + 5 se suman. Lectura usada: se suman (el cuadro resumen dice 10). "
                                "Otra lectura: Factores de evaluación E, puntos max = 5")
    assert rows[2]["valor"].startswith("La numeración salta.")


def test_every_field_has_a_short_name():
    assert set(NAMES) == set(KEYS)


def test_each_extraction_shows_its_own_consultas(conn, tmp_path):
    add(conn, 1, ["LA LIBERTAD"], NOW + timedelta(days=4), informado=NOW - timedelta(days=2))
    add(conn, 2, ["LA LIBERTAD"], NOW + timedelta(days=5), informado=NOW - timedelta(days=2))
    add_extraction(conn, 1, plazo_ejecucion_dias="60",
                   notas="\nConsulta: G dice 30 y el cuadro 15\nObra: techo\n  consulta: terreno sin acta")
    add_extraction(conn, 2, plazo_ejecucion_dias="120", notas="Sin ISO el máximo es 73")
    rep = build(conn, ["LA LIBERTAD"], Path("data/documentos"), tmp_path, NOW)
    assert "(LP-ABR-1)\n  Plazo: 60 días\n  Consultas: 2\n" in rep.text
    assert "(LP-ABR-2)\n  Plazo: 120 días\n  Consultas: 0\n" in rep.text


def test_block_title_drops_the_municipality_prefix(conn, tmp_path):
    add(conn, 1, ["LA LIBERTAD"], NOW + timedelta(days=4), informado=NOW - timedelta(days=2))
    conn.execute("UPDATE licitaciones SET entidad = 'MUNICIPALIDAD DISTRITAL DE PIAS'")
    add_extraction(conn, 1, cuantia="S/ 1,765,086.24")
    rep = build(conn, ["LA LIBERTAD"], Path("data/documentos"), tmp_path, NOW)
    assert "\nPIAS (LP-ABR-1)\n  Cuantía: S/ 1,765,086.24\n" in rep.text


def test_problems_are_listed(conn, tmp_path):
    rep = build(conn, ["LA LIBERTAD"], Path("data/documentos"), tmp_path, NOW, problems=["1.toml: not valid TOML"])
    assert "Problemas:\n- 1.toml: not valid TOML" in rep.text


def change(conn, nid, campo, antes, ahora):
    conn.execute("INSERT INTO historial (nid_proceso, campo, valor_anterior, valor_nuevo) VALUES (%s, %s, %s, %s)",
                 [nid, campo, antes, ahora])


def test_changes_of_watched_obras_go_into_the_mail_and_a_csv(conn, tmp_path):
    add(conn, 1, ["LA LIBERTAD"], NOW + timedelta(days=4), informado=NOW - timedelta(days=5))
    add(conn, 2, ["ANCASH"], NOW + timedelta(days=4), informado=NOW - timedelta(days=5))
    change(conn, 1, "fecha_limite_ofertas", "05/10/2026 23:59", "07/10/2026 09:00")
    change(conn, 1, "documento", None, "Bases Integradas: bi.pdf")
    change(conn, 1, "documento", None, "Pliego de absolución de consultas y observaciones: p.pdf")
    change(conn, 2, "estado_items", "Convocado", "Adjudicado")
    rep = build(conn, ["LA LIBERTAD"], Path("data/documentos"), tmp_path, NOW)
    assert ("MUNICIPALIDAD DE PRUEBA (LP-ABR-1)\n"
            "  documentos nuevos: Bases Integradas, Pliego de absolución de consultas y observaciones\n"
            "  fecha límite de ofertas: 05/10/2026 23:59 → 07/10/2026 09:00") in rep.text
    assert "Cambios en obras seguidas: 1" in rep.text
    assert "LP-ABR-2" not in rep.text
    assert rep.files[-1] == tmp_path / "2026-10-03-cambios.csv"
    with open(rep.files[-1], encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f, delimiter=";"))
    assert [(r["campo"], r["ahora"]) for r in rows] == [
        ("fecha límite de ofertas", "07/10/2026 09:00"), ("documento nuevo", "Bases Integradas: bi.pdf"),
        ("documento nuevo", "Pliego de absolución de consultas y observaciones: p.pdf"),
    ]
    assert len(rep.change_ids) == 3


def test_reported_changes_are_not_reported_again(conn, tmp_path):
    from seace_monitor.store import mark_changes_reported
    add(conn, 1, ["LA LIBERTAD"], NOW + timedelta(days=4), informado=NOW - timedelta(days=5))
    change(conn, 1, "estado_items", "Convocado", "Adjudicado")
    mark_changes_reported(conn, build(conn, ["LA LIBERTAD"], Path("data/documentos"), tmp_path, NOW).change_ids)
    assert "Cambios" not in build(conn, ["LA LIBERTAD"], Path("data/documentos"), tmp_path, NOW).text


def test_tracking_stops_are_said_in_words(conn, tmp_path):
    add(conn, 1, ["LA LIBERTAD"], NOW - timedelta(days=4), informado=NOW - timedelta(days=5))
    change(conn, 1, "estado_items", "Convocado", "Desierto")
    change(conn, 1, "seguimiento", "abierta", "cerrada")
    text = build(conn, ["LA LIBERTAD"], Path("data/documentos"), tmp_path, NOW).text
    assert "  estado: Convocado → Desierto\n  deja de seguirse: cerrada" in text


def test_restart_is_shown_with_the_new_obra_not_as_a_change(conn, tmp_path):
    add(conn, 1, ["LA LIBERTAD"], NOW - timedelta(days=40), informado=NOW - timedelta(days=50))
    add(conn, 2, ["LA LIBERTAD"], NOW + timedelta(days=4))
    conn.execute("UPDATE licitaciones SET reinicio_de = 1 WHERE nid_proceso = 2")
    change(conn, 2, "reinicio", None, "reiniciada; antes nid 1, estado Nulo")
    text = build(conn, ["LA LIBERTAD"], Path("data/documentos"), tmp_path, NOW).text
    assert "LP-ABR-2 | reinicio de una convocatoria anterior" in text
    assert "Cambios" not in text
