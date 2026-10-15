"""The requisito de calificación "Experiencia del personal clave" in chapter III of the bases.

A table gives each cargo (residente de obra, especialista en seguridad, ...) and the time of experience it
asks for. Every entity lays the table out its own way: the cargo in a column of short lines, the time in its
own column or at the top of a long description. The text keeps the columns (pdftotext -layout), so the
cargo is read from its column and the rows are paired with the times in order; a reading whose cargos and
times do not pair up goes to a person.
"""

import re
from collections import Counter
from collections.abc import Callable
from pathlib import Path

from . import letras, reading
from .bases_text import page_of

VERSION = "personal-5"
VALUES = {"meses": lambda r: sorted(p["meses"] for p in r.get("personal") or [] if p.get("meses") is not None)}

# The requirement heading followed by "Requisitos", not the scoring factor of chapter IV nor a sentence citing
# it. OCR leaves noise before "B.2" ("de .B.2", "“iB.2") and puts a second column on the same line;
# "Requisitos:" comes out as "Reguisitos:" as in experiencia.
REQUIREMENT = re.compile(r"(?:B\s*\.\s*2\s*\.?\s*|^[^\w\n]*)EXPERIENCIA\s+DEL?\s+PERSONAL\s+CLAVE\b(?![”\")])"
                         r"(?:(?!PUNTAJE|Acreditaci[oó]n\s*:).){0,400}?(?:\bRe\w{4,9}\s*:|^\s*REQUISITOS?\b)[^\n]*\n",
                         re.I | re.S | re.M)
# The numbered heading alone is enough when OCR garbled or dropped "Requisitos" ("Begu¡si;osz"); "8.2" is OCR's "B.2".
NUMBERED_HEADING = re.compile(r"\b[B8]\s*\.\s*2\s*\.?\s*EXPERIENCIA\s+DEL\s+PERSONAL\s+CLAVE\b(?![”\")])[^\n]*\n", re.I)
END = re.compile(r"Acreditaci[oó]n\s*:", re.I)
# Characters, not lines: a -layout line of a table is over a hundred characters, mostly spaces, so this is about
# four pages. A shorter cut ended a table in the middle and left its last cargos out.
MAX_BLOCK = 30000
# "24 meses", "36 MESES", "veinticuatro (24) meses", "(12 meses)", "3 años"
TIME = re.compile(r"\(?\s*(?<![\d.,])(\d{1,3})\s*\)?\s*(mes(?:es)?|a[ñn]os?)\b", re.I)
# "una antigüedad no mayor a veinte (20) años" is about the works counted, not a cargo
NOT_A_TIME = re.compile(r"antig[uü]edad|anteriores", re.I)
HEAD = r"RESIDENTE|ESPECIALISTA|JEFE|ARQUE[OÓ]LOGO|ASISTENTE|SUPERVISOR|TOP[OÓ]GRAFO|COORDINADOR|INSPECTOR|" \
       r"ADMINISTRADOR|MAESTRO|CAPATAZ|RESPONSABLE|GERENTE|DIRECTOR|PREVENCIONISTA|ARQUITECTO|PROFESIONAL"
HEADS = re.compile(r"\b(?:" + HEAD + r")\b", re.I)
START = re.compile(r"^(?:" + HEAD + r"|ING\.?|INGENIER[OA]|LIC\.?|LICENCIAD[OA]|T[EÉ]CNICO|BACHILLER)\b", re.I)
ENGINEER = re.compile(r"^(?:ING\.?|INGENIER[OA])\s+(?:(?:de|en|del)\s+)?\w{4,}", re.I)
CONNECTOR = re.compile(r"\b(?:de|del|en|y|e|o|la|las|el|a|con)$|[/,\-]$", re.I)
NUMBERED = re.compile(r"^\s{0,12}\d{1,2}\s*[.)\-]\s+([A-ZÁÉÍÓÚÑ][^\n]{3,70}?)\s*$", re.M)
# The column headers; the cargo column is the one headed CARGO, PERSONAL or PUESTO.
CARGO_HEADER = re.compile(r"\b(?:CARGO|PERSONAL|PUESTO)\b", re.I)
HEADER_WORDS = re.compile(r"\bCARGO|\bPERSONAL\b|\bPUESTO|EXPERIENCIA|EXPERENCIA|PROFESI|TIEMPO|TIPO\s+DE|"
                          r"ESPECIALIDAD|REQUERID|FORMACI|ACREDITACI|DESEMPE|RESPONSABILIDAD|CANT|^\s*N\s*[°º.]?\s*$|"
                          r"PLANTEL|^\s*DE\s*$|T[IÍ]TULO|POSICI[OÓ]N|\bCLAVE\b|\b[IÍ]TEM\b|DENOMINACI", re.I)
PAGE_LINE = re.compile(r"MUNICIPALIDAD|GOBIERNO|LICITACI|CONVOCATORIA|CONCURSO|PROCEDIMIENTO|PROGRAMA\s+NACIONAL|"
                       r"GERENCIA|NOMBRE\s+DE\s+LA\s+ENTIDAD|\bN[°º]\s*\d|^\s*\d{1,3}\s*$|-20\d\d-|/20\d\d\b|"
                       r"Firmado|digitalmente|Motivo\s*:|Fecha\s*:|\bFAU\b|\b\d{6,}\b|[“”]|"
                       r"BASES\s+(?:INTEGRADAS|ADMINISTRATIVAS)", re.I)
NOT_CARGO = re.compile(r"^(?:\d{1,3}|N[°º]|\d{1,2}[.)]|\d+[.,]\d+|MESES|A[ÑN]OS|[—–\-.\"'“”]+)$", re.I)
# The time column's "(computado desde la fecha de la colegiatura)" falling inside the cargo column.
COUNTED_FROM = re.compile(r"\(?\s*(?:se\s+)?computad?[oa]s?\b.*?colegiatura\s*\)?\.?|\bse\s+computa\b.*?colegiatura\.?",
                          re.I | re.S)
NOISE = {"se", "computa", "computado", "computados", "computada", "desde", "la", "fecha", "de", "colegiatura",
         "colegiatura.", "a", "partir", "partir:", "obtención", "del", "(computado", "colegiatura)", "computados,"}
# Words of that column no cargo name has
TIME_COLUMN_WORDS = {"se", "desde", "computa", "computado", "computados", "computada", "colegiatura", "colegiatura.",
                     "colegiatura)", "(computado", "partir", "partir:"}
# Words of cargo names; a cargo read through OCR with any other word is noise or a column run together.
VOCABULARY = set("""
residente obra obras de del la el en y e o a especialista especialistas ingeniero ingeniera ing ing. seguridad salud
ocupacional trabajo medio ambiente ambiental ambientalista calidad control estructuras estructural estructurista
arquitectura arquitecto urbanismo suelos pavimentos mecánica mecanica mecánico mecanico geotecnia geotécnico geología
geologia hidrología hidrologia hidráulico hidraulico hidráulica hidraulica hidrológico hidrologico arte sanitario
sanitarias sanitaria instalaciones eléctricas electricas eléctrico electrico electromecánico electromecanico costos
presupuestos metrados valorizaciones jefe proyecto gerente asistente supervisor coordinador topógrafo topografo
arqueólogo arqueologo ssoma sso impacto riesgos prevención prevencion redes primarias secundarias trazo diseño diseno
geométrico geometrico vial vías vias tránsito transito señalización materiales laboratorio comunicaciones social
puentes riego energía energia equipamiento planeamiento programación programacion higiene industrial bim
geólogo geologo geotécnico geotecnico geólogo-geotécnico arqueología arqueologia patrimonio cultural monitor
monitoreo arqueológico arqueologico electricista instalador agrónomo agronomo forestal biólogo biologo
""".split())

NOT_FOUND = "sin requisito de personal clave"
UNREADABLE = "cargos ilegibles"
NO_TIME = "personal clave sin tiempos legibles"


def times_in(block: str) -> list[dict]:
    """Every time of experience, with its line and column; "(24)" and "meses" may sit on two lines."""
    found = []
    for m in TIME.finditer(block):
        start = m.start() + len(m.group()) - len(m.group().lstrip())
        line_start = block.rfind("\n", 0, start) + 1
        before = block[line_start: start]
        if NOT_A_TIME.search(block[max(0, start - 60): start]) or NOT_A_TIME.match(block[m.end():].lstrip()):
            continue
        n, unit = int(m.group(1)), m.group(2).lower()
        years = unit.startswith("a")
        line_end = block.find("\n", start)
        item = {"line": block.count("\n", 0, start), "x": start - line_start,
                "end": min(m.end(), line_end if line_end >= 0 else m.end()) - line_start, "valor": n,
                "tiempo": f"{n} {('año' if years else 'mes') + ('' if n == 1 else 's' if years else 'es')}",
                "meses": n * 12 if years else n, "letras": None}
        # "treinta y seis (24) meses": the words before the parenthesis say another number
        if m.group().lstrip().startswith("("):
            words = letras.plain(before[-40:]).split()
            for k in range(min(4, len(words)), 0, -1):
                if (said := letras.integer(words[-k:])) is not None:
                    item["letras"] = said
                    break
        found.append(item)
    # "mínima de (12)" ending a line, "meses" opening the description's next line after another column's words
    lines = block.split("\n")
    for i, line in enumerate(lines[:-1]):
        m = re.search(r"\((\d{1,3})\)\s*$", line)
        unit = re.search(r"(?:^|\s{2,})(mes(?:es)?|a[ñn]os?)\b", lines[i + 1], re.I)
        if not m or not unit or any(t["line"] == i and abs(t["x"] - m.start()) <= 1 for t in found):
            continue
        n, years = int(m.group(1)), unit.group(1).lower().startswith("a")
        found.append({"line": i, "x": m.start(), "end": m.end(), "valor": n, "letras": None,
                      "tiempo": f"{n} {('año' if years else 'mes') + ('' if n == 1 else 's' if years else 'es')}",
                      "meses": n * 12 if years else n})
    return sorted(found, key=lambda t: (t["line"], t["x"]))


def description_column(lines: list[str]) -> int:
    """Where the long lines of the table begin: the descriptions, right of the cargo column."""
    starts = Counter()
    for line in lines:
        for m in re.finditer(r"\S+(?: \S+)*", line):
            if len(m.group()) >= 20 and not PAGE_LINE.search(m.group()):
                starts[m.start()] += 1
    if not starts:
        return 40
    # one row's description may begin a little left of the others
    most = starts.most_common(1)[0][1]
    return min(x for x, n in starts.items() if n >= min(most, max(3, most / 3)))


def cargo_column(lines: list[str], first_time: int) -> tuple[int, int]:
    """The first line below the column headers (all above the first time) and the column's right edge."""
    right = description_column(lines)
    first, cargo_end, profession = 0, None, None
    for i, line in enumerate(lines[:first_time]):
        # "CARGO Y/O" on one line and "PROFESIÓN   TIEMPO EN EXPERIENCIA" on the next
        if m := CARGO_HEADER.search(line):
            cargo_end = cargo_end or m.end()
        if (m := re.search(r"PROFESI|T[IÍ]TULO", line, re.I)) and HEADER_WORDS.search(line):
            profession = profession or m.start()
        tokens = list(re.finditer(r"\S+(?: \S+)*", line))
        if not tokens or not all(len(t.group()) <= 40 and HEADER_WORDS.search(t.group()) for t in tokens):
            continue
        if len(tokens) < 2 and not CARGO_HEADER.search(line):
            continue
        first = i + 1
        for k, t in enumerate(tokens[:-1]):
            if not CARGO_HEADER.search(t.group()):
                continue
            following = tokens[k + 1]
            # the descriptions begin where their column does; a short column (profession, type of experience,
            # quantity) is centered under its header and begins left of it
            if re.match(r"EXPERI?ENCIA\b(?!\s+DE\b)", following.group(), re.I):
                right = min(right, following.start())
            else:
                right = min(right, (t.end() + following.start()) // 2)
    if cargo_end and profession and profession > cargo_end:
        right = min(right, (cargo_end + profession) // 2)
    return first, right


def cargo_edge(lines: list[str], times: list[dict]) -> tuple[int, int]:
    first, right = cargo_column(lines, times[0]["line"])
    if right < 8:
        # descriptions too narrow to give long lines, notes across the page did: the cargo column is left of the times
        right = min(t["x"] for t in times) - 1
    return first, right


def fragments(lines: list[str], first: int, right: int, times: list[dict]) -> list[tuple[int, str]]:
    """The words of the cargo column, line by line."""
    out = []
    signature = 0  # lines left of a digital signature stamp: "Firmado digitalmente por", name, RUC, Motivo, Fecha
    for i in range(first, len(lines)):
        line = lines[i]
        if re.search(r"Firmado\s+digital|digitalmente\s+por", line, re.I):
            signature = 6
        if signature:
            signature = 0 if re.search(r"Fecha\s*:", line, re.I) else signature - 1
            line = " " * right + line[right:]
        if PAGE_LINE.search(line) and not HEADS.search(line[:right]):
            continue
        for t in times:
            if t["line"] == i:
                line = line[:t["x"]] + " " * (t["end"] - t["x"]) + line[t["end"]:]
        words = [m for m in re.finditer(r"\S+", line) if m.start() < right]
        if not words:
            continue
        # a note below the table ("*Se considera obras similares a: ...", "Importante") ends it
        if out and re.match(r"\s{0,14}(?:[*(]|Nota\b)|\s*(?:Importante|Advertencia)\b", line, re.I):
            break
        tokens = re.findall(r"\S+(?: \S+)*", line)
        if len(tokens) > 1 and all(len(t) <= 40 and HEADER_WORDS.search(t) for t in tokens):
            continue  # the column headers again at the top of the next page
        text = joined(" ".join(w.group() for w in words
                               if not NOT_CARGO.match(w.group()) and w.group().lower() not in TIME_COLUMN_WORDS))
        plain = text.lower().split()
        if plain and all(w in NOISE for w in plain) and not {"de", "la", "del", "a"}.issuperset(plain):
            continue  # "se", "desde", "colegiatura." of the time column, one word a line
        if text and not (HEADER_WORDS.search(text) and not HEADS.search(text)):
            out.append((i, text))
    return out


def joined(text: str) -> str:
    """ "Especialis ta" (a word the text layer broke in two) as one word, when only together it is a cargo word."""
    words = text.split(" ")
    out = []
    for word in words:
        if out and (out[-1] + word).lower() in VOCABULARY and out[-1].lower() not in VOCABULARY \
                and word.lower() not in VOCABULARY:
            out[-1] += word
        else:
            out.append(word)
    return " ".join(out)


def complete(cargo: str) -> bool:
    return bool(HEADS.search(cargo) or ENGINEER.match(cargo))


def doubtful(cargo: str) -> bool:
    """Two cargos run together (a row lost its time, so every pairing below it is off), a column of professions
    or descriptions mixed in, or OCR noise."""
    words = cargo.lower().split()
    return (len(re.findall(r"\b(?:RESIDENTE|ESPECIALISTA)\b", cargo, re.I)) > 1
            or len(re.findall(r"\bING(?:\.|ENIER[OA]\b)", cargo, re.I)) > 1
            or not cargo[:1].isupper() or bool(CONNECTOR.search(cargo))
            or len(cargo) > 75 or bool(re.search(r"\d", cargo))
            or any(a == b for a, b in zip(words, words[1:]))
            or bool(re.search(r"\bING(?:\.|ENIER[OA])\s+CIVIL\b|\bREQUISITO|\bIMPORTANTE\b|\by\s*/\s*o\b",
                              cargo, re.I))
            # "RESIDENTE DE OBRA seis en el INGENIERO Doce": the words of a time from the description
            or any(letras.plain(w) in letras.UNITS for w in words if w not in ("e", "y", "un", "una"))
            or bool(re.search(r"[¡=|\\{}<>]|[;,]\w", cargo)))


def unknown_words(cargo: str) -> list[str]:
    return [w for w in re.findall(r"[^\s,()/–—-]+", cargo.lower())
            if w.strip(".") not in VOCABULARY and w not in VOCABULARY]


def rows_from_column(frags: list[tuple[int, str]]) -> list[dict]:
    # "Especialis" on one line and "ta en" on the next
    frags = [list(f) for f in frags]
    for a, b in zip(frags, frags[1:]):
        head, _, last = a[1].rpartition(" ")
        first, _, rest = b[1].partition(" ")
        if joined(f"{last} {first}") == last + first:
            a[1], b[1] = f"{head} {last}{first}".strip(), rest
    rows = []
    for i, text in ((i, t) for i, t in frags if t):
        starts = START.match(text)
        if starts and (not rows or complete(rows[-1]["cargo"]) and not CONNECTOR.search(rows[-1]["cargo"])):
            rows.append({"line": i, "cargo": text})
        elif rows:
            rows[-1]["cargo"] += " " + text
    return [r for r in rows if complete(r["cargo"])]


def rows_from_headings(block: str) -> list[dict]:
    """ "1. Residente de Obra" above a small table of its own, one per cargo."""
    rows = []
    for m in NUMBERED.finditer(block):
        if HEADS.search(m.group(1)) or ENGINEER.match(m.group(1)):
            rows.append({"line": block.count("\n", 0, m.start()), "cargo": m.group(1)})
    return rows


def rows_from_cells(lines: list[str], times: list[dict]) -> list[dict]:
    """A Word table gives one cell a line: the cargo on the line just above the one its description and time
    open ("Residente de Obra" / "5 años de experiencia como: ...")."""
    rows = []
    for t in times:
        above = next((lines[i].strip() for i in range(t["line"] - 1, -1, -1) if lines[i].strip()), "")
        if t["x"] <= 2 and len(above) <= 80 and START.match(above) and complete(above):
            rows.append({"line": t["line"] - 1, "cargo": above})
    return rows


def pair(rows: list[dict], times: list[dict]) -> list[dict] | None:
    """Times in the order of the rows. A row may state its time twice, in its own column and in the
    description ("24 meses" and "veinticuatro (24) meses" a few lines apart); any other surplus is no pairing."""
    if len(times) == len(rows):
        return times
    if len(times) < len(rows):
        return None
    columns = []
    for t in times:
        column = next((c for c in columns if abs(c[0]["x"] - t["x"]) <= 10), None)
        if column is None:
            columns.append([t])
        else:
            column.append(t)
    for column in columns:
        others = [t for t in times if t not in column]
        if len(column) == len(rows) and all(
                any(u["valor"] == t["valor"] and abs(u["line"] - t["line"]) <= 15 for u in column) for t in others):
            return column
    return None


def squeeze(text: str) -> str:
    text = re.sub(r"\s+", " ", COUNTED_FROM.sub(" ", text)).strip(" ,;:-—–.…\"'“”•·")
    # A cargo in capitals with a lowercase word: a word of another column ("... TRABAJO consignadas",
    # "ESPECIALISTA DE la SEGURIDAD" with the "la" of "Desde la Colegiatura")
    if sum(c.isupper() for c in text) > 3 * sum(c.islower() for c in text):
        text = " ".join(w for w in text.split() if not re.fullmatch(r"[a-záéíóúñ]+", w))
    return text


def read(text: str) -> dict:
    """Each cargo with the time of experience it asks for; `avisos` when a time's words and digits differ."""
    result = {"pagina": None, "personal": [], "avisos": [], "revisar": None}
    m = REQUIREMENT.search(text) or NUMBERED_HEADING.search(text)
    if not m:
        result["revisar"] = NOT_FOUND
        return result
    result["pagina"] = page_of(text, m.start())
    end = END.search(text, m.end())
    block = text[m.end(): end.start() if end and end.start() - m.end() < MAX_BLOCK else m.end() + MAX_BLOCK]
    block = block.replace("|", " ")  # OCR reads the table's rules as bars that join two columns
    lines = block.split("\n")
    times = times_in(block)
    if not times:
        result["revisar"] = NO_TIME
        return result
    rows = rows_from_headings(block)
    if len(rows) != len(times):
        first, right = cargo_edge(lines, times)
        rows = rows_from_column(fragments(lines, first, right, times))
    paired = pair(rows, times) if rows else None
    if paired is None and len(cells := rows_from_cells(lines, times)) == len(times):
        rows, paired = cells, times
    if paired is None or any(doubtful(squeeze(r["cargo"])) for r in rows):
        result["personal"] = [{"cargo": None, "tiempo": t["tiempo"], "meses": t["meses"]} for t in times]
        result["revisar"] = UNREADABLE
        return result
    for row, t in zip(rows, paired):
        result["personal"].append({"cargo": squeeze(row["cargo"]), "tiempo": t["tiempo"], "meses": t["meses"]})
        if t["letras"] is not None and t["letras"] != t["valor"]:
            result["avisos"].append({"aviso": "tiempo_distinto_letras", "cargo": squeeze(row["cargo"]),
                                     "cifra": t["valor"], "letras": t["letras"]})
    return result


def read_files(files: list[Path], ocr: Callable[[Path, list[int]], Path] | None = None) -> dict:
    result = reading.read_files(files, read, NOT_FOUND, ocr, VALUES)
    # OCR breaks words and shifts columns: a cargo with a word no cargo has is not shown as read, and a time
    # whose words say another number is a misread digit, not the entity's mistake.
    if result["ocr"] and not result["revisar"] and (any(unknown_words(p["cargo"]) for p in result["personal"])
                                                    or result["avisos"]):
        result["personal"] = [{**p, "cargo": None} for p in result["personal"]]
        result["avisos"] = []
        result["revisar"] = UNREADABLE
    return result
