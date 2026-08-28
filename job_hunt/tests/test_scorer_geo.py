"""Tests for the geography constraints in Scorer._constraints.

Uses the real vocabulary.yaml — these are also the integration proof that
the shipped templates survive the scorer's lowercasing and land in the
reason sentence.

Display names in assertions ("UK", "Germany") are pinned on purpose: the
first alias in a country's vocabulary.yaml list IS the display name shown
to the user, so a reordered alias list is a product change and should
fail here.
"""
from pathlib import Path

from src.scoring.scorer import Scorer

_CONFIG = {"scoring": {"bands": {"strong": 8, "partial": 5}}}
_VOCAB = Path(__file__).parent.parent / "vocabulary.yaml"

_RESUME = {
    "id": 1,
    "label": "bi",
    "seniority": "senior",
    "target_roles": [{"title": "BI Developer", "aliases": []}],
    "skills": [{"name": "Power BI", "tier": "core", "aliases": []},
               {"name": "SQL", "tier": "working", "aliases": []}],
}

_JD = "We need Power BI and SQL dashboards."

_BOARD_CLAUSE = "found via Indeed's US board, not verified for your country"


def _scorer(country="am"):
    return Scorer(_CONFIG, _VOCAB, user_country=country)


def test_a_foreign_restriction_costs_points_and_is_named():
    restricted = _scorer().score_job(
        "BI Developer", _JD + " Must be based in the UK.", _RESUME)
    free = _scorer().score_job("BI Developer", _JD, _RESUME)
    assert restricted["match_score"] < free["match_score"]
    assert "remote, but restricted to UK" in restricted["penalties"]
    assert "restricted to UK" in restricted["reason"]


def test_an_excluding_list_costs_points_and_is_named():
    evidence = _scorer().score_job(
        "BI Developer", _JD + " Open to candidates in the UK and Germany.",
        _RESUME)
    assert "remote, but open only to UK and Germany" in evidence["penalties"]
    assert "open only to UK and Germany" in evidence["reason"]


def test_a_list_that_includes_you_is_not_flagged():
    """The v3 case, end to end through the shipped vocabulary: your country
    in the list means no flag of any kind."""
    evidence = _scorer().score_job(
        "BI Developer",
        _JD + " Open to candidates in the UK, Armenia and Poland.", _RESUME)
    assert not any("restricted" in p or "open only" in p
                   for p in evidence["penalties"])


def test_a_region_that_includes_you_is_not_flagged():
    """EMEA includes Armenia in the shipped vocabulary — eligible, silent."""
    evidence = _scorer().score_job(
        "BI Developer", _JD + " Open to candidates in EMEA.", _RESUME)
    assert not any("restricted" in p or "open only" in p
                   for p in evidence["penalties"])


def test_your_own_country_is_not_flagged():
    evidence = _scorer().score_job(
        "BI Developer", _JD + " Must be based in Armenia.", _RESUME)
    assert not any("restricted" in p for p in evidence["penalties"])


def test_no_country_on_file_claims_nothing():
    """A scorer built without a country must not fire geography at all —
    existing callers and tests keep their exact behaviour."""
    evidence = Scorer(_CONFIG, _VOCAB).score_job(
        "BI Developer", _JD + " Must be based in the UK.", _RESUME)
    assert not any("restricted" in p for p in evidence["penalties"])


def test_the_scorer_takes_no_scraped_under_argument():
    """Indeed's us-board fallback was its only writer, and Indeed is gone.

    An inert parameter that still looks live is the pattern Ship 7 deleted
    the probe mechanism to avoid.
    """
    import inspect

    assert "scraped_under" not in inspect.signature(
        Scorer.best_match).parameters
