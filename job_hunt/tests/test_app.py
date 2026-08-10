"""Tests for src/app.py — routes, not SQL."""
import pytest

from src.app import create_app
from src.store.db import connect
from src.store.schema import init_db
from src.store.ingest import ensure_user, start_run, finish_run, upsert_jobs


def _job(url, title="Analytics Engineer"):
    return {"company": "Acme", "title": title, "url": url,
            "location": "Remote", "salary": "", "platform": "LinkedIn",
            "date": "2026-08-08", "description": "dbt",
            "description_captured": True, "match_score": 9,
            "band": "STRONG FIT", "reason": "matches dbt",
            "matched": ["dbt"], "gaps": []}


@pytest.fixture
def client(tmp_path):
    db = tmp_path / "test.db"
    conn = connect(db)
    init_db(conn)
    user_id = ensure_user(conn, "G")
    run_id = start_run(conn, user_id)
    upsert_jobs(conn, user_id, run_id, [_job("https://x/1")])
    finish_run(conn, run_id, scraped=1, kept=1)
    conn.close()
    app = create_app(db_path=db, user_name="G")
    app.config.update(TESTING=True)
    return app.test_client()


def test_map_route_renders(client):
    r = client.get("/")
    assert r.status_code == 200
    assert b"Acme" in r.data


def test_map_route_shows_the_band_and_reason(client):
    body = client.get("/").data.decode("utf-8").split("<script>")[0]
    assert "STRONG FIT" in body
    assert "matches dbt" in body


def test_no_score_reaches_the_response(client):
    assert b"match_score" not in client.get("/").data


def test_activity_route_renders(client):
    r = client.get("/activity")
    assert r.status_code == 200


def test_unknown_route_is_404(client):
    assert client.get("/nope").status_code == 404
