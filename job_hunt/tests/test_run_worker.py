"""Tests for src/run_worker.py.

The runner is injected so every test drives the work synchronously. Threading
is one thin wrapper and is tested only for the property that matters: that it
returns before the work is done.
"""
import threading

import pytest

from src.run_worker import run_in_background, work
from src.store.db import connect
from src.store.ingest import ensure_user
from src.store.runs import get_run, start_run
from src.store.schema import init_db


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "worker.db"
    conn = connect(path)
    init_db(conn)
    ensure_user(conn, "default")
    conn.close()
    return path


@pytest.fixture
def user_and_run(db):
    conn = connect(db)
    user_id = ensure_user(conn, "default")
    run_id = start_run(conn, user_id)
    conn.close()
    return user_id, run_id


def _read(db, run_id):
    conn = connect(db)
    try:
        return get_run(conn, run_id)
    finally:
        conn.close()


def test_a_successful_runner_leaves_the_run_alone(db, user_and_run):
    """execute() finishes the run itself; the worker must not overwrite that."""
    user_id, run_id = user_and_run

    def runner(conn, user_id_, run_id_, on_progress):
        from src.store.runs import finish_run
        finish_run(conn, run_id_, scraped=3, kept=2)

    work(db, user_id, run_id, runner)

    stored = _read(db, run_id)
    assert stored["status"] == "OK"
    assert (stored["scraped"], stored["kept"]) == (3, 2)


def test_progress_from_the_runner_reaches_the_row(db, user_and_run):
    user_id, run_id = user_and_run

    def runner(conn, user_id_, run_id_, on_progress):
        on_progress({"stage": "scraping", "steps": [], "scraped": 7})
        from src.store.runs import finish_run
        finish_run(conn, run_id_, scraped=7, kept=0)

    work(db, user_id, run_id, runner)

    stored = _read(db, run_id)
    assert stored["stage"] == "scraping"
    assert stored["progress"]["scraped"] == 7


def test_a_raising_runner_marks_the_run_failed(db, user_and_run):
    user_id, run_id = user_and_run

    def runner(conn, user_id_, run_id_, on_progress):
        raise RuntimeError("actor rejected the input")

    work(db, user_id, run_id, runner)

    stored = _read(db, run_id)
    assert stored["status"] == "FAILED"
    assert "actor rejected the input" in stored["error"]


def test_a_raising_runner_never_leaves_the_run_running(db, user_and_run):
    """This is the lockout: a RUNNING row blocks every future run."""
    user_id, run_id = user_and_run

    def runner(conn, user_id_, run_id_, on_progress):
        raise RuntimeError("boom")

    work(db, user_id, run_id, runner)
    assert _read(db, run_id)["status"] != "RUNNING"


def test_a_runner_that_finishes_then_raises_does_not_overwrite_ok(db, user_and_run):
    """Fix for: the except branch used to fail_run unconditionally, even if
    the runner had already finished the run before raising afterward."""
    user_id, run_id = user_and_run

    def runner(conn, user_id_, run_id_, on_progress):
        from src.store.runs import finish_run
        finish_run(conn, run_id_, scraped=5, kept=3)
        raise RuntimeError("cleanup code blew up after the run was done")

    work(db, user_id, run_id, runner)

    stored = _read(db, run_id)
    assert stored["status"] == "OK"
    assert (stored["scraped"], stored["kept"]) == (5, 3)


def test_the_worker_opens_its_own_connection(db, user_and_run):
    """Connections are not shareable across threads."""
    import sqlite3

    user_id, run_id = user_and_run
    handed = {}

    def runner(conn, user_id_, run_id_, on_progress):
        handed["conn"] = conn
        handed["row_count"] = conn.execute(
            "SELECT COUNT(*) AS n FROM run").fetchone()["n"]
        from src.store.runs import finish_run
        finish_run(conn, run_id_, scraped=0, kept=0)

    work(db, user_id, run_id, runner)
    assert isinstance(handed["conn"], sqlite3.Connection)
    assert handed["row_count"] >= 1


def test_run_in_background_returns_before_the_work_finishes(db, user_and_run):
    user_id, run_id = user_and_run
    released = threading.Event()
    started = threading.Event()

    def runner(conn, user_id_, run_id_, on_progress):
        started.set()
        released.wait(timeout=5)
        from src.store.runs import finish_run
        finish_run(conn, run_id_, scraped=0, kept=0)

    thread = run_in_background(db, user_id, run_id, runner)
    assert started.wait(timeout=5), "the worker should have started"
    assert _read(db, run_id)["status"] == "RUNNING"

    released.set()
    thread.join(timeout=5)
    assert _read(db, run_id)["status"] == "OK"


def test_the_background_thread_does_not_hold_the_process_open(db, user_and_run):
    user_id, run_id = user_and_run

    def runner(conn, user_id_, run_id_, on_progress):
        from src.store.runs import finish_run
        finish_run(conn, run_id_, scraped=0, kept=0)

    thread = run_in_background(db, user_id, run_id, runner)
    assert thread.daemon is True
    thread.join(timeout=5)
