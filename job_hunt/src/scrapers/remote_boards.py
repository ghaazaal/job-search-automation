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

It aggregates ten independent boards with no guaranteed shape, so it
is *more* exposed than either incumbent to a single malformed row
(free-text salary, HTML-flavoured description) taking the whole
category down — every field read from a row is guarded accordingly.
"""
from datetime import date
import logging

from .base import call_actor, extract_description
from ..utils._dates import normalize_date

logger = logging.getLogger(__name__)

# The aggregator's board slug -> the name we show the user. Two
# DevITjobs slugs (US/UK) deliberately collapse to one display name —
# the user doesn't need the geography of the recruiter's own board.
# This actor sweeps ten boards serially, so it is an order of magnitude
# slower than the others: a measured live run of 50 rows took 301
# seconds, against roughly 20 for valig. `search.run_timeout` defaults to
# 120, which would time this source out on EVERY call — and a timeout
# returns an empty list, which looks exactly like the boards genuinely
# having nothing. So the floor is raised here rather than globally,
# where it would also let a hung Indeed call block for seven minutes.
_MIN_TIMEOUT = 420

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

# Rendered natively where we know the mark; anything else falls back to
# the bare ISO code so the value stays honest rather than guessing.
_CURRENCY_SYMBOLS = {"EUR": "€", "GBP": "£"}


def _symbol(currency: str) -> str:
    code = (currency or "").strip().upper()
    if code in ("", "USD"):
        return "$"
    return _CURRENCY_SYMBOLS.get(code, f"{code} ")


def _salary(row: dict) -> str:
    """The aggregator publishes salary already annualised — when it is
    numeric at all. Ten independent boards means ten different ideas of
    what belongs in a salary field, including free text like
    "Competitive" seen on live rows, so the numeric formatting only
    applies when the value actually is one (mirrors parse_salary's
    `isinstance(lo, (int, float))` guard in `utils/_dates.py`, which
    exists for the same reason). A row with an unparseable salary loses
    its salary, not its existence — unlike parse_salary's own fallback
    of gluing the raw values together, which reads fine for numeric-ish
    strings but not for free text next to a currency symbol.

    The digit grouping and " – " separator match parse_salary's
    structured-range rendering so a mixed map doesn't show two
    different styles side by side; parse_salary itself isn't reused
    directly because it hardcodes "$", which would be wrong here for a
    non-USD board.
    """
    low, high = row.get("salary_min"), row.get("salary_max")
    symbol = _symbol(row.get("salary_currency"))
    numeric_low = isinstance(low, (int, float))
    numeric_high = isinstance(high, (int, float))
    if numeric_low and numeric_high:
        return f"{symbol}{int(low):,} – {symbol}{int(high):,}"
    if numeric_low:
        return f"{symbol}{int(low):,}"
    return ""


def _description(row: dict) -> str:
    """Routed through the shared HTML-flattener, not read raw.

    Ten boards means no guaranteed formatting; some may return
    pre-flattened plain text with no separators (the same failure
    `extract_description` exists to catch — see `base.py`), and this
    source is more exposed to it than either incumbent, not less. A
    synthesised dict is passed rather than adding "description_snippet"
    to the shared `_DESCRIPTION_KEYS` tuple in base.py, so this
    source's field naming can't change what Indeed or LinkedIn resolve.
    "description" already matches a key in that tuple; the snippet is
    mapped onto "snippet", the tuple's lowest-priority key, since a
    snippet is a worse source than the full text whenever both exist.
    """
    return extract_description({
        "description": row.get("description"),
        "snippet": row.get("description_snippet"),
    })


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
                         max(run_timeout, _MIN_TIMEOUT))
    except Exception as exc:
        # Allowed to fail — the other sources carry the run — but not
        # allowed to fail invisibly. 14 total users, no ratings, days
        # old, and one board (Jobicy) already failed mid-run once.
        logger.warning("RemoteBoards failed for %s: %s", category, exc)
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
            # The raw slug, not the display name above — devitjobs_us and
            # devitjobs_uk both render as "DevITjobs" in `platform`, so the
            # slug is the only thing that still tells them apart.
            "source_board": board,
            "date":     normalize_date(row.get("posted_at") or today),
            "url":      url,
            "salary":   _salary(row),
            "description": _description(row),
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
            "RemoteBoards returned %d unusable row(s) for %s but none "
            "could be parsed — check the actor id is %s",
            unusable_count, category, actor_id)

    return jobs[:jobs_per_category]
