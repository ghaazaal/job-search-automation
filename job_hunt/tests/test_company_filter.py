"""Tests for src/filters/company_filter.py"""
import pytest
from src.filters.company_filter import CompanyFilter

_CONFIG = {
    "company_filter": {
        "reject_stages": ["enterprise"],
        "min_growth_score": 4,
        "cache_ttl_days": 7,
        "reject_keywords_in_company_name": ["Consulting", "Staffing", "Recruiting"],
    }
}


@pytest.fixture
def filt():
    return CompanyFilter(_CONFIG)


def test_pass_scaleup(filt):
    r = filt.evaluate("Acme Corp", {"stage": "scale-up", "growth_score": 7})
    assert r["verdict"] == "PASS"
    assert r["warn"] is None


def test_reject_enterprise(filt):
    r = filt.evaluate("BigCorp", {"stage": "enterprise", "growth_score": 8})
    assert r["verdict"] == "REJECT"
    assert "enterprise" in r["reason"]


def test_reject_keyword_staffing(filt):
    r = filt.evaluate("ABC Staffing Inc", {"stage": "scale-up", "growth_score": 7})
    assert r["verdict"] == "REJECT"
    assert "staffing" in r["reason"].lower()


def test_reject_keyword_consulting(filt):
    r = filt.evaluate("Acme Consulting Group", {"stage": "scale-up", "growth_score": 7})
    assert r["verdict"] == "REJECT"


def test_soft_warn_low_growth(filt):
    r = filt.evaluate("LowGrowth Co", {"stage": "startup", "growth_score": 2})
    assert r["verdict"] == "PASS"
    assert r["warn"] is not None
    assert "Low Growth Signal" in r["warn"]


def test_unknown_stage_passes(filt):
    r = filt.evaluate("Mystery Corp", {"stage": "unknown", "growth_score": 5})
    assert r["verdict"] == "PASS"


def test_growth_score_at_threshold_passes(filt):
    r = filt.evaluate("EdgeCase Co", {"stage": "startup", "growth_score": 4})
    assert r["verdict"] == "PASS"
    assert r["warn"] is None


def test_growth_score_below_threshold_warns(filt):
    r = filt.evaluate("EdgeCase Co", {"stage": "startup", "growth_score": 3})
    assert r["verdict"] == "PASS"
    assert r["warn"] is not None
