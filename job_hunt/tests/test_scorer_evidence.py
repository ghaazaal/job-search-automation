"""The scorer's evidence — bands, matched skills, gaps, attribution.

The UI renders a band word and a sentence, never a number, so the scorer has
to hand back what it actually matched rather than just a total.
"""
from pathlib import Path

import pytest

from src.scoring.scorer import Scorer

_CONFIG = {"scoring": {"bands": {"strong": 8, "partial": 5}}}
_VOCAB = Path(__file__).parent.parent / "vocabulary.yaml"

_RESUME = {
    "id": 7,
    "label": "analytics engineer",
    "seniority": "senior",
    "target_roles": [{"title": "Analytics Engineer", "aliases": []}],
    "skills": [{"name": "dbt", "tier": "core", "aliases": []},
               {"name": "Airflow", "tier": "core", "aliases": []},
               {"name": "Power BI", "tier": "core", "aliases": ["dax"]}],
}

_STRONG_JD = ("We run dbt on Snowflake with Airflow orchestration. You will "
              "build Power BI dashboards.")


@pytest.fixture
def scorer():
    return Scorer(_CONFIG, _VOCAB)


# ── Bands ─────────────────────────────────────────────────────────────────────

def test_a_strong_posting_earns_strong_fit(scorer):
    result = scorer.score_job("Senior Analytics Engineer", _STRONG_JD, _RESUME)
    assert result["band"] == "STRONG FIT"


def test_a_poor_posting_earns_stretch(scorer):
    jd = "React, Angular, Terraform and Kafka components."
    result = scorer.score_job("Warehouse Associate", jd, _RESUME)
    assert result["band"] == "STRETCH"


def test_no_band_is_claimed_without_a_description(scorer):
    """Nothing was compared, so nothing may be claimed."""
    result = scorer.score_job("Analytics Engineer", "", _RESUME)
    assert result["band"] is None
    assert result["description_captured"] is False


def test_the_captured_flag_is_set_when_there_is_a_description(scorer):
    result = scorer.score_job("Analytics Engineer", _STRONG_JD, _RESUME)
    assert result["description_captured"] is True


# ── Matched evidence ──────────────────────────────────────────────────────────

def test_matched_skills_are_reported(scorer):
    result = scorer.score_job("Analytics Engineer", _STRONG_JD, _RESUME)
    assert {"dbt", "Airflow", "Power BI"} == set(result["matched"])


def test_nothing_is_reported_when_nothing_matched(scorer):
    result = scorer.score_job("Analytics Engineer", "We use spreadsheets.",
                              _RESUME)
    assert result["matched"] == []


def test_a_skill_matched_by_alias_is_reported_by_name(scorer):
    result = scorer.score_job("Analytics Engineer", "Heavy dax work.", _RESUME)
    assert result["matched"] == ["Power BI"]


def test_gaps_are_tools_in_the_post_you_do_not_have(scorer):
    result = scorer.score_job("Analytics Engineer", _STRONG_JD, _RESUME)
    assert "snowflake" in result["gaps"]


def test_gaps_exclude_what_you_already_matched(scorer):
    result = scorer.score_job("Analytics Engineer", _STRONG_JD, _RESUME)
    assert not (set(result["matched"]) & set(result["gaps"]))


def test_penalties_are_named_not_just_subtracted(scorer):
    jd = _STRONG_JD + " Applicants must hold an active security clearance."
    result = scorer.score_job("Analytics Engineer", jd, _RESUME)
    assert "clearance" in result["penalties"]


def test_a_tool_mismatch_is_named_as_a_penalty(scorer):
    jd = "React, Angular, Terraform and Kafka experience required."
    result = scorer.score_job("Analytics Engineer", jd, _RESUME)
    assert any("overlap" in p for p in result["penalties"])


def test_no_penalties_are_reported_when_none_fire(scorer):
    result = scorer.score_job("Analytics Engineer", _STRONG_JD, _RESUME)
    assert result["penalties"] == []


def test_the_postings_seniority_is_reported(scorer):
    senior = scorer.score_job("Senior Analytics Engineer", _STRONG_JD, _RESUME)
    junior = scorer.score_job("Junior Analytics Engineer", _STRONG_JD, _RESUME)
    assert senior["seniority"] == "senior"
    assert junior["seniority"] == "junior"


# ── Attribution ───────────────────────────────────────────────────────────────

def test_the_evidence_records_which_resume_produced_it(scorer):
    result = scorer.score_job("Analytics Engineer", _STRONG_JD, _RESUME)
    assert result["resume_id"] == 7
    assert result["resume_label"] == "analytics engineer"


def test_the_reason_names_the_resume(scorer):
    result = scorer.score_job("Analytics Engineer", _STRONG_JD, _RESUME)
    assert "analytics engineer resume" in result["reason"]


# ── Rules carried forward ─────────────────────────────────────────────────────

def test_a_band_always_ships_with_its_sentence(scorer):
    result = scorer.score_job("Senior Analytics Engineer", _STRONG_JD, _RESUME)
    assert result["band"] and result["reason"].strip()


def test_a_reason_is_present_even_without_a_description(scorer):
    result = scorer.score_job("Analytics Engineer", "", _RESUME)
    assert result["band"] is None
    assert "without a description" in result["reason"]


def test_interview_chance_is_still_gone(scorer):
    """Fabricated precision — removed by spec rule 9, and staying removed."""
    result = scorer.score_job("Analytics Engineer", _STRONG_JD, _RESUME)
    assert "interview_chance" not in result
