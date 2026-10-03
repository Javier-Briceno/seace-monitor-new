"""Postgres connection, using the same .env values as docker-compose.yml."""

import os
from pathlib import Path

import psycopg
from dotenv import find_dotenv, load_dotenv

MIGRATIONS = Path(__file__).parents[2] / "db" / "migrations"


def connect(dbname: str | None = None) -> psycopg.Connection:
    load_dotenv(find_dotenv(usecwd=True))  # the .env of the current folder, as docker compose does
    # autocommit: every conn.transaction() block is a real transaction and
    # commits on exit. Without it, the first plain SELECT opens an implicit
    # transaction, later blocks become savepoints, and closing loses them all.
    return psycopg.connect(
        autocommit=True,
        host=os.environ.get("POSTGRES_HOST", "127.0.0.1"),
        port=os.environ.get("POSTGRES_PORT", "5433"),
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
        dbname=dbname or os.environ["POSTGRES_DB"],
    )


def migrate(conn: psycopg.Connection, folder: Path = MIGRATIONS) -> list[str]:
    """Apply the numbered migrations not applied yet, in order; return their names.

    schema.sql is the starting point of every database, fresh or old, so a fresh
    database runs all migrations too. Each migration and its record commit together.
    """
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        " version text PRIMARY KEY, aplicado_en timestamptz NOT NULL DEFAULT now())"
    )
    done = {r[0] for r in conn.execute("SELECT version FROM schema_migrations").fetchall()}
    applied = []
    for path in sorted(folder.glob("*.sql")):
        if path.stem in done:
            continue
        with conn.transaction():
            conn.execute(path.read_text(encoding="utf-8"))
            conn.execute("INSERT INTO schema_migrations (version) VALUES (%s)", [path.stem])
        applied.append(path.stem)
    return applied
