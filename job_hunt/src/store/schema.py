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
