"""Download logic against a fake session; no network."""

from pathlib import Path

import pytest
import requests

from seace_monitor.download import STORE, STORE_ON_PREMISE, DocumentError, download, file_url, local_path
from seace_monitor.search import AccessError, make_session

UUID = "593ed77a-87d6-4439-b4ec-5dc915202820"


class FakeResponse:
    def __init__(self, text="", content=b"", status=200):
        self.text, self.content, self.status_code = text, content, status

    def raise_for_status(self):
        if self.status_code >= 400:
            error = requests.HTTPError(f"{self.status_code}")
            error.response = self
            raise error

    def iter_content(self, chunk_size):
        yield self.content

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeSession:
    """Answers the path request with `path_answer`, then the file request with `file`."""

    def __init__(self, path_answer, file=None):
        self.path_answer, self.file = path_answer, file
        self.proxies = {}

    def get(self, url, **kwargs):
        if url.endswith("/downloadDoc"):
            if isinstance(self.path_answer, Exception):
                raise self.path_answer
            return self.path_answer
        self.file_url = url
        return self.file


def jsonp(result, path="/service/api/node/content/x.pdf?a=true&alf_ticket=T"):
    return FakeResponse(f'c1(\n {{"result":"{result}", "downloadUrl":"{path}"}}\n);')


def test_path_answer_200_points_to_the_cloud_store():
    assert file_url(FakeSession(jsonp("200")), UUID).startswith(STORE + "/service/api/")


def test_path_answer_201_points_to_the_on_premise_store():
    assert file_url(FakeSession(jsonp("201")), UUID).startswith(STORE_ON_PREMISE + "/service/api/")


def test_other_result_is_a_document_error():
    with pytest.raises(DocumentError, match="204"):
        file_url(FakeSession(jsonp("204", "")), UUID)


def test_hanging_store_is_a_document_error_not_an_access_error():
    with pytest.raises(DocumentError, match="did not answer"):
        file_url(FakeSession(requests.ReadTimeout("read timed out")), UUID)


def test_forbidden_is_an_access_error():
    with pytest.raises(AccessError, match="403"):
        file_url(FakeSession(FakeResponse(status=403)), UUID)


def test_dead_proxy_is_an_access_error():
    with pytest.raises(AccessError, match="VPN proxy"):
        file_url(make_session("http://127.0.0.1:9"), UUID)


def test_file_is_saved_under_the_licitacion(tmp_path):
    document = {"nid_proceso": 1253675, "uuid": UUID, "nombre_archivo": "BASES ESTANDAR.pdf"}
    path, size = download(FakeSession(jsonp("200"), FakeResponse(content=b"%PDF-1.4 ...")), document, tmp_path)
    assert path == tmp_path / "1253675" / f"{UUID}_BASES_ESTANDAR.pdf"
    assert path.read_bytes() == b"%PDF-1.4 ..."
    assert size == 12
    assert not list(tmp_path.rglob("*.part"))


def test_empty_file_is_an_error(tmp_path):
    document = {"nid_proceso": 1, "uuid": UUID, "nombre_archivo": "a.pdf"}
    with pytest.raises(DocumentError, match="empty"):
        download(FakeSession(jsonp("200"), FakeResponse(content=b"")), document, tmp_path)
    assert not any(tmp_path.rglob("*.pdf"))


def test_odd_file_names_become_safe():
    document = {"nid_proceso": 1, "uuid": UUID, "nombre_archivo": "BASES EL PROVENIR OK..pdf"}
    assert local_path(Path("data"), document).name == f"{UUID}_BASES_EL_PROVENIR_OK..pdf"
