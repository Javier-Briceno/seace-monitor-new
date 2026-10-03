"""Manual extraction templates; import runs against the test database."""

import tomllib

import pytest

from seace_monitor.fields import KEYS
from seace_monitor.manual import TemplateError, import_ready, load, template, write_template

OBRA = {"nid_proceso": 1, "nomenclatura": "LP-ABR-1", "entidad": "MD DE PRUEBA", "descripcion": 'OBRA "COBERTURA" DE PRUEBA'}
BASES = [{"uuid": "uuid-bases", "nombre_archivo": "BASES.pdf", "ruta_local": "data/documentos/1/BASES.pdf"}]


def filled(text: str, **values) -> str:
    text = text.replace("listo = false", "listo = true")
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
    assert all(data[k] == {"valor": "", "pagina": ""} for k in KEYS)


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
