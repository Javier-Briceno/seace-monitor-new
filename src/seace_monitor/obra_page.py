"""One page for the phone: every obra still open for offers, what its bases say on cuantía and límites,
and what is wrong with them, in the bases' own words.

Each obra shows the reading of its newest bases (integradas, else administrativas).
"""

import html
import re
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import psycopg

from .report import in_watched, title
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
    return [dict(zip(keys, r)) for r in rows if in_watched(r[4], watched)]


def experience_lines(found: dict | None) -> list[str]:
    """The requisito de experiencia del postor; nothing when the bases were not read for it yet."""
    e = html.escape
    if found is None:
        return []
    page = f" (pág. {found['pagina']})" if found.get("pagina") else ""
    if found.get("revisar") and not found.get("monto"):
        return [f'<p class="revisar">Experiencia del postor: no se pudo leer{page}, revisar a mano.</p>']
    if found.get("revisar"):
        return [f'<p class="revisar">Experiencia del postor: se leyó {soles(found["monto"])}, que no cuadra con la '
                f'cuantía; puede ser una cifra mal leída{page}: revisar a mano.</p>']
    times_word = "vez" if found.get("veces") == "1" else "veces"
    asked = soles(found["monto"]) if found.get("monto") else f'{found["veces"]} {times_word} la cuantía'
    times = found.get("veces_cuantia")
    if times and Decimal(times) != 1:
        asked += f", {Decimal(times):.2f} veces la cuantía".replace(".", ",", 1)
    elif times:
        asked += ", 1 vez la cuantía"
    where = found.get("especialidad") or ""
    if found.get("subespecialidades"):
        where += (" — " if where else "") + ", ".join(found["subespecialidades"])
    parts = [f"<b>Experiencia del postor:</b> {e(asked)}"]
    if where:
        parts.append(f"en {e(where)}")
    if found.get("anios"):
        parts.append(f"en los últimos {found['anios']} años")
    if found.get("cuenta_desde"):
        parts.append(f"contados desde {e(found['cuenta_desde'])}")
    how = ", leído de las letras" if found.get("monto_de_letras") else ", leído con OCR" if found.get("ocr") else ""
    note = f' (pág. {found["pagina"]}{how})' if found.get("pagina") else ""
    lines = [f'<p>{", ".join(parts)}{note}.</p>']
    if found.get("monto_letras"):
        lines.append(f'<p class="revisar">El monto en letras dice {soles(found["monto_letras"])}: mirar la página.</p>')
    return lines


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


def factor_lines(found: dict | None) -> list[str]:
    """The factores de evaluación with their points; nothing when the bases were not read for them yet."""
    e = html.escape
    if found is None:
        return []
    page = f" (pág. {found['pagina']})" if found.get("pagina") else ""
    if found.get("revisar"):
        return [f'<p class="revisar">Factores de evaluación: no se pudo leer el cuadro resumen{page}, revisar a mano.</p>']
    listed = ", ".join(f"{f['factor']} {f['puntos']}" for f in found["factores"])
    lines = [f'<p><b>Factores de evaluación{e(page)}:</b> {e(listed)}. Total {found["total"]}.</p>']
    if found.get("avisos"):
        lines.append("<ul>" + "".join(f"<li>{e(factor_warning_text(w))}</li>" for w in found["avisos"]) + "</ul>")
    return lines


def personal_lines(found: dict | None) -> list[str]:
    """Each cargo of the personal clave with the time it asks for; nothing when the bases were not read for it yet."""
    e = html.escape
    if found is None:
        return []
    page = f" (pág. {found['pagina']})" if found.get("pagina") else ""
    if found.get("revisar"):
        return [f'<p class="revisar">Personal clave: no se pudo leer el cuadro de cargos{page}, revisar a mano.</p>']
    how = ", leído con OCR" if found.get("ocr") else ""
    listed = "; ".join(f"{p['cargo']} {p['tiempo']}" for p in found["personal"])
    lines = [f'<p><b>Personal clave (pág. {found["pagina"]}{how}):</b> {e(listed)}.</p>']
    warnings = [f"{w['cargo']}: el tiempo en cifras ({w['cifra']}) no es el que dicen las letras ({w['letras']})."
                for w in found.get("avisos") or []]
    if warnings and found.get("ocr"):
        lines.append(f'<p class="ocr">Leído con OCR; antes de consultarlo, comprobar en la página {found["pagina"]}:</p>')
    if warnings:
        lines.append("<ul>" + "".join(f"<li>{e(w)}</li>" for w in warnings) + "</ul>")
    return lines


def card(obra: dict, now: datetime) -> str:
    e = html.escape
    reading = obra["lectura"]
    lines = [f'<h2>{e(title(obra))}</h2>',
             f'<p class="desc">{e(obra["descripcion"][:220])}</p>',
             f'<p><b>Ofertas hasta:</b> {e(deadline(obra["fecha_limite_ofertas"], now))}</p>']
    if obra["bases"] is None:
        lines.append('<p class="revisar">Bases todavía no descargadas.</p>')
        return '<section>' + "".join(lines) + '</section>'
    if reading is None:
        lines.append('<p class="revisar">Bases descargadas, todavía sin leer.</p>')
        return '<section>' + "".join(lines) + '</section>'
    where = f'{e(obra["bases"])}, archivo «{e(UUID_PREFIX.sub("", reading.get("archivo") or ""))}»'
    if reading.get("pagina"):
        where += f', pág. {reading["pagina"]}'
    if reading.get("cuantia"):
        lines.append(f'<p><b>Cuantía:</b> {soles(reading["cuantia"])}</p>')
    elif obra["valor_referencial"] is not None:
        lines.append(f'<p><b>Cuantía en la ficha del SEACE:</b> {soles(obra["valor_referencial"])}</p>')
    lines.append(f'<p><b>Oferta económica:</b> {e(OFFER_TYPES.get(reading.get("tipo_oferta") or "", ""))}</p>')
    if reading.get("limite_inferior") or reading.get("limite_superior"):
        lines.append(f'<p><b>Límites en las bases:</b> {soles(reading.get("limite_inferior"))} a '
                     f'{soles(reading.get("limite_superior"))}</p>')
    if reading.get("revisar"):
        lines.append(f'<p class="revisar">{e(UNREAD.get(reading["revisar"], "Revisar a mano: " + reading["revisar"]))}</p>')
    warnings = reading.get("avisos") or []
    if warnings and reading.get("ocr"):
        # OCR misreads a digit now and then: a figure off by it is not yet the entity's mistake
        lines.append(f'<p class="ocr">Leído con OCR; antes de consultarlo, comprobar en la página '
                     f'{reading.get("pagina") or ""}:</p><ul>')
        lines += [f'<li>{e(warning_text(w))}</li>' for w in warnings]
        lines.append('</ul>')
    elif warnings:
        lines.append('<p class="aviso-titulo">Para revisar o consultar:</p><ul>')
        lines += [f'<li>{e(warning_text(w))}</li>' for w in warnings]
        lines.append('</ul>')
    elif reading.get("cuantia") and not reading.get("revisar") and reading.get("tipo_oferta") in ("fija", "limitada"):
        lines.append('<p class="ok">Cuantía y límites sin observaciones.</p>')
    if reading.get("ocr") and not warnings:
        lines.append('<p class="ocr">Leído de bases escaneadas con OCR: verificar las cifras en la página.</p>')
    lines += experience_lines(obra["experiencia"])
    lines += personal_lines(obra.get("personal"))
    lines += factor_lines(obra["factores"])
    lines.append(f'<p class="fuente">{where}</p>')
    return f'<section{" class=con-aviso" if flagged(obra) else ""}>' + "".join(lines) + '</section>'


def flagged(obra: dict) -> bool:
    """Warnings read from the text; those read through OCR still wait for a look at the page."""
    reading, personal = obra["lectura"] or {}, obra.get("personal") or {}
    return (bool(reading.get("avisos") and not reading.get("ocr")) or bool((obra["factores"] or {}).get("avisos"))
            or bool(personal.get("avisos") and not personal.get("ocr")))


def build(conn: psycopg.Connection, watched: list[str], now: datetime) -> str:
    items = obras(conn, watched, now)
    flagged_count = sum(1 for o in items if flagged(o))
    head = (f'{len(items)} obras abiertas para ofertas en {e_join(watched)}. '
            f'{flagged_count} con algo que revisar o consultar en la cuantía, los límites, el personal clave '
            f'o los factores de evaluación.')
    return PAGE.format(fecha=f"{now.astimezone(LIMA):%d/%m/%Y}", resumen=html.escape(head),
                       obras="\n".join(card(o, now) for o in items))


def e_join(names: list[str]) -> str:
    names = [n.title() for n in names]
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " y " + names[-1]


def write(conn: psycopg.Connection, watched: list[str], folder: Path, now: datetime) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"obras-abiertas-{now.astimezone(LIMA):%Y-%m-%d}.html"
    path.write_text(build(conn, watched, now), encoding="utf-8")
    return path


PAGE = """<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Obras abiertas {fecha}</title>
<style>
body {{ font-family: system-ui, sans-serif; font-size: 17px; line-height: 1.45; margin: 0; padding: 12px 16px;
       background: #f6f6f4; color: #1d1d1b; overflow-wrap: anywhere; }}
h1 {{ font-size: 21px; margin: 4px 0 6px; }}
h2 {{ font-size: 18px; margin: 0 0 4px; }}
section {{ background: #fff; border-radius: 10px; padding: 12px 14px; margin: 12px 0; border-left: 5px solid #c9c9c4; }}
section.con-aviso {{ border-left-color: #c2410c; }}
p {{ margin: 4px 0; }}
.desc, .fuente {{ color: #5f5f5a; font-size: 15px; }}
.revisar {{ color: #92400e; font-weight: 600; }}
.aviso-titulo {{ color: #c2410c; font-weight: 700; margin-top: 8px; }}
.ok {{ color: #166534; }}
.ocr {{ color: #92400e; font-size: 15px; }}
ul {{ margin: 4px 0 4px 18px; padding: 0; }}
li {{ margin: 4px 0; }}
</style></head><body>
<h1>Obras abiertas, {fecha}</h1>
<p>{resumen}</p>
{obras}
</body></html>
"""
