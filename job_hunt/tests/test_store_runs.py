"""Tests for src/store/runs.py — the run lifecycle.

These cover what the poll endpoint and the boot recovery depend on. Time is
injected wherever staleness matters so no test sleeps.
"""
from datetime import datetime, timedelta, timezone

import pytest

from src.store import runs
from src.store.db import connect
from src.store.ingest import ensure_user
from src.store.schema import init_db


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "runs.db")
    init_db(c)
    yield c
    c.close()


@pytest.fixture
def user(conn):
    return ensure_user(conn, "default")


def test_a_new_run_is_running(conn, user):
    run_id = runs.start_run(conn, user)
    assert runs.get_run(conn, run_id)["status"] == "RUNNING"


def test_progress_survives_a_round_trip(conn, user):
    run_id = runs.start_run(conn, user)
    payload = {"steps": [{"source": "Indeed", "role": "BI Developer",
                          "state": "done", "found": 50}], "scraped": 50}
    runs.set_progress(conn, run_id, "scraping", payload)

    stored = runs.get_run(conn, run_id)
    assert stored["stage"] == "scraping"
    assert stored["progress"] == payload


def test_progress_defaults_to_empty_before_anything_is_written(conn, user):
    run_id = runs.start_run(conn, user)
    assert runs.get_run(conn, run_id)["progress"] == {}


def test_unreadable_progress_does_not_crash_the_poll(conn, user):
    """A half-written row must not take the screen down with it."""
    run_id = runs.start_run(conn, user)
    conn.execute("UPDATE run SET progress = 'not json' WHERE id = ?", (run_id,))
    assert runs.get_run(conn, run_id)["progress"] == {}


def test_finishing_marks_it_ok_with_its_counts(conn, user):
    run_id = runs.start_run(conn, user)
    runs.finish_run(conn, run_id, scraped=300, kept=178)

    stored = runs.get_run(conn, run_id)
    assert stored["status"] == "OK"
    assert (stored["scraped"], stored["kept"]) == (300, 178)


def test_failing_records_the_message(conn, user):
    run_id = runs.start_run(conn, user)
    runs.fail_run(conn, run_id, "Apify returned 401")

    stored = runs.get_run(conn, run_id)
    assert stored["status"] == "FAILED"
    assert stored["error"] == "Apify returned 401"


def test_a_very_long_error_is_truncated_not_dropped(conn, user):
    run_id = runs.start_run(conn, user)
    runs.fail_run(conn, run_id, "x" * 5000)
    assert 0 < len(runs.get_run(conn, run_id)["error"]) <= 500


def test_get_run_returns_none_for_an_unknown_id(conn):
    assert runs.get_run(conn, 9999) is None


def test_active_run_finds_the_running_one(conn, user):
    run_id = runs.start_run(conn, user)
    assert runs.active_run(conn, user)["id"] == run_id


def test_active_run_ignores_finished_runs(conn, user):
    run_id = runs.start_run(conn, user)
    runs.finish_run(conn, run_id, scraped=1, kept=1)
    assert runs.active_run(conn, user) is None


def test_a_fresh_run_is_not_stale():
    now = datetime.now(timezone.utc)
    assert runs.is_stale(now.isoformat(timespec="seconds"), now=now) is False


def test_a_run_older_than_the_window_is_stale():
    now = datetime.now(timezone.utc)
    old = (now - timedelta(minutes=runs.STALE_AFTER_MINUTES + 1))
    assert runs.is_stale(old.isoformat(timespec="seconds"), now=now) is True


def test_an_unparseable_start_time_counts_as_stale():
    """Better to let the user start a new run than to lock them out."""
    assert runs.is_stale("not a timestamp") is True


def test_clear_running_recovers_every_orphan(conn, user):
    first = runs.start_run(conn, user)
    second = runs.start_run(conn, user)
    cleared = runs.clear_running(conn, "interrupted")

    assert cleared == 2
    assert runs.get_run(conn, first)["status"] == "FAILED"
    assert runs.get_run(conn, second)["status"] == "FAILED"


def test_clear_running_leaves_finished_runs_alone(conn, user):
    done = runs.start_run(conn, user)
    runs.finish_run(conn, done, scraped=1, kept=1)
    runs.clear_running(conn, "interrupted")
    assert runs.get_run(conn, done)["status"] == "OK"


def test_latest_ok_run_ignores_a_run_still_going(conn, user):
    """The map keys 'what is new' off this. An in-flight run must not count."""
    done = runs.start_run(conn, user)
    runs.finish_run(conn, done, scraped=1, kept=1)
    runs.start_run(conn, user)          # still RUNNING

    assert runs.latest_ok_run(conn, user) == done


def test_latest_ok_run_is_none_before_any_run_succeeds(conn, user):
    runs.start_run(conn, user)
    assert runs.latest_ok_run(conn, user) is None


def test_finishing_records_the_dropped_count(conn, user):
    run_id = runs.start_run(conn, user)
    runs.finish_run(conn, run_id, scraped=5, kept=3, dropped=2)

    assert runs.get_run(conn, run_id)["dropped"] == 2


def test_dropped_defaults_to_zero_when_not_given(conn, user):
    run_id = runs.start_run(conn, user)
    runs.finish_run(conn, run_id, scraped=1, kept=1)

    assert runs.get_run(conn, run_id)["dropped"] == 0


def test_finishing_records_the_offtopic_count(conn, user):
    run_id = runs.start_run(conn, user)
    runs.finish_run(conn, run_id, scraped=5, kept=3, offtopic=2)

    assert runs.get_run(conn, run_id)["offtopic"] == 2


def test_offtopic_defaults_to_zero_when_not_given(conn, user):
    run_id = runs.start_run(conn, user)
    runs.finish_run(conn, run_id, scraped=1, kept=1)

    assert runs.get_run(conn, run_id)["offtopic"] == 0


def test_the_stale_window_clears_a_realistic_run():
    """A live run marked stale invites a SECOND concurrent scrape.

    STALE_AFTER_MINUTES and the scrapers' timeouts are coupled, and
    nothing checked the relationship: Ship 7 added a source needing a
    420s floor and left the window at 15 minutes, so a healthy run would
    have been declared dead partway through. The existing staleness
    tests derive their fixture from the constant, so they passed either
    way. This one pins the invariant instead.
    """
    from src.scrapers.remote_boards import _MIN_TIMEOUT

    # Four target roles is an ordinary profile. Remote boards alone can
    # spend four full timeouts, and the other sources run alongside it,
    # so this is a floor on the worst case rather than the worst case.
    slowest_single_source = _MIN_TIMEOUT * 4
    assert runs.STALE_AFTER_MINUTES * 60 > slowest_single_source, (
        "a run can legitimately outlive the staleness window - raise "
        "STALE_AFTER_MINUTES or lower a scraper's timeout floor")
