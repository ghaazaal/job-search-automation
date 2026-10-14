"""The life of one learning-path analysis: start, report, finish, fail.

Mirrors `runs.py` for scrapes. The analysis and the path are stored as JSON
snapshots on the row, so a path generated last month still states the
market it was built from.
"""
import json
import sqlite3
from datetime import datetime, timedelta, timezone

from .db import transaction

# A first analysis reads every stored posting (about half an hour for a
# thousand); a RUNNING row older than this belongs to a process that is
# gone, and boot recovery clears it sooner when the app restarts.
STALE_AFTER_MINUTES = 60
_MAX_ERROR = 500


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _row(row) -> dict | None:
    if row is None:
        return None
    out = dict(row)
    for key in ("progress", "analysis", "path"):
        try:
            out[key] = json.loads(out[key]) if out.get(key) else None
        except (TypeError, ValueError):
            out[key] = None
    return out


def start(conn: sqlite3.Connection, user_id: int,
          resume_id: int | None = None) -> int | None:
    """Open a RUNNING row, or return None when a live one already exists."""
    with transaction(conn):
        live = conn.execute(
            "SELECT id, started_at FROM learning_path"
            " WHERE user_id = ? AND status = 'RUNNING'", (user_id,)).fetchone()
        if live and not is_stale(live["started_at"]):
            return None
        if live:
            conn.execute(
                "UPDATE learning_path SET status = 'FAILED', error = ?"
                " WHERE id = ?", ("abandoned — superseded", live["id"]))
        conn.execute(
            "INSERT INTO learning_path (user_id, resume_id, started_at, status)"
            " VALUES (?, ?, ?, 'RUNNING')", (user_id, resume_id, _now()))
    return conn.execute("SELECT last_insert_rowid() AS i").fetchone()["i"]


def is_stale(started_at: str) -> bool:
    try:
        started = datetime.fromisoformat(started_at)
    except (TypeError, ValueError):
        return True
    return datetime.now(timezone.utc) - started > timedelta(
        minutes=STALE_AFTER_MINUTES)


def set_progress(conn: sqlite3.Connection, path_id: int, stage: str,
                 progress: dict) -> None:
    conn.execute(
        "UPDATE learning_path SET stage = ?, progress = ? WHERE id = ?",
        (stage, json.dumps(progress), path_id))


def finish(conn: sqlite3.Connection, path_id: int, model: str,
           analysis: dict, path: dict) -> None:
    with transaction(conn):
        conn.execute(
            """UPDATE learning_path SET status = 'OK', finished_at = ?,
                      model = ?, analysis = ?, path = ?, stage = NULL
                WHERE id = ?""",
            (_now(), model, json.dumps(analysis), json.dumps(path), path_id))


def fail(conn: sqlite3.Connection, path_id: int, error: str) -> None:
    conn.execute(
        "UPDATE learning_path SET status = 'FAILED', finished_at = ?,"
        " error = ? WHERE id = ?", (_now(), (error or "")[:_MAX_ERROR], path_id))


def get(conn: sqlite3.Connection, path_id: int) -> dict | None:
    return _row(conn.execute(
        "SELECT * FROM learning_path WHERE id = ?", (path_id,)).fetchone())


def latest(conn: sqlite3.Connection, user_id: int,
           status: str | None = None) -> dict | None:
    sql = "SELECT * FROM learning_path WHERE user_id = ?"
    params: list = [user_id]
    if status:
        sql += " AND status = ?"
        params.append(status)
    sql += " ORDER BY id DESC LIMIT 1"
    return _row(conn.execute(sql, params).fetchone())


def clear_running(conn: sqlite3.Connection, reason: str) -> int:
    """Boot recovery: no analysis survives the process that ran it."""
    cur = conn.execute(
        "UPDATE learning_path SET status = 'FAILED', error = ?"
        " WHERE status = 'RUNNING'", (reason,))
    return cur.rowcount
