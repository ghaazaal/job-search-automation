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
   AND {current}
"""


def _is_current(conn: sqlite3.Connection,
                max_age_days: int | None) -> tuple[str, tuple]:
    """A SQL condition on `role r`: something in the last `max_age_days`
    says this posting is still up. Returns (sql, params).

    Three kinds of evidence, any one enough: the posting's own date, a
    search that found it again (`last_seen_run_id`, see
    `ingest.mark_reseen`), or a liveness check that saw it open. Without
    any of them a role is out of date - on 2026-10-15 the map still
    carried postings first and last seen in August. A role the user has
    acted on stays whatever its age, like every other map rule.

    None or 0 switches the rule off.
    """
    if not max_age_days:
        return "1", ()
    since = f"-{int(max_age_days)} days"
    parts = ["EXISTS (SELECT 1 FROM application ap WHERE ap.role_id = r.id"
             " AND ap.status != 'HIDDEN')",
             "date(r.posted_date) >= date('now', ?)",
             "(SELECT date(started_at) FROM run"
             " WHERE id = r.last_seen_run_id) >= date('now', ?)"]
    params = [since, since]
    # The liveness checker's table, where that feature is present.
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table'"
                    " AND name = 'posting_check'").fetchone():
        parts.append("EXISTS (SELECT 1 FROM posting_check pc"
                     " WHERE pc.role_id = r.id AND pc.verdict = 'open'"
                     " AND date(pc.checked_at) >= date('now', ?))")
        params.append(since)
    return "(" + " OR ".join(parts) + ")", tuple(params)


def _one_per_posting(*row_lists) -> tuple[list[list], int]:
    """Keep one row per company and posting; return the lists and how many
    rows were set aside as copies.

    Stored before `dedupe` learned to ignore per-copy title noise: TELUS
    Digital's "Online Data Analyst" in seven languages, BairesDev's one
    REF# per country, Ryder's "Data Analyst III" with and without
    "(remote)". The best-scoring copy stays, then the most recent.
    """
    from ..tracker.dedup import title_key
    best: dict[tuple, sqlite3.Row] = {}
    for row in (r for rows in row_lists for r in rows):
        key = (row["company_id"], title_key(row["title"]))
        rank = (row["match_score"] or 0, row["posted_date"] or "", row["id"])
        held = best.get(key)
        if held is None or rank > (held["match_score"] or 0,
                                   held["posted_date"] or "", held["id"]):
            best[key] = row
    winners = {row["id"] for row in best.values()}
    kept = [[r for r in rows if r["id"] in winners] for rows in row_lists]
    copies = sum(len(rows) for rows in row_lists) - len(winners)
    return kept, copies


def map_sections(conn: sqlite3.Connection, user_id: int,
                 shortlist_min: int = 7,
                 max_age_days: int | None = None) -> dict:
    """The three sections of the map screen.

    `duplicates` counts the copies `_one_per_posting` set aside."""
    seen = conn.execute("SELECT last_seen_run_id FROM user WHERE id = ?",
                        (user_id,)).fetchone()["last_seen_run_id"] or 0

    current, cur_params = _is_current(conn, max_age_days)
    new_rows = conn.execute(_OPEN_ROLES.format(op=">", current=current),
                            (user_id, seen, *cur_params)).fetchall()
    old_rows = conn.execute(_OPEN_ROLES.format(op="<=", current=current),
                            (user_id, seen, *cur_params)).fetchall()
    (new_rows, old_rows), duplicates = _one_per_posting(new_rows, old_rows)

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
    return {"new": new, "earlier": earlier, "watching": watching,
            "duplicates": duplicates}


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


def eligibility_counts(conn: sqlite3.Connection, user_id: int,
                       max_age_days: int | None = None) -> dict:
    """How every stored role divides on the only question that matters.

    `unverified` is a NULL or "unknown" `location_scope` â€” a row nothing
    could judge. That is every LinkedIn row, whose location is a place
    rather than a reach statement, and every board row whose reach field
    was unparseable. Unverified is neither eligible nor ineligible; the
    map states the size of that set rather than implying either reading.

    Run 6's split for the working profile was 2 open, 66 closed, 316
    unverified â€” which is why the map stopped rendering all 384.

    `stale`, present only when `max_age_days` is set, is an open or
    unverified role `_is_current` rules out of date.
    A role both out of date and not open counts once, as not open - the
    posting's own words outrank its age.
    """
    current, cur_params = _is_current(conn, max_age_days)
    rows = conn.execute(
        f"""SELECT COALESCE(r.location_scope, 'unverified') AS verdict,
                  {current} AS is_current,
                  COUNT(*) AS n
             FROM role r
             JOIN company c ON c.id = r.company_id
            WHERE r.user_id = ? AND c.user_state != 'HIDDEN'
              AND r.dropped_at IS NULL
            GROUP BY verdict, is_current""",
        (*cur_params, user_id)).fetchall()
    counts: dict[str, int] = {}
    stale = 0
    for row in rows:
        if row["verdict"] != "closed" and not row["is_current"]:
            stale += row["n"]
        else:
            counts[row["verdict"]] = counts.get(row["verdict"], 0) + row["n"]
    result = {"open": counts.get("open", 0),
              "closed": counts.get("closed", 0),
              "unverified": (counts.get("unverified", 0)
                             + counts.get("unknown", 0))}
    if max_age_days:
        result["stale"] = stale
    return result


def activity_board(conn: sqlite3.Connection, user_id: int) -> dict:
    """Roles the user has acted on, grouped by status, oldest first.

    Carries everything the shared role drawer needs (matched, gaps, work
    mode, salary, posted date) so the tracker's ROLE button can open the
    same panel the map does."""
    board: dict[str, list] = {col: [] for col in _ACTIVITY_COLUMNS}
    rows = conn.execute(
        """SELECT r.id, r.title, r.url, r.location, c.name AS company,
                  c.id AS company_id, r.band, r.reason,
                  r.description_captured, r.matched, r.gaps, r.work_mode,
                  r.salary, r.posted_date,
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
            "company_id": row["company_id"],
            "location":   row["location"],
            "url":        row["url"],
            "band":       row["band"],
            "reason":     row["reason"],
            "description_captured": bool(row["description_captured"]),
            "matched":    json.loads(row["matched"]),
            "gaps":       json.loads(row["gaps"]),
            "work_mode":  row["work_mode"],
            "salary":     row["salary"],
            "date":       row["posted_date"],
            "status":     status,
            "applied_at": row["applied_at"],
            "updated_at": row["updated_at"],
            "events": [dict(e) for e in conn.execute(
                "SELECT from_status, to_status, at FROM event"
                " WHERE role_id = ? AND kind = 'STATUS' ORDER BY at, id",
                (row["id"],))],
        })
    return board


# The four statuses that count as "in flight" on the shell's TRACKER tab
# and the board header. Rejected and closed are outcomes, not motion.
LIVE_STATUSES = ("SAVED", "APPLIED", "INTERVIEWING", "OFFER")


def live_tracker_count(conn: sqlite3.Connection, user_id: int) -> int:
    """How many applications are in flight — the shell's TRACKER badge."""
    marks = ",".join("?" for _ in LIVE_STATUSES)
    return conn.execute(
        f"SELECT COUNT(*) AS n FROM application"
        f" WHERE user_id = ? AND status IN ({marks})",
        (user_id, *LIVE_STATUSES)).fetchone()["n"]


def open_company_count(conn: sqlite3.Connection, user_id: int,
                       max_age_days: int | None = None) -> int:
    """How many companies the map lists — the shell's MAP badge.

    Same filter as the map's role query, without the seen/unseen split."""
    current, cur_params = _is_current(conn, max_age_days)
    return conn.execute(
        f"""SELECT COUNT(DISTINCT r.company_id) AS n FROM role r
             JOIN company c ON c.id = r.company_id
             LEFT JOIN application a ON a.role_id = r.id
            WHERE r.user_id = ?
              AND (a.id IS NULL OR a.status != 'HIDDEN')
              AND c.user_state != 'HIDDEN'
              AND r.dropped_at IS NULL
              AND (r.location_scope IS NULL OR r.location_scope != 'closed')
              AND {current}""",
        (user_id, *cur_params)).fetchone()["n"]


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
