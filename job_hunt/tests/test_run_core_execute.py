"""Tests for run_core.execute — the shared scrape-and-score path.

No network: scrapers are injected. The scorer is real, because what it writes
into the store is exactly what this is for.
"""
import pytest

from src.run_core import execute
from src.store.db import connect
from src.store.ingest import ensure_user
from src.store.queries import map_sections
from src.store.runs import get_run, start_run
from src.store.schema import init_db

_CONFIG = {
    "apify": {},
    "search": {"days_posted": 7, "jobs_per_category": 50, "run_timeout": 120},
    "scoring": {"bands": {"strong": 8, "partial": 5}},
}

_PROFILE = {"location": "Toronto, ON", "country": "ca",
            "work_modes": ["remote"], "setup_complete": 1}


def _job(url, title="BI Developer", company="Acme"):
    return {"cat": title, "title": title, "company": company,
            "location": "Toronto, ON", "platform": "Indeed",
            "date": "2026-08-14", "url": url, "salary": "",
            "description": "We need Power BI and SQL."}


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "core.db")
    init_db(c)
    yield c
    c.close()


@pytest.fixture
def user(conn):
    return ensure_user(conn, "default")


@pytest.fixture
def resume(conn, user):
    from src.store.profile import create_resume, list_resumes, update_resume

    resume_id = create_resume(conn, user, label="bi", orig_filename="bi.pdf",
                              sha256="abc123", stored_path="resumes/1/abc.pdf",
                              extracted_text="Power BI")
    update_resume(conn, user, resume_id, label="bi",
                  target_roles=[{"title": "BI Developer", "aliases": []}],
                  skills=[{"name": "Power BI", "tier": "core", "aliases": []}],
                  seniority="senior")
    return list_resumes(conn, user, active_only=True)[0]


def _scrapers(indeed_jobs=None, linkedin_jobs=None, fail=()):
    """Fake scrapers. `fail` names sources that raise instead of returning."""
    def make(name, jobs):
        def scrape(category, title, actor_id, *args, **kwargs):
            if name in fail:
                raise RuntimeError(f"{name} actor timed out")
            return list(jobs or [])
        return scrape
    return {"Indeed": make("Indeed", indeed_jobs),
            "LinkedIn": make("LinkedIn", linkedin_jobs)}


def test_scraped_jobs_are_scored_and_stored(conn, user, resume):
    run_id = start_run(conn, user)
    result = execute(conn, user, run_id, _CONFIG, [resume], _PROFILE,
                     scrapers=_scrapers(indeed_jobs=[_job("https://x/1")]))

    assert result.kept == 1
    sections = map_sections(conn, user, 7)
    assert sections["new"], "the stored role should appear on the map"


def test_the_run_finishes_ok(conn, user, resume):
    run_id = start_run(conn, user)
    execute(conn, user, run_id, _CONFIG, [resume], _PROFILE,
            scrapers=_scrapers(indeed_jobs=[_job("https://x/1")]))

    assert get_run(conn, run_id)["status"] == "OK"


def test_progress_is_emitted_for_every_step(conn, user, resume):
    seen = []
    run_id = start_run(conn, user)
    execute(conn, user, run_id, _CONFIG, [resume], _PROFILE,
            on_progress=seen.append,
            scrapers=_scrapers(indeed_jobs=[_job("https://x/1")]))

    stages = [event["stage"] for event in seen]
    assert stages[0] == "scraping"
    assert "scoring" in stages and "storing" in stages


def test_the_first_event_already_lists_every_step(conn, user, resume):
    """The screen renders the whole plan from poll one."""
    seen = []
    run_id = start_run(conn, user)
    execute(conn, user, run_id, _CONFIG, [resume], _PROFILE,
            on_progress=seen.append, scrapers=_scrapers())

    assert len(seen[0]["steps"]) == 2      # one role, two sources


def test_one_source_failing_does_not_lose_the_other(conn, user, resume):
    run_id = start_run(conn, user)
    result = execute(conn, user, run_id, _CONFIG, [resume], _PROFILE,
                     scrapers=_scrapers(indeed_jobs=[_job("https://x/1")],
                                        fail=("LinkedIn",)))

    assert result.kept == 1
    assert get_run(conn, run_id)["status"] == "OK"


def test_a_failed_source_is_marked_on_its_step(conn, user, resume):
    seen = []
    run_id = start_run(conn, user)
    execute(conn, user, run_id, _CONFIG, [resume], _PROFILE,
            on_progress=seen.append,
            scrapers=_scrapers(indeed_jobs=[_job("https://x/1")],
                               fail=("LinkedIn",)))

    final = seen[-1]["steps"]
    states = {step["source"]: step["state"] for step in final}
    assert states == {"Indeed": "done", "LinkedIn": "failed"}


def test_finding_nothing_is_a_successful_run(conn, user, resume):
    """An empty search is an answer, not a failure."""
    run_id = start_run(conn, user)
    result = execute(conn, user, run_id, _CONFIG, [resume], _PROFILE,
                     scrapers=_scrapers())

    assert result.kept == 0
    assert get_run(conn, run_id)["status"] == "OK"


def test_a_listing_already_in_the_store_is_not_stored_twice(conn, user, resume):
    first = start_run(conn, user)
    execute(conn, user, first, _CONFIG, [resume], _PROFILE,
            scrapers=_scrapers(indeed_jobs=[_job("https://x/1")]))

    second = start_run(conn, user)
    result = execute(conn, user, second, _CONFIG, [resume], _PROFILE,
                     scrapers=_scrapers(indeed_jobs=[_job("https://x/1")]))

    assert result.kept == 0


def test_duplicates_within_one_scrape_collapse(conn, user, resume):
    run_id = start_run(conn, user)
    result = execute(conn, user, run_id, _CONFIG, [resume], _PROFILE,
                     scrapers=_scrapers(indeed_jobs=[_job("https://x/1")],
                                        linkedin_jobs=[_job("https://x/1")]))

    assert result.scraped == 2
    assert result.kept == 1


def test_the_enrich_hook_sees_the_new_jobs(conn, user, resume):
    """The terminal path uses this for company enrichment."""
    handed = {}

    def enrich(jobs):
        handed["count"] = len(jobs)
        return jobs

    run_id = start_run(conn, user)
    execute(conn, user, run_id, _CONFIG, [resume], _PROFILE, enrich=enrich,
            scrapers=_scrapers(indeed_jobs=[_job("https://x/1")]))

    assert handed["count"] == 1


def test_a_run_with_no_resumes_refuses_rather_than_scraping(conn, user):
    run_id = start_run(conn, user)
    with pytest.raises(ValueError, match="resume"):
        execute(conn, user, run_id, _CONFIG, [], _PROFILE,
                scrapers=_scrapers())


def test_a_resume_with_no_target_roles_also_refuses(conn, user):
    from src.store.profile import create_resume, list_resumes, update_resume

    resume_id = create_resume(conn, user, label="bi", orig_filename="bi.pdf",
                              sha256="abc123", stored_path="resumes/1/abc.pdf",
                              extracted_text="Power BI")
    update_resume(conn, user, resume_id, label="bi", target_roles=[],
                  skills=[{"name": "Power BI", "tier": "core", "aliases": []}],
                  seniority="senior")
    empty_resume = list_resumes(conn, user, active_only=True)[0]

    run_id = start_run(conn, user)
    with pytest.raises(ValueError, match="target roles"):
        execute(conn, user, run_id, _CONFIG, [empty_resume], _PROFILE,
                scrapers=_scrapers())


def test_a_foreign_restriction_reaches_the_stored_reason(conn, user, resume):
    """The profile's country must arrive at the scorer — this is the wiring
    guard for the single Scorer construction site."""
    job = _job("https://x/9")
    job["description"] += " Must be based in the UK."
    run_id = start_run(conn, user)
    result = execute(conn, user, run_id, _CONFIG, [resume], _PROFILE,
                     scrapers=_scrapers(indeed_jobs=[job]))
    assert "restricted to UK" in result.scored_jobs[0]["reason"]


def test_the_fallback_tag_becomes_a_flag_and_never_reaches_the_store(conn, user, resume):
    tagged = {**_job("https://x/8"), "_scraped_under": "us"}
    run_id = start_run(conn, user)
    result = execute(conn, user, run_id, _CONFIG, [resume], _PROFILE,
                     scrapers=_scrapers(indeed_jobs=[tagged]))
    evidence = result.scored_jobs[0]
    assert "not verified for your country" in evidence["reason"]
    # Popped, not read: the transient key must be gone from what the
    # LLM/Excel steps and persist_run receive.
    assert "_scraped_under" not in evidence


def test_a_foreign_onsite_job_is_dropped_not_stored(conn, user, resume):
    job = _job("https://x/20")
    job["location"] = "Bengaluru, Karnataka, India"
    job["description"] += " Onsite work required."
    run_id = start_run(conn, user)
    result = execute(conn, user, run_id, _CONFIG, [resume], _PROFILE,
                     scrapers=_scrapers(indeed_jobs=[job]))
    assert result.dropped == 1
    assert result.kept == 0
    assert conn.execute("SELECT COUNT(*) AS n FROM role").fetchone()["n"] == 0


def test_a_local_hybrid_job_is_kept_without_penalty(conn, user, resume):
    """'Yerevan hybrid — bring it': a mode mismatch in the user's own
    country is workable in person."""
    job = _job("https://x/21")
    job["location"] = "Toronto, Ontario, Canada"
    job["description"] += " Hybrid work, 2 days a week in the office."
    run_id = start_run(conn, user)
    result = execute(conn, user, run_id, _CONFIG, [resume], _PROFILE,
                     scrapers=_scrapers(indeed_jobs=[job]))
    assert result.dropped == 0
    assert result.kept == 1
    evidence = result.scored_jobs[0]
    assert evidence["work_mode"] == "hybrid"
    assert "says hybrid" not in evidence["reason"]


def test_an_unplaceable_mode_mismatch_is_flagged_not_dropped(conn, user, resume):
    job = _job("https://x/22")
    job["location"] = "Jakarta Metropolitan Area"
    job["description"] += " Hybrid work, 2 days a week in the office."
    run_id = start_run(conn, user)
    result = execute(conn, user, run_id, _CONFIG, [resume], _PROFILE,
                     scrapers=_scrapers(indeed_jobs=[job]))
    assert result.kept == 1
    evidence = result.scored_jobs[0]
    assert "says hybrid, you searched remote-only" in evidence["reason"]
    assert "_mode_mismatch" not in evidence


def test_a_remote_tagged_location_vetoes_a_stray_prose_phrase(conn, user, resume):
    """The location field says Remote (actor-tagged) while the prose says
    hybrid — conflicting evidence claims nothing: kept, unflagged, no
    stored mode. 36% of real stored locations are literally 'Remote', and
    they are exactly where the phrase list is blindest."""
    job = _job("https://x/25")
    job["location"] = "Remote"
    job["description"] += " Hybrid work, 2 days a week in the office."
    run_id = start_run(conn, user)
    result = execute(conn, user, run_id, _CONFIG, [resume], _PROFILE,
                     scrapers=_scrapers(indeed_jobs=[job]))
    assert result.kept == 1
    evidence = result.scored_jobs[0]
    assert "says hybrid" not in evidence["reason"]
    assert evidence.get("work_mode") is None


def test_a_job_with_no_mode_word_is_untouched(conn, user, resume):
    run_id = start_run(conn, user)
    result = execute(conn, user, run_id, _CONFIG, [resume], _PROFILE,
                     scrapers=_scrapers(indeed_jobs=[_job("https://x/23")]))
    assert result.dropped == 0
    assert result.kept == 1
    assert result.scored_jobs[0].get("work_mode") is None


def test_the_dropped_count_reaches_progress(conn, user, resume):
    seen = []
    job = _job("https://x/24")
    job["location"] = "Bengaluru, Karnataka, India"
    job["description"] += " Onsite work required."
    run_id = start_run(conn, user)
    execute(conn, user, run_id, _CONFIG, [resume], _PROFILE,
            on_progress=seen.append,
            scrapers=_scrapers(indeed_jobs=[job]))
    assert seen[-1]["dropped"] == 1


def test_a_decorated_remote_location_still_vetoes(conn, user, resume):
    """'Remote, US' is Indeed's own we-don't-know placeholder — it must
    land on the veto side, not resolve to a country and drop."""
    job = _job("https://x/26")
    job["location"] = "Remote, US"
    job["description"] += " Hybrid work, 2 days a week in the office."
    run_id = start_run(conn, user)
    result = execute(conn, user, run_id, _CONFIG, [resume], _PROFILE,
                     scrapers=_scrapers(indeed_jobs=[job]))
    assert result.dropped == 0
    assert result.kept == 1
    assert result.scored_jobs[0].get("work_mode") is None


def test_the_users_own_city_is_local_without_a_country(conn, user, resume):
    """'Toronto, ON' parses to no country, but it IS Toronto — the
    profile's own city keeps the job clean, stamp intact."""
    job = _job("https://x/27")
    job["location"] = "Toronto, ON"
    job["description"] += " Hybrid work, 2 days a week in the office."
    run_id = start_run(conn, user)
    result = execute(conn, user, run_id, _CONFIG, [resume], _PROFILE,
                     scrapers=_scrapers(indeed_jobs=[job]))
    assert result.dropped == 0
    evidence = result.scored_jobs[0]
    assert evidence["work_mode"] == "hybrid"
    assert "says hybrid" not in evidence["reason"]


def test_a_location_header_line_rescues_a_perks_mention(conn, user, resume):
    """The reviewed real-world wrong drop: 'Location: Remote' prose plus
    'hybrid work options' in a perks list — conflict claims nothing."""
    job = _job("https://x/28")
    job["location"] = "Cincinnati, OH"
    job["description"] += (" Location: Remote. Travel 2-5 weeks per year."
                           " We offer flexible time off, hybrid work"
                           " options, and a 401k plan.")
    run_id = start_run(conn, user)
    result = execute(conn, user, run_id, _CONFIG, [resume], _PROFILE,
                     scrapers=_scrapers(indeed_jobs=[job]))
    assert result.dropped == 0
    assert result.kept == 1


def test_the_dropped_count_is_persisted_on_the_run_row(conn, user, resume):
    job = _job("https://x/29")
    job["location"] = "Bengaluru, Karnataka, India"
    job["description"] += " Onsite work required."
    run_id = start_run(conn, user)
    execute(conn, user, run_id, _CONFIG, [resume], _PROFILE,
            scrapers=_scrapers(indeed_jobs=[job]))
    assert conn.execute("SELECT dropped FROM run WHERE id = ?",
                        (run_id,)).fetchone()["dropped"] == 1


def test_dropped_jobs_never_reach_the_enrich_hook(conn, user, resume):
    handed = []

    def enrich(jobs):
        handed.extend(j["url"] for j in jobs)
        return jobs

    dropped_job = _job("https://x/30")
    dropped_job["location"] = "Bengaluru, Karnataka, India"
    dropped_job["description"] += " Onsite work required."
    # A distinct company: dedupe's fingerprint is company+title, deliberately
    # location-blind (remote postings mirror per-country), so two jobs with
    # the default _job() company/title would collapse into one candidate
    # before the ladder ever ran, regardless of this test's intent.
    survivor = _job("https://x/31", company="Widgets Inc")
    run_id = start_run(conn, user)
    execute(conn, user, run_id, _CONFIG, [resume], _PROFILE, enrich=enrich,
            scrapers=_scrapers(indeed_jobs=[dropped_job, survivor]))
    assert handed == ["https://x/31"]
