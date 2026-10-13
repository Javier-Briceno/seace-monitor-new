"""Sign-in without passwords: a link by mail to the addresses allowed, then a long session in that browser.

Tokens are random and only their SHA-256 is stored, so a copy of the database opens nothing.
"""

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta

import psycopg

LINK_MINUTES = 20
SESSION_DAYS = 90
# Links one address can ask for per hour; more and the form says the same but sends nothing.
LINKS_PER_HOUR = 5


def digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def allowed(correo: str, allowlist: list[str]) -> bool:
    return correo.strip().lower() in {a.strip().lower() for a in allowlist}


def new_link(conn: psycopg.Connection, correo: str, now: datetime) -> str | None:
    """A fresh sign-in token for this address, or None when it asked too often in the last hour."""
    correo = correo.strip().lower()
    recent = conn.execute("SELECT count(*) FROM web_accesos WHERE correo = %s AND creado_en > %s",
                          [correo, now - timedelta(hours=1)]).fetchone()[0]
    if recent >= LINKS_PER_HOUR:
        return None
    token = secrets.token_urlsafe(32)
    conn.execute("INSERT INTO web_accesos (token_hash, correo, creado_en, vence_en) VALUES (%s, %s, %s, %s)",
                 [digest(token), correo, now, now + timedelta(minutes=LINK_MINUTES)])
    return token


def link_is_valid(conn: psycopg.Connection, token: str, now: datetime) -> bool:
    row = conn.execute("SELECT 1 FROM web_accesos WHERE token_hash = %s AND usado_en IS NULL AND vence_en > %s",
                       [digest(token), now]).fetchone()
    return row is not None


def use_link(conn: psycopg.Connection, token: str, now: datetime) -> str | None:
    """Spend a sign-in token once and open a session; returns the session token, or None."""
    with conn.transaction():
        row = conn.execute(
            """UPDATE web_accesos SET usado_en = %s
               WHERE token_hash = %s AND usado_en IS NULL AND vence_en > %s RETURNING correo""",
            [now, digest(token), now]).fetchone()
        if row is None:
            return None
        session = secrets.token_urlsafe(32)
        conn.execute("INSERT INTO web_sesiones (token_hash, correo, csrf, creado_en, vence_en) VALUES (%s, %s, %s, %s, %s)",
                     [digest(session), row[0], secrets.token_urlsafe(24), now, now + timedelta(days=SESSION_DAYS)])
    return session


def session_of(conn: psycopg.Connection, token: str | None, now: datetime) -> dict | None:
    if not token:
        return None
    row = conn.execute("SELECT correo, csrf FROM web_sesiones WHERE token_hash = %s AND vence_en > %s",
                       [digest(token), now]).fetchone()
    return {"correo": row[0], "csrf": row[1]} if row else None


def end_session(conn: psycopg.Connection, token: str) -> None:
    conn.execute("DELETE FROM web_sesiones WHERE token_hash = %s", [digest(token)])


def same_csrf(session: dict, sent: str | None) -> bool:
    return bool(sent) and hmac.compare_digest(session["csrf"], sent)


def forget_old(conn: psycopg.Connection, now: datetime) -> None:
    conn.execute("DELETE FROM web_accesos WHERE vence_en < %s", [now - timedelta(days=1)])
    conn.execute("DELETE FROM web_sesiones WHERE vence_en < %s", [now])
