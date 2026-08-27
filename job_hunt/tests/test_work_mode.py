"""Tests for matching.work_mode and matching.location_country.

Both are pure: text in, fact out. Configs are inlined so each test states
what it exercises; test_vocabulary.py guards the real file.
"""
from src.scoring.matching import location_country, work_mode

_MODE_CFG = {
    "remote_phrases": ["fully remote", "remote position", "work from home"],
    "hybrid_phrases": ["hybrid work", "hybrid role",
                       "days a week in the office"],
    "onsite_phrases": ["on-site role", "onsite work required",
                       "must work onsite"],
}

_LOC_CFG = {
    "countries": {
        "am": ["armenia"],
        "us": ["us", "usa", "u.s.", "united states"],
        "gb": ["uk", "united kingdom", "britain", "england"],
        "ge": ["georgia"],
        "in": ["india"],
        "nl": ["netherlands", "holland"],
    },
    "us_states": ["ny", "wa", "ga", "tx", "in"],
    "us_state_names": ["georgia", "texas", "new york"],
}


# ── work_mode ────────────────────────────────────────────────────────────────

def test_each_phrase_category_is_detected():
    assert work_mode("this is a fully remote team.", _MODE_CFG) == "remote"
    assert work_mode("hybrid work, 2 days a week in the office.",
                     _MODE_CFG) == "hybrid"
    assert work_mode("onsite work required for this analyst position.",
                     _MODE_CFG) == "onsite"


def test_bare_words_never_fire():
    """'hybrid cloud', 'remote teams', 'on-site gym' are the false
    positives phrase-only matching exists to survive."""
    assert work_mode("experience with hybrid cloud required.",
                     _MODE_CFG) is None
    assert work_mode("you will manage remote teams.", _MODE_CFG) is None
    assert work_mode("perks include an on-site gym.", _MODE_CFG) is None


def test_conflicting_evidence_claims_nothing():
    body = "remote position or hybrid work, your choice."
    assert work_mode(body, _MODE_CFG) is None


def test_no_mode_word_claims_nothing():
    assert work_mode("we need power bi and sql.", _MODE_CFG) is None


def test_empty_config_is_silent():
    assert work_mode("fully remote.", {}) is None


def test_case_is_irrelevant():
    assert work_mode("This is a FULLY REMOTE role.", _MODE_CFG) == "remote"


# ── location_country ─────────────────────────────────────────────────────────

def test_a_country_name_resolves():
    assert location_country("Bengaluru, Karnataka, India", _LOC_CFG) == "in"


def test_the_rightmost_country_wins():
    """Locations end with the country: 'Georgia, US' still resolves via
    the unambiguous 'us' match. 'Tbilisi, Georgia' does NOT resolve to
    'ge' — georgia is ambiguous with the US state both directions, so
    silence is the design (see test_the_georgia_ambiguity_is_silent_both_ways)."""
    assert location_country("Georgia, US", _LOC_CFG) == "us"
    assert location_country("Tbilisi, Georgia", _LOC_CFG) is None


def test_a_us_state_code_resolves_to_us():
    assert location_country("New York, NY", _LOC_CFG) == "us"
    assert location_country("Seattle, WA", _LOC_CFG) == "us"


def test_remote_and_unknown_stay_none():
    assert location_country("Remote", _LOC_CFG) is None
    assert location_country("Narnia", _LOC_CFG) is None
    assert location_country("", _LOC_CFG) is None
    assert location_country(None, _LOC_CFG) is None


def test_a_state_code_inside_a_word_does_not_fire():
    """'ny' must not fire inside 'company' — word boundaries hold."""
    assert location_country("Acme Company HQ", _LOC_CFG) is None


def test_a_state_code_that_is_also_a_country_code_claims_nothing():
    """'Chennai, IN' abbreviates India; 'Gary, IN' abbreviates Indiana.
    The bare token cannot tell them apart, so it must claim nothing —
    a wrong 'us' here corrupts the drop decision."""
    assert location_country("Chennai, IN", _LOC_CFG) is None
    assert location_country("Gary, IN", _LOC_CFG) is None


def test_empty_location_config_is_silent():
    assert location_country("New York, NY", {}) is None


def test_a_us_state_full_name_resolves():
    assert location_country("Austin, Texas", _LOC_CFG) == "us"


def test_the_georgia_ambiguity_is_silent_both_ways():
    """US state or the country? A wrong answer either way corrupts the
    drop decision, so both stay silent."""
    assert location_country("Atlanta, Georgia", _LOC_CFG) is None
    assert location_country("Tbilisi, Georgia", _LOC_CFG) is None


def test_ordinary_two_letter_words_do_not_resolve():
    """'La Paz' and 'Or Yehuda' contain la/or — place-name particles,
    not state codes. The scan is anchored to the final segment."""
    assert location_country("La Paz", _LOC_CFG) is None
    assert location_country("Or Yehuda", _LOC_CFG) is None


def test_a_zip_suffix_still_resolves():
    assert location_country("Austin, TX 78701", _LOC_CFG) == "us"


def test_an_ambiguous_state_code_is_silent_even_in_city_code_form():
    """'San Francisco, CA' and 'Chennai, IN' are structurally identical —
    only city knowledge separates them, and we have none. Accepted
    silence; the job is kept and flagged, never dropped on a coin-flip."""
    assert location_country("San Francisco, CA", _LOC_CFG) is None
    assert location_country("Chennai, IN", _LOC_CFG) is None


def test_substring_matching_would_be_wrong():
    """Mutation killers: phrase matching must stay word-bounded.

    has_term("remote position", "...remote positions open.") is False:
    the lookahead after "position" sees "s", so the bounded pattern does
    not match "remote positions" — a substring-matching mutant would
    wrongly match and return "remote"."""
    assert work_mode("we have 3 remote positions open.", _MODE_CFG) is None
    assert location_country("Indiaville", _LOC_CFG) is None


def test_a_us_city_named_after_a_country_is_us():
    """'Holland, MI' is Michigan, not the Netherlands — when the tail
    independently says us, it outranks a country-name match earlier in
    the string."""
    assert location_country("Holland, NY", _LOC_CFG) == "us"
    assert location_country("Georgia, US", _LOC_CFG) == "us"


def test_jd_header_idioms_are_detected():
    """'Work setup & shift: Onsite' is how BPO postings state the mode —
    only matchable now that descriptions arrive unmangled."""
    from pathlib import Path

    import yaml
    path = Path(__file__).parent.parent / "vocabulary.yaml"
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))["work_mode"]
    assert work_mode("work setup & shift: onsite. why join us?", cfg) == "onsite"
    assert work_mode("work setup: hybrid, 3 days on site.", cfg) == "hybrid"
    assert work_mode("work setup & shift: remote, night shift.", cfg) == "remote"
