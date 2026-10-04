"""Manual extraction: a TOML template per obra, filled by a person, imported into extracciones.

The file is imported only once it says `listo = true`; editing it later replaces the stored
extraction and reports it again as a correction.
"""

import json
import tomllib
from pathlib import Path

import psycopg

from .fields import FIELDS, KEYS, ROW_FIELDS
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
    ]
    for key, label, where in FIELDS:
        comment = f"# {label}" + (f" | {where}" if where else "")
        if key in ROW_FIELDS:
            lines += ["", comment, f"[[{key}]]"] + [empty_column(column, kind) for column, kind in ROW_FIELDS[key]]
            continue
        lines += [
            "",
            f"[{key}]",
            comment,
            'valor = """"""' if key in ("factores", "notas", "penalidades") else 'valor = ""',
            'pagina = ""',
        ]
    return "\n".join(lines) + "\n"


def empty_column(column: str, kind) -> str:
    """One column of an empty row; it fails validation until a person fills it."""
    if kind is int:
        return f"{column} = 0"
    if kind is bool:
        return f"{column} = false"
    if kind is list:
        return f"{column} = []"
    if isinstance(kind, tuple):
        return f'{column} = ""  # {" | ".join(kind)}'
    return f'{column} = ""'


def check_rows(name: str, key: str, value) -> list[dict]:
    """The rows of a row field, every column present and of its kind; anything else stops the import."""
    if not isinstance(value, list) or not value or not all(isinstance(row, dict) for row in value):
        raise TemplateError(f"{name}: `{key}` needs one [[{key}]] block per row")
    spec = dict(ROW_FIELDS[key])
    rows = []
    for number, row in enumerate(value, 1):
        where = f"{name}: {key} {number}"
        unknown, missing = set(row) - set(spec), set(spec) - set(row)
        if unknown or missing:
            raise TemplateError(f"{where}: unknown columns {sorted(unknown)}, missing columns {sorted(missing)}")
        for column, kind in spec.items():
            v = row[column]
            if kind is str:
                ok, expected = isinstance(v, str) and v.strip() != "", "text"
            elif kind is int:
                ok, expected = type(v) is int and v > 0, "a whole number above 0"
            elif kind is bool:
                ok, expected = type(v) is bool, "true or false"
            elif kind is list:
                ok = isinstance(v, list) and v != [] and all(isinstance(x, str) and x.strip() for x in v)
                expected = 'a list of texts, like ["a", "b"]'
            else:
                ok, expected = v in kind, "one of " + " | ".join(kind)
            if not ok:
                raise TemplateError(f"{where}: `{column}` must be {expected}, got {v!r}")
        rows.append({c: (row[c].strip() if isinstance(row[c], str) else
                         [x.strip() for x in row[c]] if isinstance(row[c], list) else row[c]) for c in spec})
    return rows


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
        campos[key] = {"valor": str(field.get("valor", "")).strip(), "pagina": str(field.get("pagina", "")).strip()}
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
