"""Tests for src/store/profile.py — the user's profile and their resumes."""
import sqlite3

import pytest

from src.store.db import connect
from src.store.ingest import ensure_user
from src.store.profile import (create_resume, delete_resume, get_profile,
                               get_resume, list_resumes, resume_by_sha,
                               set_profile, unique_label, update_resume)
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


def _add(conn, user_id, label="bi developer", sha="abc123"):
    return create_resume(conn, user_id, label=label,
                         orig_filename="Ghazal BI.pdf", sha256=sha,
                         stored_path=f"resumes/{user_id}/{sha}.pdf",
                         extracted_text="Power BI, SQL, dbt")


def test_a_new_resume_starts_active_and_unparsed(conn, user_id):
    resume_id = _add(conn, user_id)
    resume = get_resume(conn, user_id, resume_id)
    assert resume["label"] == "bi developer"
    assert resume["orig_filename"] == "Ghazal BI.pdf"
    assert resume["extracted_text"] == "Power BI, SQL, dbt"
    assert resume["skills"] == []
    assert resume["target_roles"] == []
    assert resume["seniority"] is None
    assert resume["is_active"] is True


def test_the_same_file_cannot_be_uploaded_twice(conn, user_id):
    _add(conn, user_id, label="one", sha="same")
    with pytest.raises(sqlite3.IntegrityError):
        _add(conn, user_id, label="two", sha="same")


def test_two_resumes_cannot_share_a_label(conn, user_id):
    _add(conn, user_id, label="bi developer", sha="a")
    with pytest.raises(sqlite3.IntegrityError):
        _add(conn, user_id, label="bi developer", sha="b")


def test_updating_writes_roles_skills_and_seniority(conn, user_id):
    resume_id = _add(conn, user_id)
    update_resume(
        conn, user_id, resume_id, label="bi dev",
        target_roles=[{"title": "BI Developer", "aliases": ["bi engineer"]}],
        skills=[{"name": "Power BI", "tier": "core", "aliases": ["dax"]}],
        seniority="senior")
    resume = get_resume(conn, user_id, resume_id)
    assert resume["label"] == "bi dev"
    assert resume["target_roles"][0]["aliases"] == ["bi engineer"]
    assert resume["skills"][0]["tier"] == "core"
    assert resume["seniority"] == "senior"


def test_an_unknown_seniority_is_rejected(conn, user_id):
    resume_id = _add(conn, user_id)
    with pytest.raises(ValueError, match="seniority"):
        update_resume(conn, user_id, resume_id, label="x", target_roles=[],
                      skills=[], seniority="grand wizard")


def test_updating_someone_elses_resume_raises(conn, user_id):
    resume_id = _add(conn, user_id)
    other = ensure_user(conn, "Other")
    with pytest.raises(LookupError):
        update_resume(conn, other, resume_id, label="x", target_roles=[],
                      skills=[], seniority="mid")


def test_listing_can_be_narrowed_to_active_resumes(conn, user_id):
    first = _add(conn, user_id, label="one", sha="a")
    _add(conn, user_id, label="two", sha="b")
    update_resume(conn, user_id, first, label="one", target_roles=[],
                  skills=[], seniority="mid", is_active=False)
    assert len(list_resumes(conn, user_id)) == 2
    assert [r["label"] for r in list_resumes(conn, user_id, active_only=True)] == ["two"]


def test_deleting_returns_the_stored_path_and_frees_the_label(conn, user_id):
    resume_id = _add(conn, user_id, label="one", sha="a")
    assert delete_resume(conn, user_id, resume_id) == f"resumes/{user_id}/a.pdf"
    assert get_resume(conn, user_id, resume_id) is None
    _add(conn, user_id, label="one", sha="c")   # the label is free again


def test_deleting_a_missing_resume_returns_none(conn, user_id):
    assert delete_resume(conn, user_id, 9999) is None


def test_resume_by_sha_finds_a_duplicate_upload(conn, user_id):
    _add(conn, user_id, sha="deadbeef")
    assert resume_by_sha(conn, user_id, "deadbeef") is not None
    assert resume_by_sha(conn, user_id, "nope") is None


def test_unique_label_counts_up_around_collisions(conn, user_id):
    assert unique_label(conn, user_id, "Ghazal Resume") == "ghazal resume"
    _add(conn, user_id, label="ghazal resume", sha="a")
    assert unique_label(conn, user_id, "Ghazal Resume") == "ghazal resume 2"
    _add(conn, user_id, label="ghazal resume 2", sha="b")
    assert unique_label(conn, user_id, "Ghazal Resume") == "ghazal resume 3"


def test_unique_label_falls_back_when_the_filename_gives_nothing(conn, user_id):
    assert unique_label(conn, user_id, "") == "resume"
