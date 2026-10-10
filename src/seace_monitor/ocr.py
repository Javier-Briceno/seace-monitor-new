"""A text layer for scanned bases: OCRmyPDF with Tesseract's Spanish model.

The OCRed copy is written next to the original as `<name>-ocr.pdf`; the original is never touched.
Only the image pages among those the readers look at are recognized, which covers whole scans as
well as a scanned requerimiento inside a typed bases. Recognized text finds sections and words well,
but misreads digits now and then, so amounts read from it must be checked on the image.
"""

import os
import re
import shutil
import subprocess
from pathlib import Path

from .bases_text import LAST_PAGE, ToolMissing, tool_path

SUFFIX = "-ocr.pdf"
# About 4 s per page with 8 jobs; a 150-page bases takes 10 minutes.
TIMEOUT = 3600
# Fewer letters than this: a scanned page, maybe with the entity's typed header and footer (about 120).
IMAGE_PAGE = 400
# Exit 4: the output failed PDF validation (e.g. JPEG2000 images), but its text layer is usable.
USABLE_EXITS = {0, 4}


class OcrError(Exception):
    """This file could not be recognized."""


def ocrmypdf() -> str:
    found = shutil.which("ocrmypdf")
    if not found:
        raise ToolMissing("ocrmypdf not found; install it (uv tool install ocrmypdf) with Tesseract and its Spanish model")
    return found


def ocr_path(path: Path) -> Path:
    return path.with_name(path.stem + SUFFIX)


def page_count(path: Path) -> int:
    pdfinfo = shutil.which("pdfinfo")
    if not pdfinfo:
        raise ToolMissing("pdfinfo not found; install Poppler and put it on the PATH")
    done = subprocess.run([pdfinfo, tool_path(path)], capture_output=True, timeout=60)
    found = re.search(rb"^Pages:\s+(\d+)", done.stdout, re.M)
    if not found:
        raise OcrError(f"pdfinfo could not read the file: {done.stderr.decode('utf-8', 'replace').strip()[:200]}")
    return int(found.group(1))


def image_pages(text: str) -> list[int]:
    """Pages, among those the readers look at, that are images: no text, or only the entity's typed
    header and footer around a scanned page (a requerimiento inserted as a scan, a stamped cover)."""
    pages = text.split("\f")[:LAST_PAGE]
    return [n for n, page in enumerate(pages, 1) if len(re.sub(r"\s", "", page)) < IMAGE_PAGE]


def page_ranges(pages: list[int]) -> str:
    """[1, 2, 3, 7] -> '1-3,7'"""
    ranges, start = [], None
    for n, page in enumerate(pages):
        start = page if start is None else start
        if n + 1 == len(pages) or pages[n + 1] != page + 1:
            ranges.append(f"{start}-{page}" if page != start else str(page))
            start = None
    return ",".join(ranges)


def make_ocr(path: Path, pages: list[int]) -> Path:
    """The OCRed copy of a PDF, made once: these image pages get a text layer, the rest stays as it is."""
    out = ocr_path(path)
    if out.exists():
        return out
    pages = [p for p in pages if p <= min(page_count(path), LAST_PAGE)]
    if not pages:
        raise OcrError("no image pages to recognize")
    part = out.with_name(out.name + ".part")
    # --force-ocr: an image page with a typed header has some text, which --skip-text would keep as it is.
    command = [ocrmypdf(), "-q", "-l", "spa", "--force-ocr", "--pages", page_ranges(pages),
               # landscape tables come out upside down with the default threshold
               "--rotate-pages", "--rotate-pages-threshold", "2",
               "--jobs", str(os.cpu_count() or 1), "--output-type", "pdf", str(path.resolve()), str(part.resolve())]
    try:
        done = subprocess.run(command, capture_output=True, timeout=TIMEOUT)
    except subprocess.TimeoutExpired as error:
        part.unlink(missing_ok=True)
        raise OcrError(f"OCR took longer than {error.timeout} s") from error
    if done.returncode not in USABLE_EXITS or not part.exists():
        part.unlink(missing_ok=True)
        raise OcrError(f"ocrmypdf exit {done.returncode}: {done.stderr.decode('utf-8', 'replace').strip()[-300:]}")
    part.replace(out)
    return out
