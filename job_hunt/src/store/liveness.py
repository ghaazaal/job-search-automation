"""Posting liveness: which stored postings to check, and what a check did.

Every check that made a request is kept in `posting_check`, whatever it
found, so a closure can always be traced to the words that caused it. A
CLOSED verdict stamps `role.closed_at` - a column, never a DELETE, so a
wrong rule is recoverable - and the map stops showing the role. Only a
SAVED application follows it to CLOSED: the user had not applied yet, so
there is nothing left to do. APPLIED and later stay where they are, because
an employer taking a posting down does not end an application already in
their hands; the tracker card says the posting closed instead.
"""
import sqlite3
from datetime import datetime, timezone

from .db import transaction


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def candidates(conn: sqlite3.Connection, user_id: int) -> list[sqlite3.Row]:
    """Roles still believed open, tracked ones first, then least recently
    checked. Hidden roles and hidden companies are skipped: the user asked
    not to see them, so asking the board about them is wasted traffic."""
    return conn.execute(
        """SELECT r.id, r.url, r.title, c.name AS company
             FROM role r
             JOIN company c ON c.id = r.company_id
             LEFT JOIN application a ON a.role_id = r.id
            WHERE r.user_id = ?
              AND r.dropped_at IS NULL
              AND r.closed_at IS NULL
              AND c.user_state != 'HIDDEN'
              AND (a.id IS NULL OR a.status != 'HIDDEN')
            ORDER BY (a.id IS NULL), (r.last_checked_at IS NOT NULL),
                     r.last_checked_at, r.id""", (user_id,)).fetchall()


def record_check(conn: sqlite3.Connection, user_id: int, role_id: int,
                 verdict) -> None:
    """Write one verdict. CLOSED closes the role, and a SAVED application
    with it, in the same transaction as the evidence row."""
    now = _now()
    with transaction(conn):
        conn.execute(
            """INSERT INTO posting_check (role_id, checked_at, verdict,
                                          evidence, http_status, final_url)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (role_id, now, verdict.state, verdict.evidence,
             verdict.http_status, verdict.final_url))
        conn.execute("UPDATE role SET last_checked_at = ? WHERE id = ?",
                     (now, role_id))
        if verdict.state != "closed":
            return
        closed = conn.execute(
            """UPDATE role SET closed_at = ?, closed_evidence = ?
                WHERE id = ? AND closed_at IS NULL""",
            (now, verdict.evidence, role_id)).rowcount
        if not closed:
            return
        conn.execute(
            """INSERT INTO event (user_id, role_id, kind, from_status,
                                  to_status, at)
               VALUES (?, ?, 'POSTING', 'OPEN', 'CLOSED', ?)""",
            (user_id, role_id, now))
        saved = conn.execute(
            "SELECT 1 FROM application WHERE role_id = ? AND status = 'SAVED'",
            (role_id,)).fetchone()
        if saved:
            conn.execute(
                """UPDATE application SET status = 'CLOSED', updated_at = ?
                    WHERE role_id = ?""", (now, role_id))
            conn.execute(
                """INSERT INTO event (user_id, role_id, kind, from_status,
                                      to_status, at)
                   VALUES (?, ?, 'STATUS', 'SAVED', 'CLOSED', ?)""",
                (user_id, role_id, now))


def closed_posting_count(conn: sqlite3.Connection, user_id: int) -> int:
    """Roles the map hides because their posting closed - the "N HIDDEN
    (POSTING CLOSED)" clause. Same base filter as `eligibility_counts`."""
    return conn.execute(
        """SELECT COUNT(*) AS n FROM role r
             JOIN company c ON c.id = r.company_id
            WHERE r.user_id = ? AND c.user_state != 'HIDDEN'
              AND r.dropped_at IS NULL
              AND r.closed_at IS NOT NULL""", (user_id,)).fetchone()["n"]
