"""Tailoring agent — generates cover letters and resume highlights per job.

Also provides the LLM shortlist decision layer (Apply_Now, LLM_Reason, Risk_Flags).
"""
import json
import logging
import os
import re
from pathlib import Path

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a professional resume coach helping Ghazal Izadi, a senior Analytics Engineer
with 5+ years of experience in dbt, Airflow, Power BI, ClickHouse, and Python.
Her target roles are Analytics Engineer, Data Engineer, and Data Analyst.
Her canonical resume is provided. Always write in first person, professional tone.
Output strictly as JSON with no prose preamble or markdown fences."""


def tailor_job(job_description: str, resume_text: str,
               role_title: str, company_name: str,
               config: dict) -> dict | None:
    """Generate cover letter + highlights. Returns None on Claude failure."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        logger.error("ANTHROPIC_API_KEY not set")
        return None
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        model = config.get("anthropic", {}).get("model", "claude-sonnet-4-6")
        user_msg = (
            f"Job description:\n{job_description}\n\n"
            f"Resume text for this role:\n{resume_text[:2500]}\n\n"
            f"Target role: {role_title} at {company_name}\n\n"
            'Output JSON: {"cover_letter":"...","highlights":["...","...","..."]}'
        )
        msg = client.messages.create(
            model=model, max_tokens=1500,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
        )
        text = msg.content[0].text
        m = re.search(r'\{.*\}', text, re.DOTALL)
        if not m:
            logger.error("Non-JSON response for %s: %s", company_name, text[:200])
            return None
        return json.loads(m.group())
    except json.JSONDecodeError:
        logger.error("JSON parse error for %s", company_name)
        return None
    except Exception as e:
        logger.error("Claude tailoring failed for %s: %s", company_name, e)
        return None


def save_tailoring_output(result: dict, company_name: str,
                           output_dir: Path) -> Path:
    from datetime import date
    import re as _re
    safe_name = _re.sub(r'[^\w\s-]', '_', company_name).strip()[:60]
    folder = output_dir / f"{safe_name}_{date.today().isoformat()}"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "cover_letter.txt").write_text(
        result.get("cover_letter", ""), encoding="utf-8")
    highlights = "\n".join(f"• {h}" for h in result.get("highlights", []))
    (folder / "resume_highlights.txt").write_text(highlights, encoding="utf-8")
    return folder


def shortlist_decision(job_description: str, resume_text: str,
                        role_title: str, company_name: str,
                        match_score: int, config: dict) -> dict:
    """LLM decision layer for shortlisted jobs.

    Returns {apply_now, reason, risk_flags, bullet_edits, cover_angle}.
    Falls back to safe defaults on failure.
    """
    _default = {
        "apply_now": "yes" if match_score >= 8 else "no",
        "reason": f"Score {match_score}/10",
        "risk_flags": "",
        "bullet_edits": [],
        "cover_angle": "",
    }
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return _default
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        model = config.get("anthropic", {}).get("model", "claude-sonnet-4-6")
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
        msg = client.messages.create(
            model=model, max_tokens=600,
            messages=[{"role": "user", "content": prompt}],
        )
        text = msg.content[0].text
        m = re.search(r'\{.*\}', text, re.DOTALL)
        return json.loads(m.group()) if m else _default
    except Exception as e:
        logger.warning("Shortlist decision failed for %s: %s", company_name, e)
        return _default
