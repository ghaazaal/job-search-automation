"""Tests for matching.geo_verdict — what a posting says about where it hires.

The rule is pure: body text in, (verdict, detail) out. The config is
inlined here rather than loaded from vocabulary.yaml so each test states
exactly which phrasings it exercises; test_vocabulary.py guards the real
file, and test_scorer_geo.py proves the shipped file works end to end.
"""
from src.scoring.matching import geo_verdict

_CFG = {
    "countries": {
        "am": ["armenia"],
        "us": ["us", "usa", "u.s.", "united states"],
        "gb": ["uk", "united kingdom", "britain", "england"],
        "ca": ["canada"],
        "de": ["germany"],
        "pl": ["poland"],
    },
    "templates": [
        "must be based in {country}",
        "must reside in {country}",
        "based in {country} only",
        "be located in {country}",
        "authorized to work in {country}",
        "eligible to work in {country}",
        "work authorization in {country}",
        "{country} citizens only",
        "{country} residents only",
    ],
    "list_phrases": [
        "open to candidates in",
        "we can hire in",
        "eligible countries",
    ],
    "anywhere_words": ["worldwide", "anywhere", "globally"],
    "eligible_phrases": ["open to candidates worldwide", "anywhere in the world"],
    "regions": [
        {"names": ["emea"], "codes": ["am", "gb", "de", "pl"]},
        {"names": ["europe"], "codes": ["gb", "de", "pl"]},
        {"names": ["north america"], "codes": ["us", "ca"]},
        {"names": ["latam", "latin america"], "codes": ["mx", "br"]},
    ],
}


# ── restrictions ─────────────────────────────────────────────────────────────

def test_a_stated_restriction_names_the_country():
    body = "this role is remote but you must be based in the uk."
    assert geo_verdict(body, "am", _CFG) == ("restricted", "UK")


def test_citizens_only_phrasing_fires():
    assert geo_verdict("us citizens only, no sponsorship.",
                       "am", _CFG) == ("restricted", "US")


def test_the_article_is_optional_and_long_names_resolve_to_the_short_one():
    """'the united states' must match the `united states` entry, and the
    display name is the country's first listed name — 'US', not the
    phrasing that happened to match."""
    body = "applicants must be based in the united states."
    assert geo_verdict(body, "am", _CFG) == ("restricted", "US")


def test_your_own_country_is_not_a_restriction():
    assert geo_verdict("must be based in armenia.",
                       "am", _CFG) == ("unknown", None)


def test_no_user_country_claims_nothing():
    """With no country on file the check cannot run, so it must not fire —
    a claim we cannot ground is worse than silence."""
    assert geo_verdict("must be based in the uk.", "", _CFG) == ("unknown", None)
    assert geo_verdict("must be based in the uk.", None, _CFG) == ("unknown", None)


def test_a_plain_mention_is_not_a_restriction():
    assert geo_verdict("we serve clients across the us and europe.",
                       "am", _CFG) == ("unknown", None)


def test_word_boundaries_hold_on_short_names():
    """'us' inside another word must not fire — same discipline has_term
    applies to 'opt' inside 'optimize'."""
    assert geo_verdict("the campus residents only lounge is closed.",
                       "am", _CFG) == ("unknown", None)


def test_a_nearby_place_is_not_the_named_country():
    """'new england' must not satisfy an 'england' template — the name
    must sit exactly where the template puts it."""
    assert geo_verdict("must be based in new england.",
                       "am", _CFG) == ("unknown", None)


# ── eligibility lists ────────────────────────────────────────────────────────

def test_a_list_naming_your_country_is_eligible():
    """The v3 case: a country list must be read as a list, never as a
    restriction on whichever foreign name happens to sit first."""
    body = "open to candidates in the uk, armenia and poland."
    assert geo_verdict(body, "am", _CFG) == ("eligible", None)


def test_a_list_without_your_country_is_excluded_in_text_order():
    body = "open to candidates in poland, the uk and germany."
    assert geo_verdict(body, "am", _CFG) == (
        "excluded", "Poland, UK and Germany")


def test_a_long_exclusion_list_is_capped():
    body = "open to candidates in poland, the uk, germany and canada."
    assert geo_verdict(body, "am", _CFG) == (
        "excluded", "Poland, UK, Germany and others")


def test_eligible_anywhere_in_the_body_beats_an_earlier_foreign_list():
    body = "we can hire in the uk. open to candidates in armenia."
    assert geo_verdict(body, "am", _CFG) == ("eligible", None)


def test_an_anywhere_word_inside_a_list_window_is_eligible():
    assert geo_verdict("open to candidates in any country, worldwide.",
                       "am", _CFG) == ("eligible", None)


def test_a_standalone_worldwide_phrase_is_eligible():
    """No list window opens here — "open to candidates in" needs the "in".
    The standalone phrase itself is the evidence."""
    assert geo_verdict("open to candidates worldwide.",
                       "am", _CFG) == ("eligible", None)


def test_a_stray_globally_does_not_mask_a_restriction():
    """Anywhere-words are window-scoped on purpose: "globally" in company
    boilerplate must not settle eligibility before the restriction scan."""
    assert geo_verdict("we operate globally. us citizens only.",
                       "am", _CFG) == ("restricted", "US")


def test_a_region_that_includes_you_is_eligible():
    assert geo_verdict("open to candidates in emea.",
                       "am", _CFG) == ("eligible", None)


def test_a_region_without_you_stays_silent_never_excluded():
    """Region membership is fuzzy at the edges — eligible-only evidence.
    `europe` omits `am` in this config, and the answer is silence, not a
    flag."""
    assert geo_verdict("open to candidates in europe.",
                       "am", _CFG) == ("unknown", None)


def test_north_america_is_a_region_not_the_us_name():
    """A US user is eligible for a 'north america' list via the region
    entry — `america` is deliberately not a us alias."""
    assert geo_verdict("open to candidates in north america.",
                       "us", _CFG) == ("eligible", None)


def test_a_continent_phrase_is_not_the_us():
    """'latin america' must not read as the US: the latam region omits
    `us`, no country name matches, and the verdict is silence."""
    assert geo_verdict("open to candidates in latin america.",
                       "us", _CFG) == ("unknown", None)


def test_a_list_of_unrecognised_countries_stays_silent():
    assert geo_verdict("open to candidates in narnia.",
                       "am", _CFG) == ("unknown", None)


def test_a_stated_restriction_beats_an_excluding_list():
    body = "us citizens only. open to candidates in the uk."
    assert geo_verdict(body, "am", _CFG) == ("restricted", "US")


def test_empty_config_is_silent():
    assert geo_verdict("must be based in the uk.", "am", {}) == ("unknown", None)


# ── exclusion windows (range-based, unlimited user-country scan) ───────────

def test_a_single_country_exclusion_list():
    assert geo_verdict("open to candidates in germany.",
                       "am", _CFG) == ("excluded", "Germany")


def test_exclusion_names_follow_text_order_across_windows():
    """The first window ('eligible countries: germany.') runs out at 400
    chars, well short of the body's end (500 padding chars plus the
    second phrase) — a full window, so the display hedges with "and
    others" even though only two countries were recognised."""
    body = ("eligible countries: germany. " + "x" * 500
            + " open to candidates in poland.")
    assert geo_verdict(body, "am", _CFG) == (
        "excluded", "Germany, Poland and others")


def test_a_long_list_naming_you_late_is_still_eligible():
    """The window must be big enough that a real-world list cannot flip
    to 'excluded' while explicitly naming the user."""
    others = ["poland", "germany", "canada", "the uk"] * 5
    body = "open to candidates in " + ", ".join(others) + ", armenia."
    assert geo_verdict(body, "am", _CFG) == ("eligible", None)


def test_a_truncated_list_naming_you_later_is_eligible():
    """The user's own country is scanned to end of body — a long list that
    names them past any window limit must never read as exclusion."""
    tail = ", ".join(f"country{i}" for i in range(80))
    body = f"open to candidates in poland, germany, {tail}, armenia."
    assert geo_verdict(body, "am", _CFG) == ("eligible", None)


def test_a_truncated_list_without_you_hedges_its_exclusion():
    """When the window ran full, the enumeration may continue — the claim
    must say 'and others' even though only two countries were recognised."""
    tail = ", ".join(f"country{i}" for i in range(80))
    body = f"open to candidates in poland, germany, {tail}, narnia."
    assert geo_verdict(body, "am", _CFG) == (
        "excluded", "Poland, Germany and others")


def test_a_newline_bulleted_list_naming_you_is_eligible():
    """Bullet lists separated by newlines were the terminator heuristic's
    failure mode — the unlimited user scan must handle them."""
    others = "\n".join(f"- country{i}" for i in range(30))
    body = f"eligible countries:\n- poland\n- germany\n{others}\n- armenia\n"
    assert geo_verdict(body, "am", _CFG) == ("eligible", None)


def test_a_repeated_country_keeps_its_earliest_position():
    """Padded short enough that the first window still reaches the body's
    end (no 'and others' hedge) — this isolates the ordering bug from the
    'and others' hedge tested separately above."""
    body = ("we can hire in poland and germany. " + "x " * 150
            + "open to candidates in poland.")
    assert geo_verdict(body, "am", _CFG) == (
        "excluded", "Poland and Germany")


def test_company_boilerplate_does_not_mask_a_restriction():
    assert geo_verdict("we are a worldwide remote company. us citizens only.",
                       "am", _CFG) == ("restricted", "US")


def test_company_location_prose_is_not_a_restriction():
    """'our office is located in germany' describes the company, not the
    candidate — with the anchored template it must stay silent."""
    assert geo_verdict("our office is located in germany but this role "
                       "is fully remote.", "am", _CFG) == ("unknown", None)
