"""What / does, depending on setup state and whether a run is going."""
import pytest

from src.app import create_app
from src.store.db import connect
from src.store.ingest import ensure_user
from src.store.profile import create_resume, set_profile, update_resume
from src.store.runs import finish_run, start_run
from src.store.schema import init_db


def _bare(tmp_path, name="bare.db"):
    path = tmp_path / name
    conn = connect(path)
    init_db(conn)
    ensure_user(conn, "default")
    conn.close()
    return path


def _ready(tmp_path, name="ready.db"):
    path = _bare(tmp_path, name)
    conn = connect(path)
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


def _client(path, tmp_path):
    app = create_app(db_path=path, user_name="default",
                     data_root=tmp_path / "data")
    app.config.update(TESTING=True)
    return app.test_client()


def test_an_unset_up_user_is_sent_to_setup(tmp_path):
    response = _client(_bare(tmp_path), tmp_path).get("/")

    assert response.status_code == 302
    assert "/setup" in response.headers["Location"]


def test_a_set_up_user_reaches_the_map(tmp_path):
    assert _client(_ready(tmp_path), tmp_path).get("/").status_code == 200


def test_a_set_up_user_with_no_roles_is_told_nothing_has_been_searched(tmp_path):
    body = _client(_ready(tmp_path), tmp_path).get("/").get_data(as_text=True)
    assert "nothing searched yet" in body.lower()


def test_the_empty_state_offers_to_start_a_search(tmp_path):
    body = _client(_ready(tmp_path), tmp_path).get("/").get_data(as_text=True)
    assert "start searching" in body.lower()


def test_the_map_offers_to_search_again(tmp_path):
    body = _client(_ready(tmp_path), tmp_path).get("/").get_data(as_text=True)
    assert "/api/runs" in body


def test_a_running_run_is_announced_on_the_map(tmp_path):
    # The client (create_app) must exist before the run is seeded: boot
    # recovery marks every RUNNING row FAILED on the assumption that no
    # worker of ours is alive yet, which is only true at real app startup —
    # seeding the run first would have the app immediately kill it.
    path = _ready(tmp_path)
    client = _client(path, tmp_path)
    conn = connect(path)
    try:
        run_id = start_run(conn, ensure_user(conn, "default"))
    finally:
        conn.close()

    body = client.get("/").get_data(as_text=True)
    assert "searching now" in body.lower()
    assert f"/searching/{run_id}" in body


def test_viewing_the_map_mid_run_does_not_mark_that_run_seen(tmp_path):
    """Otherwise every role the run is about to store files as already seen,
    and the map's new section silently empties."""
    path = _ready(tmp_path)
    client = _client(path, tmp_path)
    conn = connect(path)
    try:
        user_id = ensure_user(conn, "default")
        start_run(conn, user_id)
    finally:
        conn.close()

    client.get("/")

    conn = connect(path)
    try:
        seen = conn.execute("SELECT last_seen_run_id FROM user WHERE id = ?",
                            (user_id,)).fetchone()["last_seen_run_id"]
    finally:
        conn.close()
    assert seen in (None, 0)


def test_viewing_the_map_marks_the_last_finished_run_seen(tmp_path):
    path = _ready(tmp_path)
    conn = connect(path)
    try:
        user_id = ensure_user(conn, "default")
        done = start_run(conn, user_id)
        finish_run(conn, done, scraped=1, kept=1)
    finally:
        conn.close()

    _client(path, tmp_path).get("/")

    conn = connect(path)
    try:
        seen = conn.execute("SELECT last_seen_run_id FROM user WHERE id = ?",
                            (user_id,)).fetchone()["last_seen_run_id"]
    finally:
        conn.close()
    assert seen == done


def test_the_banner_shows_no_invented_total(tmp_path):
    path = _ready(tmp_path)
    client = _client(path, tmp_path)
    conn = connect(path)
    try:
        start_run(conn, ensure_user(conn, "default"))
    finally:
        conn.close()

    body = client.get("/").get_data(as_text=True)
    assert " of " not in body.lower().split("searching now")[1][:60]


def test_the_map_reports_what_the_last_run_hid(tmp_path):
    """The drop count is durably recorded on the run row (Task 5) but was
    never actually surfaced to a reader — this closes that loop."""
    path = _ready(tmp_path)
    conn = connect(path)
    try:
        user_id = ensure_user(conn, "default")
        done = start_run(conn, user_id)
        finish_run(conn, done, scraped=5, kept=3, dropped=2)
    finally:
        conn.close()

    body = _client(path, tmp_path).get("/").get_data(as_text=True)
    assert "HIDDEN (ON-SITE ELSEWHERE)" in body


def test_the_map_reports_what_the_last_run_rejected_as_offtopic(tmp_path):
    """The offtopic count is durably recorded on the run row and must reach
    the map the same way `dropped` does — the two are different facts and
    neither substitutes for the other."""
    path = _ready(tmp_path)
    conn = connect(path)
    try:
        user_id = ensure_user(conn, "default")
        done = start_run(conn, user_id)
        finish_run(conn, done, scraped=5, kept=3, offtopic=4)
    finally:
        conn.close()

    body = _client(path, tmp_path).get("/").get_data(as_text=True)
    assert "OFF-TOPIC (NOT A DATA ROLE)" in body
