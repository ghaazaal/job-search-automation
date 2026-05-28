"""Indeed scraper — wraps Apify valig~indeed-jobs-scraper."""
from datetime import date, datetime

from .base import call_actor
from ..utils._dates import normalize_date, parse_salary


_DATE_MAP = {1: "last 24 hours", 3: "last 3 days",
             7: "last 7 days",   14: "last 14 days"}


def scrape(category: str, title: str,
           actor_id: str, days_posted: int = 7,
           jobs_per_category: int = 50,
           run_timeout: int = 120) -> list[dict]:
    payload = {
        "title":      title,
        "location":   "remote",
        "country":    "us",
        "limit":      jobs_per_category,
        "datePosted": _DATE_MAP.get(days_posted, "last 7 days"),
    }
    raw = call_actor(actor_id, payload, f"Indeed/{category}", run_timeout)
    today = date.today().isoformat()
    jobs: list[dict] = []
    for item in raw:
        url = (item.get("jobUrl") or item.get("applyUrl")
               or item.get("url") or "")
        if not url:
            continue
        jobs.append({
            "cat":      category,
            "title":    item.get("title") or item.get("jobTitle") or "",
            "company":  ((item.get("employer") or {}).get("name")
                         or item.get("company") or ""),
            "location": item.get("location") or "Remote, US",
            "platform": "Indeed",
            "date":     normalize_date(
                item.get("datePublished") or item.get("postedAt") or today),
            "url":      url,
            "salary":   parse_salary(
                item.get("baseSalary") or item.get("salary") or {}),
        })
    return jobs
