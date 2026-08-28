"""Tests for src/tracker/dedup.py.

URL shapes here are taken from real rows in job_tracker.xlsx.
"""
import pytest

from src.tracker.dedup import dedupe, fingerprint, normalize_url


def _job(**kw):
    base = {"title": "Analytics Engineer", "company": "Acme",
            "location": "Remote, US", "platform": "LinkedIn",
            "url": "https://example.com/j1", "description": ""}
    return {**base, **kw}


# ── URL normalization ─────────────────────────────────────────────────────────

def test_tracking_params_are_stripped():
    assert (normalize_url("https://jobs.lever.co/fresha/9f05?lever-source=Indeed")
            == normalize_url("https://jobs.lever.co/fresha/9f05"))


def test_utm_params_are_stripped():
    assert (normalize_url("https://thorne.pinpointhq.com/postings/9bd?utm_medium=job_board&utm_source=indeed")
            == normalize_url("https://thorne.pinpointhq.com/postings/9bd"))


def test_identity_params_are_preserved():
    """gh_jid/id identify the posting — stripping them would merge all jobs."""
    a = normalize_url("https://myome.com/about-us/careers?gh_jid=4259954009")
    b = normalize_url("https://myome.com/about-us/careers?gh_jid=9999999999")
    assert a != b


def test_identity_param_survives_alongside_tracking_param():
    kept = normalize_url("https://boards.greenhouse.io/gp/jobs/6008?gh_jid=6008&utm_source=indeed")
    assert "gh_jid=6008" in kept
    assert "utm_source" not in kept


def test_linkedin_country_subdomains_unify():
    """The same posting is mirrored across country subdomains."""
    a = normalize_url("https://ca.linkedin.com/jobs/view/senior-analytics-engineer-at-jobgether-4419018363")
    b = normalize_url("https://www.linkedin.com/jobs/view/senior-analytics-engineer-at-jobgether-4419018363")
    assert a == b


def test_different_linkedin_postings_stay_distinct():
    a = normalize_url("https://ca.linkedin.com/jobs/view/senior-analytics-engineer-at-jobgether-4419018363")
    b = normalize_url("https://www.linkedin.com/jobs/view/senior-analytics-engineer-at-jobgether-4419030871")
    assert a != b


def test_scheme_and_trailing_slash_normalized():
    assert (normalize_url("http://pearson.jobs/honolulu-hi/lead-specialist/job/")
            == normalize_url("https://pearson.jobs/honolulu-hi/lead-specialist/job"))


def test_empty_url_is_safe():
    assert normalize_url("") == ""


# ── Fingerprinting ────────────────────────────────────────────────────────────

def test_fingerprint_ignores_case_and_punctuation():
    assert (fingerprint(_job(company="Acme, Inc.", title="Analytics Engineer"))
            == fingerprint(_job(company="acme inc", title="analytics  engineer")))


def test_fingerprint_ignores_location():
    """Remote roles are mirrored per-country; location must not split them."""
    assert (fingerprint(_job(location="United Kingdom"))
            == fingerprint(_job(location="United States")))


def test_fingerprint_separates_different_titles():
    assert fingerprint(_job(title="Data Engineer")) != fingerprint(_job())


# ── Dedupe ────────────────────────────────────────────────────────────────────

def test_exact_duplicate_within_batch_dropped():
    jobs = [_job(), _job()]
    assert len(dedupe(jobs)) == 1


def test_cross_platform_duplicate_dropped():
    """Same role scraped from both boards under different URLs."""
    jobs = [_job(platform="Indeed", url="https://indeed.com/viewjob?jk=abc"),
            _job(platform="LinkedIn", url="https://www.linkedin.com/jobs/view/ae-at-acme-123")]
    assert len(dedupe(jobs)) == 1


def test_distinct_jobs_are_kept():
    jobs = [_job(title="Analytics Engineer", url="https://example.com/a"),
            _job(title="Data Engineer", url="https://example.com/b"),
            _job(company="Globex", url="https://example.com/c")]
    assert len(dedupe(jobs)) == 3


def test_job_already_in_tracker_dropped_by_url():
    jobs = [_job(url="https://jobs.lever.co/fresha/9f05?lever-source=Indeed")]
    existing = ["https://jobs.lever.co/fresha/9f05"]
    assert dedupe(jobs, existing_urls=existing) == []


def test_job_already_in_tracker_dropped_by_fingerprint():
    jobs = [_job(url="https://example.com/brand-new-url")]
    existing_rows = [{"Company": "Acme", "Job Title": "Analytics Engineer"}]
    assert dedupe(jobs, existing_rows=existing_rows) == []


def test_duplicate_with_description_wins():
    """Scoring depends on the description, so keep the richer copy."""
    jobs = [_job(url="https://example.com/a", description=""),
            _job(url="https://example.com/b", description="We use dbt.")]
    kept = dedupe(jobs)
    assert len(kept) == 1
    assert kept[0]["description"] == "We use dbt."


def test_jobs_without_urls_are_dropped():
    assert dedupe([_job(url="")]) == []


def test_a_collapse_keeps_the_challengers_lane_evidence():
    """The mode lanes run last, so their copy is always the challenger.

    Lane membership is the only work-mode evidence a silent posting has,
    and dropping the challenger wholesale threw it away for exactly the
    postings the lane exists to serve.
    """
    incumbent = {"url": "https://x/1", "company": "Acme",
                 "title": "Data Analyst", "description": "body"}
    challenger = {"url": "https://x/1?src=lane", "company": "Acme",
                  "title": "Data Analyst", "description": "body",
                  "_lane_mode": "remote"}

    kept = dedupe([incumbent, challenger])

    assert len(kept) == 1
    assert kept[0]["_lane_mode"] == "remote"


def test_a_collapse_does_not_invent_lane_evidence():
    incumbent = {"url": "https://x/2", "company": "Acme",
                 "title": "Data Engineer", "description": "body"}
    challenger = {"url": "https://x/2?src=other", "company": "Acme",
                  "title": "Data Engineer", "description": "body"}

    kept = dedupe([incumbent, challenger])

    assert "_lane_mode" not in kept[0]
