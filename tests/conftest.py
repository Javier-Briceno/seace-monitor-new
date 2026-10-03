import os
from pathlib import Path

import psycopg
import pytest

from seace_monitor import db

SCHEMA = Path(__file__).parents[1] / "db" / "schema.sql"


@pytest.fixture(scope="session")
def test_dbname():
    """A separate database, rebuilt from schema.sql and the migrations once per test run."""
    try:
        admin = db.connect()
    except psycopg.OperationalError:
        pytest.skip("Postgres not running (docker compose up -d)")
    name = os.environ["POSTGRES_DB"] + "_test"
    with admin:
        admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        admin.execute(f'CREATE DATABASE "{name}"')
    with db.connect(name) as conn:
        conn.execute(SCHEMA.read_text(encoding="utf-8"))
        db.migrate(conn)
    return name


@pytest.fixture
def conn(test_dbname):
    # force_rollback: nothing a test writes is kept, and transactions inside
    # the code under test become savepoints within this one.
    with db.connect(test_dbname) as connection, connection.transaction(force_rollback=True):
        yield connection
