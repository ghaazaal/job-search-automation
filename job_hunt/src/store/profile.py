"""The user's profile and the resumes they own.

Where you live is a property of the person, not of a PDF; target roles and
skills are properties of one tailored document. That split is the reason this
module exists rather than more columns on `user`.

`skills` and `target_roles` are JSON columns, matching the `role.matched` and
`role.gaps` precedent. They are read whole and written whole by the confirm
screen; normalising them into child tables buys a query nobody has asked for.
"""
import json
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
    location = str(location or "")
    country = str(country or "")

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
