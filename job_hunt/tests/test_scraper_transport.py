"""How `call_actor` talks to Apify — and what it says about it afterwards.

The scrapers' own tests stub `call_actor` out, so nothing exercised the
transport itself. That is where the credential lives.
"""
import logging

import pytest
import requests

from src.scrapers import base

_TOKEN = "apify_api_thisIsTheSecretValue0123456789"


@pytest.fixture
def token(monkeypatch):
    monkeypatch.setenv("APIFY_TOKEN", _TOKEN)
    return _TOKEN


def _capture(monkeypatch, raising=None):
    """Stand in for requests.post; record the call, or raise."""
    seen = {}

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return [{"ok": True}]

    def post(url, **kwargs):
        seen["url"] = url
        seen.update(kwargs)
        if raising is not None:
            raise raising(url)
        return _Resp()

    monkeypatch.setattr(base.requests, "post", post)
    return seen


def test_the_token_travels_in_a_header_not_the_url(token, monkeypatch):
    """A query-string credential ends up in access logs, proxy logs, error
    messages and crash reports. A header ends up in none of them."""
    seen = _capture(monkeypatch)

    base.call_actor("kaix~indeed-scraper", {"keyword": "x"}, "Indeed/x")

    assert seen["headers"]["Authorization"] == f"Bearer {token}"
    assert "token" not in (seen.get("params") or {})
    assert token not in seen["url"]


def test_the_token_never_reaches_the_log(token, monkeypatch, caplog):
    """`requests` puts the full request URL inside its exception messages,
    and the handler logged that exception verbatim. With the token in the
    query string it was written to every log sink the run had."""
    def raising(url):
        return requests.exceptions.RequestException(
            f"503 Server Error for url: {url}?token={_TOKEN}&timeout=120")

    _capture(monkeypatch, raising=raising)

    with caplog.at_level(logging.WARNING):
        assert base.call_actor("kaix~indeed-scraper", {}, "Indeed/x") == []

    assert caplog.text, "the failure still has to be reported"
    assert _TOKEN not in caplog.text
    assert "Indeed/x" in caplog.text


def test_a_timeout_is_reported_without_the_token(token, monkeypatch, caplog):
    def raising(url):
        return requests.exceptions.Timeout(f"timed out for {url}?token={_TOKEN}")

    _capture(monkeypatch, raising=raising)

    with caplog.at_level(logging.WARNING):
        assert base.call_actor("valig~linkedin-jobs-scraper", {}, "LinkedIn/x") == []

    assert _TOKEN not in caplog.text


def test_a_missing_token_is_still_reported_and_skipped(monkeypatch, caplog):
    monkeypatch.delenv("APIFY_TOKEN", raising=False)
    with caplog.at_level(logging.WARNING):
        assert base.call_actor("kaix~indeed-scraper", {}, "Indeed/x") == []
    assert "APIFY_TOKEN not set" in caplog.text


def test_the_items_come_back_unchanged(token, monkeypatch):
    _capture(monkeypatch)
    assert base.call_actor("kaix~indeed-scraper", {}, "Indeed/x") == [{"ok": True}]
