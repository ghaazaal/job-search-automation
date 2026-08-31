"""Who a user watches, and what resolution learned about each company.

Identity, resolution state, and execution state for the company
watchlist. This module is a pure store: nothing here calls an actor —
`scrapers/watched.py` decides, this module remembers.

Which companies a user watches is a fact about a person, which is why it
lives here and can never enter vocabulary.yaml.
"""
import re
import sqlite3
from datetime import datetime, timezone

from .db import transaction
from ..tracker.dedup import fingerprint


class AlreadyWatched(ValueError):
    """The same company (by fingerprint) is already on this user's list."""


_SLUG_RE = re.compile(r"linkedin\.com/company/([^/?#]+)", re.I)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def slug_from_url(url: str | None) -> str | None:
    """The company slug out of a LinkedIn URL, or None.

    The slug is v1's disambiguator: `companyId` on the actor is dead
    (validated 2026-08-31 — a nonsense id returns unfiltered rows), but
    every returned row carries `companyUrl`, and the slug in it tells
    Andersen-the-IT-firm (/company/andersenus) apart from
    Andersen-the-window-manufacturer, which share the display name.
    """
    match = _SLUG_RE.search(str(url or ""))
    return match.group(1).strip().lower() if match else None


def add(conn: sqlite3.Connection, user_id: int, *, name: str,
        domain: str = "", linkedin_url: str = "") -> int:
    """Watch a company. Returns the new row id.

    With a pasted LinkedIn URL the row resolves immediately — the slug is
    the disambiguator, so there is nothing left to probe. Without one it
    starts 'unresolved' and the next run's watched step resolves it: the
    POST handler must stay fast, so no probe ever runs at add time.
    """
    name = (name or "").strip()
    if not name:
        raise ValueError("a company needs a name")
    fp = fingerprint({"company": name, "title": ""})
    slug = slug_from_url(linkedin_url)
    try:
        with transaction(conn):
            cursor = conn.execute(
                """INSERT INTO watched_company
                       (user_id, company_name, company_fingerprint, domain,
                        resolution, resolution_note, linkedin_name,
                        linkedin_slug, resolved_at, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (user_id, name, fp,
                 (domain or "").strip().lower() or None,
                 "linkedin" if slug else "unresolved",
                 None if slug else "pending next run",
                 name if slug else None, slug,
                 _now() if slug else None, _now()))
            return cursor.lastrowid
    except sqlite3.IntegrityError as exc:
        raise AlreadyWatched(name) from exc


def get(conn: sqlite3.Connection, user_id: int,
        watch_id: int) -> dict | None:
    row = conn.execute(
        "SELECT * FROM watched_company WHERE user_id = ? AND id = ?",
        (user_id, watch_id)).fetchone()
    return dict(row) if row else None


def list_watched(conn: sqlite3.Connection, user_id: int) -> list[dict]:
    return [dict(r) for r in conn.execute(
        """SELECT * FROM watched_company WHERE user_id = ?
            ORDER BY company_name""", (user_id,))]


def remove(conn: sqlite3.Connection, user_id: int, watch_id: int) -> None:
    with transaction(conn):
        conn.execute(
            "DELETE FROM watched_company WHERE user_id = ? AND id = ?",
            (user_id, watch_id))


def set_resolution(conn: sqlite3.Connection, user_id: int, watch_id: int,
                   resolution: str, *, note: str | None = None,
                   linkedin_name: str | None = None,
                   linkedin_slug: str | None = None) -> None:
    with transaction(conn):
        conn.execute(
            """UPDATE watched_company
                  SET resolution = ?, resolution_note = ?,
                      linkedin_name = COALESCE(?, linkedin_name),
                      linkedin_slug = COALESCE(?, linkedin_slug),
                      resolved_at = ?
                WHERE user_id = ? AND id = ?""",
            (resolution, note, linkedin_name, linkedin_slug, _now(),
             user_id, watch_id))


def record_yield(conn: sqlite3.Connection, user_id: int,
                 counts: dict[str, int]) -> None:
    """counts: company_fingerprint -> rows that survived the ingest filter."""
    now = _now()
    with transaction(conn):
        for fp, n in counts.items():
            conn.execute(
                """UPDATE watched_company
                      SET last_fetched_at = ?, last_yield_count = ?
                    WHERE user_id = ? AND company_fingerprint = ?""",
                (now, n, user_id, fp))


def watched_fingerprints(conn: sqlite3.Connection, user_id: int) -> set[str]:
    """For the map's WATCHLIST chip — the join path to `company` rows.

    Fingerprint-based because a `company` row is not guaranteed to exist
    before ingestion creates it. Inherits the documented fingerprint
    weakness: "Proxify" and "Proxify AB" fingerprint apart.
    """
    return {r["company_fingerprint"] for r in conn.execute(
        "SELECT company_fingerprint FROM watched_company WHERE user_id = ?",
        (user_id,))}
