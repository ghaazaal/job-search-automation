"""Bridge between the scrape pipeline and the store.

Kept separate from `main.py` so the persistence path is testable without
running a scrape.
"""
import sqlite3

from .store.ingest import finish_run, start_run, upsert_jobs


def persist_run(conn: sqlite3.Connection, user_id: int,
                scored_jobs: list[dict], scraped: int) -> int:
    """Write a completed scrape. Marks the run FAILED if ingest raises."""
    run_id = start_run(conn, user_id)
    try:
        upsert_jobs(conn, user_id, run_id, scored_jobs)
    except Exception:
        finish_run(conn, run_id, scraped=scraped, kept=0, ok=False)
        raise
    finish_run(conn, run_id, scraped=scraped, kept=len(scored_jobs))
    return run_id
