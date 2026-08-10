"""Tests for src/store/tracking.py — status moves and their event log."""
import sqlite3

import pytest

from src.store.db import connect
from src.store.schema import init_db
from src.store.ingest import ensure_user, start_run, upsert_jobs
from src.store.tracking import (STATUSES, set_role_status, role_status,
                                set_company_state, role_events)


@pytest.fixture
def ctx(tmp_path):
    conn = connect(tmp_path / "test.db")
    init_db(conn)
    user_id = ensure_user(conn, "Ghazal")
    run_id = start_run(conn, user_id)
    upsert_jobs(conn, user_id, run_id, [{
        "company": "Acme", "title": "Analytics Engineer", "url": "https://x/1",
        "location": "Remote", "salary": "", "platform": "LinkedIn",
        "date": "2026-08-08", "description": "dbt", "description_captured": True,
        "match_score": 9, "band": "STRONG FIT", "reason": "matches dbt",
        "matched": ["dbt"], "gaps": []}])
    role_id = conn.execute("SELECT id FROM role").fetchone()["id"]
    company_id = conn.execute("SELECT id FROM company").fetchone()["id"]
    return conn, user_id, role_id, company_id


def test_untouched_role_reads_as_new(ctx):
    conn, user_id, role_id, _ = ctx
    assert role_status(conn, role_id) == "NEW"


def test_saving_a_role_sets_its_status(ctx):
    conn, user_id, role_id, _ = ctx
    set_role_status(conn, user_id, role_id, "SAVED")
    assert role_status(conn, role_id) == "SAVED"


def test_every_move_writes_an_event(ctx):
    conn, user_id, role_id, _ = ctx
    set_role_status(conn, user_id, role_id, "SAVED")
    set_role_status(conn, user_id, role_id, "APPLIED")
    set_role_status(conn, user_id, role_id, "INTERVIEWING")
    events = role_events(conn, role_id)
    assert [e["to_status"] for e in events] == ["SAVED", "APPLIED", "INTERVIEWING"]
    assert events[1]["from_status"] == "SAVED"


def test_status_and_latest_event_never_disagree(ctx):
    conn, user_id, role_id, _ = ctx
    for status in ("SAVED", "APPLIED", "OFFER"):
        set_role_status(conn, user_id, role_id, status)
        assert role_status(conn, role_id) == role_events(conn, role_id)[-1]["to_status"]


def test_applied_at_is_stamped_once(ctx):
    conn, user_id, role_id, _ = ctx
    set_role_status(conn, user_id, role_id, "APPLIED")
    first = conn.execute("SELECT applied_at FROM application").fetchone()["applied_at"]
    set_role_status(conn, user_id, role_id, "INTERVIEWING")
    assert conn.execute(
        "SELECT applied_at FROM application").fetchone()["applied_at"] == first


def test_backwards_moves_are_allowed_and_logged(ctx):
    """A mis-click must be correctable, and the correction recorded."""
    conn, user_id, role_id, _ = ctx
    set_role_status(conn, user_id, role_id, "APPLIED")
    set_role_status(conn, user_id, role_id, "SAVED")
    assert role_status(conn, role_id) == "SAVED"
    assert len(role_events(conn, role_id)) == 2


def test_invalid_status_is_rejected(ctx):
    conn, user_id, role_id, _ = ctx
    with pytest.raises(ValueError):
        set_role_status(conn, user_id, role_id, "MAYBE")


def test_new_cannot_be_set_as_a_status(ctx):
    conn, user_id, role_id, _ = ctx
    with pytest.raises(ValueError):
        set_role_status(conn, user_id, role_id, "NEW")


def test_statuses_constant_matches_the_pipeline(ctx):
    assert STATUSES == ("SAVED", "APPLIED", "INTERVIEWING", "OFFER",
                        "REJECTED", "CLOSED", "HIDDEN")


def test_watching_a_company_persists_and_logs(ctx):
    conn, user_id, _, company_id = ctx
    set_company_state(conn, user_id, company_id, "WATCH")
    assert conn.execute("SELECT user_state FROM company WHERE id=?",
                        (company_id,)).fetchone()["user_state"] == "WATCH"
    assert conn.execute(
        "SELECT COUNT(*) c FROM event WHERE company_id=?",
        (company_id,)).fetchone()["c"] == 1


def test_invalid_company_state_is_rejected(ctx):
    conn, user_id, _, company_id = ctx
    with pytest.raises(ValueError):
        set_company_state(conn, user_id, company_id, "MAYBE")


def test_set_role_status_on_missing_role_raises(ctx):
    conn, user_id, _, _ = ctx
    with pytest.raises(sqlite3.IntegrityError):
        set_role_status(conn, user_id, 999999, "SAVED")


def test_set_company_state_on_missing_company_raises(ctx):
    conn, user_id, _, _ = ctx
    with pytest.raises(sqlite3.IntegrityError):
        set_company_state(conn, user_id, 999999, "WATCH")
