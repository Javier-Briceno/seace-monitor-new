"""Daily report: the licitaciones not reported yet, as a short summary and a full CSV."""

import csv
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import psycopg

from .fields import KEYS
from .search import LIMA, normalize

TOP = 10  # obras listed in the summary; the CSV holds all of them

# The few extracted fields shown in the mail body; the extractions CSV holds all of them.
SUMMARY_FIELDS = (("plazo_ejecucion_dias", "plazo"), ("experiencia_monto", "experiencia"),
                  ("factores_subjetivos", "subjetivos"), ("minimo_tecnico", "mínimo"))

CSV_COLUMNS = (
    "nid_proceso", "nomenclatura", "entidad", "departamentos", "ubicacion", "valor_referencial", "moneda",
    "fecha_publicacion", "fecha_limite_ofertas", "dias_restantes", "estado", "reiniciado_desde",
    "documentos_descargados", "carpeta", "descripcion",
)


def pending(conn: psycopg.Connection, watched: list[str], download_dir: Path, now: datetime) -> list[dict]:
    """Unreported licitaciones located in a watched departamento or not located at all.

    A licitación located only in other departamentos is left out: the portal lists
    it here because of the entity's seat, not the site.
    """
    watched_norm = {normalize(d) for d in watched}
    rows = conn.execute(
        """SELECT l.nid_proceso, l.nomenclatura, l.entidad, l.departamentos, l.ubicacion_fuente,
                  l.valor_referencial, l.moneda, l.fecha_publicacion, l.fecha_limite_ofertas,
                  l.reiniciado_desde, l.descripcion,
                  count(d.id) FILTER (WHERE d.estado = 'done') AS descargados
           FROM licitaciones l LEFT JOIN documentos d USING (nid_proceso)
           WHERE l.informado_en IS NULL
           GROUP BY l.nid_proceso"""
    ).fetchall()
    items = []
    for (nid, nomenclatura, entidad, departamentos, fuente, valor, moneda, publicada, limite,
         reiniciado, descripcion, descargados) in rows:
        located = bool(departamentos)
        if located and not watched_norm & {normalize(d) for d in departamentos}:
            continue
        dias = (limite.astimezone(LIMA).date() - now.astimezone(LIMA).date()).days if limite else None
        if limite is None:
            estado = "sin fecha límite"
        elif limite < now:
            estado = "plazo vencido"
        else:
            estado = "abierta"
        items.append({
            "nid_proceso": nid, "nomenclatura": nomenclatura, "entidad": entidad,
            "departamentos": "/".join(departamentos), "ubicacion": fuente if located else "sin ubicar",
            "valor_referencial": valor, "moneda": moneda, "fecha_publicacion": publicada,
            "fecha_limite_ofertas": limite, "dias_restantes": dias, "estado": estado,
            "reiniciado_desde": reiniciado, "documentos_descargados": descargados,
            "carpeta": str(download_dir / str(nid)), "descripcion": descripcion,
        })
    # Most urgent first; obras without a deadline at the end.
    items.sort(key=lambda i: (i["fecha_limite_ofertas"] is None, i["fecha_limite_ofertas"] or now))
    return items


def money(value, currency) -> str:
    if value is None:
        return "cuantía no publicada"
    prefix = "S/" if (currency or "").lower().startswith("sol") else (currency or "")
    return f"{prefix} {value:,.0f}".replace(",", ".")


def summary(items: list[dict], now: datetime, watched: list[str],
            extracted: list[dict] = (), problems: list[str] = ()) -> str:
    abiertas = [i for i in items if i["estado"] == "abierta"]
    otras = [i for i in items if i["estado"] != "abierta"]
    lines = [
        f"Informe SEACE, {now.astimezone(LIMA):%d/%m/%Y} ({', '.join(watched)})",
        "",
        f"Obras nuevas abiertas: {len(abiertas)}" + (f", de ellas {sum(1 for i in abiertas if i['ubicacion'] == 'sin ubicar')} sin ubicar" if abiertas else ""),
    ]
    if not items:
        lines.append("Ninguna obra nueva desde el último informe.")
    for i in abiertas[:TOP]:
        dias = i["dias_restantes"]
        plazo = "cierra hoy" if dias == 0 else f"cierra en {dias} días"
        lugar = "" if i["ubicacion"] != "sin ubicar" else " [sin ubicar]"
        lines.append(f"- {i['fecha_limite_ofertas'].astimezone(LIMA):%d/%m} ({plazo}) | "
                     f"{money(i['valor_referencial'], i['moneda'])} | {i['entidad']}{lugar} | {i['nomenclatura']}")
    if len(abiertas) > TOP:
        lines.append(f"... y {len(abiertas) - TOP} más en el CSV adjunto.")
    if otras:
        lines += ["", f"Sin plazo para ofertar (reiniciadas, vencidas o sin fecha): {len(otras)}, detalle en el CSV."]
    if extracted:
        lines += ["", f"Extraídas a mano desde el último informe: {len(extracted)} (todos los campos en el CSV de extracciones)"]
        for e in extracted:
            c = e["campos"]
            brief = " | ".join(f"{label}: {c[key]['valor']}" for key, label in SUMMARY_FIELDS if c[key]["valor"])
            lines.append(f"- {e['nomenclatura']} | {e['entidad']} | {brief}")
    if problems:
        lines += ["", "Problemas:"] + [f"- {p}" for p in problems]
    return "\n".join(lines) + "\n"


def write_csv(items: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # utf-8-sig and ";" so that Excel in a Spanish locale opens it with accents and columns right.
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow(CSV_COLUMNS)
        for i in items:
            row = dict(i)
            for key in ("fecha_publicacion", "fecha_limite_ofertas"):
                row[key] = row[key].astimezone(LIMA).strftime("%d/%m/%Y %H:%M") if row[key] else ""
            if row["valor_referencial"] is not None:
                row["valor_referencial"] = f"{row['valor_referencial']:.2f}".replace(".", ",")
            writer.writerow(["" if row[c] is None else row[c] for c in CSV_COLUMNS])


def extractions(conn: psycopg.Connection) -> list[dict]:
    """Extractions not reported yet, with their obra."""
    rows = conn.execute(
        """SELECT e.id, l.nid_proceso, l.nomenclatura, l.entidad, e.version_extractor, e.campos
           FROM extracciones e JOIN documentos d ON d.id = e.documento_id JOIN licitaciones l USING (nid_proceso)
           WHERE e.estado = 'done' AND e.informado_en IS NULL ORDER BY e.id"""
    ).fetchall()
    return [dict(zip(("id", "nid_proceso", "nomenclatura", "entidad", "version", "campos"), r)) for r in rows]


def write_extractions_csv(extracted: list[dict], path: Path) -> None:
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow(["nid_proceso", "nomenclatura", "entidad", "version"]
                        + [c for key in KEYS for c in (key, f"{key}_pagina")])
        for e in extracted:
            writer.writerow([e["nid_proceso"], e["nomenclatura"], e["entidad"], e["version"]]
                            + [v for key in KEYS for v in (e["campos"][key]["valor"], e["campos"][key]["pagina"])])


@dataclass
class Report:
    text: str
    files: list[Path]
    nids: list[int]
    extraction_ids: list[int] = field(default_factory=list)


def build(conn: psycopg.Connection, watched: list[str], download_dir: Path, report_dir: Path,
          now: datetime | None = None, problems: list[str] = ()) -> Report:
    """Write today's summary (.md) and CSV files; return what to send and what to mark once sent."""
    now = now or datetime.now(LIMA)
    items = pending(conn, watched, download_dir, now)
    extracted = extractions(conn)
    text = summary(items, now, watched, extracted, problems)
    stem = report_dir / f"{now.astimezone(LIMA):%Y-%m-%d}"
    stem.parent.mkdir(parents=True, exist_ok=True)
    stem.with_suffix(".md").write_text(text, encoding="utf-8")
    write_csv(items, stem.with_suffix(".csv"))
    files = [stem.with_suffix(".csv")]
    if extracted:
        files.append(stem.parent / f"{stem.name}-extracciones.csv")
        write_extractions_csv(extracted, files[-1])
    return Report(text, files, [i["nid_proceso"] for i in items], [e["id"] for e in extracted])
