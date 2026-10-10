"""A text layer for scanned bases: OCRmyPDF with Tesseract's Spanish model.

The OCRed copy is written next to the original as `<name>-ocr.pdf`; the original is never touched.
Only the pages the readers look at are recognized. Recognized text finds sections and words well,
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


def make_ocr(path: Path) -> Path:
    """The OCRed copy of a scanned PDF, made once; pages that already carry text are left as they are."""
    out = ocr_path(path)
    if out.exists():
        return out
    pages = min(page_count(path), LAST_PAGE)
    part = out.with_name(out.name + ".part")
    command = [ocrmypdf(), "-q", "-l", "spa", "--skip-text", "--pages", f"1-{pages}",
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
