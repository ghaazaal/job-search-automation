# Activity Store and Application Tracking — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the product a memory — a durable SQLite store behind a local Flask app, so companies, roles, and the user's saved/applied/interviewing/offer decisions survive between runs.

**Architecture:** SQLite becomes the source of truth. The scrape pipeline writes each run into it; a local Flask app reads from it and writes the user's clicks back. Excel is demoted to an export. The store is split into five small modules by responsibility (connection, schema, ingest, tracking, read models) so no file holds more than one job. Existing renderers (`map_page.py`) are fed from the store rather than rewritten.

**Tech Stack:** Python 3.13, SQLite (stdlib `sqlite3`), Flask, pytest. No ORM — the schema is small and the constraints matter more than the abstraction.

**Spec:** `docs/superpowers/specs/2026-08-10-activity-store-and-tracking-design.md`

**Note on existing data:** `job_tracker_ghazal.xlsx` is NOT imported. The store starts empty and fills from the first scrape.

---

## File Structure

| File | Responsibility |
|---|---|
| `job_hunt/src/store/__init__.py` | Package marker. Empty. |
| `job_hunt/src/store/db.py` | Open connections with the required pragmas. Transaction helper. Nothing else. |
| `job_hunt/src/store/schema.py` | DDL for the six tables. Idempotent `init_db`. |
| `job_hunt/src/store/ingest.py` | Write a scrape run: companies, roles, run row. Never touches tracking tables. |
| `job_hunt/src/store/tracking.py` | Status transitions and the event log. Never touches scrape tables. |
| `job_hunt/src/store/queries.py` | Read models for the two screens. Strips `match_score`. |
| `job_hunt/src/activity_page.py` | Renders the activity screen. |
| `job_hunt/src/app.py` | Flask routes. Contains no SQL. |
| `job_hunt/main.py` | Wires the pipeline to the store, then serves. |

Tests mirror this: `tests/test_store_db.py`, `test_store_schema.py`, `test_store_ingest.py`, `test_store_tracking.py`, `test_store_queries.py`, `test_activity_page.py`, `test_app.py`.

---

## Task 1: Connections with the required pragmas

SQLite ignores foreign keys unless told otherwise, on every single connection. This task exists because that default silently voids every constraint in Task 2.

**Files:**
- Create: `job_hunt/src/store/__init__.py`
- Create: `job_hunt/src/store/db.py`
- Test: `job_hunt/tests/test_store_db.py`

- [ ] **Step 1: Write the failing test**

Create `job_hunt/tests/test_store_db.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd job_hunt && python -m pytest tests/test_store_db.py -q
```

Expected: collection error, `ModuleNotFoundError: No module named 'src.store'`.

- [ ] **Step 3: Write the minimal implementation**

Create `job_hunt/src/store/__init__.py` as an empty file.

Create `job_hunt/src/store/db.py`:

```python
"""SQLite connections.

Two pragmas here are load-bearing and easy to lose. `foreign_keys` is per
connection and defaults to OFF, so without it every declared foreign key in the
schema is decorative. `journal_mode` is persisted in the file but is set
idempotently so a fresh database gets it too.
"""
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parent.parent.parent / "job_hunt.db"


def connect(db_path: Path | str = DEFAULT_PATH) -> sqlite3.Connection:
    """Open a connection with the pragmas this design depends on."""
    conn = sqlite3.connect(str(db_path), isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA synchronous = FULL")
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection):
    """Run a block atomically. Rolls back on any exception.

    `isolation_level=None` disables the driver's implicit transactions, so
    BEGIN and COMMIT are explicit and nesting cannot surprise us.
    """
    conn.execute("BEGIN")
    try:
        yield conn
    except Exception:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd job_hunt && python -m pytest tests/test_store_db.py -q
```

Expected: `7 passed`.

- [ ] **Step 5: Commit**

```bash
git add job_hunt/src/store/__init__.py job_hunt/src/store/db.py job_hunt/tests/test_store_db.py
git commit -m "feat: sqlite connections with foreign keys, WAL and explicit transactions"
```

---

## Task 2: The schema

**Files:**
- Create: `job_hunt/src/store/schema.py`
- Test: `job_hunt/tests/test_store_schema.py`

- [ ] **Step 1: Write the failing test**

Create `job_hunt/tests/test_store_schema.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd job_hunt && python -m pytest tests/test_store_schema.py -q
```

Expected: collection error, `ModuleNotFoundError: No module named 'src.store.schema'`.

- [ ] **Step 3: Write the minimal implementation**

Create `job_hunt/src/store/schema.py`:

```python
"""Schema definition.

Constraints live here rather than in Python. A status typo should be rejected
by the database, not caught by whichever caller happened to remember to check.
"""
import sqlite3

SCHEMA_VERSION = 1

_DDL = """
CREATE TABLE IF NOT EXISTS user (
    id               INTEGER PRIMARY KEY,
    name             TEXT NOT NULL,
    email            TEXT,
    last_seen_run_id INTEGER,
    created_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS run (
    id          INTEGER PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES user(id),
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    status      TEXT NOT NULL CHECK (status IN ('RUNNING','OK','FAILED')),
    scraped     INTEGER NOT NULL DEFAULT 0,
    kept        INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS company (
    id            INTEGER PRIMARY KEY,
    user_id       INTEGER NOT NULL REFERENCES user(id),
    name          TEXT NOT NULL,
    fingerprint   TEXT NOT NULL,
    user_state    TEXT NOT NULL DEFAULT 'NONE'
                  CHECK (user_state IN ('NONE','WATCH','HIDDEN')),
    first_seen_at TEXT NOT NULL,
    last_seen_at  TEXT NOT NULL,
    UNIQUE (user_id, fingerprint)
);

CREATE TABLE IF NOT EXISTS role (
    id                   INTEGER PRIMARY KEY,
    user_id              INTEGER NOT NULL REFERENCES user(id),
    company_id           INTEGER NOT NULL REFERENCES company(id),
    title                TEXT NOT NULL,
    url                  TEXT NOT NULL,
    url_normalised       TEXT NOT NULL,
    location             TEXT,
    salary               TEXT,
    platform             TEXT,
    posted_date          TEXT,
    description          TEXT,
    description_captured INTEGER NOT NULL DEFAULT 0,
    match_score          INTEGER,
    band                 TEXT CHECK (band IN ('STRONG FIT','PARTIAL FIT','STRETCH')),
    reason               TEXT,
    matched              TEXT NOT NULL DEFAULT '[]',
    gaps                 TEXT NOT NULL DEFAULT '[]',
    first_seen_run_id    INTEGER NOT NULL REFERENCES run(id),
    last_seen_run_id     INTEGER NOT NULL REFERENCES run(id),
    UNIQUE (user_id, url_normalised)
);

CREATE TABLE IF NOT EXISTS application (
    id         INTEGER PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES user(id),
    role_id    INTEGER NOT NULL UNIQUE REFERENCES role(id),
    status     TEXT NOT NULL CHECK (status IN
                 ('SAVED','APPLIED','INTERVIEWING','OFFER',
                  'REJECTED','CLOSED','HIDDEN')),
    applied_at TEXT,
    updated_at TEXT NOT NULL,
    notes      TEXT
);

CREATE TABLE IF NOT EXISTS event (
    id          INTEGER PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES user(id),
    role_id     INTEGER REFERENCES role(id),
    company_id  INTEGER REFERENCES company(id),
    kind        TEXT NOT NULL,
    from_status TEXT,
    to_status   TEXT,
    at          TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_role_company ON role(company_id);
CREATE INDEX IF NOT EXISTS idx_role_last_run ON role(user_id, last_seen_run_id);
CREATE INDEX IF NOT EXISTS idx_event_role ON event(role_id, at);
"""


def init_db(conn: sqlite3.Connection) -> None:
    """Create the schema if absent. Safe to call on every start."""
    conn.executescript(_DDL)
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd job_hunt && python -m pytest tests/test_store_schema.py -q
```

Expected: `9 passed`.

- [ ] **Step 5: Commit**

```bash
git add job_hunt/src/store/schema.py job_hunt/tests/test_store_schema.py
git commit -m "feat: store schema with enforced status and dedup constraints"
```

---

## Task 3: Ingesting a scrape run

**Files:**
- Create: `job_hunt/src/store/ingest.py`
- Test: `job_hunt/tests/test_store_ingest.py`

- [ ] **Step 1: Write the failing test**

Create `job_hunt/tests/test_store_ingest.py`:

```python
"""Tests for src/store/ingest.py — writing a scrape run into the store."""
import pytest

from src.store.db import connect
from src.store.schema import init_db
from src.store.ingest import ensure_user, start_run, finish_run, upsert_jobs


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "test.db")
    init_db(c)
    return c


def _job(url="https://x/1", company="Acme", title="Analytics Engineer", **kw):
    base = {"company": company, "title": title, "url": url,
            "location": "Remote, US", "salary": "", "platform": "LinkedIn",
            "date": "2026-08-08", "description": "We use dbt.",
            "description_captured": True, "match_score": 9,
            "band": "STRONG FIT", "reason": "matches dbt",
            "matched": ["dbt"], "gaps": ["snowflake"]}
    return {**base, **kw}


def test_ensure_user_is_idempotent(conn):
    a = ensure_user(conn, "Ghazal")
    b = ensure_user(conn, "Ghazal")
    assert a == b
    assert conn.execute("SELECT COUNT(*) c FROM user").fetchone()["c"] == 1


def test_run_starts_as_running_and_finishes_ok(conn):
    u = ensure_user(conn, "Ghazal")
    run_id = start_run(conn, u)
    assert conn.execute("SELECT status FROM run WHERE id=?",
                        (run_id,)).fetchone()["status"] == "RUNNING"
    finish_run(conn, run_id, scraped=10, kept=8)
    row = conn.execute("SELECT * FROM run WHERE id=?", (run_id,)).fetchone()
    assert row["status"] == "OK" and row["kept"] == 8 and row["finished_at"]


def test_jobs_create_companies_and_roles(conn):
    u = ensure_user(conn, "Ghazal")
    run_id = start_run(conn, u)
    upsert_jobs(conn, u, run_id, [_job()])
    assert conn.execute("SELECT COUNT(*) c FROM company").fetchone()["c"] == 1
    assert conn.execute("SELECT COUNT(*) c FROM role").fetchone()["c"] == 1


def test_two_roles_at_one_company_share_it(conn):
    u = ensure_user(conn, "Ghazal")
    run_id = start_run(conn, u)
    upsert_jobs(conn, u, run_id, [_job(url="https://x/1"),
                                  _job(url="https://x/2", title="Data Engineer")])
    assert conn.execute("SELECT COUNT(*) c FROM company").fetchone()["c"] == 1
    assert conn.execute("SELECT COUNT(*) c FROM role").fetchone()["c"] == 2


def test_reseeing_a_role_updates_last_seen_not_first_seen(conn):
    u = ensure_user(conn, "Ghazal")
    first = start_run(conn, u)
    upsert_jobs(conn, u, first, [_job()])
    second = start_run(conn, u)
    upsert_jobs(conn, u, second, [_job()])
    row = conn.execute("SELECT * FROM role").fetchone()
    assert row["first_seen_run_id"] == first
    assert row["last_seen_run_id"] == second
    assert conn.execute("SELECT COUNT(*) c FROM role").fetchone()["c"] == 1


def test_tracking_urls_do_not_create_a_second_role(conn):
    """Dedup is a database guarantee via url_normalised."""
    u = ensure_user(conn, "Ghazal")
    run_id = start_run(conn, u)
    upsert_jobs(conn, u, run_id, [_job(url="https://jobs.lever.co/a/1")])
    upsert_jobs(conn, u, run_id,
                [_job(url="https://jobs.lever.co/a/1?lever-source=Indeed")])
    assert conn.execute("SELECT COUNT(*) c FROM role").fetchone()["c"] == 1


def test_evidence_is_stored(conn):
    u = ensure_user(conn, "Ghazal")
    run_id = start_run(conn, u)
    upsert_jobs(conn, u, run_id, [_job()])
    row = conn.execute("SELECT * FROM role").fetchone()
    assert row["band"] == "STRONG FIT"
    assert row["matched"] == '["dbt"]'
    assert row["description_captured"] == 1


def test_uncaptured_description_is_persisted_as_such(conn):
    u = ensure_user(conn, "Ghazal")
    run_id = start_run(conn, u)
    upsert_jobs(conn, u, run_id,
                [_job(description="", description_captured=False, band=None)])
    row = conn.execute("SELECT * FROM role").fetchone()
    assert row["description_captured"] == 0
    assert row["band"] is None


def test_ingest_never_writes_tracking_tables(conn):
    u = ensure_user(conn, "Ghazal")
    run_id = start_run(conn, u)
    upsert_jobs(conn, u, run_id, [_job()])
    assert conn.execute("SELECT COUNT(*) c FROM application").fetchone()["c"] == 0


def test_a_failing_batch_leaves_no_partial_rows(conn):
    """Atomicity — job 2 is malformed, so neither job lands."""
    u = ensure_user(conn, "Ghazal")
    run_id = start_run(conn, u)
    bad = _job(url="https://x/2")
    del bad["title"]
    with pytest.raises(KeyError):
        upsert_jobs(conn, u, run_id, [_job(url="https://x/1"), bad])
    assert conn.execute("SELECT COUNT(*) c FROM role").fetchone()["c"] == 0
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd job_hunt && python -m pytest tests/test_store_ingest.py -q
```

Expected: collection error, `ModuleNotFoundError: No module named 'src.store.ingest'`.

- [ ] **Step 3: Write the minimal implementation**

Create `job_hunt/src/store/ingest.py`:

```python
"""Writing a scrape run into the store.

This module owns the scrape half of the database and never touches
`application` or `event` — what the user decided is not the scraper's business.
"""
import json
import sqlite3
from datetime import datetime, timezone

from .db import transaction
from ..tracker.dedup import fingerprint, normalize_url

# Batch size keeps write transactions short so the web app is not locked out
# for the length of a run.
BATCH = 50


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ensure_user(conn: sqlite3.Connection, name: str, email: str = "") -> int:
    row = conn.execute("SELECT id FROM user WHERE name = ?", (name,)).fetchone()
    if row:
        return row["id"]
    with transaction(conn):
        conn.execute(
            "INSERT INTO user (name, email, created_at) VALUES (?, ?, ?)",
            (name, email, _now()))
    return conn.execute("SELECT id FROM user WHERE name = ?", (name,)).fetchone()["id"]


def start_run(conn: sqlite3.Connection, user_id: int) -> int:
    with transaction(conn):
        conn.execute(
            "INSERT INTO run (user_id, started_at, status) VALUES (?, ?, 'RUNNING')",
            (user_id, _now()))
    return conn.execute("SELECT last_insert_rowid() AS i").fetchone()["i"]


def finish_run(conn: sqlite3.Connection, run_id: int,
               scraped: int, kept: int, ok: bool = True) -> None:
    with transaction(conn):
        conn.execute(
            """UPDATE run SET status = ?, finished_at = ?, scraped = ?, kept = ?
               WHERE id = ?""",
            ("OK" if ok else "FAILED", _now(), scraped, kept, run_id))


def _company_id(conn: sqlite3.Connection, user_id: int, name: str) -> int:
    fp = fingerprint({"company": name, "title": ""})
    row = conn.execute(
        "SELECT id FROM company WHERE user_id = ? AND fingerprint = ?",
        (user_id, fp)).fetchone()
    if row:
        conn.execute("UPDATE company SET last_seen_at = ? WHERE id = ?",
                     (_now(), row["id"]))
        return row["id"]
    conn.execute(
        """INSERT INTO company (user_id, name, fingerprint, first_seen_at, last_seen_at)
           VALUES (?, ?, ?, ?, ?)""",
        (user_id, name, fp, _now(), _now()))
    return conn.execute("SELECT last_insert_rowid() AS i").fetchone()["i"]


def _upsert_role(conn: sqlite3.Connection, user_id: int, run_id: int,
                 job: dict) -> None:
    company_id = _company_id(conn, user_id, job["company"])
    url_n = normalize_url(job["url"])
    existing = conn.execute(
        "SELECT id FROM role WHERE user_id = ? AND url_normalised = ?",
        (user_id, url_n)).fetchone()

    values = (
        job["title"], job.get("location"), job.get("salary"),
        job.get("platform"), str(job.get("date") or ""),
        job.get("description") or "",
        1 if job.get("description_captured") else 0,
        job.get("match_score"), job.get("band"), job.get("reason"),
        json.dumps(list(job.get("matched") or [])),
        json.dumps(list(job.get("gaps") or [])),
    )

    if existing:
        conn.execute(
            """UPDATE role SET title=?, location=?, salary=?, platform=?,
                   posted_date=?, description=?, description_captured=?,
                   match_score=?, band=?, reason=?, matched=?, gaps=?,
                   last_seen_run_id=?
               WHERE id=?""",
            (*values, run_id, existing["id"]))
    else:
        conn.execute(
            """INSERT INTO role (user_id, company_id, url, url_normalised,
                   title, location, salary, platform, posted_date, description,
                   description_captured, match_score, band, reason, matched, gaps,
                   first_seen_run_id, last_seen_run_id)
               VALUES (?,?,?,?, ?,?,?,?,?,?, ?,?,?,?,?,?, ?,?)""",
            (user_id, company_id, job["url"], url_n, *values, run_id, run_id))


def upsert_jobs(conn: sqlite3.Connection, user_id: int, run_id: int,
                jobs: list[dict]) -> None:
    """Write scored jobs in short batches so writers do not block the app."""
    for start in range(0, len(jobs), BATCH):
        with transaction(conn):
            for job in jobs[start:start + BATCH]:
                _upsert_role(conn, user_id, run_id, job)
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd job_hunt && python -m pytest tests/test_store_ingest.py -q
```

Expected: `10 passed`.

- [ ] **Step 5: Commit**

```bash
git add job_hunt/src/store/ingest.py job_hunt/tests/test_store_ingest.py
git commit -m "feat: ingest scrape runs into the store with batched transactions"
```

---

## Task 4: Status transitions and the event log

**Files:**
- Create: `job_hunt/src/store/tracking.py`
- Test: `job_hunt/tests/test_store_tracking.py`

- [ ] **Step 1: Write the failing test**

Create `job_hunt/tests/test_store_tracking.py`:

```python
"""Tests for src/store/tracking.py — status moves and their event log."""
import pytest

from src.store.db import connect
from src.store.schema import init_db
from src.store.ingest import ensure_user, start_run, upsert_jobs
from src.store.tracking import (STATUSES, set_role_status, role_status,
                                set_company_state, role_events)


@pytest.fixture
def ctx(tmp_path):
    conn = connect(tmp_path / "test.db")
    init_db(conn)
    user_id = ensure_user(conn, "Ghazal")
    run_id = start_run(conn, user_id)
    upsert_jobs(conn, user_id, run_id, [{
        "company": "Acme", "title": "Analytics Engineer", "url": "https://x/1",
        "location": "Remote", "salary": "", "platform": "LinkedIn",
        "date": "2026-08-08", "description": "dbt", "description_captured": True,
        "match_score": 9, "band": "STRONG FIT", "reason": "matches dbt",
        "matched": ["dbt"], "gaps": []}])
    role_id = conn.execute("SELECT id FROM role").fetchone()["id"]
    company_id = conn.execute("SELECT id FROM company").fetchone()["id"]
    return conn, user_id, role_id, company_id


def test_untouched_role_reads_as_new(ctx):
    conn, user_id, role_id, _ = ctx
    assert role_status(conn, role_id) == "NEW"


def test_saving_a_role_sets_its_status(ctx):
    conn, user_id, role_id, _ = ctx
    set_role_status(conn, user_id, role_id, "SAVED")
    assert role_status(conn, role_id) == "SAVED"


def test_every_move_writes_an_event(ctx):
    conn, user_id, role_id, _ = ctx
    set_role_status(conn, user_id, role_id, "SAVED")
    set_role_status(conn, user_id, role_id, "APPLIED")
    set_role_status(conn, user_id, role_id, "INTERVIEWING")
    events = role_events(conn, role_id)
    assert [e["to_status"] for e in events] == ["SAVED", "APPLIED", "INTERVIEWING"]
    assert events[1]["from_status"] == "SAVED"


def test_status_and_latest_event_never_disagree(ctx):
    conn, user_id, role_id, _ = ctx
    for status in ("SAVED", "APPLIED", "OFFER"):
        set_role_status(conn, user_id, role_id, status)
        assert role_status(conn, role_id) == role_events(conn, role_id)[-1]["to_status"]


def test_applied_at_is_stamped_once(ctx):
    conn, user_id, role_id, _ = ctx
    set_role_status(conn, user_id, role_id, "APPLIED")
    first = conn.execute("SELECT applied_at FROM application").fetchone()["applied_at"]
    set_role_status(conn, user_id, role_id, "INTERVIEWING")
    assert conn.execute(
        "SELECT applied_at FROM application").fetchone()["applied_at"] == first


def test_backwards_moves_are_allowed_and_logged(ctx):
    """A mis-click must be correctable, and the correction recorded."""
    conn, user_id, role_id, _ = ctx
    set_role_status(conn, user_id, role_id, "APPLIED")
    set_role_status(conn, user_id, role_id, "SAVED")
    assert role_status(conn, role_id) == "SAVED"
    assert len(role_events(conn, role_id)) == 2


def test_invalid_status_is_rejected(ctx):
    conn, user_id, role_id, _ = ctx
    with pytest.raises(ValueError):
        set_role_status(conn, user_id, role_id, "MAYBE")


def test_new_cannot_be_set_as_a_status(ctx):
    conn, user_id, role_id, _ = ctx
    with pytest.raises(ValueError):
        set_role_status(conn, user_id, role_id, "NEW")


def test_statuses_constant_matches_the_pipeline(ctx):
    assert STATUSES == ("SAVED", "APPLIED", "INTERVIEWING", "OFFER",
                        "REJECTED", "CLOSED", "HIDDEN")


def test_watching_a_company_persists_and_logs(ctx):
    conn, user_id, _, company_id = ctx
    set_company_state(conn, user_id, company_id, "WATCH")
    assert conn.execute("SELECT user_state FROM company WHERE id=?",
                        (company_id,)).fetchone()["user_state"] == "WATCH"
    assert conn.execute(
        "SELECT COUNT(*) c FROM event WHERE company_id=?",
        (company_id,)).fetchone()["c"] == 1


def test_invalid_company_state_is_rejected(ctx):
    conn, user_id, _, company_id = ctx
    with pytest.raises(ValueError):
        set_company_state(conn, user_id, company_id, "MAYBE")
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd job_hunt && python -m pytest tests/test_store_tracking.py -q
```

Expected: collection error, `ModuleNotFoundError: No module named 'src.store.tracking'`.

- [ ] **Step 3: Write the minimal implementation**

Create `job_hunt/src/store/tracking.py`:

```python
"""Status transitions and the append-only event log.

The status and its event row are written in one transaction, so the current
state and the history cannot drift apart. `event` is never updated or deleted —
it is the record that will eventually let the scoring weights be tested against
what actually happened.
"""
import sqlite3
from datetime import datetime, timezone

from .db import transaction

STATUSES = ("SAVED", "APPLIED", "INTERVIEWING", "OFFER",
            "REJECTED", "CLOSED", "HIDDEN")
COMPANY_STATES = ("NONE", "WATCH", "HIDDEN")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def role_status(conn: sqlite3.Connection, role_id: int) -> str:
    """Current status, or NEW when the user has never touched this role."""
    row = conn.execute("SELECT status FROM application WHERE role_id = ?",
                       (role_id,)).fetchone()
    return row["status"] if row else "NEW"


def role_events(conn: sqlite3.Connection, role_id: int) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT * FROM event WHERE role_id = ? ORDER BY at, id", (role_id,))]


def set_role_status(conn: sqlite3.Connection, user_id: int,
                    role_id: int, status: str) -> None:
    """Move a role to `status` and record the move. Rejects unknown values."""
    if status not in STATUSES:
        raise ValueError(f"unknown status: {status!r}")

    previous = role_status(conn, role_id)
    now = _now()
    applied_at = now if status == "APPLIED" else None

    with transaction(conn):
        if previous == "NEW":
            conn.execute(
                """INSERT INTO application (user_id, role_id, status, applied_at,
                                            updated_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (user_id, role_id, status, applied_at, now))
        else:
            # applied_at is stamped once — the first time it was applied to.
            conn.execute(
                """UPDATE application
                   SET status = ?, updated_at = ?,
                       applied_at = COALESCE(applied_at, ?)
                   WHERE role_id = ?""",
                (status, now, applied_at, role_id))
        conn.execute(
            """INSERT INTO event (user_id, role_id, kind, from_status, to_status, at)
               VALUES (?, ?, 'STATUS', ?, ?, ?)""",
            (user_id, role_id, previous, status, now))


def set_company_state(conn: sqlite3.Connection, user_id: int,
                      company_id: int, state: str) -> None:
    if state not in COMPANY_STATES:
        raise ValueError(f"unknown company state: {state!r}")

    row = conn.execute("SELECT user_state FROM company WHERE id = ?",
                       (company_id,)).fetchone()
    previous = row["user_state"] if row else None
    now = _now()

    with transaction(conn):
        conn.execute("UPDATE company SET user_state = ? WHERE id = ?",
                     (state, company_id))
        conn.execute(
            """INSERT INTO event (user_id, company_id, kind, from_status, to_status, at)
               VALUES (?, ?, 'COMPANY_STATE', ?, ?, ?)""",
            (user_id, company_id, previous, state, now))
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd job_hunt && python -m pytest tests/test_store_tracking.py -q
```

Expected: `11 passed`.

- [ ] **Step 5: Commit**

```bash
git add job_hunt/src/store/tracking.py job_hunt/tests/test_store_tracking.py
git commit -m "feat: role status transitions with an append-only event log"
```

---

## Task 5: Read models for the two screens

**Files:**
- Create: `job_hunt/src/store/queries.py`
- Test: `job_hunt/tests/test_store_queries.py`

- [ ] **Step 1: Write the failing test**

Create `job_hunt/tests/test_store_queries.py`:

```python
"""Tests for src/store/queries.py — what the screens are allowed to see."""
import json

import pytest

from src.store.db import connect
from src.store.schema import init_db
from src.store.ingest import ensure_user, start_run, finish_run, upsert_jobs
from src.store.tracking import set_role_status, set_company_state
from src.store.queries import map_sections, activity_board, mark_seen


def _job(url, company="Acme", title="Analytics Engineer", score=9, **kw):
    base = {"company": company, "title": title, "url": url,
            "location": "Remote, US", "salary": "", "platform": "LinkedIn",
            "date": "2026-08-08", "description": "dbt", "match_score": score,
            "description_captured": True, "band": "STRONG FIT",
            "reason": "matches dbt", "matched": ["dbt"], "gaps": ["snowflake"]}
    return {**base, **kw}


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "test.db")
    init_db(c)
    return c


def _run_with(conn, user_id, jobs):
    run_id = start_run(conn, user_id)
    upsert_jobs(conn, user_id, run_id, jobs)
    finish_run(conn, run_id, scraped=len(jobs), kept=len(jobs))
    return run_id


def test_first_run_is_all_new(conn):
    u = ensure_user(conn, "G")
    _run_with(conn, u, [_job("https://x/1")])
    sections = map_sections(conn, u, shortlist_min=7)
    assert [m["name"] for m in sections["new"]] == ["Acme"]
    assert sections["earlier"] == []


def test_after_marking_seen_the_next_run_is_new(conn):
    u = ensure_user(conn, "G")
    first = _run_with(conn, u, [_job("https://x/1")])
    mark_seen(conn, u, first)
    _run_with(conn, u, [_job("https://x/2", company="Globex")])
    sections = map_sections(conn, u, shortlist_min=7)
    assert [m["name"] for m in sections["new"]] == ["Globex"]
    assert [m["name"] for m in sections["earlier"]] == ["Acme"]


def test_acted_on_roles_leave_the_map(conn):
    u = ensure_user(conn, "G")
    _run_with(conn, u, [_job("https://x/1")])
    role_id = conn.execute("SELECT id FROM role").fetchone()["id"]
    set_role_status(conn, u, role_id, "SAVED")
    sections = map_sections(conn, u, shortlist_min=7)
    assert sections["new"] == [] and sections["earlier"] == []


def test_hidden_company_leaves_the_map(conn):
    u = ensure_user(conn, "G")
    _run_with(conn, u, [_job("https://x/1")])
    company_id = conn.execute("SELECT id FROM company").fetchone()["id"]
    set_company_state(conn, u, company_id, "HIDDEN")
    assert map_sections(conn, u, shortlist_min=7)["new"] == []


def test_watched_company_with_no_open_role_is_on_the_shelf(conn):
    u = ensure_user(conn, "G")
    _run_with(conn, u, [_job("https://x/1")])
    company_id = conn.execute("SELECT id FROM company").fetchone()["id"]
    role_id = conn.execute("SELECT id FROM role").fetchone()["id"]
    set_company_state(conn, u, company_id, "WATCH")
    set_role_status(conn, u, role_id, "APPLIED")
    sections = map_sections(conn, u, shortlist_min=7)
    assert [m["name"] for m in sections["watching"]] == ["Acme"]


def test_watched_company_with_an_open_role_is_a_card_not_a_tile(conn):
    u = ensure_user(conn, "G")
    _run_with(conn, u, [_job("https://x/1")])
    company_id = conn.execute("SELECT id FROM company").fetchone()["id"]
    set_company_state(conn, u, company_id, "WATCH")
    sections = map_sections(conn, u, shortlist_min=7)
    assert sections["watching"] == []
    assert [m["name"] for m in sections["new"]] == ["Acme"]


def test_state_is_derived_from_the_threshold(conn):
    u = ensure_user(conn, "G")
    _run_with(conn, u, [_job("https://x/1", score=9),
                        _job("https://x/2", company="Weak Co", score=3)])
    by_name = {m["name"]: m for m in map_sections(conn, u, shortlist_min=7)["new"]}
    assert by_name["Acme"]["state"] == "ACT_NOW"
    assert by_name["Weak Co"]["state"] == "DISCOVER"


def test_map_read_model_carries_no_score(conn):
    u = ensure_user(conn, "G")
    _run_with(conn, u, [_job("https://x/1")])
    blob = json.dumps(map_sections(conn, u, shortlist_min=7), default=str)
    assert "match_score" not in blob


def test_evidence_round_trips_as_lists(conn):
    u = ensure_user(conn, "G")
    _run_with(conn, u, [_job("https://x/1")])
    role = map_sections(conn, u, shortlist_min=7)["new"][0]["roles"][0]
    assert role["matched"] == ["dbt"]
    assert role["gaps"] == ["snowflake"]
    assert role["description_captured"] is True


def test_activity_board_groups_by_status(conn):
    u = ensure_user(conn, "G")
    _run_with(conn, u, [_job("https://x/1"),
                        _job("https://x/2", title="Data Engineer")])
    ids = [r["id"] for r in conn.execute("SELECT id FROM role ORDER BY id")]
    set_role_status(conn, u, ids[0], "SAVED")
    set_role_status(conn, u, ids[1], "APPLIED")
    board = activity_board(conn, u)
    assert [c["title"] for c in board["SAVED"]] == ["Analytics Engineer"]
    assert [c["title"] for c in board["APPLIED"]] == ["Data Engineer"]


def test_activity_columns_always_exist_even_when_empty(conn):
    u = ensure_user(conn, "G")
    board = activity_board(conn, u)
    assert set(board) == {"SAVED", "APPLIED", "INTERVIEWING", "OFFER", "CLOSED"}


def test_activity_cards_carry_their_event_log(conn):
    u = ensure_user(conn, "G")
    _run_with(conn, u, [_job("https://x/1")])
    role_id = conn.execute("SELECT id FROM role").fetchone()["id"]
    set_role_status(conn, u, role_id, "SAVED")
    set_role_status(conn, u, role_id, "APPLIED")
    card = activity_board(conn, u)["APPLIED"][0]
    assert [e["to_status"] for e in card["events"]] == ["SAVED", "APPLIED"]


def test_hidden_roles_are_absent_from_the_board(conn):
    u = ensure_user(conn, "G")
    _run_with(conn, u, [_job("https://x/1")])
    role_id = conn.execute("SELECT id FROM role").fetchone()["id"]
    set_role_status(conn, u, role_id, "HIDDEN")
    board = activity_board(conn, u)
    assert all(not column for column in board.values())


def test_activity_read_model_carries_no_score(conn):
    u = ensure_user(conn, "G")
    _run_with(conn, u, [_job("https://x/1")])
    role_id = conn.execute("SELECT id FROM role").fetchone()["id"]
    set_role_status(conn, u, role_id, "SAVED")
    assert "match_score" not in json.dumps(activity_board(conn, u), default=str)
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd job_hunt && python -m pytest tests/test_store_queries.py -q
```

Expected: collection error, `ModuleNotFoundError: No module named 'src.store.queries'`.

- [ ] **Step 3: Write the minimal implementation**

Create `job_hunt/src/store/queries.py`:

```python
"""Read models for the two screens.

Every function here is the boundary between storage and rendering. The internal
`match_score` is used for ordering and for deriving a company's state, then
dropped — it must not reach a template or a JSON response.
"""
import json
import sqlite3

from .db import transaction

_ACTIVITY_COLUMNS = ("SAVED", "APPLIED", "INTERVIEWING", "OFFER", "CLOSED")


def mark_seen(conn: sqlite3.Connection, user_id: int, run_id: int) -> None:
    """Record that the user has looked at the map up to this run."""
    with transaction(conn):
        conn.execute("UPDATE user SET last_seen_run_id = ? WHERE id = ?",
                     (run_id, user_id))


def _role_view(row: sqlite3.Row) -> dict:
    """Shape a role for the renderers. Drops match_score."""
    return {
        "id":                   row["id"],
        "title":                row["title"],
        "location":             row["location"],
        "salary":               row["salary"],
        "platform":             row["platform"],
        "date":                 row["posted_date"],
        "url":                  row["url"],
        "description":          row["description"],
        "description_captured": bool(row["description_captured"]),
        "band":                 row["band"],
        "reason":               row["reason"],
        "matched":              json.loads(row["matched"]),
        "gaps":                 json.loads(row["gaps"]),
    }


def _why(roles: list[sqlite3.Row]) -> str:
    n = len(roles)
    noun, verb = ("role", "matches") if n == 1 else ("roles", "match")
    lead = f"{n} {noun} {verb} your target titles"
    for row in roles:
        named = json.loads(row["matched"])
        if named:
            return f"{lead}, naming {named[0]} among others"
    if not roles[0]["description_captured"]:
        return f"{lead}, descriptions not captured yet"
    return lead


def _group(conn, rows, shortlist_min) -> list[dict]:
    """Group role rows into ranked company maps."""
    by_company: dict[int, list] = {}
    for row in rows:
        by_company.setdefault(row["company_id"], []).append(row)

    maps = []
    for company_id, group in by_company.items():
        group.sort(key=lambda r: -(r["match_score"] or 0))
        best = group[0]["match_score"] or 0
        name = conn.execute("SELECT name FROM company WHERE id = ?",
                            (company_id,)).fetchone()["name"]
        maps.append({
            "id":    company_id,
            "name":  name,
            "state": "ACT_NOW" if best >= shortlist_min else "DISCOVER",
            "why":   _why(group),
            "roles": [_role_view(r) for r in group],
            "_rank": best,
        })
    maps.sort(key=lambda m: (0 if m["state"] == "ACT_NOW" else 1, -m["_rank"],
                             m["name"].lower()))
    for m in maps:
        del m["_rank"]
    return maps


_OPEN_ROLES = """
SELECT r.* FROM role r
  JOIN company c ON c.id = r.company_id
  LEFT JOIN application a ON a.role_id = r.id
 WHERE r.user_id = ?
   AND a.id IS NULL
   AND c.user_state != 'HIDDEN'
   AND r.first_seen_run_id {op} ?
"""


def map_sections(conn: sqlite3.Connection, user_id: int,
                 shortlist_min: int = 7) -> dict:
    """The three sections of the map screen."""
    seen = conn.execute("SELECT last_seen_run_id FROM user WHERE id = ?",
                        (user_id,)).fetchone()["last_seen_run_id"] or 0

    new_rows = conn.execute(_OPEN_ROLES.format(op=">"), (user_id, seen)).fetchall()
    old_rows = conn.execute(_OPEN_ROLES.format(op="<="), (user_id, seen)).fetchall()

    new = _group(conn, new_rows, shortlist_min) if new_rows else []
    earlier = _group(conn, old_rows, shortlist_min) if old_rows else []
    listed = {m["id"] for m in new} | {m["id"] for m in earlier}

    watching = [
        {"id": r["id"], "name": r["name"], "state": "WATCH", "roles": [],
         "why": "watched — nothing open right now"}
        for r in conn.execute(
            "SELECT id, name FROM company WHERE user_id = ? AND user_state = 'WATCH'"
            " ORDER BY name", (user_id,))
        if r["id"] not in listed
    ]
    return {"new": new, "earlier": earlier, "watching": watching}


def activity_board(conn: sqlite3.Connection, user_id: int) -> dict:
    """Roles the user has acted on, grouped by status, oldest first."""
    board: dict[str, list] = {col: [] for col in _ACTIVITY_COLUMNS}
    rows = conn.execute(
        """SELECT r.id, r.title, r.url, r.location, c.name AS company,
                  a.status, a.applied_at, a.updated_at
             FROM application a
             JOIN role r ON r.id = a.role_id
             JOIN company c ON c.id = r.company_id
            WHERE a.user_id = ?
            ORDER BY a.updated_at""", (user_id,)).fetchall()

    for row in rows:
        status = row["status"]
        column = "CLOSED" if status in ("REJECTED", "CLOSED") else status
        if column not in board:          # HIDDEN has no column
            continue
        board[column].append({
            "role_id":    row["id"],
            "title":      row["title"],
            "company":    row["company"],
            "location":   row["location"],
            "url":        row["url"],
            "status":     status,
            "updated_at": row["updated_at"],
            "events": [dict(e) for e in conn.execute(
                "SELECT from_status, to_status, at FROM event"
                " WHERE role_id = ? AND kind = 'STATUS' ORDER BY at, id",
                (row["id"],))],
        })
    return board
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd job_hunt && python -m pytest tests/test_store_queries.py -q
```

Expected: `14 passed`.

- [ ] **Step 5: Commit**

```bash
git add job_hunt/src/store/queries.py job_hunt/tests/test_store_queries.py
git commit -m "feat: read models for the map and activity screens"
```

---

## Task 6: The pipeline writes into the store

**Files:**
- Modify: `job_hunt/main.py` (the `run_pipeline` function and `_launch_map`)
- Test: `job_hunt/tests/test_pipeline_store.py`

- [ ] **Step 1: Write the failing test**

Create `job_hunt/tests/test_pipeline_store.py`:

```python
"""The pipeline persists what it scrapes."""
import pytest

from src.store.db import connect
from src.store.schema import init_db
from src.store.ingest import ensure_user
from src.pipeline_store import persist_run


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "test.db")
    init_db(c)
    return c


def _job(url):
    return {"company": "Acme", "title": "Analytics Engineer", "url": url,
            "location": "Remote", "salary": "", "platform": "LinkedIn",
            "date": "2026-08-08", "description": "dbt",
            "description_captured": True, "match_score": 9,
            "band": "STRONG FIT", "reason": "matches dbt",
            "matched": ["dbt"], "gaps": []}


def test_persist_run_records_a_completed_run(conn):
    user_id = ensure_user(conn, "G")
    run_id = persist_run(conn, user_id, [_job("https://x/1")], scraped=5)
    row = conn.execute("SELECT * FROM run WHERE id = ?", (run_id,)).fetchone()
    assert row["status"] == "OK"
    assert row["scraped"] == 5
    assert row["kept"] == 1


def test_persist_run_stores_the_roles(conn):
    user_id = ensure_user(conn, "G")
    persist_run(conn, user_id, [_job("https://x/1"), _job("https://x/2")],
                scraped=2)
    assert conn.execute("SELECT COUNT(*) c FROM role").fetchone()["c"] == 2


def test_a_failed_run_is_marked_failed(conn):
    user_id = ensure_user(conn, "G")
    bad = _job("https://x/1")
    del bad["title"]
    with pytest.raises(KeyError):
        persist_run(conn, user_id, [bad], scraped=1)
    row = conn.execute("SELECT * FROM run ORDER BY id DESC LIMIT 1").fetchone()
    assert row["status"] == "FAILED"
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd job_hunt && python -m pytest tests/test_pipeline_store.py -q
```

Expected: collection error, `ModuleNotFoundError: No module named 'src.pipeline_store'`.

- [ ] **Step 3: Write the minimal implementation**

Create `job_hunt/src/pipeline_store.py`:

```python
"""Bridge between the scrape pipeline and the store.

Kept separate from `main.py` so the persistence path is testable without
running a scrape.
"""
import sqlite3

from .store.ingest import finish_run, start_run, upsert_jobs


def persist_run(conn: sqlite3.Connection, user_id: int,
                scored_jobs: list[dict], scraped: int) -> int:
    """Write a completed scrape. Marks the run FAILED if ingest raises."""
    run_id = start_run(conn, user_id)
    try:
        upsert_jobs(conn, user_id, run_id, scored_jobs)
    except Exception:
        finish_run(conn, run_id, scraped=scraped, kept=0, ok=False)
        raise
    finish_run(conn, run_id, scraped=scraped, kept=len(scored_jobs))
    return run_id
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd job_hunt && python -m pytest tests/test_pipeline_store.py -q
```

Expected: `3 passed`.

- [ ] **Step 5: Wire it into `main.py`**

In `job_hunt/main.py`, replace the body of `_launch_map` with a version that
persists first. Find:

```python
    # ── Opportunity map ────────────────────────────────────────────────────
    # Built from this run's jobs only — the map is a daily "today" view, not
    # the full tracker history.
    _launch_map(scored_jobs, shortlist_min)
```

Replace with:

```python
    # ── Persist and render ─────────────────────────────────────────────────
    _persist_and_launch(scored_jobs, len(all_scraped), shortlist_min, config)
```

Then add this function beside `_launch_map`, leaving `_launch_map` unchanged:

```python
def _persist_and_launch(scored_jobs: list[dict], scraped: int,
                        shortlist_min: int, config: dict) -> None:
    """Write the run to the store, then render the map from it."""
    from src.pipeline_store import persist_run
    from src.store.db import connect
    from src.store.ingest import ensure_user
    from src.store.schema import init_db

    conn = connect()
    init_db(conn)
    user_id = ensure_user(conn,
                          config.get("resume", {}).get("candidate_name") or "default")
    try:
        persist_run(conn, user_id, scored_jobs, scraped)
        print(f"  Stored {len(scored_jobs)} roles.")
    except Exception as e:
        logger.warning("Persisting the run failed: %s", e)
    finally:
        conn.close()
    _launch_map(scored_jobs, shortlist_min)
```

- [ ] **Step 6: Verify the whole suite still passes**

```bash
cd job_hunt && python -m py_compile main.py && python -m pytest tests/ -q
```

Expected: `main.py` compiles, all tests pass.

- [ ] **Step 7: Commit**

```bash
git add job_hunt/src/pipeline_store.py job_hunt/tests/test_pipeline_store.py job_hunt/main.py
git commit -m "feat: pipeline writes each run into the store"
```

---

## Task 7: Flask app serving the map read-only

**Files:**
- Create: `job_hunt/src/app.py`
- Modify: `job_hunt/requirements.txt`
- Test: `job_hunt/tests/test_app.py`

- [ ] **Step 1: Add Flask to requirements**

Append to `job_hunt/requirements.txt`:

```
flask>=3.0
```

Install it:

```bash
pip install "flask>=3.0"
```

- [ ] **Step 2: Write the failing test**

Create `job_hunt/tests/test_app.py`:

```python
"""Tests for src/app.py — routes, not SQL."""
import pytest

from src.app import create_app
from src.store.db import connect
from src.store.schema import init_db
from src.store.ingest import ensure_user, start_run, finish_run, upsert_jobs


def _job(url, title="Analytics Engineer"):
    return {"company": "Acme", "title": title, "url": url,
            "location": "Remote", "salary": "", "platform": "LinkedIn",
            "date": "2026-08-08", "description": "dbt",
            "description_captured": True, "match_score": 9,
            "band": "STRONG FIT", "reason": "matches dbt",
            "matched": ["dbt"], "gaps": []}


@pytest.fixture
def client(tmp_path):
    db = tmp_path / "test.db"
    conn = connect(db)
    init_db(conn)
    user_id = ensure_user(conn, "G")
    run_id = start_run(conn, user_id)
    upsert_jobs(conn, user_id, run_id, [_job("https://x/1")])
    finish_run(conn, run_id, scraped=1, kept=1)
    conn.close()
    app = create_app(db_path=db, user_name="G")
    app.config.update(TESTING=True)
    return app.test_client()


def test_map_route_renders(client):
    r = client.get("/")
    assert r.status_code == 200
    assert b"Acme" in r.data


def test_map_route_shows_the_band_and_reason(client):
    body = client.get("/").data.decode("utf-8").split("<script>")[0]
    assert "STRONG FIT" in body
    assert "matches dbt" in body


def test_no_score_reaches_the_response(client):
    assert b"match_score" not in client.get("/").data


def test_activity_route_renders(client):
    r = client.get("/activity")
    assert r.status_code == 200


def test_unknown_route_is_404(client):
    assert client.get("/nope").status_code == 404
```

- [ ] **Step 3: Run the tests to verify they fail**

```bash
cd job_hunt && python -m pytest tests/test_app.py -q
```

Expected: collection error, `ModuleNotFoundError: No module named 'src.app'`.

- [ ] **Step 4: Write the minimal implementation**

Create `job_hunt/src/app.py`:

```python
"""Flask routes.

No SQL lives here. Routes call the store and hand read models to renderers.
Binds to localhost only — this is a local application, not a service.
"""
from pathlib import Path

from flask import Flask, jsonify, request

from .activity_page import render as render_activity
from .map_page import render as render_map
from .store.db import DEFAULT_PATH, connect
from .store.ingest import ensure_user
from .store.queries import activity_board, map_sections, mark_seen
from .store.schema import init_db
from .store.tracking import COMPANY_STATES, STATUSES, set_company_state, set_role_status


def create_app(db_path: Path | str = DEFAULT_PATH,
               user_name: str = "default",
               shortlist_min: int = 7) -> Flask:
    app = Flask(__name__)

    def _conn():
        conn = connect(db_path)
        init_db(conn)
        return conn

    def _user(conn) -> int:
        return ensure_user(conn, user_name)

    @app.get("/")
    def map_screen():
        conn = _conn()
        try:
            user_id = _user(conn)
            sections = map_sections(conn, user_id, shortlist_min)
            latest = conn.execute(
                "SELECT MAX(id) AS i FROM run WHERE user_id = ?",
                (user_id,)).fetchone()["i"]
            html = render_map(
                sections["new"] + sections["earlier"] + sections["watching"],
                meta={"companies": len(sections["new"]) + len(sections["earlier"]),
                      "roles": sum(len(m["roles"]) for m in
                                   sections["new"] + sections["earlier"])})
            if latest:
                mark_seen(conn, user_id, latest)
            return html
        finally:
            conn.close()

    @app.get("/activity")
    def activity_screen():
        conn = _conn()
        try:
            return render_activity(activity_board(conn, _user(conn)))
        finally:
            conn.close()

    @app.post("/api/roles/<int:role_id>/status")
    def set_status(role_id: int):
        status = (request.get_json(silent=True) or {}).get("status", "")
        if status not in STATUSES:
            return jsonify({"error": "unknown status"}), 400
        conn = _conn()
        try:
            set_role_status(conn, _user(conn), role_id, status)
            return jsonify({"role_id": role_id, "status": status})
        finally:
            conn.close()

    @app.post("/api/companies/<int:company_id>/state")
    def set_state(company_id: int):
        state = (request.get_json(silent=True) or {}).get("state", "")
        if state not in COMPANY_STATES:
            return jsonify({"error": "unknown state"}), 400
        conn = _conn()
        try:
            set_company_state(conn, _user(conn), company_id, state)
            return jsonify({"company_id": company_id, "state": state})
        finally:
            conn.close()

    return app
```

- [ ] **Step 5: Run the tests**

```bash
cd job_hunt && python -m pytest tests/test_app.py -q
```

Expected: FAIL — `ModuleNotFoundError: No module named 'src.activity_page'`. That
module arrives in Task 8; proceed there and return to this test.

- [ ] **Step 6: Commit**

```bash
git add job_hunt/src/app.py job_hunt/tests/test_app.py job_hunt/requirements.txt
git commit -m "feat: flask routes for the map, activity and write endpoints"
```

---

## Task 8: The activity screen renderer

**Files:**
- Create: `job_hunt/src/activity_page.py`
- Test: `job_hunt/tests/test_activity_page.py`

- [ ] **Step 1: Write the failing test**

Create `job_hunt/tests/test_activity_page.py`:

```python
"""Tests for src/activity_page.py."""
import re

from src.activity_page import render


def _card(title="Analytics Engineer", company="Acme", status="SAVED"):
    return {"role_id": 1, "title": title, "company": company,
            "location": "Remote", "url": "https://example.com/1",
            "status": status, "updated_at": "2026-08-10T09:00:00",
            "events": [{"from_status": "NEW", "to_status": "SAVED",
                        "at": "2026-08-10T09:00:00"}]}


def _board(**kw):
    base = {"SAVED": [], "APPLIED": [], "INTERVIEWING": [], "OFFER": [],
            "CLOSED": []}
    return {**base, **kw}


def test_all_columns_render_even_when_empty():
    html = render(_board())
    for label in ("saved", "applied", "interviewing", "offer"):
        assert label in html.lower()


def test_cards_appear_in_their_column():
    html = render(_board(APPLIED=[_card(status="APPLIED")]))
    assert "Analytics Engineer" in html
    assert "Acme" in html


def test_column_counts_are_shown():
    html = render(_board(SAVED=[_card(), _card(title="Data Engineer")]))
    assert "2" in html


def test_event_log_is_rendered():
    html = render(_board(SAVED=[_card()]))
    assert "2026-08-10" in html


def test_no_numeric_score_is_rendered():
    html = render(_board(SAVED=[_card()]))
    assert "match_score" not in html
    assert not re.search(r"\d+%", html)


def test_output_is_a_full_document():
    html = render(_board())
    assert html.lstrip().startswith("<!DOCTYPE html>")


def test_titles_are_escaped():
    html = render(_board(SAVED=[_card(title="<script>alert(1)</script>")]))
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd job_hunt && python -m pytest tests/test_activity_page.py -q
```

Expected: collection error, `ModuleNotFoundError: No module named 'src.activity_page'`.

- [ ] **Step 3: Write the minimal implementation**

Create `job_hunt/src/activity_page.py`:

```python
"""Renders the activity screen.

Reuses the paper palette from the handoff. Four live columns plus a closed
section, oldest first within each column so the thing waiting longest is on top.
"""
from datetime import date, datetime
from html import escape

_COLUMNS = [("SAVED", "saved"), ("APPLIED", "applied"),
            ("INTERVIEWING", "interviewing"), ("OFFER", "offer")]

_CSS = """
*{box-sizing:border-box}
html,body{margin:0;background:#F7F2E6}
body{font-family:Inter,system-ui,sans-serif;color:#2A3342;-webkit-font-smoothing:antialiased}
a{color:#D6482B;text-decoration:none}
.page{min-height:100vh;background-image:radial-gradient(rgba(42,51,66,.14) 1px,transparent 1px);background-size:22px 22px;background-position:11px 11px;padding:0 0 80px}
.hatch{height:26px;background-image:repeating-linear-gradient(112deg,rgba(59,126,168,.28) 0 1px,transparent 1px 7px);mask-image:linear-gradient(to bottom,#000,transparent);-webkit-mask-image:linear-gradient(to bottom,#000,transparent)}
.head{display:flex;justify-content:center;padding:30px 40px 30px}
.head-in{flex:1;max-width:1180px;display:flex;align-items:flex-end;justify-content:space-between;gap:32px}
.title{font:600 46px/1 Caveat,cursive;color:#D6482B}
.sub{font:400 15px/1.6 Inter,sans-serif;color:#4C5768;margin-top:10px;max-width:46ch}
.nav{font:500 11px/1 'JetBrains Mono',monospace;color:#6E7787;letter-spacing:.1em}
.wrap{display:flex;justify-content:center;padding:0 40px}
.cols{flex:1;max-width:1180px;display:grid;grid-template-columns:repeat(4,1fr);gap:14px}
.colhead{display:flex;align-items:baseline;gap:8px;padding-bottom:10px;border-bottom:1px solid #E0D8C4}
.colname{font:600 22px/1.2 Caveat,cursive;color:#2E7D5B}
.colcount{margin-left:auto;font:500 10.5px/1 'JetBrains Mono',monospace;color:#8A93A1;letter-spacing:.1em}
.stack{display:flex;flex-direction:column;gap:10px;margin-top:14px}
.card{background:#FFFDF8;border:1px solid #E0D8C4;border-radius:4px;padding:13px 15px}
.co{font:500 10.5px/1 'JetBrains Mono',monospace;color:#8A93A1;letter-spacing:.1em}
.rt{font:500 15px/1.3 Inter,sans-serif;color:#1F2937;margin-top:6px}
.loc{font:400 11.5px/1 'JetBrains Mono',monospace;color:#6E7787;margin-top:6px}
.log{margin-top:10px;padding-top:9px;border-top:1px solid #EBE3D2}
.ev{font:400 11.5px/1.6 'JetBrains Mono',monospace;color:#8A93A1}
.empty{font:400 13px/1.6 Inter,sans-serif;color:#8A93A1;margin-top:14px}
.closed{max-width:1180px;margin:34px auto 0;padding:0 40px}
.closed-h{font:600 22px/1.2 Caveat,cursive;color:#6E7787;padding-bottom:10px;border-bottom:1px solid #E0D8C4}
.closed-l{font:400 13px/1.9 Inter,sans-serif;color:#8A93A1;margin-top:12px}
"""


def _e(value) -> str:
    return escape(str(value or ""), quote=True)


def _days(iso: str) -> str:
    try:
        then = datetime.fromisoformat(str(iso).replace("Z", "")).date()
        n = max(0, (date.today() - then).days)
        return "today" if n == 0 else f"{n}d"
    except (ValueError, TypeError):
        return ""


def _card(card: dict) -> str:
    events = "".join(
        f'<div class="ev">{_e(str(e["at"])[:10])} &middot; '
        f'{_e((e["to_status"] or "").lower())}</div>'
        for e in card.get("events") or []
    )
    log = f'<div class="log">{events}</div>' if events else ""
    return (
        f'<div class="card"><div class="co">{_e(card["company"].upper())}</div>'
        f'<div class="rt"><a href="{_e(card["url"])}" target="_blank" '
        f'rel="noopener">{_e(card["title"])}</a></div>'
        f'<div class="loc">{_e(card.get("location"))} &middot; '
        f'{_e(_days(card.get("updated_at")))} in this state</div>{log}</div>'
    )


def _column(key: str, label: str, cards: list[dict]) -> str:
    body = ("".join(_card(c) for c in cards) if cards
            else '<div class="empty">nothing here yet</div>')
    return (
        f'<div><div class="colhead"><div class="colname">{label}</div>'
        f'<div class="colcount">{len(cards)}</div></div>'
        f'<div class="stack">{body}</div></div>'
    )


def render(board: dict) -> str:
    """Render the activity board. `board` comes from queries.activity_board."""
    columns = "".join(_column(key, label, board.get(key) or [])
                      for key, label in _COLUMNS)
    closed = board.get("CLOSED") or []
    closed_html = ""
    if closed:
        items = "".join(
            f'<div class="closed-l">{_e(c["company"])} &middot; {_e(c["title"])} '
            f'&middot; {_e(c["status"].lower())}</div>' for c in closed)
        closed_html = (f'<div class="closed"><div class="closed-h">closed</div>'
                       f'{items}</div>')
    live = sum(len(board.get(k) or []) for k, _ in _COLUMNS)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Activity</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Caveat:wght@500;600&family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">
<style>{_CSS}</style>
</head>
<body>
<div class="page">
<div class="hatch"></div>
<div class="head"><div class="head-in">
<div>
<div class="title">in flight</div>
<div class="sub">{live} things you have moved on. Oldest at the top of each column.</div>
</div>
<div class="nav"><a href="/">&larr; BACK TO MAP</a></div>
</div></div>
<div class="wrap"><div class="cols">{columns}</div></div>
{closed_html}
</div>
</body>
</html>
"""
```

- [ ] **Step 4: Run both test files**

```bash
cd job_hunt && python -m pytest tests/test_activity_page.py tests/test_app.py -q
```

Expected: `12 passed` — Task 7's tests now pass too.

- [ ] **Step 5: Commit**

```bash
git add job_hunt/src/activity_page.py job_hunt/tests/test_activity_page.py
git commit -m "feat: activity screen showing saved, applied, interviewing and offer"
```

---

## Task 9: The map's three sections

The spec requires "new since your last visit", "still here from earlier" and the
watch shelf as distinct sections. Task 7 concatenates them into one list, which
loses the distinction entirely — a user returning after three days cannot tell
today's finds from Monday's.

`render` keeps its existing signature so the twenty tests already written
against it continue to pass. Each map may now carry a `section` key; maps
without one are treated as `new`.

**Files:**
- Modify: `job_hunt/src/map_page.py` (the `render` function)
- Modify: `job_hunt/src/app.py` (the `map_screen` route)
- Test: `job_hunt/tests/test_map_page.py`

- [ ] **Step 1: Write the failing test**

Append to `job_hunt/tests/test_map_page.py`:

```python
# ── Sections ──────────────────────────────────────────────────────────────────

def test_earlier_section_gets_a_heading():
    new = _map(name="Fresh Co")
    new["section"] = "new"
    old = _map(name="Older Co")
    old["section"] = "earlier"
    body = _body(render([new, old]))
    assert "still here from earlier" in body
    assert body.index("Fresh Co") < body.index("still here from earlier")
    assert body.index("still here from earlier") < body.index("Older Co")


def test_no_earlier_heading_when_nothing_is_earlier():
    m = _map()
    m["section"] = "new"
    assert "still here from earlier" not in render([m])


def test_maps_without_a_section_are_treated_as_new():
    """Keeps the in-memory render path working before the store exists."""
    body = _body(render([_map()]))
    assert "Acme Analytics" in body
    assert "still here from earlier" not in body
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd job_hunt && python -m pytest tests/test_map_page.py -q
```

Expected: FAIL — `"still here from earlier" not in body`.

- [ ] **Step 3: Add the section heading helper to `job_hunt/src/map_page.py`**

Add beside the other helpers:

```python
def _section_heading(label: str) -> str:
    return (f'<div class="fold"><i></i><span>{_e(label.upper())}</span>'
            f'<i></i></div>')
```

- [ ] **Step 4: Split the card loop in `render`**

In `render`, replace this block:

```python
    visible = listed[:_LEAD_VISIBLE]
    for i, m in enumerate(visible):
        if not m.get("roles"):
            continue
        key = keys[id(m)]
        body.append(_lead_card(m, key) if i == 0 and act_now
                    else _compact_card(m, key))

    remaining = len(listed) - len(visible)
    if remaining > 0:
        noun = "COMPANY" if remaining == 1 else "COMPANIES"
        body.append(f'<div class="fold"><i></i><span>{remaining} MORE {noun} '
                    f'WITH OPEN ROLES</span><i></i></div>')
```

with:

```python
    fresh = [m for m in listed if m.get("section", "new") == "new"]
    earlier = [m for m in listed if m.get("section") == "earlier"]

    def _emit(group: list[dict], allow_lead: bool) -> None:
        for i, m in enumerate(group[:_LEAD_VISIBLE]):
            if not m.get("roles"):
                continue
            key = keys[id(m)]
            body.append(_lead_card(m, key) if i == 0 and allow_lead and act_now
                        else _compact_card(m, key))
        left = len(group) - len(group[:_LEAD_VISIBLE])
        if left > 0:
            noun = "COMPANY" if left == 1 else "COMPANIES"
            body.append(f'<div class="fold"><i></i><span>{left} MORE {noun} '
                        f'WITH OPEN ROLES</span><i></i></div>')

    _emit(fresh, allow_lead=True)
    if earlier:
        body.append(_section_heading("still here from earlier"))
        _emit(earlier, allow_lead=False)
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
cd job_hunt && python -m pytest tests/test_map_page.py -q
```

Expected: all pass, including the twenty written earlier.

- [ ] **Step 6: Tag the sections in `job_hunt/src/app.py`**

In the `map_screen` route, replace:

```python
            html = render_map(
                sections["new"] + sections["earlier"] + sections["watching"],
```

with:

```python
            tagged = (
                [{**m, "section": "new"} for m in sections["new"]]
                + [{**m, "section": "earlier"} for m in sections["earlier"]]
                + [{**m, "section": "watching"} for m in sections["watching"]]
            )
            html = render_map(
                tagged,
```

- [ ] **Step 7: Run the app tests**

```bash
cd job_hunt && python -m pytest tests/test_app.py tests/test_map_page.py -q
```

Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add job_hunt/src/map_page.py job_hunt/src/app.py job_hunt/tests/test_map_page.py
git commit -m "feat: separate today's finds from roles still here from earlier"
```

---

## Task 10: Wire the map's buttons to the endpoints

**Files:**
- Modify: `job_hunt/src/map_page.py` (the `_actions` function and the `_JS` block)
- Test: `job_hunt/tests/test_map_page.py`

- [ ] **Step 1: Write the failing test**

Append to `job_hunt/tests/test_map_page.py`:

```python
# ── Wiring to the store ───────────────────────────────────────────────────────

def test_buttons_carry_their_role_and_company_ids():
    m = _map()
    m["id"] = 7
    m["roles"][0]["id"] = 42
    html = render([m])
    assert 'data-role="42"' in html
    assert 'data-company="7"' in html


def test_save_and_hide_actions_are_present():
    m = _map()
    m["id"] = 7
    m["roles"][0]["id"] = 42
    body = _body(render([m]))
    assert 'data-status="SAVED"' in body
    assert 'data-status="HIDDEN"' in body


def test_watch_posts_a_company_state():
    m = _map()
    m["id"] = 7
    m["roles"][0]["id"] = 42
    assert 'data-state="WATCH"' in _body(render([m]))


def test_missing_ids_do_not_break_rendering():
    """Rendering from an in-memory run, before the store exists, still works."""
    html = render([_map()])
    assert "Acme Analytics" in html
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd job_hunt && python -m pytest tests/test_map_page.py -q
```

Expected: FAIL on `data-role="42"` not found.

- [ ] **Step 3: Update `_actions` in `job_hunt/src/map_page.py`**

Replace the whole `_actions` function with:

```python
def _actions(company_key: str, company_id=None, role_id=None,
             watchable: bool = True) -> str:
    """Action row. Data attributes are the wiring to the write endpoints."""
    ids = ""
    if role_id is not None:
        ids += f' data-role="{_e(role_id)}"'
    if company_id is not None:
        ids += f' data-company="{_e(company_id)}"'
    save = (f'<button type="button" class="btn-q" data-status="SAVED"{ids}>SAVE</button>'
            if role_id is not None else "")
    watch = (f'<button type="button" class="btn-q" data-state="WATCH"{ids}>WATCH</button>'
             if watchable else "")
    return (
        f'<div class="acts">'
        f'<button type="button" class="btn" data-open="{_e(company_key)}">REVIEW ROLE</button>'
        f'{save}{watch}'
        f'<button type="button" class="btn-q btn-hide" data-status="HIDDEN"{ids}>HIDE</button>'
        f'</div>'
    )
```

- [ ] **Step 4: Pass the ids from both card builders**

In `_lead_card`, replace `{_actions(key)}` with:

```python
{_actions(key, m.get("id"), role.get("id"))}
```

In `_compact_card`, replace `{_actions(key)}` with:

```python
{_actions(key, m.get("id"), role.get("id"))}
```

- [ ] **Step 5: Add the fetch handler to the `_JS` block**

Insert this immediately before the final `document.addEventListener('keydown'...` line inside `_JS`:

```javascript
async function post(url, body){
  const r = await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  if(r.ok){location.reload();}
}
document.addEventListener('click',function(e){
  const s=e.target.closest('[data-status]');
  if(s&&s.dataset.role){post('/api/roles/'+s.dataset.role+'/status',{status:s.dataset.status});return;}
  const w=e.target.closest('[data-state]');
  if(w&&w.dataset.company){post('/api/companies/'+w.dataset.company+'/state',{state:w.dataset.state});}
});
```

- [ ] **Step 6: Run the tests**

```bash
cd job_hunt && python -m pytest tests/test_map_page.py tests/test_app.py -q
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add job_hunt/src/map_page.py job_hunt/tests/test_map_page.py
git commit -m "feat: wire save, watch and hide to the write endpoints"
```

---

## Task 11: Serve from `main.py`

**Files:**
- Modify: `job_hunt/main.py` (the `main` function and `_persist_and_launch`)

- [ ] **Step 1: Add the `--serve` flag**

In `job_hunt/main.py`, inside `main()`, after the existing `--jd` argument, add:

```python
    parser.add_argument("--serve", action="store_true",
                        help="Serve the app without scraping")
    parser.add_argument("--port", type=int, default=5000,
                        help="Port for the local app (default 5000)")
```

- [ ] **Step 2: Add the serve branch**

Still in `main()`, replace:

```python
    if args.tailor:
        if not args.jd:
            print("ERROR: --jd <file.txt> is required with --tailor")
            sys.exit(1)
        run_tailor(config, args.jd)
    else:
        run_pipeline(config)
```

with:

```python
    if args.tailor:
        if not args.jd:
            print("ERROR: --jd <file.txt> is required with --tailor")
            sys.exit(1)
        run_tailor(config, args.jd)
    elif args.serve:
        _serve(config, args.port)
    else:
        run_pipeline(config)
        _serve(config, args.port)
```

- [ ] **Step 3: Add the `_serve` function beside `_persist_and_launch`**

```python
def _serve(config: dict, port: int) -> None:
    """Run the local app. Binds to localhost only."""
    import webbrowser

    from src.app import create_app

    shortlist_min = config.get("tailoring", {}).get("shortlist_score", 7)
    name = config.get("resume", {}).get("candidate_name") or "default"
    app = create_app(user_name=name, shortlist_min=shortlist_min)
    url = f"http://127.0.0.1:{port}/"
    print(f"\n  Opportunity map: {url}")
    print("  Ctrl-C to stop.")
    webbrowser.open(url)
    app.run(host="127.0.0.1", port=port, debug=False)
```

- [ ] **Step 4: Remove the now-redundant static render**

In `_persist_and_launch`, delete the final line:

```python
    _launch_map(scored_jobs, shortlist_min)
```

The app renders the map from the store now. Leave the `_launch_map` function
itself in place — it is still useful for generating a static page without the
server.

- [ ] **Step 5: Verify**

```bash
cd job_hunt && python -m py_compile main.py && python -m pytest tests/ -q
```

Expected: compiles, all tests pass.

Then manually, with no database present:

```bash
cd job_hunt && python main.py --serve
```

Expected: the browser opens on `http://127.0.0.1:5000/`, the page renders with
no companies, and no traceback appears.

- [ ] **Step 6: Commit**

```bash
git add job_hunt/main.py
git commit -m "feat: main.py serves the local app after scraping"
```

---

## Task 12: End-to-end check against the acceptance criteria

**Files:**
- Test: `job_hunt/tests/test_end_to_end.py`

- [ ] **Step 1: Write the test**

Create `job_hunt/tests/test_end_to_end.py`:

```python
"""Acceptance criteria from the spec, exercised through the app."""
import json

import pytest

from src.app import create_app
from src.store.db import connect
from src.store.ingest import ensure_user, finish_run, start_run, upsert_jobs
from src.store.schema import init_db


def _job(url, title="Analytics Engineer", **kw):
    base = {"company": "Acme", "title": title, "url": url, "location": "Remote",
            "salary": "", "platform": "LinkedIn", "date": "2026-08-08",
            "description": "dbt", "description_captured": True,
            "match_score": 9, "band": "STRONG FIT", "reason": "matches dbt",
            "matched": ["dbt"], "gaps": []}
    return {**base, **kw}


@pytest.fixture
def env(tmp_path):
    db = tmp_path / "e2e.db"
    conn = connect(db)
    init_db(conn)
    user_id = ensure_user(conn, "G")
    run_id = start_run(conn, user_id)
    upsert_jobs(conn, user_id, run_id, [_job("https://x/1")])
    finish_run(conn, run_id, scraped=1, kept=1)
    role_id = conn.execute("SELECT id FROM role").fetchone()["id"]
    conn.close()
    app = create_app(db_path=db, user_name="G")
    app.config.update(TESTING=True)
    return app.test_client(), db, role_id


def test_criterion_2_a_status_change_persists(env):
    client, db, role_id = env
    assert client.post(f"/api/roles/{role_id}/status",
                       json={"status": "APPLIED"}).status_code == 200
    conn = connect(db)
    assert conn.execute(
        "SELECT status FROM application").fetchone()["status"] == "APPLIED"
    conn.close()


def test_criterion_5_applied_leaves_the_map_for_the_board(env):
    client, _, role_id = env
    client.post(f"/api/roles/{role_id}/status", json={"status": "APPLIED"})
    assert b"Analytics Engineer" not in client.get("/").data
    assert b"Analytics Engineer" in client.get("/activity").data


def test_criterion_6_the_event_log_has_a_row_per_move(env):
    client, db, role_id = env
    for status in ("SAVED", "APPLIED", "INTERVIEWING"):
        client.post(f"/api/roles/{role_id}/status", json={"status": status})
    conn = connect(db)
    rows = conn.execute(
        "SELECT to_status FROM event WHERE role_id=? ORDER BY id",
        (role_id,)).fetchall()
    conn.close()
    assert [r["to_status"] for r in rows] == ["SAVED", "APPLIED", "INTERVIEWING"]


def test_criterion_7_pragmas_hold_on_a_fresh_connection(env):
    _, db, _ = env
    conn = connect(db)
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    conn.close()


def test_criterion_8_an_invalid_status_is_refused(env):
    client, _, role_id = env
    assert client.post(f"/api/roles/{role_id}/status",
                       json={"status": "MAYBE"}).status_code == 400


def test_criterion_9_no_score_in_any_response(env):
    client, _, role_id = env
    client.post(f"/api/roles/{role_id}/status", json={"status": "SAVED"})
    for path in ("/", "/activity"):
        assert b"match_score" not in client.get(path).data


def test_criterion_10_a_missing_database_is_created_on_demand(tmp_path):
    app = create_app(db_path=tmp_path / "brand-new.db", user_name="G")
    app.config.update(TESTING=True)
    assert app.test_client().get("/").status_code == 200
```

- [ ] **Step 2: Run it**

```bash
cd job_hunt && python -m pytest tests/test_end_to_end.py -q
```

Expected: `7 passed`.

- [ ] **Step 3: Run the whole suite**

```bash
cd job_hunt && python -m pytest tests/ -q
```

Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add job_hunt/tests/test_end_to_end.py
git commit -m "test: acceptance criteria exercised end to end"
```

---

## Task 13: Retire the dead dashboard

The job-list dashboard is superseded. Its only remaining use is `open_browser`,
which `_launch_map` imports.

**Files:**
- Modify: `job_hunt/src/map_page.py`
- Modify: `job_hunt/main.py`
- Delete: `job_hunt/src/dashboard.py`, `job_hunt/tests/test_dashboard.py`

- [ ] **Step 1: Move `open_browser` into `map_page.py`**

Append to `job_hunt/src/map_page.py`:

```python
def open_browser(path) -> None:
    """Open a generated page in the system browser."""
    import os
    import subprocess

    try:
        os.startfile(str(path))              # Windows
    except AttributeError:
        subprocess.Popen(["open", str(path)])  # macOS
    except Exception:
        print(f"  Open manually: {path}")
```

- [ ] **Step 2: Update the import in `main.py`**

In `_launch_map`, replace:

```python
    from src.dashboard import open_browser
    from src.map_page import render
```

with:

```python
    from src.map_page import open_browser, render
```

- [ ] **Step 3: Confirm nothing else imports the dashboard**

```bash
cd job_hunt && grep -rn "dashboard" --include=*.py . | grep -v __pycache__
```

Expected: only `src/dashboard.py` and `tests/test_dashboard.py` appear.

- [ ] **Step 4: Delete the dead files**

```bash
git rm job_hunt/src/dashboard.py job_hunt/tests/test_dashboard.py
```

- [ ] **Step 5: Verify**

```bash
cd job_hunt && python -m py_compile main.py && python -m pytest tests/ -q
```

Expected: compiles, all remaining tests pass.

- [ ] **Step 6: Commit**

```bash
git commit -m "refactor: retire the job-list dashboard superseded by the map"
```

---

## Done when

All thirteen tasks are committed, the full suite passes, and:

```bash
cd job_hunt && python main.py --serve
```

opens a working map at `http://127.0.0.1:5000/` where SAVE, WATCH and HIDE
persist across a restart, and `/activity` shows what you have in flight.
