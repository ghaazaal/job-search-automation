"""Tests for src/scrapers/* — Apify item mapping.

The network call is monkeypatched out; these cover the raw-item -> job-dict
mapping only, which is where the description was being dropped.

Indeed moved from valig's flat item shape to kaix's deeply-nested one (see
`test_indeed_maps_the_kaix_field_shape` below), so the generic
description-mapping tests below are LinkedIn-only now — a flat `_MINIMAL`
item has no `urls.*` path for the new Indeed scraper to find at all, and
its own field mapping is covered by the dedicated Indeed tests further
down instead.
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

# kaix's nested item shape, minimal enough to satisfy the new Indeed
# scraper's `_get(item, "urls.indeed")` etc. lookups.
_KAIX_MINIMAL = {
    "title": {"text": "Data Analyst"},
    "company": {"name": "Acme"},
    "location": {"formatted": "Nashville, TN"},
    "urls": {"indeed": "https://indeed.com/viewjob?jk=abc"},
}


@pytest.mark.parametrize("module", [linkedin])
def test_description_is_captured(module, monkeypatch):
    job = _scrape(module, monkeypatch,
                  {**_MINIMAL, "description": "We run dbt and Airflow."})
    assert job["description"] == "We run dbt and Airflow."


@pytest.mark.parametrize("module", [linkedin])
@pytest.mark.parametrize("key", ["descriptionText", "jobDescription",
                                 "descriptionHtml"])
def test_description_alternate_keys(module, key, monkeypatch):
    """Apify actors disagree on the field name — accept the common variants."""
    job = _scrape(module, monkeypatch, {**_MINIMAL, key: "Airflow required."})
    assert job["description"] == "Airflow required."


@pytest.mark.parametrize("module", [linkedin])
def test_html_description_is_flattened(module, monkeypatch):
    """HTML bodies must become plain text so keyword matching works."""
    html = "<p>We use <strong>dbt</strong> and Airflow.</p><ul><li>SQL</li></ul>"
    job = _scrape(module, monkeypatch, {**_MINIMAL, "description": html})
    assert "<" not in job["description"]
    assert "dbt" in job["description"]
    assert "SQL" in job["description"]


@pytest.mark.parametrize("module", [linkedin])
def test_missing_description_is_empty_string(module, monkeypatch):
    """No description available must not crash or yield None."""
    job = _scrape(module, monkeypatch, _MINIMAL)
    assert job["description"] == ""


def test_indeed_missing_description_is_empty_string(monkeypatch):
    """Same guarantee as above, under kaix's nested shape."""
    job = _scrape(indeed, monkeypatch, _KAIX_MINIMAL)
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

def test_indeed_never_puts_remote_in_the_location_box(monkeypatch):
    """Indeed echoes the location box back as the job's location."""
    sent = {}

    def fake_call(actor_id, payload, label, timeout):
        sent.update(payload)
        return []

    monkeypatch.setattr(indeed, "call_actor", fake_call)
    indeed.scrape("Data Analyst", "Data Analyst", "kaix~indeed-scraper",
                  location="Yerevan, Armenia", country="am",
                  work_modes=("remote",))
    assert sent["location"].lower() != "remote"
    assert sent["remote"] == "remote"
    assert sent["keyword"] == 'title:"Data Analyst"'


def test_indeed_uses_one_title_per_search():
    """Combining titles with `or` collapses precision from 15/15 to 11/20."""
    assert indeed._keyword("Data Analyst") == 'title:"Data Analyst"'


def test_indeed_local_lane_modes_yield_no_remote_filter(monkeypatch):
    """The local lane asks for ("remote", "hybrid", "onsite") together —
    two filterable values at once must mean no filter, not an arbitrary
    pick, or on-site/hybrid work in the user's own city would vanish."""
    seen = _capture(monkeypatch, indeed, [[_KAIX_MINIMAL]])
    indeed.scrape("BI Developer", "BI Developer", "actor~id",
                 location="Toronto, ON", country="ca",
                 work_modes=("remote", "hybrid", "onsite"))
    assert "remote" not in seen[0]
    assert "fromDays" in seen[0]


def test_indeed_maps_the_kaix_field_shape(monkeypatch):
    item = {
        "title": {"text": "Data Analyst"},
        "company": {"name": "Acme"},
        "location": {"formatted": "Nashville, TN", "country": "US"},
        "workArrangement": {"locationType": "Remote"},
        "salary": {"text": "$65 - $75 an hour"},
        "dates": {"posted": "2026-08-25"},
        "urls": {"indeed": "https://indeed.com/viewjob?jk=abc"},
        "description": {"html": "<p>SQL and Python</p>"},
        "signals": {"isExpired": False},
    }
    monkeypatch.setattr(indeed, "call_actor",
                        lambda *a, **k: [item])
    jobs = indeed.scrape("Data Analyst", "Data Analyst", "kaix~indeed-scraper")
    assert len(jobs) == 1
    job = jobs[0]
    assert job["title"] == "Data Analyst"
    assert job["company"] == "Acme"
    assert job["location"] == "Nashville, TN"
    assert job["work_mode"] == "remote"
    assert job["salary"] == "$65 - $75 an hour"
    assert job["country"] == "us"
    assert "SQL and Python" in job["description"]


def test_indeed_drops_expired_postings(monkeypatch):
    item = {
        "title": {"text": "Data Analyst"},
        "company": {"name": "Acme"},
        "location": {"formatted": "Nashville, TN"},
        "urls": {"indeed": "https://indeed.com/viewjob?jk=abc"},
        "description": {"text": "SQL"},
        "signals": {"isExpired": True},
    }
    monkeypatch.setattr(indeed, "call_actor", lambda *a, **k: [item])
    assert indeed.scrape("Data Analyst", "Data Analyst", "x") == []


def test_indeed_warns_when_rows_come_back_but_none_parse(monkeypatch, caplog):
    """A shape mismatch (e.g. the config still points at the retired
    valig actor) must not look like an empty job market: the actor
    returning rows that all fail to parse is a different, louder fact.
    valig's flat item shape has no `urls.*` path for kaix's `_get` to
    find, so every row is silently skipped without this guard."""
    valig_shaped_item = {
        "jobUrl": "https://example.com/j1", "title": "Data Analyst",
        "company": "Acme", "location": "Remote",
    }
    monkeypatch.setattr(indeed, "call_actor",
                        lambda *a, **k: [valig_shaped_item])
    with caplog.at_level("WARNING", logger="src.scrapers.indeed"):
        jobs = indeed.scrape("Data Analyst", "Data Analyst",
                            "valig~indeed-jobs-scraper")
    assert jobs == []
    assert any("none could be parsed" in r.message for r in caplog.records)


def test_indeed_prefers_html_over_pre_flattened_text(monkeypatch):
    """The plain text sibling arrives pre-flattened with no separators
    ("run togetherText here"), which defeats word-boundary phrase
    matching — html must win whenever both exist."""
    item = {**_KAIX_MINIMAL,
            "description": {"text": "runtogetherText here",
                            "html": "<p>run</p><p>together</p><p>Text here</p>"}}
    job = _scrape(indeed, monkeypatch, item)
    assert "runtogetherText" not in job["description"]
    assert "run together Text here" == job["description"]


def test_indeed_overshoot_is_truncated_to_the_cap(monkeypatch):
    """The actor returns ~100 when asked for 50. The cap is enforced at
    the client boundary regardless of actor behavior."""
    items = [{**_KAIX_MINIMAL,
             "urls": {"indeed": f"https://indeed.com/viewjob?jk={i}"}}
            for i in range(100)]
    monkeypatch.setattr(indeed, "call_actor", lambda *a, **k: items)
    jobs = indeed.scrape("Data Analyst", "Data Analyst", "actor~id",
                        jobs_per_category=50)
    assert len(jobs) == 50


def test_indeed_falls_back_when_the_actor_returns_nothing(monkeypatch):
    """An actor that rejects the new input yields an empty list, which is
    indistinguishable from no results — so retry with what used to work."""
    seen = _capture(monkeypatch, indeed, [[], [_KAIX_MINIMAL]])
    jobs = indeed.scrape("BI Developer", "BI Developer", "actor~id",
                         location="Toronto, ON", country="ca",
                         work_modes=["onsite"])
    assert len(seen) == 2
    assert seen[1] == {**seen[0], "location": "United States", "country": "US"}
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
                  location="United States", country="us",
                  work_modes=["remote"])
    assert len(seen) == 1


def test_indeed_tags_fallback_results_with_the_board_they_came_from(monkeypatch):
    """When the actor rejects the user's country and the retry lands on the
    us board, every job must say so — the scorer turns the tag into a
    reduced-confidence flag."""
    _capture(monkeypatch, indeed, [[], [_KAIX_MINIMAL]])
    jobs = indeed.scrape("BI Developer", "BI Developer", "actor~id",
                         location="Yerevan, Armenia", country="am",
                         work_modes=["remote"])
    assert jobs[0]["_scraped_under"] == "us"


def test_indeed_does_not_tag_when_the_country_already_matched(monkeypatch):
    """A retry that only changed the location searched the same country —
    nothing to warn about."""
    _capture(monkeypatch, indeed, [[], [_KAIX_MINIMAL]])
    jobs = indeed.scrape("BI Developer", "BI Developer", "actor~id",
                         location="Austin, TX", country="us",
                         work_modes=["onsite"])
    assert "_scraped_under" not in jobs[0]


def test_indeed_does_not_tag_without_a_fallback(monkeypatch):
    _capture(monkeypatch, indeed, [[_KAIX_MINIMAL]])
    jobs = indeed.scrape("BI Developer", "BI Developer", "actor~id",
                         location="Yerevan, Armenia", country="am",
                         work_modes=["remote"])
    assert "_scraped_under" not in jobs[0]


def test_indeed_stays_silent_when_fallback_is_disallowed(monkeypatch):
    """The local lane asked a narrow question. An empty first answer must
    stay empty — falling back to remote/us answers a different question."""
    seen = _capture(monkeypatch, indeed, [[]])
    jobs = indeed.scrape("BI Developer", "BI Developer", "actor~id",
                         location="Yerevan, Armenia", country="am",
                         work_modes=["onsite"], allow_fallback=False)
    assert len(seen) == 1
    assert jobs == []


def test_indeed_still_falls_back_by_default(monkeypatch):
    """Pinning existing behaviour: worldwide lanes keep the retry."""
    seen = _capture(monkeypatch, indeed, [[], [_KAIX_MINIMAL]])
    jobs = indeed.scrape("BI Developer", "BI Developer", "actor~id",
                         location="Yerevan, Armenia", country="am",
                         work_modes=["onsite"])
    assert len(seen) == 2
    assert len(jobs) == 1


# ── LinkedIn ──────────────────────────────────────────────────────────────────

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


def test_the_defaults_reproduce_the_old_behaviour(monkeypatch):
    """Callers that have not been updated yet must not change what they get."""
    indeed_seen = _capture(monkeypatch, indeed, [[_KAIX_MINIMAL]])
    indeed.scrape("BI Developer", "BI Developer", "actor~id")
    assert indeed_seen[0]["location"] == "United States"
    assert indeed_seen[0]["country"] == "US"

    linkedin_seen = _capture(monkeypatch, linkedin, [[_MINIMAL]])
    linkedin.scrape("BI Developer", "BI Developer", "actor~id")
    assert linkedin_seen[0]["location"] == "Worldwide"


@pytest.mark.parametrize("module", [linkedin])
def test_an_actor_overshoot_is_truncated_to_the_cap(module, monkeypatch):
    """The cap is enforced at the client boundary regardless of actor
    behavior. See test_indeed_overshoot_is_truncated_to_the_cap for
    Indeed's kaix-shaped equivalent."""
    items = [{**_MINIMAL, "jobUrl": f"https://example.com/j{i}"}
             for i in range(100)]
    _patch(monkeypatch, module, items)
    jobs = module.scrape("Data Analyst", "Data Analyst", "actor~id",
                         jobs_per_category=50)
    assert len(jobs) == 50


@pytest.mark.parametrize("module", [linkedin])
def test_html_is_preferred_over_a_prefused_plain_field(module, monkeypatch):
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
    job = _scrape(module, monkeypatch, item)
    assert "RemoteTravel" not in job["description"]
    assert "Location: Remote" in job["description"]
