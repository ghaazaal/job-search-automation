"""Tests for src/scrapers/* — Apify item mapping.

The network call is monkeypatched out; these cover the raw-item -> job-dict
mapping only, which is where the description was being dropped.
"""
import pytest

from src.scrapers import indeed, linkedin


def _patch(monkeypatch, module, items):
    monkeypatch.setattr(module, "call_actor", lambda *a, **k: items)


def _scrape(module, monkeypatch, item):
    _patch(monkeypatch, module, [item])
    return module.scrape("Data Analyst", "Data Analyst", "actor~id")[0]


_MINIMAL = {"jobUrl": "https://example.com/j1", "title": "Data Analyst",
            "company": "Acme", "location": "Remote"}


@pytest.mark.parametrize("module", [indeed, linkedin])
def test_description_is_captured(module, monkeypatch):
    job = _scrape(module, monkeypatch,
                  {**_MINIMAL, "description": "We run dbt and Airflow."})
    assert job["description"] == "We run dbt and Airflow."


@pytest.mark.parametrize("module", [indeed, linkedin])
@pytest.mark.parametrize("key", ["descriptionText", "jobDescription",
                                 "descriptionHtml"])
def test_description_alternate_keys(module, key, monkeypatch):
    """Apify actors disagree on the field name — accept the common variants."""
    job = _scrape(module, monkeypatch, {**_MINIMAL, key: "Airflow required."})
    assert job["description"] == "Airflow required."


@pytest.mark.parametrize("module", [indeed, linkedin])
def test_html_description_is_flattened(module, monkeypatch):
    """HTML bodies must become plain text so keyword matching works."""
    html = "<p>We use <strong>dbt</strong> and Airflow.</p><ul><li>SQL</li></ul>"
    job = _scrape(module, monkeypatch, {**_MINIMAL, "description": html})
    assert "<" not in job["description"]
    assert "dbt" in job["description"]
    assert "SQL" in job["description"]


@pytest.mark.parametrize("module", [indeed, linkedin])
def test_missing_description_is_empty_string(module, monkeypatch):
    """No description available must not crash or yield None."""
    job = _scrape(module, monkeypatch, _MINIMAL)
    assert job["description"] == ""


def _capture(monkeypatch, module, items):
    """Record the payload each call_actor invocation received."""
    seen = []

    def _fake(actor_id, payload, label, timeout=120):
        seen.append(payload)
        return items.pop(0) if items else []

    monkeypatch.setattr(module, "call_actor", _fake)
    return seen


# ── Indeed ────────────────────────────────────────────────────────────────────

def test_indeed_uses_the_literal_remote_location_for_a_remote_search(monkeypatch):
    seen = _capture(monkeypatch, indeed, [[_MINIMAL]])
    indeed.scrape("BI Developer", "BI Developer", "actor~id",
                  location="Toronto, ON", country="ca", work_modes=["remote"])
    assert seen[0]["location"] == "remote"
    assert seen[0]["country"] == "ca"


def test_indeed_searches_the_place_when_onsite_is_wanted(monkeypatch):
    seen = _capture(monkeypatch, indeed, [[_MINIMAL]])
    indeed.scrape("BI Developer", "BI Developer", "actor~id",
                  location="Toronto, ON", country="ca",
                  work_modes=["remote", "onsite"])
    assert seen[0]["location"] == "Toronto, ON"


def test_indeed_falls_back_when_the_actor_returns_nothing(monkeypatch):
    """An actor that rejects the new input yields an empty list, which is
    indistinguishable from no results — so retry with what used to work."""
    seen = _capture(monkeypatch, indeed, [[], [_MINIMAL]])
    jobs = indeed.scrape("BI Developer", "BI Developer", "actor~id",
                         location="Toronto, ON", country="ca",
                         work_modes=["onsite"])
    assert len(seen) == 2
    assert seen[1] == {**seen[0], "location": "remote", "country": "us"}
    assert len(jobs) == 1


def test_indeed_returns_nothing_gracefully_when_the_retry_also_fails(monkeypatch):
    seen = _capture(monkeypatch, indeed, [[], []])
    jobs = indeed.scrape("BI Developer", "BI Developer", "actor~id",
                         location="Toronto, ON", country="ca",
                         work_modes=["onsite"])
    assert jobs == []
    assert len(seen) == 2


def test_indeed_does_not_retry_when_it_already_used_the_legacy_values(monkeypatch):
    seen = _capture(monkeypatch, indeed, [[]])
    indeed.scrape("BI Developer", "BI Developer", "actor~id",
                  location="remote", country="us", work_modes=["remote"])
    assert len(seen) == 1


def test_indeed_tags_fallback_results_with_the_board_they_came_from(monkeypatch):
    """When the actor rejects the user's country and the retry lands on the
    us board, every job must say so — the scorer turns the tag into a
    reduced-confidence flag."""
    _capture(monkeypatch, indeed, [[], [_MINIMAL]])
    jobs = indeed.scrape("BI Developer", "BI Developer", "actor~id",
                         location="Yerevan, Armenia", country="am",
                         work_modes=["remote"])
    assert jobs[0]["_scraped_under"] == "us"


def test_indeed_does_not_tag_when_the_country_already_matched(monkeypatch):
    """A retry that only changed the location searched the same country —
    nothing to warn about."""
    _capture(monkeypatch, indeed, [[], [_MINIMAL]])
    jobs = indeed.scrape("BI Developer", "BI Developer", "actor~id",
                         location="Austin, TX", country="us",
                         work_modes=["onsite"])
    assert "_scraped_under" not in jobs[0]


def test_indeed_does_not_tag_without_a_fallback(monkeypatch):
    _capture(monkeypatch, indeed, [[_MINIMAL]])
    jobs = indeed.scrape("BI Developer", "BI Developer", "actor~id",
                         location="Yerevan, Armenia", country="am",
                         work_modes=["remote"])
    assert "_scraped_under" not in jobs[0]


# ── LinkedIn ──────────────────────────────────────────────────────────────────

def test_linkedin_maps_work_modes_to_remote_codes(monkeypatch):
    seen = _capture(monkeypatch, linkedin, [[_MINIMAL]])
    linkedin.scrape("BI Developer", "BI Developer", "actor~id",
                    location="Toronto, ON", country="ca",
                    work_modes=["hybrid", "onsite"])
    assert set(seen[0]["remote"]) == {"3", "1"}
    assert seen[0]["location"] == "Toronto, ON"


def test_linkedin_searches_worldwide_for_a_remote_only_search(monkeypatch):
    seen = _capture(monkeypatch, linkedin, [[_MINIMAL]])
    linkedin.scrape("BI Developer", "BI Developer", "actor~id",
                    location="Toronto, ON", country="ca", work_modes=["remote"])
    assert seen[0]["location"] == "Worldwide"
    assert seen[0]["remote"] == ["2"]


def test_linkedin_ignores_an_unknown_work_mode(monkeypatch):
    seen = _capture(monkeypatch, linkedin, [[_MINIMAL]])
    linkedin.scrape("BI Developer", "BI Developer", "actor~id",
                    location="Toronto, ON", country="ca",
                    work_modes=["telepathic"])
    assert seen[0]["remote"] == ["2"]


def test_linkedin_falls_back_when_the_actor_returns_nothing(monkeypatch):
    seen = _capture(monkeypatch, linkedin, [[], [_MINIMAL]])
    jobs = linkedin.scrape("BI Developer", "BI Developer", "actor~id",
                           location="Toronto, ON", country="ca",
                           work_modes=["onsite"])
    assert len(seen) == 2
    assert seen[1]["location"] == "Worldwide"
    assert seen[1]["remote"] == ["2"]
    assert len(jobs) == 1


def test_linkedin_returns_nothing_gracefully_when_the_retry_also_fails(monkeypatch):
    seen = _capture(monkeypatch, linkedin, [[], []])
    jobs = linkedin.scrape("BI Developer", "BI Developer", "actor~id",
                           location="Toronto, ON", country="ca",
                           work_modes=["onsite"])
    assert jobs == []
    assert len(seen) == 2


def test_the_defaults_reproduce_the_old_behaviour(monkeypatch):
    """Callers that have not been updated yet must not change what they get."""
    indeed_seen = _capture(monkeypatch, indeed, [[_MINIMAL]])
    indeed.scrape("BI Developer", "BI Developer", "actor~id")
    assert indeed_seen[0]["location"] == "remote"
    assert indeed_seen[0]["country"] == "us"

    linkedin_seen = _capture(monkeypatch, linkedin, [[_MINIMAL]])
    linkedin.scrape("BI Developer", "BI Developer", "actor~id")
    assert linkedin_seen[0]["location"] == "Worldwide"
    assert linkedin_seen[0]["remote"] == ["2"]


@pytest.mark.parametrize("module", [indeed, linkedin])
def test_an_actor_overshoot_is_truncated_to_the_cap(module, monkeypatch):
    """The Indeed actor returns ~100 when asked for 50. The cap is
    enforced at the client boundary regardless of actor behavior."""
    items = [{**_MINIMAL, "jobUrl": f"https://example.com/j{i}"}
             for i in range(100)]
    _patch(monkeypatch, module, items)
    jobs = module.scrape("Data Analyst", "Data Analyst", "actor~id",
                         jobs_per_category=50)
    assert len(jobs) == 50
