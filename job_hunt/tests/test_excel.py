"""Tests for src/tracker/excel.py — round-tripping the tracker workbook."""
import pytest

from src.tracker import excel

_URL = "https://example.com/jobs/analytics-engineer-123"


@pytest.fixture
def tracker(tmp_path):
    path = tmp_path / "tracker.xlsx"
    excel.save(path, [{
        "Search Category":    "Analytics Engineer",
        "Job Title":          "Senior Analytics Engineer",
        "Company":            "Acme",
        "Location":           "Remote, US",
        "Platform":           "LinkedIn",
        "Apply Link":         _URL,
        "Match Score":        8,
        "Application Status": "New",
    }])
    return path


def test_apply_link_round_trips_as_url(tracker):
    """The cell displays 'Apply ->' but callers need the real target back.

    The dashboard reads row["Apply Link"] for every historical row, so the
    display string leaking through produced broken links on every old job.
    """
    row = excel.read_existing(tracker)[_URL]
    assert row["Apply Link"] == _URL


def test_read_existing_is_keyed_by_url(tracker):
    assert list(excel.read_existing(tracker)) == [_URL]


def test_other_columns_survive_round_trip(tracker):
    row = excel.read_existing(tracker)[_URL]
    assert row["Company"] == "Acme"
    assert row["Match Score"] == 8
