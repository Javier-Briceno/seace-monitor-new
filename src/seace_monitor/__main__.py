"""Search SEACE, store new licitaciones, re-read the tracked ones, download and read their bases, write the report.

    python -m seace_monitor [--config config.toml] [--no-mail]   # both parts, then the report
    python -m seace_monitor --avisos [--no-mail]                 # search, track and report; minutes
    python -m seace_monitor --lectura                            # download, OCR and read the bases; hours
    python -m seace_monitor --plantilla <nid_proceso>
    python -m seace_monitor --desempaquetar
"""

import argparse
import os
import sys
import time
from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from dotenv import find_dotenv, load_dotenv

from . import (config, cuantia, db, experiencia, factores, mail, manual, obra_page, objeto, personal, report, requisitos,
               stats, vision)
from .archives import ArchiveError, MachineError, unpack
from .bases_text import TextError, ToolMissing, bases_files, text_of
from .ocr import ia_path, image_pages, make_ocr, ocr_path, ocrmypdf
from .download import DocumentError, download
from .ficha import CronogramaError, FichaError, StaleTable, offer_deadline, open_ficha, parse_cronograma, parse_estados, read_documents
from .locate import place
from .search import LIMA, AccessError, Query, SearchError, make_session, search_pages, search_split
from .store import (
    archives_to_unpack, bases_to_extract, contents_done, contents_failed, document_done, document_failed, ficha_failed,
    fichas_to_read, link_restarts, locate_from_bases, mark_changes_reported, mark_extractions_reported, mark_reported,
    latest_reading, mark_stalled, newest_bases, open_since, pending_documents, save_extraction, save_ficha, save_new_licitaciones,
    tracked,
)

PAUSE = 1  # seconds between requests to SEACE
OCR_PER_RUN = 10  # scanned bases files; about 10 minutes each


def run_search(conn, session, query) -> list[tuple[int, Query]]:
    """Store new obras and read the fichas of new and still tracked ones.

    The range reaches back to the oldest tracked obra, so a long range is split
    where the portal would cut the list. Returns the fichas that need a session
    of their own, with the query that found them.
    """
    print(f"{query.objeto} / {query.departamento} / {query.desde} to {query.hasta}")
    total_new = total_rows = 0
    alone = []
    for number, result in enumerate(search_split(query, session), 1):
        for row in result.rows:
            row["departamentos"], row["ubicacion_fuente"] = place(row["descripcion"], row["entidad"],
                                                                  row["departamento_busqueda"])
        new = set(save_new_licitaciones(conn, result.rows))
        for old, restart in link_restarts(conn):
            print(f"  restart: {restart} restarts {old}")
        total_new += len(new)
        total_rows += len(result.rows)
        print(f"  page {number}: {len(result.rows)} rows of {result.total}, new: {len(new)}")
        alone += [(nid, query) for nid in read_fichas(conn, session, result, new)]
    print(f"  new: {total_new}, already stored: {total_rows - total_new}")
    return alone


def read_fichas(conn, session, result, new) -> list[int]:
    """Read the fichas of this results page; return those that need a session of their own."""
    # Fichas only open within this search's session and for the page loaded
    # last, so every row of this page still missing its bases or still tracked is read now.
    to_read = fichas_to_read(conn, [r["nid_proceso"] for r in result.rows])
    alone = []
    for row in result.rows:
        nid = row["nid_proceso"]
        mark = "new" if nid in new else "   "
        line = f"  {mark} {nid}  {row['nomenclatura']}  {'/'.join(row['departamentos']) or '?'}"
        if nid not in to_read:
            if nid in new:
                print(line)
            continue
        time.sleep(PAUSE)
        if not read_ficha(conn, session, result, row, line):
            alone.append(nid)
    return alone


def read_ficha(conn, session, result, row, line) -> bool:
    """Read and store one ficha. False when its document table must be read in a session of its own."""
    nid = row["nid_proceso"]
    try:
        page = open_ficha(session, result, row)
        documents = read_documents(session, page)
        try:
            cronograma = parse_cronograma(page)
        except CronogramaError as error:
            print(f"{line}  cronograma and deadline kept as stored: {error}")
            cronograma = None
        deadline = offer_deadline(cronograma or [])
        estados = parse_estados(page)
    except StaleTable:
        print(f"{line}  documents on several pages; read again in a new session")
        return False
    except FichaError as error:
        ficha_failed(conn, nid, str(error))
        print(f"{line}  ficha failed: {error}")
        return True
    added = save_ficha(conn, nid, documents, deadline, estados, cronograma)
    until = f"offers until {deadline:%d/%m %H:%M}" if deadline else "no offer deadline in the cronograma"
    print(f"{line}  documents: {len(documents)} ({added} new), {until}, {'/'.join(estados)}")
    return True


def read_alone(conn, proxy, alone) -> None:
    """Fichas whose document table runs over several pages, each opened first in a new session.

    The portal can answer a ficha's page requests with the table of a ficha paged
    earlier in the same session; the first ficha of a session gets its own table.
    """
    if alone:
        print(f"fichas read in a session of their own: {len(alone)}")
    for nid, query in alone:
        day = conn.execute(
            "SELECT (fecha_publicacion AT TIME ZONE 'America/Lima')::date FROM licitaciones WHERE nid_proceso = %s",
            [nid],
        ).fetchone()[0]
        line = f"  alone {nid}"
        session = make_session(proxy)
        try:
            result = next((r for r in search_pages(replace(query, desde=day, hasta=day), session)
                           if any(row["nid_proceso"] == nid for row in r.rows)), None)
        except AccessError:
            raise
        except SearchError as error:
            print(f"{line}  search failed: {error}")
            continue
        if result is None:
            ficha_failed(conn, nid, f"not found in the search of its publication day {day}")
            print(f"{line}  not found in the search of {day}")
            continue
        row = next(row for row in result.rows if row["nid_proceso"] == nid)
        time.sleep(PAUSE)
        if not read_ficha(conn, session, result, row, line):
            ficha_failed(conn, nid, "document table of another ficha, also in a new session")


def run_downloads(conn, session, root, nids) -> None:
    pending = pending_documents(conn, nids)
    print(f"downloads pending for {len(nids)} obras of the report or tracked: {len(pending)}")
    for document in pending:
        time.sleep(PAUSE)
        try:
            path, size = download(session, document, root)
        except DocumentError as error:
            document_failed(conn, document["id"], str(error))
            print(f"  failed  {document['nombre_archivo']}: {error}")
            continue
        document_done(conn, document["id"], path.as_posix(), size)
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


def run_extraction(conn, nids=None, ocr_budget=None) -> None:
    """Read section 1.4, the experiencia del postor, the personal clave, the factores de evaluación and section 1.3 of the
    downloaded bases of these obras not read yet by the current readers; None means every obra.

    Image pages of an obra's newest bases are OCRed when a section is not in the text, at most
    `ocr_budget` files per run (None: no limit); bases still waiting for OCR are left for the next run.
    """
    try:
        ocrmypdf()
    except ToolMissing as error:
        print(f"{error}; scanned bases wait")
        ocr_budget = 0
    made = []

    def counted_ocr(path, pages):
        if not ocr_path(path).exists():
            made.append(path)
            print(f"  OCR {path.name} ({len(pages)} pages)")
        return make_ocr(path, pages)

    def cuantia_of(document):
        found = document["cuantia_bases"] or document["valor_referencial"]
        return Decimal(found) if found is not None else None

    readers = (
        (cuantia.VERSION, lambda files, document, ocr: cuantia.read_files(files, document["valor_referencial"], ocr),
         lambda r: f"{r['revisar'] or r['cuantia']}  {', '.join(w['aviso'] for w in r['avisos'])}"),
        (experiencia.VERSION, lambda files, document, ocr: experiencia.read_files(files, cuantia_of(document), ocr),
         lambda r: f"{r['revisar'] or r['monto']}  {r['veces_cuantia'] or ''}"),
        (factores.VERSION, lambda files, document, ocr: factores.read_files(files, ocr),
         lambda r: f"{r['revisar'] or r['suma']}  {', '.join(w['aviso'] for w in r['avisos'])}"),
        (personal.VERSION, lambda files, document, ocr: personal.read_files(files, ocr),
         lambda r: f"{r['revisar'] or len(r['personal'])}  {', '.join(w['aviso'] for w in r['avisos'])}"),
        (objeto.VERSION, lambda files, document, ocr: objeto.read_files(files, document["descripcion"], ocr),
         lambda r: f"{r['revisar'] or (r['obra'] or '')[:60]}  {r['cui'] or ''}"),
    )
    for version, read, line in readers:
        pending = bases_to_extract(conn, version, nids)
        print(f"bases to read with {version}: {len(pending)}")
        for document in pending:
            may_ocr = document["newest"] and (ocr_budget is None or len(made) < ocr_budget)
            try:
                result = read(bases_files(document["ruta_local"], document["contents"]), document,
                              counted_ocr if may_ocr else None)
            except ToolMissing as error:
                print(f"reading stopped, nothing marked: {error}")
                return
            if result.pop("ocr_pendiente", False) and document["newest"]:
                print(f"  {document['nid_proceso']}  image pages, waits for OCR in the next run")
                continue
            # together: a reading marked done is never read again, so its location must not be left behind
            with conn.transaction():
                save_extraction(conn, document["id"], version, result, result["revisar"])
                if version == objeto.VERSION and document["newest"]:
                    locate_from_bases(conn, document["nid_proceso"], result)
            print(f"  {document['nid_proceso']}  {line(result)}{' (OCR)' if result['ocr'] else ''}")


def run_transcription(conn, cfg, nids) -> None:
    """Transcribe with the vision model the image pages of the newest bases of these obras that have none yet,
    until the month's spending reaches the cap of [vision] tope_mensual_usd. Without that setting or without
    OPENROUTER_API_KEY, scanned bases are read through Tesseract alone."""
    cap = (cfg.get("vision") or {}).get("tope_mensual_usd")
    key = vision.api_key()
    if cap is None or not key:
        print("vision model off" + ("" if cap is None else ": OPENROUTER_API_KEY not set") + "; scans go to Tesseract")
        return
    cap = Decimal(str(cap))
    for document in newest_bases(conn, nids):
        for path in bases_files(document["ruta_local"], document["contents"]):
            if path.suffix.lower() != ".pdf" or not path.exists() or ia_path(path).exists():
                continue
            try:
                if not image_pages(text_of(path)):
                    continue
            except TextError:
                continue
            now = datetime.now(LIMA)
            if (spent := vision.spent(conn, now)) >= cap:
                print(f"vision model: this month's {spent} USD reached the cap of {cap} USD; scans go to Tesseract")
                return
            try:
                # each page's cost is recorded as it is paid, also when a later page fails
                out, cost, pages = vision.transcribe(path, key,
                                                     charge=lambda usd: vision.add_spending(conn, now, usd, 1))
            except (vision.VisionError, TextError) as error:
                print(f"  vision {document['nid_proceso']} {path.name}: {error}; left for the next run")
                continue
            print(f"  vision {document['nid_proceso']} {path.name}: {pages} pages, {cost:.4f} USD")


def run_requirements(conn, cfg, nids=None, run_cap: Decimal | None = None) -> None:
    """Ask the model what each factor asks for its points and what profile each cargo needs, for the newest bases
    of these obras not asked yet (None: every obra), within the month's cap of [vision] tope_mensual_usd and, when
    given, `run_cap` USD for this run."""
    cap = (cfg.get("vision") or {}).get("tope_mensual_usd")
    key = vision.api_key()
    if cap is None or not key:
        return
    cap, run_spent = Decimal(str(cap)), Decimal(0)
    pending = [d for d in bases_to_extract(conn, requisitos.VERSION, nids) if d["newest"]]
    print(f"bases to ask with {requisitos.VERSION}: {len(pending)}")
    for document in pending:
        now = datetime.now(LIMA)

        def may_spend():
            return vision.spent(conn, now) < cap and (run_cap is None or run_spent < run_cap)

        def charge(usd):
            nonlocal run_spent
            run_spent += usd
            vision.add_spending(conn, now, usd, 0)

        try:
            result = requisitos.read_files(bases_files(document["ruta_local"], document["contents"]), key,
                                           latest_reading(conn, document["id"], "factores"),
                                           latest_reading(conn, document["id"], "personal"), charge=charge,
                                           may_spend=may_spend)
        except requisitos.SpendingCap:
            print("requisitos: spending cap reached; the rest waits for a later run")
            return
        except requisitos.RequisitosError as error:
            print(f"  {document['nid_proceso']}  {error}; left for the next run")
            continue
        save_extraction(conn, document["id"], requisitos.VERSION, result, result["revisar"])
        checked = sum(f["comprobado"] for f in result["factores"])
        print(f"  {document['nid_proceso']}  factores {checked}/{len(result['factores'])} checked, "
              f"personal {len(result['personal'])}{' checked' if result['personal_comprobado'] else ''}")


def run_notices(conn, cfg, proxy, session) -> None:
    """Store new obras and the changes of the tracked ones; no downloads, so it takes minutes."""
    alone = []
    for query in config.queries(cfg, open_since=open_since(conn)):
        alone += run_search(conn, session, query)
    read_alone(conn, proxy, alone)
    # Only after every search went through: an obra skipped by a failed search may have changed.
    for nid in mark_stalled(conn, datetime.now(LIMA)):
        print(f"stalled, no longer tracked: {nid}")


def run_reading(conn, cfg, session, ocr_budget) -> None:
    """Download, unpack and read the documents of the obras not reported yet and the tracked ones,
    whose new documents (bases integradas, absolución) are needed; closed obras are left alone.
    Readings are reported by the next notices run.
    """
    candidates = [i["nid_proceso"] for i in report.pending(
        conn, config.watched(cfg), config.download_dir(cfg), datetime.now(LIMA))]
    candidates = sorted(set(candidates) | set(tracked(conn)))
    run_downloads(conn, session, config.download_dir(cfg), candidates)
    run_unpacking(conn, candidates)
    # before the readers: a bases read once is not read again by the same reader versions
    run_transcription(conn, cfg, candidates)
    run_extraction(conn, candidates, ocr_budget)
    run_requirements(conn, cfg, candidates)


def main() -> int:
    parser = argparse.ArgumentParser(prog="seace_monitor")
    parser.add_argument("--config", default="config.toml")
    parser.add_argument("--no-mail", action="store_true", help="write the report but do not send it or mark anything")
    parser.add_argument("--plantilla", type=int, metavar="NID_PROCESO", help="write the manual extraction template of one obra and exit")
    parser.add_argument("--desempaquetar", action="store_true", help="unpack every downloaded archive not unpacked yet and exit")
    parser.add_argument("--extraer", action="store_true", help="read cuantía, experiencia, personal clave and factores of every downloaded bases not read yet and exit")
    parser.add_argument("--pagina", action="store_true", help="write the phone page of the obras open for offers and exit")
    parser.add_argument("--requisitos", type=Decimal, metavar="USD",
                        help="ask the model for factor requirements and personal profiles of every bases not asked yet, "
                             "spending at most USD in this run, and exit")
    part = parser.add_mutually_exclusive_group()
    part.add_argument("--avisos", action="store_true", help="search, track and send the report; bases read by an earlier --lectura show up in it")
    part.add_argument("--lectura", action="store_true", help="download, unpack, OCR and read the bases of the reported and tracked obras; no report")
    parser.add_argument("--estadisticas", action="store_true",
                        help="print how the open obras' bases were read and what the vision model cost, and exit")
    parser.add_argument("--fallo", metavar="UNIT", help="mail that this run failed, with the log read from stdin, and exit")
    args = parser.parse_args()

    if args.fallo:
        # Before the database and the VPN: either may be what failed.
        load_dotenv(find_dotenv(usecwd=True))
        log = sys.stdin.read()[-20000:]
        try:
            mail.send(f"SEACE monitor: {args.fallo} falló", f"La corrida {args.fallo} terminó con error.\n\n{log}", [])
        except mail.MailError as error:
            print(error, file=sys.stderr)
            return 1
        return 0

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
    if args.estadisticas:
        print(stats.text(conn))
        return 0
    if args.desempaquetar:
        run_unpacking(conn)
        return 0
    if args.extraer:
        run_extraction(conn)
        return 0
    if args.requisitos is not None:
        run_requirements(conn, cfg, run_cap=args.requisitos)
        return 0
    if args.pagina:
        print(f"page written: {obra_page.write(conn, config.watched(cfg), config.report_dir(cfg), datetime.now(LIMA))}")
        return 0
    try:
        if not args.lectura:
            run_notices(conn, cfg, proxy, session)
        if not args.avisos:
            run_reading(conn, cfg, session, OCR_PER_RUN)
    except AccessError as error:
        print(f"stopped, SEACE unreachable; no attempts were counted: {error}", file=sys.stderr)
        return 1
    except SearchError as error:
        print(f"search failed: {error}", file=sys.stderr)
        return 1
    if args.lectura:
        return 0
    imported, problems = manual.import_ready(conn, config.extraction_dir(cfg))
    for name in imported:
        print(f"manual extraction imported: {name}")
    rep = report.build(conn, config.watched(cfg), config.download_dir(cfg), config.report_dir(cfg), problems=problems,
                       web_url=(cfg.get("web", {}).get("url") or "").rstrip("/"),
                       recipients=[a.strip() for a in os.environ.get("REPORT_TO", "").split(",") if a.strip()])
    rep.files.append(obra_page.write(conn, config.watched(cfg), config.report_dir(cfg), datetime.now(LIMA)))
    print(f"\n{rep.text}\nreport files: {', '.join(str(f) for f in rep.files)}")
    if args.no_mail:
        print("not sent (--no-mail); nothing marked as reported")
        return 0
    try:
        to = mail.send(rep.text.splitlines()[0], rep.text, rep.files, html=rep.html)
    except mail.MailError as error:
        print(f"{error}; the same obras go into tomorrow's report", file=sys.stderr)
        return 1
    mark_reported(conn, rep.nids)
    mark_extractions_reported(conn, rep.extraction_ids)
    mark_changes_reported(conn, rep.change_ids)
    print(f"sent to {', '.join(to)}; {len(rep.nids)} obras, {len(rep.extraction_ids)} extractions and "
          f"{len(rep.change_ids)} changes marked as reported")
    return 0


if __name__ == "__main__":
    sys.exit(main())
