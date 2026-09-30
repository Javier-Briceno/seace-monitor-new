"""Search SEACE, store new licitaciones, list their documents and download them.

    python -m seace_monitor [--config config.toml]
"""

import argparse
import sys
import time

from . import config, db
from .download import DocumentError, download
from .ficha import FichaError, open_ficha, parse_documents
from .locate import locate
from .search import AccessError, SearchError, make_session, search
from .store import (
    document_done, document_failed, ficha_failed, fichas_to_read, pending_documents,
    save_ficha, save_new_licitaciones,
)

PAUSE = 1  # seconds between requests to SEACE


def run_search(conn, session, query) -> None:
    print(f"{query.objeto} / {query.departamento} / {query.desde} to {query.hasta}")
    result = search(query, session)
    print(f"  portal total {result.total}, rows on this page {len(result.rows)}")
    if result.total > len(result.rows):
        print(f"  warning: only the first page is read, {result.total - len(result.rows)} rows not collected")
    for row in result.rows:
        row["departamentos"], row["ubicacion_fuente"] = locate(row["descripcion"])
    new = set(save_new_licitaciones(conn, result.rows))
    print(f"  new: {len(new)}, already stored: {len(result.rows) - len(new)}")

    # Fichas only open within this search's session, so every row still
    # missing its bases is read now, not only the new ones.
    to_read = fichas_to_read(conn, [r["nid_proceso"] for r in result.rows])
    for row in result.rows:
        nid = row["nid_proceso"]
        mark = "new" if nid in new else "   "
        line = f"  {mark} {nid}  {row['nomenclatura']}  {'/'.join(row['departamentos']) or '?'}"
        if nid not in to_read:
            print(line)
            continue
        time.sleep(PAUSE)
        try:
            documents = parse_documents(open_ficha(session, result, row))
        except FichaError as error:
            ficha_failed(conn, nid, str(error))
            print(f"{line}  ficha failed: {error}")
            continue
        added = save_ficha(conn, nid, documents)
        print(f"{line}  documents: {len(documents)} ({added} new)")


def run_downloads(conn, session, root) -> None:
    pending = pending_documents(conn)
    print(f"downloads pending: {len(pending)}")
    for document in pending:
        time.sleep(PAUSE)
        try:
            path, size = download(session, document, root)
        except DocumentError as error:
            document_failed(conn, document["id"], str(error))
            print(f"  failed  {document['nombre_archivo']}: {error}")
            continue
        document_done(conn, document["id"], str(path), size)
        print(f"  done    {path} ({size / 1e6:.1f} MB)")


def main() -> int:
    parser = argparse.ArgumentParser(prog="seace_monitor")
    parser.add_argument("--config", default="config.toml")
    args = parser.parse_args()

    cfg = config.load(args.config)
    proxy = config.proxy(cfg)
    session = make_session(proxy)
    print(f"route: {'VPN proxy ' + proxy if proxy else 'direct'}")
    conn = db.connect()
    try:
        for query in config.queries(cfg):
            run_search(conn, session, query)
        run_downloads(conn, session, config.download_dir(cfg))
    except AccessError as error:
        print(f"stopped, SEACE unreachable; no attempts were counted: {error}", file=sys.stderr)
        return 1
    except SearchError as error:
        print(f"search failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
