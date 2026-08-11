# Resume Profile — Ship 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A user can upload a PDF resume, have it parsed into target roles, skills and seniority, correct the result on a confirm screen, and manage several resumes from a profile page — all persisted in the SQLite store.

**Architecture:** Schema version 1 → 2 introduces the project's first real migration (`PRAGMA user_version` + `ALTER TABLE`), a `resume` table, and profile columns on `user`. A new store module owns resume and profile reads/writes; a new intake module owns upload validation and file storage; a new agent module owns the LLM parse. Three new server-rendered screens reuse the existing paper palette. Nothing in the scrape, scoring, or map path is touched — Ship 1 is deliberately inert, reached by URL only.

**Tech Stack:** Python 3, SQLite (stdlib `sqlite3`), Flask 3, pdfminer.six, vanilla HTML/CSS/JS (no JS toolchain), pytest.

**Spec:** `docs/superpowers/specs/2026-08-11-resume-profile-and-search-design.md`

**Scope note:** The spec defines three ships. This plan covers **Ship 1 only**. Ship 2 (vocabulary.yaml split, scorer rewrite, scrapers take location/work modes) and Ship 3 (background run, progress screen, `/` routing) get their own plans, written after Ship 1 lands — their tasks depend on the exact shape of what Ship 1 builds, so writing them now would be speculative.

**Deliberate deviation from the spec, flagged:** the spec's confirm screen ends with `LOOKS RIGHT — START SEARCHING`. Ship 1 has no search to start, so the button reads `SAVE THIS PROFILE` and lands on `/profile`. Ship 3 renames it and wires it to `POST /api/runs`.

**Working directory for every command below:** `job_hunt/`.

**Baseline before starting:** `python -m pytest tests/ -q` → `230 passed`.

---

## File Structure

| File | Responsibility |
| --- | --- |
| `src/store/schema.py` (modify) | DDL + the version 1 → 2 migration. Constraints live in SQL, not Python. |
| `src/store/profile.py` (create) | The only place that reads or writes `user` profile columns and the `resume` table. |
| `src/resume_intake.py` (create) | Upload validation and file storage. No database, no Flask — testable without a request. |
| `src/agents/profile_parser.py` (create) | Resume text → `{target_roles, skills, seniority}` via the LLM, normalised so a bad reply cannot poison the store. |
| `src/setup_page.py` (create) | Renders the three new screens. Same shape as `map_page.py` / `activity_page.py`: module-level `_CSS`, `_JS`, `render_*` functions returning a full HTML document. |
| `src/app.py` (modify) | Seven new routes. No SQL here — routes call the store. |
| `.gitignore` (modify) | Exclude `job_hunt/data/` — uploaded resumes are personal data. |

Tests mirror the source: `tests/test_store_migration.py`, `tests/test_store_profile.py`, `tests/test_resume_intake.py`, `tests/test_profile_parser.py`, `tests/test_setup_page.py`, `tests/test_setup_routes.py`.

---

### Task 1: Schema version 2 and the migration

**Files:**
- Modify: `src/store/schema.py`
- Test: `tests/test_store_migration.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_store_migration.py`:

```python
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_store_migration.py -v`

Expected: FAIL. `test_the_migration_adds_every_version_two_column` fails on the missing `location` column; `test_a_fresh_database_lands_on_version_two` fails because `PRAGMA user_version` is 1.

- [ ] **Step 3: Write the implementation**

Replace the whole of `src/store/schema.py` with:

```python
"""Schema definition and migrations.

Constraints live here rather than in Python. A status typo should be rejected
by the database, not caught by whichever caller happened to remember to check.

Migrations are forward-only. `_DDL` is the current shape — a fresh database
gets it whole. `_MIGRATIONS` carries what an older database needs to catch up,
keyed by the version it arrives at.
"""
import sqlite3

from .db import transaction

SCHEMA_VERSION = 2

_DDL = """
CREATE TABLE IF NOT EXISTS user (
    id               INTEGER PRIMARY KEY,
    name             TEXT NOT NULL,
    email            TEXT,
    last_seen_run_id INTEGER,
    created_at       TEXT NOT NULL,
    location         TEXT,
    country          TEXT,
    work_modes       TEXT,
    setup_complete   INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS run (
    id          INTEGER PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES user(id),
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    status      TEXT NOT NULL CHECK (status IN ('RUNNING','OK','FAILED')),
    scraped     INTEGER NOT NULL DEFAULT 0,
    kept        INTEGER NOT NULL DEFAULT 0,
    stage       TEXT,
    progress    TEXT NOT NULL DEFAULT '{}',
    error       TEXT
);

CREATE TABLE IF NOT EXISTS resume (
    id             INTEGER PRIMARY KEY,
    user_id        INTEGER NOT NULL REFERENCES user(id),
    label          TEXT NOT NULL,
    orig_filename  TEXT NOT NULL,
    sha256         TEXT NOT NULL,
    stored_path    TEXT NOT NULL,
    extracted_text TEXT NOT NULL,
    seniority      TEXT CHECK (seniority IN ('junior','mid','senior','exec')),
    skills         TEXT NOT NULL DEFAULT '[]',
    target_roles   TEXT NOT NULL DEFAULT '[]',
    is_active      INTEGER NOT NULL DEFAULT 1,
    created_at     TEXT NOT NULL,
    UNIQUE (user_id, label),
    UNIQUE (user_id, sha256)
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
    resume_id            INTEGER REFERENCES resume(id),
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
CREATE INDEX IF NOT EXISTS idx_resume_user ON resume(user_id, is_active);
"""

# SQLite allows ADD COLUMN with a REFERENCES clause only when the new column
# defaults to NULL, and allows NOT NULL only with a non-null default. Both
# rules are already satisfied below; changing a default here can break the
# migration on a populated database.
_MIGRATIONS: dict[int, tuple[str, ...]] = {
    2: (
        "ALTER TABLE user ADD COLUMN location TEXT",
        "ALTER TABLE user ADD COLUMN country TEXT",
        "ALTER TABLE user ADD COLUMN work_modes TEXT",
        "ALTER TABLE user ADD COLUMN setup_complete INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE role ADD COLUMN resume_id INTEGER REFERENCES resume(id)",
        "ALTER TABLE run ADD COLUMN stage TEXT",
        "ALTER TABLE run ADD COLUMN progress TEXT NOT NULL DEFAULT '{}'",
        "ALTER TABLE run ADD COLUMN error TEXT",
    ),
}


def _is_fresh(conn: sqlite3.Connection) -> bool:
    """True when nothing has ever been created in this file.

    A brand-new file and a version-1 file both need the DDL, but only the
    version-1 file needs the ALTERs — running them on a fresh database would
    raise 'duplicate column name'.
    """
    return conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='user'"
    ).fetchone() is None


def init_db(conn: sqlite3.Connection) -> None:
    """Create or migrate the schema. Safe to call on every start.

    Never call this from inside a `transaction()` block — `executescript`
    always issues an implicit COMMIT first, which would commit the block's
    BEGIN out from under it.
    """
    fresh = _is_fresh(conn)
    version = 0 if fresh else conn.execute("PRAGMA user_version").fetchone()[0]

    conn.executescript(_DDL)

    if not fresh and version < SCHEMA_VERSION:
        with transaction(conn):
            for target in range(version + 1, SCHEMA_VERSION + 1):
                for statement in _MIGRATIONS.get(target, ()):
                    conn.execute(statement)

    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_store_migration.py tests/test_store_schema.py -v`

Expected: PASS — 5 new tests plus the 10 existing schema tests.

- [ ] **Step 5: Run the whole suite**

Run: `python -m pytest tests/ -q`

Expected: `235 passed`. Nothing else touches the schema module, so no existing test should change.

- [ ] **Step 6: Commit**

```bash
git add job_hunt/src/store/schema.py job_hunt/tests/test_store_migration.py && git commit -m "feat: schema version 2 with a forward-only migration"
```

---

### Task 2: The user half of the profile

**Files:**
- Create: `src/store/profile.py`
- Test: `tests/test_store_profile.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_store_profile.py`:

```python
"""Tests for src/store/profile.py — the user's profile and their resumes."""
import pytest

from src.store.db import connect
from src.store.ingest import ensure_user
from src.store.profile import get_profile, set_profile
from src.store.schema import init_db


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "test.db")
    init_db(c)
    return c


@pytest.fixture
def user_id(conn):
    return ensure_user(conn, "G")


def test_a_new_user_has_an_empty_profile(conn, user_id):
    assert get_profile(conn, user_id) == {
        "location": "", "country": "", "work_modes": [],
        "setup_complete": False}


def test_setting_the_profile_marks_setup_complete(conn, user_id):
    set_profile(conn, user_id, location="Toronto, ON", country="CA",
                work_modes=["remote", "hybrid"])
    assert get_profile(conn, user_id) == {
        "location": "Toronto, ON", "country": "ca",
        "work_modes": ["remote", "hybrid"], "setup_complete": True}


def test_an_unknown_work_mode_is_rejected(conn, user_id):
    with pytest.raises(ValueError, match="hybrid-ish"):
        set_profile(conn, user_id, location="Toronto",
                    country="ca", work_modes=["hybrid-ish"])
    assert get_profile(conn, user_id)["setup_complete"] is False


def test_at_least_one_work_mode_is_required(conn, user_id):
    with pytest.raises(ValueError, match="work mode"):
        set_profile(conn, user_id, location="Toronto",
                    country="ca", work_modes=[])


def test_the_profile_of_a_missing_user_raises(conn):
    with pytest.raises(ValueError, match="no user"):
        get_profile(conn, 9999)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_store_profile.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'src.store.profile'`.

- [ ] **Step 3: Write the implementation**

Create `src/store/profile.py`:

```python
"""The user's profile and the resumes they own.

Where you live is a property of the person, not of a PDF; target roles and
skills are properties of one tailored document. That split is the reason this
module exists rather than more columns on `user`.

`skills` and `target_roles` are JSON columns, matching the `role.matched` and
`role.gaps` precedent. They are read whole and written whole by the confirm
screen; normalising them into child tables buys a query nobody has asked for.
"""
import sqlite3
from datetime import datetime, timezone

from .db import transaction

WORK_MODES = ("remote", "hybrid", "onsite")
SENIORITIES = ("junior", "mid", "senior", "exec")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def get_profile(conn: sqlite3.Connection, user_id: int) -> dict:
    """Location, country and work modes for one user."""
    row = conn.execute(
        """SELECT location, country, work_modes, setup_complete
           FROM user WHERE id = ?""", (user_id,)).fetchone()
    if row is None:
        raise ValueError(f"no user {user_id}")
    return {
        "location": row["location"] or "",
        "country": row["country"] or "",
        "work_modes": [m for m in (row["work_modes"] or "").split(",") if m],
        "setup_complete": bool(row["setup_complete"]),
    }


def set_profile(conn: sqlite3.Connection, user_id: int, *,
                location: str, country: str, work_modes: list[str]) -> None:
    """Write the half of setup a resume cannot state, and mark setup done.

    Validation happens before the transaction opens so a bad value never
    starts a write.
    """
    unknown = [m for m in work_modes if m not in WORK_MODES]
    if unknown:
        raise ValueError(f"unknown work mode: {unknown[0]!r}")
    if not work_modes:
        raise ValueError("at least one work mode is required")

    with transaction(conn):
        conn.execute(
            """UPDATE user SET location = ?, country = ?, work_modes = ?,
                   setup_complete = 1
               WHERE id = ?""",
            (location.strip(), country.strip().lower(),
             ",".join(work_modes), user_id))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_store_profile.py -v`

Expected: PASS, 5 tests.

- [ ] **Step 5: Commit**

```bash
git add job_hunt/src/store/profile.py job_hunt/tests/test_store_profile.py && git commit -m "feat: store the user's location and work modes"
```

---

### Task 3: Resume records

**Files:**
- Modify: `src/store/profile.py`
- Test: `tests/test_store_profile.py` (append)
- Test: `tests/test_store_schema.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_store_profile.py`:

```python
import sqlite3

from src.store.profile import (create_resume, delete_resume, get_resume,
                               list_resumes, resume_by_sha, unique_label,
                               update_resume)


def _add(conn, user_id, label="bi developer", sha="abc123"):
    return create_resume(conn, user_id, label=label,
                         orig_filename="Ghazal BI.pdf", sha256=sha,
                         stored_path=f"resumes/{user_id}/{sha}.pdf",
                         extracted_text="Power BI, SQL, dbt")


def test_a_new_resume_starts_active_and_unparsed(conn, user_id):
    resume_id = _add(conn, user_id)
    resume = get_resume(conn, user_id, resume_id)
    assert resume["label"] == "bi developer"
    assert resume["orig_filename"] == "Ghazal BI.pdf"
    assert resume["extracted_text"] == "Power BI, SQL, dbt"
    assert resume["skills"] == []
    assert resume["target_roles"] == []
    assert resume["seniority"] is None
    assert resume["is_active"] is True


def test_the_same_file_cannot_be_uploaded_twice(conn, user_id):
    _add(conn, user_id, label="one", sha="same")
    with pytest.raises(sqlite3.IntegrityError):
        _add(conn, user_id, label="two", sha="same")


def test_two_resumes_cannot_share_a_label(conn, user_id):
    _add(conn, user_id, label="bi developer", sha="a")
    with pytest.raises(sqlite3.IntegrityError):
        _add(conn, user_id, label="bi developer", sha="b")


def test_updating_writes_roles_skills_and_seniority(conn, user_id):
    resume_id = _add(conn, user_id)
    update_resume(
        conn, user_id, resume_id, label="bi dev",
        target_roles=[{"title": "BI Developer", "aliases": ["bi engineer"]}],
        skills=[{"name": "Power BI", "tier": "core", "aliases": ["dax"]}],
        seniority="senior")
    resume = get_resume(conn, user_id, resume_id)
    assert resume["label"] == "bi dev"
    assert resume["target_roles"][0]["aliases"] == ["bi engineer"]
    assert resume["skills"][0]["tier"] == "core"
    assert resume["seniority"] == "senior"


def test_an_unknown_seniority_is_rejected(conn, user_id):
    resume_id = _add(conn, user_id)
    with pytest.raises(ValueError, match="seniority"):
        update_resume(conn, user_id, resume_id, label="x", target_roles=[],
                      skills=[], seniority="grand wizard")


def test_updating_someone_elses_resume_raises(conn, user_id):
    resume_id = _add(conn, user_id)
    other = ensure_user(conn, "Other")
    with pytest.raises(LookupError):
        update_resume(conn, other, resume_id, label="x", target_roles=[],
                      skills=[], seniority="mid")


def test_listing_can_be_narrowed_to_active_resumes(conn, user_id):
    first = _add(conn, user_id, label="one", sha="a")
    _add(conn, user_id, label="two", sha="b")
    update_resume(conn, user_id, first, label="one", target_roles=[],
                  skills=[], seniority="mid", is_active=False)
    assert len(list_resumes(conn, user_id)) == 2
    assert [r["label"] for r in list_resumes(conn, user_id, active_only=True)] == ["two"]


def test_deleting_returns_the_stored_path_and_frees_the_label(conn, user_id):
    resume_id = _add(conn, user_id, label="one", sha="a")
    assert delete_resume(conn, user_id, resume_id) == f"resumes/{user_id}/a.pdf"
    assert get_resume(conn, user_id, resume_id) is None
    _add(conn, user_id, label="one", sha="c")   # the label is free again


def test_deleting_a_missing_resume_returns_none(conn, user_id):
    assert delete_resume(conn, user_id, 9999) is None


def test_resume_by_sha_finds_a_duplicate_upload(conn, user_id):
    _add(conn, user_id, sha="deadbeef")
    assert resume_by_sha(conn, user_id, "deadbeef") is not None
    assert resume_by_sha(conn, user_id, "nope") is None


def test_unique_label_counts_up_around_collisions(conn, user_id):
    assert unique_label(conn, user_id, "Ghazal Resume") == "ghazal resume"
    _add(conn, user_id, label="ghazal resume", sha="a")
    assert unique_label(conn, user_id, "Ghazal Resume") == "ghazal resume 2"
    _add(conn, user_id, label="ghazal resume 2", sha="b")
    assert unique_label(conn, user_id, "Ghazal Resume") == "ghazal resume 3"


def test_unique_label_falls_back_when_the_filename_gives_nothing(conn, user_id):
    assert unique_label(conn, user_id, "") == "resume"
```

Append to `tests/test_store_schema.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_store_profile.py tests/test_store_schema.py -v`

Expected: FAIL with `ImportError: cannot import name 'create_resume'` for the profile tests; the two schema tests pass already (the constraints landed in Task 1) — that is fine, they are regression cover.

- [ ] **Step 3: Write the implementation**

Append to `src/store/profile.py`:

```python
def _row_to_resume(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "label": row["label"],
        "orig_filename": row["orig_filename"],
        "sha256": row["sha256"],
        "stored_path": row["stored_path"],
        "extracted_text": row["extracted_text"],
        "seniority": row["seniority"],
        "skills": json.loads(row["skills"]),
        "target_roles": json.loads(row["target_roles"]),
        "is_active": bool(row["is_active"]),
        "created_at": row["created_at"],
    }


def create_resume(conn: sqlite3.Connection, user_id: int, *, label: str,
                  orig_filename: str, sha256: str, stored_path: str,
                  extracted_text: str) -> int:
    """Insert an unparsed resume and return its id.

    Raises sqlite3.IntegrityError when the label is taken or the same file has
    already been uploaded.
    """
    with transaction(conn):
        conn.execute(
            """INSERT INTO resume (user_id, label, orig_filename, sha256,
                   stored_path, extracted_text, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (user_id, label, orig_filename, sha256, stored_path,
             extracted_text, _now()))
    return conn.execute("SELECT last_insert_rowid() AS i").fetchone()["i"]


def get_resume(conn: sqlite3.Connection, user_id: int,
               resume_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM resume WHERE id = ? AND user_id = ?",
                       (resume_id, user_id)).fetchone()
    return _row_to_resume(row) if row else None


def resume_by_sha(conn: sqlite3.Connection, user_id: int,
                  sha256: str) -> dict | None:
    row = conn.execute("SELECT * FROM resume WHERE user_id = ? AND sha256 = ?",
                       (user_id, sha256)).fetchone()
    return _row_to_resume(row) if row else None


def list_resumes(conn: sqlite3.Connection, user_id: int,
                 active_only: bool = False) -> list[dict]:
    sql = "SELECT * FROM resume WHERE user_id = ?"
    if active_only:
        sql += " AND is_active = 1"
    sql += " ORDER BY created_at, id"
    return [_row_to_resume(r) for r in conn.execute(sql, (user_id,))]


def update_resume(conn: sqlite3.Connection, user_id: int, resume_id: int, *,
                  label: str, target_roles: list[dict], skills: list[dict],
                  seniority: str, is_active: bool = True) -> None:
    """Overwrite everything the confirm screen owns.

    Raises ValueError on an unknown seniority, LookupError when the resume is
    not this user's, sqlite3.IntegrityError when the label is taken.
    """
    if seniority not in SENIORITIES:
        raise ValueError(f"unknown seniority: {seniority!r}")

    with transaction(conn):
        cursor = conn.execute(
            """UPDATE resume SET label = ?, target_roles = ?, skills = ?,
                   seniority = ?, is_active = ?
               WHERE id = ? AND user_id = ?""",
            (label, json.dumps(target_roles), json.dumps(skills),
             seniority, 1 if is_active else 0, resume_id, user_id))
        if cursor.rowcount == 0:
            raise LookupError(f"no resume {resume_id} for user {user_id}")


def delete_resume(conn: sqlite3.Connection, user_id: int,
                  resume_id: int) -> str | None:
    """Remove the row; return the stored path so the caller can unlink the file.

    Roles this resume won keep their scores and lose only the attribution —
    dropping a resume must not delete anything the user found through it.
    """
    row = conn.execute(
        "SELECT stored_path FROM resume WHERE id = ? AND user_id = ?",
        (resume_id, user_id)).fetchone()
    if row is None:
        return None
    with transaction(conn):
        conn.execute("UPDATE role SET resume_id = NULL WHERE resume_id = ?",
                     (resume_id,))
        conn.execute("DELETE FROM resume WHERE id = ? AND user_id = ?",
                     (resume_id, user_id))
    return row["stored_path"]


def unique_label(conn: sqlite3.Connection, user_id: int, base: str) -> str:
    """A label this user is not already using: `resume`, then `resume 2`, ...

    The caller passes the uploaded filename's stem, which is why this
    lowercases and truncates rather than trusting it.
    """
    base = (base or "").strip().lower()[:40] or "resume"
    taken = {r["label"] for r in conn.execute(
        "SELECT label FROM resume WHERE user_id = ?", (user_id,))}
    if base not in taken:
        return base
    suffix = 2
    while f"{base} {suffix}" in taken:
        suffix += 1
    return f"{base} {suffix}"
```

Add `import json` to the imports at the top of `src/store/profile.py`, so the header reads:

```python
import json
import sqlite3
from datetime import datetime, timezone
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_store_profile.py tests/test_store_schema.py -v`

Expected: PASS — 16 profile tests, 12 schema tests.

- [ ] **Step 5: Commit**

```bash
git add job_hunt/src/store/profile.py job_hunt/tests/test_store_profile.py job_hunt/tests/test_store_schema.py && git commit -m "feat: create, read, update and delete resumes"
```

---

### Task 4: Upload validation and storage

**Files:**
- Create: `src/resume_intake.py`
- Test: `tests/test_resume_intake.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_resume_intake.py`:

```python
"""Tests for src/resume_intake.py — what is allowed in, and where it lands."""
import hashlib

import pytest

from src.resume_intake import (MAX_BYTES, UploadRejected, digest, store,
                               validate)

_PDF = b"%PDF-1.4\nnot really a pdf but it starts like one\n"


def test_a_pdf_is_accepted():
    validate("resume.pdf", _PDF)          # does not raise


def test_a_non_pdf_extension_is_rejected():
    with pytest.raises(UploadRejected, match="not a PDF"):
        validate("resume.docx", _PDF)


def test_a_pdf_extension_over_something_else_is_rejected():
    """The extension is a claim; the leading bytes are the evidence."""
    with pytest.raises(UploadRejected, match="not a PDF"):
        validate("resume.pdf", b"PK\x03\x04 this is a zip")


def test_an_empty_file_says_so():
    with pytest.raises(UploadRejected, match="empty"):
        validate("resume.pdf", b"")


def test_a_file_over_the_cap_is_rejected():
    oversized = _PDF + b"x" * MAX_BYTES
    with pytest.raises(UploadRejected, match="5 MB"):
        validate("resume.pdf", oversized)


def test_digest_is_the_sha256_of_the_bytes():
    assert digest(_PDF) == hashlib.sha256(_PDF).hexdigest()


def test_store_writes_under_the_user_folder_named_by_hash(tmp_path):
    relative = store(tmp_path, user_id=7, sha256=digest(_PDF), data=_PDF)
    assert relative == f"resumes/7/{digest(_PDF)}.pdf"
    assert (tmp_path / relative).read_bytes() == _PDF


def test_the_clients_filename_never_reaches_the_path(tmp_path):
    """A crafted filename must not escape the data root — the stored name is
    the content hash, and the client's name is display only."""
    relative = store(tmp_path, user_id=7, sha256=digest(_PDF), data=_PDF)
    written = list((tmp_path / "resumes" / "7").iterdir())
    assert [p.name for p in written] == [f"{digest(_PDF)}.pdf"]
    assert ".." not in relative


def test_storing_the_same_bytes_twice_is_idempotent(tmp_path):
    first = store(tmp_path, user_id=1, sha256=digest(_PDF), data=_PDF)
    second = store(tmp_path, user_id=1, sha256=digest(_PDF), data=_PDF)
    assert first == second
    assert len(list((tmp_path / "resumes" / "1").iterdir())) == 1
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_resume_intake.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'src.resume_intake'`.

- [ ] **Step 3: Write the implementation**

Create `src/resume_intake.py`:

```python
"""Taking a resume file in.

Validation lives here rather than in the route, so the rules can be tested
without building a request. PDF only, because pdfminer is the only extractor
present — a .docx has to be refused with a message rather than accepted and
failed later, halfway through a parse.

The client's filename is never used to build a path. The stored name is the
content hash, so a filename of `../../secrets` writes exactly where every
other upload writes.
"""
import hashlib
from pathlib import Path

MAX_BYTES = 5 * 1024 * 1024
_PDF_MAGIC = b"%PDF-"


class UploadRejected(Exception):
    """The file cannot be accepted. The message is shown to the user."""


def validate(filename: str, data: bytes) -> None:
    """Raise UploadRejected unless this is a PDF within the size cap."""
    if not data:
        raise UploadRejected("That file is empty.")
    if len(data) > MAX_BYTES:
        raise UploadRejected(
            f"That file is larger than {MAX_BYTES // (1024 * 1024)} MB. "
            "Export a smaller PDF and try again.")
    if not filename.lower().endswith(".pdf") or not data.startswith(_PDF_MAGIC):
        raise UploadRejected(
            "That is not a PDF. Only PDF resumes can be read at the moment.")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def store(data_root: Path | str, user_id: int, sha256: str,
          data: bytes) -> str:
    """Write the PDF under the data root. Returns the path relative to it."""
    relative = f"resumes/{user_id}/{sha256}.pdf"
    target = Path(data_root) / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return relative
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_resume_intake.py -v`

Expected: PASS, 9 tests.

- [ ] **Step 5: Commit**

```bash
git add job_hunt/src/resume_intake.py job_hunt/tests/test_resume_intake.py && git commit -m "feat: validate and store an uploaded resume PDF"
```

---

### Task 5: Parsing a resume into a profile

**Files:**
- Create: `src/agents/profile_parser.py`
- Test: `tests/test_profile_parser.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_profile_parser.py`:

```python
"""Tests for src/agents/profile_parser.py.

The normalisation half matters more than the prompt half: an LLM that returns
a bare string where an object belongs must not put a row into the database
that the scorer cannot read.
"""
import json

import pytest

from src.agents.profile_parser import parse_profile
from tests.conftest import MockLLMClient

_GOOD = json.dumps({
    "target_roles": [
        {"title": "BI Developer", "aliases": ["Business Intelligence Developer"]},
        {"title": "Analytics Engineer", "aliases": []}],
    "skills": [
        {"name": "Power BI", "tier": "core", "aliases": ["PowerBI", "DAX"]},
        {"name": "Airflow", "tier": "working", "aliases": []}],
    "seniority": "senior",
})


def test_a_clean_reply_comes_through_whole():
    result = parse_profile("resume text", MockLLMClient(_GOOD))
    assert result["seniority"] == "senior"
    assert [r["title"] for r in result["target_roles"]] == [
        "BI Developer", "Analytics Engineer"]
    assert result["skills"][0]["tier"] == "core"
    assert result["skills"][1]["tier"] == "working"


def test_aliases_are_lowercased_for_matching():
    """The scorer matches lowercase, so the store holds lowercase."""
    result = parse_profile("resume text", MockLLMClient(_GOOD))
    assert result["target_roles"][0]["aliases"] == [
        "business intelligence developer"]
    assert result["skills"][0]["aliases"] == ["powerbi", "dax"]


def test_prose_around_the_json_is_tolerated():
    reply = "Sure! Here you go:\n" + _GOOD + "\nHope that helps."
    assert parse_profile("resume text", MockLLMClient(reply))["seniority"] == "senior"


def test_bare_strings_are_promoted_to_objects():
    reply = json.dumps({"target_roles": ["Data Engineer"],
                        "skills": ["SQL"], "seniority": "mid"})
    result = parse_profile("resume text", MockLLMClient(reply))
    assert result["target_roles"] == [{"title": "Data Engineer", "aliases": []}]
    assert result["skills"] == [{"name": "SQL", "tier": "working", "aliases": []}]


def test_an_unknown_tier_falls_back_to_working():
    reply = json.dumps({"target_roles": [], "seniority": "mid",
                        "skills": [{"name": "SQL", "tier": "expert"}]})
    result = parse_profile("resume text", MockLLMClient(reply))
    assert result["skills"][0]["tier"] == "working"


def test_an_unknown_seniority_falls_back_to_mid():
    reply = json.dumps({"target_roles": [], "skills": [],
                        "seniority": "grand wizard"})
    assert parse_profile("x", MockLLMClient(reply))["seniority"] == "mid"


def test_blank_titles_and_names_are_dropped():
    reply = json.dumps({"target_roles": [{"title": "  "}, {"title": "DE"}],
                        "skills": [{"name": ""}], "seniority": "mid"})
    result = parse_profile("x", MockLLMClient(reply))
    assert [r["title"] for r in result["target_roles"]] == ["DE"]
    assert result["skills"] == []


def test_the_lists_are_capped():
    reply = json.dumps({
        "target_roles": [{"title": f"Role {i}"} for i in range(12)],
        "skills": [{"name": f"Skill {i}"} for i in range(40)],
        "seniority": "mid"})
    result = parse_profile("x", MockLLMClient(reply))
    assert len(result["target_roles"]) == 5
    assert len(result["skills"]) == 20


def test_a_reply_with_no_json_raises():
    with pytest.raises(ValueError, match="no JSON"):
        parse_profile("x", MockLLMClient("I cannot help with that."))


def test_the_resume_text_reaches_the_prompt():
    class Capturing(MockLLMClient):
        def complete(self, prompt, *, system="", max_tokens=1000):
            self.seen = prompt
            return _GOOD

    llm = Capturing(_GOOD)
    parse_profile("Ghazal Izadi — Power BI developer", llm)
    assert "Ghazal Izadi" in llm.seen
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_profile_parser.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'src.agents.profile_parser'`.

- [ ] **Step 3: Write the implementation**

Create `src/agents/profile_parser.py`:

```python
"""Turning resume text into a searchable profile.

The aliases are the point. `Senior BI Developer` only scores if the resume's
target roles carry `bi developer` as something to match against, and `dax`
only counts towards Power BI if Power BI says it does. Asking the model for
aliases at upload time buys what a skill taxonomy would buy, without importing
one.

Everything the model returns is normalised before it leaves this module. The
store and the scorer are entitled to assume the shape.
"""
import json
import re

from ..llm.base import LLMClient

SENIORITIES = ("junior", "mid", "senior", "exec")
TIERS = ("core", "working")

MAX_ROLES = 5
MAX_SKILLS = 20
MAX_TEXT = 6000

_PROMPT = """Read this resume and describe the person as a job search profile.

Reply with JSON only, in exactly this shape:
{"target_roles": [{"title": "BI Developer",
                   "aliases": ["business intelligence developer", "bi engineer"]}],
 "skills": [{"name": "Power BI", "tier": "core",
             "aliases": ["powerbi", "pbi", "dax", "power query"]}],
 "seniority": "senior"}

Rules:
- target_roles: at most 5 job titles this person should be searching for.
  aliases are other titles the same job gets posted under.
- skills: at most 20. tier is "core" when the resume shows it repeatedly or in
  recent roles, "working" when it appears once or in passing. aliases are
  spellings, abbreviations, and sub-tools bound tightly enough that naming one
  means the other.
- seniority: one of junior, mid, senior, exec.
- Use only what the resume supports. Do not invent skills.

Resume text:
"""


def parse_profile(extracted_text: str, llm: LLMClient) -> dict:
    """Return {target_roles, skills, seniority} from resume text."""
    reply = llm.complete(_PROMPT + extracted_text[:MAX_TEXT], max_tokens=1200)
    match = re.search(r"\{.*\}", reply, re.DOTALL)
    if not match:
        raise ValueError(
            f"LLM ({llm.provider}) returned no JSON for the resume profile: "
            f"{reply[:200]}")
    return _normalise(json.loads(match.group()))


def _strings(value) -> list[str]:
    """Aliases are matched lowercase, so they are stored lowercase."""
    if not isinstance(value, list):
        return []
    return [str(v).strip().lower() for v in value if str(v).strip()]


def _normalise(raw: dict) -> dict:
    roles: list[dict] = []
    for item in raw.get("target_roles") or []:
        if isinstance(item, str):
            item = {"title": item}
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        if title:
            roles.append({"title": title, "aliases": _strings(item.get("aliases"))})

    skills: list[dict] = []
    for item in raw.get("skills") or []:
        if isinstance(item, str):
            item = {"name": item}
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if name:
            tier = item.get("tier")
            skills.append({
                "name": name,
                "tier": tier if tier in TIERS else "working",
                "aliases": _strings(item.get("aliases")),
            })

    seniority = str(raw.get("seniority") or "").strip().lower()
    return {
        "target_roles": roles[:MAX_ROLES],
        "skills": skills[:MAX_SKILLS],
        "seniority": seniority if seniority in SENIORITIES else "mid",
    }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_profile_parser.py -v`

Expected: PASS, 10 tests.

- [ ] **Step 5: Commit**

```bash
git add job_hunt/src/agents/profile_parser.py job_hunt/tests/test_profile_parser.py && git commit -m "feat: parse a resume into target roles, skills and seniority"
```

---

### Task 6: The page shell and the upload screen

**Files:**
- Create: `src/setup_page.py`
- Test: `tests/test_setup_page.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_setup_page.py`:

```python
"""Tests for src/setup_page.py — rendering only, no database, no Flask."""
import re

from src.setup_page import render_upload


def _visible(html: str) -> str:
    """The document with its CSS and JS stripped — what a reader actually
    sees. The product rules are about what reaches the reader, and a `%` in a
    stylesheet is not a percentage on the screen."""
    return re.sub(r"<(style|script)\b.*?</\1>", "", html, flags=re.DOTALL)


def test_the_upload_screen_is_a_whole_document():
    html = render_upload()
    assert html.startswith("<!DOCTYPE html>")
    assert "</html>" in html


def test_the_upload_screen_offers_a_pdf_file_field():
    html = render_upload()
    assert 'type="file"' in html
    assert 'name="resume"' in html
    assert 'accept="application/pdf"' in html


def test_the_upload_screen_states_the_limits():
    html = render_upload()
    assert "PDF only" in html
    assert "5 MB" in html


def test_a_message_is_shown_when_one_is_passed():
    assert "That is not a PDF." in render_upload("That is not a PDF.")


def test_a_message_is_escaped():
    """The page carries its own <script> block, so check for the escaped
    form rather than the absence of the tag."""
    html = render_upload("<script>alert(1)</script>")
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "alert(1)</script>" not in html
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_setup_page.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'src.setup_page'`.

- [ ] **Step 3: Write the implementation**

Create `src/setup_page.py`:

```python
"""Renders the setup screens — upload, confirm, and the resume list.

Same paper palette as the map and the activity board, same shape: a module
holding its own CSS and JS, and functions that return whole documents. The
project generates static pages from Python and has no JS toolchain.

The confirm screen is the one place the scoring model is authored by hand, so
everything on it is editable. Aliases are carried in the page's JS state
rather than shown — a list of synonyms is not something a person wants to
proofread, and it is the model's job to get them roughly right.
"""
import json
from html import escape

_CSS = """
*{box-sizing:border-box}
html,body{margin:0;background:#F7F2E6}
body{font-family:Inter,system-ui,sans-serif;color:#2A3342;-webkit-font-smoothing:antialiased}
a{color:#D6482B;text-decoration:none}
a:hover{color:#A83519}
.page{min-height:100vh;background-image:radial-gradient(rgba(42,51,66,.14) 1px,transparent 1px);background-size:22px 22px;background-position:11px 11px;padding:0 0 80px}
.hatch{height:26px;background-image:repeating-linear-gradient(112deg,rgba(59,126,168,.28) 0 1px,transparent 1px 7px);mask-image:linear-gradient(to bottom,#000,transparent);-webkit-mask-image:linear-gradient(to bottom,#000,transparent)}
.head{display:flex;justify-content:center;padding:30px 40px 30px}
.head-in{flex:1;max-width:820px;display:flex;align-items:flex-end;justify-content:space-between;gap:32px}
.title{font:600 46px/1 Caveat,cursive;color:#D6482B}
.sub{font:400 15px/1.6 Inter,sans-serif;color:#4C5768;margin-top:10px;max-width:48ch;text-wrap:pretty}
.nav{font:500 11px/1 'JetBrains Mono',monospace;color:#6E7787;letter-spacing:.1em}
.wrap{display:flex;justify-content:center;padding:0 40px}
.col{flex:1;max-width:820px;display:flex;flex-direction:column;gap:16px;min-width:0}
.card{background:#FFFDF8;border:1px solid #E0D8C4;border-radius:4px;padding:22px 26px}
.lab{font:500 9.5px/1 'JetBrains Mono',monospace;color:#6E7787;letter-spacing:.11em;display:block;margin-bottom:9px}
.row{margin-top:20px}
.row:first-child{margin-top:0}
input[type=text]{width:100%;padding:9px 11px;border:1px solid #E0D8C4;border-radius:3px;background:#FFFDF8;font:400 14.5px/1.4 Inter,sans-serif;color:#2A3342}
input[type=text]:focus{outline:0;border-color:#2E7D5B}
.chips{display:flex;flex-wrap:wrap;gap:6px;align-items:center}
.chip{display:inline-flex;align-items:center;gap:7px;font:400 12.5px/1.3 Inter,sans-serif;padding:5px 9px;border-radius:2px;background:#EAF2ED;border:1px solid #C3DACD;color:#215E44}
.chip-w{background:transparent;border:1px dashed #C9BFA8;color:#4C5768}
.chip button{border:0;background:transparent;padding:0;cursor:pointer;color:inherit;font:400 13px/1 Inter,sans-serif}
.add{width:auto;min-width:190px;padding:5px 9px;font-size:12.5px}
.opts{display:flex;flex-wrap:wrap;gap:16px;font:400 14px/1.4 Inter,sans-serif;color:#3A4557}
.opts label{display:inline-flex;align-items:center;gap:7px;cursor:pointer}
.note{font:400 13px/1.6 Inter,sans-serif;color:#8A93A1;margin-top:9px;text-wrap:pretty}
.err{color:#A83519}
.warn{background:#F4EFE1;border:1px dashed #C9BFA8;border-radius:3px;padding:11px 13px;font:400 13.5px/1.6 Inter,sans-serif;color:#6E7787;margin-bottom:18px;text-wrap:pretty}
.foot{display:flex;align-items:center;gap:12px;margin-top:26px;padding-top:18px;border-top:1px solid #EBE3D2}
.btn-p{display:inline-block;padding:9px 16px;border:1px solid #D6482B;background:#D6482B;border-radius:3px;color:#FFFDF8;font:500 11px/1 'JetBrains Mono',monospace;letter-spacing:.06em;cursor:pointer}
.btn-p:hover{background:#A83519;border-color:#A83519;color:#FFFDF8}
.btn-q{display:inline-block;padding:9px 14px;border:1px solid transparent;background:transparent;border-radius:3px;color:#8A93A1;font:400 11px/1 'JetBrains Mono',monospace;letter-spacing:.06em;cursor:pointer}
.btn-q:hover{color:#4C5768}
.rlist{display:flex;flex-direction:column;gap:10px;margin-top:14px}
.ritem{display:flex;align-items:baseline;gap:12px;padding:12px 14px;border:1px solid #E0D8C4;border-radius:3px;background:#FFFDF8}
.rname{font:500 15px/1.3 Inter,sans-serif;color:#1F2937}
.rmeta{margin-left:auto;font:400 10.5px/1 'JetBrains Mono',monospace;color:#8A93A1;letter-spacing:.1em}
.off{opacity:.55}
"""


def _e(value) -> str:
    return escape(str(value or ""), quote=True)


def _payload(value) -> str:
    """JSON safe to inline in a <script> block."""
    return json.dumps(value, ensure_ascii=False).replace("</", "<\\/")


def _shell(title: str, heading: str, sub: str, body: str,
           script: str = "", nav: str = "") -> str:
    script_tag = f"<script>{script}</script>" if script else ""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_e(title)}</title>
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
<div class="title">{_e(heading)}</div>
<div class="sub">{_e(sub)}</div>
</div>
<div class="nav">{nav}</div>
</div></div>
<div class="wrap"><div class="col">{body}</div></div>
</div>
{script_tag}
</body>
</html>
"""


_UPLOAD_JS = """
const form = document.getElementById('up');
const out = document.getElementById('msg');
form.addEventListener('submit', async function(e){
  e.preventDefault();
  out.className = 'note';
  out.textContent = 'Reading your resume...';
  const r = await fetch('/api/resumes', {method:'POST', body:new FormData(form)});
  const data = await r.json().catch(function(){return {};});
  if(r.ok){ location.href = '/setup/confirm/' + data.resume_id; return; }
  out.className = 'note err';
  out.textContent = data.error || 'That did not upload. Try again.';
});
"""


def render_upload(message: str = "") -> str:
    """The first screen: one file field."""
    css = "note err" if message else "note"
    body = (
        '<div class="card"><form id="up">'
        '<div class="row"><span class="lab">YOUR RESUME</span>'
        '<input type="file" name="resume" accept="application/pdf" required>'
        '<div class="note">PDF only, up to 5 MB. It stays on this machine — '
        'the file is written next to the database, not sent anywhere.</div>'
        '</div>'
        '<div class="foot">'
        '<button type="submit" class="btn-p">READ MY RESUME</button>'
        f'<span id="msg" class="{css}">{_e(message)}</span>'
        '</div></form></div>'
    )
    return _shell(
        "Set up", "start here",
        "Your resume decides what gets searched and what counts as a good "
        "fit. Nothing runs until it is in.",
        body, _UPLOAD_JS)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_setup_page.py -v`

Expected: PASS, 5 tests.

- [ ] **Step 5: Commit**

```bash
git add job_hunt/src/setup_page.py job_hunt/tests/test_setup_page.py && git commit -m "feat: render the resume upload screen"
```

---

### Task 7: The confirm screen

**Files:**
- Modify: `src/setup_page.py`
- Test: `tests/test_setup_page.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_setup_page.py`:

```python
from src.setup_page import render_confirm

_RESUME = {
    "id": 3,
    "label": "bi developer",
    "seniority": "senior",
    "target_roles": [{"title": "BI Developer", "aliases": ["bi engineer"]}],
    "skills": [{"name": "Power BI", "tier": "core", "aliases": ["dax"]},
               {"name": "Airflow", "tier": "working", "aliases": []}],
}
_EMPTY_PROFILE = {"location": "", "country": "", "work_modes": [],
                  "setup_complete": False}
_SET_PROFILE = {"location": "Toronto, ON", "country": "ca",
                "work_modes": ["remote"], "setup_complete": True}


def test_the_confirm_screen_carries_the_parsed_values_into_its_state():
    html = render_confirm(_RESUME, _EMPTY_PROFILE, ask_location=True)
    assert "BI Developer" in html
    assert "Power BI" in html
    assert '"tier": "core"' in html or '"tier":"core"' in html


def test_the_confirm_screen_preselects_the_parsed_seniority():
    html = render_confirm(_RESUME, _EMPTY_PROFILE, ask_location=True)
    assert 'value="senior" checked' in html
    assert 'value="junior" checked' not in html


def test_the_first_resume_is_asked_for_location_and_work_mode():
    html = render_confirm(_RESUME, _EMPTY_PROFILE, ask_location=True)
    assert 'id="location"' in html
    assert 'name="mode"' in html


def test_a_later_resume_skips_the_location_block():
    html = render_confirm(_RESUME, _SET_PROFILE, ask_location=False)
    assert 'id="location"' not in html
    assert 'name="mode"' not in html


def test_an_unparsed_resume_says_so_rather_than_showing_nothing():
    blank = {**_RESUME, "target_roles": [], "skills": [], "seniority": None}
    html = render_confirm(blank, _EMPTY_PROFILE, ask_location=True)
    assert "could not read this resume" in html
    assert 'value="mid" checked' in html


def test_the_resume_id_reaches_the_script():
    html = render_confirm(_RESUME, _EMPTY_PROFILE, ask_location=True)
    assert "const RESUME_ID = 3;" in html


def test_the_confirm_screen_never_shows_a_score():
    html = _visible(render_confirm(_RESUME, _EMPTY_PROFILE, ask_location=True))
    assert "match_score" not in html
    assert "%" not in html
```

Note for whoever implements Task 8: `_EMPTY_PROFILE`, `_SET_PROFILE` and
`_visible` are defined in the blocks above. Task 8's tests reuse them, so
Task 7 has to land first.

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_setup_page.py -v`

Expected: FAIL with `ImportError: cannot import name 'render_confirm' from 'src.setup_page'`.

- [ ] **Step 3: Write the implementation**

Append to `src/setup_page.py`:

```python
_CONFIRM_JS = """
let ROLES = __ROLES__;
let SKILLS = __SKILLS__;
const RESUME_ID = __RESUME_ID__;
const ASK_LOCATION = __ASK_LOCATION__;

function esc(s){const d=document.createElement('div');d.textContent=s==null?'':s;return d.innerHTML;}

function drawRoles(){
  document.getElementById('roles').innerHTML = ROLES.map(function(r,i){
    return '<span class="chip">'+esc(r.title)
      + '<button type="button" data-drop-role="'+i+'" title="remove">\\u00d7</button></span>';
  }).join('') + '<input type="text" class="add" id="add-role" placeholder="add a role, then Enter">';
}
function drawSkills(){
  document.getElementById('skills').innerHTML = SKILLS.map(function(s,i){
    const core = s.tier === 'core';
    return '<span class="chip'+(core?'':' chip-w')+'">'
      + '<button type="button" data-tier="'+i+'" title="core or working">'
      + (core?'\\u2605':'\\u2606')+'</button>'
      + esc(s.name)
      + '<button type="button" data-drop-skill="'+i+'" title="remove">\\u00d7</button></span>';
  }).join('') + '<input type="text" class="add" id="add-skill" placeholder="add a skill, then Enter">';
}
document.addEventListener('click', function(e){
  const dr = e.target.closest('[data-drop-role]');
  if(dr){ ROLES.splice(parseInt(dr.dataset.dropRole,10),1); drawRoles(); return; }
  const ds = e.target.closest('[data-drop-skill]');
  if(ds){ SKILLS.splice(parseInt(ds.dataset.dropSkill,10),1); drawSkills(); return; }
  const t = e.target.closest('[data-tier]');
  if(t){ const s = SKILLS[parseInt(t.dataset.tier,10)];
         s.tier = s.tier === 'core' ? 'working' : 'core'; drawSkills(); }
});
document.addEventListener('keydown', function(e){
  if(e.key !== 'Enter') return;
  if(e.target.id === 'add-role'){
    e.preventDefault();
    const v = e.target.value.trim();
    if(v){ ROLES.push({title:v, aliases:[]}); drawRoles();
           document.getElementById('add-role').focus(); }
  }
  if(e.target.id === 'add-skill'){
    e.preventDefault();
    const v = e.target.value.trim();
    if(v){ SKILLS.push({name:v, tier:'core', aliases:[]}); drawSkills();
           document.getElementById('add-skill').focus(); }
  }
});
async function post(url, body){
  const r = await fetch(url, {method:'POST',
                              headers:{'Content-Type':'application/json'},
                              body:JSON.stringify(body)});
  if(r.ok) return null;
  const data = await r.json().catch(function(){return {};});
  return data.error || 'That did not save.';
}
document.getElementById('save').addEventListener('click', async function(){
  const out = document.getElementById('msg');
  out.className = 'note';
  out.textContent = 'Saving...';
  const chosen = document.querySelector('input[name=seniority]:checked');
  let err = await post('/api/resumes/' + RESUME_ID, {
    label: document.getElementById('label').value.trim(),
    target_roles: ROLES,
    skills: SKILLS,
    seniority: chosen ? chosen.value : 'mid'});
  if(!err && ASK_LOCATION){
    const modes = Array.prototype.slice.call(
      document.querySelectorAll('input[name=mode]:checked')
    ).map(function(c){return c.value;});
    err = await post('/api/profile', {
      location: document.getElementById('location').value.trim(),
      country: document.getElementById('country').value.trim(),
      work_modes: modes});
  }
  if(err){ out.className = 'note err'; out.textContent = err; return; }
  location.href = '/profile';
});
drawRoles();
drawSkills();
"""


def _location_block(profile: dict) -> str:
    modes = profile.get("work_modes") or ["remote"]
    checks = "".join(
        f'<label><input type="checkbox" name="mode" value="{mode}"'
        f'{" checked" if mode in modes else ""}> {mode}</label>'
        for mode in ("remote", "hybrid", "onsite"))
    return (
        '<div class="row"><span class="lab">WHERE</span>'
        f'<input type="text" id="location" value="{_e(profile.get("location"))}"'
        ' placeholder="Toronto, ON"></div>'
        '<div class="row"><span class="lab">COUNTRY CODE</span>'
        f'<input type="text" id="country" value="{_e(profile.get("country"))}"'
        ' placeholder="ca"></div>'
        '<div class="row"><span class="lab">WORK MODE</span>'
        f'<div class="opts">{checks}</div></div>'
    )


def render_confirm(resume: dict, profile: dict, ask_location: bool) -> str:
    """The screen where the scoring model gets authored.

    `ask_location` is False for every resume after the first — where you live
    is asked once, because it belongs to the person, not to the document.
    """
    parsed = bool(resume.get("target_roles") or resume.get("skills"))
    warn = "" if parsed else (
        '<div class="warn">We could not read this resume automatically. '
        'Add your roles and skills below by hand — everything the tool does '
        'next is built on them.</div>')

    seniority = resume.get("seniority") or "mid"
    radios = "".join(
        f'<label><input type="radio" name="seniority" value="{band}"'
        f'{" checked" if band == seniority else ""}> {band}</label>'
        for band in ("junior", "mid", "senior", "exec"))

    body = (
        f'<div class="card">{warn}'
        '<div class="row"><span class="lab">LABEL</span>'
        f'<input type="text" id="label" value="{_e(resume.get("label"))}">'
        '<div class="note">What you call this version of your resume.</div></div>'
        '<div class="row"><span class="lab">TARGET ROLES</span>'
        '<div class="chips" id="roles"></div>'
        '<div class="note">These are the searches that get run.</div></div>'
        '<div class="row"><span class="lab">YOUR SKILLS</span>'
        '<div class="chips" id="skills"></div>'
        '<div class="note">A filled star is a core skill — worth more when a '
        'posting names it. Click a star to change it.</div></div>'
        '<div class="row"><span class="lab">SENIORITY</span>'
        f'<div class="opts">{radios}</div></div>'
        f'{_location_block(profile) if ask_location else ""}'
        '<div class="foot">'
        '<button type="button" id="save" class="btn-p">SAVE THIS PROFILE</button>'
        '<a class="btn-q" href="/profile">SKIP FOR NOW</a>'
        '<span id="msg" class="note"></span></div></div>'
    )

    script = (_CONFIRM_JS
              .replace("__ROLES__", _payload(resume.get("target_roles") or []))
              .replace("__SKILLS__", _payload(resume.get("skills") or []))
              .replace("__RESUME_ID__", str(int(resume["id"])))
              .replace("__ASK_LOCATION__", "true" if ask_location else "false"))

    return _shell(
        "Confirm your profile", "we read your resume as...",
        "Change anything that is wrong. Everything the tool does next is "
        "built on this.",
        body, script, nav='<a href="/profile">ALL RESUMES &rarr;</a>')
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_setup_page.py -v`

Expected: PASS, 12 tests.

- [ ] **Step 5: Commit**

```bash
git add job_hunt/src/setup_page.py job_hunt/tests/test_setup_page.py && git commit -m "feat: render the confirm screen for a parsed resume"
```

---

### Task 8: The profile screen

**Files:**
- Modify: `src/setup_page.py`
- Test: `tests/test_setup_page.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_setup_page.py`:

```python
from src.setup_page import render_profile

_RESUMES = [
    {"id": 1, "label": "bi developer", "seniority": "senior", "is_active": True,
     "target_roles": [{"title": "BI Developer", "aliases": []}],
     "skills": [{"name": "Power BI", "tier": "core", "aliases": []}]},
    {"id": 2, "label": "data engineer", "seniority": "mid", "is_active": False,
     "target_roles": [], "skills": []},
]


def test_the_profile_screen_lists_every_resume():
    html = render_profile(_RESUMES, _SET_PROFILE)
    assert "bi developer" in html
    assert "data engineer" in html


def test_an_inactive_resume_is_marked():
    assert "INACTIVE" in render_profile(_RESUMES, _SET_PROFILE)


def test_each_resume_links_to_its_confirm_screen():
    html = render_profile(_RESUMES, _SET_PROFILE)
    assert 'href="/setup/confirm/1"' in html
    assert 'data-delete="2"' in html


def test_the_profile_screen_shows_where_you_are_looking():
    html = render_profile(_RESUMES, _SET_PROFILE)
    assert "Toronto, ON" in html
    assert "remote" in html


def test_with_no_resumes_it_points_at_the_upload_screen():
    html = render_profile([], _EMPTY_PROFILE)
    assert "No resumes yet" in html
    assert 'href="/setup"' in html


def test_the_profile_screen_never_shows_a_score():
    html = _visible(render_profile(_RESUMES, _SET_PROFILE))
    assert "match_score" not in html
    assert "%" not in html
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_setup_page.py -v`

Expected: FAIL with `ImportError: cannot import name 'render_profile' from 'src.setup_page'`.

- [ ] **Step 3: Write the implementation**

Append to `src/setup_page.py`:

```python
_PROFILE_JS = """
document.addEventListener('click', async function(e){
  const d = e.target.closest('[data-delete]');
  if(!d) return;
  if(!confirm('Delete this resume? Roles it already scored keep their scores.')) return;
  const r = await fetch('/api/resumes/' + d.dataset.delete, {method:'DELETE'});
  if(r.ok){ location.reload(); } else { alert('That did not delete.'); }
});
"""


def _resume_item(resume: dict) -> str:
    active = resume.get("is_active")
    inactive_meta = "" if active else " &middot; INACTIVE"
    return (
        f'<div class="ritem{"" if active else " off"}">'
        f'<div class="rname">{_e(resume["label"])}</div>'
        f'<div class="rmeta">{len(resume.get("target_roles") or [])} ROLES '
        f'&middot; {len(resume.get("skills") or [])} SKILLS &middot; '
        f'{_e((resume.get("seniority") or "unset").upper())}{inactive_meta}</div>'
        f'<a class="btn-q" href="/setup/confirm/{int(resume["id"])}">EDIT</a>'
        f'<button type="button" class="btn-q" data-delete="{int(resume["id"])}">'
        'DELETE</button></div>'
    )


def render_profile(resumes: list[dict], profile: dict) -> str:
    """One person, many resumes. Each active one adds its roles to the search."""
    if resumes:
        listing = (f'<div class="rlist">'
                   f'{"".join(_resume_item(r) for r in resumes)}</div>')
    else:
        listing = ('<div class="note">No resumes yet. '
                   '<a href="/setup">Add one</a>.</div>')

    where = profile.get("location") or "not set"
    modes = ", ".join(profile.get("work_modes") or []) or "not set"
    body = (
        f'<div class="card"><span class="lab">YOUR RESUMES</span>{listing}'
        '<div class="foot"><a class="btn-p" href="/setup">ADD A RESUME</a>'
        '</div></div>'
        '<div class="card"><span class="lab">WHERE YOU ARE LOOKING</span>'
        f'<div class="note">{_e(where)} &middot; {_e(modes)}</div></div>'
    )
    return _shell(
        "Your profile", "your profile",
        "One person, many resumes. Each active resume adds its target roles "
        "to the search.",
        body, _PROFILE_JS, nav='<a href="/">&larr; BACK TO MAP</a>')
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_setup_page.py -v`

Expected: PASS, 18 tests.

- [ ] **Step 5: Commit**

```bash
git add job_hunt/src/setup_page.py job_hunt/tests/test_setup_page.py && git commit -m "feat: render the resume list on the profile screen"
```

---

### Task 9: The upload route

**Files:**
- Modify: `src/app.py`
- Test: `tests/test_setup_routes.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_setup_routes.py`:

```python
"""Tests for the setup routes in src/app.py.

No network: the LLM is injected. The PDF is a real, minimal one so pdfminer
does the extraction it will do in production.
"""
import io
import json
import re

import pytest

from src.app import create_app
from src.store.db import connect
from src.store.ingest import ensure_user
from src.store.schema import init_db
from tests.conftest import MockLLMClient

# A handcrafted PDF with one line of text. pdfminer reads it without an xref.
_PDF = (
    b"%PDF-1.4\n"
    b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 300 300]"
    b"/Resources<</Font<</F1 4 0 R>>>>/Contents 5 0 R>>endobj\n"
    b"4 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n"
    b"5 0 obj<</Length 62>>stream\n"
    b"BT /F1 12 Tf 20 200 Td (Power BI and SQL and dbt) Tj ET\n"
    b"endstream\nendobj\n"
    b"trailer<</Root 1 0 R/Size 6>>\n"
)

# A different resume, for the tests that need two. The replacement is exactly
# 24 bytes, the same as the text it replaces, so `/Length 62` stays honest.
_OTHER_PDF = _PDF.replace(b"Power BI and SQL and dbt",
                          b"Airflow and Python dbt..")
assert len(_OTHER_PDF) == len(_PDF)


def _visible(html: str) -> str:
    """The document with its CSS and JS stripped — what a reader sees."""
    return re.sub(r"<(style|script)\b.*?</\1>", "", html, flags=re.DOTALL)


_PARSE_REPLY = json.dumps({
    "target_roles": [{"title": "BI Developer", "aliases": ["bi engineer"]}],
    "skills": [{"name": "Power BI", "tier": "core", "aliases": ["dax"]}],
    "seniority": "senior",
})


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "test.db"
    conn = connect(path)
    init_db(conn)
    ensure_user(conn, "G")
    conn.close()
    return path


@pytest.fixture
def client(db, tmp_path):
    app = create_app(db_path=db, user_name="G",
                     data_root=tmp_path / "data",
                     llm_factory=lambda: MockLLMClient(_PARSE_REPLY))
    app.config.update(TESTING=True)
    return app.test_client()


def _upload(client, name="Ghazal BI.pdf", data=_PDF):
    return client.post("/api/resumes",
                       data={"resume": (io.BytesIO(data), name)},
                       content_type="multipart/form-data")


def test_the_setup_screen_renders(client):
    response = client.get("/setup")
    assert response.status_code == 200
    assert b"YOUR RESUME" in response.data


def test_uploading_a_pdf_returns_a_resume_id(client):
    response = _upload(client)
    assert response.status_code == 201
    assert isinstance(response.get_json()["resume_id"], int)


def test_uploading_stores_the_file_under_the_data_root(client, tmp_path):
    _upload(client)
    written = list((tmp_path / "data" / "resumes").rglob("*.pdf"))
    assert len(written) == 1
    assert written[0].read_bytes() == _PDF


def test_uploading_runs_the_parse_and_saves_the_result(client, db):
    resume_id = _upload(client).get_json()["resume_id"]
    from src.store.profile import get_resume
    conn = connect(db)
    resume = get_resume(conn, 1, resume_id)
    conn.close()
    assert resume["seniority"] == "senior"
    assert resume["target_roles"][0]["title"] == "BI Developer"
    assert resume["skills"][0]["name"] == "Power BI"
    assert "Power BI" in resume["extracted_text"]


def test_the_label_comes_from_the_filename(client, db):
    resume_id = _upload(client, name="Ghazal BI.pdf").get_json()["resume_id"]
    from src.store.profile import get_resume
    conn = connect(db)
    label = get_resume(conn, 1, resume_id)["label"]
    conn.close()
    assert label == "ghazal bi"


def test_a_second_file_with_the_same_name_gets_its_own_label(client, db):
    _upload(client, name="resume.pdf", data=_PDF)
    resume_id = _upload(client, name="resume.pdf",
                        data=_OTHER_PDF).get_json()["resume_id"]
    from src.store.profile import get_resume
    conn = connect(db)
    label = get_resume(conn, 1, resume_id)["label"]
    conn.close()
    assert label == "resume 2"


def test_the_same_file_twice_is_refused(client):
    _upload(client)
    response = _upload(client, name="a different name.pdf")
    assert response.status_code == 409
    assert "already uploaded" in response.get_json()["error"]


def test_a_non_pdf_is_refused_with_its_own_message(client):
    response = _upload(client, name="resume.docx", data=b"PK\x03\x04zip")
    assert response.status_code == 400
    assert "not a PDF" in response.get_json()["error"]


def test_an_oversized_pdf_is_refused_with_its_own_message(client):
    response = _upload(client, data=_PDF + b"x" * (5 * 1024 * 1024))
    assert response.status_code == 400
    assert "5 MB" in response.get_json()["error"]


def test_sending_no_file_is_a_400(client):
    response = client.post("/api/resumes", data={},
                           content_type="multipart/form-data")
    assert response.status_code == 400


def test_a_failing_parse_still_stores_the_resume(db, tmp_path):
    """The confirm screen asks for the details by hand rather than 500ing."""
    def _explode():
        raise RuntimeError("no API key")

    app = create_app(db_path=db, user_name="G", data_root=tmp_path / "data",
                     llm_factory=_explode)
    app.config.update(TESTING=True)
    response = _upload(app.test_client())
    assert response.status_code == 201

    from src.store.profile import get_resume
    conn = connect(db)
    resume = get_resume(conn, 1, response.get_json()["resume_id"])
    conn.close()
    assert resume["target_roles"] == []
    assert resume["seniority"] is None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_setup_routes.py -v`

Expected: FAIL with `TypeError: create_app() got an unexpected keyword argument 'data_root'`.

- [ ] **Step 3: Write the implementation**

Replace the imports and the head of `create_app` in `src/app.py`. The file's imports become:

```python
"""Flask routes.

No SQL lives here. Routes call the store and hand read models to renderers.
Binds to localhost only — this is a local application, not a service.
"""
import logging
import sqlite3
from pathlib import Path

from flask import Flask, jsonify, request

from . import resume_intake as intake
from .activity_page import render as render_activity
from .agents.profile_parser import parse_profile
from .llm.base import LLMClient
from .map_page import render as render_map
from .setup_page import render_confirm, render_profile, render_upload
from .store.db import DEFAULT_PATH, connect
from .store.ingest import ensure_user
from .store.profile import (create_resume, delete_resume, get_profile,
                            get_resume, list_resumes, resume_by_sha,
                            set_profile, unique_label, update_resume)
from .store.queries import activity_board, map_sections, mark_seen
from .store.schema import init_db
from .store.tracking import COMPANY_STATES, STATUSES, set_company_state, set_role_status
from .utils.pdf import extract_text

logger = logging.getLogger(__name__)

# Uploaded resumes live next to the database, not in the source tree.
DEFAULT_DATA_ROOT = Path(__file__).resolve().parent.parent / "data"


def _default_llm() -> LLMClient:
    """Build the configured client. Only called when a resume is uploaded."""
    import yaml

    from .llm.factory import get_client

    config_path = Path(__file__).resolve().parent.parent / "config.yaml"
    with open(config_path, encoding="utf-8") as handle:
        return get_client(yaml.safe_load(handle))


def create_app(db_path: Path | str = DEFAULT_PATH,
               user_name: str = "default",
               shortlist_min: int = 7,
               data_root: Path | str = DEFAULT_DATA_ROOT,
               llm_factory=None) -> Flask:
    app = Flask(__name__)
    data_root = Path(data_root)
    build_llm = llm_factory or _default_llm
```

Leave `_conn`, `_user`, and the three existing routes exactly as they are. Then add, immediately before the closing `return app`:

```python
    @app.get("/setup")
    def setup_screen():
        return render_upload()

    @app.post("/api/resumes")
    def add_resume():
        upload = request.files.get("resume")
        if upload is None:
            return jsonify({"error": "No file was sent."}), 400
        data = upload.read()
        filename = upload.filename or ""
        try:
            intake.validate(filename, data)
        except intake.UploadRejected as rejected:
            return jsonify({"error": str(rejected)}), 400

        conn = _conn()
        try:
            user_id = _user(conn)
            sha256 = intake.digest(data)
            if resume_by_sha(conn, user_id, sha256):
                return jsonify(
                    {"error": "You have already uploaded this resume."}), 409

            stored_path = intake.store(data_root, user_id, sha256, data)
            try:
                text = extract_text(data_root / stored_path)
            except Exception:
                logger.exception("PDF text extraction failed")
                return jsonify({"error": "That PDF could not be read. Try "
                                         "exporting it again."}), 400

            label = unique_label(conn, user_id, Path(filename).stem)
            resume_id = create_resume(
                conn, user_id, label=label, orig_filename=filename,
                sha256=sha256, stored_path=stored_path, extracted_text=text)

            # A parse failure must not lose the upload — the confirm screen
            # asks for the roles and skills by hand instead.
            try:
                parsed = parse_profile(text, build_llm())
            except Exception:
                logger.exception("Resume parse failed for resume %s", resume_id)
            else:
                update_resume(conn, user_id, resume_id, label=label,
                              target_roles=parsed["target_roles"],
                              skills=parsed["skills"],
                              seniority=parsed["seniority"])
            return jsonify({"resume_id": resume_id}), 201
        finally:
            conn.close()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_setup_routes.py -v`

Expected: PASS, 12 tests.

- [ ] **Step 5: Run the whole suite**

Run: `python -m pytest tests/ -q`

Expected: all green. `create_app`'s new arguments have defaults, so the existing `test_app.py` fixture is unaffected.

- [ ] **Step 6: Commit**

```bash
git add job_hunt/src/app.py job_hunt/tests/test_setup_routes.py && git commit -m "feat: upload, extract and parse a resume over HTTP"
```

---

### Task 10: The confirm screen route and saving edits

**Files:**
- Modify: `src/app.py`
- Test: `tests/test_setup_routes.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_setup_routes.py`:

```python
def test_the_confirm_screen_shows_what_was_parsed(client):
    resume_id = _upload(client).get_json()["resume_id"]
    response = client.get(f"/setup/confirm/{resume_id}")
    assert response.status_code == 200
    body = response.data.decode("utf-8")
    assert "BI Developer" in body
    assert "Power BI" in body


def test_the_first_resume_is_asked_where_you_live(client):
    resume_id = _upload(client).get_json()["resume_id"]
    body = client.get(f"/setup/confirm/{resume_id}").data.decode("utf-8")
    assert 'id="location"' in body


def test_a_missing_resume_is_a_404(client):
    assert client.get("/setup/confirm/9999").status_code == 404


def test_saving_edits_overwrites_roles_skills_and_seniority(client, db):
    resume_id = _upload(client).get_json()["resume_id"]
    response = client.post(f"/api/resumes/{resume_id}", json={
        "label": "BI Dev",
        "target_roles": [{"title": "BI Analyst", "aliases": []}],
        "skills": [{"name": "SQL", "tier": "working", "aliases": []}],
        "seniority": "mid"})
    assert response.status_code == 200

    from src.store.profile import get_resume
    conn = connect(db)
    resume = get_resume(conn, 1, resume_id)
    conn.close()
    assert resume["label"] == "bi dev"
    assert resume["target_roles"] == [{"title": "BI Analyst", "aliases": []}]
    assert resume["seniority"] == "mid"


def test_saving_without_a_label_is_a_400(client):
    resume_id = _upload(client).get_json()["resume_id"]
    response = client.post(f"/api/resumes/{resume_id}", json={
        "label": "  ", "target_roles": [], "skills": [], "seniority": "mid"})
    assert response.status_code == 400


def test_saving_an_unknown_seniority_is_a_400(client):
    resume_id = _upload(client).get_json()["resume_id"]
    response = client.post(f"/api/resumes/{resume_id}", json={
        "label": "x", "target_roles": [], "skills": [],
        "seniority": "grand wizard"})
    assert response.status_code == 400


def test_saving_a_missing_resume_is_a_404(client):
    response = client.post("/api/resumes/9999", json={
        "label": "x", "target_roles": [], "skills": [], "seniority": "mid"})
    assert response.status_code == 404


def test_reusing_another_resumes_label_is_a_409(client):
    first = _upload(client, name="one.pdf").get_json()["resume_id"]
    second = _upload(client, name="two.pdf",
                     data=_OTHER_PDF).get_json()["resume_id"]
    assert first != second
    response = client.post(f"/api/resumes/{second}", json={
        "label": "one", "target_roles": [], "skills": [], "seniority": "mid"})
    assert response.status_code == 409
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_setup_routes.py -v`

Expected: FAIL — the confirm-screen tests get 404 (no such route) and the save tests get 405.

- [ ] **Step 3: Write the implementation**

Add to `src/app.py`, after the `add_resume` route:

```python
    @app.get("/setup/confirm/<int:resume_id>")
    def confirm_screen(resume_id: int):
        conn = _conn()
        try:
            user_id = _user(conn)
            resume = get_resume(conn, user_id, resume_id)
            if resume is None:
                return jsonify({"error": "not found"}), 404
            profile = get_profile(conn, user_id)
            # Where you live is asked once, on the first resume.
            return render_confirm(resume, profile,
                                  ask_location=not profile["setup_complete"])
        finally:
            conn.close()

    @app.post("/api/resumes/<int:resume_id>")
    def save_resume(resume_id: int):
        payload = request.get_json(silent=True) or {}
        label = str(payload.get("label") or "").strip().lower()[:40]
        if not label:
            return jsonify({"error": "A label is required."}), 400
        conn = _conn()
        try:
            update_resume(
                conn, _user(conn), resume_id, label=label,
                target_roles=list(payload.get("target_roles") or []),
                skills=list(payload.get("skills") or []),
                seniority=str(payload.get("seniority") or "mid"),
                is_active=bool(payload.get("is_active", True)))
            return jsonify({"resume_id": resume_id})
        except ValueError as bad:
            return jsonify({"error": str(bad)}), 400
        except LookupError:
            return jsonify({"error": "not found"}), 404
        except sqlite3.IntegrityError:
            return jsonify(
                {"error": "You already have a resume with that label."}), 409
        finally:
            conn.close()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_setup_routes.py -v`

Expected: PASS, 20 tests.

- [ ] **Step 5: Commit**

```bash
git add job_hunt/src/app.py job_hunt/tests/test_setup_routes.py && git commit -m "feat: confirm screen route and saving the edited profile"
```

---

### Task 11: Deleting a resume and saving the profile

**Files:**
- Modify: `src/app.py`
- Test: `tests/test_setup_routes.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_setup_routes.py`:

```python
def test_deleting_a_resume_removes_the_row_and_the_file(client, db, tmp_path):
    resume_id = _upload(client).get_json()["resume_id"]
    assert list((tmp_path / "data" / "resumes").rglob("*.pdf"))

    response = client.delete(f"/api/resumes/{resume_id}")
    assert response.status_code == 200

    from src.store.profile import get_resume
    conn = connect(db)
    assert get_resume(conn, 1, resume_id) is None
    conn.close()
    assert not list((tmp_path / "data" / "resumes").rglob("*.pdf"))


def test_deleting_a_missing_resume_is_a_404(client):
    assert client.delete("/api/resumes/9999").status_code == 404


def test_saving_the_profile_records_location_and_work_modes(client, db):
    response = client.post("/api/profile", json={
        "location": "Toronto, ON", "country": "CA",
        "work_modes": ["remote", "hybrid"]})
    assert response.status_code == 200

    from src.store.profile import get_profile as read
    conn = connect(db)
    profile = read(conn, 1)
    conn.close()
    assert profile == {"location": "Toronto, ON", "country": "ca",
                       "work_modes": ["remote", "hybrid"],
                       "setup_complete": True}


def test_saving_the_profile_with_no_work_mode_is_a_400(client):
    response = client.post("/api/profile", json={
        "location": "Toronto", "country": "ca", "work_modes": []})
    assert response.status_code == 400


def test_saving_the_profile_with_an_unknown_work_mode_is_a_400(client):
    response = client.post("/api/profile", json={
        "location": "Toronto", "country": "ca", "work_modes": ["telepathic"]})
    assert response.status_code == 400


def test_a_second_resume_is_not_asked_where_you_live_again(client):
    client.post("/api/profile", json={"location": "Toronto, ON",
                                      "country": "ca",
                                      "work_modes": ["remote"]})
    resume_id = _upload(client, name="second.pdf",
                        data=_OTHER_PDF).get_json()["resume_id"]
    body = client.get(f"/setup/confirm/{resume_id}").data.decode("utf-8")
    assert 'id="location"' not in body
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_setup_routes.py -v`

Expected: FAIL — the delete tests get 405, the profile tests get 404.

- [ ] **Step 3: Write the implementation**

Add to `src/app.py`, after `save_resume`:

```python
    @app.delete("/api/resumes/<int:resume_id>")
    def remove_resume(resume_id: int):
        conn = _conn()
        try:
            stored_path = delete_resume(conn, _user(conn), resume_id)
            if stored_path is None:
                return jsonify({"error": "not found"}), 404
            (data_root / stored_path).unlink(missing_ok=True)
            return jsonify({"resume_id": resume_id, "deleted": True})
        finally:
            conn.close()

    @app.post("/api/profile")
    def save_profile():
        payload = request.get_json(silent=True) or {}
        conn = _conn()
        try:
            set_profile(conn, _user(conn),
                        location=str(payload.get("location") or ""),
                        country=str(payload.get("country") or ""),
                        work_modes=list(payload.get("work_modes") or []))
            return jsonify({"saved": True})
        except ValueError as bad:
            return jsonify({"error": str(bad)}), 400
        finally:
            conn.close()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_setup_routes.py -v`

Expected: PASS, 26 tests.

- [ ] **Step 5: Commit**

```bash
git add job_hunt/src/app.py job_hunt/tests/test_setup_routes.py && git commit -m "feat: delete a resume and save the user's location and work modes"
```

---

### Task 12: The profile route

**Files:**
- Modify: `src/app.py`
- Test: `tests/test_setup_routes.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_setup_routes.py`:

```python
def test_the_profile_screen_lists_the_uploaded_resume(client):
    _upload(client, name="Ghazal BI.pdf")
    response = client.get("/profile")
    assert response.status_code == 200
    assert b"ghazal bi" in response.data


def test_the_profile_screen_works_before_anything_is_uploaded(client):
    response = client.get("/profile")
    assert response.status_code == 200
    assert b"No resumes yet" in response.data


def test_the_profile_screen_shows_the_saved_location(client):
    client.post("/api/profile", json={"location": "Toronto, ON",
                                      "country": "ca",
                                      "work_modes": ["remote", "hybrid"]})
    body = client.get("/profile").data.decode("utf-8")
    assert "Toronto, ON" in body
    assert "remote, hybrid" in body
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_setup_routes.py -v`

Expected: FAIL with 404 on `/profile`.

- [ ] **Step 3: Write the implementation**

Add to `src/app.py`, after `save_profile`:

```python
    @app.get("/profile")
    def profile_screen():
        conn = _conn()
        try:
            user_id = _user(conn)
            return render_profile(list_resumes(conn, user_id),
                                  get_profile(conn, user_id))
        finally:
            conn.close()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_setup_routes.py -v`

Expected: PASS, 29 tests.

- [ ] **Step 5: Commit**

```bash
git add job_hunt/src/app.py job_hunt/tests/test_setup_routes.py && git commit -m "feat: the profile screen route"
```

---

### Task 13: Keep resumes out of git, and guard the product rules

**Files:**
- Modify: `.gitignore`
- Test: `tests/test_setup_routes.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_setup_routes.py`:

```python
_NEW_ROUTES = ["/setup", "/profile"]


def test_no_new_screen_leaks_a_score(client):
    """CLAUDE.md: the numeric score is internal. No new route may emit it,
    and no new route may render a bare percentage."""
    _upload(client)
    for route in _NEW_ROUTES:
        body = _visible(client.get(route).data.decode("utf-8"))
        assert "match_score" not in body, route
        assert "%" not in body, route


def test_the_confirm_screen_leaks_no_score(client):
    resume_id = _upload(client).get_json()["resume_id"]
    body = _visible(
        client.get(f"/setup/confirm/{resume_id}").data.decode("utf-8"))
    assert "match_score" not in body
    assert "%" not in body


def test_no_json_response_leaks_a_score(client):
    resume_id = _upload(client).get_json()["resume_id"]
    responses = [
        client.post(f"/api/resumes/{resume_id}", json={
            "label": "x", "target_roles": [], "skills": [], "seniority": "mid"}),
        client.post("/api/profile", json={"location": "T", "country": "ca",
                                          "work_modes": ["remote"]}),
        client.delete(f"/api/resumes/{resume_id}"),
    ]
    for response in responses:
        body = response.data.decode("utf-8")
        assert "match_score" not in body
        assert "%" not in body


def test_the_extracted_text_never_reaches_a_screen(client):
    """A whole resume rendered into a page is a lot of personal data on
    screen for no reason. Only the parsed profile is shown."""
    _upload(client)
    for route in _NEW_ROUTES:
        assert b"Power BI and SQL and dbt" not in client.get(route).data
```

- [ ] **Step 2: Run the tests to verify they behave as expected**

Run: `python -m pytest tests/test_setup_routes.py -v -k "leak or extracted"`

Expected: PASS. These are guard tests — if any of them fails, the offending
route is emitting something it must not, and the route is what gets fixed, not
the test.

- [ ] **Step 3: Exclude uploaded resumes from git**

Append to `.gitignore` (repository root):

```
# Uploaded resumes — personal data, never committed.
job_hunt/data/
```

- [ ] **Step 4: Verify git is ignoring the data root**

Run: `git check-ignore -v job_hunt/data/resumes/1/abc.pdf`

Expected: a line naming `.gitignore` and the `job_hunt/data/` pattern. An empty
output and exit code 1 means the rule is not matching — fix it before committing.

- [ ] **Step 5: Run the whole suite**

Run: `python -m pytest tests/ -q`

Expected: `323 passed` — the 230 baseline plus 93 new tests (5 migration, 16 profile store, 2 schema, 9 intake, 10 parser, 18 page, 33 routes). If the number is lower, a test file was not saved or a module failed to import; if a previously passing test now fails, that is a regression in `create_app` or `init_db`, not a test to update.

- [ ] **Step 6: Smoke-test the real thing**

Run: `python main.py --serve`

Then, in a browser: open `http://127.0.0.1:5000/setup`, upload a real PDF resume, check the confirm screen shows plausible roles and skills, edit one chip, save, and confirm `/profile` lists it. Stop with Ctrl-C. This is the one step the test suite cannot cover — it is the first time the configured LLM actually sees a resume.

- [ ] **Step 7: Commit**

```bash
git add .gitignore job_hunt/tests/test_setup_routes.py && git commit -m "test: guard the new routes against leaking scores or resume text"
```

---

## What Ship 1 deliberately does not do

Do not add these while implementing — they belong to later ships and adding them early makes the review harder:

- `/` still renders the map regardless of setup state. The redirect is Ship 3.
- `keywords.yaml` is untouched. The split into `vocabulary.yaml` is Ship 2.
- The scorer still reads `keywords.yaml` and knows nothing about resumes. Ship 2.
- The scrapers still hardcode `"remote"` / `"us"` / `"Worldwide"`. Ship 2.
- `config.yaml`'s `resume:` block, `search.categories`, and `src/config.py`'s
  `apply_env_overrides` all stay. Removing them is Ship 2.
- No background run, no progress screen, no `POST /api/runs`. Ship 3.
- `src/agents/resume_agent.py` is left alone — the tailoring path still uses it.
