"""One page for the phone: every obra still open for offers, grouped by when offers close, one short row each
that opens on tap to what its bases ask and what is wrong with them, in the bases' own words.

Each obra shows the reading of its newest bases (integradas, else administrativas).
"""

import html
import re
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import psycopg

from .report import in_watched
from .search import LIMA

DAYS = ("lun", "mar", "mié", "jue", "vie", "sáb", "dom")
# Downloads are stored as "<SEACE uuid>_<file name>".
UUID_PREFIX = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}_")

OFFER_TYPES = {
    "fija": "fija: los postores ofertan el 100 % de la cuantía",
    "limitada": "limitada: la oferta debe estar entre el 95 % y el 110 % de la cuantía",
    "sin rellenar": "el capítulo IV no lo dice (quedó el texto del modelo de bases)",
    "": "no se encontró en el capítulo IV",
}

# Why the bases could not be read, as the reader of the page needs it.
UNREAD = {
    "escaneado": "Bases escaneadas, todavía sin leer: revisar a mano.",
    "sin sección 1.4": "No se encontró el punto 1.4 en las bases: revisar a mano.",
    "1.4 sin monto legible": "El punto 1.4 no trae un monto legible: revisar a mano.",
    "diseño y construcción: montos por componente": "Diseño y construcción, con montos por componente: revisar a mano.",
    "plantilla sin rellenar": "El punto 1.4 quedó con el texto del modelo, sin la cuantía: revisar a mano.",
    "cuadro de límites ilegible": "El cuadro de límites no se pudo leer: revisar a mano.",
    "sin PDF ni DOCX": "Las bases no traen PDF ni Word: revisar a mano.",
}


def soles(value: str | Decimal | None) -> str:
    """As the bases write amounts: S/ 1,517,852.57."""
    return "—" if value is None else f"S/ {Decimal(value):,.2f}"


def deadline(limit: datetime, now: datetime) -> str:
    local = limit.astimezone(LIMA)
    days = (local.date() - now.astimezone(LIMA).date()).days
    when = "hoy" if days == 0 else "mañana" if days == 1 else f"en {days} días"
    return f"{DAYS[local.weekday()]} {local:%d/%m %H:%M} ({when})"


def warning_text(w: dict) -> str:
    """One warning as a sentence a reader of the bases can check."""
    kind = w["aviso"]
    if kind == "limite_inferior":
        stated, exact = Decimal(w["bases"]), Decimal(w["exacto"])
        effect = (f"una oferta de {soles(stated)} queda por debajo del 95 %" if stated < exact else
                  f"una oferta desde {soles(exact)} hasta {soles(stated - Decimal('0.01'))} cumple el 95 % "
                  f"y aun así quedaría descalificada")
        return (f"Límite inferior: las bases dicen {soles(stated)}; el 95 % de la cuantía, redondeado hacia arriba, "
                f"es {soles(exact)}. Con el de las bases, {effect}.")
    if kind == "limite_superior":
        stated, exact = Decimal(w["bases"]), Decimal(w["exacto"])
        effect = (f"una oferta de {soles(stated)} pasa del 110 %" if stated > exact else
                  f"una oferta desde {soles(stated + Decimal('0.01'))} hasta {soles(exact)} cumple el 110 % "
                  f"y aun así quedaría descalificada")
        return (f"Límite superior: las bases dicen {soles(stated)}; el 110 % de la cuantía, sin redondear, "
                f"es {soles(exact)}. Con el de las bases, {effect}.")
    if kind == "fija_con_limites":
        return "El capítulo IV dice que la oferta es FIJA, pero el punto 1.4 trae un cuadro de límites."
    if kind == "limitada_sin_limites":
        return "El capítulo IV dice que la oferta es LIMITADA, pero el punto 1.4 no trae el cuadro de límites."
    if kind == "tipo_oferta_sin_rellenar":
        return "El capítulo IV no dice si la oferta es fija o limitada: quedó el texto del modelo de bases."
    if kind == "cuantia_distinta_letras":
        return (f"La cuantía en cifras ({soles(w['cifra'])}) no es la que dicen las letras ({soles(w['letras'])}). "
                f"Puede ser un error de las bases o, si se leyó con OCR, un dígito mal leído: mirar la página.")
    if kind == "cuantia_distinta_seace":
        return (f"La cuantía de las bases ({soles(w['bases'])}) no es la de la ficha del SEACE ({soles(w['seace'])}). "
                f"Las bases dicen que, si hay contradicción, prima la de las bases.")
    return kind


def obras(conn: psycopg.Connection, watched: list[str], now: datetime) -> list[dict]:
    """Obras still open for offers in the watched departamentos, nearest deadline first."""
    rows = conn.execute(
        """WITH newest AS (
               SELECT DISTINCT ON (nid_proceso) nid_proceso, id, nombre_archivo, tipo
               FROM documentos WHERE estado = 'done' AND tipo ILIKE 'bases%%'
               ORDER BY nid_proceso, (tipo ILIKE '%%integrad%%') DESC, publicado_en DESC NULLS LAST, id DESC)
           SELECT l.nid_proceso, l.nomenclatura, l.entidad, l.descripcion, l.departamentos, l.fecha_limite_ofertas,
                  l.valor_referencial, n.tipo,
                  (SELECT e.campos FROM extracciones e WHERE e.documento_id = n.id
                     AND e.version_extractor LIKE 'cuantia-%%' ORDER BY e.creado_en DESC LIMIT 1),
                  (SELECT e.campos FROM extracciones e WHERE e.documento_id = n.id
                     AND e.version_extractor LIKE 'experiencia-%%' ORDER BY e.creado_en DESC LIMIT 1),
                  (SELECT e.campos FROM extracciones e WHERE e.documento_id = n.id
                     AND e.version_extractor LIKE 'factores-%%' ORDER BY e.creado_en DESC LIMIT 1),
                  (SELECT e.campos FROM extracciones e WHERE e.documento_id = n.id
                     AND e.version_extractor LIKE 'personal-%%' ORDER BY e.creado_en DESC LIMIT 1)
           FROM licitaciones l LEFT JOIN newest n USING (nid_proceso)
           WHERE l.seguimiento = 'abierta' AND l.fecha_limite_ofertas > %s
           ORDER BY l.fecha_limite_ofertas, l.nid_proceso""",
        [now],
    ).fetchall()
    keys = ("nid_proceso", "nomenclatura", "entidad", "descripcion", "departamentos", "fecha_limite_ofertas",
            "valor_referencial", "bases", "lectura", "experiencia", "factores", "personal")
    items = [dict(zip(keys, r)) for r in rows if in_watched(r[4], watched)]
    for obra in items:
        for key in ("lectura", "experiencia", "factores", "personal"):
            found = obra[key]
            # a Word file has no pages; the readers count every DOCX as page 1
            if found and str(found.get("archivo") or "").lower().endswith(".docx"):
                obra[key] = {**found, "pagina": None}
    return items


def factor_warning_text(w: dict) -> str:
    kind = w["aviso"]
    if kind == "suma_distinta_total":
        return f"Los puntajes del cuadro resumen suman {w['suma']}, pero el puntaje total dice {w['total']}."
    if kind == "total_distinto_100":
        return f"El puntaje total del cuadro resumen es {w['total']}, no 100."
    if kind == "factor_sin_rellenar":
        return (f"En el cuadro resumen quedó el texto del modelo («[Como máximo …]») en: {', '.join(w['factores'])}. "
                f"No dice si se evalúan.")
    if kind == "puntaje_distinto":
        return (f"{w['factor']}: el cuadro resumen da {w['cuadro']} puntos y la descripción del factor "
                f"{w['descripcion']}.")
    return kind


# Closing buckets, in the order the page shows them.
# Lowercase inside a name; "La", "Los" start place names (La Libertad, Los Olivos), so they stay capitalized.
SMALL_WORDS = {"de", "del", "y", "e", "en", "para", "con"}
BUCKETS = (("hoy", "Cierran hoy"), ("manana", "Cierran mañana"), ("semana", "Cierran esta semana"),
           ("despues", "Cierran más adelante"))
ENTITY_PREFIXES = ("MUNICIPALIDAD DISTRITAL DE ", "MUNICIPALIDAD PROVINCIAL DE ", "MUNICIPALIDAD DISTRITAL ",
                   "MUNICIPALIDAD PROVINCIAL ")
# "CONTRATACIÓN DE LA EJECUCIÓN DE LA OBRA: «MEJORAMIENTO …» CON CUI N° 2511071": only the middle says what it is.
WORK_PREFIX = re.compile(r"^\W*(?:CONTRATACI[OÓ]N\s+(?:DE|PARA)\s+(?:LA\s+)?)?(?:EJECUCI[OÓ]N\s+DE\s+(?:LA\s+)?)?"
                         r"(?:OBRA|IOARR)\s*[:\-–]?\W*", re.I)
CUI_TAIL = re.compile(r"[\s,;\-–(]*(?:CON\s+)?(?:C\.?\s?U\.?\s?I\.?|C[OÓ]DIGO\s+[UÚ]NICO)\b.*$", re.I | re.S)


def bucket(limit: datetime, now: datetime) -> str:
    days = (limit.astimezone(LIMA).date() - now.astimezone(LIMA).date()).days
    return "hoy" if days <= 0 else "manana" if days == 1 else "semana" if days < 7 else "despues"


def place(obra: dict) -> str:
    """Who calls the licitación, short: «Pataz», «Gobierno Regional La Libertad»."""
    entidad = obra["entidad"].upper()
    for prefix in ENTITY_PREFIXES:
        entidad = entidad.removeprefix(prefix)
    return proper(entidad)


def proper(name: str) -> str:
    """«GOBIERNO REGIONAL DE LA LIBERTAD» as «Gobierno Regional de La Libertad»: small words stay small."""
    words = name.lower().split()
    return " ".join(w if n and w in SMALL_WORDS else "-".join(p[:1].upper() + p[1:] for p in w.split("-"))
                    for n, w in enumerate(words))


def work(obra: dict) -> str:
    """What is built, without the procedure's wording around it."""
    text = CUI_TAIL.sub("", WORK_PREFIX.sub("", obra["descripcion"] or "").strip())
    return text.strip(" \"'“”«»,.;") or obra["descripcion"] or ""


def page_note(found: dict, label: str = "pág.") -> str:
    """Where a value is, and for a scan a reminder to look: OCR misreads a digit now and then."""
    if not found.get("pagina"):
        return ""
    look = ", comprobar la cifra en la página" if found.get("ocr") else ""
    return f'<span class="pag">{label} {found["pagina"]}{look}</span>'


def row(label: str, value: str, note: str = "") -> str:
    return f'<div class="fila"><dt>{label}</dt><dd>{value}{note}</dd></div>'


def cuantia_rows(obra: dict, manual: list[str], consult: list[str], look: list[str]) -> list[str]:
    e = html.escape
    reading = obra["lectura"]
    rows = []
    if reading.get("cuantia"):
        rows.append(row("Cuantía", soles(reading["cuantia"]), page_note(reading)))
    elif obra["valor_referencial"] is not None:
        rows.append(row("Cuantía", f'{soles(obra["valor_referencial"])} <span class="pag">ficha del SEACE</span>'))
    rows.append(row("Oferta económica", e(OFFER_TYPES.get(reading.get("tipo_oferta") or "", ""))))
    if reading.get("limite_inferior") or reading.get("limite_superior"):
        rows.append(row("Límites", f'{soles(reading.get("limite_inferior"))} a {soles(reading.get("limite_superior"))}',
                        page_note(reading)))
    if reading.get("revisar"):
        manual.append(UNREAD.get(reading["revisar"], "Revisar a mano: " + reading["revisar"]))
    warnings = [warning_text(w) for w in reading.get("avisos") or []]
    if warnings and reading.get("ocr"):
        look.append(f'Página {reading.get("pagina") or ""}: ' + " ".join(warnings))
    else:
        consult += warnings
    return rows


def experience_rows(found: dict | None, manual: list[str]) -> list[str]:
    """The requisito de experiencia del postor; nothing when the bases were not read for it yet."""
    e = html.escape
    if found is None:
        return []
    where_page = f' (pág. {found["pagina"]})' if found.get("pagina") else ""
    if found.get("revisar") and not found.get("monto"):
        manual.append(f"Experiencia del postor: no se pudo leer{where_page}.")
        return []
    if found.get("revisar"):
        manual.append(f'Experiencia del postor: se leyó {soles(found["monto"])}, que no cuadra con la cuantía; '
                      f'puede ser una cifra mal leída{where_page}.')
        return []
    times_word = "vez" if found.get("veces") == "1" else "veces"
    asked = soles(found["monto"]) if found.get("monto") else f'{found["veces"]} {times_word} la cuantía'
    times = found.get("veces_cuantia")
    if times and Decimal(times) != 1:
        asked += f" ({Decimal(times):.2f} veces la cuantía)".replace(".", ",", 1)
    elif times:
        asked += " (1 vez la cuantía)"
    parts = [e(asked)]
    where = found.get("especialidad") or ""
    if found.get("subespecialidades"):
        where += (" — " if where else "") + ", ".join(found["subespecialidades"])
    if where:
        parts.append(f"en {e(where)}")
    if found.get("anios"):
        parts.append(f"en los últimos {found['anios']} años")
    if found.get("cuenta_desde"):
        parts.append(f"contados desde {e(found['cuenta_desde'])}")
    if found.get("monto_letras"):
        manual.append(f'Experiencia del postor: el monto en letras dice {soles(found["monto_letras"])}{where_page}.')
    return [row("Experiencia del postor", ", ".join(parts), page_note(found))]


def personal_rows(found: dict | None, manual: list[str], consult: list[str], look: list[str]) -> list[str]:
    """Each cargo of the personal clave with the time it asks for; nothing when the bases were not read for it yet."""
    e = html.escape
    if found is None:
        return []
    where_page = f' (pág. {found["pagina"]})' if found.get("pagina") else ""
    if found.get("revisar") in ("cargos ilegibles", "personal clave sin tiempos legibles"):
        manual.append(f"Personal clave: no se pudo leer el cuadro de cargos{where_page}.")
        return []
    if found.get("revisar"):
        manual.append("Personal clave: no se encontró en el texto de las bases.")
        return []
    items = "".join(f'<li><span>{e(p["cargo"])}</span><span class="cifra">{e(p["tiempo"])}</span></li>'
                    for p in found["personal"])
    warnings = [f"{w['cargo']}: el tiempo en cifras ({w['cifra']}) no es el que dicen las letras ({w['letras']})."
                for w in found.get("avisos") or []]
    if warnings and found.get("ocr"):
        look.append(f'Página {found["pagina"]}: ' + " ".join(warnings))
    else:
        consult += warnings
    return [row("Personal clave", f'<ul class="lista">{items}</ul>', page_note(found))]


def factor_rows(found: dict | None, manual: list[str], consult: list[str]) -> list[str]:
    """The factores de evaluación with their points; nothing when the bases were not read for them yet."""
    e = html.escape
    if found is None:
        return []
    if found.get("revisar"):
        where_page = f' (pág. {found["pagina"]})' if found.get("pagina") else ""
        manual.append(f"Factores de evaluación: no se pudo leer el cuadro resumen{where_page}.")
        return []
    items = "".join(f'<li><span>{e(f["factor"])}</span><span class="cifra">{f["puntos"]} pts</span></li>'
                    for f in found["factores"])
    items += f'<li class="total"><span>Total</span><span class="cifra">{found["total"]} pts</span></li>'
    consult += [factor_warning_text(w) for w in found.get("avisos") or []]
    return [row("Factores de evaluación", f'<ul class="lista">{items}</ul>', page_note(found))]


def notes(title_text: str, css: str, lines: list[str]) -> str:
    e = html.escape
    if not lines:
        return ""
    return (f'<div class="nota {css}"><p class="nota-titulo">{title_text}</p><ul>'
            + "".join(f"<li>{e(line)}</li>" for line in lines) + "</ul></div>")


def card(obra: dict, now: datetime) -> str:
    e = html.escape
    rows, manual, consult, look = [row("Ofertas hasta", e(deadline(obra["fecha_limite_ofertas"], now)))], [], [], []
    reading = obra["lectura"]
    source = ""
    if obra["bases"] is None:
        manual.append("Bases todavía no descargadas.")
    elif reading is None:
        manual.append("Bases descargadas, todavía sin leer.")
    else:
        rows += cuantia_rows(obra, manual, consult, look)
        rows += experience_rows(obra["experiencia"], manual)
        rows += personal_rows(obra.get("personal"), manual, consult, look)
        rows += factor_rows(obra["factores"], manual, consult)
        source = f'{e(obra["bases"])}, archivo «{e(UUID_PREFIX.sub("", reading.get("archivo") or ""))}»'
        if reading.get("pagina"):
            source += f', pág. {reading["pagina"]}'
    clear = (reading and reading.get("cuantia") and not reading.get("revisar") and not reading.get("avisos")
             and reading.get("tipo_oferta") in ("fija", "limitada"))
    # Only what asks for action shows on the row; what could not be read waits in the detail.
    status = ('<span class="chip consultar">para consultar</span>' if consult else
              '<span class="chip revisar">bases sin leer</span>' if reading is None else "")
    cuantia = (reading or {}).get("cuantia") or obra["valor_referencial"]
    deps = "|".join(obra["departamentos"] or ["sin ubicar"])
    return (f'<details class="obra" data-dep="{e(deps)}"><summary>'
            f'<span class="cabeza"><span class="lugar">{e(place(obra))}</span>{status}</span>'
            f'<span class="que">{e(work(obra))}</span>'
            f'<span class="meta"><span class="cifra">{soles(cuantia) if cuantia else "cuantía no publicada"}</span>'
            f'<span>{e(deadline(obra["fecha_limite_ofertas"], now))}</span></span></summary>'
            f'<div class="detalle"><p class="nomen">{e(obra["nomenclatura"])} · {e(obra["entidad"])}</p>'
            f'<p class="desc">{e(obra["descripcion"] or "")}</p>'
            + notes("Para revisar o consultar", "consultar", consult)
            + notes("Mirar la página antes de consultarlo", "mirar", look)
            + notes("Falta revisar a mano", "revisar", manual)
            + (f'<p class="ok">Cuantía y límites sin observaciones.</p>' if clear and not consult else "")
            + f'<dl>{"".join(rows)}</dl>'
            + (f'<p class="fuente">{source}</p>' if source else "")
            + '</div></details>')


def flagged(obra: dict) -> bool:
    """Warnings read from the text; those read through OCR still wait for a look at the page."""
    reading, personal = obra["lectura"] or {}, obra.get("personal") or {}
    return (bool(reading.get("avisos") and not reading.get("ocr")) or bool((obra["factores"] or {}).get("avisos"))
            or bool(personal.get("avisos") and not personal.get("ocr")))


def build(conn: psycopg.Connection, watched: list[str], now: datetime) -> str:
    e = html.escape
    items = obras(conn, watched, now)
    flagged_count = sum(1 for o in items if flagged(o))
    word = "obra abierta" if len(items) == 1 else "obras abiertas"
    head = (f'{len(items)} {word} para ofertas en {e_join(watched)}. {flagged_count} con algo que revisar o '
            f'consultar en la cuantía, los límites, el personal clave o los factores de evaluación.')
    groups = {key: [o for o in items if bucket(o["fecha_limite_ofertas"], now) == key] for key, _ in BUCKETS}
    jumps = "".join(f'<a class="salto" href="#{key}">{name.removeprefix("Cierran ")} <b>{len(groups[key])}</b></a>'
                    for key, name in BUCKETS if groups[key])
    deps = sorted({d for o in items for d in (o["departamentos"] or ["sin ubicar"])})
    filters = ("" if len(deps) < 2 else '<div class="filtros" id="filtros"><button type="button" data-dep="" '
               'aria-pressed="true">Todos</button>' + "".join(
                   f'<button type="button" data-dep="{e(d)}" aria-pressed="false">{e(proper(d) if d != "sin ubicar" else "Sin ubicar")}</button>' for d in deps)
               + "</div>")
    sections = "".join(
        f'<section id="{key}"><h2>{name} <span class="cuenta">{len(groups[key])}</span></h2>'
        + "".join(card(o, now) for o in groups[key]) + "</section>"
        for key, name in BUCKETS if groups[key])
    return PAGE.format(fecha=f"{now.astimezone(LIMA):%d/%m/%Y}", resumen=e(head), saltos=jumps, filtros=filters,
                       secciones=sections or "<p>Ninguna obra abierta para ofertas.</p>")


def e_join(names: list[str]) -> str:
    names = [proper(n) for n in names]
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " y " + names[-1]


def write(conn: psycopg.Connection, watched: list[str], folder: Path, now: datetime) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"obras-abiertas-{now.astimezone(LIMA):%Y-%m-%d}.html"
    path.write_text(build(conn, watched, now), encoding="utf-8")
    return path


# Opened from a mail on a phone, maybe offline and without scripts: system fonts, everything readable without
# the script, which only adds the departamento filter. Rows fold open on tap (<details>).
PAGE = """<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Obras abiertas {fecha}</title>
<style>
:root {{
  --fondo: #f3f4f1; --hoja: #ffffff; --tinta: #1c211d; --gris: #5b6560; --linea: #dfe3de;
  --acento: #1f5f4a; --consultar: #b4410f; --consultar-fondo: #fdf0e8; --revisar: #8a5a00; --revisar-fondo: #fbf4e2;
  --ok: #1f6b3a;
  --texto: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  --cifras: ui-monospace, "SF Mono", "Roboto Mono", Consolas, monospace;
  color-scheme: light;
}}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{
  --fondo: #141816; --hoja: #1d2320; --tinta: #e7ebe7; --gris: #a1aba5; --linea: #313a35;
  --acento: #7cc4a6; --consultar: #ff9b6b; --consultar-fondo: #3a2418; --revisar: #e6b55c; --revisar-fondo: #33291a;
  --ok: #7fd19b; color-scheme: dark; }} }}
:root[data-theme="dark"] {{
  --fondo: #141816; --hoja: #1d2320; --tinta: #e7ebe7; --gris: #a1aba5; --linea: #313a35;
  --acento: #7cc4a6; --consultar: #ff9b6b; --consultar-fondo: #3a2418; --revisar: #e6b55c; --revisar-fondo: #33291a;
  --ok: #7fd19b; color-scheme: dark; }}
* {{ box-sizing: border-box; }}
body {{ margin: 0; padding-block: 12px 32px; padding-inline: 16px; background: var(--fondo); color: var(--tinta);
       font: 16px/1.45 var(--texto); overflow-wrap: anywhere; }}
main {{ max-width: 720px; margin: 0 auto; display: grid; grid-template-columns: minmax(0, 1fr); gap: 14px; }}
h1 {{ font-size: 22px; margin: 0; text-wrap: balance; }}
.resumen {{ margin: 0; color: var(--gris); }}
.saltos, .filtros {{ display: flex; flex-wrap: wrap; gap: 8px; }}
.salto, .filtros button {{ font: inherit; font-size: 14px; color: var(--tinta); background: var(--hoja);
  border: 1px solid var(--linea); border-radius: 999px; padding: 6px 12px; text-decoration: none; cursor: pointer; }}
.filtros button[aria-pressed="true"] {{ background: var(--acento); border-color: var(--acento); color: var(--hoja); }}
.salto b {{ color: var(--acento); }}
section {{ display: grid; grid-template-columns: minmax(0, 1fr); gap: 8px; }}
h2 {{ font-size: 13px; text-transform: uppercase; letter-spacing: .06em; color: var(--gris); margin: 10px 0 0; }}
.cuenta {{ color: var(--acento); }}
details.obra {{ background: var(--hoja); border: 1px solid var(--linea); border-radius: 10px; }}
details.obra[open] {{ border-color: var(--acento); }}
summary {{ list-style: none; cursor: pointer; padding: 12px 14px; display: grid; grid-template-columns: minmax(0, 1fr); gap: 4px; }}
summary::-webkit-details-marker {{ display: none; }}
summary:focus-visible {{ outline: 2px solid var(--acento); outline-offset: 2px; border-radius: 10px; }}
.cabeza {{ display: flex; flex-wrap: wrap; align-items: center; gap: 8px; justify-content: space-between; }}
.lugar {{ font-weight: 700; font-size: 17px; }}
.que {{ color: var(--gris); font-size: 14px; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;
        overflow: hidden; }}
.meta {{ display: flex; flex-wrap: wrap; gap: 4px 14px; font-size: 14px; }}
.cifra {{ font-family: var(--cifras); font-variant-numeric: tabular-nums; }}
.chip {{ font-size: 12px; font-weight: 700; border-radius: 999px; padding: 2px 9px; white-space: nowrap; }}
.chip.consultar {{ color: var(--consultar); background: var(--consultar-fondo); }}
.chip.revisar {{ color: var(--revisar); background: var(--revisar-fondo); }}
.detalle {{ padding: 0 14px 14px; display: grid; grid-template-columns: minmax(0, 1fr); gap: 10px; border-top: 1px solid var(--linea); padding-top: 12px; }}
.nomen, .desc, .fuente {{ margin: 0; font-size: 14px; color: var(--gris); }}
dl {{ margin: 0; display: grid; gap: 10px; }}
.fila {{ display: grid; gap: 2px; }}
dt {{ font-size: 13px; color: var(--gris); }}
dd {{ margin: 0; }}
.pag {{ display: block; font-size: 13px; color: var(--gris); }}
.lista {{ list-style: none; margin: 0; padding: 0; display: grid; gap: 4px; }}
.lista li {{ display: flex; justify-content: space-between; gap: 12px; border-bottom: 1px dotted var(--linea);
             padding-bottom: 3px; }}
.lista li.total {{ font-weight: 700; border-bottom: 0; }}
.lista .cifra {{ white-space: nowrap; }}
.nota {{ border-radius: 8px; padding: 10px 12px; }}
.nota ul {{ margin: 4px 0 0; padding-left: 18px; display: grid; gap: 4px; }}
.nota-titulo {{ margin: 0; font-weight: 700; }}
.nota.consultar {{ background: var(--consultar-fondo); }}
.nota.consultar .nota-titulo {{ color: var(--consultar); }}
.nota.mirar, .nota.revisar {{ background: var(--revisar-fondo); }}
.nota.mirar .nota-titulo, .nota.revisar .nota-titulo {{ color: var(--revisar); }}
.ok {{ margin: 0; color: var(--ok); }}
@media (prefers-reduced-motion: no-preference) {{ details.obra {{ transition: border-color .15s; }} }}
</style></head><body><main>
<h1>Obras abiertas, {fecha}</h1>
<p class="resumen">{resumen}</p>
<nav class="saltos">{saltos}</nav>
{filtros}
{secciones}
</main>
<script>
(function () {{
  var bar = document.getElementById("filtros");
  if (!bar) return;
  bar.addEventListener("click", function (event) {{
    var button = event.target.closest("button");
    if (!button) return;
    var dep = button.getAttribute("data-dep");
    bar.querySelectorAll("button").forEach(function (b) {{ b.setAttribute("aria-pressed", String(b === button)); }});
    document.querySelectorAll("details.obra").forEach(function (obra) {{
      obra.hidden = dep !== "" && obra.getAttribute("data-dep").split("|").indexOf(dep) < 0;
    }});
    document.querySelectorAll("main section").forEach(function (section) {{
      section.hidden = !section.querySelector("details.obra:not([hidden])");
    }});
  }});
}})();
</script>
</body></html>
"""
