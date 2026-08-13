"""Tailoring agent — generates cover letters, highlights, and shortlist decisions.

Provider-agnostic: all LLM calls go through the injected LLMClient.
"""
import json
import logging
import re
from pathlib import Path

from ..llm.base import LLMClient

logger = logging.getLogger(__name__)

def build_system_prompt(resume: dict) -> str:
    """Describe the candidate from their resume, not from a hardcoded person.

    This prompt used to name one user, her stack and her target roles, which
    quietly wrote every other user's cover letters as if they were her.
    """
    skills = [str(s.get("name") or "").strip()
              for s in resume.get("skills") or []]
    skills = [s for s in skills if s][:8]
    roles = [str(r.get("title") or "").strip()
             for r in resume.get("target_roles") or []]
    roles = [r for r in roles if r]
    seniority = str(resume.get("seniority") or "").strip()

    lines = ["You are a professional resume coach helping a candidate."]
    if seniority:
        lines.append(f"They describe themselves as {seniority} level.")
    if skills:
        lines.append(f"Their main skills are {', '.join(skills)}.")
    if roles:
        lines.append(f"Their target roles are {', '.join(roles)}.")
    lines.append("Their resume is provided. Always write in first person, "
                 "professional tone.")
    lines.append("Output strictly as JSON with no prose preamble or markdown "
                 "fences.")
    return "\n".join(lines)


def tailor_job(job_description: str, resume_text: str,
               role_title: str, company_name: str,
               llm: LLMClient, resume: dict | None = None) -> dict | None:
    """Generate cover letter + highlights. Returns None on LLM failure."""
    prompt = (
        f"Job description:\n{job_description}\n\n"
        f"Resume text for this role:\n{resume_text[:2500]}\n\n"
        f"Target role: {role_title} at {company_name}\n\n"
        'Output JSON: {"cover_letter":"...","highlights":["...","...","..."]}'
    )
    try:
        text = llm.complete(prompt, system=build_system_prompt(resume or {}),
                            max_tokens=1500)
        m = re.search(r'\{.*\}', text, re.DOTALL)
        if not m:
            logger.error("Non-JSON response from %s for %s: %s",
                         llm.provider, company_name, text[:200])
            return None
        return json.loads(m.group())
    except json.JSONDecodeError:
        logger.error("JSON parse error from %s for %s", llm.provider, company_name)
        return None
    except Exception as e:
        logger.error("LLM tailoring failed for %s: %s", company_name, e)
        return None


def save_tailoring_output(result: dict, company_name: str,
                           output_dir: Path) -> Path:
    from datetime import date
    safe_name = re.sub(r'[^\w\s-]', '_', company_name).strip()[:60]
    folder = output_dir / f"{safe_name}_{date.today().isoformat()}"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "cover_letter.txt").write_text(
        result.get("cover_letter", ""), encoding="utf-8")
    highlights = "\n".join(f"• {h}" for h in result.get("highlights", []))
    (folder / "resume_highlights.txt").write_text(highlights, encoding="utf-8")
    return folder


def shortlist_decision(job_description: str, resume_text: str,
                        role_title: str, company_name: str,
                        match_score: int, llm: LLMClient) -> dict:
    """LLM decision layer for shortlisted jobs.

    Returns {apply_now, reason, risk_flags, bullet_edits, cover_angle}.
    Falls back to score-based defaults on failure.
    """
    _default = {
        "apply_now":    "yes" if match_score >= 8 else "no",
        "reason":       f"Score {match_score}/10",
        "risk_flags":   "",
        "bullet_edits": [],
        "cover_angle":  "",
    }
    prompt = (
        f"Role: {role_title} at {company_name} (match score {match_score}/10)\n\n"
        f"Job description (first 1500 chars):\n{job_description[:1500]}\n\n"
        f"Resume:\n{resume_text[:1500]}\n\n"
        "Evaluate fit. Output JSON only:\n"
        '{"apply_now":"yes|no",'
        '"reason":"one sentence",'
        '"risk_flags":"comma-separated or empty",'
        '"bullet_edits":["rewritten bullet 1","rewritten bullet 2","rewritten bullet 3"],'
        '"cover_angle":"one sentence angle for cover letter"}'
    )
    try:
        text = llm.complete(prompt, max_tokens=600)
        m = re.search(r'\{.*\}', text, re.DOTALL)
        return json.loads(m.group()) if m else _default
    except Exception as e:
        logger.warning("Shortlist decision failed for %s: %s", company_name, e)
        return _default
