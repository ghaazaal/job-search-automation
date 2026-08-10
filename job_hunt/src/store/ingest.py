"""Writing a scrape run into the store.

This module owns the scrape half of the database and never touches
`application` or `event` — what the user decided is not the scraper's business.
"""
import json
import sqlite3
from datetime import datetime, timezone

from .db import transaction
from ..tracker.dedup import fingerprint, normalize_url

# Batch size keeps write transactions short so the web app is not locked out
# for the length of a run.
BATCH = 50


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ensure_user(conn: sqlite3.Connection, name: str, email: str = "") -> int:
    row = conn.execute("SELECT id FROM user WHERE name = ?", (name,)).fetchone()
    if row:
        return row["id"]
    with transaction(conn):
        conn.execute(
            "INSERT INTO user (name, email, created_at) VALUES (?, ?, ?)",
            (name, email, _now()))
    return conn.execute("SELECT id FROM user WHERE name = ?", (name,)).fetchone()["id"]


def start_run(conn: sqlite3.Connection, user_id: int) -> int:
    with transaction(conn):
        conn.execute(
            "INSERT INTO run (user_id, started_at, status) VALUES (?, ?, 'RUNNING')",
            (user_id, _now()))
    return conn.execute("SELECT last_insert_rowid() AS i").fetchone()["i"]


def finish_run(conn: sqlite3.Connection, run_id: int,
               scraped: int, kept: int, ok: bool = True) -> None:
    with transaction(conn):
        conn.execute(
            """UPDATE run SET status = ?, finished_at = ?, scraped = ?, kept = ?
               WHERE id = ?""",
            ("OK" if ok else "FAILED", _now(), scraped, kept, run_id))


def _company_id(conn: sqlite3.Connection, user_id: int, name: str) -> int:
    fp = fingerprint({"company": name, "title": ""})
    row = conn.execute(
        "SELECT id FROM company WHERE user_id = ? AND fingerprint = ?",
        (user_id, fp)).fetchone()
    if row:
        conn.execute("UPDATE company SET last_seen_at = ? WHERE id = ?",
                     (_now(), row["id"]))
        return row["id"]
    conn.execute(
        """INSERT INTO company (user_id, name, fingerprint, first_seen_at, last_seen_at)
           VALUES (?, ?, ?, ?, ?)""",
        (user_id, name, fp, _now(), _now()))
    return conn.execute("SELECT last_insert_rowid() AS i").fetchone()["i"]


def _upsert_role(conn: sqlite3.Connection, user_id: int, run_id: int,
                 job: dict) -> None:
    company_id = _company_id(conn, user_id, job["company"])
    url_n = normalize_url(job["url"])
    existing = conn.execute(
        "SELECT id FROM role WHERE user_id = ? AND url_normalised = ?",
        (user_id, url_n)).fetchone()

    values = (
        job["title"], job.get("location"), job.get("salary"),
        job.get("platform"), str(job.get("date") or ""),
        job.get("description") or "",
        1 if job.get("description_captured") else 0,
        job.get("match_score"), job.get("band"), job.get("reason"),
        json.dumps(list(job.get("matched") or [])),
        json.dumps(list(job.get("gaps") or [])),
    )

    if existing:
        conn.execute(
            """UPDATE role SET title=?, location=?, salary=?, platform=?,
                   posted_date=?, description=?, description_captured=?,
                   match_score=?, band=?, reason=?, matched=?, gaps=?,
                   last_seen_run_id=?
               WHERE id=?""",
            (*values, run_id, existing["id"]))
    else:
        conn.execute(
            """INSERT INTO role (user_id, company_id, url, url_normalised,
                   title, location, salary, platform, posted_date, description,
                   description_captured, match_score, band, reason, matched, gaps,
                   first_seen_run_id, last_seen_run_id)
               VALUES (?,?,?,?, ?,?,?,?,?,?, ?,?,?,?,?,?, ?,?)""",
            (user_id, company_id, job["url"], url_n, *values, run_id, run_id))


def upsert_jobs(conn: sqlite3.Connection, user_id: int, run_id: int,
                jobs: list[dict]) -> None:
    """Write scored jobs in short batches so writers do not block the app."""
    for start in range(0, len(jobs), BATCH):
        with transaction(conn):
            for job in jobs[start:start + BATCH]:
                _upsert_role(conn, user_id, run_id, job)
