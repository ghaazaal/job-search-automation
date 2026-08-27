"""Every string here was returned by a live remote-board run."""
import pytest
import yaml

from src.scoring.location_scope import scope_verdict

VOCAB = yaml.safe_load(open("vocabulary.yaml", encoding="utf-8"))
CFG = VOCAB["location_scope"]
# `location_country` and region membership both come from eligibility's
# country and region tables, not this section's, so the parser takes
# both configs.
GEO = VOCAB["eligibility"]


@pytest.mark.parametrize("text", [
    "Anywhere in the World",
    "anywhere in the world",
    "Worldwide",
])
def test_worldwide_is_open_to_everyone(text):
    assert scope_verdict(text, "am", CFG, GEO) == "open"


def test_a_foreign_country_is_closed():
    assert scope_verdict("United States", "am", CFG, GEO) == "closed"


def test_your_own_country_is_open():
    assert scope_verdict("Armenia", "am", CFG, GEO) == "open"


def test_a_region_list_is_checked_for_membership():
    """Region membership reads eligibility.regions, the one reviewed
    table - not a second copy. That table's "europe" deliberately
    excludes the Caucasus (see its own comment), so Armenia is not a
    member of any region this text names; absence claims nothing."""
    text = "Europe, North America, Latin America, APAC"
    assert scope_verdict(text, "gb", CFG, GEO) == "open"     # GB is in eligibility's "europe"
    assert scope_verdict(text, "am", CFG, GEO) == "unknown"  # Armenia is in none of these named regions


def test_a_region_not_naming_the_user_is_unknown_not_closed():
    """eligibility.regions documents itself as non-exhaustive - a region
    can genuinely include a country it doesn't enumerate. Absence from a
    partial list must never be read as exclusion. India is not in
    eligibility's EMEA list."""
    assert scope_verdict("EMEA", "in", CFG, GEO) == "unknown"


def test_timezone_band_is_computed_not_skipped():
    """Yerevan is UTC+4; CET+3 reaches UTC+4. This is a real match."""
    assert scope_verdict("Time zone: CET (+/- 3 hours)", "am", CFG, GEO) == "open"
    assert scope_verdict("Time zone: CET (+/- 3 hours)", "us", CFG, GEO) == "closed"


def test_timezone_band_with_no_offset_on_file_is_unknown():
    """New Zealand is a real country in eligibility's regions but has no
    entry in country_utc_offset - the band check must not guess."""
    assert scope_verdict("Time zone: CET (+/- 3 hours)", "nz", CFG, GEO) == "unknown"


def test_silence_claims_nothing():
    assert scope_verdict("", "am", CFG, GEO) == "unknown"
    assert scope_verdict("Flexible / Remote", "am", CFG, GEO) == "unknown"


def test_unset_user_country_claims_nothing():
    """Same discipline as geo_verdict - the check cannot run."""
    assert scope_verdict("United States", "", CFG, GEO) == "unknown"
