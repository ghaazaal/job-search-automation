"""Read models for the two screens.

Every function here is the boundary between storage and rendering. The internal
`match_score` is used for ordering and for deriving a company's state, then
dropped — it must not reach a template or a JSON response.
"""
import json
import sqlite3

from .db import transaction

_ACTIVITY_COLUMNS = ("SAVED", "APPLIED", "INTERVIEWING", "OFFER", "CLOSED")


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
        "date":                 row["posted_date"],
        "url":                  row["url"],
        "description":          row["description"],
        "description_captured": bool(row["description_captured"]),
        "band":                 row["band"],
        "reason":               row["reason"],
        "matched":              json.loads(row["matched"]),
        "gaps":                 json.loads(row["gaps"]),
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


def _group(conn, rows, shortlist_min) -> list[dict]:
    """Group role rows into ranked company maps."""
    by_company: dict[int, list] = {}
    for row in rows:
        by_company.setdefault(row["company_id"], []).append(row)

    maps = []
    for company_id, group in by_company.items():
        group.sort(key=lambda r: -(r["match_score"] or 0))
        best = group[0]["match_score"] or 0
        verified = max((1 if r["eligibility_verified"] else 0)
                       for r in group)
        name = conn.execute("SELECT name FROM company WHERE id = ?",
                            (company_id,)).fetchone()["name"]
        maps.append({
            "id":    company_id,
            "name":  name,
            "state": "ACT_NOW" if best >= shortlist_min else "DISCOVER",
            "why":   _why(group),
            "roles": [_role_view(r) for r in group],
            "_rank": best,
            "_tier": verified,
        })
    maps.sort(key=lambda m: (0 if m["state"] == "ACT_NOW" else 1,
                             -m["_tier"], -m["_rank"], m["name"].lower()))
    for m in maps:
        del m["_rank"], m["_tier"]
    return maps


_OPEN_ROLES = """
SELECT r.* FROM role r
  JOIN company c ON c.id = r.company_id
  LEFT JOIN application a ON a.role_id = r.id
 WHERE r.user_id = ?
   AND a.id IS NULL
   AND c.user_state != 'HIDDEN'
   AND r.location_scope = 'open'
   AND r.first_seen_run_id {op} ?
"""


def map_sections(conn: sqlite3.Connection, user_id: int,
                 shortlist_min: int = 7) -> dict:
    """The three sections of the map screen."""
    seen = conn.execute("SELECT last_seen_run_id FROM user WHERE id = ?",
                        (user_id,)).fetchone()["last_seen_run_id"] or 0

    new_rows = conn.execute(_OPEN_ROLES.format(op=">"), (user_id, seen)).fetchall()
    old_rows = conn.execute(_OPEN_ROLES.format(op="<="), (user_id, seen)).fetchall()

    new = _group(conn, new_rows, shortlist_min) if new_rows else []
    earlier = _group(conn, old_rows, shortlist_min) if old_rows else []
    listed = {m["id"] for m in new} | {m["id"] for m in earlier}

    watching = [
        {"id": r["id"], "name": r["name"], "state": "WATCH", "roles": [],
         "why": "watched — nothing open right now"}
        for r in conn.execute(
            "SELECT id, name FROM company WHERE user_id = ? AND user_state = 'WATCH'"
            " ORDER BY name", (user_id,))
        if r["id"] not in listed
    ]
    return {"new": new, "earlier": earlier, "watching": watching}


def eligibility_counts(conn: sqlite3.Connection, user_id: int) -> dict:
    """How every stored role divides on the only question that matters.

    `unverified` is a NULL or "unknown" `location_scope` — a row nothing
    could judge. That is every LinkedIn row, whose location is a place
    rather than a reach statement, and every board row whose reach field
    was unparseable. Unverified is neither eligible nor ineligible; the
    map states the size of that set rather than implying either reading.

    Run 6's split for the working profile was 2 open, 66 closed, 316
    unverified — which is why the map stopped rendering all 384.
    """
    rows = conn.execute(
        """SELECT COALESCE(r.location_scope, 'unverified') AS verdict,
                  COUNT(*) AS n
             FROM role r
             JOIN company c ON c.id = r.company_id
            WHERE r.user_id = ? AND c.user_state != 'HIDDEN'
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
                  a.status, a.applied_at, a.updated_at
             FROM application a
             JOIN role r ON r.id = a.role_id
             JOIN company c ON c.id = r.company_id
            WHERE a.user_id = ?
            ORDER BY a.updated_at""", (user_id,)).fetchall()

    for row in rows:
        status = row["status"]
        column = "CLOSED" if status in ("REJECTED", "CLOSED") else status
        if column not in board:          # HIDDEN has no column
            continue
        board[column].append({
            "role_id":    row["id"],
            "title":      row["title"],
            "company":    row["company"],
            "location":   row["location"],
            "url":        row["url"],
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
