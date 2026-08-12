"""Tests for src/scoring/scorer.py — one posting against one resume."""
from pathlib import Path

import pytest

from src.scoring.scorer import Scorer

_CONFIG = {"scoring": {"bands": {"strong": 8, "partial": 5}}}
_VOCAB = Path(__file__).parent.parent / "vocabulary.yaml"

_RESUME = {
    "id": 1,
    "label": "analytics engineer",
    "seniority": "senior",
    "target_roles": [{"title": "Analytics Engineer", "aliases": []},
                     {"title": "Data Engineer", "aliases": []}],
    "skills": [{"name": "dbt", "tier": "core", "aliases": []},
               {"name": "Airflow", "tier": "core", "aliases": []},
               {"name": "Power BI", "tier": "core", "aliases": ["dax"]},
               {"name": "Python", "tier": "working", "aliases": []},
               {"name": "SQL", "tier": "working", "aliases": []}],
}

_STRONG_JD = ("We run dbt with Airflow orchestration. You will build Power BI "
              "dashboards using Python and SQL.")


@pytest.fixture
def scorer():
    return Scorer(_CONFIG, _VOCAB)


def _score(scorer, title, description="", resume=_RESUME):
    return scorer.score_job(title, description, resume)


def test_a_matching_title_and_stack_scores_high(scorer):
    assert _score(scorer, "Senior Analytics Engineer",
                  _STRONG_JD)["match_score"] >= 8


def test_an_unrelated_title_scores_low(scorer):
    assert _score(scorer, "Warehouse Associate")["match_score"] <= 4


def test_naming_the_stack_beats_the_same_title_with_no_description(scorer):
    with_jd = _score(scorer, "Data Engineer", _STRONG_JD)["match_score"]
    without = _score(scorer, "Data Engineer")["match_score"]
    assert with_jd > without


def test_seniority_distance_costs_points(scorer):
    """The resume says senior, so a junior posting is further away."""
    same = _score(scorer, "Senior Data Engineer", _STRONG_JD)["match_score"]
    apart = _score(scorer, "Junior Data Engineer", _STRONG_JD)["match_score"]
    assert same > apart


def test_the_same_posting_scores_differently_for_a_different_resume(scorer):
    """The whole point of Ship 2: the resume is the yardstick."""
    react = {**_RESUME, "id": 2, "label": "frontend",
             "target_roles": [{"title": "Frontend Engineer", "aliases": []}],
             "skills": [{"name": "React", "tier": "core", "aliases": []}]}
    jd = "React, Angular, Terraform and Kafka experience required."
    for_data = _score(scorer, "Frontend Engineer", jd)["match_score"]
    for_react = _score(scorer, "Frontend Engineer", jd, react)["match_score"]
    assert for_react > for_data


def test_a_clearance_requirement_costs_points(scorer):
    flagged = _score(scorer, "Data Engineer",
                     _STRONG_JD + " Requires an active security clearance.")
    clean = _score(scorer, "Data Engineer", _STRONG_JD)
    assert flagged["match_score"] < clean["match_score"]


def test_a_visa_restriction_costs_points(scorer):
    flagged = _score(scorer, "Data Engineer",
                     _STRONG_JD + " We cannot sponsor CPT or OPT.")
    clean = _score(scorer, "Data Engineer", _STRONG_JD)
    assert flagged["match_score"] < clean["match_score"]


def test_common_words_do_not_fire_the_visa_penalty(scorer):
    """'optimize' must not read as 'opt'."""
    innocuous = _score(scorer, "Data Engineer",
                       _STRONG_JD + " You will optimize queries.")
    clean = _score(scorer, "Data Engineer", _STRONG_JD)
    assert innocuous["match_score"] == clean["match_score"]


def test_an_exec_posting_costs_a_non_exec_points(scorer):
    exec_role = _score(scorer, "VP of Data Engineering", _STRONG_JD)
    senior_role = _score(scorer, "Senior Data Engineer", _STRONG_JD)
    assert exec_role["match_score"] < senior_role["match_score"]


def test_an_exec_posting_does_not_penalise_an_exec(scorer):
    """The penalty is about the gap, not about the word."""
    exec_resume = {**_RESUME, "seniority": "exec"}
    penalised = _score(scorer, "VP of Data Engineering", _STRONG_JD)
    not_penalised = _score(scorer, "VP of Data Engineering", _STRONG_JD,
                           exec_resume)
    assert "executive role" in penalised["penalties"]
    assert "executive role" not in not_penalised["penalties"]


def test_the_score_stays_inside_one_to_ten(scorer):
    worst = _score(scorer, "Warehouse Associate",
                   "React Angular Terraform Kafka. Requires clearance.")
    best = _score(scorer, "Senior Analytics Engineer", _STRONG_JD)
    assert 1 <= worst["match_score"] <= 10
    assert 1 <= best["match_score"] <= 10


def test_a_description_is_optional(scorer):
    assert 1 <= _score(scorer, "Analytics Engineer")["match_score"] <= 10


def test_tailoring_is_reported(scorer):
    result = _score(scorer, "Analytics Engineer", _STRONG_JD)
    assert result["tailoring"] in ("Minor", "Moderate", "Significant", "N/A")
