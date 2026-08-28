"""Tests for src/scrapers/* — Apify item mapping.

The network call is monkeypatched out; these cover the raw-item -> job-dict
mapping only, which is where the description was being dropped.

Indeed was removed in Ship 8 — it is organised one site per country, which
is the wrong shape for a user in a country it does not serve — so every
test here belongs to LinkedIn or the remote boards.
"""
import pytest

from src.scrapers import linkedin


def _patch(monkeypatch, module, items):
    monkeypatch.setattr(module, "call_actor", lambda *a, **k: items)


def _scrape(module, monkeypatch, item):
    _patch(monkeypatch, module, [item])
    return module.scrape("Data Analyst", "Data Analyst", "actor~id")[0]


_MINIMAL = {"jobUrl": "https://example.com/j1", "title": "Data Analyst",
            "company": "Acme", "location": "Remote"}

# kaix's nested item shape, minimal enough to satisfy the new Indeed
# scraper's `_get(item, "urls.indeed")` etc. lookups.
_KAIX_MINIMAL = {
    "title": {"text": "Data Analyst"},
    "company": {"name": "Acme"},
    "location": {"formatted": "Nashville, TN"},
    "urls": {"indeed": "https://indeed.com/viewjob?jk=abc"},
}


def test_linkedin_description_is_captured(monkeypatch):
    job = _scrape(linkedin, monkeypatch,
                  {**_MINIMAL, "description": "We run dbt and Airflow."})
    assert job["description"] == "We run dbt and Airflow."


@pytest.mark.parametrize("key", ["descriptionText", "jobDescription",
                                 "descriptionHtml"])
def test_linkedin_description_alternate_keys(key, monkeypatch):
    """Apify actors disagree on the field name — accept the common variants."""
    job = _scrape(linkedin, monkeypatch, {**_MINIMAL, key: "Airflow required."})
    assert job["description"] == "Airflow required."


def test_linkedin_html_description_is_flattened(monkeypatch):
    """HTML bodies must become plain text so keyword matching works."""
    html = "<p>We use <strong>dbt</strong> and Airflow.</p><ul><li>SQL</li></ul>"
    job = _scrape(linkedin, monkeypatch, {**_MINIMAL, "description": html})
    assert "<" not in job["description"]
    assert "dbt" in job["description"]
    assert "SQL" in job["description"]


def test_linkedin_missing_description_is_empty_string(monkeypatch):
    """No description available must not crash or yield None."""
    job = _scrape(linkedin, monkeypatch, _MINIMAL)
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
#
# kaix's `remote` filter param replaces the old trick of putting "remote"
# in the location box (see test_indeed_never_puts_remote_in_the_location_box
# below for the regression that motivated the swap). The retry/fallback and
# `_scraped_under` reduced-confidence tagging behaviour is unchanged from
# valig — only the legacy sentinel values and payload key names moved.

def test_linkedin_uses_the_given_location_regardless_of_work_modes(monkeypatch):
    """valig has no `remote` parameter, so work_modes never reaches the
    payload — only location does."""
    seen = _capture(monkeypatch, linkedin, [[_MINIMAL]])
    linkedin.scrape("BI Developer", "BI Developer", "actor~id",
                    location="Toronto, ON", country="ca",
                    work_modes=["hybrid", "onsite"])
    assert seen[0]["location"] == "Toronto, ON"
    assert "remote" not in seen[0]


def test_linkedin_defaults_to_worldwide_when_location_is_empty(monkeypatch):
    seen = _capture(monkeypatch, linkedin, [[_MINIMAL]])
    linkedin.scrape("BI Developer", "BI Developer", "actor~id",
                    location="", country="ca", work_modes=["remote"])
    assert seen[0]["location"] == "Worldwide"


def test_linkedin_falls_back_when_the_actor_returns_nothing(monkeypatch):
    seen = _capture(monkeypatch, linkedin, [[], [_MINIMAL]])
    jobs = linkedin.scrape("BI Developer", "BI Developer", "actor~id",
                           location="Toronto, ON", country="ca",
                           work_modes=["onsite"])
    assert len(seen) == 2
    assert seen[1]["location"] == "Worldwide"
    assert len(jobs) == 1


def test_linkedin_returns_nothing_gracefully_when_the_retry_also_fails(monkeypatch):
    seen = _capture(monkeypatch, linkedin, [[], []])
    jobs = linkedin.scrape("BI Developer", "BI Developer", "actor~id",
                           location="Toronto, ON", country="ca",
                           work_modes=["onsite"])
    assert jobs == []
    assert len(seen) == 2


def test_linkedin_stays_silent_when_fallback_is_disallowed(monkeypatch):
    """The local lane asks a narrow, deliberate question. An empty first
    answer must stay empty rather than silently retrying with the legacy
    Worldwide payload."""
    seen = _capture(monkeypatch, linkedin, [[]])
    jobs = linkedin.scrape("BI Developer", "BI Developer", "actor~id",
                           location="Yerevan, Armenia", country="am",
                           work_modes=["hybrid"], allow_fallback=False)
    assert len(seen) == 1
    assert jobs == []


def test_linkedin_still_falls_back_by_default(monkeypatch):
    """Pinning existing behaviour: worldwide lanes keep the retry."""
    seen = _capture(monkeypatch, linkedin, [[], [_MINIMAL]])
    jobs = linkedin.scrape("BI Developer", "BI Developer", "actor~id",
                           location="Toronto, ON", country="ca",
                           work_modes=["onsite"])
    assert len(seen) == 2
    assert len(jobs) == 1


def test_linkedin_warns_when_rows_come_back_but_none_parse(monkeypatch, caplog):
    """A shape mismatch (none of jobUrl/applyUrl/url/link present) must
    not look like an empty job market — see the equivalent Indeed test
    for why this guard exists. Location is pinned so the fallback retry
    (also empty) doesn't add a second, distracting warning."""
    wrong_shaped_item = {"title": "Data Analyst", "company": "Acme",
                          "location": "Remote"}  # no url-ish key at all
    monkeypatch.setattr(linkedin, "call_actor",
                        lambda *a, **k: [wrong_shaped_item])
    with caplog.at_level("WARNING", logger="src.scrapers.linkedin"):
        jobs = linkedin.scrape("Data Analyst", "Data Analyst",
                               "wrong~actor~id", location="Worldwide")
    assert jobs == []
    assert any("none could be parsed" in r.message for r in caplog.records)


def test_the_defaults_reproduce_the_old_behaviour(monkeypatch):
    """Callers that have not been updated yet must not change what they get."""
    seen = _capture(monkeypatch, linkedin, [[_MINIMAL]])
    linkedin.scrape("BI Developer", "BI Developer", "actor~id")
    assert seen[0]["location"] == "Worldwide"

    linkedin_seen = _capture(monkeypatch, linkedin, [[_MINIMAL]])
    linkedin.scrape("BI Developer", "BI Developer", "actor~id")
    assert linkedin_seen[0]["location"] == "Worldwide"


def test_linkedin_overshoot_is_truncated_to_the_cap(monkeypatch):
    """The cap is enforced at the client boundary regardless of actor
    behavior. See test_indeed_overshoot_is_truncated_to_the_cap for
    Indeed's kaix-shaped equivalent."""
    items = [{**_MINIMAL, "jobUrl": f"https://example.com/j{i}"}
             for i in range(100)]
    _patch(monkeypatch, linkedin, items)
    jobs = linkedin.scrape("Data Analyst", "Data Analyst", "actor~id",
                          jobs_per_category=50)
    assert len(jobs) == 50


def test_linkedin_prefers_html_over_a_prefused_plain_field(monkeypatch):
    """valig's plain `description` arrives pre-flattened with NO
    separators ("…RemoteTravel Required…"), defeating word-boundary
    matching. The html sibling has real structure, and tag-flattening
    inserts a space per tag — so html wins whenever both exist. See
    test_indeed_prefers_html_over_pre_flattened_text for Indeed's
    kaix-shaped equivalent."""
    item = {**_MINIMAL,
            "description": "Location: RemoteTravel Required: 2-5 Weeks",
            "descriptionHtml": "<p>Location: Remote</p>"
                               "<p>Travel Required: 2-5 Weeks</p>"}
    job = _scrape(linkedin, monkeypatch, item)
    assert "RemoteTravel" not in job["description"]
    assert "Location: Remote" in job["description"]
