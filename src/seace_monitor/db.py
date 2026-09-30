"""Postgres connection, using the same .env values as docker-compose.yml."""

import os

import psycopg
from dotenv import load_dotenv


def connect() -> psycopg.Connection:
    load_dotenv()
    return psycopg.connect(
        host=os.environ.get("POSTGRES_HOST", "127.0.0.1"),
        port=os.environ.get("POSTGRES_PORT", "5433"),
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
        dbname=os.environ["POSTGRES_DB"],
    )
