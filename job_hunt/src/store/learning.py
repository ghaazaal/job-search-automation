"""The life of one learning-path analysis: start, report, finish, fail.

Mirrors `runs.py` for scrapes. The analysis and the path are stored as JSON
snapshots on the row, so a path generated last month still states the
market it was built from.
"""
import json
import sqlite3
from datetime import datetime, timedelta, timezone

from .db import transaction

# Reading through Claude's Batch API can legitimately wait up to 24 hours,
# so only a row older than that is presumed dead. A process that died is
# cleared sooner by boot recovery the next time the app starts.
STALE_AFTER_MINUTES = 25 * 60
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
    count = cur.rowcount
    cur = conn.execute(
        "UPDATE role_learning_path SET status = 'FAILED', error = ?"
        " WHERE status = 'RUNNING'", (reason,))
    return count + cur.rowcount


# ── One job ────────────────────────────────────────────────────────────────
# A path toward one posting lives in role_learning_path. Same life cycle as
# the market analysis, one row per attempt, the newest per role shown.

# A one-job path is a handful of calls; a row RUNNING this long is dead.
ROLE_STALE_AFTER_MINUTES = 30


def role_start(conn: sqlite3.Connection, user_id: int,
               role_id: int) -> int | None:
    """Open a RUNNING row for this role, or None when one is already live."""
    with transaction(conn):
        live = conn.execute(
            "SELECT id, started_at FROM role_learning_path"
            " WHERE user_id = ? AND role_id = ? AND status = 'RUNNING'",
            (user_id, role_id)).fetchone()
        if live and datetime.now(timezone.utc) - _parse(live["started_at"]) \
                < timedelta(minutes=ROLE_STALE_AFTER_MINUTES):
            return None
        if live:
            conn.execute(
                "UPDATE role_learning_path SET status = 'FAILED', error = ?"
                " WHERE id = ?", ("abandoned — superseded", live["id"]))
        conn.execute(
            "INSERT INTO role_learning_path (user_id, role_id, started_at,"
            " status) VALUES (?, ?, ?, 'RUNNING')", (user_id, role_id, _now()))
    return conn.execute("SELECT last_insert_rowid() AS i").fetchone()["i"]


def _parse(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return datetime.min.replace(tzinfo=timezone.utc)


def role_progress(conn: sqlite3.Connection, row_id: int, stage: str,
                  progress: dict) -> None:
    conn.execute(
        "UPDATE role_learning_path SET stage = ?, progress = ? WHERE id = ?",
        (stage, json.dumps(progress), row_id))


def role_finish(conn: sqlite3.Connection, row_id: int, model: str,
                analysis: dict, path: dict) -> None:
    with transaction(conn):
        conn.execute(
            """UPDATE role_learning_path SET status = 'OK', finished_at = ?,
                      model = ?, analysis = ?, path = ?, stage = NULL
                WHERE id = ?""",
            (_now(), model, json.dumps(analysis), json.dumps(path), row_id))


def role_fail(conn: sqlite3.Connection, row_id: int, error: str) -> None:
    conn.execute(
        "UPDATE role_learning_path SET status = 'FAILED', finished_at = ?,"
        " error = ? WHERE id = ?", (_now(), (error or "")[:_MAX_ERROR], row_id))


def role_get(conn: sqlite3.Connection, row_id: int) -> dict | None:
    return _row(conn.execute(
        "SELECT * FROM role_learning_path WHERE id = ?", (row_id,)).fetchone())


def role_latest(conn: sqlite3.Connection, user_id: int, role_id: int,
                status: str | None = None) -> dict | None:
    sql = ("SELECT * FROM role_learning_path WHERE user_id = ? AND role_id = ?")
    params: list = [user_id, role_id]
    if status:
        sql += " AND status = ?"
        params.append(status)
    sql += " ORDER BY id DESC LIMIT 1"
    return _row(conn.execute(sql, params).fetchone())


def role_paths(conn: sqlite3.Connection, user_id: int) -> list[dict]:
    """The newest finished path per role, newest first, for the LEARN page."""
    rows = conn.execute(
        """SELECT p.role_id, p.finished_at, p.analysis, r.title,
                  c.name AS company
             FROM role_learning_path p
             JOIN role r ON r.id = p.role_id
             JOIN company c ON c.id = r.company_id
            WHERE p.user_id = ? AND p.status = 'OK'
              AND p.id = (SELECT MAX(id) FROM role_learning_path q
                           WHERE q.role_id = p.role_id AND q.status = 'OK')
            ORDER BY p.finished_at DESC""", (user_id,))
    out = []
    for row in rows:
        analysis = json.loads(row["analysis"] or "{}")
        out.append({"role_id": row["role_id"], "title": row["title"],
                    "company": row["company"],
                    "finished_at": row["finished_at"],
                    "gaps": len(analysis.get("gaps") or []),
                    "required": analysis.get("required", 0),
                    "have": analysis.get("have_required", 0)})
    return out


def owned_role(conn: sqlite3.Connection, user_id: int,
               role_id: int) -> dict | None:
    """The posting a one-job path is for, only if it is this user's."""
    row = conn.execute(
        "SELECT r.id, r.title, r.url, r.description_captured,"
        " c.name AS company FROM role r JOIN company c"
        " ON c.id = r.company_id WHERE r.id = ? AND r.user_id = ?",
        (role_id, user_id)).fetchone()
    return dict(row) if row else None
