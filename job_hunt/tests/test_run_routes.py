"""Tests for POST /api/runs and GET /api/runs/<id>.

The runner is injected through create_app so no test scrapes anything.
"""
import json

import pytest

from src.app import create_app
from src.store.db import connect
from src.store.ingest import ensure_user
from src.store.profile import create_resume, set_profile, update_resume
from src.store.runs import finish_run, get_run, start_run
from src.store.schema import init_db


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "runs.db"
    conn = connect(path)
    init_db(conn)
    user_id = ensure_user(conn, "default")
    resume_id = create_resume(conn, user_id, label="bi",
                              orig_filename="bi.pdf", sha256="abc",
                              stored_path="resumes/1/abc.pdf",
                              extracted_text="Power BI")
    update_resume(conn, user_id, resume_id, label="bi",
                  target_roles=[{"title": "BI Developer", "aliases": []}],
                  skills=[{"name": "Power BI", "tier": "core", "aliases": []}],
                  seniority="senior")
    set_profile(conn, user_id, location="Toronto, ON", country="ca",
                work_modes=["remote"])
    conn.close()
    return path


def _client(db, tmp_path, runner=None, token="apify_test"):
    app = create_app(db_path=db, user_name="default",
                     data_root=tmp_path / "data",
                     runner=runner or (lambda *a, **k: None),
                     run_in_thread=False)
    app.config.update(TESTING=True)
    return app.test_client()


@pytest.fixture
def client(db, tmp_path, monkeypatch):
    monkeypatch.setenv("APIFY_TOKEN", "apify_test")
    return _client(db, tmp_path)


def _user_id(db):
    conn = connect(db)
    try:
        return ensure_user(conn, "default")
    finally:
        conn.close()


def test_starting_a_run_returns_its_id(client):
    response = client.post("/api/runs")
    assert response.status_code == 201
    assert isinstance(response.get_json()["run_id"], int)


def test_the_run_row_exists_before_the_response_returns(client, db):
    run_id = client.post("/api/runs").get_json()["run_id"]
    conn = connect(db)
    try:
        assert get_run(conn, run_id) is not None
    finally:
        conn.close()


def test_a_second_run_while_one_is_going_is_refused(db, tmp_path, monkeypatch):
    """Needs the first run to genuinely still be RUNNING when the second
    POST fires — the synchronous run_in_thread=False path can't produce
    that state, since work() always runs to completion before returning."""
    import threading

    monkeypatch.setenv("APIFY_TOKEN", "apify_test")
    released = threading.Event()

    def blocking_runner(conn, user_id, run_id, on_progress):
        released.wait(timeout=5)

    app = create_app(db_path=db, user_name="default",
                     data_root=tmp_path / "data",
                     runner=blocking_runner, run_in_thread=True)
    app.config.update(TESTING=True)
    client = app.test_client()

    first = client.post("/api/runs")
    assert first.status_code == 201

    response = client.post("/api/runs")
    assert response.status_code == 409
    assert "already" in response.get_json()["error"].lower()

    released.set()


def test_a_run_can_start_once_the_previous_one_finished(client, db):
    run_id = client.post("/api/runs").get_json()["run_id"]
    conn = connect(db)
    try:
        finish_run(conn, run_id, scraped=1, kept=1)
    finally:
        conn.close()

    assert client.post("/api/runs").status_code == 201


def test_an_abandoned_run_is_superseded_rather_than_blocking(db, tmp_path,
                                                              monkeypatch):
    """A worker killed without marking FAILED must not lock the user out.

    Needs the stale run to still be RUNNING when superseded, which requires
    real threading — see the note on the previous test."""
    import threading

    monkeypatch.setenv("APIFY_TOKEN", "apify_test")
    released = threading.Event()

    def blocking_runner(conn, user_id, run_id, on_progress):
        released.wait(timeout=5)

    app = create_app(db_path=db, user_name="default",
                     data_root=tmp_path / "data",
                     runner=blocking_runner, run_in_thread=True)
    app.config.update(TESTING=True)
    client = app.test_client()

    stale = client.post("/api/runs").get_json()["run_id"]
    conn = connect(db)
    try:
        conn.execute("UPDATE run SET started_at = '2020-01-01T00:00:00+00:00'"
                     " WHERE id = ?", (stale,))
    finally:
        conn.close()

    response = client.post("/api/runs")
    assert response.status_code == 201

    conn = connect(db)
    try:
        assert get_run(conn, stale)["status"] == "FAILED"
    finally:
        conn.close()

    released.set()


def test_starting_a_run_without_target_roles_is_refused(tmp_path, monkeypatch):
    monkeypatch.setenv("APIFY_TOKEN", "apify_test")
    path = tmp_path / "no_roles.db"
    conn = connect(path)
    init_db(conn)
    user_id = ensure_user(conn, "default")
    resume_id = create_resume(conn, user_id, label="bi",
                              orig_filename="bi.pdf", sha256="abc",
                              stored_path="resumes/1/abc.pdf",
                              extracted_text="Power BI")
    update_resume(conn, user_id, resume_id, label="bi", target_roles=[],
                  skills=[{"name": "Power BI", "tier": "core", "aliases": []}],
                  seniority="senior")
    conn.close()

    response = _client(path, tmp_path).post("/api/runs")
    assert response.status_code == 400
    assert "target role" in response.get_json()["error"].lower()


def test_starting_a_run_without_a_resume_is_refused(tmp_path, monkeypatch):
    monkeypatch.setenv("APIFY_TOKEN", "apify_test")
    path = tmp_path / "empty.db"
    conn = connect(path)
    init_db(conn)
    ensure_user(conn, "default")
    conn.close()

    response = _client(path, tmp_path).post("/api/runs")
    assert response.status_code == 400
    assert "resume" in response.get_json()["error"].lower()


def test_a_refused_run_leaves_no_row_behind(tmp_path, monkeypatch):
    monkeypatch.setenv("APIFY_TOKEN", "apify_test")
    path = tmp_path / "empty.db"
    conn = connect(path)
    init_db(conn)
    ensure_user(conn, "default")
    conn.close()

    _client(path, tmp_path).post("/api/runs")

    conn = connect(path)
    try:
        assert conn.execute("SELECT COUNT(*) AS n FROM run").fetchone()["n"] == 0
    finally:
        conn.close()


def test_starting_a_run_without_an_apify_token_is_refused(db, tmp_path,
                                                          monkeypatch):
    monkeypatch.delenv("APIFY_TOKEN", raising=False)
    response = _client(db, tmp_path).post("/api/runs")

    assert response.status_code == 400
    assert "APIFY_TOKEN" in response.get_json()["error"]


def test_polling_reports_status_stage_and_progress(db, tmp_path, monkeypatch):
    """Needs the run to still be RUNNING with real progress when polled —
    same reason as the previous two tests. This version also exercises the
    real on_progress wiring end-to-end (route -> worker -> set_progress)
    rather than poking the DB directly, which is a strictly better test."""
    import threading

    monkeypatch.setenv("APIFY_TOKEN", "apify_test")
    reported = threading.Event()
    released = threading.Event()

    def blocking_runner(conn, user_id, run_id, on_progress):
        on_progress({"stage": "scraping", "steps": [], "scraped": 12})
        reported.set()
        released.wait(timeout=5)

    app = create_app(db_path=db, user_name="default",
                     data_root=tmp_path / "data",
                     runner=blocking_runner, run_in_thread=True)
    app.config.update(TESTING=True)
    client = app.test_client()

    run_id = client.post("/api/runs").get_json()["run_id"]
    assert reported.wait(timeout=5), "the runner should have reported progress"

    body = client.get(f"/api/runs/{run_id}").get_json()
    assert body["status"] == "RUNNING"
    assert body["stage"] == "scraping"
    assert body["progress"]["scraped"] == 12

    released.set()


def test_polling_an_unknown_run_is_a_404(client):
    assert client.get("/api/runs/9999").status_code == 404


def test_polling_reports_the_error_of_a_failed_run(client, db):
    run_id = client.post("/api/runs").get_json()["run_id"]
    conn = connect(db)
    try:
        from src.store.runs import fail_run
        fail_run(conn, run_id, "Apify returned 401")
    finally:
        conn.close()

    body = client.get(f"/api/runs/{run_id}").get_json()
    assert body["status"] == "FAILED"
    assert body["error"] == "Apify returned 401"


def test_no_score_or_percentage_leaks_from_the_poll_endpoint(client, db):
    run_id = client.post("/api/runs").get_json()["run_id"]
    body = json.dumps(client.get(f"/api/runs/{run_id}").get_json())

    assert "match_score" not in body
    assert "%" not in body


def test_the_progress_screen_renders_for_a_real_run(client):
    run_id = client.post("/api/runs").get_json()["run_id"]
    response = client.get(f"/searching/{run_id}")

    assert response.status_code == 200
    assert b"searching" in response.data.lower()


def test_the_progress_screen_polls_its_own_run(client):
    run_id = client.post("/api/runs").get_json()["run_id"]
    body = client.get(f"/searching/{run_id}").get_data(as_text=True)

    assert f"/api/runs/{run_id}" in body


def test_the_progress_screen_404s_for_an_unknown_run(client):
    assert client.get("/searching/9999").status_code == 404


def test_starting_a_run_before_setup_is_complete_is_refused(tmp_path, monkeypatch):
    """Skipping the location step on the confirm screen must not let a
    search start with no location on file."""
    monkeypatch.setenv("APIFY_TOKEN", "apify_test")
    path = tmp_path / "no_profile.db"
    conn = connect(path)
    init_db(conn)
    user_id = ensure_user(conn, "default")
    resume_id = create_resume(conn, user_id, label="bi",
                              orig_filename="bi.pdf", sha256="abc",
                              stored_path="resumes/1/abc.pdf",
                              extracted_text="Power BI")
    update_resume(conn, user_id, resume_id, label="bi",
                  target_roles=[{"title": "BI Developer", "aliases": []}],
                  skills=[{"name": "Power BI", "tier": "core", "aliases": []}],
                  seniority="senior")
    conn.close()  # deliberately no set_profile call — setup_complete stays 0

    response = _client(path, tmp_path).post("/api/runs")
    assert response.status_code == 400
    assert "setup" in response.get_json()["error"].lower()
