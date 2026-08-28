"""The version 1 -> 2 migration.

`init_db` used to be nothing but CREATE TABLE IF NOT EXISTS, which cannot add
a column to a table that already exists. These tests exist because the first
person to run the new code will have a database full of rows.
"""
import sqlite3

import pytest

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


def test_a_fresh_database_lands_on_the_current_version(tmp_path):
    conn = connect(tmp_path / "fresh.db")
    init_db(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
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


def test_a_database_ahead_of_this_code_keeps_its_version(tmp_path):
    """A database already migrated by newer code (plausible across
    worktrees/branches) must not be silently downgraded. The table shape is
    untouched and still newer than what this code knows how to write —
    dragging the stored version number down would make the next run of the
    newer code replay ALTERs against columns that already exist."""
    conn = connect(tmp_path / "ahead.db")
    init_db(conn)
    conn.execute("PRAGMA user_version = 99")
    init_db(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 99


def test_migration_survives_a_crash_between_create_and_version_stamp(tmp_path):
    """`executescript` autocommits each CREATE TABLE as it runs, so a
    process killed after the tables are created but before the final
    PRAGMA user_version write leaves a fully-shaped table sitting behind a
    stale (pre-migration) version number. Re-running init_db against that
    state must not try to add columns that already exist."""
    from src.store.schema import _DDL

    conn = connect(tmp_path / "crashed.db")
    conn.executescript(_DDL)  # simulate the fresh-create having completed
    # PRAGMA user_version defaults to 0 — never stamped, as if killed here.

    init_db(conn)  # must not raise "duplicate column name"

    assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION


def test_the_sole_existing_user_is_renamed_to_default(tmp_path):
    """Ship 2 stops reading CANDIDATE_NAME. Without this the user's whole
    map would be stranded behind a name nothing sets any more."""
    conn = _v1_database(tmp_path / "v1.db")
    conn.execute("UPDATE user SET name = 'Ghazal Izadi'")
    init_db(conn)
    assert conn.execute("SELECT name FROM user").fetchone()["name"] == "default"


def test_the_renamed_user_keeps_their_rows(tmp_path):
    conn = _v1_database(tmp_path / "v1.db")
    conn.execute("UPDATE user SET name = 'Ghazal Izadi'")
    init_db(conn)
    row = conn.execute(
        "SELECT u.name, COUNT(r.id) AS roles FROM user u"
        " LEFT JOIN role r ON r.user_id = u.id GROUP BY u.id").fetchone()
    assert row["name"] == "default"
    assert row["roles"] == 1


def test_several_users_are_left_alone(tmp_path):
    """The rename is a rescue for the single-user case, not a policy."""
    conn = _v1_database(tmp_path / "v1.db")
    conn.execute("UPDATE user SET name = 'Ghazal Izadi'")
    conn.execute("INSERT INTO user (name, created_at) VALUES ('Other', '2026-01-01')")
    init_db(conn)
    names = {r["name"] for r in conn.execute("SELECT name FROM user")}
    assert names == {"Ghazal Izadi", "Other"}


def test_the_rename_is_safe_to_replay(tmp_path):
    conn = _v1_database(tmp_path / "v1.db")
    conn.execute("UPDATE user SET name = 'Ghazal Izadi'")
    init_db(conn)
    init_db(conn)
    assert conn.execute("SELECT name FROM user").fetchone()["name"] == "default"


def test_version_four_adds_work_mode_and_old_rows_stay_honest(tmp_path):
    """Old rows were scraped before mode detection existed — NULL, never a
    guessed backfill."""
    conn = _v1_database(tmp_path / "v1.db")
    init_db(conn)
    assert "work_mode" in _columns(conn, "role")
    assert conn.execute(
        "SELECT work_mode FROM role").fetchone()["work_mode"] is None


def test_version_four_adds_dropped_and_old_runs_default_to_zero(tmp_path):
    """A run recorded before the policy ladder existed dropped nothing it
    knew about — 0, not NULL, since 'dropped' is a count, not a fact that
    could be missing."""
    conn = _v1_database(tmp_path / "v1.db")
    init_db(conn)
    assert "dropped" in _columns(conn, "run")
    assert conn.execute(
        "SELECT dropped FROM run").fetchone()["dropped"] == 0


def test_version_five_adds_eligibility_verified_defaulting_honest(tmp_path):
    """Old rows were scored before verification existed — 0, never a
    guessed backfill."""
    conn = _v1_database(tmp_path / "v1.db")
    init_db(conn)
    assert "eligibility_verified" in _columns(conn, "role")
    assert conn.execute("SELECT eligibility_verified FROM role"
                        ).fetchone()["eligibility_verified"] == 0


def test_version_six_adds_offtopic_and_old_runs_default_to_zero(tmp_path):
    """A run recorded before the relevance gate existed rejected nothing it
    knew about — 0, not NULL, same as `dropped` in version 4."""
    conn = _v1_database(tmp_path / "v1.db")
    init_db(conn)
    assert "offtopic" in _columns(conn, "run")
    assert conn.execute(
        "SELECT offtopic FROM run").fetchone()["offtopic"] == 0


def test_version_seven_adds_country_scope_and_source_board(tmp_path):
    """kaix's country code, the remote-board reach verdict, and which board
    a row came from all land on `role` — none had anywhere to live before."""
    conn = _v1_database(tmp_path / "v1.db")
    init_db(conn)
    assert {"country", "location_scope", "source_board"} <= _columns(conn, "role")


def test_version_seven_defaults_are_null_on_existing_rows(tmp_path):
    """Old rows were scraped before any of the three had a producer —
    NULL, never a guessed backfill."""
    conn = _v1_database(tmp_path / "v1.db")
    init_db(conn)
    row = conn.execute(
        "SELECT country, location_scope, source_board FROM role").fetchone()
    assert row["country"] is None
    assert row["location_scope"] is None
    assert row["source_board"] is None


def test_location_scope_rejects_values_outside_the_verdict_set(tmp_path):
    """Same discipline as `band`: a typo in the verdict must not silently
    land in the database."""
    conn = _v1_database(tmp_path / "v1.db")
    init_db(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE role SET location_scope = 'sideways'")


def test_migration_v8_adds_the_boards_column(tmp_path):
    """The aggregator advertises ten boards and returned four in run 6.
    Which ones is now a fact the run row carries."""
    conn = connect(tmp_path / "v8.db")
    init_db(conn)
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(run)")}
    assert "boards" in cols
    assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    conn.close()


def test_migration_v9_adds_the_dropped_at_column(tmp_path):
    """Soft drop, never DELETE - a wrong cleanup rule has to be
    recoverable as a column change, not a restore from backup."""
    conn = connect(tmp_path / "v9.db")
    init_db(conn)
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(role)")}
    assert "dropped_at" in cols
    conn.close()
