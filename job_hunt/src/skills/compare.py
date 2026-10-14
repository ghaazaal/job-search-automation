"""The resume against the market: have, builds-on, or missing.

Two passes, cheapest first.

1. Exact: the skill (or any spelling the postings used for it) is on the
   resume's confirmed skill list, or is named word-bounded in the resume
   text. No model involved.
2. Claude, for the most-demanded skills pass 1 could not place. It may say
   "have" (the resume describes the skill without naming it) or "builds on"
   (a related skill makes it quicker to learn) — and either answer must
   quote the resume. A quote that is not in the resume turns the answer
   into "missing". Saying nothing is always allowed; inventing is not.
"""
import re

from ..scoring.matching import has_term, resume_terms
from .extract import squash, verified

HAVE, ADJACENT, MISSING = "have", "adjacent", "missing"

# How many of the most-demanded unplaced skills Claude is asked about.
REVIEW_LIMIT = 40

SYSTEM = """You compare a candidate's resume with skills that job postings ask for.

For each skill, decide one status:
- have: the resume shows the candidate has this skill, even if under another name (for example the resume describes building star schemas, and the skill is "Data modeling").
- adjacent: the candidate does not have it, but the resume shows a closely related skill that makes it noticeably quicker to learn (for example Apache Airflow for Dagster, Power BI for Tableau, PostgreSQL for Snowflake SQL).
- missing: neither.

For have and adjacent, quote the resume: copy a short phrase exactly, character for character, from the resume text that supports the decision, and for adjacent name the related skill in related_to. For missing, leave evidence and related_to empty. When unsure, answer missing."""

SCHEMA = {
    "type": "object",
    "properties": {
        "skills": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "status": {"type": "string",
                               "enum": [HAVE, ADJACENT, MISSING]},
                    "related_to": {"type": "string"},
                    "evidence": {"type": "string"},
                },
                "required": ["name", "status", "related_to", "evidence"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["skills"],
    "additionalProperties": False,
}

_CONTEXT = 50


def _snippet(text: str, term: str) -> str:
    """The resume's own words around a matched term, for the evidence line."""
    match = re.search(re.escape(term), text, re.IGNORECASE)
    if not match:
        return term
    start = max(0, match.start() - _CONTEXT)
    end = min(len(text), match.end() + _CONTEXT)
    piece = " ".join(text[start:end].split())
    return ("…" if start else "") + piece + ("…" if end < len(text) else "")


def exact_status(skill: dict, resume: dict) -> dict | None:
    """Pass 1. None when the resume does not name the skill."""
    listed = resume_terms(resume.get("skills") or [])
    text = resume.get("extracted_text") or ""
    lowered = text.lower()
    candidates = [skill["name"]] + list(skill.get("variants") or [])
    for name in candidates:
        if name.lower() in listed:
            return {"status": HAVE, "how": "listed",
                    "evidence": f"On your resume's skill list ({name})."}
    for name in candidates:
        # "R" and "Go" are also ordinary words and letters in prose; a name
        # that short only counts when the skill list states it.
        if len(squash(name)) < 3:
            continue
        if has_term(name.lower(), lowered):
            return {"status": HAVE, "how": "text",
                    "evidence": _snippet(text, name)}
    return None


def compare(demand: list[dict], resume: dict, model=None,
            review_limit: int = REVIEW_LIMIT) -> dict[str, dict]:
    """name -> {status, how, evidence, related_to} for every demanded skill."""
    result: dict[str, dict] = {}
    unplaced = []
    for skill in demand:
        found = exact_status(skill, resume)
        if found:
            result[skill["name"]] = found
        else:
            result[skill["name"]] = {"status": MISSING, "how": "absent",
                                     "evidence": ""}
            unplaced.append(skill)

    # Soft skills are read in the market view but not planned, so they are
    # not worth a question to the model.
    to_review = [s for s in unplaced if s["category"] != "soft"][:review_limit]
    if model is None or not to_review:
        return result

    text = resume.get("extracted_text") or ""
    listed = ", ".join(s.get("name", "") for s in resume.get("skills") or [])
    prompt = ("Resume skill list: " + listed + "\n\nResume text:\n"
              + text + "\n\nSkills to decide:\n"
              + "\n".join(f"- {s['name']}" for s in to_review))
    answer = model(system=SYSTEM, prompt=prompt, schema=SCHEMA,
                   effort="medium")
    wanted = {s["name"] for s in to_review}
    for item in (answer or {}).get("skills") or []:
        name = item.get("name")
        status = item.get("status")
        if name not in wanted or status not in (HAVE, ADJACENT):
            continue
        evidence = " ".join(str(item.get("evidence") or "").split())
        if not verified(evidence, text):
            continue
        result[name] = {"status": status, "how": "claude",
                        "evidence": evidence,
                        "related_to": " ".join(
                            str(item.get("related_to") or "").split())[:80]}
    return result
