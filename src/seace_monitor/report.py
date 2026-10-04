"""Daily report: the licitaciones not reported yet, as a short summary and a full CSV."""

import csv
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import psycopg

from .fields import KEYS, NAMES
from .search import LIMA, normalize

TOP = 10  # obras listed in the summary; the CSV holds all of them

# The few extracted fields shown in the mail body; the extractions CSV holds all of them.
SUMMARY_FIELDS = ("cuantia", "plazo_ejecucion_dias", "experiencia_requerida", "minimo_tecnico")

# Dropped from the entity's name in a block title; the nomenclatura next to it already says it.
ENTITY_PREFIXES = ("MUNICIPALIDAD DISTRITAL DE ", "MUNICIPALIDAD PROVINCIAL DE ")

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


def title(extraction: dict) -> str:
    """The obra as readers name it: the entity's short name and the nomenclatura."""
    entidad = extraction["entidad"].upper()
    for prefix in ENTITY_PREFIXES:
        entidad = entidad.removeprefix(prefix)
    return f"{entidad} ({extraction['nomenclatura']})"


def consultas(campos: dict) -> int:
    """Questions to ask the entity: incongruences marked as consulta. Extractions stored before
    incongruences were rows marked them as notes lines starting with 'Consulta:'."""
    if "filas" in campos.get("incongruencias", {}):
        return sum(1 for row in campos["incongruencias"]["filas"] if row["consulta"])
    return sum(1 for line in campos["notas"]["valor"].splitlines() if line.strip().lower().startswith("consulta:"))


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
            lines += ["", title(e)]
            for key in SUMMARY_FIELDS:
                if key not in c:
                    continue
                valor = brief(key, c[key]["bloque"]) if "bloque" in c[key] else c[key]["valor"].strip()
                if key == "plazo_ejecucion_dias" and valor.isdigit():
                    valor += " días"
                if valor:
                    lines.append(f"  {NAMES[key]}: {valor}")
            if "filas" in c.get("factores", {}):
                judged = [f"{r['letra']}. {r['nombre']} ({r['que_se_juzga']})"
                          for r in c["factores"]["filas"] if r["tipo"] == "juicio_comite"]
                lines.append(f"  Factores subjetivos: {'; '.join(judged) or 'ninguno'}")
            lines.append(f"  Consultas: {consultas(c)}")
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
    # One row per field, so an obra reads top to bottom on a phone instead of scrolling sideways.
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f, delimiter=";")
        # Page before value: long values push anything after them out of sight.
        writer.writerow(["obra", "campo", "página", "valor"])
        for e in extracted:
            for key in KEYS:
                field = e["campos"].get(key)
                if field is None:  # stored before the field existed
                    continue
                if "filas" in field:
                    for row in field["filas"]:
                        writer.writerow([title(e), NAMES[key], row.get("pagina", row.get("paginas")), describe(key, row)])
                elif "bloque" in field:
                    writer.writerow([title(e), NAMES[key], field["bloque"]["pagina"], describe(key, field["bloque"])])
                else:
                    writer.writerow([title(e), NAMES[key], field["pagina"], field["valor"].strip()])


def experience_amount(block: dict) -> str:
    veces = f"{block['veces_cuantia']:g}"
    return f"S/ {block['monto']:,.2f} ({veces} {'vez' if veces == '1' else 'veces'} la cuantía)"


def describe_factor(row: dict) -> str:
    """One part of a factor in the bases' words; the internal type name never shows."""
    head = f"{row['letra']}. {row['nombre']}" + (f", {row['parte']}" if row["parte"] != row["letra"] else "")
    head += f" (máx. {row['puntos_max']})"
    escala = row["escala"]
    tipo = row["tipo"]
    if tipo == "personal_adicional":
        anios = f"{row['anios_extra']} año{'s' if row['anios_extra'] > 1 else ''}"
        body = (f"{' o '.join(row['cargos'])} con {anios} más de lo pedido; "
                + "; ".join(f"{s['pct_minimo']:g} % o más del personal evaluado → {s['puntos']}" for s in escala))
    elif tipo == "experiencia_adicional":
        desde = "el acta de recepción" if row["cuenta_desde"] == "acta de recepción" else "la conformidad o el pago"
        body = ("; ".join(f"{'más de' if s['estricto'] else 'desde'} S/ {s['monto_minimo']:,.2f} → {s['puntos']}"
                          for s in escala) + f" (últimos {row['ventana_anios']} años desde {desde})")
    else:
        what = {"certificacion_empresa": row.get("certificado", "") + (
                    f", alcance pedido: {row['alcance_pedido']}" if row.get("alcance_pedido", "ninguno") != "ninguno" else ""),
                "capacitacion_personal": f"{row.get('tema', '')} del {row.get('cargo', '')}",
                "herramienta": row.get("herramienta", ""),
                "juicio_comite": f"lo juzga el comité: {row.get('que_se_juzga', '')}"}[tipo]
        body = what + "; " + "; ".join(f"{s['nivel']} → {s['puntos']}" for s in escala)
    return f"{head}: {body}"


def brief(key: str, block: dict) -> str:
    """A block in the few words the mail body has room for."""
    if key == "experiencia_requerida":
        return experience_amount(block)
    return describe(key, block)


def describe(key: str, row: dict) -> str:
    """One row or block of a structured field as a sentence in the bases' words."""
    if key == "factores":
        return describe_factor(row)
    if key == "incongruencias":
        text = ("Consulta: " if row["consulta"] else "") + f"{row['descripcion']}. Lectura usada: {row['lectura_usada']}"
        if row["campo"]:
            valor = row["valor"]
            if isinstance(valor, list) and valor and isinstance(valor[0], dict):  # a scale
                valor = "; ".join(", ".join(f"{v:,.2f}" if isinstance(v, float) else str(v) for v in step.values())
                                  for step in valor)
            where = " ".join(p for p in (NAMES[row["campo"]], row["fila"]) if p)
            text += f". Otra lectura: {where}, {row['columna'].replace('_', ' ')} = {valor}"
        return text
    if key == "cuantia":
        return f"S/ {row['monto']:,.2f}"
    if key == "experiencia_requerida":
        tipo = f"{row['especialidad']}: {' o '.join(row['subespecialidades'])}"
        if row["tipologias"]:
            tipo += f" (tipología {' o '.join(row['tipologias'])})"
        return (f"{experience_amount(row)} en {tipo}; últimos {row['ventana_anios']} años desde "
                f"{'el acta de recepción' if row['cuenta_desde'] == 'acta de recepción' else 'la conformidad o el pago'}")
    if key == "personal_clave":
        grado = row["grado"] + (" colegiado" if row["colegiado"] else "")
        desde = " desde la colegiatura" if row["desde_colegiatura"] else ""
        ambito = "en la especialidad y subespecialidad" if row["ambito"] == "subespecialidad" else "en obras en general"
        como = " o ".join(row["roles"]) + (" en " + " o ".join(row["areas"]) if row["areas"] else "")
        return (f"{row['cargo']} ({row['cantidad']}): {' o '.join(row['profesiones'])}, {grado}; "
                f"{row['meses']} meses{desde} como {como}; {ambito}; últimos {row['ventana_anios']} años")
    return "; ".join(f"{k}: {v}" for k, v in row.items() if k != "pagina")


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
