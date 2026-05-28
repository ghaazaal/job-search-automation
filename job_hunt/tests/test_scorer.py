"""Tests for src/scoring/scorer.py"""
import pytest
from pathlib import Path
from src.scoring.scorer import Scorer

_CONFIG = {
    "scoring": {
        "weights": {
            "title_match": 0.40, "category_bonus": 0.10,
            "seniority": 0.20, "skills": 0.20, "penalty": 0.10
        }
    }
}
_KW = Path(__file__).parent.parent / "keywords.yaml"


@pytest.fixture
def scorer():
    return Scorer(_CONFIG, _KW)


def test_core_ae_senior_scores_high(scorer):
    r = scorer.score_job("Senior Analytics Engineer", "Analytics Engineer",
                         "$120k-$150k", "https://example.com/job1")
    assert r["match_score"] >= 7


def test_core_de_scores_well(scorer):
    r = scorer.score_job("Data Engineer", "Data Engineer",
                         "$110k", "https://example.com/job2")
    assert r["match_score"] >= 5


def test_junior_penalty(scorer):
    r = scorer.score_job("Junior Data Engineer", "Data Engineer",
                         "", "https://example.com/job3")
    senior_r = scorer.score_job("Senior Data Engineer", "Data Engineer",
                                "", "https://example.com/job4")
    assert r["match_score"] < senior_r["match_score"]


def test_weak_keyword_scores_low(scorer):
    r = scorer.score_job("React Frontend Engineer", "Analytics Engineer",
                         "", "https://example.com/job5")
    assert r["match_score"] <= 3


def test_clearance_penalty(scorer):
    r_clear = scorer.score_job("Data Analyst clearance required",
                               "Data Analyst", "", "https://example.com/job6")
    r_normal = scorer.score_job("Data Analyst", "Data Analyst",
                                "", "https://example.com/job7")
    assert r_clear["match_score"] < r_normal["match_score"]


def test_seniority_exec_penalized(scorer):
    r_exec = scorer.score_job("VP of Data Engineering", "Data Engineer",
                              "", "https://example.com/job8")
    r_senior = scorer.score_job("Senior Data Engineer", "Data Engineer",
                                "", "https://example.com/job9")
    assert r_exec["match_score"] < r_senior["match_score"]


def test_salary_parsing_in_interview_chance(scorer):
    r_high_sal = scorer.score_job("Senior Analytics Engineer", "Analytics Engineer",
                                   "$400,000", "https://example.com/job10")
    r_normal = scorer.score_job("Senior Analytics Engineer", "Analytics Engineer",
                                "$130,000", "https://example.com/job11")
    # High salary slightly reduces interview chance base
    hi = int(r_high_sal["interview_chance"].replace("%", ""))
    lo = int(r_normal["interview_chance"].replace("%", ""))
    assert hi <= lo


def test_tailoring_field_returned(scorer):
    r = scorer.score_job("Analytics Engineer", "Analytics Engineer",
                         "", "https://example.com/job12")
    assert r["tailoring"] in ("Minor", "Moderate", "Significant", "N/A")
