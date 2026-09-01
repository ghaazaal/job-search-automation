"""Watched companies — the resolver and both fetch rungs.

Resolution is a SOURCE STRATEGY, not authority: it decides where v1
ingests a company's postings from, nothing more. Try ATS (needs a
domain), else LinkedIn (batched by exact name, disambiguated by
companyUrl slug), else stay unresolved with a user-facing note.

Validated 2026-08-31 against the live LinkedIn actor: `companyId` is
DEAD — a nonsense id returns unfiltered rows, the Ship 7 `remote:`
failure mode — while `companyName` ARRAYS batch as OR and purely, and
rows carry `companyUrl`, whose slug distinguishes the two companies that
share the display name "Andersen". Nothing in this module uses
companyId.

Everything network goes through the injected `call` (default
`base.call_actor`), so tests never touch an actor and the run's failure
isolation wraps each rung exactly as it wraps a source. Rows returned by
`fetch` are already purity-filtered; downstream they are ordinary
scraped jobs — they join the stream BEFORE dedupe and pass every gate,
because watching a company changes where we search, not what qualifies
as a job for the user.
"""
import logging
from datetime import date

from .base import call_actor, extract_description
from ..store import watchlist
from ..utils._dates import normalize_date, parse_salary

logger = logging.getLogger(__name__)

_CAREERS_ACTOR_DEFAULT = "fabro.dev~company-career-page-jobs"
_LINKEDIN_ACTOR_DEFAULT = "valig~linkedin-jobs-scraper"


def resolve_pending(conn, user_id: int, config: dict,
                    call=call_actor) -> None:
    """Give every 'unresolved' row one resolution attempt.

    At most two probe calls per row: the ATS actor when a domain is
    stored, then LinkedIn by exact name. A crashing probe marks nothing
    failed — the row stays unresolved and is retried next run, because a
    flaky probe must never take the run down.
    """
    apify = config.get("apify", {})
    careers = apify.get("careers_actor", _CAREERS_ACTOR_DEFAULT)
    linkedin = apify.get("linkedin_actor", _LINKEDIN_ACTOR_DEFAULT)

    for row in watchlist.list_watched(conn, user_id):
        if row["resolution"] != "unresolved":
            continue
        try:
            _resolve_one(conn, user_id, row, careers, linkedin, call)
        except Exception:
            logger.exception(
                "resolution probe failed for %s (stays unresolved, "
                "retried next run)", row["company_name"])


def _resolve_one(conn, user_id, row, careers_actor, linkedin_actor, call):
    if row["domain"]:
        hits = call(careers_actor,
                    {"companies": [row["domain"]], "maxJobsPerCompany": 1},
                    f"Watched/resolve-ats/{row['company_name']}", 180) or []
        if hits:
            watchlist.set_resolution(conn, user_id, row["id"], "ats")
            return

    name = row["company_name"]
    rows = call(linkedin_actor,
                {"companyName": [name], "limit": 10,
                 "datePosted": "r2592000"},
                f"Watched/resolve-li/{name}", 120) or []
    mine = [r for r in rows
            if (r.get("companyName") or "").strip() == name]
    slugs = {watchlist.slug_from_url(r.get("companyUrl"))
             for r in mine} - {None}
    if len(slugs) == 1:
        watchlist.set_resolution(conn, user_id, row["id"], "linkedin",
                                 linkedin_name=name,
                                 linkedin_slug=slugs.pop())
    elif len(slugs) > 1:
        # The Andersen case: two real companies behind one display name.
        # Never fetched by bare name — the user supplies the URL.
        watchlist.set_resolution(
            conn, user_id, row["id"], "unresolved",
            note="several companies share this name on LinkedIn — paste "
                 "the right one's LinkedIn URL")
    else:
        watchlist.set_resolution(
            conn, user_id, row["id"], "unresolved",
            note="not found on a careers ATS or on LinkedIn in the last "
                 "30 days; add a domain or a LinkedIn URL")


# The custom rung's adapters, keyed by company fingerprint. Plain dict,
# not a registry class: the v1 spec's trap is frameworks for n=1, and at
# n=1 a dict literal IS the whole dispatch. A row resolved 'custom' with
# no entry here is skipped with a log line, never an error.
def _dataart(row, profile):
    from . import dataart

    # DataArt's API filters by display name ("Armenia"); the profile
    # stores the ISO code. pycountry is already a dependency (geo.py).
    import pycountry
    code = (profile.get("country") or "").strip().upper()
    country = pycountry.countries.get(alpha_2=code) if code else None
    return dataart.scrape(country.name if country else "")


_CUSTOM_ADAPTERS = {
    "dataart|": _dataart,
}


def fetch(conn, user_id: int, lane: str, config: dict,
          call=call_actor, profile: dict | None = None) -> list[dict]:
    """One batched call for every company on the rung. Empty rung, no call."""
    rows = [r for r in watchlist.list_watched(conn, user_id)
            if r["resolution"] == lane]
    if not rows:
        return []
    apify = config.get("apify", {})
    per_co = int(config.get("search", {})
                 .get("watched_jobs_per_company", 25))

    if lane == "ats":
        jobs, counts = _fetch_ats(rows, apify, per_co, call)
    elif lane == "linkedin":
        jobs, counts = _fetch_linkedin(rows, apify, per_co, call)
    else:
        jobs, counts = _fetch_custom(rows, profile or {})
    watchlist.record_yield(conn, user_id, counts)
    return jobs


def _fetch_custom(rows, profile):
    jobs: list[dict] = []
    counts = {}
    for row in rows:
        adapter = _CUSTOM_ADAPTERS.get(row["company_fingerprint"])
        if adapter is None:
            logger.info("no custom adapter for %r - skipped",
                        row["company_name"])
            continue
        fetched = adapter(row, profile)
        jobs.extend(fetched)
        counts[row["company_fingerprint"]] = len(fetched)
    return jobs, counts


def _fetch_ats(rows, apify, per_co, call):
    actor = apify.get("careers_actor", _CAREERS_ACTOR_DEFAULT)
    raw = call(actor,
               {"companies": [r["domain"] for r in rows if r["domain"]],
                "maxJobsPerCompany": per_co,
                "includeDescription": True},
               "Watched/ats", 300) or []
    by_name = {r["company_name"]: r for r in rows}
    jobs: list[dict] = []
    counts = {r["company_fingerprint"]: 0 for r in rows}
    today = date.today().isoformat()
    for item in raw:
        company = str(item.get("company_name") or "").strip()
        watch = by_name.get(company)
        if watch is None:
            # The actor resolved a domain to a company we did not ask
            # for, or renamed one. Counted nowhere, stored nowhere.
            logger.info("Watched/ats: unexpected company %r skipped",
                        company)
            continue
        url = (item.get("job_url") or item.get("apply_url") or "").strip()
        if not url:
            continue
        loc = item.get("location")
        loc = loc.get("raw") if isinstance(loc, dict) else loc
        jobs.append({
            "cat":      "watchlist",
            "title":    item.get("title") or "",
            "company":  company,
            "location": loc or "",
            "platform": "Careers page",
            "date":     normalize_date(item.get("posted_at") or today),
            "url":      url,
            "salary":   "",
            "description": (item.get("description_text") or ""),
        })
        counts[watch["company_fingerprint"]] += 1
    return jobs, counts


def _fetch_linkedin(rows, apify, per_co, call):
    actor = apify.get("linkedin_actor", _LINKEDIN_ACTOR_DEFAULT)
    names = [r["linkedin_name"] or r["company_name"] for r in rows]
    # The batch shares one limit (measured: 23/2 skew across two
    # companies), so it scales with the rung's size.
    raw = call(actor,
               {"companyName": names, "limit": per_co * len(rows),
                "datePosted": "r2592000"},
               "Watched/linkedin", 120) or []
    expect = {(r["linkedin_name"] or r["company_name"]): r for r in rows}
    jobs: list[dict] = []
    counts = {r["company_fingerprint"]: 0 for r in rows}
    rejected = 0
    today = date.today().isoformat()
    for item in raw:
        name = str(item.get("companyName") or "").strip()
        watch = expect.get(name)
        slug = watchlist.slug_from_url(item.get("companyUrl"))
        if watch is None or (watch["linkedin_slug"]
                             and slug != watch["linkedin_slug"]):
            # Exact name, and the slug when we hold one: the purity
            # filter that replaces the dead companyId parameter.
            rejected += 1
            continue
        url = (item.get("jobUrl") or item.get("url") or "").strip()
        if not url:
            continue
        jobs.append({
            "cat":      "watchlist",
            "title":    item.get("title") or "",
            "company":  watch["company_name"],
            "location": item.get("location") or "",
            "platform": "LinkedIn",
            "date":     normalize_date(item.get("postedDate") or today),
            "url":      url,
            "salary":   parse_salary(item.get("salary") or {}),
            "description": extract_description(item),
        })
        counts[watch["company_fingerprint"]] += 1
    if rejected:
        logger.info("Watched/linkedin: %d row(s) failed the purity filter",
                    rejected)
    return jobs, counts
