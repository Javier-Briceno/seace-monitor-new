"""Find a section among the files of a bases document, with OCR for the image pages when needed.

A reader is a function from the text of one file to its result, a dict with `revisar`; the
result whose `revisar` is the reader's "not in this file" value sends the search on to the next
file. Files with text are read first; then, if no text held the section, at most a few files with
image pages are read from their OCRed copy, those named as bases first.
"""

from collections.abc import Callable
from pathlib import Path

from .bases_text import TextError, is_scanned, text_of
from .ocr import OcrError, image_pages

SCANNED = "escaneado"
# Files of one bases document that are OCRed in search of a section.
OCR_FILES = 2


def read_files(files: list[Path], read: Callable[[str], dict], missing: str,
               ocr: Callable[[Path, list[int]], Path] | None = None) -> dict:
    """The reading of the first file that holds the section, with `archivo` and `ocr` (read from
    an OCRed copy). Without it: `revisar` says why (a scan, unreadable files, no PDF or DOCX), and
    `ocr_pendiente` that OCR could still find it but none was allowed.
    """
    scanned, with_images, unreadable = [], [], []
    for path in files:
        try:
            text = text_of(path)
        except TextError as error:
            unreadable.append(f"{path.name}: {error}")
            continue
        if is_scanned(text):
            scanned.append(path)
        else:
            result = read(text)
            if result["revisar"] != missing:
                return {**result, "archivo": path.name, "ocr": False}
        if pages := image_pages(text):
            with_images.append((path, pages))
    # OCR costs minutes per file: the files named as bases first, and only a few of an archive's.
    for path, pages in sorted(with_images, key=lambda f: "BASE" not in f[0].name.upper())[:OCR_FILES if ocr else 0]:
        try:
            text = text_of(ocr(path, pages))
        except (OcrError, TextError) as error:
            unreadable.append(f"{path.name}: {error}")
            continue
        result = read(text)
        if result["revisar"] != missing:
            return {**result, "archivo": path.name, "ocr": True}
    result = {**read(""), "ocr": False, "ocr_pendiente": bool(with_images) and ocr is None}
    result["archivo"] = scanned[0].name if scanned else ""
    if scanned:
        result["revisar"] = SCANNED
    elif unreadable:
        result["revisar"] = "ilegible: " + "; ".join(unreadable)[:300]
    elif not files:
        result["revisar"] = "sin PDF ni DOCX"
    return result
