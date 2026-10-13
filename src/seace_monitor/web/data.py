"""What the search tool shows: the obras of the watched departamentos with the reading of their newest bases,
filtered as asked, and one obra in full.

A filter on what the bases ask (experiencia, especialidad, cargo) never hides an obra whose bases were not read
for it: those come back apart, so nobody misses an obra only because a reader could not read it.
"""

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import quote

import psycopg

from .. import obra_page as op
from ..bases_text import bases_files
from ..report import CHANGE_NAMES, STOPPED

ORDERS = {"cierre": "Cierre más cercano", "cuantia": "Cuantía más alta", "publicacion": "Publicación más reciente"}
CLOSING = {"hoy": "Cierran hoy", "semana": "Cierran en 7 días", "mes": "Cierran en 30 días"}
CLOSING_DAYS = {"hoy": 0, "semana": 7, "mes": 30}
PUBLISHED = {"semana": "Publicadas en los últimos 7 días", "mes": "Publicadas en los últimos 30 días"}
PUBLISHED_DAYS = {"semana": 7, "mes": 30}
OFFER_FILTER = {"fija": "Fija", "limitada": "Limitada"}


def plain(text: str) -> str:
    """Lowercase without accents, for matching what someone types against what the bases say."""
    return "".join(c for c in unicodedata.normalize("NFD", text.lower()) if unicodedata.category(c) != "Mn")


PLACE_MARKERS = re.compile(r"\b(distrito|provincia|departamento|centro poblado|caser[ií]o|localidad|anexo|sector|"
                           r"comunidad campesina|urbanizaci[oó]n|asentamiento humano)( de| del)?\s+", re.I)
CONNECTORS = {"de", "del", "y", "e", "en", "para", "con", "a", "al"}
ARTICLES = {"la", "el", "los", "las"}
ROMAN = re.compile(r"^(?:i{1,3}|iv|vi{0,3}|ix|x{1,3})(?:-[a-z])?$")
# a place name ends where the next place word begins: «Caña Brava distrito de Ongón»
MARKER_WORDS = {"distrito", "provincia", "departamento", "centro", "caserio", "caserío", "localidad", "anexo",
                "sector", "comunidad", "urbanizacion", "urbanización", "asentamiento", "region", "región"}


def tidy(text: str) -> str:
    """The template junk SEACE descriptions carry: «EN EL(LA)», a «;» where a comma goes, a stray «?» at the end."""
    if "?" not in text:
        text = text.replace("¿", " ")  # a quote mark broken by SEACE's encoding, not a question
    text = re.sub(r"\b(EL|LA|LOS|LAS)\s*\((?:EL|LA|LOS|LAS)\)", r"\1", text, flags=re.I)
    text = re.sub(r"\s*;\s*", ", ", text)
    text = re.sub(r"\s+,", ",", re.sub(r"\s{2,}", " ", text))
    return text.strip(" ,.;¿?\"'“”«»")


def sentence(text: str) -> str:
    """SEACE writes descriptions in capitals; read as a sentence, with the place names after «distrito de»,
    «centro poblado», … still capitalized."""
    text = tidy(text or "")
    if not text or text != text.upper():
        return text
    low = text.lower()
    out, pos = [], 0
    for m in PLACE_MARKERS.finditer(low):
        out.append(low[pos:m.end()])
        pos = m.end()
        words = re.match(r"((?:[\wáéíóúñü.'-]+\s*)+)", low[pos:])
        if not words:
            continue
        name = []
        for n, word in enumerate(words.group(1).split()):
            if word in CONNECTORS or word in MARKER_WORDS or (word in ARTICLES and n > 0):
                break
            if ROMAN.match(word):
                if n > 0:  # «La Libertad II etapa»: the numeral belongs to the obra, not to the place
                    break
                name.append(word.upper())  # «sector VI-D»
                continue
            name.append(word[:1].upper() + word[1:])
        if name:
            out.append(" ".join(name))
            pos += len(" ".join(words.group(1).split()[:len(name)]))
    out.append(low[pos:])
    joined = "".join(out).rstrip(" ¿?")
    # abbreviations and numerals that stay in capitals: «I.E.», «II etapa», «SS.HH.»
    joined = re.sub(r"\b(?:[a-zñ]{1,2}\.){2,}|\b(?:i{2,3}|iv|vi{1,3}|ix|xi{0,3})\b",
                    lambda m: m.group(0).upper(), joined)
    return joined[:1].upper() + joined[1:]


def amount(value: str | None) -> Decimal | None:
    """A typed amount: «1.5 millones» is not supported, «1500000», «1,500,000» and «1 500 000» are."""
    if not value:
        return None
    digits = value.replace("S/", "").replace(",", "").replace(" ", "").strip()
    try:
        number = Decimal(digits)
    except InvalidOperation:
        return None
    return number if number.is_finite() and number >= 0 else None


@dataclass
class Filters:
    q: str = ""
    deps: list[str] = field(default_factory=list)
    cerradas: bool = False
    cierre: str = ""
    publicada: str = ""
    cuantia_min: Decimal | None = None
    cuantia_max: Decimal | None = None
    tipos: list[str] = field(default_factory=list)
    consultar: bool = False
    seguidas: bool = False
    exp_max: Decimal | None = None
    especialidad: str = ""
    cargo: str = ""
    orden: str = "cierre"

    @classmethod
    def parse(cls, params) -> "Filters":
        """From the query string; `params` may repeat a key (departamentos, offer types)."""
        get = lambda key: (params.get(key) or "").strip()[:120]
        many = (lambda key: [v.strip()[:60] for v in params.getlist(key) if v.strip()]) if hasattr(
            params, "getlist") else (lambda key: [get(key)] if get(key) else [])
        return cls(
            q=get("q"), deps=many("dep")[:30], cerradas=get("cerradas") == "1",
            cierre=get("cierre") if get("cierre") in CLOSING else "",
            publicada=get("publicada") if get("publicada") in PUBLISHED else "",
            cuantia_min=amount(get("cuantia_min")), cuantia_max=amount(get("cuantia_max")),
            tipos=[t for t in many("tipo") if t in OFFER_FILTER],
            consultar=get("consultar") == "1", seguidas=get("seguidas") == "1",
            exp_max=amount(get("exp_max")), especialidad=get("especialidad"), cargo=get("cargo"),
            orden=get("orden") if get("orden") in ORDERS else "cierre",
        )

    def asks_bases(self) -> bool:
        return self.exp_max is not None or bool(self.especialidad) or bool(self.cargo)

    def active(self) -> int:
        """How many filters beyond the defaults are set, for the «Filtros (n)» button."""
        return len(self.chips(lambda key, value=None: ""))

    def chips(self, without) -> list[tuple[str, str]]:
        """Each active filter as a label and the address of the same search without it.
        `without(key, value)` builds that address."""
        out = []
        if self.q:
            out.append((f"«{self.q}»", without("q")))
        out += [(op.proper(d), without("dep", d)) for d in self.deps]
        if self.cerradas:
            out.append(("Incluye cerradas", without("cerradas")))
        if self.cierre:
            out.append((CLOSING[self.cierre], without("cierre")))
        if self.publicada:
            out.append((PUBLISHED[self.publicada], without("publicada")))
        if self.cuantia_min is not None:
            out.append((f"Cuantía desde {op.soles(self.cuantia_min)}", without("cuantia_min")))
        if self.cuantia_max is not None:
            out.append((f"Cuantía hasta {op.soles(self.cuantia_max)}", without("cuantia_max")))
        out += [(f"Oferta {OFFER_FILTER[t].lower()}", without("tipo", t)) for t in self.tipos]
        if self.consultar:
            out.append(("Con algo para consultar", without("consultar")))
        if self.seguidas:
            out.append(("Las que sigo", without("seguidas")))
        if self.exp_max is not None:
            out.append((f"Experiencia hasta {op.soles(self.exp_max)}", without("exp_max")))
        if self.especialidad:
            out.append((f"Especialidad «{self.especialidad}»", without("especialidad")))
        if self.cargo:
            out.append((f"Cargo «{self.cargo}»", without("cargo")))
        return out


def cuantia(obra: dict) -> Decimal | None:
    value = (obra["lectura"] or {}).get("cuantia") or obra["valor_referencial"]
    return Decimal(value) if value is not None else None


def experience_amount(obra: dict) -> Decimal | None:
    """The amount of experiencia del postor the bases ask, None when it was not read."""
    found = obra["experiencia"] or {}
    if found.get("revisar") or not (found.get("monto") or found.get("veces")):
        return None
    if found.get("monto"):
        return Decimal(found["monto"])
    base = cuantia(obra)
    try:
        return Decimal(found["veces"]) * base if base is not None else None
    except InvalidOperation:
        return None


def specialty(obra: dict) -> str | None:
    found = obra["experiencia"] or {}
    if found.get("revisar") or not found.get("especialidad"):
        return None
    return " ".join([found["especialidad"], *(found.get("subespecialidades") or [])])


def cargos(obra: dict) -> list[str] | None:
    found = obra.get("personal") or {}
    if found.get("revisar") or not found.get("personal"):
        return None
    return [p["cargo"] for p in found["personal"] if p.get("cargo")]


def consults(obra: dict) -> bool:
    """Something in the bases to consult with the entidad, read from text (OCR readings wait for a look)."""
    return op.flagged(obra)


def days_until(when: datetime, now: datetime) -> int:
    return (when.astimezone(op.LIMA).date() - now.astimezone(op.LIMA).date()).days


def matches(obra: dict, f: Filters, followed: set[int], now: datetime) -> str:
    """'si', 'no', or 'sin_leer' when only an unread requisito keeps it from matching."""
    if f.deps and not set(f.deps) & set(obra["departamentos"] or []):
        return "no"
    if f.q:
        words = plain(f.q).split()
        hay = plain(" ".join([obra["entidad"], obra["nomenclatura"], obra["descripcion"] or ""]))
        if not all(w in hay for w in words):
            return "no"
    if f.cierre:
        if not obra["abierta"]:
            return "no"
        if days_until(obra["fecha_limite_ofertas"], now) > CLOSING_DAYS[f.cierre]:
            return "no"
    if f.publicada:
        published = obra["fecha_publicacion"]
        if published is None or -days_until(published, now) > PUBLISHED_DAYS[f.publicada]:
            return "no"
    value = cuantia(obra)
    if f.cuantia_min is not None and (value is None or value < f.cuantia_min):
        return "no"
    if f.cuantia_max is not None and (value is None or value > f.cuantia_max):
        return "no"
    if f.tipos and (obra["lectura"] or {}).get("tipo_oferta") not in f.tipos:
        return "no"
    if f.consultar and not consults(obra):
        return "no"
    if f.seguidas and obra["nid_proceso"] not in followed:
        return "no"
    unread = False
    if f.exp_max is not None:
        asked = experience_amount(obra)
        if asked is None:
            unread = True
        elif asked > f.exp_max:
            return "no"
    if f.especialidad:
        text = specialty(obra)
        if text is None:
            unread = True
        elif plain(f.especialidad) not in plain(text):
            return "no"
    if f.cargo:
        names = cargos(obra)
        if names is None:
            unread = True
        elif not any(plain(f.cargo) in plain(n) for n in names):
            return "no"
    return "sin_leer" if unread else "si"


@dataclass
class Listing:
    found: list[dict] = field(default_factory=list)
    unread: list[dict] = field(default_factory=list)
    departamentos: list[str] = field(default_factory=list)


WEEKDAYS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
MONTHS = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
          "noviembre", "diciembre")


def long_date(when: datetime | None, time: bool = True) -> str:
    """«martes 13 de octubre, 23:59», in Lima's time."""
    if when is None:
        return "—"
    local = when.astimezone(op.LIMA)
    text = f"{WEEKDAYS[local.weekday()]} {local.day} de {MONTHS[local.month - 1]}"
    return f"{text}, {local:%H:%M}" if time else text


def short_date(when: datetime | None) -> str:
    """«13 oct 2026», for dense rows."""
    if when is None:
        return "—"
    local = when.astimezone(op.LIMA)
    return f"{local.day} {MONTHS[local.month - 1][:3]} {local.year}"


def consult_count(obra: dict) -> int:
    reading, personal_found = obra["lectura"] or {}, obra.get("personal") or {}
    n = len(reading.get("avisos") or []) if not reading.get("ocr") else 0
    n += len((obra["factores"] or {}).get("avisos") or [])
    n += len(personal_found.get("avisos") or []) if not personal_found.get("ocr") else 0
    return n


def summary(obra: dict, followed: set[int], now: datetime) -> dict:
    """What one row of the list shows."""
    value = cuantia(obra)
    limit = obra["fecha_limite_ofertas"]
    reading = obra["lectura"] or {}
    asked = experience_amount(obra)
    return {
        "nid": obra["nid_proceso"],
        "lugar": op.place(obra),
        "que": sentence(op.work(obra)),
        "nomenclatura": obra["nomenclatura"],
        "entidad": op.proper(obra["entidad"]),
        "cuantia": op.soles(value) if value is not None else "No publicada",
        "cierre": long_date(limit) if limit else "Sin fecha de ofertas",
        "cierre_corto": short_date(limit),
        "publicada": short_date(obra["fecha_publicacion"]),
        "grupo": op.bucket(limit, now) if limit and obra["abierta"] else "cerrada",
        "abierta": obra["abierta"],
        "dias": days_until(limit, now) if limit and obra["abierta"] else None,
        "oferta": {"fija": "Fija", "limitada": "Limitada"}.get(reading.get("tipo_oferta") or "", "—"),
        "experiencia": op.soles(asked) if asked is not None else "—",
        "consultar": consults(obra),
        "consultas": consult_count(obra),
        "sin_leer": obra["lectura"] is None,
        "seguida": obra["nid_proceso"] in followed,
        "departamentos": [op.proper(d) for d in obra["departamentos"] or []],
    }


def listing(obras: list[dict], f: Filters, followed: set[int], now: datetime) -> Listing:
    result = Listing(departamentos=sorted({d for o in obras for d in o["departamentos"] or []}))
    for obra in obras:
        verdict = matches(obra, f, followed, now)
        if verdict != "no":
            (result.found if verdict == "si" else result.unread).append(obra)
    if f.orden == "cuantia":
        key = lambda o: -(cuantia(o) or Decimal(-1))
        result.found.sort(key=key)
        result.unread.sort(key=key)
    elif f.orden == "publicacion":
        key = lambda o: -(o["fecha_publicacion"].timestamp() if o["fecha_publicacion"] else 0)
        result.found.sort(key=key)
        result.unread.sort(key=key)
    result.found = [summary(o, followed, now) for o in result.found]
    result.unread = [summary(o, followed, now) for o in result.unread]
    return result


def followed_by(conn: psycopg.Connection, correo: str) -> set[int]:
    return {r[0] for r in conn.execute("SELECT nid_proceso FROM seguidas WHERE correo = %s", [correo]).fetchall()}


def page_link(obra: dict, found: dict) -> str | None:
    """Where a reading came from, as a link that opens the bases at that page."""
    if not obra["bases_id"] or not found.get("archivo"):
        return None
    link = f'/obras/{obra["nid_proceso"]}/bases/{obra["bases_id"]}/{quote(found["archivo"])}'
    return link + (f'#page={found["pagina"]}' if found.get("pagina") else "")


def note(text: str, obra: dict, found: dict | None) -> dict:
    found = found or {}
    return {"texto": text, "pagina": found.get("pagina"), "enlace": page_link(obra, found)}


def value(label: str, text: str, obra: dict, found: dict | None, items: list[tuple[str, str]] | None = None) -> dict:
    found = found or {}
    return {"etiqueta": label, "valor": text, "pagina": found.get("pagina"), "ocr": bool(found.get("ocr")),
            "enlace": page_link(obra, found), "lista": items}


def detail(obra: dict) -> dict:
    """The reading of one obra: what to consult, what to look at first, what is left for a person, and each value
    with its page. The same rules as the phone page: a warning read through OCR waits for a look at the page."""
    consult, look, manual, values = [], [], [], []
    reading = obra["lectura"]
    if obra["bases"] is None:
        manual.append(note("Bases todavía no descargadas.", obra, None))
    elif reading is None:
        manual.append(note("Bases descargadas, todavía sin leer.", obra, None))
    else:
        if reading.get("cuantia"):
            values.append(value("Cuantía", op.soles(reading["cuantia"]), obra, reading))
        elif obra["valor_referencial"] is not None:
            values.append(value("Cuantía", f'{op.soles(obra["valor_referencial"])} (ficha del SEACE)', obra, None))
        offer = op.OFFER_TYPES.get(reading.get("tipo_oferta") or "", "")
        values.append(value("Oferta económica", offer[:1].upper() + offer[1:], obra, None))
        if reading.get("limite_inferior") or reading.get("limite_superior"):
            values.append(value("Límites con IGV", f'{op.soles(reading.get("limite_inferior"))} a '
                                f'{op.soles(reading.get("limite_superior"))}', obra, reading))
        if reading.get("sin_igv_inferior") or reading.get("sin_igv_superior"):
            values.append(value("Límites sin IGV", f'{op.soles(reading.get("sin_igv_inferior"))} a '
                                f'{op.soles(reading.get("sin_igv_superior"))}', obra, reading))
        if reading.get("revisar"):
            manual.append(note(op.UNREAD.get(reading["revisar"], "Revisar a mano: " + reading["revisar"]), obra,
                               reading))
        for w in reading.get("avisos") or []:
            (look if reading.get("ocr") else consult).append(note(op.warning_text(w), obra, reading))
        experience(obra, values, manual)
        personal(obra, values, manual, consult, look)
        factors(obra, values, manual, consult)
    return {"consultar": consult, "mirar": look, "revisar": manual, "valores": values,
            "sin_observaciones": bool(reading and reading.get("cuantia") and not reading.get("revisar")
                                      and not reading.get("avisos") and not consult
                                      and reading.get("tipo_oferta") in ("fija", "limitada"))}


def experience(obra: dict, values: list, manual: list) -> None:
    found = obra["experiencia"]
    if found is None:
        return
    if found.get("revisar") and not found.get("monto"):
        manual.append(note("Experiencia del postor: no se pudo leer.", obra, found))
        return
    if found.get("revisar"):
        manual.append(note(f'Experiencia del postor: se leyó {op.soles(found["monto"])}, que no cuadra con la '
                           f'cuantía; puede ser una cifra mal leída.', obra, found))
        return
    times_word = "vez" if found.get("veces") == "1" else "veces"
    asked = op.soles(found["monto"]) if found.get("monto") else f'{found["veces"]} {times_word} la cuantía'
    times = found.get("veces_cuantia")
    # shown as a fact: a requisito above or below one cuantía is the entidad's choice, not an error
    if times and Decimal(times) != 1:
        asked += f" ({Decimal(times):.2f} veces la cuantía)".replace(".", ",", 1)
    parts = [asked]
    where = found.get("especialidad") or ""
    if found.get("subespecialidades"):
        where += (" — " if where else "") + ", ".join(found["subespecialidades"])
    if where:
        parts.append(f"en {where}")
    if found.get("anios"):
        parts.append(f"en los últimos {found['anios']} años")
    if found.get("cuenta_desde"):
        parts.append(f"contados desde {found['cuenta_desde']}")
    if found.get("monto_letras"):
        manual.append(note(f'Experiencia del postor: el monto en letras dice {op.soles(found["monto_letras"])}.',
                           obra, found))
    values.append(value("Experiencia del postor", ", ".join(parts), obra, found))


def personal(obra: dict, values: list, manual: list, consult: list, look: list) -> None:
    found = obra.get("personal")
    if found is None:
        return
    if found.get("revisar") in ("cargos ilegibles", "personal clave sin tiempos legibles"):
        manual.append(note("Personal clave: no se pudo leer el cuadro de cargos.", obra, found))
        return
    if found.get("revisar"):
        manual.append(note("Personal clave: no se encontró en el texto de las bases.", obra, None))
        return
    for w in found.get("avisos") or []:
        text = f"{w['cargo']}: el tiempo en cifras ({w['cifra']}) no es el que dicen las letras ({w['letras']})."
        (look if found.get("ocr") else consult).append(note(text, obra, found))
    values.append(value("Personal clave", "", obra, found, [(p["cargo"] or "", p["tiempo"]) for p in found["personal"]]))


def factors(obra: dict, values: list, manual: list, consult: list) -> None:
    found = obra["factores"]
    if found is None:
        return
    if found.get("revisar"):
        manual.append(note("Factores de evaluación: no se pudo leer el cuadro resumen.", obra, found))
        return
    for w in found.get("avisos") or []:
        consult.append(note(op.factor_warning_text(w), obra, found))
    items = [(f["factor"], f"{f['puntos']} pts") for f in found["factores"]] + [("Total", f"{found['total']} pts")]
    values.append(value("Factores de evaluación", "", obra, found, items))


def history(conn: psycopg.Connection, nid: int) -> list[dict]:
    rows = conn.execute(
        """SELECT campo, valor_anterior, valor_nuevo, detectado_en FROM historial
           WHERE nid_proceso = %s AND campo <> 'reinicio' ORDER BY detectado_en DESC, id DESC""", [nid]).fetchall()
    out = []
    for campo, antes, ahora, cuando in rows:
        if campo == "seguimiento":
            text = STOPPED.get(ahora, ahora or "")
        elif campo == "documento":
            text = f"Documento nuevo: {ahora}"
        else:
            text = f"{CHANGE_NAMES.get(campo, campo).capitalize()}: {antes or '—'} → {ahora or '—'}"
        out.append({"texto": text, "cuando": cuando.astimezone(op.LIMA)})
    return out


def documents(conn: psycopg.Connection, nid: int) -> list[dict]:
    rows = conn.execute(
        """SELECT id, tipo, nombre_archivo, publicado_en, ruta_local FROM documentos
           WHERE nid_proceso = %s AND estado = 'done' ORDER BY publicado_en DESC NULLS LAST, id DESC""", [nid]
    ).fetchall()
    return [{"id": i, "tipo": tipo, "nombre": nombre, "publicado": publicado.astimezone(op.LIMA) if publicado else None,
             "disponible": bool(ruta) and Path(ruta).exists()} for i, tipo, nombre, publicado, ruta in rows]


def document_path(conn: psycopg.Connection, nid: int, doc_id: int, root: Path) -> Path | None:
    """The downloaded file of one document of this obra, only if it lies inside the download folder."""
    row = conn.execute("SELECT ruta_local FROM documentos WHERE id = %s AND nid_proceso = %s AND estado = 'done'",
                       [doc_id, nid]).fetchone()
    return inside(Path(row[0]), root) if row and row[0] else None


def document_uuid(conn: psycopg.Connection, nid: int, doc_id: int) -> str | None:
    """The SEACE id of one document of this obra, to fetch it from SEACE when it is no longer here."""
    row = conn.execute("SELECT uuid FROM documentos WHERE id = %s AND nid_proceso = %s AND uuid IS NOT NULL",
                       [doc_id, nid]).fetchone()
    return row[0] if row else None


def bases_file(conn: psycopg.Connection, nid: int, doc_id: int, name: str, root: Path) -> Path | None:
    """One PDF or DOCX of a bases document by its file name: the download itself, or a file unpacked from it."""
    row = conn.execute("SELECT ruta_local FROM documentos WHERE id = %s AND nid_proceso = %s AND estado = 'done'",
                       [doc_id, nid]).fetchone()
    if not row or not row[0]:
        return None
    contents = [r[0] for r in conn.execute("SELECT ruta FROM documento_contenido WHERE documento_id = %s",
                                           [doc_id]).fetchall()]
    for path in bases_files(row[0], contents):
        if path.name == name:
            return inside(path, root)
    return None


def inside(path: Path, root: Path) -> Path | None:
    resolved, base = path.resolve(), root.resolve()
    return resolved if resolved.is_relative_to(base) and resolved.is_file() else None
