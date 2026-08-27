"""Every string here was returned by a live remote-board run."""
import pytest
import yaml

from src.scoring.location_scope import scope_verdict

VOCAB = yaml.safe_load(open("vocabulary.yaml", encoding="utf-8"))
CFG = VOCAB["location_scope"]
# `location_country` needs the eligibility country tables, not this
# section's, so the parser takes both.
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
    text = "Europe, North America, Latin America, APAC"
    assert scope_verdict(text, "am", CFG, GEO) == "open"    # Armenia is in APAC
    assert scope_verdict(text, "za", CFG, GEO) == "closed"  # South Africa is not


def test_timezone_band_is_computed_not_skipped():
    """Yerevan is UTC+4; CET+3 reaches UTC+4. This is a real match."""
    assert scope_verdict("Time zone: CET (+/- 3 hours)", "am", CFG, GEO) == "open"
    assert scope_verdict("Time zone: CET (+/- 3 hours)", "us", CFG, GEO) == "closed"


def test_silence_claims_nothing():
    assert scope_verdict("", "am", CFG, GEO) == "unknown"
    assert scope_verdict("Flexible / Remote", "am", CFG, GEO) == "unknown"


def test_unset_user_country_claims_nothing():
    """Same discipline as geo_verdict - the check cannot run."""
    assert scope_verdict("United States", "", CFG, GEO) == "unknown"
