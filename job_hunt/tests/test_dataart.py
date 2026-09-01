"""Tests for src/scrapers/dataart.py — the watchlist's one custom source.

All fixtures mirror the live API shapes measured 2026-09-01, including
its two traps: pagination that repeats items, and a slugless banner card
shipped inside the vacancy list.
"""
from src.scrapers import dataart

_COUNTRIES = [
    {"id": 4610, "parentId": None, "title": "Armenia", "total": 68},
    {"id": 17, "parentId": None, "title": "Bulgaria", "total": 90},
]

_ITEM = {"title": "Platform Engineer with Python", "slug": "DE00320",
         "fullUrl": "https://www.dataart.team/vacancies/de00320",
         "countriesTags": [{"id": 4610, "title": "Armenia"}],
         "text": "We are looking for a platform engineer."}
_BANNER = {"title": "What if I can't find it?", "contentType": 1}


def _api(pages):
    """A fake `get` serving `pages` (list of item-lists) per page number."""
    def get(url, params):
        page = int(params.get("page", 1))
        items = pages[page - 1] if page <= len(pages) else []
        return {"countries": _COUNTRIES,
                "vacancies": {"pagesTotal": len(pages), "page": page,
                              "items": items}}
    return get


def test_resolves_the_country_id_by_display_name():
    seen = []

    def get(url, params):
        seen.append(dict(params))
        return {"countries": _COUNTRIES,
                "vacancies": {"pagesTotal": 1, "page": 1, "items": [_ITEM]}}

    jobs = dataart.scrape("Armenia", get=get)
    assert seen[1]["countries"] == 4610      # first call has no filter
    assert jobs[0]["title"] == "Platform Engineer with Python"
    assert jobs[0]["company"] == "DataArt"
    assert jobs[0]["location"] == "Armenia"
    assert jobs[0]["url"].endswith("/de00320")


def test_a_country_dataart_does_not_operate_in_is_an_answer():
    assert dataart.scrape("Wakanda", get=_api([[_ITEM]])) == []


def test_pagination_echoes_are_deduped_by_slug():
    """Live measurement: 68 'total' collapsed to 10 distinct slugs."""
    jobs = dataart.scrape("Armenia", get=_api([[_ITEM], [_ITEM], [_ITEM]]))
    assert len(jobs) == 1


def test_the_banner_card_is_not_a_vacancy():
    jobs = dataart.scrape("Armenia", get=_api([[_ITEM, _BANNER]]))
    assert [j["title"] for j in jobs] == ["Platform Engineer with Python"]


def test_an_empty_country_name_claims_nothing():
    assert dataart.scrape("", get=_api([[_ITEM]])) == []


def test_a_transient_5xx_is_retried_and_a_4xx_is_not(monkeypatch):
    """Their API 502'd and 504'd within one day, fine seconds later."""
    import requests as _requests

    from src.scrapers import dataart as da

    calls = {"n": 0}

    class _Resp:
        def __init__(self, status):
            self.status_code = status

        def raise_for_status(self):
            if self.status_code >= 400:
                err = _requests.exceptions.HTTPError(str(self.status_code))
                err.response = self
                raise err

        def json(self):
            return {"countries": [{"id": 1, "title": "Armenia"}],
                    "vacancies": {"pagesTotal": 1, "page": 1, "items": []}}

    def flaky_get(url, params=None, headers=None, timeout=None):
        calls["n"] += 1
        return _Resp(504 if calls["n"] == 1 else 200)

    monkeypatch.setattr(da.requests, "get", flaky_get)
    monkeypatch.setattr(da.time, "sleep", lambda s: None)
    assert da.scrape("Armenia") == []
    assert calls["n"] >= 2

    calls["n"] = 0

    def forbidden_get(url, params=None, headers=None, timeout=None):
        calls["n"] += 1
        return _Resp(404)

    monkeypatch.setattr(da.requests, "get", forbidden_get)
    import pytest as _pytest
    with _pytest.raises(_requests.exceptions.HTTPError):
        da.scrape("Armenia")
    assert calls["n"] == 1
