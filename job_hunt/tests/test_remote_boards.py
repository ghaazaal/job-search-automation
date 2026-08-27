"""Fixtures are rows from a live flash_scraper~remote-job-aggregator run."""
from src.scrapers import remote_boards


def test_search_terms_are_the_role_titles(monkeypatch):
    sent = {}
    monkeypatch.setattr(remote_boards, "call_actor",
                        lambda a, p, l, t: sent.update(p) or [])
    remote_boards.scrape("Data Analyst", "Data Analyst", "actor")
    assert sent["searchTerms"] == ["Data Analyst"]
    assert sent["maxItems"] > 0


def test_maps_a_worldwide_row(monkeypatch):
    row = {
        "title": "Senior Staff Data Engineer",
        "company": "Faire",
        "location": "Anywhere in the World",
        "url": "https://weworkremotely.com/jobs/1",
        "source_board": "weworkremotely",
        "posted_at": "2026-08-25",
        "salary_min": 276000, "salary_max": 379500,
        "salary_currency": "USD",
        "description": "Build the data platform.",
    }
    monkeypatch.setattr(remote_boards, "call_actor", lambda *a, **k: [row])
    jobs = remote_boards.scrape("Data Engineer", "Data Engineer", "actor")
    assert len(jobs) == 1
    job = jobs[0]
    assert job["title"] == "Senior Staff Data Engineer"
    assert job["company"] == "Faire"
    assert job["platform"] == "We Work Remotely"
    assert job["work_mode"] == "remote"
    assert job["location"] == "Anywhere in the World"
    assert "276,000" in job["salary"] or "276000" in job["salary"]
    assert job["source_board"] == "weworkremotely"


def test_source_board_survives_when_platform_names_collide(monkeypatch):
    """devitjobs_us and devitjobs_uk both render as 'DevITjobs' in
    `platform` — `source_board` is the only field that still tells them
    apart, so it must carry the raw slug, not the display name."""
    rows = [
        {"title": "Data Engineer", "company": "A",
         "location": "United States",
         "url": "https://devitjobs.com/us/1",
         "source_board": "devitjobs_us"},
        {"title": "Data Engineer", "company": "B",
         "location": "United Kingdom",
         "url": "https://devitjobs.com/uk/1",
         "source_board": "devitjobs_uk"},
    ]
    monkeypatch.setattr(remote_boards, "call_actor", lambda *a, **k: rows)
    jobs = remote_boards.scrape("Data Engineer", "Data Engineer", "actor")
    assert len(jobs) == 2
    assert jobs[0]["platform"] == jobs[1]["platform"] == "DevITjobs"
    assert {j["source_board"] for j in jobs} == {"devitjobs_us", "devitjobs_uk"}


def test_every_row_is_remote(monkeypatch):
    """These boards carry nothing else - that is what they are for."""
    row = {"title": "Data Analyst", "company": "X", "location": "United States",
           "url": "https://remoteok.com/1", "source_board": "remoteok",
           "posted_at": "2026-08-25", "description": ""}
    monkeypatch.setattr(remote_boards, "call_actor", lambda *a, **k: [row])
    assert remote_boards.scrape("Data Analyst", "Data Analyst", "a")[0]["work_mode"] == "remote"


def test_rows_without_a_url_are_skipped(monkeypatch):
    monkeypatch.setattr(remote_boards, "call_actor",
                        lambda *a, **k: [{"title": "X", "company": "Y"}])
    assert remote_boards.scrape("Data Analyst", "Data Analyst", "a") == []


def test_a_failing_actor_returns_nothing_rather_than_raising(monkeypatch):
    """This source is allowed to fail without taking the run down."""
    def boom(*a, **k):
        raise RuntimeError("board down")
    monkeypatch.setattr(remote_boards, "call_actor", boom)
    assert remote_boards.scrape("Data Analyst", "Data Analyst", "a") == []


def test_a_failing_actor_logs_a_warning(monkeypatch, caplog):
    """Allowed to fail does not mean allowed to fail invisibly."""
    def boom(*a, **k):
        raise RuntimeError("board down")
    monkeypatch.setattr(remote_boards, "call_actor", boom)
    with caplog.at_level("WARNING", logger="src.scrapers.remote_boards"):
        remote_boards.scrape("Data Analyst", "Data Analyst", "a")
    assert any("board down" in r.message for r in caplog.records)


def test_warns_when_rows_come_back_but_none_parse(monkeypatch, caplog):
    """A shape mismatch (wrong actor id, or the actor's output shape
    changed) must not look like an empty job market - it's a louder,
    different fact than a genuinely empty search."""
    wrong_shaped_row = {"title": "Data Analyst", "company": "Acme",
                         "location": "Remote"}  # no "url" key at all
    monkeypatch.setattr(remote_boards, "call_actor",
                        lambda *a, **k: [wrong_shaped_row])
    with caplog.at_level("WARNING", logger="src.scrapers.remote_boards"):
        jobs = remote_boards.scrape("Data Analyst", "Data Analyst",
                                    "wrong~actor~id")
    assert jobs == []
    assert any("none could be parsed" in r.message for r in caplog.records)


def test_a_missing_posted_at_falls_back_to_today(monkeypatch):
    """Matches how indeed.py and linkedin.py treat a missing date -
    fall back to today rather than storing an empty string."""
    import datetime
    row = {"title": "Data Analyst", "company": "X", "location": "Remote",
           "url": "https://remoteok.com/1", "source_board": "remoteok",
           "description": ""}  # no "posted_at" at all
    monkeypatch.setattr(remote_boards, "call_actor", lambda *a, **k: [row])
    job = remote_boards.scrape("Data Analyst", "Data Analyst", "a")[0]
    assert job["date"] == datetime.date.today().isoformat()


def test_a_non_numeric_salary_does_not_crash_the_whole_category(monkeypatch):
    """Ten independent boards means ten different ideas of what belongs
    in a salary field. A free-text value like "Competitive" (seen on a
    live row) must not blow up _salary and take the entire category's
    results with it via scrape()'s own error boundary - the row should
    just come back with no salary."""
    row = {"title": "Data Analyst", "company": "X", "location": "Remote",
           "url": "https://remoteok.com/1", "source_board": "remoteok",
           "posted_at": "2026-08-25",
           "salary_min": "Competitive", "salary_max": None,
           "salary_currency": "USD", "description": ""}
    monkeypatch.setattr(remote_boards, "call_actor", lambda *a, **k: [row])
    jobs = remote_boards.scrape("Data Analyst", "Data Analyst", "a")
    assert len(jobs) == 1
    assert jobs[0]["salary"] == ""


def test_a_foreign_currency_renders_its_own_symbol(monkeypatch):
    row = {"title": "Data Analyst", "company": "X", "location": "Remote, EU",
           "url": "https://remoteok.com/1", "source_board": "remoteok",
           "posted_at": "2026-08-25",
           "salary_min": 60000, "salary_max": 75000,
           "salary_currency": "EUR", "description": ""}
    monkeypatch.setattr(remote_boards, "call_actor", lambda *a, **k: [row])
    job = remote_boards.scrape("Data Analyst", "Data Analyst", "a")[0]
    assert job["salary"] == "€60,000 – €75,000"


def test_an_unmapped_currency_falls_back_to_its_bare_code(monkeypatch):
    row = {"title": "Data Analyst", "company": "X", "location": "Remote",
           "url": "https://remoteok.com/1", "source_board": "remoteok",
           "posted_at": "2026-08-25",
           "salary_min": 120000, "salary_max": 150000,
           "salary_currency": "CAD", "description": ""}
    monkeypatch.setattr(remote_boards, "call_actor", lambda *a, **k: [row])
    job = remote_boards.scrape("Data Analyst", "Data Analyst", "a")[0]
    assert job["salary"] == "CAD 120,000 – CAD 150,000"


def test_description_is_flattened_like_the_other_scrapers(monkeypatch):
    """Ten boards, no guaranteed formatting - a description that arrives
    pre-flattened with no separators between fields must not defeat
    word-boundary phrase matching. Routed through the same
    extract_description helper indeed.py and linkedin.py use."""
    row = {"title": "Data Analyst", "company": "X", "location": "Remote",
           "url": "https://remoteok.com/1", "source_board": "remoteok",
           "posted_at": "2026-08-25",
           "description": "<p>Location: Remote</p><p>Travel: None</p>"}
    monkeypatch.setattr(remote_boards, "call_actor", lambda *a, **k: [row])
    job = remote_boards.scrape("Data Analyst", "Data Analyst", "a")[0]
    assert "Location: Remote Travel: None" == job["description"]


def test_description_snippet_is_used_when_description_is_missing(monkeypatch):
    row = {"title": "Data Analyst", "company": "X", "location": "Remote",
           "url": "https://remoteok.com/1", "source_board": "remoteok",
           "posted_at": "2026-08-25",
           "description_snippet": "Build the data platform."}
    monkeypatch.setattr(remote_boards, "call_actor", lambda *a, **k: [row])
    job = remote_boards.scrape("Data Analyst", "Data Analyst", "a")[0]
    assert job["description"] == "Build the data platform."
