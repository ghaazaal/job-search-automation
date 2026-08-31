"""Tests for src/scoring/geo.py — is this place the user's?

The design insight (the user's, 2026-08-28): eligibility never needs to
know WHICH Dublin a posting means. Every Dublin on earth is not Armenia,
so for an Armenian user the answer is "foreign" without disambiguating.
Ambiguity only matters when one candidate IS the user's own country — and
then the honest answer is silence, the rule this codebase already has.
"""
from pathlib import Path

import pytest
import yaml

from src.scoring.geo import location_relation

_CFG = yaml.safe_load(
    (Path(__file__).parent.parent / "vocabulary.yaml")
    .read_text(encoding="utf-8"))["eligibility"]


# --- foreign: no candidate is the user's country -----------------------

@pytest.mark.parametrize("location", [
    # Every one a live value the old hand-kept tables could not read.
    "Dublin, CA",                        # ambiguous city - but never Armenia
    "Bolingbrook, IL",
    "New York City Metropolitan Area",
    "Greater Hyderabad Area",
    "Springfield",                       # 8 places, all of them the US
    "Pueblo-Cañon City Area",
    "Aguadilla, Puerto Rico",
    "Istanbul, Istanbul, Türkiye",
    "Canada",
    "London, England, United Kingdom",
])
def test_a_place_that_cannot_be_the_users_is_foreign(location):
    assert location_relation(location, "am", _CFG) == "foreign"


# --- local: the user's own place ---------------------------------------

@pytest.mark.parametrize("location", [
    "Yerevan, Armenia",
    "Yerevan, Yerevan, Armenia",
    "Armenia",
])
def test_the_users_own_place_is_local(location):
    assert location_relation(location, "am", _CFG) == "local"


# --- silence: ambiguity that touches the user, or no place at all ------

def test_ambiguity_touching_the_users_own_country_stays_silent():
    """"Georgia" is a country and a US state. For a Georgian user it
    might be theirs, so it claims nothing - the documented rule."""
    assert location_relation("Georgia", "ge", _CFG) is None


def test_the_same_ambiguity_is_foreign_for_everyone_else():
    """For an Armenian user, both Georgias are elsewhere."""
    assert location_relation("Georgia", "am", _CFG) == "foreign"


@pytest.mark.parametrize("location", [
    "Flexible / Remote",
    "Anywhere in the World",
    "Time zone: CET (+/- 3 hours)",
    "",
    None,
])
def test_a_non_place_claims_nothing(location):
    assert location_relation(location, "am", _CFG) is None


def test_no_user_country_claims_nothing():
    assert location_relation("Yerevan, Armenia", "", _CFG) is None


# --- the dataset covers what the hand table never could ----------------

@pytest.mark.parametrize("location,relation", [
    ("Tunis, Tunis, Tunisia", "foreign"),
    ("Montevideo, Montevideo, Uruguay", "foreign"),
    ("Skopje, Skopje Statistical Region, North Macedonia", "foreign"),
    ("Hanoi Capital Region", "foreign"),
    ("Greater Buenos Aires", "foreign"),
    ("Tbilisi, Georgia", "foreign"),     # city disambiguates the country
])
def test_places_beyond_the_hand_tables_resolve(location, relation):
    assert location_relation(location, "am", _CFG) == relation
