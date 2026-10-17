"""Find a section among the files of a bases document, with OCR for the image pages when needed.

A reader is a function from the text of one file to its result, a dict with `revisar`; the
result whose `revisar` is the reader's "not in this file" value sends the search on to the next
file. Files with text are read first; then, if no text held the section, at most a few files with
image pages are read from their OCRed copy, those named as bases first. A file with text and image pages that has
a model's transcription is read from it when the transcription reads everything the PDF's text read and more: the
section starts on a text page and goes on on a scanned one.

An image page read by a vision model (`<name>-ia.txt`, see ocr.ia_path) is read before Tesseract's copy. When both
copies hold the section, the values Tesseract read are kept next to the model's in `segunda_lectura`, with the
fields where both read a value and the values differ: those are checked on the page.
"""

from collections.abc import Callable
from pathlib import Path

from .bases_text import TextError, is_scanned, text_of
from .ocr import OcrError, ia_path, image_pages

SCANNED = "escaneado"
# Files of one bases document that are OCRed in search of a section.
OCR_FILES = 2


def second_reading(first: dict, second: dict | None, values: dict[str, Callable[[dict], object]], missing: str,
                   alike: dict[str, Callable[[object], object]] | None = None) -> dict:
    """Both readings' values, and the fields both read differently. `values` names each compared value and how
    to take it from a reading; `alike` gives what of a value is compared, where the rest is noise (spaces)."""
    alike = alike or {}
    if second is None or second["revisar"] == missing:
        return {"ia": None, "tesseract": None, "difieren": []}
    ia = {k: get(first) for k, get in values.items()}
    tesseract = {k: get(second) for k, get in values.items()}
    return {"ia": ia, "tesseract": tesseract,
            "difieren": [k for k in values if ia[k] not in (None, [], "") and tesseract[k] not in (None, [], "")
                         and alike.get(k, same)(ia[k]) != alike.get(k, same)(tesseract[k])]}


def same(value: object) -> object:
    return value


def fuller(whole: dict, part: dict, values: dict[str, Callable[[dict], object]]) -> bool:
    """The transcription's reading has every value the PDF text's has, and one more or no reason to look."""
    def filled(result: dict) -> set[str]:
        return {k for k, get in values.items() if get(result) not in (None, "", [])}
    return filled(part) <= filled(whole) and (filled(part) < filled(whole) or bool(part["revisar"] and not whole["revisar"]))


def transcribed(path: Path, pages: list[int], result: dict, read: Callable[[str], dict], missing: str,
                ocr: Callable[[Path, list[int]], Path] | None, values: dict | None, alike: dict | None) -> dict:
    """A reading of the model's transcription, with Tesseract's next to it when OCR is allowed."""
    second = None
    if ocr:
        try:
            second = read(text_of(ocr(path, pages)))
        except (OcrError, TextError):
            pass
    return {**result, "archivo": path.name, "ocr": True, "ia": True,
            "segunda_lectura": second_reading(result, second, values or {}, missing, alike)}


def read_files(files: list[Path], read: Callable[[str], dict], missing: str,
               ocr: Callable[[Path, list[int]], Path] | None = None,
               values: dict[str, Callable[[dict], object]] | None = None,
               alike: dict[str, Callable[[object], object]] | None = None) -> dict:
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
        pages = image_pages(text)
        if is_scanned(text):
            scanned.append(path)
        else:
            result = read(text)
            if result["revisar"] != missing:
                if pages and ia_path(path).exists():
                    whole = read(text_of(ia_path(path)))
                    if fuller(whole, result, values or {}):
                        return transcribed(path, pages, whole, read, missing, ocr, values, alike)
                return {**result, "archivo": path.name, "ocr": False}
        if pages:
            with_images.append((path, pages))
    # OCR costs minutes per file: the files named as bases first, and only a few of an archive's.
    readable = [f for f in sorted(with_images, key=lambda f: "BASE" not in f[0].name.upper())
                if ocr or ia_path(f[0]).exists()]
    recognized = 0
    for path, pages in readable:
        # a model's transcription is read at once, every file that has one
        if ia_path(path).exists():
            text = text_of(ia_path(path))
            result = read(text)
            if result["revisar"] != missing:
                return transcribed(path, pages, result, read, missing, ocr, values, alike)
            if path in scanned and not is_scanned(text):
                scanned.remove(path)
        # Tesseract, minutes a file, for a few files: those without a transcription, or whose transcription
        # missed the section
        if ocr is None or recognized >= OCR_FILES:
            continue
        recognized += 1
        try:
            text = text_of(ocr(path, pages))
        except (OcrError, TextError) as error:
            unreadable.append(f"{path.name}: {error}")
            continue
        result = read(text)
        if result["revisar"] != missing:
            return {**result, "archivo": path.name, "ocr": True}
        if path in scanned and not is_scanned(text):
            scanned.remove(path)  # recognized and searched: no longer an unread scan
    result = {**read(""), "ocr": False, "ocr_pendiente": bool(with_images) and ocr is None}
    result["archivo"] = scanned[0].name if scanned else ""
    if scanned:
        result["revisar"] = SCANNED
    elif unreadable:
        result["revisar"] = "ilegible: " + "; ".join(unreadable)[:300]
    elif not files:
        result["revisar"] = "sin PDF ni DOCX"
    return result
