"""The user's profile and the resumes they own.

Where you live is a property of the person, not of a PDF; target roles and
skills are properties of one tailored document. That split is the reason this
module exists rather than more columns on `user`.

`skills` and `target_roles` are JSON columns, matching the `role.matched` and
`role.gaps` precedent. They are read whole and written whole by the confirm
screen; normalising them into child tables buys a query nobody has asked for.
"""
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
