"""Tests for src/scoring/matching.py — the scoring rules, on their own.

These are the rules a future reader will argue with, so they are tested
against plain data rather than through the Scorer.
"""
from src.scoring.matching import has_term, significant, title_tier, tokens

_STOP = ["the", "and", "for", "senior", "junior", "lead", "staff"]


def _role(title, *aliases):
    return {"title": title, "aliases": list(aliases)}


# ── tokens / significant ──────────────────────────────────────────────────────

def test_tokens_lowercases_and_splits_on_punctuation():
    assert tokens("Senior Engineer, Analytics") == ["senior", "engineer",
                                                    "analytics"]


def test_tokens_keeps_symbols_that_are_part_of_a_name():
    assert tokens("C# and C++ developer") == ["c#", "and", "c++", "developer"]


def test_significant_drops_short_tokens_and_stopwords():
    assert significant("Senior BI Developer", _STOP) == ["developer"]


# ── has_term ──────────────────────────────────────────────────────────────────

def test_has_term_matches_on_word_boundaries():
    assert has_term("opt", "cpt or opt candidates")
    assert not has_term("opt", "we will optimize the query")


def test_has_term_handles_multi_word_terms():
    assert has_term("power bi", "you will build power bi dashboards")


def test_has_term_matches_a_term_ending_in_a_symbol():
    assert has_term("c++", "we use c++ daily")
    assert has_term("c#", "we use c# daily")


def test_has_term_does_not_match_a_longer_word_sharing_a_symbol_prefix():
    assert not has_term("c++", "we use c++x daily")


# ── title_tier ────────────────────────────────────────────────────────────────

def test_an_exact_title_is_the_top_tier():
    assert title_tier("Senior Data Engineer",
                      [_role("Data Engineer")], _STOP) == "exact"


def test_an_alias_also_counts_as_exact():
    roles = [_role("BI Developer", "business intelligence developer")]
    assert title_tier("Business Intelligence Developer Lead",
                      roles, _STOP) == "exact"


def test_reordered_tokens_are_the_second_tier():
    """`Senior Engineer, Analytics` is the same job as `Analytics Engineer`."""
    assert title_tier("Senior Engineer, Analytics",
                      [_role("Analytics Engineer")], _STOP) == "all_tokens"


def test_a_seniority_prefix_on_the_target_role_does_not_block_a_match():
    """Seniority is scored separately, so it is a stopword here."""
    assert title_tier("Data Engineer",
                      [_role("Senior Data Engineer")], _STOP) == "all_tokens"


def test_one_shared_token_is_the_third_tier():
    assert title_tier("Data Scientist",
                      [_role("Data Engineer")], _STOP) == "some_tokens"


def test_a_single_token_target_cannot_reach_the_second_tier():
    """`BI Developer` reduces to one significant token, so `Frontend
    Developer` must not score as if the whole role matched."""
    assert title_tier("Frontend Developer",
                      [_role("BI Developer")], _STOP) == "some_tokens"


def test_nothing_in_common_is_the_floor():
    assert title_tier("Warehouse Associate",
                      [_role("Analytics Engineer")], _STOP) == "none"


def test_the_best_of_several_target_roles_wins():
    roles = [_role("Product Analyst"), _role("Data Engineer")]
    assert title_tier("Data Engineer II", roles, _STOP) == "exact"


def test_no_target_roles_is_the_floor_not_a_crash():
    assert title_tier("Data Engineer", [], _STOP) == "none"


def test_an_empty_title_is_the_floor_not_a_crash():
    assert title_tier("", [_role("Data Engineer")], _STOP) == "none"


# ── seniority_band / band_distance ─────────────────────────────────────────────

from src.scoring.matching import band_distance, seniority_band

_SENIORITY = {
    "senior_keywords": ["senior", "sr.", "staff", "principal", "lead",
                        "manager", "director", "head of", "vp ",
                        "vice president"],
    "junior_keywords": ["junior", "jr.", "intern", "entry", "associate "],
    "exec_keywords":   ["vp ", "vice president", "director", "head of",
                        "executive"],
}


def test_a_plain_title_reads_as_mid():
    assert seniority_band("Data Engineer", _SENIORITY) == "mid"


def test_senior_is_recognised():
    assert seniority_band("Senior Data Engineer", _SENIORITY) == "senior"


def test_junior_is_recognised():
    assert seniority_band("Junior Data Engineer", _SENIORITY) == "junior"


def test_exec_beats_senior_when_a_title_reads_as_both():
    """`Director` is in both lists. An exec title is an exec title."""
    assert seniority_band("Director of Data", _SENIORITY) == "exec"


def test_an_empty_title_reads_as_mid():
    assert seniority_band("", _SENIORITY) == "mid"


def test_the_same_band_is_no_distance():
    assert band_distance("senior", "senior") == 0


def test_neighbouring_bands_are_one_apart():
    assert band_distance("mid", "senior") == 1
    assert band_distance("senior", "mid") == 1


def test_the_ends_of_the_scale_are_far_apart():
    assert band_distance("junior", "exec") == 3


def test_an_unknown_band_is_treated_as_mid():
    """A resume saved before the seniority field existed must not crash."""
    assert band_distance("wizard", "mid") == 0
    assert band_distance(None, "senior") == 1


from src.scoring.matching import (gaps, mismatch_penalty, resume_terms,
                                  skill_hits)

_SKILL_SCORES = {"core": 5, "working": 2, "cap": 20}
_MISMATCH = {"min_tools": 4, "hard_ratio": 0.25, "hard_value": 20,
             "soft_ratio": 0.5, "soft_value": 10}
_TOOLS = ["snowflake", "databricks", "spark", "kafka", "airflow", "react",
          "angular", "terraform"]


def _skill(name, tier="core", *aliases):
    return {"name": name, "tier": tier, "aliases": list(aliases)}


# ── resume_terms ──────────────────────────────────────────────────────────────

def test_resume_terms_collects_names_and_aliases_lowercased():
    skills = [_skill("Power BI", "core", "PowerBI", "DAX")]
    assert resume_terms(skills) == {"power bi", "powerbi", "dax"}


def test_resume_terms_of_nothing_is_empty():
    assert resume_terms([]) == set()


# ── skill_hits ────────────────────────────────────────────────────────────────

def test_a_named_skill_is_matched_and_scored():
    matched, points = skill_hits("we run airflow daily",
                                 [_skill("Airflow")], _SKILL_SCORES)
    assert matched == ["Airflow"]
    assert points == 5


def test_an_alias_matches_but_the_display_name_is_reported():
    """The reason sentence should read like the resume, not like the JD."""
    matched, _ = skill_hits("heavy dax work ahead",
                            [_skill("Power BI", "core", "dax")], _SKILL_SCORES)
    assert matched == ["Power BI"]


def test_a_working_skill_is_worth_less_than_a_core_one():
    _, core = skill_hits("airflow", [_skill("Airflow", "core")], _SKILL_SCORES)
    _, working = skill_hits("airflow", [_skill("Airflow", "working")],
                            _SKILL_SCORES)
    assert core > working


def test_unnamed_skills_score_nothing():
    matched, points = skill_hits("we use spreadsheets",
                                 [_skill("Airflow")], _SKILL_SCORES)
    assert matched == []
    assert points == 0


def test_the_skill_total_is_capped():
    many = [_skill(f"Tool{i}") for i in range(10)]
    body = " ".join(f"tool{i}" for i in range(10))
    _, points = skill_hits(body, many, _SKILL_SCORES)
    assert points == _SKILL_SCORES["cap"]


def test_core_skills_are_reported_before_working_ones():
    skills = [_skill("Tableau", "working"), _skill("Power BI", "core")]
    matched, _ = skill_hits("tableau and power bi", skills, _SKILL_SCORES)
    assert matched == ["Power BI", "Tableau"]


# ── gaps ──────────────────────────────────────────────────────────────────────

def test_a_tool_in_the_post_that_is_not_yours_is_a_gap():
    assert "snowflake" in gaps("we run snowflake", _TOOLS, {"airflow"})


def test_a_tool_you_have_is_not_a_gap():
    assert gaps("we run airflow", _TOOLS, {"airflow"}) == []


def test_gaps_come_from_the_description_only():
    """The title is not evidence of a tool being used."""
    assert gaps("", _TOOLS, set()) == []


# ── mismatch_penalty ──────────────────────────────────────────────────────────

def test_too_few_tools_named_is_never_a_mismatch():
    """Three tools is too small a sample to conclude anything."""
    body = "we use snowflake, spark and kafka"
    assert mismatch_penalty(body, _TOOLS, set(), _MISMATCH) == 0


def test_a_dense_post_with_none_of_your_tools_lands_hard():
    body = "react, angular, terraform and kafka experience required"
    assert mismatch_penalty(body, _TOOLS, {"airflow"},
                            _MISMATCH) == _MISMATCH["hard_value"]


def test_a_dense_post_with_some_of_your_tools_lands_softly():
    """Four named, one of them yours — a quarter, under the soft threshold."""
    body = "react, angular, terraform and airflow experience required"
    assert mismatch_penalty(body, _TOOLS, {"airflow"},
                            _MISMATCH) == _MISMATCH["soft_value"]


def test_a_post_that_is_mostly_your_tools_is_not_penalised():
    body = "snowflake, spark, kafka and airflow"
    mine = {"snowflake", "spark", "kafka"}
    assert mismatch_penalty(body, _TOOLS, mine, _MISMATCH) == 0


def test_the_same_post_lands_softly_for_someone_whose_stack_it_is():
    """The point of the ratio: a React post is only a mismatch for a
    non-React person."""
    body = "react, angular, terraform and kafka experience required"
    data_person = mismatch_penalty(body, _TOOLS, {"airflow"}, _MISMATCH)
    react_person = mismatch_penalty(body, _TOOLS,
                                    {"react", "angular", "terraform"},
                                    _MISMATCH)
    assert data_person > react_person == 0
