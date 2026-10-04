"""Manual extraction templates; import runs against the test database."""

import re
import tomllib

import pytest

from seace_monitor.fields import BLOCK_FIELDS, KEYS, ROW_FIELDS
from seace_monitor.manual import TemplateError, import_ready, load, template, write_template

OBRA = {"nid_proceso": 1, "nomenclatura": "LP-ABR-1", "entidad": "MD DE PRUEBA", "descripcion": 'OBRA "COBERTURA" DE PRUEBA'}
BASES = [{"uuid": "uuid-bases", "nombre_archivo": "BASES.pdf", "ruta_local": "data/documentos/1/BASES.pdf"}]


RESIDENTE = """[[personal_clave]]
cargo = "Residente de obra"
cantidad = 1
profesiones = ["Ingeniero civil", "Arquitecto"]
grado = "título profesional"
colegiado = true
meses = 24
desde_colegiatura = true
roles = ["Residente de obra", "Supervisor de obra"]
areas = []
ambito = "subespecialidad"
ventana_anios = 25
cita = "Residente de Obra o Supervisor de Obra"
pagina = "56"
"""

EXPERIENCIA = """[experiencia_requerida]
monto = 436482.01
veces_cuantia = 1
especialidad = "Edificaciones y afines"
subespecialidades = ["Establecimientos o espacios deportivos"]
tipologias = []
ventana_anios = 20
cuenta_desde = "acta de recepción"
cita = "un monto facturado acumulado equivalente a UNA VEZ LA CUANTÍA"
pagina = "49"
"""


def empty_block(text: str, header: str) -> str:
    start = text.index("\n" + header) + 1
    return text[start:text.index("\n\n", start) + 1]


def empty_rows(text: str) -> str:
    return empty_block(text, "[[personal_clave]]")


def filled(text: str, rows: str = RESIDENTE, experiencia: str = EXPERIENCIA, **values) -> str:
    text = (text.replace("listo = false", "listo = true").replace(empty_rows(text), rows)
            .replace(empty_block(text, "[experiencia_requerida]"), experiencia))
    for key, value in values.items():
        start = text.index(f"[{key}]")
        text = text[:start] + text[start:].replace('valor = ""', f'valor = "{value}"', 1)
    return text


def add_obra(conn, uuid="uuid-bases"):
    conn.execute("""INSERT INTO licitaciones (nid_proceso, nomenclatura, entidad, objeto, descripcion)
                    VALUES (1, 'LP-ABR-1', 'MD', 'Obra', 'OBRA')""")
    conn.execute("""INSERT INTO documentos (nid_proceso, uuid, etapa, tipo, nombre_archivo)
                    VALUES (1, %s, 'Convocatoria', 'Bases Administrativas', 'BASES.pdf')""", [uuid])


def test_template_is_valid_toml_with_every_field():
    data = tomllib.loads(template(OBRA, BASES))
    assert data["listo"] is False
    assert data["documento"] == "uuid-bases"  # the only candidate is filled in
    assert all(data[k] == {"valor": "", "pagina": ""} for k in KEYS if k not in ROW_FIELDS and k not in BLOCK_FIELDS)
    assert data["experiencia_requerida"]["monto"] == 0  # an empty block, rejected until filled
    assert len(data["personal_clave"]) == 1 and data["personal_clave"][0]["meses"] == 0  # one empty row to copy


def test_several_bases_leave_the_choice_to_the_person():
    two = BASES + [{"uuid": "uuid-integradas", "nombre_archivo": "INTEGRADAS.pdf", "ruta_local": None}]
    text = template(OBRA, two)
    assert tomllib.loads(text)["documento"] == ""
    assert "uuid-integradas  INTEGRADAS.pdf  (not downloaded)" in text


def test_unfinished_file_is_not_loaded(tmp_path):
    (tmp_path / "1.toml").write_text(template(OBRA, BASES), encoding="utf-8")
    assert load(tmp_path / "1.toml") is None


def test_filled_file_is_loaded(tmp_path):
    (tmp_path / "1.toml").write_text(filled(template(OBRA, BASES), plazo_ejecucion_dias="120"), encoding="utf-8")
    data = load(tmp_path / "1.toml")
    assert data["campos"]["plazo_ejecucion_dias"] == {"valor": "120", "pagina": ""}
    assert set(data["campos"]) == set(KEYS)


def test_key_personnel_is_loaded_as_typed_rows(tmp_path):
    seguridad = RESIDENTE.replace("Residente de obra", "Especialista en seguridad", 1).replace("meses = 24", "meses = 12")
    (tmp_path / "1.toml").write_text(filled(template(OBRA, BASES), rows=RESIDENTE + "\n" + seguridad), encoding="utf-8")
    filas = load(tmp_path / "1.toml")["campos"]["personal_clave"]["filas"]
    assert [(f["cargo"], f["meses"]) for f in filas] == [("Residente de obra", 24), ("Especialista en seguridad", 12)]
    assert filas[0]["profesiones"] == ["Ingeniero civil", "Arquitecto"] and filas[0]["desde_colegiatura"] is True
    assert filas[0]["areas"] == []  # whole job titles need no area


def test_roles_can_combine_with_areas(tmp_path):
    combined = RESIDENTE.replace('roles = ["Residente de obra", "Supervisor de obra"]', 'roles = ["Jefe", "Coordinador"]')
    combined = combined.replace("areas = []", 'areas = ["Seguridad, salud en el trabajo y medio ambiente", "SSOMA"]')
    (tmp_path / "1.toml").write_text(filled(template(OBRA, BASES), rows=combined), encoding="utf-8")
    fila = load(tmp_path / "1.toml")["campos"]["personal_clave"]["filas"][0]
    assert fila["roles"] == ["Jefe", "Coordinador"] and fila["areas"][1] == "SSOMA"


@pytest.mark.parametrize("wrong, message", [
    ('meses = "24 meses"', "`meses` must be a whole number above 0, got '24 meses'"),
    ('ambito = "general"', "`ambito` must be one of subespecialidad | obras en general"),
    ("profesiones = []", "`profesiones` must be a list of texts"),
    ("roles = []", "`roles` must be a list of texts"),
    ('areas = [""]', "`areas` must be a list of texts, like [\"a\", \"b\"] (may be empty)"),
    ("desde_colegiatura = 1", "`desde_colegiatura` must be true or false"),
])
def test_a_wrong_column_stops_the_whole_file(tmp_path, wrong, message):
    column = wrong.split(" = ")[0]
    rows = "\n".join(wrong if line.startswith(column + " = ") else line for line in RESIDENTE.splitlines()) + "\n"
    (tmp_path / "1.toml").write_text(filled(template(OBRA, BASES), rows=rows), encoding="utf-8")
    with pytest.raises(TemplateError, match="personal_clave 1: " + re.escape(message)):
        load(tmp_path / "1.toml")


def test_bidder_experience_is_one_typed_block(tmp_path):
    (tmp_path / "1.toml").write_text(filled(template(OBRA, BASES)), encoding="utf-8")
    bloque = load(tmp_path / "1.toml")["campos"]["experiencia_requerida"]["bloque"]
    assert bloque["monto"] == 436482.01 and bloque["veces_cuantia"] == 1 and bloque["ventana_anios"] == 20
    assert bloque["cuenta_desde"] == "acta de recepción"


@pytest.mark.parametrize("wrong, message", [
    ('monto = "S/ 436,482.01"', "`monto` must be a number above 0"),
    ('cuenta_desde = "acta"', "`cuenta_desde` must be one of acta de recepción | conformidad o comprobante de pago"),
    ('cita = ""', "`cita` must be text"),
])
def test_a_wrong_experience_column_stops_the_whole_file(tmp_path, wrong, message):
    column = wrong.split(" = ")[0]
    block = "\n".join(wrong if line.startswith(column + " = ") else line for line in EXPERIENCIA.splitlines()) + "\n"
    (tmp_path / "1.toml").write_text(filled(template(OBRA, BASES), experiencia=block), encoding="utf-8")
    with pytest.raises(TemplateError, match="experiencia_requerida: " + re.escape(message)):
        load(tmp_path / "1.toml")


def test_the_empty_row_of_the_template_is_not_accepted(tmp_path):
    text = template(OBRA, BASES)
    (tmp_path / "1.toml").write_text(filled(text, rows=empty_rows(text)), encoding="utf-8")
    with pytest.raises(TemplateError, match="`cargo` must be text"):
        load(tmp_path / "1.toml")


def test_misspelled_field_is_an_error(tmp_path):
    text = filled(template(OBRA, BASES)).replace("[cuantia]", "[cuantias]")
    (tmp_path / "1.toml").write_text(text, encoding="utf-8")
    with pytest.raises(TemplateError, match="unknown fields"):
        load(tmp_path / "1.toml")


def test_import_once_then_only_corrections(conn, tmp_path):
    add_obra(conn)
    path = tmp_path / "1.toml"
    path.write_text(filled(template(OBRA, BASES), plazo_ejecucion_dias="120"), encoding="utf-8")
    assert import_ready(conn, tmp_path) == (["1.toml"], [])
    conn.execute("UPDATE extracciones SET informado_en = now()")
    assert import_ready(conn, tmp_path) == ([], [])  # unchanged: nothing to report again

    path.write_text(filled(template(OBRA, BASES), plazo_ejecucion_dias="150"), encoding="utf-8")
    assert import_ready(conn, tmp_path) == (["1.toml"], [])
    campos, informado = conn.execute("SELECT campos, informado_en FROM extracciones").fetchone()
    assert campos["plazo_ejecucion_dias"]["valor"] == "150"
    assert informado is None  # the correction goes into the next report
    assert conn.execute("SELECT count(*) FROM extracciones").fetchone()[0] == 1


def test_a_rejected_template_names_its_obra(conn, tmp_path):
    add_obra(conn)
    (tmp_path / "1.toml").write_text(filled(template(OBRA, BASES)).replace("[cuantia]", "[cuantias]"), encoding="utf-8")
    done, errors = import_ready(conn, tmp_path)
    assert done == [] and errors[0].startswith("MD (LP-ABR-1): plantilla no importada: 1.toml: unknown fields")


def test_document_of_another_obra_is_refused(conn, tmp_path):
    add_obra(conn, uuid="uuid-other")
    (tmp_path / "1.toml").write_text(filled(template(OBRA, BASES)), encoding="utf-8")
    done, errors = import_ready(conn, tmp_path)
    assert done == [] and "is not a document of 1" in errors[0]


def test_write_template_from_the_database_and_never_overwrite(conn, tmp_path):
    add_obra(conn)
    path = write_template(conn, 1, tmp_path)
    assert tomllib.loads(path.read_text(encoding="utf-8"))["documento"] == "uuid-bases"
    with pytest.raises(TemplateError, match="already exists"):
        write_template(conn, 1, tmp_path)
