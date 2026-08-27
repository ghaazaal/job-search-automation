"""Remote job boards — wraps Apify flash_scraper~remote-job-aggregator.

The fourth source, and for a user outside the US and EU the only one
that carries anything. Measured on one profile: Indeed and LinkedIn
returned 0 roles open to Armenia across 800 jobs; a single 50-row run
here returned 11.

It sweeps ten public boards (RemoteOK, We Work Remotely, Working
Nomads, Remotive, Jobicy, Himalayas, The Muse, DevITjobs US/UK, HN
"Who is hiring?") into one deduplicated feed. Two things make it a
better fit than either incumbent: `searchTerms` matches job TITLES, so
the relevance gate is enforced before we pay per row; and the location
field states reach outright rather than burying it in prose.

This source is allowed to fail. It is young (14 total users, no
ratings, published days ago), one of its boards failed mid-run during
testing, and a run takes minutes rather than seconds — so every error
is swallowed and the run continues on the others. Allowed to fail does
not mean allowed to fail silently: the exception is always logged.
"""
from datetime import date
import logging

from .base import call_actor
from ..utils._dates import normalize_date

logger = logging.getLogger(__name__)

# The aggregator's board slug -> the name we show the user. Two
# DevITjobs slugs (US/UK) deliberately collapse to one display name —
# the user doesn't need the geography of the recruiter's own board.
_BOARDS = {
    "remoteok": "RemoteOK",
    "weworkremotely": "We Work Remotely",
    "working_nomads": "Working Nomads",
    "remotive": "Remotive",
    "jobicy": "Jobicy",
    "himalayas": "Himalayas",
    "muse": "The Muse",
    "devitjobs_us": "DevITjobs",
    "devitjobs_uk": "DevITjobs",
    "hn_hiring": "Hacker News",
}


def _salary(row: dict) -> str:
    """The aggregator publishes salary already annualised.

    Formatted to match parse_salary's structured-range rendering
    (`utils/_dates.py`, used for LinkedIn's `minValue`/`maxValue` pairs)
    so a mixed map doesn't show two different dash/comma styles side by
    side. parse_salary hardcodes "$", which would be wrong here for a
    non-USD board, so it isn't reused directly — but the digit grouping
    and " – " separator are kept identical.
    """
    low, high = row.get("salary_min"), row.get("salary_max")
    currency = (row.get("salary_currency") or "").strip()
    symbol = "$" if currency in ("", "USD") else f"{currency} "
    if low and high:
        return f"{symbol}{int(low):,} – {symbol}{int(high):,}"
    if low:
        return f"{symbol}{int(low):,}"
    return ""


def scrape(category: str, title: str,
           actor_id: str, days_posted: int = 7,
           jobs_per_category: int = 50,
           run_timeout: int = 120,
           location: str = "",
           country: str = "",
           work_modes=("remote",),
           allow_fallback: bool = True) -> list[dict]:
    """One search per role title, same signature as the other scrapers.

    `location`, `country` and `work_modes` are accepted and ignored:
    every row on these boards is remote by definition (there is no
    filter to apply), and reach is judged later from the raw location
    string by `location_scope` — not here.
    """
    payload = {
        "searchTerms":      [title],
        "maxItems":         jobs_per_category,
        "postedWithinDays": days_posted,
        "includeDescription": True,
    }
    try:
        raw = call_actor(actor_id, payload, f"RemoteBoards/{category}",
                         run_timeout)
    except Exception as exc:
        # Allowed to fail — the other sources carry the run — but not
        # allowed to fail invisibly. 14 total users, no ratings, days
        # old, and one board (Jobicy) already failed mid-run once.
        logger.warning("Remote boards failed for %s: %s", category, exc)
        return []

    today = date.today().isoformat()
    jobs: list[dict] = []
    unusable_count = 0
    for row in raw or []:
        url = (row.get("url") or "").strip()
        if not url:
            # The only skip this source has. Unlike Indeed's expired
            # flag, there is no deliberate-skip category here — every
            # row with a url is used, so any loss below is a shape
            # problem, not a routine one.
            unusable_count += 1
            continue
        board = (row.get("source_board") or "").strip().lower()
        jobs.append({
            "cat":      category,
            "title":    row.get("title") or "",
            "company":  row.get("company") or "",
            "location": row.get("location") or "",
            "platform": _BOARDS.get(board, board or "Remote board"),
            "date":     normalize_date(row.get("posted_at") or today),
            "url":      url,
            "salary":   _salary(row),
            "description": row.get("description")
                           or row.get("description_snippet") or "",
            # Not inference. These boards carry nothing else.
            "work_mode": "remote",
        })

    if unusable_count and not jobs:
        # Every row failed to yield a usable job — almost always a
        # shape mismatch (wrong actor id, or the actor changed its
        # output), not a genuinely empty search. There is no
        # deliberate-skip category to gate this on (see above), so
        # this fires whenever rows came back but none survived.
        logger.warning(
            "Remote boards returned %d unusable row(s) for %s but none "
            "could be parsed — check the actor id is %s",
            unusable_count, category, actor_id)

    return jobs[:jobs_per_category]
