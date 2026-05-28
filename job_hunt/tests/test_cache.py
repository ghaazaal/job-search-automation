"""Tests for src/tracker/cache.py"""
import pytest
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile

from src.tracker.cache import CompanyCache


@pytest.fixture
def tmp_cache(tmp_path):
    return CompanyCache(db_path=tmp_path / "test.db", ttl_days=7)


def test_miss_on_empty_cache(tmp_cache):
    assert tmp_cache.get("Acme Corp") is None


def test_set_and_hit(tmp_cache):
    data = {"stage": "scale-up", "growth_score": 7}
    tmp_cache.set("Acme Corp", data)
    assert tmp_cache.get("Acme Corp") == data


def test_case_insensitive_key(tmp_cache):
    data = {"stage": "startup", "growth_score": 8}
    tmp_cache.set("ACME CORP", data)
    assert tmp_cache.get("acme corp") == data


def test_expired_returns_none(tmp_path):
    cache = CompanyCache(db_path=tmp_path / "exp.db", ttl_days=1)
    data = {"stage": "scale-up", "growth_score": 6}
    cache.set("OldCo", data)

    import sqlite3
    conn = sqlite3.connect(str(tmp_path / "exp.db"))
    old_ts = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    conn.execute("UPDATE company_cache SET updated_at = ? WHERE name = 'oldco'", (old_ts,))
    conn.commit()
    conn.close()

    assert cache.get("OldCo") is None


def test_overwrite_updates_timestamp(tmp_cache):
    tmp_cache.set("Stripe", {"growth_score": 5})
    tmp_cache.set("Stripe", {"growth_score": 9})
    assert tmp_cache.get("Stripe")["growth_score"] == 9
