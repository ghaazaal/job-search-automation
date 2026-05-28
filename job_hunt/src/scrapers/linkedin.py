"""LinkedIn scraper — wraps Apify valig~linkedin-jobs-scraper."""
from datetime import date

from .base import call_actor
from ..utils._dates import normalize_date, parse_salary


_DATE_MAP = {1: "r86400", 7: "r604800", 14: "r604800", 30: "r2592000"}


def scrape(category: str, title: str,
           actor_id: str, days_posted: int = 7,
           jobs_per_category: int = 50,
           run_timeout: int = 120) -> list[dict]:
    payload = {
        "title":      title,
        "location":   "Worldwide",
        "remote":     ["2"],
        "datePosted": _DATE_MAP.get(days_posted, "r604800"),
        "limit":      jobs_per_category,
    }
    raw = call_actor(actor_id, payload, f"LinkedIn/{category}", run_timeout)
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
        })
    return jobs
