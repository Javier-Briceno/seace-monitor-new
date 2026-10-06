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


def test_monitor_unpacks_a_downloaded_archive_and_stores_its_files(conn, tmp_path):
    from seace_monitor.__main__ import run_unpacking
    from seace_monitor.store import archives_to_unpack

    good = make_zip(tmp_path / "BASES.zip", {"bases.pdf": b"%PDF"})
    broken = tmp_path / "ANEXOS.rar"
    broken.write_bytes(b"not a rar")
    conn.execute("INSERT INTO licitaciones (nid_proceso, nomenclatura, entidad, objeto, descripcion) VALUES (1, 'LP-1', 'E', 'Obra', 'D')")
    ids = [conn.execute(
        "INSERT INTO documentos (nid_proceso, uuid, etapa, tipo, nombre_archivo, estado, ruta_local)"
        " VALUES (1, %s, 'Convocatoria', 'Bases', %s, 'done', %s) RETURNING id",
        [path.name, path.name, str(path)],
    ).fetchone()[0] for path in (good, broken)]

    run_unpacking(conn, [1])

    assert conn.execute("SELECT documento_id, ruta FROM documento_contenido").fetchall() == [(ids[0], "bases.pdf")]
    states = conn.execute("SELECT contenido_estado FROM documentos ORDER BY id").fetchall()
    assert states == [("done",), ("error",)]
    assert archives_to_unpack(conn) == []
