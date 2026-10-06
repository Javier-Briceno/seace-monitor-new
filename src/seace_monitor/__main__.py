"""Search SEACE, store new licitaciones, list and download their documents, write the daily report.

    python -m seace_monitor [--config config.toml] [--no-mail]
    python -m seace_monitor --plantilla <nid_proceso>
    python -m seace_monitor --desempaquetar
"""

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

from . import config, db, mail, manual, report
from .archives import ArchiveError, MachineError, unpack
from .download import DocumentError, download
from .ficha import FichaError, open_ficha, parse_deadline, parse_documents, parse_estados
from .locate import locate
from .search import LIMA, AccessError, SearchError, make_session, search_pages
from .store import (
    archives_to_unpack, contents_done, contents_failed, document_done, document_failed, ficha_failed,
    fichas_to_read, mark_extractions_reported, mark_reported, pending_documents, save_ficha,
    save_new_licitaciones,
)

PAUSE = 1  # seconds between requests to SEACE


def run_search(conn, session, query) -> None:
    print(f"{query.objeto} / {query.departamento} / {query.desde} to {query.hasta}")
    total_new = total_rows = 0
    for number, result in enumerate(search_pages(query, session), 1):
        if number == 1:
            print(f"  portal total {result.total}")
        for row in result.rows:
            row["departamentos"], row["ubicacion_fuente"] = locate(row["descripcion"])
        new = set(save_new_licitaciones(conn, result.rows))
        total_new += len(new)
        total_rows += len(result.rows)
        print(f"  page {number}: {len(result.rows)} rows, new: {len(new)}")
        read_fichas(conn, session, result, new)
    print(f"  new: {total_new}, already stored: {total_rows - total_new}")


def read_fichas(conn, session, result, new) -> None:
    # Fichas only open within this search's session and for the page loaded
    # last, so every row of this page still missing its bases is read now.
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
            page = open_ficha(session, result, row)
            documents = parse_documents(page)
            deadline = parse_deadline(page)
            estados = parse_estados(page)
        except FichaError as error:
            ficha_failed(conn, nid, str(error))
            print(f"{line}  ficha failed: {error}")
            continue
        added = save_ficha(conn, nid, documents, deadline, estados)
        until = f"offers until {deadline:%d/%m %H:%M}" if deadline else "no offer deadline in the cronograma"
        print(f"{line}  documents: {len(documents)} ({added} new), {until}, {'/'.join(estados)}")


def run_downloads(conn, session, root, nids) -> None:
    pending = pending_documents(conn, nids)
    print(f"downloads pending for {len(nids)} obras of the report: {len(pending)}")
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


def run_unpacking(conn, nids=None) -> None:
    """Unpack the downloaded archives of these obras that are not unpacked yet; None means every obra."""
    pending = archives_to_unpack(conn, nids)
    print(f"archives to unpack: {len(pending)}")
    for document in pending:
        path = Path(document["ruta_local"])
        try:
            files = unpack(path)
        except MachineError as error:
            # The archives are fine, so nothing is marked and a later run unpacks them.
            print(f"unpacking stopped, nothing marked: {error}")
            return
        except ArchiveError as error:
            contents_failed(conn, document["id"], str(error))
            print(f"  failed  {path.name}: {error}")
            continue
        contents_done(conn, document["id"], files)
        print(f"  unpacked {path} ({len(files)} files)")


def main() -> int:
    parser = argparse.ArgumentParser(prog="seace_monitor")
    parser.add_argument("--config", default="config.toml")
    parser.add_argument("--no-mail", action="store_true", help="write the report but do not send it or mark anything")
    parser.add_argument("--plantilla", type=int, metavar="NID_PROCESO", help="write the manual extraction template of one obra and exit")
    parser.add_argument("--desempaquetar", action="store_true", help="unpack every downloaded archive not unpacked yet and exit")
    args = parser.parse_args()

    cfg = config.load(args.config)
    proxy = config.proxy(cfg)
    session = make_session(proxy)
    print(f"route: {'VPN proxy ' + proxy if proxy else 'direct'}")
    conn = db.connect()
    for version in db.migrate(conn):
        print(f"migration applied: {version}")
    if args.plantilla:
        try:
            print(f"template written: {manual.write_template(conn, args.plantilla, config.extraction_dir(cfg))}")
        except manual.TemplateError as error:
            print(error, file=sys.stderr)
            return 1
        return 0
    if args.desempaquetar:
        run_unpacking(conn)
        return 0
    try:
        for query in config.queries(cfg):
            run_search(conn, session, query)
        # Only the obras that go into today's report; documents of older obras
        # are fetched by the step that needs them.
        candidates = [i["nid_proceso"] for i in report.pending(
            conn, config.watched(cfg), config.download_dir(cfg), datetime.now(LIMA))]
        run_downloads(conn, session, config.download_dir(cfg), candidates)
        run_unpacking(conn, candidates)
    except AccessError as error:
        print(f"stopped, SEACE unreachable; no attempts were counted: {error}", file=sys.stderr)
        return 1
    except SearchError as error:
        print(f"search failed: {error}", file=sys.stderr)
        return 1
    imported, problems = manual.import_ready(conn, config.extraction_dir(cfg))
    for name in imported:
        print(f"manual extraction imported: {name}")
    rep = report.build(conn, config.watched(cfg), config.download_dir(cfg), config.report_dir(cfg), problems=problems)
    print(f"\n{rep.text}\nreport files: {', '.join(str(f) for f in rep.files)}")
    if args.no_mail:
        print("not sent (--no-mail); nothing marked as reported")
        return 0
    try:
        to = mail.send(rep.text.splitlines()[0], rep.text, rep.files)
    except mail.MailError as error:
        print(f"{error}; the same obras go into tomorrow's report", file=sys.stderr)
        return 1
    mark_reported(conn, rep.nids)
    mark_extractions_reported(conn, rep.extraction_ids)
    print(f"sent to {', '.join(to)}; {len(rep.nids)} obras and {len(rep.extraction_ids)} extractions marked as reported")
    return 0


if __name__ == "__main__":
    sys.exit(main())
