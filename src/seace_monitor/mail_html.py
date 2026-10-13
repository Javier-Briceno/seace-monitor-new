"""The daily report as an HTML mail next to its text: one table of new obras, then the changes, each obra linked
to its page in the search tool. Mail clients only keep inline styles and tables, so the layout is built from them.
"""

import html
from datetime import datetime

from . import obra_page as op
from .report import TOP, change_lines, money
from .search import LIMA

INK, MUTED, RULE, ACCENT, PAPER = "#1d232a", "#5a626c", "#ece9e2", "#1c4f8a", "#f6f5f1"
FONT = "font-family:'Public Sans',-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;"


def what(item: dict) -> str:
    """What is built, short enough for one line of a mail."""
    from .web.data import sentence
    text = sentence(op.work(item))
    return text if len(text) <= 120 else text[:117].rsplit(" ", 1)[0] + "…"


def deadline(item: dict) -> str:
    days = item["dias_restantes"]
    when = "cierra hoy" if days == 0 else "cierra mañana" if days == 1 else f"cierra en {days} días"
    return f"{when}, {item['fecha_limite_ofertas'].astimezone(LIMA):%d/%m %H:%M}"


def link(web_url: str, nid: int, text: str) -> str:
    e = html.escape
    if not web_url:
        return e(text)
    return f'<a href="{e(web_url)}/obras/{nid}" style="color:{ACCENT};text-decoration:none;font-weight:600;">{e(text)}</a>'


def heading(text: str) -> str:
    return (f'<tr><td colspan="2" style="padding:28px 0 8px;{FONT}font-size:15px;font-weight:700;color:{INK};'
            f'border-bottom:1px solid {RULE};">{html.escape(text)}</td></tr>')


def row(left: str, sub: str, right: str = "", right_sub: str = "") -> str:
    e = html.escape
    return (f'<tr><td style="padding:12px 12px 12px 0;border-bottom:1px solid {RULE};{FONT}font-size:14px;color:{INK};">'
            f'{left}<div style="font-size:12.5px;color:{MUTED};padding-top:2px;">{sub}</div></td>'
            f'<td style="padding:12px 0;border-bottom:1px solid {RULE};{FONT}font-size:14px;color:{INK};'
            f'text-align:right;white-space:nowrap;vertical-align:top;">{e(right)}'
            f'<div style="font-size:12.5px;color:{MUTED};padding-top:2px;">{e(right_sub)}</div></td></tr>')


def summary_html(items: list[dict], now: datetime, watched: list[str], changed: list[dict] = (),
                 web_url: str = "", followed: frozenset[int] | set[int] = frozenset()) -> str:
    e = html.escape
    abiertas = [i for i in items if i["estado"] == "abierta"]
    rows = [heading(f"Obras nuevas abiertas: {len(abiertas)}")]
    if not abiertas:
        rows.append(row("Ninguna obra nueva desde el último informe.", ""))
    for i in abiertas[:TOP]:
        notes = [e(i["nomenclatura"])]
        if i["ubicacion"] == "sin ubicar":
            notes.append("sin ubicar")
        if i["reinicio_de"]:
            notes.append("reinicio de una convocatoria anterior")
        rows.append(row(link(web_url, i["nid_proceso"], op.place(i)), e(what(i)) + "<br>" + ", ".join(notes),
                        money(i["valor_referencial"], i["moneda"]), deadline(i)))
    if len(abiertas) > TOP:
        rows.append(row(f"Y {len(abiertas) - TOP} más en el buscador y en el CSV adjunto.", ""))
    mine = [o for o in changed if o["nid_proceso"] in followed]
    others = [o for o in changed if o["nid_proceso"] not in followed]
    for name, group in (("Cambios en tus obras seguidas", mine), ("Cambios en otras obras abiertas", others)):
        if not group:
            continue
        rows.append(heading(f"{name}: {len(group)}"))
        for o in group[:TOP]:
            rows.append(row(link(web_url, o["nid_proceso"], op.place(o)),
                            e(o["nomenclatura"]) + "<br>" + "<br>".join(e(c) for c in change_lines(o))))
        if len(group) > TOP:
            rows.append(row(f"Y {len(group) - TOP} más en el CSV de cambios.", ""))
    button = ("" if not web_url else
              f'<tr><td colspan="2" style="padding:28px 0 0;"><a href="{e(web_url)}" style="display:inline-block;'
              f'background:{ACCENT};color:#ffffff;{FONT}font-size:14px;font-weight:600;text-decoration:none;'
              f'padding:12px 20px;border-radius:6px;">Abrir el buscador</a></td></tr>')
    return f"""<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Informe SEACE</title></head><body style="margin:0;padding:0;background:{PAPER};">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{PAPER};"><tr><td align="center" style="padding:24px 12px;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:600px;background:#ffffff;border:1px solid #dcd9d1;border-radius:6px;">
<tr><td style="padding:24px 28px 28px;">
<div style="{FONT}font-size:13px;color:{MUTED};">Monitor SEACE</div>
<div style="{FONT}font-size:20px;font-weight:700;color:{INK};padding-top:4px;">Informe del {now.astimezone(LIMA):%d/%m/%Y}</div>
<div style="{FONT}font-size:13px;color:{MUTED};padding-top:4px;">{e(", ".join(d.title() for d in watched))}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0">{"".join(rows)}{button}</table>
</td></tr></table>
<div style="{FONT}font-size:12px;color:{MUTED};padding-top:12px;">La lista completa va en los archivos adjuntos.</div>
</td></tr></table></body></html>"""
