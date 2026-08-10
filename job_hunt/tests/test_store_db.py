"""Tests for src/store/db.py — connection pragmas and transactions."""
import sqlite3

import pytest

from src.store.db import connect, transaction


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "test.db"


def test_foreign_keys_are_enabled(db_path):
    """Off by default in SQLite — every declared FK is ignored without this."""
    with connect(db_path) as conn:
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_journal_mode_is_wal(db_path):
    """WAL lets the web app read while the scraper writes."""
    with connect(db_path) as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"


def test_busy_timeout_is_set(db_path):
    with connect(db_path) as conn:
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] >= 5000


def test_rows_are_addressable_by_name(db_path):
    with connect(db_path) as conn:
        conn.execute("CREATE TABLE t (a TEXT)")
        conn.execute("INSERT INTO t VALUES ('x')")
        assert conn.execute("SELECT a FROM t").fetchone()["a"] == "x"


def test_transaction_commits_on_success(db_path):
    with connect(db_path) as conn:
        conn.execute("CREATE TABLE t (a TEXT)")
        with transaction(conn):
            conn.execute("INSERT INTO t VALUES ('kept')")
    with connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) c FROM t").fetchone()["c"] == 1


def test_transaction_rolls_back_on_error(db_path):
    """Atomicity — a batch that fails partway leaves nothing behind."""
    with connect(db_path) as conn:
        conn.execute("CREATE TABLE t (a TEXT)")
        with pytest.raises(ValueError):
            with transaction(conn):
                conn.execute("INSERT INTO t VALUES ('doomed')")
                raise ValueError("boom")
    with connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) c FROM t").fetchone()["c"] == 0


def test_foreign_key_violation_is_raised(db_path):
    with connect(db_path) as conn:
        conn.execute("CREATE TABLE parent (id INTEGER PRIMARY KEY)")
        conn.execute("CREATE TABLE child (p INTEGER REFERENCES parent(id))")
        with pytest.raises(sqlite3.IntegrityError):
            with transaction(conn):
                conn.execute("INSERT INTO child VALUES (999)")
