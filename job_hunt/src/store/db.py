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
