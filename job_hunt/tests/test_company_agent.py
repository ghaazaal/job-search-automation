"""Tests for src/agents/company_agent.py — fallback chain logic."""
from unittest.mock import patch
import pytest

from src.agents.company_agent import lookup
from tests.conftest import MockLLMClient

_CONFIG = {
    "apify": {"company_actor": "curious_coder~linkedin-company-scraper"},
    "llm":   {"provider": "mock", "model": "mock-model"},
    "company_filter": {"cache_ttl_days": 7},
}


def test_apify_lookup_helper_returns_apify_source():
    """_lookup_apify() still works standalone — used when enrichment is re-enabled."""
    from src.agents.company_agent import _lookup_apify
    mock_item = {
        "employeeRange": "51-200",
        "description": "Series B startup growing fast",
        "founded": 2020,
    }
    with patch("src.agents.company_agent.call_actor", return_value=[mock_item]):
        result = _lookup_apify("Acme Corp", "some-actor-id")
    assert result["source"] == "apify"
    assert result["stage"] == "scale-up"
    assert result["growth_score"] >= 5


def test_apify_fail_llm_ok():
    llm = MockLLMClient(
        '{"headcount_range":"11-50","stage":"startup","growth_score":8}'
    )
    with patch("src.agents.company_agent.call_actor", return_value=[]):
        result = lookup("TinyStartup", _CONFIG, llm, cache=None)
    assert result["source"] == "mock_inference"
    assert result["stage"] == "startup"
    assert result["growth_score"] == 8


def test_apify_fail_llm_fail_returns_unknown():
    # LLM returns garbage — falls through to unknown defaults
    llm = MockLLMClient("not json at all")
    with patch("src.agents.company_agent.call_actor", return_value=[]):
        result = lookup("GhostCo", _CONFIG, llm, cache=None)
    assert result["source"] == "unknown"
    assert result["stage"] == "unknown"
    assert result["growth_score"] == 5
    assert result["verdict"] == "PASS"


def test_enterprise_verdict_set_correctly():
    llm = MockLLMClient(
        '{"headcount_range":"5000+","stage":"enterprise","growth_score":3}'
    )
    with patch("src.agents.company_agent.call_actor", return_value=[]):
        result = lookup("BigCorp", _CONFIG, llm, cache=None)
    assert result["verdict"] == "REJECT: enterprise"


def test_cache_hit_skips_apify(tmp_path):
    from src.tracker.cache import CompanyCache
    cache = CompanyCache(db_path=tmp_path / "c.db", ttl_days=7)
    cached_data = {
        "stage": "scale-up", "growth_score": 7,
        "source": "apify", "name": "Stripe",
        "headcount_range": "1001-5000", "verdict": "PASS",
    }
    cache.set("Stripe", cached_data)
    llm = MockLLMClient("{}")
    with patch("src.agents.company_agent.call_actor") as mock_apify:
        result = lookup("Stripe", _CONFIG, llm, cache=cache)
    mock_apify.assert_not_called()
    assert result == cached_data
