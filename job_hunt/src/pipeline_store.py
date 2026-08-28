"""Bridge between the scrape pipeline and the store.

Kept separate from `main.py` so the persistence path is testable without
running a scrape.
"""
import sqlite3

from .store.ingest import upsert_jobs
from .store.runs import finish_run


def persist_run(conn: sqlite3.Connection, user_id: int, run_id: int,
                scored_jobs: list[dict], scraped: int,
                dropped: int = 0, offtopic: int = 0,
                boards: list[str] | None = None) -> int:
    """Write a completed scrape into a run that already exists.

    The caller creates the run. A browser-triggered run needs its id returned
    to the page before any scraping starts, so creating it here would be too
    late; the terminal path calls `start_run` for the same reason.
    """
    try:
        upsert_jobs(conn, user_id, run_id, scored_jobs)
    except Exception:
        finish_run(conn, run_id, scraped=scraped, kept=0, ok=False,
                  dropped=dropped, offtopic=offtopic, boards=boards)
        raise
    finish_run(conn, run_id, scraped=scraped, kept=len(scored_jobs),
              dropped=dropped, offtopic=offtopic, boards=boards)
    return run_id
