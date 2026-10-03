"""Runs against the test database (see conftest.py), which is already migrated."""

from seace_monitor import db


def test_migrations_are_recorded(conn):
    versions = [r[0] for r in conn.execute("SELECT version FROM schema_migrations ORDER BY version")]
    assert versions == [p.stem for p in sorted(db.MIGRATIONS.glob("*.sql"))]


def test_second_migrate_applies_nothing(conn):
    assert db.migrate(conn) == []


def test_new_migration_is_applied_once(conn, tmp_path):
    (tmp_path / "900_probe.sql").write_text("CREATE TABLE probe (x int);", encoding="utf-8")
    assert db.migrate(conn, tmp_path) == ["900_probe"]
    assert db.migrate(conn, tmp_path) == []
    assert conn.execute("SELECT to_regclass('probe')").fetchone()[0] == "probe"


def test_failing_migration_leaves_no_record(conn, tmp_path):
    (tmp_path / "901_broken.sql").write_text("CREATE TABLE half (x int); SELECT nonsense;", encoding="utf-8")
    try:
        db.migrate(conn, tmp_path)
    except Exception:
        pass
    assert conn.execute("SELECT count(*) FROM schema_migrations WHERE version = '901_broken'").fetchone()[0] == 0
    assert conn.execute("SELECT to_regclass('half')").fetchone()[0] is None
