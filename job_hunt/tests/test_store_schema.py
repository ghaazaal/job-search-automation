"""Tests for src/store/schema.py — the constraints must actually bite."""
import sqlite3

import pytest

from src.store.db import connect, transaction
from src.store.schema import init_db


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "test.db")
    init_db(c)
    return c


def _user(conn) -> int:
    conn.execute("INSERT INTO user (name, created_at) VALUES ('t', '2026-08-10')")
    return conn.execute("SELECT last_insert_rowid() AS i").fetchone()["i"]


def _run(conn, user_id) -> int:
    conn.execute(
        "INSERT INTO run (user_id, started_at, status) VALUES (?, ?, 'RUNNING')",
        (user_id, "2026-08-10T06:40:00"))
    return conn.execute("SELECT last_insert_rowid() AS i").fetchone()["i"]


def _company(conn, user_id, name="Acme") -> int:
    conn.execute(
        """INSERT INTO company (user_id, name, fingerprint, first_seen_at, last_seen_at)
           VALUES (?, ?, ?, '2026-08-10', '2026-08-10')""",
        (user_id, name, name.lower()))
    return conn.execute("SELECT last_insert_rowid() AS i").fetchone()["i"]


def _role(conn, user_id, company_id, run_id, url="https://x/1") -> int:
    conn.execute(
        """INSERT INTO role (user_id, company_id, title, url, url_normalised,
                             first_seen_run_id, last_seen_run_id)
           VALUES (?, ?, 'Analytics Engineer', ?, ?, ?, ?)""",
        (user_id, company_id, url, url, run_id, run_id))
    return conn.execute("SELECT last_insert_rowid() AS i").fetchone()["i"]


def test_init_db_is_idempotent(conn):
    init_db(conn)
    init_db(conn)
    names = {r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"user", "run", "company", "role", "application", "event"} <= names


def test_role_requires_an_existing_company(conn):
    u = _user(conn)
    r = _run(conn, u)
    with pytest.raises(sqlite3.IntegrityError):
        with transaction(conn):
            _role(conn, u, 9999, r)


def test_duplicate_normalised_url_is_rejected(conn):
    u = _user(conn)
    r = _run(conn, u)
    c = _company(conn, u)
    _role(conn, u, c, r, url="https://x/same")
    with pytest.raises(sqlite3.IntegrityError):
        with transaction(conn):
            _role(conn, u, c, r, url="https://x/same")


def test_duplicate_company_fingerprint_is_rejected(conn):
    u = _user(conn)
    _company(conn, u, "Acme")
    with pytest.raises(sqlite3.IntegrityError):
        with transaction(conn):
            _company(conn, u, "Acme")


def test_invalid_application_status_is_rejected(conn):
    u = _user(conn)
    r = _run(conn, u)
    c = _company(conn, u)
    role_id = _role(conn, u, c, r)
    with pytest.raises(sqlite3.IntegrityError):
        with transaction(conn):
            conn.execute(
                """INSERT INTO application (user_id, role_id, status, updated_at)
                   VALUES (?, ?, 'aplied', '2026-08-10')""", (u, role_id))


def test_new_is_not_a_storable_status(conn):
    """NEW is the absence of an application row, never a stored value."""
    u = _user(conn)
    r = _run(conn, u)
    c = _company(conn, u)
    role_id = _role(conn, u, c, r)
    with pytest.raises(sqlite3.IntegrityError):
        with transaction(conn):
            conn.execute(
                """INSERT INTO application (user_id, role_id, status, updated_at)
                   VALUES (?, ?, 'NEW', '2026-08-10')""", (u, role_id))


def test_invalid_run_status_is_rejected(conn):
    u = _user(conn)
    with pytest.raises(sqlite3.IntegrityError):
        with transaction(conn):
            conn.execute(
                "INSERT INTO run (user_id, started_at, status) VALUES (?, ?, 'PENDING')",
                (u, "2026-08-10T06:40:00"))


def test_invalid_company_state_is_rejected(conn):
    u = _user(conn)
    with pytest.raises(sqlite3.IntegrityError):
        with transaction(conn):
            conn.execute(
                """INSERT INTO company (user_id, name, fingerprint, user_state,
                                        first_seen_at, last_seen_at)
                   VALUES (?, 'X', 'x', 'MAYBE', '2026-08-10', '2026-08-10')""",
                (u,))


def test_one_application_per_role(conn):
    u = _user(conn)
    r = _run(conn, u)
    c = _company(conn, u)
    role_id = _role(conn, u, c, r)
    conn.execute("""INSERT INTO application (user_id, role_id, status, updated_at)
                    VALUES (?, ?, 'SAVED', '2026-08-10')""", (u, role_id))
    with pytest.raises(sqlite3.IntegrityError):
        with transaction(conn):
            conn.execute(
                """INSERT INTO application (user_id, role_id, status, updated_at)
                   VALUES (?, ?, 'APPLIED', '2026-08-10')""", (u, role_id))


def test_band_may_be_null_but_not_arbitrary(conn):
    u = _user(conn)
    r = _run(conn, u)
    c = _company(conn, u)
    conn.execute(
        """INSERT INTO role (user_id, company_id, title, url, url_normalised,
                             band, first_seen_run_id, last_seen_run_id)
           VALUES (?, ?, 'T', 'https://x/2', 'https://x/2', NULL, ?, ?)""",
        (u, c, r, r))
    with pytest.raises(sqlite3.IntegrityError):
        with transaction(conn):
            conn.execute(
                """INSERT INTO role (user_id, company_id, title, url, url_normalised,
                                     band, first_seen_run_id, last_seen_run_id)
                   VALUES (?, ?, 'T', 'https://x/3', 'https://x/3', 'GREAT', ?, ?)""",
                (u, c, r, r))


def test_invalid_resume_seniority_is_rejected(conn):
    u = _user(conn)
    with pytest.raises(sqlite3.IntegrityError):
        with transaction(conn):
            conn.execute(
                """INSERT INTO resume (user_id, label, orig_filename, sha256,
                       stored_path, extracted_text, seniority, created_at)
                   VALUES (?, 'l', 'f.pdf', 's', 'p', 't', 'principal',
                           '2026-08-11')""", (u,))


def test_a_role_cannot_point_at_a_missing_resume(conn):
    u = _user(conn)
    r = _run(conn, u)
    c = _company(conn, u)
    with pytest.raises(sqlite3.IntegrityError):
        with transaction(conn):
            conn.execute(
                """INSERT INTO role (user_id, company_id, title, url,
                       url_normalised, resume_id,
                       first_seen_run_id, last_seen_run_id)
                   VALUES (?, ?, 'T', 'https://x/9', 'https://x/9', 4242, ?, ?)""",
                (u, c, r, r))
