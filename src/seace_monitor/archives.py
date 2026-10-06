"""Open ZIP, RAR and 7z documents with 7-Zip and list what they hold.

Each archive is unpacked into a folder next to it; an archive found inside is
unpacked too, down to MAX_DEPTH levels.
"""

import shutil
import subprocess
from pathlib import Path

ARCHIVE_SUFFIXES = {".zip", ".rar", ".7z"}
MAX_DEPTH = 3
# Bases are a few hundred MB at most; more than this unpacked is not a bases.
MAX_UNPACKED_BYTES = 5 * 1024**3
SEVEN_ZIP_DEFAULT = Path(r"C:\Program Files\7-Zip\7z.exe")


class ArchiveError(Exception):
    pass


def seven_zip() -> str:
    found = shutil.which("7z") or shutil.which("7zz")
    if found:
        return found
    if SEVEN_ZIP_DEFAULT.exists():
        return str(SEVEN_ZIP_DEFAULT)
    raise ArchiveError("7-Zip not found; install it or put 7z on the PATH")


def is_archive(path: Path) -> bool:
    return path.suffix.lower() in ARCHIVE_SUFFIXES


def unpacked_folder(archive: Path) -> Path:
    return archive.with_name(archive.name + "_contenido")


def run(args: list[str]) -> str:
    # A dummy password makes 7-Zip fail on protected archives instead of asking.
    result = subprocess.run(
        [seven_zip(), *args, "-pX", "-y", "-sccUTF-8"],
        capture_output=True, encoding="utf-8", errors="replace",
    )
    if result.returncode != 0:
        lines = [l for l in (result.stderr + result.stdout).splitlines() if "ERROR" in l or "Wrong password" in l]
        raise ArchiveError(lines[0].strip() if lines else f"7-Zip exited with {result.returncode}")
    return result.stdout


def unpacked_size(archive: Path) -> int:
    listing = run(["l", "-slt", str(archive)])
    return sum(int(l.split("=", 1)[1]) for l in listing.splitlines() if l.startswith("Size = ") and l[7:].strip())


def unpack(archive: Path, depth: int = 1) -> list[dict]:
    """Unpack archive next to itself; return every file it holds, nested archives included.

    Each file: ruta (path relative to the outer archive's folder), tamano_bytes,
    dentro_de (the archive it came out of, relative the same way; "" for the outer one),
    error (why a nested archive could not be opened, else None).
    """
    size = unpacked_size(archive)
    if size > MAX_UNPACKED_BYTES:
        raise ArchiveError(f"unpacks to {size / 1e9:.1f} GB, more than the limit")
    target = unpacked_folder(archive)
    if target.exists():
        shutil.rmtree(target)
    run(["x", str(archive), f"-o{target}"])

    root = target.resolve()
    files = []
    for path in sorted(p for p in target.rglob("*") if p.is_file()):
        if not path.resolve().is_relative_to(root):
            raise ArchiveError(f"{path.name} unpacked outside its folder")
        entry = {"ruta": path.relative_to(target).as_posix(), "tamano_bytes": path.stat().st_size,
                 "dentro_de": "", "error": None}
        files.append(entry)
        if not is_archive(path) or depth >= MAX_DEPTH:
            continue
        # A broken archive inside is noted on its own entry; the rest of the outer one stays usable.
        try:
            inner = unpack(path, depth + 1)
        except ArchiveError as error:
            entry["error"] = str(error)
            continue
        folder = entry["ruta"] + "_contenido"
        for f in inner:
            f["ruta"] = f"{folder}/{f['ruta']}"
            f["dentro_de"] = f"{folder}/{f['dentro_de']}" if f["dentro_de"] else entry["ruta"]
        files.extend(inner)
    return files
