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
