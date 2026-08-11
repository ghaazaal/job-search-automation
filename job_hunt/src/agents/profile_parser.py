"""Turning resume text into a searchable profile.

The aliases are the point. `Senior BI Developer` only scores if the resume's
target roles carry `bi developer` as something to match against, and `dax`
only counts towards Power BI if Power BI says it does. Asking the model for
aliases at upload time buys what a skill taxonomy would buy, without importing
one.

Everything the model returns is normalised before it leaves this module. The
store and the scorer are entitled to assume the shape.
"""
import json
import re

from ..llm.base import LLMClient

SENIORITIES = ("junior", "mid", "senior", "exec")
TIERS = ("core", "working")

MAX_ROLES = 5
MAX_SKILLS = 20
MAX_TEXT = 6000

_PROMPT = """Read this resume and describe the person as a job search profile.

Reply with JSON only, in exactly this shape:
{"target_roles": [{"title": "BI Developer",
                   "aliases": ["business intelligence developer", "bi engineer"]}],
 "skills": [{"name": "Power BI", "tier": "core",
             "aliases": ["powerbi", "pbi", "dax", "power query"]}],
 "seniority": "senior"}

Rules:
- target_roles: at most 5 job titles this person should be searching for.
  aliases are other titles the same job gets posted under.
- skills: at most 20. tier is "core" when the resume shows it repeatedly or in
  recent roles, "working" when it appears once or in passing. aliases are
  spellings, abbreviations, and sub-tools bound tightly enough that naming one
  means the other.
- seniority: one of junior, mid, senior, exec.
- Use only what the resume supports. Do not invent skills.

Resume text:
"""


def parse_profile(extracted_text: str, llm: LLMClient) -> dict:
    """Return {target_roles, skills, seniority} from resume text."""
    reply = llm.complete(_PROMPT + extracted_text[:MAX_TEXT], max_tokens=1200)
    match = re.search(r"\{.*\}", reply, re.DOTALL)
    if not match:
        raise ValueError(
            f"LLM ({llm.provider}) returned no JSON for the resume profile: "
            f"{reply[:200]}")
    return _normalise(json.loads(match.group()))


def _strings(value) -> list[str]:
    """Aliases are matched lowercase, so they are stored lowercase."""
    if not isinstance(value, list):
        return []
    return [str(v).strip().lower() for v in value if str(v).strip()]


def _normalise(raw: dict) -> dict:
    roles: list[dict] = []
    for item in raw.get("target_roles") or []:
        if isinstance(item, str):
            item = {"title": item}
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        if title:
            roles.append({"title": title, "aliases": _strings(item.get("aliases"))})

    skills: list[dict] = []
    for item in raw.get("skills") or []:
        if isinstance(item, str):
            item = {"name": item}
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if name:
            tier = item.get("tier")
            skills.append({
                "name": name,
                "tier": tier if tier in TIERS else "working",
                "aliases": _strings(item.get("aliases")),
            })

    seniority = str(raw.get("seniority") or "").strip().lower()
    return {
        "target_roles": roles[:MAX_ROLES],
        "skills": skills[:MAX_SKILLS],
        "seniority": seniority if seniority in SENIORITIES else "mid",
    }
