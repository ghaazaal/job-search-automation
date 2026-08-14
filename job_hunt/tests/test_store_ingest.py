"""Tests for src/store/ingest.py — writing a scrape run into the store."""
import pytest

from src.store.db import connect
from src.store.schema import init_db
from src.store.ingest import ensure_user, upsert_jobs
from src.store.runs import start_run, finish_run


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "test.db")
    init_db(c)
    return c


def _job(url="https://x/1", company="Acme", title="Analytics Engineer", **kw):
    base = {"company": company, "title": title, "url": url,
            "location": "Remote, US", "salary": "", "platform": "LinkedIn",
            "date": "2026-08-08", "description": "We use dbt.",
            "description_captured": True, "match_score": 9,
            "band": "STRONG FIT", "reason": "matches dbt",
            "matched": ["dbt"], "gaps": ["snowflake"]}
    return {**base, **kw}


def test_ensure_user_is_idempotent(conn):
    a = ensure_user(conn, "Ghazal")
    b = ensure_user(conn, "Ghazal")
    assert a == b
    assert conn.execute("SELECT COUNT(*) c FROM user").fetchone()["c"] == 1


def test_run_starts_as_running_and_finishes_ok(conn):
    u = ensure_user(conn, "Ghazal")
    run_id = start_run(conn, u)
    assert conn.execute("SELECT status FROM run WHERE id=?",
                        (run_id,)).fetchone()["status"] == "RUNNING"
    finish_run(conn, run_id, scraped=10, kept=8)
    row = conn.execute("SELECT * FROM run WHERE id=?", (run_id,)).fetchone()
    assert row["status"] == "OK" and row["kept"] == 8 and row["finished_at"]


def test_run_can_finish_as_failed(conn):
    u = ensure_user(conn, "Ghazal")
    run_id = start_run(conn, u)
    finish_run(conn, run_id, scraped=5, kept=0, ok=False)
    row = conn.execute("SELECT * FROM run WHERE id=?", (run_id,)).fetchone()
    assert row["status"] == "FAILED" and row["finished_at"]


def test_jobs_create_companies_and_roles(conn):
    u = ensure_user(conn, "Ghazal")
    run_id = start_run(conn, u)
    upsert_jobs(conn, u, run_id, [_job()])
    assert conn.execute("SELECT COUNT(*) c FROM company").fetchone()["c"] == 1
    assert conn.execute("SELECT COUNT(*) c FROM role").fetchone()["c"] == 1


def test_two_roles_at_one_company_share_it(conn):
    u = ensure_user(conn, "Ghazal")
    run_id = start_run(conn, u)
    upsert_jobs(conn, u, run_id, [_job(url="https://x/1"),
                                  _job(url="https://x/2", title="Data Engineer")])
    assert conn.execute("SELECT COUNT(*) c FROM company").fetchone()["c"] == 1
    assert conn.execute("SELECT COUNT(*) c FROM role").fetchone()["c"] == 2


def test_reseeing_a_role_updates_last_seen_not_first_seen(conn):
    u = ensure_user(conn, "Ghazal")
    first = start_run(conn, u)
    upsert_jobs(conn, u, first, [_job()])
    second = start_run(conn, u)
    upsert_jobs(conn, u, second, [_job()])
    row = conn.execute("SELECT * FROM role").fetchone()
    assert row["first_seen_run_id"] == first
    assert row["last_seen_run_id"] == second
    assert conn.execute("SELECT COUNT(*) c FROM role").fetchone()["c"] == 1


def test_tracking_urls_do_not_create_a_second_role(conn):
    """Dedup is a database guarantee via url_normalised."""
    u = ensure_user(conn, "Ghazal")
    run_id = start_run(conn, u)
    upsert_jobs(conn, u, run_id, [_job(url="https://jobs.lever.co/a/1")])
    upsert_jobs(conn, u, run_id,
                [_job(url="https://jobs.lever.co/a/1?lever-source=Indeed")])
    assert conn.execute("SELECT COUNT(*) c FROM role").fetchone()["c"] == 1


def test_evidence_is_stored(conn):
    u = ensure_user(conn, "Ghazal")
    run_id = start_run(conn, u)
    upsert_jobs(conn, u, run_id, [_job()])
    row = conn.execute("SELECT * FROM role").fetchone()
    assert row["band"] == "STRONG FIT"
    assert row["matched"] == '["dbt"]'
    assert row["description_captured"] == 1


def test_uncaptured_description_is_persisted_as_such(conn):
    u = ensure_user(conn, "Ghazal")
    run_id = start_run(conn, u)
    upsert_jobs(conn, u, run_id,
                [_job(description="", description_captured=False, band=None)])
    row = conn.execute("SELECT * FROM role").fetchone()
    assert row["description_captured"] == 0
    assert row["band"] is None


def test_ingest_never_writes_tracking_tables(conn):
    u = ensure_user(conn, "Ghazal")
    run_id = start_run(conn, u)
    upsert_jobs(conn, u, run_id, [_job()])
    assert conn.execute("SELECT COUNT(*) c FROM application").fetchone()["c"] == 0


def test_a_failing_batch_leaves_no_partial_rows(conn):
    """Atomicity — job 2 is malformed, so neither job lands."""
    u = ensure_user(conn, "Ghazal")
    run_id = start_run(conn, u)
    bad = _job(url="https://x/2")
    del bad["title"]
    with pytest.raises(KeyError):
        upsert_jobs(conn, u, run_id, [_job(url="https://x/1"), bad])
    assert conn.execute("SELECT COUNT(*) c FROM role").fetchone()["c"] == 0


def _resume_row(conn, user_id, label="ae", sha="sha-ae"):
    from src.store.profile import create_resume
    return create_resume(conn, user_id, label=label, orig_filename="cv.pdf",
                         sha256=sha, stored_path=f"resumes/{user_id}/{sha}.pdf",
                         extracted_text="dbt and Airflow")


def test_the_winning_resume_is_recorded_on_the_role(conn):
    user_id = ensure_user(conn, "G")
    resume_id = _resume_row(conn, user_id)
    run_id = start_run(conn, user_id)
    upsert_jobs(conn, user_id, run_id,
                [_job(url="https://x/attributed", resume_id=resume_id)])
    stored = conn.execute(
        "SELECT resume_id FROM role WHERE url = ?",
        ("https://x/attributed",)).fetchone()["resume_id"]
    assert stored == resume_id


def test_a_job_scored_without_a_resume_stores_null(conn):
    """Roles ingested before Ship 2 have no attribution and must not break."""
    user_id = ensure_user(conn, "G")
    run_id = start_run(conn, user_id)
    upsert_jobs(conn, user_id, run_id, [_job(url="https://x/plain")])
    stored = conn.execute(
        "SELECT resume_id FROM role WHERE url = ?",
        ("https://x/plain",)).fetchone()["resume_id"]
    assert stored is None


def test_re_running_a_scrape_updates_the_attribution(conn):
    """A second resume can win a posting the first one won last week."""
    user_id = ensure_user(conn, "G")
    first = _resume_row(conn, user_id, label="ae", sha="sha-ae")
    second = _resume_row(conn, user_id, label="bi", sha="sha-bi")
    run_one = start_run(conn, user_id)
    upsert_jobs(conn, user_id, run_one,
                [_job(url="https://x/moves", resume_id=first)])
    run_two = start_run(conn, user_id)
    upsert_jobs(conn, user_id, run_two,
                [_job(url="https://x/moves", resume_id=second)])
    stored = conn.execute(
        "SELECT resume_id FROM role WHERE url = ?",
        ("https://x/moves",)).fetchone()["resume_id"]
    assert stored == second
