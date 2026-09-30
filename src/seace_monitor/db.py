"""Postgres connection, using the same .env values as docker-compose.yml."""

import os

import psycopg
from dotenv import find_dotenv, load_dotenv


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
