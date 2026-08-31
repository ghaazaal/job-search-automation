"""Tests for src/store/watchlist.py — who a user watches, and what we know."""
import pytest

from src.store.db import connect
from src.store.ingest import ensure_user
from src.store.schema import init_db
from src.store import watchlist


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "wl.db")
    init_db(c)
    yield c
    c.close()


@pytest.fixture
def user(conn):
    return ensure_user(conn, "default")


def test_add_stores_identity_and_starts_unresolved(conn, user):
    wid = watchlist.add(conn, user, name="DataArt", domain="dataart.com")
    row = watchlist.get(conn, user, wid)
    assert row["company_name"] == "DataArt"
    assert row["domain"] == "dataart.com"
    assert row["resolution"] == "unresolved"
    assert row["company_fingerprint"]


def test_the_same_company_cannot_be_watched_twice(conn, user):
    watchlist.add(conn, user, name="DataArt")
    with pytest.raises(watchlist.AlreadyWatched):
        watchlist.add(conn, user, name="DataArt Inc")  # same fingerprint


def test_a_pasted_linkedin_url_resolves_immediately(conn, user):
    """A slug is the disambiguator; with it there is nothing to probe."""
    wid = watchlist.add(conn, user, name="Andersen",
                        linkedin_url="https://www.linkedin.com/company/andersenus/")
    row = watchlist.get(conn, user, wid)
    assert row["resolution"] == "linkedin"
    assert row["linkedin_slug"] == "andersenus"
    assert row["linkedin_name"] == "Andersen"


def test_remove_deletes_the_row(conn, user):
    wid = watchlist.add(conn, user, name="EPAM Systems")
    watchlist.remove(conn, user, wid)
    assert watchlist.get(conn, user, wid) is None


def test_set_resolution_records_when(conn, user):
    wid = watchlist.add(conn, user, name="GitLab", domain="gitlab.com")
    watchlist.set_resolution(conn, user, wid, "ats")
    row = watchlist.get(conn, user, wid)
    assert row["resolution"] == "ats" and row["resolved_at"]


def test_the_linkedin_invariant_is_enforced_by_the_database(conn, user):
    """resolution='linkedin' with neither name nor slug must be rejected
    by SQLite itself, not by whichever caller remembered to check."""
    import sqlite3

    wid = watchlist.add(conn, user, name="X Co")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "UPDATE watched_company SET resolution='linkedin', "
            "linkedin_name=NULL, linkedin_slug=NULL WHERE id=?", (wid,))


def test_record_yield(conn, user):
    wid = watchlist.add(conn, user, name="GitLab", domain="gitlab.com")
    watchlist.set_resolution(conn, user, wid, "ats")
    fp = watchlist.get(conn, user, wid)["company_fingerprint"]
    watchlist.record_yield(conn, user, {fp: 7})
    row = watchlist.get(conn, user, wid)
    assert row["last_yield_count"] == 7 and row["last_fetched_at"]
