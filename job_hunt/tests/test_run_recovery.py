"""Boot recovery for runs a dead process left RUNNING."""
import pytest

from src.app import create_app
from src.store.db import connect
from src.store.ingest import ensure_user
from src.store.runs import get_run, start_run
from src.store.schema import init_db


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "recovery.db"
    conn = connect(path)
    init_db(conn)
    ensure_user(conn, "default")
    conn.close()
    return path


def _orphan(db):
    conn = connect(db)
    try:
        return start_run(conn, ensure_user(conn, "default"))
    finally:
        conn.close()


def _read(db, run_id):
    conn = connect(db)
    try:
        return get_run(conn, run_id)
    finally:
        conn.close()


def test_creating_the_app_clears_a_run_left_running(db, tmp_path):
    orphan = _orphan(db)
    create_app(db_path=db, user_name="default", data_root=tmp_path / "data")

    assert _read(db, orphan)["status"] == "FAILED"


def test_the_cleared_run_says_why(db, tmp_path):
    orphan = _orphan(db)
    create_app(db_path=db, user_name="default", data_root=tmp_path / "data")

    assert "interrupted" in _read(db, orphan)["error"].lower()


def test_a_finished_run_is_untouched_at_boot(db, tmp_path):
    from src.store.runs import finish_run

    done = _orphan(db)
    conn = connect(db)
    try:
        finish_run(conn, done, scraped=5, kept=3)
    finally:
        conn.close()

    create_app(db_path=db, user_name="default", data_root=tmp_path / "data")
    assert _read(db, done)["status"] == "OK"


def test_an_ordinary_request_does_not_kill_a_live_run(db, tmp_path):
    """Recovery belongs to boot. _conn() runs init_db on every request, so
    putting this there would fail the run currently in flight."""
    app = create_app(db_path=db, user_name="default",
                     data_root=tmp_path / "data")
    app.config.update(TESTING=True)
    client = app.test_client()

    live = _orphan(db)                 # starts after boot, so it is real
    client.get("/")

    assert _read(db, live)["status"] == "RUNNING"
