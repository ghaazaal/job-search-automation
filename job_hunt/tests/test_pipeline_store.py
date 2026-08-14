"""Tests for src/pipeline_store.py — the bridge from a scrape to the store."""
import pytest

from src.pipeline_store import persist_run
from src.store.db import connect
from src.store.ingest import ensure_user
from src.store.runs import get_run, start_run
from src.store.schema import init_db


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "persist.db")
    init_db(c)
    yield c
    c.close()


_JOB = {"cat": "BI Developer", "title": "BI Developer", "company": "Acme",
        "location": "Toronto, ON", "platform": "Indeed", "date": "2026-08-14",
        "url": "https://example.com/j1", "salary": "", "description": "Power BI",
        "match_score": 8, "band": "STRONG FIT", "reason": "matches Power BI",
        "matched": ["Power BI"], "gaps": [], "resume_id": None,
        "description_captured": True}


def test_persist_writes_into_the_run_it_was_given(conn):
    user_id = ensure_user(conn, "default")
    run_id = start_run(conn, user_id)

    persist_run(conn, user_id, run_id, [_JOB], scraped=1)

    stored = get_run(conn, run_id)
    assert stored["status"] == "OK"
    assert (stored["scraped"], stored["kept"]) == (1, 1)


def test_persist_does_not_create_a_second_run(conn):
    user_id = ensure_user(conn, "default")
    run_id = start_run(conn, user_id)

    persist_run(conn, user_id, run_id, [_JOB], scraped=1)

    total = conn.execute("SELECT COUNT(*) AS n FROM run").fetchone()["n"]
    assert total == 1


def test_a_failing_ingest_marks_the_run_failed_and_re_raises(conn):
    user_id = ensure_user(conn, "default")
    run_id = start_run(conn, user_id)
    broken = {**_JOB, "url": None}      # NOT NULL on role.url

    with pytest.raises(Exception):
        persist_run(conn, user_id, run_id, [broken], scraped=1)

    assert get_run(conn, run_id)["status"] == "FAILED"
