"""The title gate. Every trap here reached the live map before it existed."""
import pytest
import yaml

from src.scoring.relevance import is_relevant

CFG = yaml.safe_load(
    open("vocabulary.yaml", encoding="utf-8"))["roles"]


@pytest.mark.parametrize("title", [
    "Data Analyst",
    "Senior Data Engineer",
    "BI Developer",
    "Analytics Engineer - AI Trainer",
    "Data Analyst II - Marketing & Customer Analytics",
    "Principal Business Intelligence Analyst",
    "Senior Power BI Data Analyst - Remote Work",
])
def test_real_roles_pass(title):
    assert is_relevant(title, CFG) is True


@pytest.mark.parametrize("title", [
    "Quantitative Analyst",
    "Cloud, Data Center & Edge Infrastructure Lead",
    "Urban Data Platforms, Digital Twins & AI Governance",
    "Senior Mechanical Engineer - Data Centers",
    "Electrical Engineer, Data Centers - Remote (U.S.)",
    "Nurse Practitioner - Telehealth HRT part time",
    "Fleet Parking Specialist",
    "Travel Advisor",
    "Online SAT Test Prep Expert Tutor",
    "Territory Sales Manager",
])
def test_traps_are_rejected(title):
    assert is_relevant(title, CFG) is False


def test_exclusion_beats_inclusion():
    """A data-centre job is a data-centre job however it is titled."""
    assert is_relevant("Data Engineer, Data Center Operations", CFG) is False


def test_exclusion_catches_the_plural_form():
    """Both data-centre titles in the live store were plural, and the
    word-bounded singular phrase does not match a trailing "s"."""
    assert is_relevant("Data Engineer, Data Centers Operations", CFG) is False


def test_empty_title_is_not_relevant():
    assert is_relevant("", CFG) is False
    assert is_relevant(None, CFG) is False


def test_no_include_list_accepts_everything_not_excluded():
    """An unconfigured gate must not silently reject the whole run."""
    assert is_relevant("Anything At All", {"include": [], "exclude": []}) is True
