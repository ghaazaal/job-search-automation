"""Tests for the mode-mismatch flag in Scorer._constraints.

The scorer does not decide mode policy — run_core does, and passes
`mode_mismatch` only for the keep-and-flag rung of the ladder (mode the
user did not ask for, location unparseable). The scorer's job is the
penalty and the sentence.
"""
from pathlib import Path

from src.scoring.scorer import Scorer

_CONFIG = {"scoring": {"bands": {"strong": 8, "partial": 5}}}
_VOCAB = Path(__file__).parent.parent / "vocabulary.yaml"

_RESUME = {
    "id": 1, "label": "bi", "seniority": "senior",
    "target_roles": [{"title": "BI Developer", "aliases": []}],
    "skills": [{"name": "Power BI", "tier": "core", "aliases": []},
               {"name": "SQL", "tier": "working", "aliases": []}],
}

_JD = "We need Power BI and SQL dashboards."


def _scorer():
    return Scorer(_CONFIG, _VOCAB, user_country="am",
                  user_modes=("remote",))


def test_the_flag_costs_points_and_is_named():
    flagged = _scorer().score_job("BI Developer", _JD, _RESUME,
                                  mode_mismatch="hybrid")
    clean = _scorer().score_job("BI Developer", _JD, _RESUME)
    assert flagged["match_score"] <= clean["match_score"]
    assert "says hybrid, you searched remote-only" in flagged["penalties"]
    assert "says hybrid" in flagged["reason"]


def test_no_flag_without_the_argument():
    evidence = _scorer().score_job(
        "BI Developer", _JD + " Hybrid work, 2 days a week in the office.",
        _RESUME)
    assert not any("says hybrid" in p for p in evidence["penalties"])


def test_the_sentence_names_every_searched_mode():
    scorer = Scorer(_CONFIG, _VOCAB, user_country="am",
                    user_modes=("remote", "hybrid"))
    evidence = scorer.score_job("BI Developer", _JD, _RESUME,
                                mode_mismatch="onsite")
    assert "says onsite, you searched remote/hybrid-only" in evidence["penalties"]


def test_best_match_passes_the_flag_through():
    evidence = _scorer().best_match("BI Developer", _JD, [_RESUME],
                                    mode_mismatch="onsite")
    assert any("says onsite" in p for p in evidence["penalties"])
