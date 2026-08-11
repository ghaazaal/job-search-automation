"""Tests for src/store/profile.py — the user's profile and their resumes."""
import pytest

from src.store.db import connect
from src.store.ingest import ensure_user
from src.store.profile import get_profile, set_profile
from src.store.schema import init_db


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "test.db")
    init_db(c)
    return c


@pytest.fixture
def user_id(conn):
    return ensure_user(conn, "G")


def test_a_new_user_has_an_empty_profile(conn, user_id):
    assert get_profile(conn, user_id) == {
        "location": "", "country": "", "work_modes": [],
        "setup_complete": False}


def test_setting_the_profile_marks_setup_complete(conn, user_id):
    set_profile(conn, user_id, location="Toronto, ON", country="CA",
                work_modes=["remote", "hybrid"])
    assert get_profile(conn, user_id) == {
        "location": "Toronto, ON", "country": "ca",
        "work_modes": ["remote", "hybrid"], "setup_complete": True}


def test_an_unknown_work_mode_is_rejected(conn, user_id):
    with pytest.raises(ValueError, match="hybrid-ish"):
        set_profile(conn, user_id, location="Toronto",
                    country="ca", work_modes=["hybrid-ish"])
    assert get_profile(conn, user_id)["setup_complete"] is False


def test_at_least_one_work_mode_is_required(conn, user_id):
    with pytest.raises(ValueError, match="work mode"):
        set_profile(conn, user_id, location="Toronto",
                    country="ca", work_modes=[])


def test_the_profile_of_a_missing_user_raises(conn):
    with pytest.raises(ValueError, match="no user"):
        get_profile(conn, 9999)


def test_none_location_and_country_are_treated_as_empty_strings(conn, user_id):
    set_profile(conn, user_id, location=None, country=None,
                work_modes=["remote"])
    assert get_profile(conn, user_id) == {
        "location": "", "country": "",
        "work_modes": ["remote"], "setup_complete": True}
