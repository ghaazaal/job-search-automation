"""Tests for src/agents/company_agent.py — fallback chain logic."""
from unittest.mock import patch, MagicMock
import pytest

from src.agents.company_agent import lookup

_CONFIG = {
    "apify": {"company_actor": "curious_coder~linkedin-company-scraper"},
    "anthropic": {"model": "claude-sonnet-4-6"},
    "company_filter": {"cache_ttl_days": 7},
}


def test_apify_ok_returns_apify_source():
    mock_item = {
        "employeeRange": "51-200",
        "description": "Series B startup growing fast",
        "founded": 2020,
    }
    with patch("src.agents.company_agent.call_actor", return_value=[mock_item]):
        result = lookup("Acme Corp", _CONFIG, cache=None)
    assert result["source"] == "apify"
    assert result["stage"] == "scale-up"
    assert result["growth_score"] >= 5


def test_apify_fail_claude_ok():
    claude_result = {
        "name": "TinyStartup", "headcount_range": "11-50",
        "stage": "startup", "growth_score": 8,
        "source": "claude_inference", "verdict": "PASS",
    }
    with patch("src.agents.company_agent.call_actor", return_value=[]):
        with patch("src.agents.company_agent._lookup_claude",
                   return_value=claude_result):
            result = lookup("TinyStartup", _CONFIG, cache=None)
    assert result["source"] == "claude_inference"
    assert result["stage"] == "startup"


def test_both_fail_returns_unknown():
    with patch("src.agents.company_agent.call_actor", return_value=[]):
        with patch.dict(__import__("os").environ, {}, clear=True):
            result = lookup("GhostCo", _CONFIG, cache=None)
    assert result["source"] == "unknown"
    assert result["stage"] == "unknown"
    assert result["growth_score"] == 5
    assert result["verdict"] == "PASS"


def test_cache_hit_skips_apify(tmp_path):
    from src.tracker.cache import CompanyCache
    cache = CompanyCache(db_path=tmp_path / "c.db", ttl_days=7)
    cached_data = {"stage": "scale-up", "growth_score": 7,
                   "source": "apify", "name": "Stripe",
                   "headcount_range": "1001-5000", "verdict": "PASS"}
    cache.set("Stripe", cached_data)

    with patch("src.agents.company_agent.call_actor") as mock_apify:
        result = lookup("Stripe", _CONFIG, cache=cache)
    mock_apify.assert_not_called()
    assert result == cached_data
