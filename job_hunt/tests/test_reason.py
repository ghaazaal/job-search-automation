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


def test_a_verified_clean_run_says_open_to_your_location():
    r = compose_reason(_ev(matched=["dbt"], penalties=[],
                           eligibility_verified=True))
    assert "open to your location" in r


def test_an_unverified_clean_run_says_not_verified():
    """No penalties fired, but nothing positively confirmed eligibility
    either — unchecked must not read as fine."""
    r = compose_reason(_ev(matched=["dbt"], penalties=[]))
    assert "location eligibility not verified" in r
    assert "no visa or clearance limits found" not in r


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


def test_the_matched_clause_names_the_resume():
    """A person with three resumes needs to know which one this was."""
    sentence = compose_reason({
        "description_captured": True,
        "matched": ["dbt", "Airflow"],
        "seniority": "senior",
        "penalties": [],
        "resume_label": "bi developer",
    })
    assert "from your bi developer resume" in sentence


def test_an_unlabelled_resume_still_reads_as_a_sentence():
    sentence = compose_reason({
        "description_captured": True,
        "matched": ["dbt"],
        "seniority": "mid",
        "penalties": [],
    })
    assert "from your resume" in sentence


def test_the_resume_is_named_even_when_nothing_matched():
    sentence = compose_reason({
        "description_captured": True,
        "matched": [],
        "seniority": "senior",
        "penalties": [],
        "resume_label": "data engineer",
    })
    assert "your data engineer resume" in sentence
