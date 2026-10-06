import subprocess
import zipfile

import pytest

from seace_monitor.archives import ArchiveError, seven_zip, unpack, unpacked_folder

try:
    seven_zip()
except ArchiveError:
    pytest.skip("7-Zip not installed", allow_module_level=True)


def pack(archive, *args):
    subprocess.run([seven_zip(), "a", str(archive), *map(str, args)], check=True, capture_output=True)


def make_zip(path, files: dict[str, bytes]):
    with zipfile.ZipFile(path, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
    return path


def test_files_are_listed_with_their_size(tmp_path):
    archive = make_zip(tmp_path / "BASES.zip", {"bases.pdf": b"%PDF 1234", "anexos/anexo 1.docx": b"xx"})
    files = unpack(archive)
    assert [(f["ruta"], f["tamano_bytes"], f["dentro_de"]) for f in files] == [
        ("anexos/anexo 1.docx", 2, ""),
        ("bases.pdf", 9, ""),
    ]
    assert (unpacked_folder(archive) / "bases.pdf").read_bytes() == b"%PDF 1234"


def test_archive_inside_is_opened_too(tmp_path):
    inner = make_zip(tmp_path / "planos.zip", {"plano 1.pdf": b"p1"})
    outer = make_zip(tmp_path / "BASES.zip", {"bases.pdf": b"b", "planos.zip": inner.read_bytes()})
    files = {f["ruta"]: f["dentro_de"] for f in unpack(outer)}
    assert files == {
        "bases.pdf": "",
        "planos.zip": "",
        "planos.zip_contenido/plano 1.pdf": "planos.zip",
    }


def test_seven_z_and_unicode_names(tmp_path):
    source = tmp_path / "src"
    source.mkdir()
    (source / "Expediente Técnico.pdf").write_bytes(b"e")
    archive = tmp_path / "BASES.7z"
    pack(archive, source / "*")
    assert [f["ruta"] for f in unpack(archive)] == ["Expediente Técnico.pdf"]


def test_broken_archive_is_an_error(tmp_path):
    archive = tmp_path / "BASES.rar"
    archive.write_bytes(b"not an archive")
    with pytest.raises(ArchiveError):
        unpack(archive)


def test_broken_archive_inside_is_noted_and_the_rest_kept(tmp_path):
    outer = make_zip(tmp_path / "BASES.zip", {"bases.pdf": b"b", "roto.zip": b"not a zip"})
    files = {f["ruta"]: f["error"] for f in unpack(outer)}
    assert files["bases.pdf"] is None
    assert files["roto.zip"]


def test_password_protected_archive_is_an_error(tmp_path):
    source = tmp_path / "bases.pdf"
    source.write_bytes(b"secret")
    archive = tmp_path / "BASES.7z"
    pack(archive, source, "-psecreto")
    with pytest.raises(ArchiveError):
        unpack(archive)
