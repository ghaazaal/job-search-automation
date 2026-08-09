"""Tests for src/scrapers/* — Apify item mapping.

The network call is monkeypatched out; these cover the raw-item -> job-dict
mapping only, which is where the description was being dropped.
"""
import pytest

from src.scrapers import indeed, linkedin


def _patch(monkeypatch, module, items):
    monkeypatch.setattr(module, "call_actor", lambda *a, **k: items)


def _scrape(module, monkeypatch, item):
    _patch(monkeypatch, module, [item])
    return module.scrape("Data Analyst", "Data Analyst", "actor~id")[0]


_MINIMAL = {"jobUrl": "https://example.com/j1", "title": "Data Analyst",
            "company": "Acme", "location": "Remote"}


@pytest.mark.parametrize("module", [indeed, linkedin])
def test_description_is_captured(module, monkeypatch):
    job = _scrape(module, monkeypatch,
                  {**_MINIMAL, "description": "We run dbt and Airflow."})
    assert job["description"] == "We run dbt and Airflow."


@pytest.mark.parametrize("module", [indeed, linkedin])
@pytest.mark.parametrize("key", ["descriptionText", "jobDescription",
                                 "descriptionHtml"])
def test_description_alternate_keys(module, key, monkeypatch):
    """Apify actors disagree on the field name — accept the common variants."""
    job = _scrape(module, monkeypatch, {**_MINIMAL, key: "Airflow required."})
    assert job["description"] == "Airflow required."


@pytest.mark.parametrize("module", [indeed, linkedin])
def test_html_description_is_flattened(module, monkeypatch):
    """HTML bodies must become plain text so keyword matching works."""
    html = "<p>We use <strong>dbt</strong> and Airflow.</p><ul><li>SQL</li></ul>"
    job = _scrape(module, monkeypatch, {**_MINIMAL, "description": html})
    assert "<" not in job["description"]
    assert "dbt" in job["description"]
    assert "SQL" in job["description"]


@pytest.mark.parametrize("module", [indeed, linkedin])
def test_missing_description_is_empty_string(module, monkeypatch):
    """No description available must not crash or yield None."""
    job = _scrape(module, monkeypatch, _MINIMAL)
    assert job["description"] == ""
