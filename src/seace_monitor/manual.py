"""Manual extraction: a TOML template per obra, filled by a person, imported into extracciones.

The file is imported only once it says `listo = true`; editing it later replaces the stored
extraction and reports it again as a correction.
"""

import json
import tomllib
from pathlib import Path

import psycopg

from .fields import FIELDS, KEYS
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
        lines += [
            "",
            f"[{key}]",
            f"# {label}" + (f" | {where}" if where else ""),
            'valor = """"""' if key in ("personal_clave", "factores", "notas", "penalidades") else 'valor = ""',
            'pagina = ""',
        ]
    return "\n".join(lines) + "\n"


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
        campos[key] = {"valor": str(field.get("valor", "")).strip(), "pagina": str(field.get("pagina", "")).strip()}
    return {"nid_proceso": data["nid_proceso"], "documento": data["documento"], "campos": campos}


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
            errors.append(str(error))
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
