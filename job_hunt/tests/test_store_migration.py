"""The version 1 -> 2 migration.

`init_db` used to be nothing but CREATE TABLE IF NOT EXISTS, which cannot add
a column to a table that already exists. These tests exist because the first
person to run the new code will have a database full of rows.
"""
from src.store.db import connect
from src.store.schema import SCHEMA_VERSION, init_db

# The exact version-1 DDL, frozen here. Do not update it when schema.py
# changes — the point is to reproduce a database written by the old code.
_V1_DDL = """
CREATE TABLE user (
    id INTEGER PRIMARY KEY, name TEXT NOT NULL, email TEXT,
    last_seen_run_id INTEGER, created_at TEXT NOT NULL);
CREATE TABLE run (
    id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES user(id),
    started_at TEXT NOT NULL, finished_at TEXT,
    status TEXT NOT NULL CHECK (status IN ('RUNNING','OK','FAILED')),
    scraped INTEGER NOT NULL DEFAULT 0, kept INTEGER NOT NULL DEFAULT 0);
CREATE TABLE company (
    id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES user(id),
    name TEXT NOT NULL, fingerprint TEXT NOT NULL,
    user_state TEXT NOT NULL DEFAULT 'NONE',
    first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL,
    UNIQUE (user_id, fingerprint));
CREATE TABLE role (
    id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES user(id),
    company_id INTEGER NOT NULL REFERENCES company(id),
    title TEXT NOT NULL, url TEXT NOT NULL, url_normalised TEXT NOT NULL,
    location TEXT, salary TEXT, platform TEXT, posted_date TEXT,
    description TEXT, description_captured INTEGER NOT NULL DEFAULT 0,
    match_score INTEGER, band TEXT, reason TEXT,
    matched TEXT NOT NULL DEFAULT '[]', gaps TEXT NOT NULL DEFAULT '[]',
    first_seen_run_id INTEGER NOT NULL REFERENCES run(id),
    last_seen_run_id INTEGER NOT NULL REFERENCES run(id),
    UNIQUE (user_id, url_normalised));
"""


def _v1_database(path):
    """A version-1 database with one of everything already in it."""
    conn = connect(path)
    conn.executescript(_V1_DDL)
    conn.execute("PRAGMA user_version = 1")
    conn.execute("INSERT INTO user (name, created_at) VALUES ('G', '2026-01-01')")
    conn.execute("INSERT INTO run (user_id, started_at, status, scraped, kept)"
                 " VALUES (1, '2026-01-01', 'OK', 3, 2)")
    conn.execute("INSERT INTO company (user_id, name, fingerprint,"
                 " first_seen_at, last_seen_at)"
                 " VALUES (1, 'Acme', 'acme', '2026-01-01', '2026-01-01')")
    conn.execute("INSERT INTO role (user_id, company_id, title, url,"
                 " url_normalised, first_seen_run_id, last_seen_run_id)"
                 " VALUES (1, 1, 'Data Engineer', 'https://x/1', 'https://x/1', 1, 1)")
    return conn


def _columns(conn, table):
    return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}


def _tables(conn):
    return {r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}


def test_a_version_one_database_migrates_and_keeps_its_rows(tmp_path):
    conn = _v1_database(tmp_path / "v1.db")
    init_db(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert conn.execute("SELECT COUNT(*) AS n FROM role").fetchone()["n"] == 1
    assert conn.execute("SELECT title FROM role").fetchone()["title"] == "Data Engineer"
    assert conn.execute("SELECT scraped AS s FROM run").fetchone()["s"] == 3


def test_the_migration_adds_every_version_two_column(tmp_path):
    conn = _v1_database(tmp_path / "v1.db")
    init_db(conn)
    assert {"location", "country", "work_modes",
            "setup_complete"} <= _columns(conn, "user")
    assert "resume_id" in _columns(conn, "role")
    assert {"stage", "progress", "error"} <= _columns(conn, "run")
    assert "resume" in _tables(conn)


def test_migrating_twice_is_a_no_op(tmp_path):
    """init_db runs on every request. Re-running the ALTERs would raise
    'duplicate column name' and take the whole app down."""
    conn = _v1_database(tmp_path / "v1.db")
    init_db(conn)
    init_db(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION


def test_a_fresh_database_lands_on_version_two(tmp_path):
    conn = connect(tmp_path / "fresh.db")
    init_db(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 2
    assert {"location", "country", "work_modes",
            "setup_complete"} <= _columns(conn, "user")
    assert "resume" in _tables(conn)


def test_existing_users_default_to_setup_incomplete(tmp_path):
    conn = _v1_database(tmp_path / "v1.db")
    init_db(conn)
    row = conn.execute("SELECT setup_complete AS s, location AS l "
                       "FROM user").fetchone()
    assert row["s"] == 0
    assert row["l"] is None
