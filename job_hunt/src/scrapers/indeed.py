"""Indeed scraper — wraps Apify valig~indeed-jobs-scraper.

Actor input schema (as of May 2026):
  query      : search term (was 'title')
  location   : location string
  country    : ISO country code
  maxResults : max jobs to return (was 'limit')
  datePosted : "1" | "3" | "7" | "14" | "" (was "last N days" text)
"""
from datetime import date

from .base import call_actor
from ..utils._dates import normalize_date, parse_salary


# Actor now expects numeric strings, not human-readable text
_DATE_MAP = {1: "1", 3: "3", 7: "7", 14: "14"}


def scrape(category: str, title: str,
           actor_id: str, days_posted: int = 7,
           jobs_per_category: int = 50,
           run_timeout: int = 120) -> list[dict]:
    payload = {
        "query":      title,
        "location":   "remote",
        "country":    "us",
        "maxResults": jobs_per_category,
        "datePosted": _DATE_MAP.get(days_posted, "7"),
    }
    raw = call_actor(actor_id, payload, f"Indeed/{category}", run_timeout)
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
            location = f"{city}, {state}".strip(", ") or "Remote, US"
        else:
            location = str(loc_raw) or "Remote, US"

        jobs.append({
            "cat":      category,
            "title":    item.get("title") or item.get("jobTitle") or "",
            "company":  ((item.get("employer") or {}).get("name")
                         or item.get("company") or ""),
            "location": location,
            "platform": "Indeed",
            "date":     normalize_date(
                item.get("datePublished") or item.get("postedAt") or today),
            "url":      url,
            "salary":   parse_salary(
                item.get("baseSalary") or item.get("salary") or {}),
        })
    return jobs
