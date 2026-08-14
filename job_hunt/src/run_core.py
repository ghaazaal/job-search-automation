"""Scrape, dedupe, score, store — the part of a run the map depends on.

Callers differ in how they report progress and in what they do afterwards, so
this module does neither. It emits events through `on_progress` and returns
what it produced. Printing, writing progress into the run row, and the LLM and
Excel steps all belong to the caller.

Nothing here imports Flask or threading.
"""
import logging

logger = logging.getLogger(__name__)

# (display name, config key for the actor id, default actor id)
SOURCES = (
    ("Indeed",   "indeed_actor",   "valig~indeed-jobs-scraper"),
    ("LinkedIn", "linkedin_actor", "valig~linkedin-jobs-scraper"),
)


def search_titles(resumes: list[dict]) -> list[str]:
    """Every distinct target role across the active resumes, in order.

    Case-insensitive on the key so 'BI Developer' and 'bi developer' are one
    search, but the first spelling seen is the one that gets searched.
    """
    titles: list[str] = []
    seen: set[str] = set()
    for resume in resumes:
        for role in resume.get("target_roles") or []:
            title = (role.get("title") or "").strip()
            key = title.lower()
            if title and key not in seen:
                seen.add(key)
                titles.append(title)
    return titles


def plan_steps(titles: list[str]) -> list[dict]:
    """The whole scrape, listed before any of it runs.

    Grouped by role rather than by source so the progress screen reads down
    one role at a time, which is the order they actually run in.
    """
    return [{"source": name, "role": title, "state": "pending", "found": 0}
            for title in titles
            for name, _, _ in SOURCES]
