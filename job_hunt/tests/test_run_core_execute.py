"""Tests for run_core.execute — the shared scrape-and-score path.

No network: scrapers are injected. The scorer is real, because what it writes
into the store is exactly what this is for.
"""
import pytest

from src.run_core import _apply_gates, execute
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

# A minimal vocabulary — just enough for _apply_gates' two gates, not the
# full vocabulary.yaml — so these tests don't depend on real-world phrase
# lists changing underneath them.
_GATE_VOCAB = {
    "roles": {"include": ["data analyst", "bi developer"],
              "exclude": ["nurse"]},
    "work_mode": {
        "remote_phrases": ["fully remote", "work from home"],
        "hybrid_phrases": ["hybrid work"],
        "onsite_phrases": ["onsite role", "on-site required"],
    },
    "eligibility": {"countries": {"ca": ["canada"], "in": ["india"],
                                  "us": ["us", "usa", "united states"]}},
}


def _job(url, title="BI Developer", company="Acme"):
    return {"cat": title, "title": title, "company": company,
            "location": "Toronto, ON", "platform": "Remote board",
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


def _scrapers(linkedin_jobs=None, remote_boards_jobs=None,
             fail=(), linkedin_mode_jobs=None):
    """Fake scrapers. `fail` names sources that raise instead of returning.

    `linkedin_mode_jobs`, if given, maps a mode word ("remote"/"hybrid") to
    the jobs returned only for the LinkedIn call whose search title carries
    that mode lane's prefix (e.g. "remote BI Developer") — every other
    LinkedIn call still gets `linkedin_jobs`.

    Indeed was removed in Ship 8. Fixtures that used to arrive through it
    now arrive through Remote boards, which — like Indeed's local lane —
    is planned exactly once per title, so every scraped-count assertion
    still counts what it counted.
    """
    def make(name, jobs):
        def scrape(category, title, actor_id, *args, **kwargs):
            if name in fail:
                raise RuntimeError(f"{name} actor timed out")
            if name == "LinkedIn" and linkedin_mode_jobs:
                for mode, mode_jobs in linkedin_mode_jobs.items():
                    if title == f"{mode} {category}":
                        return list(mode_jobs)
            return list(jobs or [])
        return scrape
    return {"LinkedIn": make("LinkedIn", linkedin_jobs),
            "Remote boards": make("Remote boards", remote_boards_jobs)}


def test_scraped_jobs_are_scored_and_stored(conn, user, resume):
    """The map lists roles proven open, so reaching it takes a board row
    whose published reach names somewhere the user can work."""
    job = {**_job("https://x/1"), "source_board": "himalayas",
           "location": "Anywhere in the World"}
    run_id = start_run(conn, user)
    result = execute(conn, user, run_id, _CONFIG, [resume], _PROFILE,
                     scrapers=_scrapers(remote_boards_jobs=[job]))

    assert result.kept == 1
    sections = map_sections(conn, user, 7)
    assert sections["new"], "the stored role should appear on the map"


def test_an_unverified_role_is_stored_but_not_listed(conn, user, resume):
    """A LinkedIn row has a place, not a reach statement. It is kept and
    counted, and it does not claim to be somewhere the user can work."""
    run_id = start_run(conn, user)
    result = execute(conn, user, run_id, _CONFIG, [resume], _PROFILE,
                     scrapers=_scrapers(linkedin_jobs=[_job("https://x/2")]))

    assert result.kept == 1
    assert not map_sections(conn, user, 7)["new"]
    row = conn.execute("SELECT location_scope FROM role WHERE url = ?",
                       ("https://x/2",)).fetchone()
    assert row["location_scope"] is None


def test_the_run_finishes_ok(conn, user, resume):
    run_id = start_run(conn, user)
    execute(conn, user, run_id, _CONFIG, [resume], _PROFILE,
            scrapers=_scrapers(remote_boards_jobs=[_job("https://x/1")]))

    assert get_run(conn, run_id)["status"] == "OK"


def test_progress_is_emitted_for_every_step(conn, user, resume):
    seen = []
    run_id = start_run(conn, user)
    execute(conn, user, run_id, _CONFIG, [resume], _PROFILE,
            on_progress=seen.append,
            scrapers=_scrapers(remote_boards_jobs=[_job("https://x/1")]))

    stages = [event["stage"] for event in seen]
    assert stages[0] == "scraping"
    assert "scoring" in stages and "storing" in stages


def test_the_first_event_already_lists_every_step(conn, user, resume):
    """The screen renders the whole plan from poll one."""
    seen = []
    run_id = start_run(conn, user)
    execute(conn, user, run_id, _CONFIG, [resume], _PROFILE,
            on_progress=seen.append, scrapers=_scrapers())

    # 1 worldwide (Remote boards — LinkedIn has no plain worldwide lane)
    # + 1 local (LinkedIn — Remote boards has no local lane) + 1
    # LinkedIn-only mode lane ("remote", the profile's own work mode) = 3.
    assert len(seen[0]["steps"]) == 3


def test_one_source_failing_does_not_lose_the_other(conn, user, resume):
    run_id = start_run(conn, user)
    result = execute(conn, user, run_id, _CONFIG, [resume], _PROFILE,
                     scrapers=_scrapers(remote_boards_jobs=[_job("https://x/1")],
                                        fail=("LinkedIn",)))

    assert result.kept == 1
    assert get_run(conn, run_id)["status"] == "OK"


def test_remote_boards_failing_does_not_lose_the_others(conn, user, resume):
    """Remote boards is allowed to fail (young actor, no ratings) — its own
    scrape swallows errors and returns [], but the run loop's try/except
    must also survive an actor raising outright, same as any other source."""
    run_id = start_run(conn, user)
    result = execute(conn, user, run_id, _CONFIG, [resume], _PROFILE,
                     scrapers=_scrapers(linkedin_jobs=[_job("https://x/rb1")],
                                        fail=("Remote boards",)))

    assert result.kept == 1
    assert get_run(conn, run_id)["status"] == "OK"


def test_a_failed_source_is_marked_on_its_step(conn, user, resume):
    seen = []
    run_id = start_run(conn, user)
    execute(conn, user, run_id, _CONFIG, [resume], _PROFILE,
            on_progress=seen.append,
            scrapers=_scrapers(remote_boards_jobs=[_job("https://x/1")],
                               fail=("LinkedIn",)))

    final = seen[-1]["steps"]
    states = {step["source"]: step["state"] for step in final}
    assert states == {"LinkedIn": "failed", "Remote boards": "done"}


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
            scrapers=_scrapers(remote_boards_jobs=[_job("https://x/1")]))

    second = start_run(conn, user)
    result = execute(conn, user, second, _CONFIG, [resume], _PROFILE,
                     scrapers=_scrapers(remote_boards_jobs=[_job("https://x/1")]))

    assert result.kept == 0


def test_duplicates_within_one_scrape_collapse(conn, user, resume):
    run_id = start_run(conn, user)
    result = execute(conn, user, run_id, _CONFIG, [resume], _PROFILE,
                     scrapers=_scrapers(remote_boards_jobs=[_job("https://x/1")],
                                        linkedin_jobs=[_job("https://x/1")]))

    # Remote boards' 1 worldwide lane plus LinkedIn's 2 (local + the
    # "remote" mode lane), each finding the same job: 1 + 2 = 3.
    assert result.scraped == 3
    assert result.kept == 1


def test_the_enrich_hook_sees_the_new_jobs(conn, user, resume):
    """The terminal path uses this for company enrichment."""
    handed = {}

    def enrich(jobs):
        handed["count"] = len(jobs)
        return jobs

    run_id = start_run(conn, user)
    execute(conn, user, run_id, _CONFIG, [resume], _PROFILE, enrich=enrich,
            scrapers=_scrapers(remote_boards_jobs=[_job("https://x/1")]))

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
                     scrapers=_scrapers(remote_boards_jobs=[job]))
    assert "restricted to UK" in result.scored_jobs[0]["reason"]


def test_a_foreign_onsite_job_is_dropped_not_stored(conn, user, resume):
    job = _job("https://x/20")
    job["location"] = "Bengaluru, Karnataka, India"
    job["description"] += " Onsite work required."
    run_id = start_run(conn, user)
    result = execute(conn, user, run_id, _CONFIG, [resume], _PROFILE,
                     scrapers=_scrapers(remote_boards_jobs=[job]))
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
                     scrapers=_scrapers(remote_boards_jobs=[job]))
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
                     scrapers=_scrapers(remote_boards_jobs=[job]))
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
                     scrapers=_scrapers(remote_boards_jobs=[job]))
    assert result.kept == 1
    evidence = result.scored_jobs[0]
    assert "says hybrid" not in evidence["reason"]
    assert evidence.get("work_mode") is None


def test_a_job_with_no_mode_word_is_untouched(conn, user, resume):
    run_id = start_run(conn, user)
    result = execute(conn, user, run_id, _CONFIG, [resume], _PROFILE,
                     scrapers=_scrapers(remote_boards_jobs=[_job("https://x/23")]))
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
            scrapers=_scrapers(remote_boards_jobs=[job]))
    assert seen[-1]["dropped"] == 1


def test_a_decorated_remote_location_still_vetoes(conn, user, resume):
    """'Remote, US' is Indeed's own we-don't-know placeholder — it must
    land on the veto side, not resolve to a country and drop."""
    job = _job("https://x/26")
    job["location"] = "Remote, US"
    job["description"] += " Hybrid work, 2 days a week in the office."
    run_id = start_run(conn, user)
    result = execute(conn, user, run_id, _CONFIG, [resume], _PROFILE,
                     scrapers=_scrapers(remote_boards_jobs=[job]))
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
                     scrapers=_scrapers(remote_boards_jobs=[job]))
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
                     scrapers=_scrapers(remote_boards_jobs=[job]))
    assert result.dropped == 0
    assert result.kept == 1


def test_the_dropped_count_is_persisted_on_the_run_row(conn, user, resume):
    job = _job("https://x/29")
    job["location"] = "Bengaluru, Karnataka, India"
    job["description"] += " Onsite work required."
    run_id = start_run(conn, user)
    execute(conn, user, run_id, _CONFIG, [resume], _PROFILE,
            scrapers=_scrapers(remote_boards_jobs=[job]))
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
            scrapers=_scrapers(remote_boards_jobs=[dropped_job, survivor]))
    assert handed == ["https://x/31"]


def test_the_local_lane_searches_the_actual_place_with_all_modes(conn, user, resume):
    calls = []

    def spy(category, title, actor_id, *args, **kwargs):
        calls.append({"location": kwargs.get("location"),
                      "work_modes": tuple(kwargs.get("work_modes") or ())})
        return []

    run_id = start_run(conn, user)
    execute(conn, user, run_id, _CONFIG, [resume], _PROFILE,
            scrapers={"LinkedIn": spy, "Remote boards": spy})

    local = [c for c in calls
             if c["work_modes"] == ("remote", "hybrid", "onsite")]
    # LinkedIn is the only source with a local lane: Remote boards is
    # borderless and has no "near Toronto" to search.
    assert len(local) == 1
    assert all(c["location"] == "Toronto, ON" for c in local)


def test_no_location_means_no_local_lane(conn, user, resume):
    profile = {**_PROFILE, "location": ""}
    seen = []
    run_id = start_run(conn, user)
    execute(conn, user, run_id, _CONFIG, [resume], profile,
            on_progress=seen.append, scrapers=_scrapers())
    # Remote boards on the worldwide lane (LinkedIn is local-only and so
    # drops out entirely when there is no location), plus one LinkedIn
    # mode lane ("remote") — a mode lane needs no location, so an empty
    # profile location still yields it: 1 + 1 = 2.
    assert len(seen[0]["steps"]) == 2


def test_a_disabled_source_is_never_planned_or_called(conn, user, resume):
    config = {**_CONFIG,
              "search": {**_CONFIG["search"], "sources": {"indeed": False}}}
    calls = []

    def spy(*args, **kwargs):
        calls.append(args)
        return []

    seen = []
    run_id = start_run(conn, user)
    execute(conn, user, run_id, config, [resume], _PROFILE,
            on_progress=seen.append,
            scrapers={"Indeed": spy, "LinkedIn": spy})

    sources = {s["source"] for s in seen[0]["steps"]}
    assert sources == {"LinkedIn", "Remote boards"}


def test_a_multi_word_source_can_be_switched_off_in_config(conn, user, resume):
    """A user editing config.yaml sees `remote_boards_actor` right above
    search.sources and will reasonably guess `remote_boards` there too —
    not `"remote boards"`, the space-containing display name that
    happened to work by accident while every source was one word."""
    config = {**_CONFIG,
              "search": {**_CONFIG["search"],
                        "sources": {"remote_boards": False}}}
    seen = []
    run_id = start_run(conn, user)
    execute(conn, user, run_id, config, [resume], _PROFILE,
            on_progress=seen.append, scrapers=_scrapers())

    sources = {s["source"] for s in seen[0]["steps"]}
    assert sources == {"LinkedIn"}


def test_a_missing_sources_key_enables_everything(conn, user, resume):
    seen = []
    run_id = start_run(conn, user)
    execute(conn, user, run_id, _CONFIG, [resume], _PROFILE,
            on_progress=seen.append, scrapers=_scrapers())
    assert {s["source"] for s in seen[0]["steps"]} == {
        "LinkedIn", "Remote boards"}


def test_local_country_verifies_eligibility(conn, user, resume):
    job = _job("https://x/verified")
    job["location"] = "Toronto, Ontario, Canada"
    run_id = start_run(conn, user)
    result = execute(conn, user, run_id, _CONFIG, [resume], _PROFILE,
                     scrapers=_scrapers(remote_boards_jobs=[job]))
    evidence = result.scored_jobs[0]
    assert evidence["eligibility_verified"] is True
    assert "open to your location" in evidence["reason"]
    assert conn.execute(
        "SELECT eligibility_verified FROM role WHERE url = ?",
        ("https://x/verified",)).fetchone()["eligibility_verified"] == 1


def test_an_unplaceable_job_is_stored_unverified(conn, user, resume):
    job = _job("https://x/unv")
    job["location"] = "Remote"
    run_id = start_run(conn, user)
    result = execute(conn, user, run_id, _CONFIG, [resume], _PROFILE,
                     scrapers=_scrapers(remote_boards_jobs=[job]))
    evidence = result.scored_jobs[0]
    assert evidence["eligibility_verified"] is False
    assert "location eligibility not verified" in evidence["reason"]
    assert "_local_ok" not in evidence


def test_offtopic_titles_are_never_stored(conn, user, resume):
    """A nurse posting must not reach the map, whatever it scores."""
    run_id = start_run(conn, user)
    result = execute(conn, user, run_id, _CONFIG, [resume], _PROFILE,
                     scrapers=_scrapers(remote_boards_jobs=[
                         _job("https://x/40"),
                         _job("https://x/41", title="Nurse Practitioner",
                              company="Med"),
                     ]))
    titles = [job["title"] for job in result.scored_jobs]
    assert titles == ["BI Developer"]
    assert result.offtopic == 1


def test_offtopic_count_reaches_the_progress_payload(conn, user, resume):
    seen = []
    run_id = start_run(conn, user)
    execute(conn, user, run_id, _CONFIG, [resume], _PROFILE,
            on_progress=seen.append,
            scrapers=_scrapers(remote_boards_jobs=[
                _job("https://x/42", title="Travel Advisor", company="T"),
            ]))
    assert seen[-1]["offtopic"] == 1


def test_offtopic_jobs_never_reach_the_enrich_hook(conn, user, resume):
    handed = []

    def enrich(jobs):
        handed.extend(j["url"] for j in jobs)
        return jobs

    offtopic_job = _job("https://x/43", title="Nurse Practitioner",
                        company="Med")
    survivor = _job("https://x/44", company="Widgets Inc")
    run_id = start_run(conn, user)
    execute(conn, user, run_id, _CONFIG, [resume], _PROFILE, enrich=enrich,
            scrapers=_scrapers(remote_boards_jobs=[offtopic_job, survivor]))
    assert handed == ["https://x/44"]


def test_the_local_lane_never_falls_back(conn, user, resume):
    """The local lane finding nothing must stay silent, not retry with the
    legacy Worldwide/remote-us payload — that re-fetches the worldwide
    lane's own results and double-counts `scraped`."""
    calls = []

    def spy(category, title, actor_id, *args, **kwargs):
        calls.append({"title": title,
                      "location": kwargs.get("location"),
                      "work_modes": tuple(kwargs.get("work_modes") or ()),
                      "allow_fallback": kwargs.get("allow_fallback")})
        return []

    run_id = start_run(conn, user)
    execute(conn, user, run_id, _CONFIG, [resume], _PROFILE,
            scrapers={"Indeed": spy, "LinkedIn": spy, "Remote boards": spy})

    # The local lane is the only one that names the profile's own place;
    # the other two both search Worldwide and are told apart by their
    # search words, since a mode lane prefixes the mode onto the title.
    local_calls = [c for c in calls
                  if c["location"] == _PROFILE["location"]]
    worldwide_calls = [c for c in calls
                       if c["location"] != _PROFILE["location"]
                       and c["title"] == "BI Developer"]
    mode_lane_calls = [c for c in calls
                      if c["location"] != _PROFILE["location"]
                      and c["title"] != "BI Developer"]

    assert local_calls and all(c["allow_fallback"] is False
                               for c in local_calls)
    assert worldwide_calls and all(c["allow_fallback"] is not False
                                   for c in worldwide_calls)
    assert mode_lane_calls and all(c["allow_fallback"] is False
                                   for c in mode_lane_calls)


def test_a_mode_lane_prefixes_the_mode_onto_the_search_words(conn, user, resume):
    calls = []

    def spy(category, title, actor_id, *args, **kwargs):
        calls.append({"category": category, "title": title})
        return []

    run_id = start_run(conn, user)
    execute(conn, user, run_id, _CONFIG, [resume], _PROFILE,
            scrapers={"Indeed": spy, "LinkedIn": spy})

    assert {"category": "BI Developer", "title": "remote BI Developer"} in calls


def test_a_mode_lane_sends_no_fallback_and_a_worldwide_location(conn, user, resume):
    calls = []

    def spy(category, title, actor_id, *args, **kwargs):
        if title == "remote BI Developer":
            calls.append({"location": kwargs.get("location"),
                          "allow_fallback": kwargs.get("allow_fallback")})
        return []

    run_id = start_run(conn, user)
    execute(conn, user, run_id, _CONFIG, [resume], _PROFILE,
            scrapers={"Indeed": spy, "LinkedIn": spy})

    assert calls == [{"location": "Worldwide", "allow_fallback": False}]


def test_lane_membership_fills_silence_about_work_mode(conn, user, resume):
    """A job the remote lane surfaces, whose own text says nothing about
    mode, still ends up tagged remote — lane membership is the only
    evidence there is."""
    silent_job = _job("https://x/lane1")
    run_id = start_run(conn, user)
    result = execute(conn, user, run_id, _CONFIG, [resume], _PROFILE,
                     scrapers=_scrapers(
                         linkedin_mode_jobs={"remote": [silent_job]}))

    assert result.kept == 1
    evidence = result.scored_jobs[0]
    assert evidence["work_mode"] == "remote"
    # Transient, popped inside _apply_gates: must never reach what the
    # LLM/Excel steps and persist_run receive, same guard as
    # _scraped_under above.
    assert "_lane_mode" not in evidence


def test_lane_and_text_agreeing_confirms_the_mode(conn, user, resume):
    """A job surfaced by the remote lane whose own description also says
    remote is the third, unpinned branch of the rule: lane and text
    agreeing is not a conflict, so the mode is simply confirmed."""
    agreeing_job = _job("https://x/lane3")
    agreeing_job["description"] += " This is a remote position."
    run_id = start_run(conn, user)
    result = execute(conn, user, run_id, _CONFIG, [resume], _PROFILE,
                     scrapers=_scrapers(
                         linkedin_mode_jobs={"remote": [agreeing_job]}))

    assert result.kept == 1
    assert result.scored_jobs[0]["work_mode"] == "remote"


def test_lane_and_text_disagreeing_claims_nothing(conn, user, resume):
    """A job surfaced by the remote lane whose own description says
    hybrid must not come out as remote, or as hybrid — conflicting
    evidence claims nothing, exactly like every other conflict this
    scorer handles."""
    conflicting_job = _job("https://x/lane2")
    conflicting_job["description"] += (
        " Hybrid work, 2 days a week in the office.")
    run_id = start_run(conn, user)
    result = execute(conn, user, run_id, _CONFIG, [resume], _PROFILE,
                     scrapers=_scrapers(
                         linkedin_mode_jobs={"remote": [conflicting_job]}))

    assert result.kept == 1
    assert result.scored_jobs[0].get("work_mode") is None


# --- _apply_gates: direct tests, no db/run/scrapers needed -----------------

def test_apply_gates_relevance_gate_rejects_offtopic_titles():
    jobs = [_job("https://x/g1", title="BI Developer"),
           _job("https://x/g2", title="Nurse Practitioner")]
    kept, offtopic, dropped = _apply_gates(
        jobs, _GATE_VOCAB, _PROFILE, ["remote"])
    assert [j["url"] for j in kept] == ["https://x/g1"]
    assert offtopic == 1
    assert dropped == 0


def test_apply_gates_work_mode_policy_drops_a_foreign_onsite_job():
    job = _job("https://x/g3")
    job["location"] = "Bengaluru, India"
    job["description"] += " Onsite role, 5 days in office."
    kept, offtopic, dropped = _apply_gates(
        [job], _GATE_VOCAB, _PROFILE, ["remote"])
    assert kept == []
    assert offtopic == 0
    assert dropped == 1


def test_apply_gates_counts_stay_separate():
    """One offtopic title, one foreign onsite mismatch, one clean survivor.

    Each count registers its own gate's rejection and the survivor passes
    both. This cannot prove the counts are unconflatable — the relevance
    gate runs first and narrows what the geo loop ever sees, so an
    off-topic job can never reach it — but it does catch an off-by-one, a
    wrong-variable increment, or the survivor being dropped."""
    offtopic_job = _job("https://x/g4", title="Nurse Practitioner")
    dropped_job = _job("https://x/g5")
    dropped_job["location"] = "Bengaluru, India"
    dropped_job["description"] += " Onsite role, 5 days in office."
    survivor = _job("https://x/g6")

    kept, offtopic, dropped = _apply_gates(
        [offtopic_job, dropped_job, survivor],
        _GATE_VOCAB, _PROFILE, ["remote"])

    assert [j["url"] for j in kept] == ["https://x/g6"]
    assert offtopic == 1
    assert dropped == 1


def test_apply_gates_a_stated_mode_beats_lane_and_text():
    """kaix sets work_mode from Indeed's own workArrangement.locationType
    field before this ever runs. That publisher-stated value must win
    over both a text phrase and a lane, even when the two weaker signals
    agree with each other and disagree with the stated field - neither
    gets a vote once the posting has already answered."""
    job = _job("https://x/g7")
    job["work_mode"] = "remote"
    job["_lane_mode"] = "hybrid"
    job["description"] += " Hybrid work, 2 days a week in the office."

    kept, offtopic, dropped = _apply_gates(
        [job], _GATE_VOCAB, _PROFILE, ["remote"])

    assert kept[0]["work_mode"] == "remote"
    assert "_lane_mode" not in kept[0]


def test_each_lane_asks_its_own_question_in_its_own_place(conn, user, resume):
    """Before Ship 7's review the worldwide lane passed the profile's own
    location, making its payload identical to the local lane's. Ship 8 then
    took LinkedIn off the worldwide lane entirely, so the only un-prefixed
    LinkedIn call left is the local one."""
    linkedin, boards = [], []

    def li(category, title, actor_id, *args, **kwargs):
        linkedin.append({"title": title, "location": kwargs.get("location")})
        return []

    def bd(category, title, actor_id, *args, **kwargs):
        boards.append({"title": title, "location": kwargs.get("location")})
        return []

    run_id = start_run(conn, user)
    execute(conn, user, run_id, _CONFIG, [resume], _PROFILE,
            scrapers={"LinkedIn": li, "Remote boards": bd})

    # LinkedIn's un-prefixed title is the local lane, and only that.
    assert [c["location"] for c in linkedin
            if c["title"] == "BI Developer"] == [_PROFILE["location"]]
    # Its mode lane asks a worldwide question.
    assert [c["location"] for c in linkedin
            if c["title"] == "remote BI Developer"] == ["Worldwide"]
    # And the boards are borderless: worldwide, once.
    assert [c["location"] for c in boards] == ["Worldwide"]


def test_an_onsite_only_profile_never_calls_the_remote_boards(conn, user,
                                                             resume):
    """The boards stamp every row remote, so an onsite-only user would
    have all of them dropped or flagged - after paying for the slowest
    source in the run."""
    profile = {**_PROFILE, "work_modes": ["onsite"]}
    called = []

    def boards(*args, **kwargs):
        called.append(args)
        return []

    run_id = start_run(conn, user)
    execute(conn, user, run_id, _CONFIG, [resume], profile,
            scrapers={"LinkedIn": lambda *a, **k: [], "Remote boards": boards})
    assert called == []


def test_a_board_row_gets_its_reach_judged():
    """The reach field is the only eligibility evidence that has ever
    worked. Verbatim from run 6, on a profile whose country is in it."""
    from src.run_core import _apply_scope

    vocab = {
        "location_scope": {"worldwide": ["anywhere in the world"]},
        "eligibility": {"countries": {"am": ["armenia"], "pl": ["poland"]},
                        "regions": []},
    }
    jobs = [
        {"title": "Analytics Engineer", "source_board": "himalayas",
         "location": "Armenia, Cyprus, Georgia, Kazakhstan, Poland"},
        {"title": "Data Analyst", "source_board": "jobicy",
         "location": "Poland"},
        {"title": "Data Engineer", "platform": "LinkedIn",
         "location": "Yerevan, Armenia"},
    ]
    _apply_scope(jobs, vocab, {"country": "am"})

    assert jobs[0]["location_scope"] == "open"
    assert jobs[1]["location_scope"] == "closed"
    # A LinkedIn location is a place, not a reach statement. Judging it
    # would manufacture the fake evidence rule 6a exists to stop.
    assert "location_scope" not in jobs[2]


def test_the_scope_reaches_the_store(conn, user, resume):
    board_job = {**_job("https://x/scope1"), "platform": "Himalayas",
                 "source_board": "himalayas",
                 "location": "Anywhere in the World"}
    run_id = start_run(conn, user)
    execute(conn, user, run_id, _CONFIG, [resume], _PROFILE,
            scrapers=_scrapers(remote_boards_jobs=[board_job]))

    row = conn.execute(
        "SELECT location_scope FROM role WHERE url = ?",
        ("https://x/scope1",)).fetchone()
    assert row["location_scope"] == "open"


def test_the_run_row_records_which_boards_returned_rows(conn, user, resume):
    """Four of the aggregator's ten boards answered in run 6 and nothing
    noticed, because 133 rows arrived from those four."""
    rows = [{**_job("https://x/b1"), "source_board": "himalayas"},
            {**_job("https://x/b2", company="Other"),
             "source_board": "jobicy"}]
    run_id = start_run(conn, user)
    execute(conn, user, run_id, _CONFIG, [resume], _PROFILE,
            scrapers=_scrapers(remote_boards_jobs=rows))

    assert get_run(conn, run_id)["boards"] == ["himalayas", "jobicy"]
