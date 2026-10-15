"""The master resume and the resumes tailored from it.

One master per user, stored as the Markdown the user edits. A tailored
resume is a snapshot: it keeps the master text it was built from, so the
ids its report cites still mean something after the master is edited.
"""
import json
import sqlite3
from datetime import datetime, timezone

from .db import transaction


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _json(value, default):
    try:
        return json.loads(value) if value else default
    except (TypeError, ValueError):
        return default


def get_master(conn: sqlite3.Connection, user_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM master_resume WHERE user_id = ?",
                       (user_id,)).fetchone()
    if row is None:
        return None
    out = dict(row)
    out["sources"] = _json(out.get("sources"), [])
    out["report"] = _json(out.get("report"), {})
    return out


def save_master(conn: sqlite3.Connection, user_id: int, markdown: str, *,
                sources: list | None = None, report: dict | None = None,
                model: str | None = None) -> None:
    """Write the master. A build passes sources, report and model; a hand
    edit passes only the text and keeps what the build recorded."""
    now = _now()
    with transaction(conn):
        existing = conn.execute(
            "SELECT id FROM master_resume WHERE user_id = ?",
            (user_id,)).fetchone()
        if existing is None:
            conn.execute(
                """INSERT INTO master_resume (user_id, markdown, sources,
                       report, model, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (user_id, markdown, json.dumps(sources or []),
                 json.dumps(report or {}), model, now, now))
        elif sources is None:
            conn.execute(
                "UPDATE master_resume SET markdown = ?, updated_at = ?,"
                " edited = 1 WHERE user_id = ?", (markdown, now, user_id))
        else:
            conn.execute(
                """UPDATE master_resume SET markdown = ?, sources = ?,
                       report = ?, model = ?, created_at = ?, updated_at = ?,
                       edited = 0
                   WHERE user_id = ?""",
                (markdown, json.dumps(sources), json.dumps(report or {}),
                 model, now, now, user_id))


def role_for_tailoring(conn: sqlite3.Connection, user_id: int,
                       role_id: int) -> dict | None:
    row = conn.execute(
        """SELECT r.id, r.title, r.url, r.location, r.platform,
                  r.source_board, r.description, r.description_captured,
                  c.name AS company
             FROM role r JOIN company c ON c.id = r.company_id
            WHERE r.id = ? AND r.user_id = ?""",
        (role_id, user_id)).fetchone()
    return dict(row) if row else None


def add_tailored(conn: sqlite3.Connection, user_id: int, role_id: int, *,
                 master_markdown: str, markdown: str, report: dict,
                 usage: dict, model: str) -> int:
    with transaction(conn):
        conn.execute(
            """INSERT INTO tailored_resume (user_id, role_id, created_at,
                   model, master_markdown, markdown, report, usage)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, role_id, _now(), model, master_markdown, markdown,
             json.dumps(report), json.dumps(usage)))
    return conn.execute("SELECT last_insert_rowid() AS i").fetchone()["i"]


def _tailored(row) -> dict | None:
    if row is None:
        return None
    out = dict(row)
    out["report"] = _json(out.get("report"), {})
    out["usage"] = _json(out.get("usage"), {})
    return out


def get_tailored(conn: sqlite3.Connection, user_id: int,
                 tailored_id: int) -> dict | None:
    return _tailored(conn.execute(
        """SELECT t.*, r.title, c.name AS company, r.url
             FROM tailored_resume t
             JOIN role r ON r.id = t.role_id
             JOIN company c ON c.id = r.company_id
            WHERE t.id = ? AND t.user_id = ?""",
        (tailored_id, user_id)).fetchone())


def latest_for_role(conn: sqlite3.Connection, user_id: int,
                    role_id: int) -> dict | None:
    row = conn.execute(
        "SELECT id FROM tailored_resume WHERE user_id = ? AND role_id = ?"
        " ORDER BY id DESC LIMIT 1", (user_id, role_id)).fetchone()
    return get_tailored(conn, user_id, row["id"]) if row else None


def list_tailored(conn: sqlite3.Connection, user_id: int) -> list[dict]:
    """The latest tailored resume per role, newest first."""
    rows = conn.execute(
        """SELECT t.id, t.role_id, t.created_at, t.usage, r.title,
                  c.name AS company
             FROM tailored_resume t
             JOIN role r ON r.id = t.role_id
             JOIN company c ON c.id = r.company_id
            WHERE t.user_id = ?
              AND t.id = (SELECT MAX(id) FROM tailored_resume
                           WHERE role_id = t.role_id AND user_id = t.user_id)
            ORDER BY t.id DESC""", (user_id,)).fetchall()
    out = []
    for row in rows:
        item = dict(row)
        item["usage"] = _json(item.get("usage"), {})
        out.append(item)
    return out
