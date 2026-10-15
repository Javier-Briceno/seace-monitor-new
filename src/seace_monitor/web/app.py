"""The search tool on the web: sign-in by mail link, the list with filters, one obra in full, follow, the bases.

    uvicorn --factory seace_monitor.web.app:default_app

Reads config.toml ([web] url and correos) and the same database and download folder as the monitor.
"""

import os
from collections.abc import Callable, Iterator
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode, urlsplit

import psycopg
from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .. import config as cfg
from .. import db, download, mail
from .. import obra_page as op
from ..search import LIMA, make_session
from . import auth, data

HERE = Path(__file__).parent
COOKIE = "sesion"
NAME = "Monitor SEACE"
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
    "Content-Security-Policy": ("default-src 'self'; style-src 'self' https://fonts.googleapis.com; "
                                "font-src https://fonts.gstatic.com; img-src 'self' data:; frame-ancestors 'none'; "
                                "form-action 'self'; base-uri 'none'"),
}


def create_app(settings: dict, connect: Callable[[], psycopg.Connection] = db.connect,
               send: Callable[..., list[str]] = mail.send, clock: Callable[[], datetime] = lambda: datetime.now(LIMA),
               resolve: Callable[[str], str] | None = None) -> FastAPI:
    """`resolve` turns a document's SEACE id into its download address, for files no longer on this server."""
    web = settings.get("web", {})
    base_url = (web.get("url") or "").rstrip("/")
    allowlist = list(web.get("correos") or [])
    watched = cfg.watched(settings)
    root = cfg.download_dir(settings)
    secure = base_url.startswith("https://")

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
    pages = Jinja2Templates(directory=HERE / "templates")
    pages.env.globals["nombre"] = NAME

    @app.middleware("http")
    async def headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.update(SECURITY_HEADERS)
        if request.url.path.startswith("/obras") or request.url.path == "/":
            response.headers["Cache-Control"] = "private, no-store"
        return response

    def conn_dep() -> Iterator[psycopg.Connection]:
        with connect() as conn:
            yield conn

    def session_dep(request: Request, conn: psycopg.Connection = Depends(conn_dep)) -> dict | None:
        # an address taken off the allowlist loses its open sessions too
        session = auth.session_of(conn, request.cookies.get(COOKIE), clock())
        return session if session and auth.allowed(session["correo"], allowlist) else None

    def to_login() -> RedirectResponse:
        return RedirectResponse("/entrar", status_code=303)

    @app.get("/entrar", response_class=HTMLResponse)
    def sign_in_form(request: Request):
        return pages.TemplateResponse(request, "entrar.html", {"paso": "pedir"})

    @app.post("/entrar", response_class=HTMLResponse)
    def sign_in_ask(request: Request, correo: str = Form(...), conn: psycopg.Connection = Depends(conn_dep)):
        correo = correo.strip().lower()[:200]
        now = clock()
        auth.forget_old(conn, now)
        if auth.allowed(correo, allowlist) and (token := auth.new_link(conn, correo, now)):
            send(f"Tu enlace para entrar a {NAME}",
                 f"Para entrar a {NAME}, abre este enlace. Vale {auth.LINK_MINUTES} minutos y sirve una sola vez:\n\n"
                 f"{base_url}/entrar/{token}\n\nSi no lo pediste, ignora este correo.\n", [], to=[correo])
        # the same answer either way, so the form does not tell who may enter
        return pages.TemplateResponse(request, "entrar.html", {"paso": "enviado", "correo": correo})

    @app.get("/entrar/{token}", response_class=HTMLResponse)
    def sign_in_confirm(request: Request, token: str, conn: psycopg.Connection = Depends(conn_dep)):
        # Opening the link only shows a button: mail scanners that follow links must not spend it.
        valid = auth.link_is_valid(conn, token, clock())
        return pages.TemplateResponse(request, "entrar.html", {"paso": "confirmar" if valid else "vencido",
                                                               "token": token})

    @app.post("/entrar/{token}")
    def sign_in(token: str, conn: psycopg.Connection = Depends(conn_dep)):
        session = auth.use_link(conn, token, clock(), allowlist)
        if session is None:
            return RedirectResponse(f"/entrar/{token}", status_code=303)
        response = RedirectResponse("/", status_code=303)
        response.set_cookie(COOKIE, session, max_age=auth.SESSION_DAYS * 86400, httponly=True, secure=secure,
                            samesite="lax")
        return response

    @app.post("/salir")
    def sign_out(request: Request, csrf: str = Form(""), conn: psycopg.Connection = Depends(conn_dep),
                 session: dict | None = Depends(session_dep)):
        # a form posted from another site must not sign anyone out: the cookie goes only with the right token
        if session is None:
            return to_login()
        if not auth.same_csrf(session, csrf):
            raise HTTPException(403)
        auth.end_session(conn, request.cookies[COOKIE])
        response = to_login()
        response.delete_cookie(COOKIE, httponly=True, secure=secure, samesite="lax")
        return response

    @app.get("/", response_class=HTMLResponse)
    def search(request: Request, conn: psycopg.Connection = Depends(conn_dep),
               session: dict | None = Depends(session_dep)):
        if session is None:
            return to_login()
        now = clock()
        params = request.query_params
        f = data.Filters.parse(params)
        followed = data.followed_by(conn, session["correo"])
        result = data.listing(op.obras(conn, watched, now, closed_too=f.cerradas), f, followed, now)

        def without(key: str, value: str | None = None) -> str:
            kept = [(k, v) for k, v in params.multi_items() if not (k == key and (value is None or v == value))]
            return "/?" + urlencode(kept) if kept else "/"
        return pages.TemplateResponse(request, "lista.html", {
            "f": f, "r": result, "sesion": session, "ordenes": data.ORDERS, "cierres": data.CLOSING,
            "publicadas": data.PUBLISHED, "tipos": data.OFFER_FILTER, "chips": f.chips(without),
            "grupos": dict(op.BUCKETS) | {"cerrada": "Cerradas"}, "proper": op.proper,
            "query": str(request.url.query)})

    @app.get("/obras/{nid}", response_class=HTMLResponse)
    def obra(request: Request, nid: int, conn: psycopg.Connection = Depends(conn_dep),
             session: dict | None = Depends(session_dep)):
        if session is None:
            return to_login()
        now = clock()
        found = next((o for o in op.obras(conn, watched, now, closed_too=True) if o["nid_proceso"] == nid), None)
        if found is None:
            raise HTTPException(404)
        followed = data.followed_by(conn, session["correo"])
        return pages.TemplateResponse(request, "obra.html", {
            "o": found, "s": data.summary(found, followed, now), "d": data.detail(found), "sesion": session,
            "historial": data.history(conn, nid), "documentos": data.documents(conn, nid),
            "cronograma": data.cronograma(conn, nid),
            "publicada": data.long_date(found["fecha_publicacion"], time=False), "volver": back_to_list(request)})

    @app.post("/obras/{nid}/seguir")
    def follow(nid: int, accion: str = Form(...), csrf: str = Form(""), volver: str = Form(""),
               conn: psycopg.Connection = Depends(conn_dep), session: dict | None = Depends(session_dep)):
        if session is None:
            return to_login()
        if not auth.same_csrf(session, csrf):
            raise HTTPException(403)
        if accion == "seguir":
            conn.execute("INSERT INTO seguidas (correo, nid_proceso) SELECT %s, nid_proceso FROM licitaciones "
                         "WHERE nid_proceso = %s ON CONFLICT DO NOTHING", [session["correo"], nid])
        else:
            conn.execute("DELETE FROM seguidas WHERE correo = %s AND nid_proceso = %s", [session["correo"], nid])
        # only paths of this site, never another host
        back = volver if volver.startswith("/") and not volver.startswith("//") else f"/obras/{nid}"
        return RedirectResponse(back, status_code=303)

    @app.get("/obras/{nid}/bases/{doc_id}/{name}")
    def bases_page(nid: int, doc_id: int, name: str, conn: psycopg.Connection = Depends(conn_dep),
                   session: dict | None = Depends(session_dep)):
        if session is None:
            return to_login()
        path = data.bases_file(conn, nid, doc_id, name, root)
        if path is None:
            raise HTTPException(404)
        return file_response(path, inline=True)

    @app.get("/obras/{nid}/documentos/{doc_id}")
    def document(nid: int, doc_id: int, conn: psycopg.Connection = Depends(conn_dep),
                 session: dict | None = Depends(session_dep)):
        if session is None:
            return to_login()
        path = data.document_path(conn, nid, doc_id, root)
        if path is not None:
            return file_response(path, inline=False)
        # Closed obras' files leave the server: ask SEACE where the file is now and send the browser there.
        uuid = data.document_uuid(conn, nid, doc_id)
        if uuid is None or resolve is None:
            raise HTTPException(404)
        try:
            url = resolve(uuid)
        except Exception:  # SEACE or the VPN not answering: the page says the file is archived
            raise HTTPException(404)
        if not url.startswith((download.STORE + "/", download.STORE_ON_PREMISE + "/")):
            raise HTTPException(404)
        return RedirectResponse(url, status_code=302)

    @app.exception_handler(404)
    def not_found(request: Request, _exc) -> Response:
        return pages.TemplateResponse(request, "error.html", {"titulo": "No está aquí",
                                      "texto": "La obra o el archivo no existe, o el archivo ya no está en el servidor "
                                               "y el SEACE no respondió. Prueba de nuevo en unos minutos."},
                                      status_code=404)

    return app


def back_to_list(request: Request) -> str:
    """The search the obra was opened from, so going back keeps its filters; only a page of this site."""
    referer = urlsplit(request.headers.get("referer", ""))
    if referer.netloc == request.url.netloc and referer.path == "/" and referer.query:
        return "/?" + referer.query
    return "/"


def file_response(path: Path, inline: bool) -> FileResponse:
    """PDFs open in the browser; anything else is downloaded, never rendered on this site."""
    name = op.UUID_PREFIX.sub("", path.name)
    if inline and path.suffix.lower() == ".pdf":
        return FileResponse(path, media_type="application/pdf", filename=name, content_disposition_type="inline")
    return FileResponse(path, media_type="application/octet-stream", filename=name)


def default_app() -> FastAPI:
    # the search tool may start before any monitor run has applied the newest migrations
    with db.connect() as conn:
        db.migrate(conn)
    settings = cfg.load(os.environ.get("SEACE_CONFIG", "config.toml"))
    proxy = cfg.proxy(settings)
    return create_app(settings, resolve=lambda uuid: download.file_url(make_session(proxy), uuid))

