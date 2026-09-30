"""Download documents from SEACE's document store by their id.

Two requests per document, no session needed: the store first answers with a
path to the file (JSONP), then serves the file from that path.
"""

import json
import random
import re
from pathlib import Path

import requests

from .search import access_error

STORE = "https://alfprod.seace.gob.pe/alfresco"
# The store answers 201 when the file lives on SEACE's own servers instead.
STORE_ON_PREMISE = "https://prodcont2.seace.gob.pe/alfresco"

# An unknown id makes the store hang instead of answering, so the path request
# gets a short read timeout. Files can be hundreds of MB and get a long one.
PATH_TIMEOUT = (10, 20)
FILE_TIMEOUT = (10, 120)


class DocumentError(Exception):
    pass


def file_url(session: requests.Session, uuid: str) -> str:
    callback = f"c{random.randint(1, 100_000_000)}"
    try:
        response = session.get(
            f"{STORE}/service/osce/downloadDoc",
            params={"id": uuid, "doc": callback, "guest": "false"},
            timeout=PATH_TIMEOUT,
        )
        response.raise_for_status()
    except requests.Timeout as error:
        raise DocumentError(f"document store did not answer for this id: {error}") from error
    except requests.RequestException as error:
        raise access_error(session, error) or DocumentError(f"path request failed: {error}") from error

    wrapped = re.search(r"\((.*)\)", response.text, re.S)
    if not wrapped:
        raise DocumentError(f"unexpected answer from the document store: {response.text[:200]!r}")
    answer = json.loads(wrapped.group(1))
    result, path = str(answer.get("result")), answer.get("downloadUrl") or ""
    if result == "200" and path:
        return STORE + path
    if result == "201" and path:
        return STORE_ON_PREMISE + path
    raise DocumentError(f"document store answered {result}")


def save_file(session: requests.Session, url: str, target: Path) -> int:
    """Stream the file to target; return its size in bytes."""
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".part")
    try:
        with session.get(url, stream=True, timeout=FILE_TIMEOUT) as response:
            response.raise_for_status()
            with open(partial, "wb") as f:
                for chunk in response.iter_content(chunk_size=1 << 20):
                    f.write(chunk)
    except requests.RequestException as error:
        partial.unlink(missing_ok=True)
        raise access_error(session, error) or DocumentError(f"file download failed: {error}") from error
    partial.replace(target)
    return target.stat().st_size


def local_path(root: Path, document: dict) -> Path:
    name = re.sub(r"[^\w.-]+", "_", document["nombre_archivo"]).strip("_") or "documento"
    return root / str(document["nid_proceso"]) / f"{document['uuid']}_{name}"


def download(session: requests.Session, document: dict, root: Path) -> tuple[Path, int]:
    target = local_path(root, document)
    size = save_file(session, file_url(session, document["uuid"]), target)
    if size == 0:
        target.unlink()
        raise DocumentError("the document store sent an empty file")
    return target, size
