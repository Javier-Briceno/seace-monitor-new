"""Manual extraction: a TOML template per obra, filled by a person, imported into extracciones.

The file is imported only once it says `listo = true`; editing it later replaces the stored
extraction and reports it again as a correction.
"""

import json
import re
import tomllib
from pathlib import Path

import psycopg

from .fields import (
    BLOCK_FIELDS, FACTOR_COLUMNS, FACTOR_TYPES, FIELDS, INCONGRUENCE_COLUMNS, KEYS, OPTIONAL_LIST, OPTIONAL_TEXT,
    ROW_FIELDS,
)
from .report import title
from .search import normalize

VERSION = "manual"


class TemplateError(Exception):
    pass


def toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)  # a JSON string is a valid TOML basic string


def template(obra: dict, bases: list[dict]) -> str:
    """obra: nid_proceso, nomenclatura, entidad, descripcion. bases: uuid, nombre_archivo, ruta_local of each candidate."""
    lines = [
        f"# {obra['nomenclatura']} | {obra['entidad']}",
        f"# {obra['descripcion'][:200]}",
        "#",
        "# Fill `valor` and `pagina` of each field; leave `valor` empty if the bases do not say it.",
        "# `pagina` is the page number in the PDF viewer, not the one printed on the page.",
        "# Set listo = true when done; the next run imports the file.",
        "",
        f"nid_proceso = {obra['nid_proceso']}",
        "listo = false",
        "",
        "# The bases document read. Candidates:",
        *[f"#   {b['uuid']}  {b['nombre_archivo']}  {b['ruta_local'] or '(not downloaded)'}" for b in bases],
        f"documento = {toml_string(bases[0]['uuid'] if len(bases) == 1 else '')}",
        "",
        "# Incongruencias de las bases: déjalo así si no hay ninguna; si hay, ver el bloque al final.",
        "incongruencias = []",
    ]
    for key, label, where in FIELDS:
        comment = f"# {label}" + (f" | {where}" if where else "")
        if key in ROW_FIELDS:
            lines += ["", comment, f"[[{key}]]"] + [empty_column(column, kind) for column, kind in ROW_FIELDS[key]]
            continue
        if key in BLOCK_FIELDS:
            lines += ["", f"[{key}]", comment] + [empty_column(column, kind) for column, kind in BLOCK_FIELDS[key]]
            continue
        if key == "factores":
            lines += ["", comment, "# Cada tipo agrega sus columnas; escala = lista de pasos, el más alto que se cumple da los puntos:"]
            lines += [f"#   {tipo}: {', '.join(c for c, _ in extra)}; escala: [{{{', '.join(c for c, _ in step)}}}, ...]"
                      for tipo, (extra, step) in FACTOR_TYPES.items()]
            lines += ["[[factores]]"] + [empty_column(c, k) for c, k in FACTOR_COLUMNS]
            lines += [f'tipo = ""  # {" | ".join(FACTOR_TYPES)}', "escala = []"]
            continue
        if key == "incongruencias":
            # TOML puts a plain key before the first table, so the empty list sits at the top of the
            # file; here only a commented block to copy.
            lines += ["", comment,
                      "# Los campos de arriba llevan una sola lectura (lectura_usada). Si la otra lectura es otro valor de una",
                      "# columna, campo/fila/columna/valor dicen cuál: fila = letra o parte del factor, cargo, o \"\" en un bloque.",
                      "# Si no se puede recalcular nada, deja campo, fila, columna y valor en \"\".",
                      "# Para anotar una: borra `incongruencias = []` arriba y copia este bloque sin los #:",
                      "# [[incongruencias]]"] + [f"# {empty_column(c, k)}" for c, k in INCONGRUENCE_COLUMNS] + ['# valor = ""']
            continue
        lines += [
            "",
            f"[{key}]",
            comment,
            'valor = """"""' if key in ("notas", "penalidades") else 'valor = ""',
            'pagina = ""',
        ]
    return "\n".join(lines) + "\n"


def empty_column(column: str, kind) -> str:
    """One column of an empty row; it fails validation until a person fills it."""
    if kind is int or kind is float:
        return f"{column} = 0"
    if kind is bool:
        return f"{column} = false"
    if kind is list or kind == OPTIONAL_LIST:
        return f"{column} = []"
    if kind == OPTIONAL_TEXT:
        return f'{column} = ""'
    if isinstance(kind, tuple):
        return f'{column} = ""  # {" | ".join(kind)}'
    return f'{column} = ""'


def check_row(where: str, columns: tuple, row: dict) -> dict:
    """One row or block, every column present and of its kind; anything else stops the import."""
    spec = dict(columns)
    unknown, missing = set(row) - set(spec), set(spec) - set(row)
    if unknown or missing:
        raise TemplateError(f"{where}: unknown columns {sorted(unknown)}, missing columns {sorted(missing)}")
    for column, kind in spec.items():
        v = row[column]
        if kind is str:
            ok, expected = isinstance(v, str) and v.strip() != "", "text"
        elif kind == OPTIONAL_TEXT:
            ok, expected = isinstance(v, str), 'text, or "" when it does not apply'
        elif isinstance(kind, ESCALA):
            ok, expected = isinstance(v, list) and v != [] and all(isinstance(s, dict) for s in v), "a list of steps"
            if ok:
                for i, s in enumerate(v, 1):
                    check_row(f"{where}: {column} {i}", kind.step, s)
        elif kind is int:
            ok, expected = type(v) is int and v > 0, "a whole number above 0"
        elif kind is float:
            ok, expected = type(v) in (int, float) and v > 0, "a number above 0, like 436482.01"
        elif kind is bool:
            ok, expected = type(v) is bool, "true or false"
        elif kind is list or kind == OPTIONAL_LIST:
            ok = (isinstance(v, list) and (v != [] or kind == OPTIONAL_LIST)
                  and all(isinstance(x, str) and x.strip() for x in v))
            expected = 'a list of texts, like ["a", "b"]' + (" (may be empty)" if kind == OPTIONAL_LIST else "")
        else:
            ok, expected = v in kind, "one of " + " | ".join(kind)
        if not ok:
            raise TemplateError(f"{where}: `{column}` must be {expected}, got {v!r}")
    return {c: (row[c].strip() if isinstance(row[c], str) else
                [x.strip() if isinstance(x, str) else x for x in row[c]] if isinstance(row[c], list) else row[c])
            for c in spec}


def check_amounts(name: str, campos: dict) -> list[tuple[str, str, str]]:
    """The required experience must follow from its rule, so a mistyped amount is caught on import.
    Some bases write two different amounts themselves; that is returned as a contradiction to record."""
    experiencia, cuantia = campos["experiencia_requerida"]["bloque"], campos["cuantia"]["bloque"]
    expected = experiencia["veces_cuantia"] * cuantia["monto"]
    if abs(experiencia["monto"] - expected) > 0.01:  # one céntimo of rounding
        return [("experiencia_requerida", "",
                 f"{name}: experiencia_requerida: `monto` {experiencia['monto']:,.2f} is not `veces_cuantia` "
                 f"{experiencia['veces_cuantia']:g} x cuantia {cuantia['monto']:,.2f} = {expected:,.2f}")]
    return []


def check_factores(name: str, value, personal: list[dict]) -> tuple[list[dict], list[tuple[str, str, str]]]:
    """The parts of the evaluation factors, each checked by its type, then checked against each other.

    Points that do not add up may be a typo in the template or a contradiction in the bases, which
    happens (factors announced at 10 with scales up to 5, summaries adding to 135, no factors at all).
    So they are returned as ("factores", factor letter or "", message) and accepted only when an incongruence
    names that factor; refusing would hide the obra.
    """
    if not isinstance(value, list) or not all(isinstance(row, dict) for row in value):
        raise TemplateError(f"{name}: `factores` needs one [[factores]] block per part of a factor")
    if not value:
        return [], [("factores", "", f"{name}: factores: the bases list no evaluation factors")]
    rows = []
    for number, row in enumerate(value, 1):
        where = f"{name}: factores {number}"
        tipo = row.get("tipo")
        if tipo not in FACTOR_TYPES:
            raise TemplateError(f"{where}: `tipo` must be one of {' | '.join(FACTOR_TYPES)}, got {tipo!r}")
        extra, step = FACTOR_TYPES[tipo]
        escala = row.get("escala")
        if not isinstance(escala, list) or not escala or not all(isinstance(s, dict) for s in escala):
            raise TemplateError(f'{where}: `escala` must be a list of steps, like [{{nivel = "acredita", puntos = 5}}]')
        checked = check_row(where, FACTOR_COLUMNS + extra, {k: v for k, v in row.items() if k not in ("tipo", "escala")})
        if not re.fullmatch(r"[A-Z]", checked["letra"]):
            raise TemplateError(f"{where}: `letra` must be one capital letter as in the bases, got {checked['letra']!r}")
        checked["tipo"] = tipo
        checked["escala"] = [check_row(f"{where}: escala {i}", step, s) for i, s in enumerate(escala, 1)]
        rows.append(checked)

    partes = [r["parte"] for r in rows]
    if len(set(partes)) != len(partes):
        raise TemplateError(f"{name}: factores: a `parte` appears twice: {sorted({p for p in partes if partes.count(p) > 1})}")
    by_letter: dict[str, list[dict]] = {}
    for row in rows:
        by_letter.setdefault(row["letra"], []).append(row)
    for letra, parts in by_letter.items():
        if any((p["nombre"], p["puntos_max"]) != (parts[0]["nombre"], parts[0]["puntos_max"]) for p in parts):
            raise TemplateError(f"{name}: factor {letra}: every part must repeat the same `nombre` and `puntos_max`")
    contradictions = []
    for letra, parts in by_letter.items():
        most = sum(max(s["puntos"] for s in p["escala"]) for p in parts)
        if most != parts[0]["puntos_max"]:
            contradictions.append(("factores", letra, f"{name}: factor {letra}: its parts give at most {most} points, "
                                          f"but `puntos_max` is {parts[0]['puntos_max']}"))
    total = sum(parts[0]["puntos_max"] for parts in by_letter.values())
    if total != 100:
        contradictions.append(("factores", "", f"{name}: factores: the maxima add up to {total}, not 100"))
    cargos = {p["cargo"] for p in personal}
    for row in rows:
        if row["tipo"] == "personal_adicional" and set(row["cargos"]) - cargos:
            raise TemplateError(f"{name}: factor {row['letra']}: {sorted(set(row['cargos']) - cargos)} "
                                f"is not a `cargo` of personal_clave")
    return rows, contradictions


def check_contradictions_recorded(contradictions: list[tuple[str, str, str]], incongruencias: list[dict]) -> None:
    """Every value that does not add up must be named by an incongruence on its field and row, or it is a typo."""
    named = {(r["campo"], r["fila"]) for r in incongruencias}
    for campo, fila, message in contradictions:
        if (campo, fila) not in named:
            raise TemplateError(f"{message}. If the bases say so, record it as an [[incongruencias]] block "
                                f'with campo = "{campo}", fila = "{fila}"; otherwise fix the template')


def check_incongruencias(name: str, value, campos: dict) -> list[dict]:
    """Each incongruence, and that its other reading names a real column and a value of that column's kind."""
    if not isinstance(value, list) or not all(isinstance(row, dict) for row in value):
        raise TemplateError(f"{name}: `incongruencias` needs one [[incongruencias]] block each, or incongruencias = []")
    rows = []
    for number, row in enumerate(value, 1):
        where = f"{name}: incongruencias {number}"
        if "valor" not in row:
            raise TemplateError(f"{where}: missing column `valor` (\"\" when nothing can be recomputed)")
        checked = check_row(where, INCONGRUENCE_COLUMNS, {k: v for k, v in row.items() if k != "valor"})
        checked["valor"] = row["valor"]
        target = (checked["campo"], checked["fila"], checked["columna"])
        if target == ("", "", ""):
            if row["valor"] != "":
                raise TemplateError(f"{where}: `valor` without `campo` and `columna`")
            rows.append(checked)
            continue
        if not checked["columna"]:
            # names the field or row it is about, with no other reading to compute
            if row["valor"] != "":
                raise TemplateError(f"{where}: `valor` without `columna`")
            named_target(where, campos, checked["campo"], checked["fila"])
            rows.append(checked)
            continue
        current = reading_target(where, campos, *target)
        check_row(f"{where}: valor", ((checked["columna"], current["kind"]),), {checked["columna"]: row["valor"]})
        if any(value == row["valor"] for value in current["values"]):
            raise TemplateError(f"{where}: `valor` is the reading already used; write the other one")
        rows.append(checked)
    return rows


def named_target(where: str, campos: dict, campo: str, fila: str) -> None:
    """An incongruence about a whole field ("" row) or one row of it: the field and row must exist."""
    if campo not in (*BLOCK_FIELDS, "personal_clave", "factores"):
        raise TemplateError(f"{where}: `campo` must be one of {', '.join([*BLOCK_FIELDS, 'personal_clave', 'factores'])}"
                            f" or \"\", got {campo!r}")
    if not fila:
        return
    if campo in BLOCK_FIELDS:
        raise TemplateError(f"{where}: `fila` must be \"\" for the block {campo}")
    keys = ({r["cargo"] for r in campos[campo]["filas"]} if campo == "personal_clave"
            else {k for r in campos[campo]["filas"] for k in (r["letra"], r["parte"])})
    if fila not in keys:
        raise TemplateError(f"{where}: no row {fila!r} in {campo}")


def reading_target(where: str, campos: dict, campo: str, fila: str, columna: str) -> dict:
    """The kind and current values of the column an alternative reading changes."""
    if campo in BLOCK_FIELDS:
        spec, rows = dict(BLOCK_FIELDS[campo]), [campos[campo]["bloque"]]
        if fila:
            raise TemplateError(f"{where}: `fila` must be \"\" for the block {campo}")
    elif campo == "personal_clave":
        spec, rows = dict(ROW_FIELDS[campo]), [r for r in campos[campo]["filas"] if r["cargo"] == fila]
    elif campo == "factores":
        rows = [r for r in campos[campo]["filas"] if fila in (r["letra"], r["parte"])]
        spec = {}
        for r in rows:
            extra, step = FACTOR_TYPES[r["tipo"]]
            spec.update(dict(FACTOR_COLUMNS + extra))
            spec["escala"] = ESCALA(step)
    else:
        raise TemplateError(f"{where}: `campo` must be one of {', '.join([*BLOCK_FIELDS, 'personal_clave', 'factores'])}"
                            f" or \"\", got {campo!r}")
    if not rows:
        raise TemplateError(f"{where}: no row {fila!r} in {campo}")
    if columna not in spec or columna in ("cita", "pagina"):
        raise TemplateError(f"{where}: {campo} has no column {columna!r} to read differently")
    return {"kind": spec[columna], "values": [r[columna] for r in rows if columna in r]}


class ESCALA:
    """The kind of a whole scale: a list of steps, each with its type's columns."""

    def __init__(self, step):
        self.step = step


def check_rows(name: str, key: str, value) -> list[dict]:
    if not isinstance(value, list) or not value or not all(isinstance(row, dict) for row in value):
        raise TemplateError(f"{name}: `{key}` needs one [[{key}]] block per row")
    return [check_row(f"{name}: {key} {number}", ROW_FIELDS[key], row) for number, row in enumerate(value, 1)]


def load(path: Path) -> dict | None:
    """The filled template as {nid_proceso, documento, campos}, or None while it is not marked listo."""
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as error:
        raise TemplateError(f"{path.name}: not valid TOML: {error}") from error
    if not data.get("listo"):
        return None
    if not data.get("documento"):
        raise TemplateError(f"{path.name}: `documento` is empty; copy the uuid of the bases you read")
    unknown = set(data) - set(KEYS) - {"nid_proceso", "listo", "documento"}
    missing = set(KEYS) - set(data)
    if unknown or missing:
        raise TemplateError(f"{path.name}: unknown fields {sorted(unknown)}, missing fields {sorted(missing)}")
    campos = {}
    for key in KEYS:
        field = data[key]
        if key in ROW_FIELDS:
            campos[key] = {"filas": check_rows(path.name, key, field)}
            continue
        if key in BLOCK_FIELDS:
            campos[key] = {"bloque": check_row(f"{path.name}: {key}", BLOCK_FIELDS[key], field)}
            continue
        if key in ("factores", "incongruencias"):
            continue  # checked last, against the other fields
        campos[key] = {"valor": str(field.get("valor", "")).strip(), "pagina": str(field.get("pagina", "")).strip()}
    factores, contradictions = check_factores(path.name, data["factores"], campos["personal_clave"]["filas"])
    campos["factores"] = {"filas": factores}
    contradictions += check_amounts(path.name, campos)
    campos["incongruencias"] = {"filas": check_incongruencias(path.name, data["incongruencias"], campos)}
    check_contradictions_recorded(contradictions, campos["incongruencias"]["filas"])
    return {"nid_proceso": data["nid_proceso"], "documento": data["documento"], "campos": campos}


def obra_name(conn: psycopg.Connection, path: Path) -> str:
    """The obra a template belongs to, as the report names it, so a rejected file does not hide its obra."""
    if path.stem.isdigit():
        row = conn.execute("SELECT nomenclatura, entidad FROM licitaciones WHERE nid_proceso = %s",
                           [int(path.stem)]).fetchone()
        if row:
            return title({"nomenclatura": row[0], "entidad": row[1]})
    return path.name


def import_ready(conn: psycopg.Connection, folder: Path) -> tuple[list[str], list[str]]:
    """Import every file marked listo; return (imported or updated files, errors).

    A changed file replaces the stored extraction and clears its report mark, so the
    correction appears in the next report. An unchanged file is left alone.
    """
    done, errors = [], []
    for path in sorted(folder.glob("*.toml")):
        try:
            filled = load(path)
        except TemplateError as error:
            errors.append(f"{obra_name(conn, path)}: plantilla no importada: {error}")
            continue
        if filled is None:
            continue
        doc = conn.execute(
            "SELECT id FROM documentos WHERE uuid = %s AND nid_proceso = %s", [filled["documento"], filled["nid_proceso"]]
        ).fetchone()
        if not doc:
            errors.append(f"{path.name}: documento {filled['documento']} is not a document of {filled['nid_proceso']}")
            continue
        changed = conn.execute(
            """INSERT INTO extracciones (documento_id, version_extractor, campos, estado)
               VALUES (%s, %s, %s, 'done')
               ON CONFLICT (documento_id, version_extractor) DO UPDATE
                   SET campos = EXCLUDED.campos, informado_en = NULL, creado_en = now()
                   WHERE extracciones.campos IS DISTINCT FROM EXCLUDED.campos
               RETURNING id""",
            [doc[0], VERSION, json.dumps(filled["campos"], ensure_ascii=False)],
        ).fetchone()
        if changed:
            done.append(path.name)
    return done, errors


def write_template(conn: psycopg.Connection, nid: int, folder: Path) -> Path:
    """Write the template of one obra; never overwrites a file a person may have started filling."""
    path = folder / f"{nid}.toml"
    if path.exists():
        raise TemplateError(f"{path} already exists; edit it or delete it first")
    row = conn.execute(
        "SELECT nid_proceso, nomenclatura, entidad, descripcion FROM licitaciones WHERE nid_proceso = %s", [nid]
    ).fetchone()
    if not row:
        raise TemplateError(f"{nid} is not a stored licitación")
    bases = [
        {"uuid": u, "nombre_archivo": n, "ruta_local": r}
        for u, n, r, tipo in conn.execute(
            "SELECT uuid, nombre_archivo, ruta_local, tipo FROM documentos WHERE nid_proceso = %s ORDER BY id", [nid]
        ).fetchall()
        if "bases" in normalize(tipo)
    ]
    if not bases:
        raise TemplateError(f"{nid} has no bases listed yet")
    folder.mkdir(parents=True, exist_ok=True)
    path.write_text(template(dict(zip(("nid_proceso", "nomenclatura", "entidad", "descripcion"), row)), bases),
                    encoding="utf-8")
    return path
