"""The pipeline persists what it scrapes."""
import pytest

from src.store.db import connect
from src.store.schema import init_db
from src.store.ingest import ensure_user
from src.pipeline_store import persist_run


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "test.db")
    init_db(c)
    return c


def _job(url):
    return {"company": "Acme", "title": "Analytics Engineer", "url": url,
            "location": "Remote", "salary": "", "platform": "LinkedIn",
            "date": "2026-08-08", "description": "dbt",
            "description_captured": True, "match_score": 9,
            "band": "STRONG FIT", "reason": "matches dbt",
            "matched": ["dbt"], "gaps": []}


def test_persist_run_records_a_completed_run(conn):
    user_id = ensure_user(conn, "G")
    run_id = persist_run(conn, user_id, [_job("https://x/1")], scraped=5)
    row = conn.execute("SELECT * FROM run WHERE id = ?", (run_id,)).fetchone()
    assert row["status"] == "OK"
    assert row["scraped"] == 5
    assert row["kept"] == 1


def test_persist_run_stores_the_roles(conn):
    user_id = ensure_user(conn, "G")
    persist_run(conn, user_id, [_job("https://x/1"), _job("https://x/2")],
                scraped=2)
    assert conn.execute("SELECT COUNT(*) c FROM role").fetchone()["c"] == 2


def test_a_failed_run_is_marked_failed(conn):
    user_id = ensure_user(conn, "G")
    bad = _job("https://x/1")
    del bad["title"]
    with pytest.raises(KeyError):
        persist_run(conn, user_id, [bad], scraped=1)
    row = conn.execute("SELECT * FROM run ORDER BY id DESC LIMIT 1").fetchone()
    assert row["status"] == "FAILED"


def test_setup_failure_does_not_raise(monkeypatch):
    """A broken connect()/init_db()/ensure_user() must not crash the pipeline —
    main() always calls _serve() afterward regardless of what happened here."""
    import main

    def _boom(*a, **k):
        raise RuntimeError("db is locked")

    monkeypatch.setattr("src.store.db.connect", _boom)

    main._persist_and_launch([], scraped=0, shortlist_min=7, config={})
