"""Tests for the scorer's evidence output — bands, matched skills, gaps.

The UI renders a band word and a sentence, never a number, so the scorer has
to hand back what it actually matched rather than just a total.
"""
import pytest
from pathlib import Path

from src.scoring.scorer import Scorer

_CONFIG = {"scoring": {"weights": {}}}
_KW = Path(__file__).parent.parent / "keywords.yaml"

_STRONG_JD = ("We run dbt on Snowflake with Airflow orchestration. You will "
              "build Power BI dashboards over our ClickHouse warehouse using "
              "Python and SQL.")


@pytest.fixture
def scorer():
    return Scorer(_CONFIG, _KW)


# ── Bands ─────────────────────────────────────────────────────────────────────

def test_strong_jd_earns_strong_fit(scorer):
    r = scorer.score_job("Senior Analytics Engineer", "Analytics Engineer", "",
                         "https://x/y", description=_STRONG_JD)
    assert r["band"] == "STRONG FIT"


def test_poor_jd_earns_stretch(scorer):
    jd = "You will build React components and maintain our Angular frontend."
    r = scorer.score_job("Data Analyst", "Data Analyst", "",
                         "https://x/y", description=jd)
    assert r["band"] == "STRETCH"


def test_band_is_none_without_a_description(scorer):
    """Rule 3 — nothing was checked, so no band may be claimed."""
    r = scorer.score_job("Data Analyst", "Data Analyst", "", "https://x/y")
    assert r["band"] is None
    assert r["description_captured"] is False


def test_description_captured_flag_set(scorer):
    r = scorer.score_job("Data Analyst", "Data Analyst", "", "https://x/y",
                         description=_STRONG_JD)
    assert r["description_captured"] is True


def test_bands_are_ordered_by_score(scorer):
    strong = scorer.score_job("Senior Analytics Engineer", "Analytics Engineer",
                              "", "https://x/y", description=_STRONG_JD)
    stretch = scorer.score_job("Data Analyst", "Data Analyst", "", "https://x/y",
                               description="React and Angular frontend work.")
    assert strong["match_score"] > stretch["match_score"]


# ── Matched evidence ──────────────────────────────────────────────────────────

def test_matched_skills_are_reported(scorer):
    r = scorer.score_job("Data Analyst", "Data Analyst", "", "https://x/y",
                         description=_STRONG_JD)
    assert {"dbt", "airflow", "clickhouse"} <= set(r["matched"])


def test_unmatched_skills_are_not_reported(scorer):
    r = scorer.score_job("Data Analyst", "Data Analyst", "", "https://x/y",
                         description="We use spreadsheets.")
    assert r["matched"] == []


def test_gaps_are_tools_in_the_post_you_do_not_have(scorer):
    """Snowflake appears in the JD but is not one of the scored skills."""
    r = scorer.score_job("Data Analyst", "Data Analyst", "", "https://x/y",
                         description=_STRONG_JD)
    assert "snowflake" in r["gaps"]


def test_gaps_exclude_things_already_matched(scorer):
    r = scorer.score_job("Data Analyst", "Data Analyst", "", "https://x/y",
                         description=_STRONG_JD)
    assert not (set(r["matched"]) & set(r["gaps"]))


def test_penalties_are_named_not_just_subtracted(scorer):
    jd = "Applicants must hold an active TS/SCI security clearance."
    r = scorer.score_job("Data Analyst", "Data Analyst", "", "https://x/y",
                         description=jd)
    assert "clearance" in r["penalties"]


def test_no_penalties_reported_when_none_fire(scorer):
    r = scorer.score_job("Data Analyst", "Data Analyst", "", "https://x/y",
                         description=_STRONG_JD)
    assert r["penalties"] == []


def test_seniority_band_is_reported(scorer):
    senior = scorer.score_job("Senior Data Engineer", "Data Engineer", "",
                              "https://x/y", description=_STRONG_JD)
    junior = scorer.score_job("Junior Data Engineer", "Data Engineer", "",
                              "https://x/y", description=_STRONG_JD)
    assert senior["seniority"] == "senior"
    assert junior["seniority"] == "junior"


# ── Removals ──────────────────────────────────────────────────────────────────

def test_reason_ships_with_the_band(scorer):
    """Rule 2 — a band is never available without its sentence."""
    r = scorer.score_job("Senior Analytics Engineer", "Analytics Engineer", "",
                         "https://x/y", description=_STRONG_JD)
    assert r["band"] and r["reason"].strip()
    # The sentence names the highest-weighted matches, not every one of them.
    assert all(skill in r["reason"] for skill in r["matched"][:4])


def test_reason_present_even_without_a_description(scorer):
    r = scorer.score_job("Data Analyst", "Data Analyst", "", "https://x/y")
    assert r["band"] is None
    assert "without a description" in r["reason"]


def test_interview_chance_is_gone(scorer):
    """Fabricated precision — removed by spec rule 9."""
    r = scorer.score_job("Data Analyst", "Data Analyst", "", "https://x/y",
                         description=_STRONG_JD)
    assert "interview_chance" not in r
