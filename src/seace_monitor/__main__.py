"""Search SEACE, store new licitaciones, list and download their documents, write the daily report.

    python -m seace_monitor [--config config.toml] [--no-mail]
    python -m seace_monitor --plantilla <nid_proceso>
"""

import argparse
import sys
import time
from datetime import datetime

from . import config, db, mail, manual, report
from .download import DocumentError, download
from .ficha import FichaError, open_ficha, parse_deadline, parse_documents
from .locate import locate
from .search import LIMA, AccessError, SearchError, make_session, search
from .store import (
    document_done, document_failed, ficha_failed, fichas_to_read, mark_extractions_reported, mark_reported,
    pending_documents,
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
            page = open_ficha(session, result, row)
            documents = parse_documents(page)
            deadline = parse_deadline(page)
        except FichaError as error:
            ficha_failed(conn, nid, str(error))
            print(f"{line}  ficha failed: {error}")
            continue
        added = save_ficha(conn, nid, documents, deadline)
        print(f"{line}  documents: {len(documents)} ({added} new), offers until {deadline:%d/%m %H:%M}" if deadline
              else f"{line}  documents: {len(documents)} ({added} new), no offer deadline in the cronograma")


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


def main() -> int:
    parser = argparse.ArgumentParser(prog="seace_monitor")
    parser.add_argument("--config", default="config.toml")
    parser.add_argument("--no-mail", action="store_true", help="write the report but do not send it or mark anything")
    parser.add_argument("--plantilla", type=int, metavar="NID_PROCESO", help="write the manual extraction template of one obra and exit")
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
    try:
        for query in config.queries(cfg):
            run_search(conn, session, query)
        # Only the obras that go into today's report; documents of older obras
        # are fetched by the step that needs them.
        candidates = [i["nid_proceso"] for i in report.pending(
            conn, config.watched(cfg), config.download_dir(cfg), datetime.now(LIMA))]
        run_downloads(conn, session, config.download_dir(cfg), candidates)
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
