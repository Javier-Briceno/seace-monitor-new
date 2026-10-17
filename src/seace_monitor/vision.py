"""Transcription of the image pages of scanned bases by a vision model (Claude Haiku through OpenRouter).

The result is kept next to the original as `<name>-ia.txt` (ocr.ia_path), shaped like the Tesseract copy: the
pages with text keep pdftotext's text, each image page among the first LAST_PAGE takes the model's transcription,
every page ends with a line break and pages are split by form feeds. The readers read it before Tesseract's copy.

Spending is capped per calendar month (Lima time): each page's cost, as OpenRouter reports it, is added to
`gasto_ia`, and no file is started once the month's spending has reached the cap. The API key comes from the
OPENROUTER_API_KEY environment variable and is never stored.

Only the pages a reader or the requirements model can use are paid for. A page that is the same scan as a page
of another file of the obra already transcribed (an integradas that keeps the administrativas' pages) takes that
transcription. The sección general, standard text no reader uses, is skipped: its pages are told apart by
Tesseract, which finds where the sección específica starts. Past the contract proforma nothing is read, so
transcription stops there once chapter III and chapter IV are behind it. Skipped pages keep their own text.
"""

import base64
import hashlib
import os
import re
import subprocess
import tempfile
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pikepdf
import psycopg
import requests

from . import requisitos
from .bases_text import LAST_PAGE, TextError, ToolMissing, text_of, tool_path
from .ocr import ia_path, image_pages

URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = "anthropic/claude-haiku-5.5"
TIMEOUT = 300
PROMPT = """Transcribe el texto de esta página escaneada de unas bases de licitación de obras del Perú.

Reglas:
- Copia cada palabra y cada cifra exactamente como está impresa. No corrijas, no completes y no calcules nada.
- En las tablas, escribe cada fila en una sola línea, con las celdas de izquierda a derecha separadas por tres espacios. Si una celda ocupa varias líneas, júntalas en esa misma fila.
- Si una fila o una cifra está tachada a mano, escribe [TACHADO] delante de ella.
- No transcribas firmas, sellos ni vistos buenos.
- Devuelve solo el texto, sin comentarios y sin formato markdown."""


# Cyrillic letters the model sometimes writes for the Latin ones they look like ("PÚBLICА")
HOMOGLYPHS = str.maketrans("АВЕКМНОРСТХУаеорсухіјѕ", "ABEKMHOPCTXYaeopcyxijs")
# Headings on top of a page; Tesseract's accents are not trusted.
GENERAL = re.compile(r"^\W{0,10}SECCI.N\s+GENERAL\b", re.M)
SPECIFIC = re.compile(r"^\W{0,10}SECCI.N\s+ESPEC.FICA\b", re.M)
# Pages sent to the model at once; one at a time a bases of a hundred pages takes over an hour.
WORKERS = 8
# Without the sección específica's heading this many pages after the general one, the skipped pages are sent too.
GENERAL_PAGES = 40
# Words on the first pages of a bases, for a file unpacked from an archive whose name does not say so
BASES_COVER = re.compile(r"BASES\s+(?:EST.NDAR|INTEGRADAS|ADMINISTRATIVAS|DE\s+LA\s+LICITACI|DEL\s+PROCEDIMIENTO)"
                         r"|SECCI.N\s+ESPEC.FICA", re.I)


def top(page: str, lines: int = 8) -> str:
    return "\n".join(page.strip().splitlines()[:lines])


class VisionError(Exception):
    """A page could not be transcribed; the file is left for a later run."""


class BudgetReached(Exception):
    """The month's spending reached the cap."""


def spent(conn: psycopg.Connection, now: datetime) -> Decimal:
    row = conn.execute("SELECT usd FROM gasto_ia WHERE mes = %s", [now.date().replace(day=1)]).fetchone()
    return row[0] if row else Decimal(0)


def add_spending(conn: psycopg.Connection, now: datetime, usd: Decimal, pages: int) -> None:
    conn.execute("""INSERT INTO gasto_ia (mes, usd, paginas) VALUES (%s, %s, %s)
                    ON CONFLICT (mes) DO UPDATE SET usd = gasto_ia.usd + EXCLUDED.usd,
                                                    paginas = gasto_ia.paginas + EXCLUDED.paginas""",
                 [now.date().replace(day=1), usd, pages])


def render(path: Path, page: int, folder: Path) -> bytes:
    stem = folder / f"p{page}"
    try:
        done = subprocess.run(["pdftoppm", "-png", "-r", "150", "-singlefile", "-f", str(page), "-l", str(page),
                               tool_path(path), str(stem)], capture_output=True, timeout=TIMEOUT)
    except subprocess.TimeoutExpired as error:
        raise VisionError(f"page {page} took longer than {error.timeout} s to render") from error
    image = stem.with_suffix(".png")
    if not image.exists():
        raise VisionError(f"page {page} gave no image: {done.stderr.decode('utf-8', 'replace').strip()[:200]}")
    try:
        return image.read_bytes()
    finally:
        image.unlink(missing_ok=True)


def ask(key: str, image: bytes) -> tuple[str, Decimal]:
    """The page's transcription and what it cost. A blank page comes back empty."""
    body = {"model": MODEL, "usage": {"include": True}, "max_tokens": 8000,
            "messages": [{"role": "system", "content": "Eres un OCR. Respondes solo con el texto transcrito."},
                         {"role": "user", "content": [
                             {"type": "text", "text": PROMPT},
                             {"type": "image_url",
                              "image_url": {"url": "data:image/png;base64," + base64.b64encode(image).decode()}}]}]}
    try:
        answer = requests.post(URL, json=body, timeout=TIMEOUT, headers={"Authorization": f"Bearer {key}"})
    except requests.RequestException as error:
        raise VisionError(f"OpenRouter unreachable: {error}") from error
    if answer.status_code != 200:
        raise VisionError(f"OpenRouter answered {answer.status_code}: {answer.text[:200]}")
    try:
        data = answer.json()
        choice = data["choices"][0]
        text = choice["message"]["content"] or ""
        cost = Decimal(str((data.get("usage") or {}).get("cost") or 0))
    except (ValueError, KeyError, AttributeError, IndexError, TypeError, ArithmeticError) as error:
        raise VisionError(f"OpenRouter answer not understood: {answer.text[:200]}") from error
    # an empty transcription is a blank page only when the model finished normally, not a cut or failed answer
    if not text.strip() and choice.get("finish_reason") != "stop":
        raise VisionError(f"empty answer, finish_reason {choice.get('finish_reason')!r}")
    return text, cost


def fingerprint(page: pikepdf.Page) -> str | None:
    """The same for two pages only when both draw the same scanned images, byte for byte, with the same operators
    in the same place (an entity's typed header and footer around the scan included) and nothing else differs;
    None for a page without a scan, with annotations or drawing another document inside it."""
    if page.obj.get("/Annots"):
        return None
    try:
        ops = pikepdf.parse_content_stream(page)
    except pikepdf.PdfError:
        return None
    xobjects = page.resources.get("/XObject") or {}
    fonts = page.resources.get("/Font") or {}
    digest, images = hashlib.sha256(), 0
    for operands, op in ops:
        if str(op) == "Do":
            image = xobjects.get(str(operands[0]))
            if image is None or image.get("/Subtype") != "/Image":
                return None
            digest.update(hashlib.sha256(image.read_raw_bytes()).digest())
            images += 1
        elif str(op) == "Tf":
            font = fonts.get(str(operands[0]))
            digest.update(f"Tf {font.get('/BaseFont') if font is not None else None} {operands[1]};".encode())
        else:
            digest.update(f"{op} {[str(o) for o in operands]};".encode())
    return digest.hexdigest() if images else None


def fingerprints(path: Path) -> list[str | None]:
    try:
        with pikepdf.open(path) as pdf:
            return [fingerprint(page) for page in pdf.pages]
    except (pikepdf.PdfError, OSError):
        return []


def invisible_text_pages(path: Path) -> list[int]:
    """Scanned pages with the entity's own OCR as an invisible layer on top (text render mode 3): they have text,
    but only as good as that OCR ("[80]" where the scan says [30]), so they are transcribed like a bare scan."""
    found = []
    try:
        with pikepdf.open(path) as pdf:
            for n, page in enumerate(pdf.pages[:LAST_PAGE], 1):
                try:
                    ops = pikepdf.parse_content_stream(page)
                except pikepdf.PdfError:
                    continue
                if any(str(op) == "Tr" and operands and int(operands[0]) == 3 for operands, op in ops) \
                        and any(str(op) == "Do" for _, op in ops):
                    found.append(n)
    except (pikepdf.PdfError, OSError):
        return []
    return found


def known_pages(folder: Path, but: Path) -> dict[str, str]:
    """The transcribed pages of the obra's other files, by fingerprint."""
    known = {}
    for pdf in sorted(folder.rglob("*.pdf")):
        if pdf == but or not ia_path(pdf).exists():
            continue
        try:
            texts = text_of(ia_path(pdf)).split("\f")
        except TextError:
            continue
        for mark, text in zip(fingerprints(pdf), texts):
            if mark and text.strip():
                known.setdefault(mark, text)
    return known


def tesseract_page(path: Path, page: int) -> str:
    """Tesseract's text of one page, enough to tell a heading; empty when it cannot run."""
    with tempfile.TemporaryDirectory(prefix="probe-") as folder:
        try:
            image = render(path, page, Path(folder))
            done = subprocess.run(["tesseract", "stdin", "stdout", "-l", "spa"], input=image, capture_output=True,
                                  timeout=TIMEOUT)
        except (VisionError, OSError, subprocess.TimeoutExpired):
            return ""
    return done.stdout.decode("utf-8", "replace")


def is_bases(path: Path, probe: Callable[[Path, int], str] = tesseract_page) -> bool:
    """Whether a file unpacked from an archive is the bases: its name says so, or its first pages do."""
    if re.search(r"bases", path.name, re.I):
        return True
    try:
        # pdftotext ends with a form feed: the empty piece after it is no page
        pages = text_of(path).split("\f")[:-1]
    except TextError:
        return False
    for n, text in enumerate(pages[:2], 1):
        if BASES_COVER.search(text if text.strip() else probe(path, n)):
            return True
    return False


def transcribe(path: Path, key: str, ask: Callable[[str, bytes], tuple[str, Decimal]] = ask,
               render: Callable[[Path, int, Path], bytes] = render,
               charge: Callable[[Decimal], None] = lambda usd: None,
               known: dict[str, str] | None = None,
               probe: Callable[[Path, int], str] = tesseract_page) -> tuple[Path, Decimal, int, int]:
    """Write `<name>-ia.txt` for a PDF with image pages; returns it, its cost, the pages sent and the pages taken
    from `known` (transcriptions by fingerprint). Nothing is written unless every page to transcribe was
    transcribed; `charge` gets each page's cost as it is paid, also when a later page fails."""
    pages = text_of(path).split("\f")
    images = image_pages("\f".join(pages)) + invisible_text_pages(path)
    # pdftotext ends with a form feed: the empty piece after it is no page
    images = set(p for p in images if p < len(pages) or pages[p - 1].strip())
    if not images:
        raise VisionError("no image pages")
    marks = fingerprints(path) if known else []
    cost, sent, reused = Decimal(0), 0, 0
    general_from, skipped = None, []
    with tempfile.TemporaryDirectory(prefix="vision-") as folder, ThreadPoolExecutor(WORKERS) as pool:

        def take(batch):
            """The pages of a batch at once; each one paid is charged, also when another one of them failed."""
            nonlocal cost, sent, reused
            mark = lambda page: marks[page - 1] if page <= len(marks) else None
            asked = {page: pool.submit(lambda p: ask(key, render(path, p, Path(folder))), page)
                     for page in batch if not (mark(page) and mark(page) in known)}
            failed = None
            for page in batch:
                if page not in asked:
                    text = known[mark(page)]
                    reused += 1
                else:
                    try:
                        text, usd = asked[page].result()
                    except VisionError as error:
                        failed = failed or error
                        continue
                    charge(usd)
                    cost += usd
                    sent += 1
                pages[page - 1] = text.replace("\r\n", "\n").replace("\f", "\n").translate(HOMOGLYPHS).rstrip("\n") + "\n"
            if failed:
                raise failed

        # A batch is sent once WORKERS pages wait, so a heading or the proforma found in it may leave a few pages past
        # it paid for: their answers are kept, nothing is thrown away.
        page, batch, stop = 1, [], False
        while page <= len(pages) and not stop:
            first = page
            while page <= len(pages) and len(batch) < WORKERS:
                if general_from is not None:
                    if SPECIFIC.search(top(probe(path, page) if page in images else pages[page - 1])):
                        general_from = None
                    elif page - general_from > GENERAL_PAGES:
                        batch += skipped
                        general_from, skipped = None, []
                    elif page in images:
                        skipped.append(page)
                        page += 1
                        continue
                if page in images:
                    batch.append(page)
                page += 1
            take(batch)
            batch = []
            for q in range(first, page):
                if general_from is None and not skipped and q >= 2 and GENERAL.search(top(pages[q - 1])):
                    general_from = q
                elif general_from is not None and q > general_from and SPECIFIC.search(top(pages[q - 1])):
                    general_from = None  # the sección específica already in this batch
                done = "\f".join(pages[:q])
                if (at := requisitos.all_read_before(done)) is not None and done[:at].count("\f") < q:
                    stop = True
                    break
        if general_from is not None:
            take(skipped)
    out = ia_path(path)
    part = out.with_name(out.name + ".part")
    part.write_bytes("\f".join(pages).encode("utf-8"))
    part.replace(out)
    return out, cost, sent, reused


def api_key() -> str | None:
    return os.environ.get("OPENROUTER_API_KEY") or None


def check_tools() -> None:
    try:
        subprocess.run(["pdftoppm", "-v"], capture_output=True, timeout=30)
    except FileNotFoundError as error:
        raise ToolMissing("pdftoppm not found; install Poppler and put it on the PATH") from error
