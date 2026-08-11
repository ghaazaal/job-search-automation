"""Tests for src/agents/profile_parser.py.

The normalisation half matters more than the prompt half: an LLM that returns
a bare string where an object belongs must not put a row into the database
that the scorer cannot read.
"""
import json

import pytest

from src.agents.profile_parser import parse_profile
from tests.conftest import MockLLMClient

_GOOD = json.dumps({
    "target_roles": [
        {"title": "BI Developer", "aliases": ["Business Intelligence Developer"]},
        {"title": "Analytics Engineer", "aliases": []}],
    "skills": [
        {"name": "Power BI", "tier": "core", "aliases": ["PowerBI", "DAX"]},
        {"name": "Airflow", "tier": "working", "aliases": []}],
    "seniority": "senior",
})


def test_a_clean_reply_comes_through_whole():
    result = parse_profile("resume text", MockLLMClient(_GOOD))
    assert result["seniority"] == "senior"
    assert [r["title"] for r in result["target_roles"]] == [
        "BI Developer", "Analytics Engineer"]
    assert result["skills"][0]["tier"] == "core"
    assert result["skills"][1]["tier"] == "working"


def test_aliases_are_lowercased_for_matching():
    """The scorer matches lowercase, so the store holds lowercase."""
    result = parse_profile("resume text", MockLLMClient(_GOOD))
    assert result["target_roles"][0]["aliases"] == [
        "business intelligence developer"]
    assert result["skills"][0]["aliases"] == ["powerbi", "dax"]


def test_prose_around_the_json_is_tolerated():
    reply = "Sure! Here you go:\n" + _GOOD + "\nHope that helps."
    assert parse_profile("resume text", MockLLMClient(reply))["seniority"] == "senior"


def test_bare_strings_are_promoted_to_objects():
    reply = json.dumps({"target_roles": ["Data Engineer"],
                        "skills": ["SQL"], "seniority": "mid"})
    result = parse_profile("resume text", MockLLMClient(reply))
    assert result["target_roles"] == [{"title": "Data Engineer", "aliases": []}]
    assert result["skills"] == [{"name": "SQL", "tier": "working", "aliases": []}]


def test_an_unknown_tier_falls_back_to_working():
    reply = json.dumps({"target_roles": [], "seniority": "mid",
                        "skills": [{"name": "SQL", "tier": "expert"}]})
    result = parse_profile("resume text", MockLLMClient(reply))
    assert result["skills"][0]["tier"] == "working"


def test_an_unknown_seniority_falls_back_to_mid():
    reply = json.dumps({"target_roles": [], "skills": [],
                        "seniority": "grand wizard"})
    assert parse_profile("x", MockLLMClient(reply))["seniority"] == "mid"


def test_blank_titles_and_names_are_dropped():
    reply = json.dumps({"target_roles": [{"title": "  "}, {"title": "DE"}],
                        "skills": [{"name": ""}], "seniority": "mid"})
    result = parse_profile("x", MockLLMClient(reply))
    assert [r["title"] for r in result["target_roles"]] == ["DE"]
    assert result["skills"] == []


def test_the_lists_are_capped():
    reply = json.dumps({
        "target_roles": [{"title": f"Role {i}"} for i in range(12)],
        "skills": [{"name": f"Skill {i}"} for i in range(40)],
        "seniority": "mid"})
    result = parse_profile("x", MockLLMClient(reply))
    assert len(result["target_roles"]) == 5
    assert len(result["skills"]) == 20


def test_a_dict_instead_of_a_list_produces_no_bogus_entries():
    """A dict's keys must not get promoted into fabricated role/skill entries."""
    reply = json.dumps({"target_roles": {"weird": "shape"},
                        "skills": {"also": "weird"}, "seniority": "mid"})
    result = parse_profile("x", MockLLMClient(reply))
    assert result["target_roles"] == []
    assert result["skills"] == []


def test_a_scalar_instead_of_a_list_does_not_raise_type_error():
    """parse_profile's documented contract is ValueError, never TypeError."""
    reply = json.dumps({"target_roles": 5, "skills": 5, "seniority": "mid"})
    result = parse_profile("x", MockLLMClient(reply))
    assert result["target_roles"] == []
    assert result["skills"] == []


def test_a_reply_with_no_json_raises():
    with pytest.raises(ValueError, match="no JSON"):
        parse_profile("x", MockLLMClient("I cannot help with that."))


def test_the_resume_text_reaches_the_prompt():
    class Capturing(MockLLMClient):
        def complete(self, prompt, *, system="", max_tokens=1000):
            self.seen = prompt
            return _GOOD

    llm = Capturing(_GOOD)
    parse_profile("Ghazal Izadi — Power BI developer", llm)
    assert "Ghazal Izadi" in llm.seen
