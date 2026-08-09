"""Tests for src/dashboard.py — pipeline rows -> JOBS array."""
from src.dashboard import _rows_to_jobs


def _row(**kw):
    base = {"Company": "Acme", "Job Title": "Analytics Engineer",
            "Location": "Remote, US", "Match Score": 8, "Platform": "LinkedIn",
            "Apply Link": "https://example.com/j1", "Application Status": "New"}
    return {**base, **kw}


def test_real_description_is_used():
    jd = "You will own our dbt models and Airflow DAGs."
    job = _rows_to_jobs([_row(_description=jd)])[0]
    assert jd in job["description"]


def test_falls_back_to_link_when_no_description():
    job = _rows_to_jobs([_row()])[0]
    assert "Open listing" in job["description"]


def test_chips_come_from_the_description():
    """Titles rarely name tools; the JD does."""
    jd = "Our stack is dbt, Snowflake and Airflow."
    chips = {c["label"] for c in _rows_to_jobs([_row(_description=jd)])[0]["chips"]}
    assert {"dbt", "snowflake", "airflow"} <= chips


def test_chips_do_not_match_inside_words():
    """'bi' must not be extracted from 'ambitious'."""
    jd = "We are an ambitious team that values collaboration."
    chips = {c["label"] for c in _rows_to_jobs([_row(_description=jd)])[0]["chips"]}
    assert "bi" not in chips


def test_filtered_rows_are_excluded():
    rows = [_row(**{"Application Status": "Filtered Out"})]
    assert _rows_to_jobs(rows) == []
