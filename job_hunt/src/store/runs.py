"""The life of one scrape run: start, report, finish, fail, recover.

`ingest` owns the rows a run produces. This module owns the run itself — the
row the progress screen polls and the boot recovery repairs.
"""
import json
import sqlite3
from datetime import datetime, timedelta, timezone

from .db import transaction

# A RUNNING run older than this is presumed abandoned. The worker writes no
# heartbeat, so age is the only evidence available. Long enough that a genuine
# slow scrape is never mistaken for a dead one: four Apify calls at a 120
# second timeout is eight minutes worst case.
STALE_AFTER_MINUTES = 15

# The error column is display text, not a log. Keep it short enough to render.
_MAX_ERROR = 500


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def start_run(conn: sqlite3.Connection, user_id: int) -> int:
    with transaction(conn):
        conn.execute(
            "INSERT INTO run (user_id, started_at, status) VALUES (?, ?, 'RUNNING')",
            (user_id, _now()))
    return conn.execute("SELECT last_insert_rowid() AS i").fetchone()["i"]


def finish_run(conn: sqlite3.Connection, run_id: int,
               scraped: int, kept: int, ok: bool = True,
               dropped: int = 0) -> None:
    with transaction(conn):
        conn.execute(
            """UPDATE run SET status = ?, finished_at = ?, scraped = ?,
               kept = ?, dropped = ? WHERE id = ?""",
            ("OK" if ok else "FAILED", _now(), scraped, kept, dropped, run_id))


def fail_run(conn: sqlite3.Connection, run_id: int, error: str) -> None:
    """Mark a run failed, carrying the message the screen will show."""
    with transaction(conn):
        conn.execute(
            "UPDATE run SET status = 'FAILED', finished_at = ?, error = ?"
            " WHERE id = ?",
            (_now(), str(error)[:_MAX_ERROR], run_id))


def set_progress(conn: sqlite3.Connection, run_id: int,
                 stage: str, progress: dict) -> None:
    with transaction(conn):
        conn.execute("UPDATE run SET stage = ?, progress = ? WHERE id = ?",
                     (stage, json.dumps(progress), run_id))


def get_run(conn: sqlite3.Connection, run_id: int) -> dict | None:
    row = conn.execute(
        """SELECT id, status, stage, progress, error, scraped, kept
             FROM run WHERE id = ?""", (run_id,)).fetchone()
    if row is None:
        return None
    # A run killed mid-write can leave this unparseable. The screen matters
    # more than the payload, so fall back rather than raise.
    try:
        progress = json.loads(row["progress"] or "{}")
    except (json.JSONDecodeError, TypeError):
        progress = {}
    return {
        "id":       row["id"],
        "status":   row["status"],
        "stage":    row["stage"] or "",
        "progress": progress,
        "error":    row["error"] or "",
        "scraped":  row["scraped"],
        "kept":     row["kept"],
    }


def active_run(conn: sqlite3.Connection, user_id: int) -> dict | None:
    """The user's RUNNING run if there is one, at any age."""
    row = conn.execute(
        "SELECT id, started_at FROM run WHERE user_id = ? AND status = 'RUNNING'"
        " ORDER BY id DESC LIMIT 1", (user_id,)).fetchone()
    if row is None:
        return None
    return {"id": row["id"], "started_at": row["started_at"]}


def is_stale(started_at: str, now: datetime | None = None) -> bool:
    """True when a RUNNING run is old enough to be presumed dead.

    An unreadable timestamp counts as stale. Letting the user start a new run
    is a smaller failure than locking them out of running anything.
    """
    now = now or datetime.now(timezone.utc)
    try:
        started = datetime.fromisoformat(started_at)
    except (TypeError, ValueError):
        return True
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    return now - started > timedelta(minutes=STALE_AFTER_MINUTES)


def clear_running(conn: sqlite3.Connection, error: str) -> int:
    """Mark every RUNNING run FAILED. Boot recovery only.

    Never call this per-request: at boot no worker of ours is alive, so every
    RUNNING row is an orphan, but during normal operation one of them is the
    run currently in flight.
    """
    with transaction(conn):
        cur = conn.execute(
            "UPDATE run SET status = 'FAILED', finished_at = ?, error = ?"
            " WHERE status = 'RUNNING'", (_now(), str(error)[:_MAX_ERROR]))
    return cur.rowcount


def latest_ok_run(conn: sqlite3.Connection, user_id: int) -> int | None:
    """The newest successful run.

    The map marks roles seen up to this id. It must ignore a run still in
    flight: marking an unfinished run seen would file every role it is about
    to store as already seen, silently emptying the map's new section.
    """
    row = conn.execute(
        "SELECT MAX(id) AS i FROM run WHERE user_id = ? AND status = 'OK'",
        (user_id,)).fetchone()
    return row["i"]
