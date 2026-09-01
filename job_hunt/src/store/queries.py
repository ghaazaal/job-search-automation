"""Read models for the two screens.

Every function here is the boundary between storage and rendering. The internal
`match_score` is used for ordering and for deriving a company's state, then
dropped â€” it must not reach a template or a JSON response.
"""
import json
import sqlite3
from datetime import datetime, timezone

from .db import transaction


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

_ACTIVITY_COLUMNS = ("SAVED", "APPLIED", "INTERVIEWING", "OFFER",
                     "REJECTED", "CLOSED")


def mark_seen(conn: sqlite3.Connection, user_id: int, run_id: int) -> None:
    """Record that the user has looked at the map up to this run."""
    with transaction(conn):
        conn.execute("UPDATE user SET last_seen_run_id = ? WHERE id = ?",
                     (run_id, user_id))


def _role_view(row: sqlite3.Row) -> dict:
    """Shape a role for the renderers. Drops match_score."""
    return {
        "id":                   row["id"],
        "title":                row["title"],
        "location":             row["location"],
        "salary":               row["salary"],
        "platform":             row["platform"],
        "work_mode":            row["work_mode"],
        "eligibility_verified": bool(row["eligibility_verified"]),
        "location_scope":       row["location_scope"],
        "date":                 row["posted_date"],
        "url":                  row["url"],
        "description":          row["description"],
        "description_captured": bool(row["description_captured"]),
        "band":                 row["band"],
        "reason":               row["reason"],
        "matched":              json.loads(row["matched"]),
        "gaps":                 json.loads(row["gaps"]),
        "app_status":           (row["app_status"]
                                 if "app_status" in row.keys() else None),
    }


def _why(roles: list[sqlite3.Row]) -> str:
    n = len(roles)
    noun, verb = ("role", "matches") if n == 1 else ("roles", "match")
    lead = f"{n} {noun} {verb} your target titles"
    for row in roles:
        named = json.loads(row["matched"])
        if named:
            return f"{lead}, naming {named[0]} among others"
    if not roles[0]["description_captured"]:
        return f"{lead}, descriptions not captured yet"
    return lead


def _group(conn, rows, shortlist_min, watched_fps=frozenset()) -> list[dict]:
    """Group role rows into ranked company maps."""
    by_company: dict[int, list] = {}
    for row in rows:
        by_company.setdefault(row["company_id"], []).append(row)

    maps = []
    for company_id, group in by_company.items():
        group.sort(key=lambda r: -(r["match_score"] or 0))
        best = group[0]["match_score"] or 0
        # Two independent rungs, not one scale. Reach comes first â€” a
        # role proven open to this user outranks one we merely could not
        # disprove â€” and the older eligibility_verified flag still breaks
        # ties beneath it. Collapsing them into a single number let a
        # proven-open company swamp the verified/unverified distinction
        # entirely, which is a different question about a different fact.
        #
        # Ship 8 hid everything below the top rung; showing it again only
        # works if it sorts beneath.
        open_reach = max(1 if r["location_scope"] == "open" else 0
                         for r in group)
        verified = max(1 if r["eligibility_verified"] else 0 for r in group)
        company = conn.execute(
            "SELECT name, fingerprint FROM company WHERE id = ?",
            (company_id,)).fetchone()
        name = company["name"]
        maps.append({
            "id":    company_id,
            "name":  name,
            # Marker only: watching changed what was FETCHED, never how
            # anything here ranks or scores.
            "watched": company["fingerprint"] in watched_fps,
            "state": "ACT_NOW" if best >= shortlist_min else "DISCOVER",
            "why":   _why(group),
            "roles": [_role_view(r) for r in group],
            "_rank": best,
            "_tier": (open_reach, verified),
        })
    maps.sort(key=lambda m: (0 if m["state"] == "ACT_NOW" else 1,
                             -m["_tier"][0], -m["_tier"][1],
                             -m["_rank"], m["name"].lower()))
    for m in maps:
        del m["_rank"], m["_tier"]
    return maps


# Tracked roles (any application row except HIDDEN) STAY on the map,
# marked — adding a role to the board must not make it vanish here
# (decision 2026-09-01, kanban spec). HIDDEN still removes it: the user
# asked not to see it.
_OPEN_ROLES = """
SELECT r.*, a.status AS app_status FROM role r
  JOIN company c ON c.id = r.company_id
  LEFT JOIN application a ON a.role_id = r.id
 WHERE r.user_id = ?
   AND (a.id IS NULL OR a.status != 'HIDDEN')
   AND c.user_state != 'HIDDEN'
   AND r.dropped_at IS NULL
   AND (r.location_scope IS NULL OR r.location_scope != 'closed')
   AND r.first_seen_run_id {op} ?
"""


def map_sections(conn: sqlite3.Connection, user_id: int,
                 shortlist_min: int = 7) -> dict:
    """The three sections of the map screen."""
    seen = conn.execute("SELECT last_seen_run_id FROM user WHERE id = ?",
                        (user_id,)).fetchone()["last_seen_run_id"] or 0

    new_rows = conn.execute(_OPEN_ROLES.format(op=">"), (user_id, seen)).fetchall()
    old_rows = conn.execute(_OPEN_ROLES.format(op="<="), (user_id, seen)).fetchall()

    from .watchlist import watched_fingerprints
    watched_fps = watched_fingerprints(conn, user_id)

    new = (_group(conn, new_rows, shortlist_min, watched_fps)
           if new_rows else [])
    earlier = (_group(conn, old_rows, shortlist_min, watched_fps)
               if old_rows else [])
    listed = {m["id"] for m in new} | {m["id"] for m in earlier}

    watching = [
        {"id": r["id"], "name": r["name"], "state": "WATCH", "roles": [],
         "why": "watched â€” nothing open right now"}
        for r in conn.execute(
            "SELECT id, name FROM company WHERE user_id = ? AND user_state = 'WATCH'"
            " ORDER BY name", (user_id,))
        if r["id"] not in listed
    ]
    return {"new": new, "earlier": earlier, "watching": watching}


def drop_roles_from_runs(conn: sqlite3.Connection, user_id: int, *,
                         through_run_id: int) -> int:
    """Soft-drop every role first seen in a run at or before `through_run_id`.

    Soft, never DELETE. The 800 roles this was written for were stored
    before the relevance gate existed - Nurse Practitioner, Travel
    Advisor, Fleet Parking Specialist - so they are off-target, not
    fictional. A cleanup rule that turns out to be wrong has to be
    recoverable, and `dropped_at` makes it a column change rather than a
    restore from backup.

    A role the user has acted on is never dropped. Whatever the rules say
    about a posting, a job they applied to is part of their history.
    Returns the number newly dropped, so running it twice reports 0 the
    second time rather than silently re-stamping.
    """
    with transaction(conn):
        cursor = conn.execute(
            """UPDATE role SET dropped_at = ?
                WHERE user_id = ?
                  AND first_seen_run_id <= ?
                  AND dropped_at IS NULL
                  AND id NOT IN (SELECT role_id FROM application
                                  WHERE user_id = ?)""",
            (_now(), user_id, through_run_id, user_id))
        return cursor.rowcount


def eligibility_counts(conn: sqlite3.Connection, user_id: int) -> dict:
    """How every stored role divides on the only question that matters.

    `unverified` is a NULL or "unknown" `location_scope` â€” a row nothing
    could judge. That is every LinkedIn row, whose location is a place
    rather than a reach statement, and every board row whose reach field
    was unparseable. Unverified is neither eligible nor ineligible; the
    map states the size of that set rather than implying either reading.

    Run 6's split for the working profile was 2 open, 66 closed, 316
    unverified â€” which is why the map stopped rendering all 384.
    """
    rows = conn.execute(
        """SELECT COALESCE(r.location_scope, 'unverified') AS verdict,
                  COUNT(*) AS n
             FROM role r
             JOIN company c ON c.id = r.company_id
            WHERE r.user_id = ? AND c.user_state != 'HIDDEN'
              AND r.dropped_at IS NULL
            GROUP BY verdict""", (user_id,)).fetchall()
    counts = {row["verdict"]: row["n"] for row in rows}
    return {"open": counts.get("open", 0),
            "closed": counts.get("closed", 0),
            "unverified": (counts.get("unverified", 0)
                           + counts.get("unknown", 0))}


def activity_board(conn: sqlite3.Connection, user_id: int) -> dict:
    """Roles the user has acted on, grouped by status, oldest first."""
    board: dict[str, list] = {col: [] for col in _ACTIVITY_COLUMNS}
    rows = conn.execute(
        """SELECT r.id, r.title, r.url, r.location, c.name AS company,
                  r.band, r.reason, r.description_captured,
                  a.status, a.applied_at, a.updated_at
             FROM application a
             JOIN role r ON r.id = a.role_id
             JOIN company c ON c.id = r.company_id
            WHERE a.user_id = ?
            ORDER BY a.updated_at""", (user_id,)).fetchall()

    for row in rows:
        status = row["status"]
        if status not in board:          # HIDDEN has no column
            continue
        board[status].append({
            "role_id":    row["id"],
            "title":      row["title"],
            "company":    row["company"],
            "location":   row["location"],
            "url":        row["url"],
            "band":       row["band"],
            "reason":     row["reason"],
            "description_captured": bool(row["description_captured"]),
            "status":     status,
            "updated_at": row["updated_at"],
            "events": [dict(e) for e in conn.execute(
                "SELECT from_status, to_status, at FROM event"
                " WHERE role_id = ? AND kind = 'STATUS' ORDER BY at, id",
                (row["id"],))],
        })
    return board


def known_listings(conn: sqlite3.Connection,
                   user_id: int) -> tuple[list[str], list[dict]]:
    """Every role this user has already stored, shaped for `dedupe`.

    The terminal run reads this from the Excel workbook. A browser run has no
    workbook, so the store answers instead: the URLs it has seen, and the
    company/title pairs `dedupe` fingerprints to catch a repost that came back
    under a new URL.
    """
    rows = conn.execute(
        """SELECT r.url, r.title, c.name AS company
             FROM role r
             JOIN company c ON c.id = r.company_id
            WHERE r.user_id = ?""", (user_id,)).fetchall()
    urls = [row["url"] for row in rows]
    pairs = [{"company": row["company"], "title": row["title"]} for row in rows]
    return urls, pairs
