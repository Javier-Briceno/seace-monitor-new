"""The text of a bases document: its PDF or DOCX, or the PDF and DOCX files inside its archive.

PDF text comes from Poppler's pdftotext in layout mode: a table keeps its rows and columns,
while the raw order can put a table before the title of its section.
"""

import re
import shutil
import subprocess
import zipfile
from pathlib import Path

from .archives import unpacked_folder

TEXT_SUFFIXES = {".pdf", ".docx"}
# Bases run to 100-200 pages; chapters I-IV, which hold every field read, end well before that.
LAST_PAGE = 150
# A page with fewer letters than this is an image: a scan, or a stamp on a scan.
MIN_PAGE_CHARS = 80
SCANNED_SHARE = 0.8


class TextError(Exception):
    """The file could not be turned into text."""


class ToolMissing(Exception):
    """pdftotext is not installed; nothing is wrong with the document."""


def pdftotext() -> str:
    found = shutil.which("pdftotext")
    if not found:
        raise ToolMissing("pdftotext not found; install Poppler and put it on the PATH")
    return found


def pdf_text(path: Path) -> str:
    """Pages are separated by form feeds."""
    try:
        done = subprocess.run([pdftotext(), "-enc", "UTF-8", "-layout", "-l", str(LAST_PAGE), str(path), "-"],
                              capture_output=True, timeout=180)
    except subprocess.TimeoutExpired as error:
        raise TextError(f"pdftotext took longer than {error.timeout} s") from error
    if done.returncode != 0 and not done.stdout:
        raise TextError(f"pdftotext failed: {done.stderr.decode('utf-8', 'replace').strip()[:200]}")
    return done.stdout.decode("utf-8", "replace")


def docx_text(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as z:
            xml = z.read("word/document.xml").decode("utf-8", "replace")
    except (zipfile.BadZipFile, KeyError) as error:
        raise TextError(f"not a readable DOCX: {error}") from error
    return re.sub(r"<[^>]+>", "", re.sub(r"</w:p>", "\n", xml))


def text_of(path: Path) -> str:
    return docx_text(path) if path.suffix.lower() == ".docx" else pdf_text(path)


def is_scanned(text: str) -> bool:
    """Most pages without text: a scan, even if a few pages (a stamp, a typed cover) carry text."""
    pages = text.split("\f")
    empty = sum(len(re.sub(r"\s", "", p)) < MIN_PAGE_CHARS for p in pages)
    return empty >= SCANNED_SHARE * len(pages)


def page_of(text: str, position: int) -> int:
    return text.count("\f", 0, position) + 1


def bases_files(ruta_local: str, contents: list[str]) -> list[Path]:
    """The PDF and DOCX files of a downloaded document: itself, or those unpacked from it.

    `contents` are the paths stored for the archive, relative to its unpacked folder.
    """
    path = Path(ruta_local)
    if path.suffix.lower() in TEXT_SUFFIXES:
        return [path]
    folder = unpacked_folder(path)
    return [folder / r for r in contents if Path(r).suffix.lower() in TEXT_SUFFIXES]
