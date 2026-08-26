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
    # all()/for over an empty collection passes vacuously — a bad merge
    # that emptied a list would sail through without these.
    assert eligibility["countries"]
    assert eligibility["templates"]
    assert eligibility["list_phrases"]
    assert eligibility["anywhere_words"]
    assert eligibility["eligible_phrases"]
    assert eligibility["regions"]
    assert eligibility["us_state_names"]
    assert all(isinstance(s, str) for s in eligibility["us_state_names"])
    assert {"countries", "templates", "list_phrases", "anywhere_words",
            "eligible_phrases", "ambiguous_names", "regions",
            "us_states", "us_state_names"} == set(eligibility)
    assert all("{country}" in t for t in eligibility["templates"])
    # A list phrase introduces a list — it must not carry the slot itself.
    assert all("{country}" not in p for p in eligibility["list_phrases"])
    assert all("{country}" not in p for p in eligibility["eligible_phrases"])
    # YAML 1.1 parses a bare `no:` (Norway) or `on:` as a boolean. Every
    # code must arrive as a string — quote any future code YAML would eat.
    assert all(isinstance(code, str) for code in eligibility["countries"])
    assert all(isinstance(names, list) and names
               for names in eligibility["countries"].values())
    # An exception list, not a market fact list — empty would be a valid
    # config (no ambiguous names at all), so no non-emptiness assert here.
    assert all(isinstance(n, str) for n in eligibility["ambiguous_names"])
    for region in eligibility["regions"]:
        assert {"names", "codes"} == set(region)
        assert region["names"] and region["codes"]
        assert all(isinstance(code, str) for code in region["codes"])


def test_the_geo_penalties_are_configured():
    penalties = _vocabulary()["penalties"]
    assert penalties["geo_restricted"] == penalties["clearance"]
    assert penalties["wrong_board"] < penalties["geo_restricted"]


def test_the_work_mode_section_holds_role_anchored_phrases():
    """Phrases only, never bare words — bare 'hybrid' fires on 'hybrid
    cloud', bare 'remote' on 'remote teams', bare 'on-site' on 'on-site
    gym'. Single-word entries are how those false positives creep back.

    'telecommute' is a reviewed, named exception: it does not compound
    into unrelated tech-stack or amenity phrases the way hybrid/remote/
    on-site do ('telecommute cloud', 'telecommute teams' are not things
    postings say), so a bare match carries none of the collision risk
    the general ban exists to prevent."""
    work_mode = _vocabulary()["work_mode"]
    assert {"remote_phrases", "hybrid_phrases",
            "onsite_phrases"} == set(work_mode)
    for phrases in work_mode.values():
        assert phrases
        assert all(" " in p or "-" in p or p == "telecommute"
                   for p in phrases), \
            "single bare words are banned here (telecommute is the one " \
            "reviewed exception)"


def test_the_mode_mismatch_penalty_is_configured():
    penalties = _vocabulary()["penalties"]
    assert 0 < penalties["mode_mismatch"] < penalties["geo_restricted"]


def test_us_states_are_two_letter_strings():
    """`in` (Indiana) is not a YAML boolean, but `on`/`no`/`off` would be —
    none of them are US states, and this guard keeps every entry a
    2-letter string if that ever changes."""
    states = _vocabulary()["eligibility"]["us_states"]
    assert states
    assert all(isinstance(s, str) and len(s) == 2 for s in states)
    assert "ny" in states and "dc" in states
