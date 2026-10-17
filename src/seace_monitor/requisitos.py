"""What each evaluation factor asks for its points (chapter IV) and the profile each cargo of the personal clave
must have (chapter III), read by Claude Haiku through OpenRouter from the bases' text.

Both chapters are written in two columns and every entity arranges them its own way, so the text (pdftotext, or
the vision model's transcription of a scan) goes to the model with page marks, and the answer is checked against
what the rule readers already read: each factor's maximum points against the CUADRO RESUMEN, the months per
cargo against the personal clave table. A factor or cargo that does not match is kept but marked unchecked, for
a person. Pages are found in the text, not taken from the model.
"""

import json
import re
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path

import requests

from .bases_text import TextError, is_scanned, page_of, text_of
from . import personal
from .factores import factor_name
from .ocr import ia_path

VERSION = "requisitos-1"
URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = "anthropic/claude-haiku-5.5"
TIMEOUT = 300
MAX_CHARS = 45000
# how far before the personal clave requirement chapter III's text starts at most (the formación comes first)
PERSONAL_LEAD = 12000
NOT_FOUND = "sin capítulos III ni IV legibles"
EMPTY = "el modelo no devolvió factores o cargos de un capítulo encontrado"

FACTORS_PROMPT = """Abajo va el capítulo IV (evaluación de ofertas) de unas bases de licitación de obras del Perú, con la
página de cada parte marcada como [página N]. El texto puede venir de un PDF a dos columnas: a la izquierda
"Evaluación" y "Acreditación", a la derecha el puntaje por tramo; las líneas de ambas columnas pueden estar mezcladas.

Para cada factor de la evaluación técnica que da puntos (no los que dicen "NO CORRESPONDE"), devuelve:
- "letra" y "nombre" como en las bases,
- "puntaje_maximo" (número),
- "que_se_evalua": qué tiene que tener el postor para los puntos, en una o dos frases cortas, con las cifras
  exactas (años, montos, cargos, normas ISO),
- "como_se_acredita": con qué documento se prueba, en una frase corta,
- "tramos": lista de {"condicion": ..., "puntos": número}, tal como los da la columna de puntaje.

Reglas: copia las cifras tal como están; no inventes nada que no esté en el texto; si algo no se puede leer,
pon null. Devuelve solo un JSON: {"factores": [...]}"""

PERSONAL_PROMPT = """Abajo van los requisitos de calificación (capítulo III) de unas bases de licitación de obras del Perú,
con la página de cada parte marcada como [página N]. Puede venir de un PDF con tablas; las columnas pueden estar
mezcladas.

Para cada cargo del personal clave, devuelve:
- "cargo" como en las bases,
- "formacion": profesión o grado pedido (por ejemplo "Ingeniero civil o ingeniero agrícola"), o null si no lo dice,
- "colegiatura": true si pide estar colegiado o habilitado (también si cuenta la experiencia "desde la
  colegiatura"), false si dice que no hace falta, null si no lo dice en ninguna parte del texto,
- "experiencia_meses": número de meses de experiencia pedidos (convierte años a meses),
- "experiencia_en": en qué cargos o trabajos cuenta esa experiencia, en una frase corta,
- "capacitacion": horas o cursos pedidos, o null.

Reglas: copia las cifras tal como están; no inventes nada; si algo no se puede leer, pon null.
Devuelve solo un JSON: {"personal": [...]}"""


class RequisitosError(Exception):
    """The model could not be asked or its answer was not usable; the bases are left for a later run."""


class SpendingCap(Exception):
    """No further request may be made in this run."""


def marked(text: str, start: int, stop: int) -> str:
    first = page_of(text, start)
    pages = text[start:stop].split("\f")
    return "\n".join(f"[página {first + i}]\n{p}" for i, p in enumerate(pages))[:MAX_CHARS]


def chapter_iv(text: str) -> tuple[int, int] | None:
    """Where chapter IV's factors start and the economic evaluation (or chapter V) begins."""
    for m in re.finditer(r"CAP[IÍ]TULO\s+IV\b", text):
        if re.search(r"FACTORES\s+DE\s+EVALUACI", text[m.start(): m.start() + 4000], re.I):
            end = re.search(r"EVALUACI[OÓ]N\s+ECON[OÓ]MICA\s*\(|CAP[IÍ]TULO\s+V\b", text[m.start() + 2000:])
            return m.start(), m.start() + 2000 + end.start() if end else m.start() + MAX_CHARS
    return None


def chapter_iii(text: str) -> tuple[int, int] | None:
    """Where chapter III's requisitos de calificación start and chapter IV begins, when it asks for personal clave.
    The sección general has a chapter III that names the personal clave too, without its requirement."""
    for m in re.finditer(r"CAP[IÍ]TULO\s+III\b", text):
        end = re.search(r"CAP[IÍ]TULO\s+IV\b", text[m.end():])
        stop = m.end() + end.start() if end else m.end() + MAX_CHARS
        found = personal.REQUIREMENT.search(text, m.end(), stop) or personal.NUMBERED_HEADING.search(text, m.end(), stop)
        if not found:
            continue
        return lead_in(text, m.start(), found.start()), stop
    return None


def lead_in(text: str, floor: int, requirement: int) -> int:
    """The requerimiento before the personal clave can run for many pages: start at the capacidad técnica heading
    that opens the personal clave's formación and experiencia, or shortly before the requirement, so it fits."""
    near = max(floor, requirement - PERSONAL_LEAD)
    heading = None
    for heading in re.finditer(r"CAPACIDAD\s+T[EÉ]CNICA", text[near: requirement], re.I):
        pass
    return near + heading.start() if heading else near


def around_personal(text: str, page: int) -> tuple[int, int] | None:
    """Chapter III around the requirement the personal clave reader read on `page`, for bases without the heading
    chapter_iii looks for, or with another chapter between it and the requirement."""
    at = len("\f".join(text.split("\f")[: page - 1]))
    found = personal.REQUIREMENT.search(text, at) or personal.NUMBERED_HEADING.search(text, at)
    if not found or page_of(text, found.start()) != page:
        return None
    end = re.search(r"CAP[IÍ]TULO\s+IV\b", text[found.end():])
    return lead_in(text, 0, found.start()), found.end() + end.start() if end else found.end() + MAX_CHARS


def texts(files: list[Path]) -> list[tuple[Path, str]]:
    """Each file with its text as the readers see it: the model's transcription of a scan, else its own text."""
    out = []
    for path in files:
        try:
            if ia_path(path).exists():
                out.append((path, text_of(ia_path(path))))
            elif not is_scanned(text := text_of(path)):
                out.append((path, text))
        except TextError:
            continue
    return out


def ask(key: str, prompt: str) -> tuple[dict, Decimal]:
    body = {"model": MODEL, "usage": {"include": True}, "max_tokens": 12000,
            "messages": [{"role": "system", "content": "Extraes datos de documentos y respondes solo con JSON."},
                         {"role": "user", "content": prompt}]}
    try:
        answer = requests.post(URL, json=body, timeout=TIMEOUT, headers={"Authorization": f"Bearer {key}"})
    except requests.RequestException as error:
        raise RequisitosError(f"OpenRouter unreachable: {error}") from error
    if answer.status_code != 200:
        raise RequisitosError(f"OpenRouter answered {answer.status_code}: {answer.text[:200]}")
    try:
        data = answer.json()
        cost = Decimal(str((data.get("usage") or {}).get("cost") or 0))
    except (ValueError, AttributeError, ArithmeticError) as error:
        raise RequisitosError(f"answer not understood: {answer.text[:200]}") from error
    # paid even when its content is not usable: the caller charges the cost and then gives up on the bases
    try:
        content = data["choices"][0]["message"]["content"] or ""
        parsed = json.loads(content[content.find("{"): content.rfind("}") + 1])
    except (ValueError, KeyError, IndexError, TypeError):
        parsed = None
    return parsed if isinstance(parsed, dict) else None, cost


HEADING = re.compile(r"(?m)^[^\w\n]{0,30}[A-P](?:\.\d)?\s*[.)]\s*([A-ZÁÉÍÓÚÑ][^\n]{4,120})$")


def factor_page(text: str, start: int, stop: int, name: str | None) -> int | None:
    """The page where the factor's own description starts: its lettered heading ("M. EXPERIENCIA ADICIONAL DEL
    POSTOR ..."), which the standard bases put before the CUADRO RESUMEN; the table's rows name every factor too."""
    if name is None:
        return None
    summary = re.search(r"RESUMEN\W{0,5}(?:DE\s+)?(?:LOS\s+)?FACTORES", text[start:stop], re.I)
    end = start + summary.start() if summary else stop
    for m in HEADING.finditer(text, start, end):
        if factor_name(m.group(1)) == name:
            # its end, not its start: the line can open with the form feed of its page
            return page_of(text, m.end())
    return None


def check_factors(answer: list[dict], summary: list[dict] | None, text: str, start: int, stop: int) -> list[dict]:
    """Each factor with its standard name, its page and whether its maximum points are the summary table's."""
    table = {f["factor"]: f["puntos"] for f in summary or [] if f.get("puntos") is not None}
    out = []
    for f in answer:
        name = factor_name(f.get("nombre") or "") or f.get("nombre")
        out.append({**f, "factor": name, "pagina": factor_page(text, start, stop, name),
                    "comprobado": name in table and table[name] == f.get("puntaje_maximo")})
    return out


def check_personal(answer: list[dict], reading: list[dict] | None) -> tuple[list[dict], bool]:
    """The cargos as the model gives them; checked when its months, in order, are the personal clave table's."""
    months = [p["meses"] for p in reading or [] if p.get("meses") is not None]
    asked = [p.get("experiencia_meses") for p in answer]
    return answer, bool(months) and asked == months


def read_files(files: list[Path], key: str, factores_reading: dict | None, personal_reading: dict | None,
               ask: Callable[[str, str], tuple[dict, Decimal]] = ask,
               charge: Callable[[Decimal], None] = lambda usd: None,
               may_spend: Callable[[], bool] = lambda: True) -> dict:
    """Ask the model for both chapters of the first file that holds each; `charge` gets each answer's cost.
    `may_spend` is asked once, before the first request: a bases once started is finished, so a cap is passed by
    one request at most and no paid answer is thrown away to be paid again."""
    result = {"factores": [], "personal": [], "pagina_factores": None, "pagina_personal": None,
              "personal_comprobado": False, "revisar": None}
    all_text = texts(files)
    iv = next(((p, t, found) for p, t in all_text if (found := chapter_iv(t))), None)
    iii = next(((p, t, found) for p, t in all_text if (found := chapter_iii(t))), None)
    if iii is None and (where := personal_reading or {}).get("archivo") and where.get("pagina"):
        iii = next(((p, t, found) for p, t in all_text
                    if p.name == where["archivo"] and (found := around_personal(t, where["pagina"]))), None)
    if iv is None and iii is None:
        result["revisar"] = NOT_FOUND
        return result
    if not may_spend():
        raise SpendingCap("spending cap reached")

    def asked(prompt: str, field: str) -> list[dict]:
        answer, usd = ask(key, prompt)
        charge(usd)
        if answer is None or not isinstance(answer.get(field) or [], list):
            raise RequisitosError("answer not understood")
        return [item for item in answer.get(field) or [] if isinstance(item, dict)]

    if iv:
        path, text, (start, stop) = iv
        factors = asked(FACTORS_PROMPT + "\n\n" + marked(text, start, stop), "factores")
        result["pagina_factores"], result["archivo_factores"] = page_of(text, start), path.name
        result["factores"] = check_factors(factors, (factores_reading or {}).get("factores"), text, start, stop)
    if iii:
        path, text, (start, stop) = iii
        personnel = asked(PERSONAL_PROMPT + "\n\n" + marked(text, start, stop), "personal")
        result["pagina_personal"], result["archivo_personal"] = page_of(text, start), path.name
        result["personal"], result["personal_comprobado"] = check_personal(
            personnel, (personal_reading or {}).get("personal"))
    # a chapter found but answered with nothing: kept for a person rather than asked (and paid) again every night
    if iv and not result["factores"] or iii and not result["personal"]:
        result["revisar"] = EMPTY
    return result
