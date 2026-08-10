"""Tests for src/scoring/reason.py.

The reason sentence is the only fit explanation the user sees. Every fact in
it must come from the scorer's evidence — nothing may be invented.
"""
from src.scoring.reason import compose_reason


def _ev(**kw):
    base = {"band": "STRONG FIT", "matched": [], "gaps": [], "penalties": [],
            "seniority": "mid", "description_captured": True}
    return {**base, **kw}


def test_named_skills_appear_in_the_sentence():
    r = compose_reason(_ev(matched=["dbt", "airflow", "clickhouse"]))
    assert "dbt" in r and "airflow" in r and "clickhouse" in r


def test_skills_are_listed_readably():
    r = compose_reason(_ev(matched=["dbt", "airflow", "clickhouse"]))
    assert "dbt, airflow and clickhouse" in r


def test_single_skill_needs_no_conjunction():
    r = compose_reason(_ev(matched=["dbt"]))
    assert "dbt" in r
    assert " and " not in r.split("·")[0]


def test_long_skill_lists_are_capped():
    """Cards must not grow unbounded — the design caps the reason length."""
    r = compose_reason(_ev(matched=["dbt", "airflow", "clickhouse", "python",
                                    "sql", "power bi", "etl", "dashboard"]))
    assert r.count(",") <= 3


def test_seniority_is_stated():
    assert "senior" in compose_reason(_ev(matched=["dbt"], seniority="senior"))


def test_penalties_are_stated_plainly():
    r = compose_reason(_ev(matched=["dbt"], penalties=["clearance"]))
    assert "clearance" in r


def test_clean_run_says_no_restrictions_found():
    r = compose_reason(_ev(matched=["dbt"], penalties=[]))
    assert "no visa or clearance" in r


def test_no_description_uses_reduced_confidence_wording():
    """Rule 3 — must not imply skills were compared and found lacking."""
    r = compose_reason(_ev(band=None, description_captured=False))
    assert "no description" in r.lower() or "without a description" in r.lower()


def test_no_description_never_claims_a_skill_match():
    r = compose_reason(_ev(band=None, description_captured=False,
                           matched=["dbt"]))
    assert "dbt" not in r


def test_stretch_explains_what_was_missing():
    r = compose_reason(_ev(band="STRETCH", matched=[],
                           penalties=["frontend focus"]))
    assert "frontend focus" in r


def test_no_matches_does_not_claim_matches():
    r = compose_reason(_ev(band="STRETCH", matched=[]))
    assert "matches" not in r.lower()


def test_sentence_never_ends_with_a_separator():
    for ev in (_ev(matched=["dbt"]), _ev(band="STRETCH", matched=[]),
               _ev(band=None, description_captured=False)):
        assert not compose_reason(ev).rstrip().endswith(("·", ",", ";"))


def test_sentence_is_not_empty_for_any_input():
    assert compose_reason(_ev(band="STRETCH", matched=[], penalties=[],
                              seniority="mid")).strip()
