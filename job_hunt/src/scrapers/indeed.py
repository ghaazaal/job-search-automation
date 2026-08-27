"""Indeed scraper — wraps Apify kaix~indeed-scraper.

Swapped from valig because valig has no work-mode filter, so the old
payload put "remote" in the LOCATION box. Indeed then returned the
string "Remote" as each job's location — our own query reflected back,
which four of eleven hand-reviewed roles were wrongly admitted on.

kaix has Indeed's real attribute filter (`remote`) and returns
`workArrangement.locationType` as a publisher-stated field, plus
`signals.isExpired`, structured `location.country` and parsed salary.
"""
from datetime import date
import logging

from .base import call_actor, extract_description
from ..utils._dates import normalize_date, parse_salary

logger = logging.getLogger(__name__)

_DATE_MAP = {1: "1", 3: "3", 7: "7", 14: "14"}

# kaix speaks Indeed's own remote filter. It has no "onsite" value —
# absence of the filter is how you ask for everything.
_REMOTE_FILTER = {"remote": "remote", "hybrid": "hybrid"}

_LEGACY_LOCATION = "United States"
_LEGACY_COUNTRY = "us"


def _get(item: dict, path: str, default=None):
    """Read a dotted path out of kaix's nested item shape."""
    node = item
    for part in path.split("."):
        if not isinstance(node, dict):
            return default
        node = node.get(part)
    return node if node is not None else default


def _keyword(title: str) -> str:
    """Indeed's title operator, ONE title per search.

    Measured: `title:"Data Analyst"` returns 15/15 on-target, while
    `title:("A" or "B" or "C")` collapses to 11/20 and silently ignores
    `-intern`. So the caller runs one search per role title rather than
    combining them.
    """
    return f'title:"{(title or "").strip()}"'


def _remote_filter(work_modes) -> str:
    """Indeed's filter value, or "" meaning no filter.

    Only set it when the user wants exactly one filterable mode. Asking
    for remote when they also accept hybrid would hide the hybrid work,
    and the local lane's ("remote", "hybrid", "onsite") must yield no
    filter at all rather than an arbitrary one.
    """
    modes = {str(m).strip().lower() for m in work_modes or ()}
    filterable = modes & set(_REMOTE_FILTER)
    if len(filterable) == 1 and modes == filterable:
        return _REMOTE_FILTER[filterable.pop()]
    return ""


def scrape(category: str, title: str,
           actor_id: str, days_posted: int = 7,
           jobs_per_category: int = 50,
           run_timeout: int = 120,
           location: str = _LEGACY_LOCATION,
           country: str = _LEGACY_COUNTRY,
           work_modes=("remote",),
           allow_fallback: bool = True) -> list[dict]:
    payload = {
        "keyword":  _keyword(title),
        "location": (location or "").strip() or _LEGACY_LOCATION,
        "country":  ((country or _LEGACY_COUNTRY).strip().upper()),
        "maxItems": jobs_per_category,
        "sort":     "date",
    }
    remote = _remote_filter(work_modes)
    if remote:
        # kaix documents that fromDays cannot combine with the remote
        # filter, so recency is traded for a real work-mode answer.
        payload["remote"] = remote
    else:
        payload["fromDays"] = _DATE_MAP.get(days_posted, "7")

    raw = call_actor(actor_id, payload, f"Indeed/{category}", run_timeout)

    # kaix documents its parameters (see the remote/fromDays note above),
    # but not what happens when `location` doesn't resolve to a place it
    # recognizes — that comes back as an empty list, indistinguishable
    # from a genuinely empty search there, so the only safe response is
    # to retry once with the values known to work. But the local lane
    # asked a narrow, deliberate question — remote/us answers a
    # different one entirely, and would re-fetch the worldwide lane's
    # own results. A search that found nothing there must stay silent
    # rather than fabricate.
    fellback = False
    legacy = {**payload, "location": _LEGACY_LOCATION,
              "country": _LEGACY_COUNTRY.upper()}
    if allow_fallback and not raw and legacy != payload:
        logger.warning(
            "Indeed returned nothing for %s with location=%r country=%r"
            " — retrying with %s", category, payload["location"],
            payload["country"], _LEGACY_LOCATION)
        raw = call_actor(actor_id, legacy, f"Indeed/{category} (legacy)",
                         run_timeout)
        fellback = True

    today = date.today().isoformat()
    jobs: list[dict] = []
    expired_count = 0
    unusable_count = 0
    stated_mode_count = 0
    for item in raw:
        if _get(item, "signals.isExpired") is True:
            # A closed posting wastes the user's time. kaix is the only
            # source that tells us; LinkedIn does not. Counted
            # separately from unusable rows below — an all-expired batch
            # is a legitimate outcome, not a parsing failure.
            expired_count += 1
            continue
        url = (_get(item, "urls.indeed") or _get(item, "urls.apply")
               or _get(item, "urls.external") or "")
        if not url:
            unusable_count += 1
            continue

        job = {
            "cat":      category,
            "title":    _get(item, "title.text", ""),
            "company":  _get(item, "company.name", ""),
            "location": _get(item, "location.formatted", ""),
            "platform": "Indeed",
            "date":     normalize_date(_get(item, "dates.posted") or today),
            "url":      url,
            "salary":   parse_salary(_get(item, "salary.text") or ""),
            "description": extract_description(
                {"descriptionHtml": _get(item, "description.html"),
                 "description":     _get(item, "description.text")}),
        }
        # Publisher-stated, unlike the old location-box echo. "In-person"
        # is kaix's wording for on-site.
        stated = (_get(item, "workArrangement.locationType") or "").lower()
        mode = {"remote": "remote", "hybrid": "hybrid",
                "in-person": "onsite"}.get(stated)
        if mode:
            job["work_mode"] = mode
            stated_mode_count += 1
        country_code = (_get(item, "location.country") or "").strip().lower()
        if country_code:
            # Structured, so `location_country`'s ambiguity cases
            # ("Chennai, IN" vs "Gary, IN") never arise for Indeed rows.
            job["country"] = country_code
        jobs.append(job)

    if expired_count:
        # Not a warning — a closed posting is routine, but a run that
        # quietly discards a lot of them is worth surfacing.
        logger.info("Indeed dropped %d expired posting(s) for %s",
                   expired_count, category)

    if unusable_count and not jobs:
        # Every non-expired row failed to yield a usable job — almost
        # always a shape mismatch (wrong actor id, or the actor changed
        # its output), not a genuinely empty search. Gated on
        # unusable_count specifically, not just "raw and not jobs": an
        # all-expired batch parsed perfectly and must not trip this.
        logger.warning(
            "Indeed returned %d unusable row(s) for %s but none could be "
            "parsed — check the actor id is %s",
            unusable_count, category, actor_id)

    if jobs and not stated_mode_count:
        # Measured 20/20 and 15/15 live rows carrying a stated mode, so
        # a whole batch with none is unlikely — though not impossible,
        # this is a signal to check for shape drift, not an error.
        # workArrangement.locationType is the field this entire ship
        # exists to trust over text inference; if it silently moved,
        # every job here quietly reverted to the old guesswork with no
        # other sign of it.
        logger.warning(
            "Indeed parsed %d job(s) for %s with no stated work mode — "
            "check workArrangement.locationType is still the field name",
            len(jobs), category)

    jobs = jobs[:jobs_per_category]

    if fellback and payload["country"] != _LEGACY_COUNTRY.upper():
        # These jobs came off the us board, not the one that was asked
        # for. Transient by design: run_core pops the key before
        # anything is scored or stored; the scorer receives it as an
        # explicit argument for the reduced-confidence flag.
        for job in jobs:
            job["_scraped_under"] = _LEGACY_COUNTRY
    return jobs
