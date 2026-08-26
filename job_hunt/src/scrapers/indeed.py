"""Indeed scraper — wraps Apify valig~indeed-jobs-scraper.

Actor input schema (as of May 2026):
  query      : search term (was 'title')
  location   : location string
  country    : ISO country code
  maxResults : max jobs to return (was 'limit')
  datePosted : "1" | "3" | "7" | "14" | "" (was "last N days" text)
"""
from datetime import date
import logging

from .base import call_actor, extract_description
from ..utils._dates import normalize_date, parse_salary

logger = logging.getLogger(__name__)

# Actor now expects numeric strings, not human-readable text
_DATE_MAP = {1: "1", 3: "3", 7: "7", 14: "14"}

# What this scraper sent before it knew where the user lives. Kept as the
# fallback because it is the only combination confirmed to work against the
# live actor.
_LEGACY_LOCATION = "remote"
_LEGACY_COUNTRY = "us"


def _location_for(location: str, work_modes) -> str:
    """Indeed has no work-mode filter — 'remote' goes in the location box.

    A remote-only search uses the literal string the actor understands.
    Anything that includes an on-site mode has to search the actual place.
    """
    modes = {str(m).strip().lower() for m in work_modes or ()}
    if modes == {"remote"}:
        return _LEGACY_LOCATION
    return (location or "").strip() or _LEGACY_LOCATION


def scrape(category: str, title: str,
           actor_id: str, days_posted: int = 7,
           jobs_per_category: int = 50,
           run_timeout: int = 120,
           location: str = _LEGACY_LOCATION,
           country: str = _LEGACY_COUNTRY,
           work_modes=("remote",)) -> list[dict]:
    payload = {
        "query":      title,
        "location":   _location_for(location, work_modes),
        "country":    (country or _LEGACY_COUNTRY).strip().lower(),
        "maxResults": jobs_per_category,
        "datePosted": _DATE_MAP.get(days_posted, "7"),
    }
    raw = call_actor(actor_id, payload, f"Indeed/{category}", run_timeout)

    # The actor's input schema is undocumented. A rejected payload comes back
    # as an empty list, indistinguishable from a genuinely empty search, so
    # the only safe response is to retry once with the values known to work.
    fellback = False
    legacy = {**payload, "location": _LEGACY_LOCATION,
              "country": _LEGACY_COUNTRY}
    if not raw and legacy != payload:
        logger.warning(
            "Indeed returned nothing for %s with location=%r country=%r — "
            "retrying with the legacy remote/us payload",
            category, payload["location"], payload["country"])
        raw = call_actor(actor_id, legacy, f"Indeed/{category} (legacy)",
                         run_timeout)
        fellback = True

    today = date.today().isoformat()
    jobs: list[dict] = []
    for item in raw:
        url = (item.get("jobUrl") or item.get("applyUrl")
               or item.get("url") or "")
        if not url:
            continue
        # Location may be a nested object or a plain string
        loc_raw = item.get("location") or {}
        if isinstance(loc_raw, dict):
            city    = loc_raw.get("city") or ""
            state   = loc_raw.get("state") or ""
            job_location = f"{city}, {state}".strip(", ") or "Remote, US"
        else:
            job_location = str(loc_raw) or "Remote, US"

        jobs.append({
            "cat":      category,
            "title":    item.get("title") or item.get("jobTitle") or "",
            "company":  ((item.get("employer") or {}).get("name")
                         or item.get("company") or ""),
            "location": job_location,
            "platform": "Indeed",
            "date":     normalize_date(
                item.get("datePublished") or item.get("postedAt") or today),
            "url":      url,
            "salary":   parse_salary(
                item.get("baseSalary") or item.get("salary") or {}),
            "description": extract_description(item),
        })

    # Actors overshoot (Indeed returns ~100 for maxResults=50). The cap
    # is a promise to the user about volume and cost, so it is enforced
    # here, not trusted to the actor.
    jobs = jobs[:jobs_per_category]

    if fellback and payload["country"] != _LEGACY_COUNTRY:
        # These jobs came off the us board, not the one that was asked for.
        # Transient by design: run_core pops the key before anything is
        # scored or stored; the scorer receives it as an explicit argument.
        for job in jobs:
            job["_scraped_under"] = _LEGACY_COUNTRY
    return jobs
