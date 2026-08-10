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

    now = _now()
    applied_at = now if status == "APPLIED" else None

    with transaction(conn):
        previous = role_status(conn, role_id)
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

    now = _now()

    with transaction(conn):
        row = conn.execute("SELECT user_state FROM company WHERE id = ?",
                           (company_id,)).fetchone()
        previous = row["user_state"] if row else None
        conn.execute("UPDATE company SET user_state = ? WHERE id = ?",
                     (state, company_id))
        conn.execute(
            """INSERT INTO event (user_id, company_id, kind, from_status, to_status, at)
               VALUES (?, ?, 'COMPANY_STATE', ?, ?, ?)""",
            (user_id, company_id, previous, state, now))
