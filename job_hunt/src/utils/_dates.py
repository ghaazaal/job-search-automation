"""Date and salary parsing helpers shared by scrapers."""
import re
from datetime import date, datetime


def normalize_date(raw) -> str:
    today = date.today().isoformat()
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ",
                "%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(str(raw)[:26], fmt).date().isoformat()
        except (ValueError, TypeError):
            pass
    return today


def parse_salary(sal) -> str:
    if isinstance(sal, dict):
        v = sal.get("value") or {}
        if isinstance(v, dict):
            lo, hi = v.get("minValue"), v.get("maxValue")
            if lo and hi:
                return (f"${lo:,.0f} – ${hi:,.0f}"
                        if isinstance(lo, (int, float)) else f"{lo} – {hi}")
            return str(lo) if lo else ""
    return str(sal) if sal else ""
