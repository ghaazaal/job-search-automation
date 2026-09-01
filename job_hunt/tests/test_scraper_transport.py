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


# --- two accounts, one pipeline ----------------------------------------

def test_a_refused_token_fails_over_to_the_second(monkeypatch, caplog):
    """Run 10's credit death, survived: token A 403s, token B answers."""
    monkeypatch.setenv("APIFY_TOKEN", "apify_api_tokenA_aaaaaaaaaaaaaaaa")
    monkeypatch.setenv("APIFY_TOKEN_2", "apify_api_tokenB_bbbbbbbbbbbbbb")
    base._reset_token_preference()
    used = []

    class _Resp:
        def __init__(self, ok):
            self.ok_ = ok
            self.status_code = 200 if ok else 403

        def raise_for_status(self):
            if not self.ok_:
                raise requests.exceptions.HTTPError("403", response=self)

        def json(self):
            return [{"ok": True}]

    def post(url, **kwargs):
        token = kwargs["headers"]["Authorization"].split()[-1]
        used.append(token)
        return _Resp("tokenB" in token)

    monkeypatch.setattr(base.requests, "post", post)
    with caplog.at_level(logging.WARNING):
        out = base.call_actor("a~b", {}, "X/y")
    assert out == [{"ok": True}]
    assert "tokenA" in used[0] and "tokenB" in used[1]
    # Neither token's value may reach the log.
    assert "tokenA_aaaa" not in caplog.text and "tokenB_bbbb" not in caplog.text


def test_the_working_token_becomes_sticky(monkeypatch):
    """After a failover, later calls start with the token that worked -
    one dead account must not cost a wasted request per call."""
    monkeypatch.setenv("APIFY_TOKEN", "apify_api_tokenA_aaaaaaaaaaaaaaaa")
    monkeypatch.setenv("APIFY_TOKEN_2", "apify_api_tokenB_bbbbbbbbbbbbbb")
    base._reset_token_preference()
    used = []

    class _Resp:
        def __init__(self, ok):
            self.ok_ = ok
            self.status_code = 200 if ok else 403

        def raise_for_status(self):
            if not self.ok_:
                raise requests.exceptions.HTTPError("403", response=self)

        def json(self):
            return []

    def post(url, **kwargs):
        token = kwargs["headers"]["Authorization"].split()[-1]
        used.append(token)
        return _Resp("tokenB" in token)

    monkeypatch.setattr(base.requests, "post", post)
    base.call_actor("a~b", {}, "X/y")       # fails over A -> B
    base.call_actor("a~b", {}, "X/y")       # must start at B
    assert "tokenB" in used[2]
    assert len(used) == 3


def test_both_tokens_dead_behaves_like_one_dead(monkeypatch):
    monkeypatch.setenv("APIFY_TOKEN", "apify_api_tokenA_aaaaaaaaaaaaaaaa")
    monkeypatch.setenv("APIFY_TOKEN_2", "apify_api_tokenB_bbbbbbbbbbbbbb")
    base._reset_token_preference()

    class _Resp:
        status_code = 403

        def raise_for_status(self):
            raise requests.exceptions.HTTPError("403", response=self)

    monkeypatch.setattr(base.requests, "post", lambda url, **kw: _Resp())
    assert base.call_actor("a~b", {}, "X/y") == []
    import pytest as _pytest
    with _pytest.raises(requests.exceptions.HTTPError):
        base.call_actor("a~b", {}, "X/y", strict=True)


def test_a_non_auth_error_does_not_rotate(monkeypatch):
    """A 500 from the actor is not the account's fault; burning the second
    account's credit on it would be a silent cost."""
    monkeypatch.setenv("APIFY_TOKEN", "apify_api_tokenA_aaaaaaaaaaaaaaaa")
    monkeypatch.setenv("APIFY_TOKEN_2", "apify_api_tokenB_bbbbbbbbbbbbbb")
    base._reset_token_preference()
    used = []

    class _Resp:
        status_code = 500

        def raise_for_status(self):
            raise requests.exceptions.HTTPError("500", response=self)

    def post(url, **kwargs):
        used.append(kwargs["headers"]["Authorization"])
        return _Resp()

    monkeypatch.setattr(base.requests, "post", post)
    base.call_actor("a~b", {}, "X/y")
    assert len(used) == 1
