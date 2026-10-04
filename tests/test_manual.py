"""Manual extraction templates; import runs against the test database."""

import json
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


FACTORES = """[[factores]]
letra = "A"
nombre = "Experiencia específica adicional del personal clave"
parte = "A"
puntos_max = 70
cita = "Si el 50% o más ... supere el requisito"
pagina = "59"
tipo = "personal_adicional"
cargos = ["Residente de obra"]
anios_extra = 1
escala = [{pct_minimo = 50, puntos = 70}]

[[factores]]
letra = "D"
nombre = "Integridad en la contratación pública"
parte = "D"
puntos_max = 30
cita = "ISO 37001"
pagina = "61"
tipo = "certificacion_empresa"
certificado = "ISO 37001"
alcance_pedido = "ninguno"
escala = [{nivel = "acredita", puntos = 30}]
"""

CUANTIA = """[cuantia]
monto = 436482.01
cita = "CUANTÍA DE CONTRATACIÓN (TOTAL) S/ 436,482.01"
pagina = "21"
"""


def filled(text: str, rows: str = RESIDENTE, experiencia: str = EXPERIENCIA, cuantia: str = CUANTIA,
           factores: str = FACTORES, **values) -> str:
    text = (text.replace("listo = false", "listo = true").replace(empty_rows(text), rows)
            .replace(empty_block(text, "[experiencia_requerida]"), experiencia)
            .replace(empty_block(text, "[cuantia]"), cuantia)
            .replace(empty_block(text, "[[factores]]"), factores))
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
    plain = [k for k in KEYS if k not in ROW_FIELDS and k not in BLOCK_FIELDS and k not in ("factores", "incongruencias")]
    assert data["incongruencias"] == []
    assert all(data[k] == {"valor": "", "pagina": ""} for k in plain)
    assert data["factores"][0]["tipo"] == "" and data["factores"][0]["escala"] == []
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


def test_an_experience_amount_that_does_not_follow_its_rule_is_refused(tmp_path):
    typo = EXPERIENCIA.replace("monto = 436482.01", "monto = 463482.01")
    (tmp_path / "1.toml").write_text(filled(template(OBRA, BASES), experiencia=typo), encoding="utf-8")
    with pytest.raises(TemplateError, match=re.escape(
            "`monto` 463,482.01 is not `veces_cuantia` 1 x cuantia 436,482.01 = 436,482.01")):
        load(tmp_path / "1.toml")


def test_an_amount_rounded_to_the_centimo_is_accepted(tmp_path):
    half = EXPERIENCIA.replace("monto = 436482.01", "monto = 218241.01").replace("veces_cuantia = 1", "veces_cuantia = 0.5")
    (tmp_path / "1.toml").write_text(filled(template(OBRA, BASES), experiencia=half), encoding="utf-8")  # 218241.005 rounded up
    assert load(tmp_path / "1.toml")["campos"]["cuantia"]["bloque"]["monto"] == 436482.01


def test_factor_parts_are_loaded_with_their_type_and_scale(tmp_path):
    (tmp_path / "1.toml").write_text(filled(template(OBRA, BASES)), encoding="utf-8")
    filas = load(tmp_path / "1.toml")["campos"]["factores"]["filas"]
    assert [(f["letra"], f["tipo"]) for f in filas] == [("A", "personal_adicional"), ("D", "certificacion_empresa")]
    assert filas[0]["escala"] == [{"pct_minimo": 50, "puntos": 70}] and filas[1]["certificado"] == "ISO 37001"


@pytest.mark.parametrize("change, message", [
    (('letra = "D"', 'letra = "d"'), "`letra` must be one capital letter as in the bases, got 'd'"),
    (('tipo = "certificacion_empresa"', 'tipo = "certificado"'), "`tipo` must be one of personal_adicional"),
    (("puntos = 30}", "puntos = 25}"), "factor D: its parts give at most 25 points, but `puntos_max` is 30"),
    (("puntos_max = 30", "puntos_max = 25"), "factor D: its parts give at most 30 points, but `puntos_max` is 25"),
    (('cargos = ["Residente de obra"]', 'cargos = ["Residente"]'), "factor A: ['Residente'] is not a `cargo` of personal_clave"),
    (('parte = "D"', 'parte = "A"'), "a `parte` appears twice: ['A']"),
    (('nivel = "acredita"', 'nivel = ""'), "factores 2: escala 1: `nivel` must be text"),
    (("certificado = \"ISO 37001\"\n", ""), "factores 2: unknown columns [], missing columns ['certificado']"),
])
def test_a_wrong_factor_stops_the_whole_file(tmp_path, change, message):
    (tmp_path / "1.toml").write_text(filled(template(OBRA, BASES), factores=FACTORES.replace(*change)), encoding="utf-8")
    with pytest.raises(TemplateError, match=re.escape(message)):
        load(tmp_path / "1.toml")


def test_factor_maxima_must_add_up_to_100(tmp_path):
    lower = FACTORES.replace("puntos_max = 30", "puntos_max = 20").replace("puntos = 30}", "puntos = 20}")
    (tmp_path / "1.toml").write_text(filled(template(OBRA, BASES), factores=lower), encoding="utf-8")
    with pytest.raises(TemplateError, match="the maxima add up to 90, not 100. If the bases say so"):
        load(tmp_path / "1.toml")


def about(campo="factores", fila="", **columns) -> str:
    return incongruence(campo=campo, fila=fila, columna="", valor="", **columns)


def test_a_factor_that_does_not_add_up_in_the_bases_is_accepted_once_recorded(tmp_path):
    # Quiruvilca: D announced at 30 in the bases, its scale tops at 25
    contradictory = FACTORES.replace("puntos = 30}", "puntos = 25}")
    text = filled(template(OBRA, BASES), factores=contradictory)
    (tmp_path / "1.toml").write_text(text, encoding="utf-8")
    with pytest.raises(TemplateError, match='factor D: its parts give at most 25 .* campo = "factores", fila = "D"'):
        load(tmp_path / "1.toml")
    (tmp_path / "1.toml").write_text(with_incongruencias(text, about(fila="D")), encoding="utf-8")
    campos = load(tmp_path / "1.toml")["campos"]
    assert campos["factores"]["filas"][1]["puntos_max"] == 30
    assert campos["incongruencias"]["filas"][0]["fila"] == "D"


def test_a_note_on_another_factor_does_not_excuse_it(tmp_path):
    text = filled(template(OBRA, BASES), factores=FACTORES.replace("puntos = 30}", "puntos = 25}"))
    (tmp_path / "1.toml").write_text(with_incongruencias(text, about(fila="A")), encoding="utf-8")
    with pytest.raises(TemplateError, match="factor D: its parts give at most 25"):
        load(tmp_path / "1.toml")


def test_bases_without_factors_or_with_a_wrong_total_are_recorded_on_the_whole_field(tmp_path):
    text = filled(template(OBRA, BASES), factores="")
    text = text.replace("incongruencias = []\n", "incongruencias = []\nfactores = []\n", 1)
    (tmp_path / "1.toml").write_text(text, encoding="utf-8")
    with pytest.raises(TemplateError, match="the bases list no evaluation factors"):
        load(tmp_path / "1.toml")
    (tmp_path / "1.toml").write_text(with_incongruencias(text, about()), encoding="utf-8")
    assert load(tmp_path / "1.toml")["campos"]["factores"] == {"filas": []}


def test_a_tool_level_is_written_in_the_bases_words(tmp_path):
    tool = FACTORES.replace('tipo = "certificacion_empresa"\ncertificado = "ISO 37001"\nalcance_pedido = "ninguno"',
                            'tipo = "herramienta"\nherramienta = "monitoreo con cámaras"')
    tool = tool.replace('escala = [{nivel = "acredita", puntos = 30}]',
                        'escala = [{nivel = "herramientas digitales avanzadas", puntos = 30}, '
                        '{nivel = "evidencia limitada a herramientas básicas de monitoreo", puntos = 10}]')
    (tmp_path / "1.toml").write_text(filled(template(OBRA, BASES), factores=tool), encoding="utf-8")
    assert load(tmp_path / "1.toml")["campos"]["factores"]["filas"][1]["escala"][0]["nivel"] == "herramientas digitales avanzadas"


def test_a_certificate_level_is_written_in_the_bases_words(tmp_path):
    other = FACTORES.replace('escala = [{nivel = "acredita", puntos = 30}]',
                             'escala = [{nivel = "Reconocimiento del MTPE", puntos = 30}, '
                             '{nivel = "otro tipo de certificaciones", puntos = 4}]')
    (tmp_path / "1.toml").write_text(filled(template(OBRA, BASES), factores=other), encoding="utf-8")
    assert load(tmp_path / "1.toml")["campos"]["factores"]["filas"][1]["escala"][1]["nivel"] == "otro tipo de certificaciones"


def test_a_factor_split_in_parts_repeats_its_name_and_maximum(tmp_path):
    split = FACTORES.replace("puntos_max = 70", "puntos_max = 30").replace("puntos = 70}", "puntos = 30}") + """
[[factores]]
letra = "D"
nombre = "Integridad"
parte = "d.2"
puntos_max = 30
cita = "x"
pagina = "61"
tipo = "herramienta"
herramienta = "software"
escala = [{nivel = "avanzada", puntos = 10}]
"""
    (tmp_path / "1.toml").write_text(filled(template(OBRA, BASES), factores=split), encoding="utf-8")
    with pytest.raises(TemplateError, match="factor D: every part must repeat the same `nombre` and `puntos_max`"):
        load(tmp_path / "1.toml")


def incongruence(**columns) -> str:
    row = {"descripcion": "D dice 30 en el texto y 20 en el cuadro", "cita": "30 puntos", "paginas": "61, 64",
           "lectura_usada": "el cuadro resumen", "consulta": True, "campo": "factores", "fila": "D",
           "columna": "puntos_max", "valor": 20} | columns
    return "[[incongruencias]]\n" + "".join(f"{k} = {toml(v)}\n" for k, v in row.items())


def toml(v) -> str:
    if isinstance(v, bool):
        return str(v).lower()
    if isinstance(v, list):
        return "[" + ", ".join("{" + ", ".join(f"{k} = {toml(x)}" for k, x in s.items()) + "}" for s in v) + "]"
    if isinstance(v, str) and v.startswith("["):
        return v  # already TOML
    return json.dumps(v, ensure_ascii=False)


def with_incongruencias(text: str, *blocks: str) -> str:
    return text.replace("incongruencias = []\n", "") + "\n" + "\n".join(blocks)


def test_template_starts_without_incongruences(tmp_path):
    (tmp_path / "1.toml").write_text(filled(template(OBRA, BASES)), encoding="utf-8")
    assert load(tmp_path / "1.toml")["campos"]["incongruencias"] == {"filas": []}


def test_incongruences_are_loaded_with_their_other_reading(tmp_path):
    text = with_incongruencias(filled(template(OBRA, BASES)), incongruence(),
                               incongruence(campo="", fila="", columna="", valor="", consulta=False,
                                            descripcion="La lista de cargos termina cortada"),
                               incongruence(campo="experiencia_requerida", fila="", columna="ventana_anios", valor=25))
    (tmp_path / "1.toml").write_text(text, encoding="utf-8")
    filas = load(tmp_path / "1.toml")["campos"]["incongruencias"]["filas"]
    assert [(f["campo"], f["columna"], f["valor"]) for f in filas] == [
        ("factores", "puntos_max", 20), ("", "", ""), ("experiencia_requerida", "ventana_anios", 25)]


@pytest.mark.parametrize("columns, message", [
    ({"fila": "Z"}, "no row 'Z' in factores"),
    ({"columna": "puntaje"}, "factores has no column 'puntaje' to read differently"),
    ({"valor": "veinte"}, "valor: `puntos_max` must be a whole number above 0, got 'veinte'"),
    ({"valor": 30}, "`valor` is the reading already used; write the other one"),
    ({"campo": "", "fila": "", "columna": ""}, "`valor` without `campo` and `columna`"),
    ({"campo": "plazo"}, "`campo` must be one of cuantia, experiencia_requerida, personal_clave, factores"),
    ({"campo": "experiencia_requerida", "fila": "D", "columna": "ventana_anios", "valor": 25},
     "`fila` must be \"\" for the block experiencia_requerida"),
    ({"columna": "escala", "valor": [{"nivel": "acredita"}]}, "valor: escala 1: unknown columns [], missing columns ['puntos']"),
    ({"columna": ""}, "`valor` without `columna`"),
    ({"fila": "Z", "columna": "", "valor": ""}, "no row 'Z' in factores"),
])
def test_a_wrong_other_reading_stops_the_whole_file(tmp_path, columns, message):
    text = with_incongruencias(filled(template(OBRA, BASES)), incongruence(**columns))
    (tmp_path / "1.toml").write_text(text, encoding="utf-8")
    with pytest.raises(TemplateError, match=re.escape(message)):
        load(tmp_path / "1.toml")


def test_a_scale_can_be_the_other_reading(tmp_path):
    text = with_incongruencias(filled(template(OBRA, BASES)),
                               incongruence(columna="escala", valor='[{nivel = "acredita", puntos = 25}]'))
    (tmp_path / "1.toml").write_text(text, encoding="utf-8")
    assert load(tmp_path / "1.toml")["campos"]["incongruencias"]["filas"][0]["valor"] == [{"nivel": "acredita", "puntos": 25}]


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
