"""DataArt's careers API — the watchlist's one custom source.

Their portal (dataart.team) is a JS shell over a plain JSON endpoint:

    /dataart-team/api/vacancies/filter-fields-page?countries=<id>&page=N

so this needs no browser and no actor — plain HTTP, like the boards'
aggregator but first-party. The endpoint was found by watching the
page's own network traffic on 2026-09-01, after the ATS and LinkedIn
rungs both measurably failed for DataArt (their careers domain is
dataart.team, not dataart.com, and they barely post to LinkedIn).

Deliberately a MODULE, not a framework. The v1 spec's warning stands:
the trap is CustomScraper/AdapterRegistry abstractions for n=1. This is
one file with one public function, shaped like its scraper siblings; a
second custom company earns its own file, and only 5-10 of them earn a
shared shape.

Two field notes from measurement:
- The country id is resolved from the API's own `countries` list by
  display name, so any user's country works — Armenia is 4610 today,
  but nothing here hardcodes that.
- Pagination REPEATS items across pages (68 "total" collapsed to 10
  distinct Armenia vacancies), so rows are deduped by slug here rather
  than trusting the counter. A banner card ships in the same list with
  no slug; the slug requirement drops it too.
"""
import logging
import time
from datetime import date

import requests

logger = logging.getLogger(__name__)

_API = ("https://www.dataart.team/dataart-team/api/vacancies/"
        "filter-fields-page")
_UA = {"User-Agent": "job-hunt-automation/1.0 (personal job search)",
       "Accept": "application/json"}
_MAX_PAGES = 30   # backstop; Armenia is 1-7 pages today


def _get(params, get=None):
    if get is not None:
        return get(_API, params)
    # Their API returned a 502 and a 504 within one day (2026-09-01) and
    # was fine seconds later each time — transient load, not policy. A
    # 4xx is not retried: that would be our request's fault.
    last = None
    for attempt in range(3):
        if attempt:
            time.sleep(5 * attempt)
        try:
            resp = requests.get(_API, params=params, headers=_UA, timeout=30)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.HTTPError as exc:
            last = exc
            status = getattr(exc.response, "status_code", 0)
            if status < 500:
                raise
            logger.warning("DataArt API %s (attempt %d/3)", status,
                           attempt + 1)
        except requests.exceptions.RequestException as exc:
            last = exc
            logger.warning("DataArt API %s (attempt %d/3)",
                           type(exc).__name__, attempt + 1)
    raise last


def scrape(country_display: str, get=None) -> list[dict]:
    """Every distinct DataArt vacancy in the user's country.

    `country_display` is the vocabulary display name ("Armenia"), matched
    case-insensitively against the API's own countries list. A country
    DataArt does not operate in returns [] — that is an answer, not an
    error. `get(url, params) -> parsed json` is injectable for tests.
    """
    wanted = (country_display or "").strip().lower()
    if not wanted:
        return []
    first = _get({"page": 1, "pageSize": 0}, get)
    country = next((c for c in first.get("countries") or []
                    if str(c.get("title", "")).strip().lower() == wanted),
                   None)
    if country is None:
        logger.info("DataArt lists no country named %r", country_display)
        return []

    jobs: list[dict] = []
    seen: set[str] = set()
    today = date.today().isoformat()
    page, pages_total = 1, 1
    while page <= min(pages_total, _MAX_PAGES):
        data = _get({"countries": country["id"], "page": page,
                     "pageSize": 0}, get)
        block = data.get("vacancies") or {}
        pages_total = int(block.get("pagesTotal") or 1)
        for item in block.get("items") or []:
            slug = (item.get("slug") or "").strip()
            if not slug or slug in seen:
                # No slug is the banner card; a repeated slug is the
                # pagination echo. Neither is a vacancy.
                continue
            seen.add(slug)
            places = [str(t.get("title", "")).strip()
                      for t in item.get("countriesTags") or []]
            jobs.append({
                "cat":      "watchlist",
                "title":    item.get("title") or "",
                "company":  "DataArt",
                "location": ", ".join(p for p in places if p),
                "platform": "DataArt careers",
                "date":     today,   # the API publishes no posting date
                "url":      (item.get("fullUrl")
                             or f"https://www.dataart.team/vacancies/"
                                f"{slug.lower()}"),
                "salary":   "",
                "description": (item.get("text") or ""),
            })
        page += 1
    return jobs
