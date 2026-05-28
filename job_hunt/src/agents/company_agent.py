"""Company intelligence agent — headcount, stage, growth signals.

Source priority:
  1. Apify LinkedIn Company Scraper (primary)
  2. Claude API inference (fallback)
  3. Unknown defaults (both fail)
"""
import logging
import os
from pathlib import Path

from ..scrapers.base import call_actor
from ..tracker.cache import CompanyCache

logger = logging.getLogger(__name__)

_STAGE_MAP = [
    (1,    50,   "startup"),
    (51,   500,  "scale-up"),
    (501,  2000, "growth-stage"),
    (2001, None, "enterprise"),
]


def _classify_stage(headcount: int | None) -> str:
    if headcount is None:
        return "unknown"
    for lo, hi, label in _STAGE_MAP:
        if hi is None or lo <= headcount <= hi:
            return label
    return "unknown"


def _headcount_from_range(range_str: str) -> int | None:
    """Parse '51-200' → midpoint int, or None."""
    import re
    nums = re.findall(r'\d+', (range_str or "").replace(',', ''))
    if not nums:
        return None
    return int(nums[-1]) if len(nums) == 1 else (int(nums[0]) + int(nums[-1])) // 2


def _growth_score(description: str, founded_year: int | None) -> int:
    from datetime import date
    desc = (description or "").lower()
    score = 5  # neutral default
    if any(w in desc for w in ["series a", "series b", "series c", "funding", "raised"]):
        score += 3
    if any(w in desc for w in ["hiring", "growing", "data engineer", "we're growing"]):
        score += 2
    if founded_year and (date.today().year - founded_year) <= 5:
        score += 2
    if any(w in desc for w in ["layoff", "layoffs", "restructuring"]):
        score -= 3
    return max(0, min(score, 10))


def _lookup_apify(company_name: str, actor_id: str) -> dict | None:
    results = call_actor(
        actor_id,
        {"searchKeywords": company_name, "limit": 1},
        f"company/{company_name}",
        timeout=60,
    )
    if not results:
        return None
    item = results[0]
    headcount_range = (item.get("employeeRange") or item.get("staffCountRange") or "")
    headcount = _headcount_from_range(str(headcount_range))
    stage = _classify_stage(headcount)
    description = item.get("description") or ""
    founded = item.get("founded") or item.get("foundedYear")
    try:
        founded_year = int(founded) if founded else None
    except (ValueError, TypeError):
        founded_year = None
    growth = _growth_score(description, founded_year)
    return {
        "name":           company_name,
        "headcount_range": str(headcount_range),
        "stage":          stage,
        "growth_score":   growth,
        "source":         "apify",
        "verdict":        "REJECT: enterprise" if stage == "enterprise" else "PASS",
    }


def _lookup_claude(company_name: str, model: str) -> dict | None:
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return None
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        prompt = (
            f"Estimate the company size and growth stage for '{company_name}'.\n"
            "Reply in JSON only, no prose:\n"
            '{"headcount_range":"51-200","stage":"scale-up","growth_score":7}\n'
            "stage must be one of: startup, scale-up, growth-stage, enterprise, unknown\n"
            "growth_score: 0-10 integer"
        )
        msg = client.messages.create(
            model=model,
            max_tokens=150,
            messages=[{"role": "user", "content": prompt}],
        )
        import json, re
        text = msg.content[0].text
        m = re.search(r'\{.*\}', text, re.DOTALL)
        if not m:
            return None
        data = json.loads(m.group())
        stage = data.get("stage", "unknown")
        return {
            "name":           company_name,
            "headcount_range": data.get("headcount_range", ""),
            "stage":          stage,
            "growth_score":   int(data.get("growth_score", 5)),
            "source":         "claude_inference",
            "verdict":        "REJECT: enterprise" if stage == "enterprise" else "PASS",
        }
    except Exception as e:
        logger.warning("Claude company lookup failed for %s: %s", company_name, e)
        return None


def lookup(company_name: str, config: dict,
           cache: CompanyCache | None = None) -> dict:
    """Return company intel dict. Never raises — returns unknown defaults on failure."""
    if cache:
        cached = cache.get(company_name)
        if cached:
            return cached

    actor_id = (config.get("apify", {}).get("company_actor")
                or "curious_coder~linkedin-company-scraper")
    model = config.get("anthropic", {}).get("model", "claude-sonnet-4-6")

    result = _lookup_apify(company_name, actor_id)
    if result is None:
        result = _lookup_claude(company_name, model)
    if result is None:
        result = {
            "name":           company_name,
            "headcount_range": "",
            "stage":          "unknown",
            "growth_score":   5,
            "source":         "unknown",
            "verdict":        "PASS",
        }

    if cache:
        cache.set(company_name, result)
    return result
