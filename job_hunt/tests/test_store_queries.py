"""Tests for src/store/queries.py — what the screens are allowed to see."""
import json

import pytest

from src.store.db import connect
from src.store.schema import init_db
from src.store.ingest import ensure_user, upsert_jobs
from src.store.runs import start_run, finish_run
from src.store.tracking import set_role_status, set_company_state
from src.store.queries import map_sections, activity_board, mark_seen


def _job(url, company="Acme", title="Analytics Engineer", score=9, **kw):
    base = {"company": company, "title": title, "url": url,
            "location": "Remote, US", "salary": "", "platform": "LinkedIn",
            "date": "2026-08-08", "description": "dbt", "match_score": score,
            "description_captured": True, "band": "STRONG FIT",
            "reason": "matches dbt", "matched": ["dbt"], "gaps": ["snowflake"]}
    return {**base, **kw}


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "test.db")
    init_db(c)
    return c


def _run_with(conn, user_id, jobs):
    run_id = start_run(conn, user_id)
    upsert_jobs(conn, user_id, run_id, jobs)
    finish_run(conn, run_id, scraped=len(jobs), kept=len(jobs))
    return run_id


def test_first_run_is_all_new(conn):
    u = ensure_user(conn, "G")
    _run_with(conn, u, [_job("https://x/1")])
    sections = map_sections(conn, u, shortlist_min=7)
    assert [m["name"] for m in sections["new"]] == ["Acme"]
    assert sections["earlier"] == []


def test_after_marking_seen_the_next_run_is_new(conn):
    u = ensure_user(conn, "G")
    first = _run_with(conn, u, [_job("https://x/1")])
    mark_seen(conn, u, first)
    _run_with(conn, u, [_job("https://x/2", company="Globex")])
    sections = map_sections(conn, u, shortlist_min=7)
    assert [m["name"] for m in sections["new"]] == ["Globex"]
    assert [m["name"] for m in sections["earlier"]] == ["Acme"]


def test_acted_on_roles_leave_the_map(conn):
    u = ensure_user(conn, "G")
    _run_with(conn, u, [_job("https://x/1")])
    role_id = conn.execute("SELECT id FROM role").fetchone()["id"]
    set_role_status(conn, u, role_id, "SAVED")
    sections = map_sections(conn, u, shortlist_min=7)
    assert sections["new"] == [] and sections["earlier"] == []


def test_hidden_company_leaves_the_map(conn):
    u = ensure_user(conn, "G")
    _run_with(conn, u, [_job("https://x/1")])
    company_id = conn.execute("SELECT id FROM company").fetchone()["id"]
    set_company_state(conn, u, company_id, "HIDDEN")
    assert map_sections(conn, u, shortlist_min=7)["new"] == []


def test_watched_company_with_no_open_role_is_on_the_shelf(conn):
    u = ensure_user(conn, "G")
    _run_with(conn, u, [_job("https://x/1")])
    company_id = conn.execute("SELECT id FROM company").fetchone()["id"]
    role_id = conn.execute("SELECT id FROM role").fetchone()["id"]
    set_company_state(conn, u, company_id, "WATCH")
    set_role_status(conn, u, role_id, "APPLIED")
    sections = map_sections(conn, u, shortlist_min=7)
    assert [m["name"] for m in sections["watching"]] == ["Acme"]


def test_watched_company_with_an_open_role_is_a_card_not_a_tile(conn):
    u = ensure_user(conn, "G")
    _run_with(conn, u, [_job("https://x/1")])
    company_id = conn.execute("SELECT id FROM company").fetchone()["id"]
    set_company_state(conn, u, company_id, "WATCH")
    sections = map_sections(conn, u, shortlist_min=7)
    assert sections["watching"] == []
    assert [m["name"] for m in sections["new"]] == ["Acme"]


def test_watched_company_with_only_an_earlier_role_is_not_also_a_tile(conn):
    """The exact case the new/earlier/watching split has to get right:
    an open role that's 'earlier', not 'new', must still count as open —
    so the company must NOT also appear as a no-role watching tile."""
    u = ensure_user(conn, "G")
    first = _run_with(conn, u, [_job("https://x/1")])
    mark_seen(conn, u, first)
    company_id = conn.execute("SELECT id FROM company").fetchone()["id"]
    set_company_state(conn, u, company_id, "WATCH")
    sections = map_sections(conn, u, shortlist_min=7)
    assert [m["name"] for m in sections["earlier"]] == ["Acme"]
    assert sections["watching"] == []


def test_state_is_derived_from_the_threshold(conn):
    u = ensure_user(conn, "G")
    _run_with(conn, u, [_job("https://x/1", score=9),
                        _job("https://x/2", company="Weak Co", score=3)])
    by_name = {m["name"]: m for m in map_sections(conn, u, shortlist_min=7)["new"]}
    assert by_name["Acme"]["state"] == "ACT_NOW"
    assert by_name["Weak Co"]["state"] == "DISCOVER"


def test_map_read_model_carries_no_score(conn):
    u = ensure_user(conn, "G")
    _run_with(conn, u, [_job("https://x/1")])
    blob = json.dumps(map_sections(conn, u, shortlist_min=7), default=str)
    assert "match_score" not in blob


def test_evidence_round_trips_as_lists(conn):
    u = ensure_user(conn, "G")
    _run_with(conn, u, [_job("https://x/1")])
    role = map_sections(conn, u, shortlist_min=7)["new"][0]["roles"][0]
    assert role["matched"] == ["dbt"]
    assert role["gaps"] == ["snowflake"]
    assert role["description_captured"] is True


def test_why_notes_uncaptured_descriptions(conn):
    u = ensure_user(conn, "G")
    _run_with(conn, u, [_job("https://x/1", description_captured=False,
                             band=None, matched=[])])
    why = map_sections(conn, u, shortlist_min=7)["new"][0]["why"]
    assert "descriptions not captured yet" in why


def test_activity_board_groups_by_status(conn):
    u = ensure_user(conn, "G")
    _run_with(conn, u, [_job("https://x/1"),
                        _job("https://x/2", title="Data Engineer")])
    ids = [r["id"] for r in conn.execute("SELECT id FROM role ORDER BY id")]
    set_role_status(conn, u, ids[0], "SAVED")
    set_role_status(conn, u, ids[1], "APPLIED")
    board = activity_board(conn, u)
    assert [c["title"] for c in board["SAVED"]] == ["Analytics Engineer"]
    assert [c["title"] for c in board["APPLIED"]] == ["Data Engineer"]


def test_activity_columns_always_exist_even_when_empty(conn):
    u = ensure_user(conn, "G")
    board = activity_board(conn, u)
    assert set(board) == {"SAVED", "APPLIED", "INTERVIEWING", "OFFER", "CLOSED"}


def test_activity_cards_carry_their_event_log(conn):
    u = ensure_user(conn, "G")
    _run_with(conn, u, [_job("https://x/1")])
    role_id = conn.execute("SELECT id FROM role").fetchone()["id"]
    set_role_status(conn, u, role_id, "SAVED")
    set_role_status(conn, u, role_id, "APPLIED")
    card = activity_board(conn, u)["APPLIED"][0]
    assert [e["to_status"] for e in card["events"]] == ["SAVED", "APPLIED"]


def test_hidden_roles_are_absent_from_the_board(conn):
    u = ensure_user(conn, "G")
    _run_with(conn, u, [_job("https://x/1")])
    role_id = conn.execute("SELECT id FROM role").fetchone()["id"]
    set_role_status(conn, u, role_id, "HIDDEN")
    board = activity_board(conn, u)
    assert all(not column for column in board.values())


def test_activity_read_model_carries_no_score(conn):
    u = ensure_user(conn, "G")
    _run_with(conn, u, [_job("https://x/1")])
    role_id = conn.execute("SELECT id FROM role").fetchone()["id"]
    set_role_status(conn, u, role_id, "SAVED")
    assert "match_score" not in json.dumps(activity_board(conn, u), default=str)
