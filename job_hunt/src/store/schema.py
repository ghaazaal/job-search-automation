"""Schema definition and migrations.

Constraints live here rather than in Python. A status typo should be rejected
by the database, not caught by whichever caller happened to remember to check.

Migrations are forward-only. `_DDL` is the current shape — a fresh database
gets it whole. `_MIGRATIONS` carries what an older database needs to catch up,
keyed by the version it arrives at.
"""
import sqlite3

from .db import transaction

SCHEMA_VERSION = 9

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
    dropped     INTEGER NOT NULL DEFAULT 0,
    offtopic    INTEGER NOT NULL DEFAULT 0,
    boards      TEXT NOT NULL DEFAULT '[]',
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
    work_mode            TEXT,
    country              TEXT,
    -- Populated by a later ship: `scope_verdict` (src/scoring/location_scope.py)
    -- exists but nothing calls it yet, so this column is NULL for every row
    -- until that ship decides where the call belongs. Not a bug.
    location_scope       TEXT CHECK (location_scope IN ('open','closed','unknown')),
    source_board         TEXT,
    -- Soft drop. A role we no longer want on the map but will not
    -- DELETE: the run that stored it is history, and a hard delete
    -- makes a wrong rule unrecoverable.
    dropped_at           TEXT,
    eligibility_verified INTEGER NOT NULL DEFAULT 0,
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
#
# Entries are (table, column, sql). A `column` of None marks a data migration
# that always runs; otherwise the statement adds a column and is skipped when
# that column already exists — see `_run_step`.
_MIGRATIONS: dict[int, tuple[tuple[str | None, str | None, str], ...]] = {
    2: (
        ("user", "location", "ALTER TABLE user ADD COLUMN location TEXT"),
        ("user", "country", "ALTER TABLE user ADD COLUMN country TEXT"),
        ("user", "work_modes", "ALTER TABLE user ADD COLUMN work_modes TEXT"),
        ("user", "setup_complete",
         "ALTER TABLE user ADD COLUMN setup_complete INTEGER NOT NULL DEFAULT 0"),
        ("role", "resume_id",
         "ALTER TABLE role ADD COLUMN resume_id INTEGER REFERENCES resume(id)"),
        ("run", "stage", "ALTER TABLE run ADD COLUMN stage TEXT"),
        ("run", "progress",
         "ALTER TABLE run ADD COLUMN progress TEXT NOT NULL DEFAULT '{}'"),
        ("run", "error", "ALTER TABLE run ADD COLUMN error TEXT"),
    ),
    3: (
        # Ship 2 stops reading CANDIDATE_NAME from .env, but that value is the
        # key `ensure_user` looks the user row up by. Rename the sole existing
        # user rather than strand their whole map behind a name nothing sets
        # any more. Guarded to one user, so a genuinely multi-user database is
        # left alone, and idempotent, so replaying it is a no-op.
        (None, None,
         "UPDATE user SET name = 'default'"
         " WHERE (SELECT COUNT(*) FROM user) = 1"),
    ),
    4: (
        ("role", "work_mode", "ALTER TABLE role ADD COLUMN work_mode TEXT"),
        ("run", "dropped",
         "ALTER TABLE run ADD COLUMN dropped INTEGER NOT NULL DEFAULT 0"),
    ),
    5: (
        ("role", "eligibility_verified",
         "ALTER TABLE role ADD COLUMN eligibility_verified INTEGER NOT NULL DEFAULT 0"),
    ),
    6: (
        ("run", "offtopic",
         "ALTER TABLE run ADD COLUMN offtopic INTEGER NOT NULL DEFAULT 0"),
    ),
    7: (
        # kaix supplies a structured country code, so Indeed rows never
        # need `location_country`'s ambiguity cases ("Chennai, IN" vs
        # "Gary, IN", which both stay silent).
        ("role", "country", "ALTER TABLE role ADD COLUMN country TEXT"),
        # What the remote boards publish about reach: open / closed /
        # unknown for this user. Null on every pre-existing row, and
        # until something calls `scope_verdict`, on every new one too.
        ("role", "location_scope",
         "ALTER TABLE role ADD COLUMN location_scope TEXT "
         "CHECK (location_scope IN ('open','closed','unknown'))"),
        # Which board a remote-board row came from, so the card can say.
        ("role", "source_board",
         "ALTER TABLE role ADD COLUMN source_board TEXT"),
    ),
    8: (
        # Which of the aggregator's ten boards actually returned rows.
        # Run 6 got four and nothing noticed, because Ship 7's residual
        # watched row count and 133 rows arrived. A board silent across
        # two consecutive runs is the signal; the row count is not.
        ("run", "boards",
         "ALTER TABLE run ADD COLUMN boards TEXT NOT NULL DEFAULT '[]'"),
    ),
    9: (
        # Soft drop, never DELETE. The 800 roles stored before the
        # relevance gate existed are off-target, not fictional, and a rule
        # that turns out wrong has to be recoverable.
        ("role", "dropped_at", "ALTER TABLE role ADD COLUMN dropped_at TEXT"),
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


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}


def _run_step(conn: sqlite3.Connection, table: str | None,
              column: str | None, sql: str) -> None:
    """Run one migration statement.

    `column is None` marks a data migration — SQL that changes rows rather
    than shape. Those always run, so they have to be written to be safe to
    replay; the guard is in the statement, not here.

    Otherwise the statement adds a column and is skipped when the column is
    already present. `_DDL` always describes the current (post-migration)
    shape of every table, and `executescript` autocommits each statement as it
    runs, so a process killed partway through a fresh CREATE TABLE run can
    leave a table that already has every column while `user_version` still
    reads 0. Checking the column directly, instead of trusting the counter, is
    what makes replaying a migration after that kind of crash safe.
    """
    if column is None:
        conn.execute(sql)
        return
    if column not in _columns(conn, table):
        conn.execute(sql)


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
                for table, column, sql in _MIGRATIONS.get(target, ()):
                    _run_step(conn, table, column, sql)

    # A database already migrated by newer code (version > SCHEMA_VERSION,
    # plausible across worktrees/branches during development) must not have
    # its stored version number dragged back down — the table shape here is
    # untouched and still newer than what this code knows how to write. That
    # would make the next run of the newer code see a stale low version and
    # replay ALTERs against columns that already exist.
    if fresh or version <= SCHEMA_VERSION:
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
