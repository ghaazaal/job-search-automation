"""Tests for src/scrapers/watched.py — resolver and both fetch rungs.

No network: `call` is injected everywhere.
"""
import pytest

from src.store.db import connect
from src.store.ingest import ensure_user
from src.store.schema import init_db
from src.store import watchlist
from src.scrapers import watched


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "w.db")
    init_db(c)
    yield c
    c.close()


@pytest.fixture
def user(conn):
    return ensure_user(conn, "default")


_CFG = {"apify": {}, "search": {}}


# --- the resolver -------------------------------------------------------

def test_a_domain_that_resolves_on_the_ats_actor_is_ats(conn, user):
    wid = watchlist.add(conn, user, name="GitLab", domain="gitlab.com")

    def call(actor, payload, label, timeout, **kw):
        assert payload["companies"] == ["gitlab.com"]
        return [{"title": "Data Engineer", "company_name": "GitLab"}]

    watched.resolve_pending(conn, user, _CFG, call=call)
    assert watchlist.get(conn, user, wid)["resolution"] == "ats"


def test_a_clean_linkedin_name_resolves_linkedin(conn, user):
    wid = watchlist.add(conn, user, name="EPAM Systems")

    def call(actor, payload, label, timeout, **kw):
        assert "companyName" in payload
        return [{"companyName": "EPAM Systems",
                 "companyUrl": "https://www.linkedin.com/company/epam-systems"}]

    watched.resolve_pending(conn, user, _CFG, call=call)
    row = watchlist.get(conn, user, wid)
    assert row["resolution"] == "linkedin"
    assert row["linkedin_name"] == "EPAM Systems"
    assert row["linkedin_slug"] == "epam-systems"


def test_an_ambiguous_name_stays_unresolved_with_a_note(conn, user):
    """Two distinct slugs behind one display name is the Andersen case."""
    wid = watchlist.add(conn, user, name="Andersen")

    def call(actor, payload, label, timeout, **kw):
        return [
            {"companyName": "Andersen",
             "companyUrl": "https://www.linkedin.com/company/andersenus"},
            {"companyName": "Andersen",
             "companyUrl": "https://www.linkedin.com/company/andersen-corp"},
        ]

    watched.resolve_pending(conn, user, _CFG, call=call)
    row = watchlist.get(conn, user, wid)
    assert row["resolution"] == "unresolved"
    assert "linkedin" in (row["resolution_note"] or "").lower()


def test_no_rows_anywhere_stays_unresolved(conn, user):
    wid = watchlist.add(conn, user, name="DataArt", domain="dataart.com")
    watched.resolve_pending(conn, user, _CFG,
                            call=lambda *a, **k: [])
    row = watchlist.get(conn, user, wid)
    assert row["resolution"] == "unresolved"
    assert row["resolution_note"]


def test_a_probe_crash_leaves_the_row_unresolved_and_does_not_raise(conn,
                                                                    user):
    watchlist.add(conn, user, name="GitLab", domain="gitlab.com")

    def call(*a, **k):
        raise RuntimeError("actor down")

    watched.resolve_pending(conn, user, _CFG, call=call)  # must not raise


# --- the fetch rungs ----------------------------------------------------

def _watch_resolved(conn, user, name, resolution, **kw):
    wid = watchlist.add(conn, user, name=name, domain=kw.pop("domain", ""))
    watchlist.set_resolution(conn, user, wid, resolution, **kw)
    return watchlist.get(conn, user, wid)


def test_ats_rung_is_one_call_for_all_companies(conn, user):
    _watch_resolved(conn, user, "GitLab", "ats", domain="gitlab.com")
    _watch_resolved(conn, user, "Supabase", "ats", domain="supabase.com")
    calls = []

    def call(actor, payload, label, timeout, **kw):
        calls.append(payload)
        return [{"title": "Data Engineer", "company_name": "GitLab",
                 "location": {"raw": "Remote"}, "job_url": "https://g/1",
                 "description_text": "dbt."}]

    jobs = watched.fetch(conn, user, "ats", _CFG, call=call)
    assert len(calls) == 1
    assert sorted(calls[0]["companies"]) == ["gitlab.com", "supabase.com"]
    assert jobs[0]["company"] == "GitLab"
    assert jobs[0]["url"] == "https://g/1"
    assert jobs[0]["platform"] == "Careers page"
    assert jobs[0]["location"] == "Remote"


def test_linkedin_rung_is_one_call_and_filters_purity(conn, user):
    """The batch returns whatever LinkedIn likes; only exact-name rows
    survive, and a stored slug must also match (the Andersen rule)."""
    _watch_resolved(conn, user, "Andersen", "linkedin",
                    linkedin_name="Andersen", linkedin_slug="andersenus")
    calls = []

    def call(actor, payload, label, timeout, **kw):
        calls.append(payload)
        return [
            {"companyName": "Andersen", "title": "Data Analyst",
             "companyUrl": "https://www.linkedin.com/company/andersenus",
             "jobUrl": "https://l/1", "description": "sql."},
            {"companyName": "Andersen", "title": "Window Installer",
             "companyUrl": "https://www.linkedin.com/company/andersen-corp",
             "jobUrl": "https://l/2", "description": "windows."},
            {"companyName": "Totally Other Co", "title": "Data Analyst",
             "companyUrl": "https://www.linkedin.com/company/other",
             "jobUrl": "https://l/3", "description": "sql."},
        ]

    jobs = watched.fetch(conn, user, "linkedin", _CFG, call=call)
    assert len(calls) == 1
    assert calls[0]["companyName"] == ["Andersen"]
    assert [j["url"] for j in jobs] == ["https://l/1"]


def test_yields_are_recorded_per_company(conn, user):
    row = _watch_resolved(conn, user, "GitLab", "ats", domain="gitlab.com")

    def call(actor, payload, label, timeout, **kw):
        return [{"title": "A", "company_name": "GitLab",
                 "job_url": "https://g/1", "description_text": "x"},
                {"title": "B", "company_name": "GitLab",
                 "job_url": "https://g/2", "description_text": "y"}]

    watched.fetch(conn, user, "ats", _CFG, call=call)
    after = watchlist.get(conn, user, row["id"])
    assert after["last_yield_count"] == 2 and after["last_fetched_at"]


def test_an_empty_rung_makes_no_call(conn, user):
    def call(*a, **k):
        raise AssertionError("no companies on this rung - must not bill")

    assert watched.fetch(conn, user, "ats", _CFG, call=call) == []


# --- the custom rung ----------------------------------------------------

def test_the_custom_rung_dispatches_by_fingerprint(conn, user, monkeypatch):
    _watch_resolved(conn, user, "DataArt", "custom")
    seen = {}

    def fake_scrape(country):
        seen["country"] = country
        return [{"cat": "watchlist", "title": "Data Analyst",
                 "company": "DataArt", "location": "Armenia",
                 "platform": "DataArt careers", "date": "2026-09-01",
                 "url": "https://www.dataart.team/vacancies/da1",
                 "salary": "", "description": "sql"}]

    from src.scrapers import dataart
    monkeypatch.setattr(dataart, "scrape", fake_scrape)
    jobs = watched.fetch(conn, user, "custom", _CFG,
                         profile={"country": "am"})
    assert seen["country"] == "Armenia"     # ISO am -> display, via pycountry
    assert [j["url"] for j in jobs] == ["https://www.dataart.team/vacancies/da1"]


def test_a_custom_row_without_an_adapter_is_skipped_not_fatal(conn, user):
    _watch_resolved(conn, user, "Mystery Co", "custom")
    assert watched.fetch(conn, user, "custom", _CFG, profile={}) == []


def test_a_credit_403_never_becomes_a_fact_about_the_company(conn, user):
    """Run 10's lesson: the account's credit ran out mid-run, every call
    403'd, and the resolver recorded "not found on LinkedIn" - a
    transport failure stored as a claim about the world. A strict raise
    leaves the row pending instead."""
    import requests

    wid = watchlist.add(conn, user, name="EPAM Systems")

    def call(actor, payload, label, timeout, **kw):
        if kw.get("strict"):
            raise requests.exceptions.HTTPError("403 Forbidden")
        return []

    watched.resolve_pending(conn, user, _CFG, call=call)
    row = watchlist.get(conn, user, wid)
    assert row["resolution"] == "unresolved"
    assert row["resolution_note"] == "pending next run"   # unchanged
