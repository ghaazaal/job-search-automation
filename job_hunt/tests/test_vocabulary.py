"""vocabulary.yaml holds language and market facts, never a person.

The whole point of the split is that nothing in here describes who is
searching. A test is the only thing that keeps a personal skill list from
creeping back in the next time someone wants to nudge a score.
"""
from pathlib import Path

import yaml

_PATH = Path(__file__).parent.parent / "vocabulary.yaml"


def _vocabulary() -> dict:
    with open(_PATH, "r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def test_it_loads():
    assert isinstance(_vocabulary(), dict)


def test_it_keeps_the_sections_the_scorer_needs():
    vocab = _vocabulary()
    assert {"stopwords", "seniority", "market_tools", "mismatch", "penalties",
            "title_scores", "seniority_scores",
            "skill_scores"} <= set(vocab)


def test_the_personal_sections_are_gone():
    """`skills` and `title_groups` described one person. They live in the
    resume now, and must not come back here."""
    vocab = _vocabulary()
    assert "skills" not in vocab
    assert "title_groups" not in vocab


def test_the_hardcoded_domain_penalties_are_gone():
    """legacy_tech and frontend_tech said React and COBOL are bad, which is
    only true for a data person. The mismatch ratio replaces them."""
    penalties = _vocabulary()["penalties"]
    assert "legacy_tech" not in penalties
    assert "frontend_tech" not in penalties


def test_the_point_values_cover_every_tier():
    vocab = _vocabulary()
    assert {"exact", "all_tokens", "some_tokens",
            "none"} == set(vocab["title_scores"])
    assert {"same", "one_apart", "far"} == set(vocab["seniority_scores"])
    assert {"core", "working", "cap"} == set(vocab["skill_scores"])


def test_the_mismatch_thresholds_are_configurable():
    mismatch = _vocabulary()["mismatch"]
    assert {"min_tools", "hard_ratio", "hard_value",
            "soft_ratio", "soft_value"} == set(mismatch)
    assert mismatch["hard_ratio"] < mismatch["soft_ratio"]


def test_the_eligibility_section_holds_market_facts():
    """Country names, region membership and restriction phrasing are
    language facts, so they live here — but nothing in them may describe a
    particular person."""
    eligibility = _vocabulary()["eligibility"]
    assert {"countries", "templates", "list_phrases", "anywhere_words",
            "regions"} == set(eligibility)
    assert all("{country}" in t for t in eligibility["templates"])
    # A list phrase introduces a list — it must not carry the slot itself.
    assert all("{country}" not in p for p in eligibility["list_phrases"])
    # YAML 1.1 parses a bare `no:` (Norway) or `on:` as a boolean. Every
    # code must arrive as a string — quote any future code YAML would eat.
    assert all(isinstance(code, str) for code in eligibility["countries"])
    assert all(isinstance(names, list) and names
               for names in eligibility["countries"].values())
    for region in eligibility["regions"]:
        assert {"names", "codes"} == set(region)
        assert region["names"] and region["codes"]
        assert all(isinstance(code, str) for code in region["codes"])


def test_the_geo_penalties_are_configured():
    penalties = _vocabulary()["penalties"]
    assert penalties["geo_restricted"] == penalties["clearance"]
    assert penalties["wrong_board"] < penalties["geo_restricted"]
