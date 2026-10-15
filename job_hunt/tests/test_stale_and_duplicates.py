"""Out-of-date postings and second copies of one posting.

Measured on the live store 2026-10-15: 0 of 2,191 roles had ever been
marked seen by a later search, so the map carried postings last seen in
August; and TELUS Digital's "Online Data Analyst" sat on it four times,
once per language.
"""
from datetime import date, timedelta

import pytest

from src.map_page import render as render_map
from src.store.db import connect
from src.store.ingest import ensure_user, mark_reseen, upsert_jobs
from src.store.queries import (eligibility_counts, map_sections,
                               open_company_count)
from src.store.runs import finish_run, start_run
from src.store.schema import init_db
from src.store.tracking import set_role_status
from src.tracker.dedup import dedupe, fingerprint, title_key


def _days_ago(n: int) -> str:
    return (date.today() - timedelta(days=n)).isoformat()


def _job(url, company="Acme", title="Analytics Engineer", score=9, **kw):
    base = {"company": company, "title": title, "url": url,
            "location": "Remote", "salary": "", "platform": "Himalayas",
            "date": _days_ago(2), "description": "dbt", "match_score": score,
            "description_captured": True, "band": "STRONG FIT",
            "reason": "matches dbt", "matched": ["dbt"], "gaps": [],
            "location_scope": "open"}
    return {**base, **kw}


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "test.db")
    init_db(c)
    return c


def _run_with(conn, user_id, jobs, started=None):
    run_id = start_run(conn, user_id)
    if started:
        conn.execute("UPDATE run SET started_at = ? WHERE id = ?",
                     (started, run_id))
    upsert_jobs(conn, user_id, run_id, jobs)
    finish_run(conn, run_id, scraped=len(jobs), kept=len(jobs))
    return run_id


def _titles(sections):
    return sorted(r["title"] for m in sections["new"] + sections["earlier"]
                  for r in m["roles"])


# --- title_key: what one copy of a job differs from the next by ----------

@pytest.mark.parametrize("a,b", [
    ("Online Data Analyst - Bengali (IN)", "Online Data Analyst - English (AU)"),
    ("Online Data Analyst - Czech (CZ)", "Online Data Analyst - German Language"),
    ("Data Analyst (Python) - Remote Work | REF#302087",
     "Data Analyst (Python) - Remote Work | REF#299522"),
    ("Data Analyst III", "Data Analyst III (remote)"),
    ("Senior Data Analyst, GTM Analytics - CANADA",
     "Senior Data Analyst, GTM Analytics - US"),
    ("Sr. Power BI Developer", "Senior Power BI Developer"),
    ("Engineer III - Platform Data Engineer",
     "Engineer III - Platform Data Engineer (Remote)"),
])
def test_copies_of_one_job_share_a_key(a, b):
    assert title_key(a) == title_key(b)


@pytest.mark.parametrize("a,b", [
    ("Senior Data Engineer (Python)", "Senior Data Engineer (Azure)"),
    ("Engineer III - Platform Data Engineer",
     "Engineer III - FinOps Data Analytics"),
    ("Data Analyst", "Data Engineer"),
    ("AWS Data Engineer (Senior)", "AWS Data Engineer (Associate)"),
])
def test_different_jobs_keep_different_keys(a, b):
    assert title_key(a) != title_key(b)


def test_a_title_that_is_all_noise_keeps_its_words():
    assert title_key("Remote") == "remote"


def test_dedupe_collapses_per_country_copies_in_one_scrape():
    jobs = [_job(f"https://b/{n}", company="BairesDev",
                 title=f"BI Developer - Remote Work | REF#30{n}")
            for n in range(3)]
    assert len(dedupe(jobs)) == 1


def test_company_fingerprint_is_unchanged():
    """Company rows and the watchlist key on fingerprint(title="")."""
    assert fingerprint({"company": "Acme, Inc.", "title": ""}) == "acme|"


# --- mark_reseen: a search finding a stored posting again ----------------

def test_a_posting_found_again_by_url_is_marked_seen(conn):
    u = ensure_user(conn, "G")
    first = _run_with(conn, u, [_job("https://x/1")])
    second = start_run(conn, u)
    # Tracking parameters and a trailing slash do not make a new posting.
    assert mark_reseen(conn, u, second,
                       [_job("https://www.x/1/?utm_source=a",
                             title="Something Else")]) == 1
    # Already stamped for this run: nothing left to do.
    assert mark_reseen(conn, u, second, [_job("https://x/1")]) == 0
    row = conn.execute("SELECT first_seen_run_id, last_seen_run_id FROM role").fetchone()
    assert (row["first_seen_run_id"], row["last_seen_run_id"]) == (first, second)


def test_a_repost_under_a_new_url_is_marked_seen(conn):
    u = ensure_user(conn, "G")
    _run_with(conn, u, [_job("https://x/1", title="Data Analyst III")])
    second = start_run(conn, u)
    assert mark_reseen(conn, u, second,
                       [_job("https://y/9", title="Data Analyst III (remote)")]) == 1


def test_an_unrelated_scrape_marks_nothing(conn):
    u = ensure_user(conn, "G")
    first = _run_with(conn, u, [_job("https://x/1")])
    second = start_run(conn, u)
    assert mark_reseen(conn, u, second,
                       [_job("https://x/2", company="Globex")]) == 0
    assert conn.execute("SELECT last_seen_run_id FROM role").fetchone()[0] == first


# --- the map: out of date -------------------------------------------------

def test_an_old_posting_nobody_has_seen_since_leaves_the_map(conn):
    u = ensure_user(conn, "G")
    _run_with(conn, u, [_job("https://x/old", title="Old Role",
                             date=_days_ago(60))],
              started=_days_ago(60) + "T10:00:00+00:00")
    _run_with(conn, u, [_job("https://x/new", title="New Role")])
    assert _titles(map_sections(conn, u, max_age_days=30)) == ["New Role"]
    # Off by default: the rule is the caller's choice.
    assert _titles(map_sections(conn, u)) == ["New Role", "Old Role"]


def test_an_old_posting_a_recent_search_found_again_stays(conn):
    u = ensure_user(conn, "G")
    _run_with(conn, u, [_job("https://x/old", title="Old Role",
                             date=_days_ago(60))],
              started=_days_ago(60) + "T10:00:00+00:00")
    recent = _run_with(conn, u, [])
    mark_reseen(conn, u, recent, [_job("https://x/old")])
    assert _titles(map_sections(conn, u, max_age_days=30)) == ["Old Role"]


def test_an_old_posting_the_user_saved_stays(conn):
    u = ensure_user(conn, "G")
    _run_with(conn, u, [_job("https://x/old", title="Old Role",
                             date=_days_ago(60))],
              started=_days_ago(60) + "T10:00:00+00:00")
    set_role_status(conn, u, conn.execute("SELECT id FROM role").fetchone()[0],
                    "SAVED")
    assert _titles(map_sections(conn, u, max_age_days=30)) == ["Old Role"]


def test_counts_name_the_out_of_date_roles(conn):
    u = ensure_user(conn, "G")
    old = _days_ago(60)
    _run_with(conn, u, [_job("https://x/1", date=old, title="A"),
                        _job("https://x/2", date=old, title="B",
                             location_scope="closed")],
              started=old + "T10:00:00+00:00")
    _run_with(conn, u, [_job("https://x/3", company="Globex")])
    counts = eligibility_counts(conn, u, 30)
    # The not-open posting counts as not open, not as out of date.
    assert counts == {"open": 1, "closed": 1, "unverified": 0, "stale": 1}
    assert open_company_count(conn, u, 30) == 1
    assert open_company_count(conn, u) == 2


# --- the map: second copies ------------------------------------------------

def test_one_card_row_per_posting(conn):
    u = ensure_user(conn, "G")
    _run_with(conn, u, [
        _job("https://t/bn", company="TELUS Digital",
             title="Online Data Analyst - Bengali (IN)", score=5),
        _job("https://t/au", company="TELUS Digital",
             title="Online Data Analyst - English (AU)", score=8),
        _job("https://t/cz", company="TELUS Digital",
             title="Online Data Analyst - Czech (CZ)", score=5),
    ])
    sections = map_sections(conn, u)
    assert _titles(sections) == ["Online Data Analyst - English (AU)"]
    assert sections["duplicates"] == 2


def test_the_same_title_at_two_companies_is_not_a_copy(conn):
    u = ensure_user(conn, "G")
    _run_with(conn, u, [_job("https://x/1", title="Data Analyst"),
                        _job("https://y/1", title="Data Analyst",
                             company="Globex")])
    sections = map_sections(conn, u)
    assert len(_titles(sections)) == 2
    assert sections["duplicates"] == 0


def test_the_header_says_what_was_hidden():
    html = render_map([], meta={"stale": 23, "max_age_days": 30,
                                "duplicates": 3})
    assert "23 HIDDEN (NOT SEEN IN 30 DAYS)" in html
    assert "3 HIDDEN (DUPLICATE COPY)" in html
