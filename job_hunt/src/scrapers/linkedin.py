"""LinkedIn scraper — wraps Apify valig~linkedin-jobs-scraper."""
from datetime import date
import logging

from .base import call_actor, extract_description
from ..utils._dates import normalize_date, parse_salary

logger = logging.getLogger(__name__)

_DATE_MAP = {1: "r86400", 7: "r604800", 14: "r604800", 30: "r2592000"}

# LinkedIn's own filter codes for how a job is worked.
_REMOTE_CODES = {"onsite": "1", "remote": "2", "hybrid": "3"}

# What this scraper sent before it knew where the user lives.
_LEGACY_LOCATION = "Worldwide"
_LEGACY_REMOTE = ["2"]


def _filters_for(location: str, work_modes) -> tuple[str, list[str]]:
    """Location and remote codes for one search.

    A remote-only search is worldwide by definition. Any other combination has
    to name the place, because 'hybrid in Worldwide' is not a thing.
    """
    modes = [str(m).strip().lower() for m in work_modes or ()]
    modes = [m for m in modes if m in _REMOTE_CODES]
    if not modes:
        return _LEGACY_LOCATION, list(_LEGACY_REMOTE)
    codes = [_REMOTE_CODES[m] for m in modes]
    if modes == ["remote"]:
        return _LEGACY_LOCATION, codes
    return ((location or "").strip() or _LEGACY_LOCATION), codes


def scrape(category: str, title: str,
           actor_id: str, days_posted: int = 7,
           jobs_per_category: int = 50,
           run_timeout: int = 120,
           location: str = _LEGACY_LOCATION,
           country: str = "us",
           work_modes=("remote",),
           allow_fallback: bool = True) -> list[dict]:
    where, codes = _filters_for(location, work_modes)
    payload = {
        "title":      title,
        "location":   where,
        "remote":     codes,
        "datePosted": _DATE_MAP.get(days_posted, "r604800"),
        "limit":      jobs_per_category,
    }
    raw = call_actor(actor_id, payload, f"LinkedIn/{category}", run_timeout)

    # See the note in indeed.py: a rejected payload is indistinguishable from
    # an empty search, so retry once with the values known to work. But a
    # probe or the local lane asked a narrow, deliberate question — Worldwide/
    # remote answers a different one, and for a probe that answer gets
    # recorded as badge evidence. A search that found nothing there must
    # stay silent rather than fabricate.
    legacy = {**payload, "location": _LEGACY_LOCATION,
              "remote": list(_LEGACY_REMOTE)}
    if allow_fallback and not raw and legacy != payload:
        logger.warning(
            "LinkedIn returned nothing for %s with location=%r remote=%r — "
            "retrying with the legacy Worldwide/remote payload",
            category, payload["location"], payload["remote"])
        raw = call_actor(actor_id, legacy, f"LinkedIn/{category} (legacy)",
                         run_timeout)

    today = date.today().isoformat()
    jobs: list[dict] = []
    for item in raw:
        url = (item.get("jobUrl") or item.get("applyUrl")
               or item.get("url") or item.get("link") or "")
        if not url:
            continue
        job_title = (item.get("title") or item.get("jobTitle")
                     or item.get("positionName") or "")
        company_raw = item.get("company") or item.get("companyName") or ""
        company = (company_raw.get("name") if isinstance(company_raw, dict)
                   else str(company_raw))
        posted_raw = (item.get("datePublished") or item.get("postedAt")
                      or item.get("publishedAt") or item.get("listedAt") or today)
        jobs.append({
            "cat":      category,
            "title":    job_title,
            "company":  company,
            "location": item.get("location") or item.get("jobLocation") or "Remote",
            "platform": "LinkedIn",
            "date":     normalize_date(posted_raw),
            "url":      url,
            "salary":   parse_salary(
                item.get("salary") or item.get("baseSalary") or {}),
            "description": extract_description(item),
        })

    # Actors overshoot (Indeed returns ~100 for maxResults=50). The cap
    # is a promise to the user about volume and cost, so it is enforced
    # here, not trusted to the actor.
    jobs = jobs[:jobs_per_category]
    return jobs
