"""Tests for src/scoring/platforms.py — which names are talent platforms."""
import pytest

from src.scoring.platforms import is_talent_platform


@pytest.mark.parametrize("name", ["Proxify", "Proxify AB", "TOPTAL, Inc.",
                                  "micro1", "Mercor", "Lemon.io"])
def test_listed_platforms_match_whatever_their_suffix(name):
    assert is_talent_platform(name)


@pytest.mark.parametrize("name", ["Toptal Recruiting Partners",
                                  "Nigel Wright Recruitment",
                                  "Lemon Law Group Partners, PLC",
                                  "Acme", "", None])
def test_anything_else_is_an_employer(name):
    """Exact equality after folding — a name merely containing a platform's
    name is a different company."""
    assert not is_talent_platform(name)


def test_the_list_can_be_supplied():
    cfg = {"names": ["Jobgether"], "legal_suffixes": ["ab"]}
    assert is_talent_platform("Jobgether AB", cfg)
    assert not is_talent_platform("Proxify", cfg)
