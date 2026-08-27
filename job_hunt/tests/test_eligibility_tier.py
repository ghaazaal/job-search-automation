"""The verified tier: positive evidence the user can take the job.

Verified = geo verdict `eligible` OR run_core-supplied local evidence
(job's parsed country / profile city == the user's). Everything else is
unverified and says so — unchecked must not masquerade as fine.
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
    return Scorer(_CONFIG, _VOCAB, user_country="am", user_modes=("remote",))


def test_an_eligible_geo_verdict_verifies():
    e = _scorer().score_job(
        "BI Developer", _JD + " Open to candidates in EMEA.", _RESUME)
    assert e["eligibility_verified"] is True
    assert "open to your location" in e["reason"]
    assert "not verified" not in e["reason"]


def test_local_evidence_verifies():
    e = _scorer().score_job("BI Developer", _JD, _RESUME,
                            local_evidence=True)
    assert e["eligibility_verified"] is True
    assert "open to your location" in e["reason"]


def test_no_evidence_says_so():
    e = _scorer().score_job("BI Developer", _JD, _RESUME)
    assert e["eligibility_verified"] is False
    assert "location eligibility not verified" in e["reason"]
    assert "no visa or clearance limits found" not in e["reason"]


def test_a_restriction_is_not_reworded():
    """A fired penalty already carries the story — the absence clause
    never appears alongside it."""
    e = _scorer().score_job(
        "BI Developer", _JD + " Must be based in the UK.", _RESUME)
    assert e["eligibility_verified"] is False
    assert "restricted to UK" in e["reason"]
    assert "not verified" not in e["reason"]


def test_no_description_claims_no_tier():
    """Rule 3 territory: nothing was compared, so the reduced-confidence
    sentence stands alone."""
    e = _scorer().score_job("BI Developer", "", _RESUME)
    assert "not verified" not in e["reason"]


def test_best_match_passes_local_evidence_through():
    e = _scorer().best_match("BI Developer", _JD, [_RESUME],
                             local_evidence=True)
    assert e["eligibility_verified"] is True


def test_a_stated_restriction_beats_local_evidence():
    """A Yerevan-tagged posting that says 'must be based in the UK' is
    not a verified sure thing — the tier and the sentence must agree."""
    e = _scorer().score_job(
        "BI Developer", _JD + " Must be based in the UK.", _RESUME,
        local_evidence=True)
    assert e["eligibility_verified"] is False
    assert "restricted to UK" in e["reason"]

