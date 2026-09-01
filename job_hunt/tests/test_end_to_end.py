"""Acceptance criteria from the spec, exercised through the app."""
import json

import pytest

from src.app import create_app
from src.store.db import connect
from src.store.ingest import ensure_user, upsert_jobs
from src.store.profile import create_resume, set_profile, update_resume
from src.store.runs import finish_run, start_run
from src.store.schema import init_db


def _job(url, title="Analytics Engineer", **kw):
    base = {"company": "Acme", "title": title, "url": url, "location": "Remote",
            "salary": "", "platform": "LinkedIn", "date": "2026-08-08",
            "description": "dbt", "description_captured": True,
            "match_score": 9, "band": "STRONG FIT", "reason": "matches dbt",
            "matched": ["dbt"], "gaps": []}
    return {**base, **kw}


def _finish_setup(conn, user_id):
    """Give the user an active resume and a complete profile, the two
    things map_screen now requires before it will render the map at all."""
    resume_id = create_resume(conn, user_id, label="ae",
                              orig_filename="ae.pdf", sha256="abc",
                              stored_path="resumes/1/abc.pdf",
                              extracted_text="dbt")
    update_resume(conn, user_id, resume_id, label="ae",
                  target_roles=[{"title": "Analytics Engineer", "aliases": []}],
                  skills=[{"name": "dbt", "tier": "core", "aliases": []}],
                  seniority="senior")
    set_profile(conn, user_id, location="Toronto, ON", country="ca",
                work_modes=["remote"])


@pytest.fixture
def env(tmp_path):
    db = tmp_path / "e2e.db"
    conn = connect(db)
    init_db(conn)
    user_id = ensure_user(conn, "G")
    _finish_setup(conn, user_id)
    run_id = start_run(conn, user_id)
    upsert_jobs(conn, user_id, run_id, [_job("https://x/1")])
    finish_run(conn, run_id, scraped=1, kept=1)
    role_id = conn.execute("SELECT id FROM role").fetchone()["id"]
    conn.close()
    app = create_app(db_path=db, user_name="G")
    app.config.update(TESTING=True)
    return app.test_client(), db, role_id


def test_criterion_2_a_status_change_persists(env):
    client, db, role_id = env
    assert client.post(f"/api/roles/{role_id}/status",
                       json={"status": "APPLIED"}).status_code == 200
    conn = connect(db)
    assert conn.execute(
        "SELECT status FROM application WHERE role_id = ?",
        (role_id,)).fetchone()["status"] == "APPLIED"
    conn.close()


def test_criterion_5_applied_reaches_the_board_and_the_map_marks_it(env):
    """Superseded criterion (2026-09-01): a tracked role used to LEAVE the
    map; now it stays there marked IN TRACKER, and is on the board."""
    client, _, role_id = env
    client.post(f"/api/roles/{role_id}/status", json={"status": "APPLIED"})
    map_data = client.get("/").data
    assert b"Analytics Engineer" in map_data
    assert b"IN TRACKER" in map_data
    assert b"Analytics Engineer" in client.get("/activity").data


def test_criterion_5b_hidden_leaves_both_map_and_board(env):
    client, _, role_id = env
    client.post(f"/api/roles/{role_id}/status", json={"status": "HIDDEN"})
    assert b"Analytics Engineer" not in client.get("/").data
    assert b"Analytics Engineer" not in client.get("/activity").data


def test_criterion_6_the_event_log_has_a_row_per_move(env):
    client, db, role_id = env
    for status in ("SAVED", "APPLIED", "INTERVIEWING"):
        client.post(f"/api/roles/{role_id}/status", json={"status": status})
    conn = connect(db)
    rows = conn.execute(
        "SELECT to_status FROM event WHERE role_id=? ORDER BY id",
        (role_id,)).fetchall()
    conn.close()
    assert [r["to_status"] for r in rows] == ["SAVED", "APPLIED", "INTERVIEWING"]


def test_criterion_7_pragmas_hold_on_a_fresh_connection(env):
    _, db, _ = env
    conn = connect(db)
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    conn.close()


def test_criterion_8_an_invalid_status_is_refused(env):
    client, _, role_id = env
    assert client.post(f"/api/roles/{role_id}/status",
                       json={"status": "MAYBE"}).status_code == 400


def test_criterion_9_no_score_in_any_response(env):
    client, _, role_id = env
    responses = [
        client.post(f"/api/roles/{role_id}/status", json={"status": "SAVED"}),
        client.get("/"),
        client.get("/activity"),
    ]
    for r in responses:
        assert b"match_score" not in r.data


def test_criterion_10_a_missing_database_is_created_on_demand(tmp_path):
    db = tmp_path / "brand-new.db"
    assert not db.exists()
    app = create_app(db_path=db, user_name="G")
    app.config.update(TESTING=True)
    # No resume or profile exists for a genuinely brand-new user, so the map
    # route sends them to setup instead of erroring — but the db file itself
    # must now exist, proving it was created rather than the app crashing.
    response = app.test_client().get("/")
    assert response.status_code == 302
    assert "/setup" in response.headers["Location"]
    assert db.exists()
