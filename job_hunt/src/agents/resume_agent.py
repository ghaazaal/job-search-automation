"""Resume agent — parses canonical PDF and generates role-specific text variants.

Cache logic: re-parses only when the PDF md5 changes.
"""
import hashlib
import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


def _md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes(), usedforsecurity=False).hexdigest()


def _parse_with_claude(pdf_text: str, candidate_name: str,
                       email: str, model: str) -> dict:
    import anthropic
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    prompt = (
        f"Extract structured information from this resume for {candidate_name}.\n"
        "Reply in JSON only:\n"
        '{"skills":["dbt","Airflow","Python"],'
        '"technologies":["Snowflake","ClickHouse","Power BI"],'
        '"years_experience":5,'
        '"target_roles":["Analytics Engineer","Data Engineer","Data Analyst"],'
        '"summary":"Senior Analytics Engineer with..."}\n\n'
        f"Resume text:\n{pdf_text[:4000]}"
    )
    msg = client.messages.create(
        model=model, max_tokens=800,
        messages=[{"role": "user", "content": prompt}],
    )
    import re
    text = msg.content[0].text
    m = re.search(r'\{.*\}', text, re.DOTALL)
    if not m:
        raise ValueError(f"Claude returned no JSON for resume parse: {text[:200]}")
    return json.loads(m.group())


def parse_resume(config: dict, output_dir: Path) -> dict:
    """Parse canonical PDF → output/resume_parsed.json. Uses cache if unchanged."""
    canonical = Path(config["resume"]["canonical_path"])
    if not canonical.is_absolute():
        canonical = (Path(__file__).parent.parent.parent / canonical).resolve()

    cache_file = output_dir / "resume_parsed.json"
    current_md5 = _md5(canonical)

    if cache_file.exists():
        cached = json.loads(cache_file.read_text(encoding="utf-8"))
        if cached.get("pdf_md5") == current_md5:
            logger.info("Resume cache hit — skipping parse")
            return cached

    logger.info("Parsing resume (PDF changed or first run)...")
    from ..utils import pdf as _pdf_mod
    pdf_text = _pdf_mod.extract_text(canonical)

    model = config.get("anthropic", {}).get("model", "claude-sonnet-4-6")
    parsed = _parse_with_claude(
        pdf_text,
        config["resume"]["candidate_name"],
        config["resume"]["email"],
        model,
    )
    result = {"pdf_md5": current_md5, "extracted_text": pdf_text, **parsed}
    cache_file.write_text(json.dumps(result, indent=2), encoding="utf-8")
    logger.info("Resume parsed and cached")
    return result


def generate_role_variant(role: str, parsed_resume: dict,
                           config: dict, output_dir: Path) -> Path:
    """Generate a role-specific resume text variant, cached as output/resume_{ROLE}.txt."""
    safe_role = role.replace(" ", "_").replace("/", "_")
    out_file = output_dir / f"resume_{safe_role}.txt"
    if out_file.exists():
        logger.info("Role variant cached: %s", out_file)
        return out_file

    logger.info("Generating role variant: %s", role)
    import anthropic
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    model = config.get("anthropic", {}).get("model", "claude-sonnet-4-6")
    resume_cfg = config["resume"]

    prompt = (
        f"Rewrite the resume highlights below for the role '{role}'.\n"
        f"Candidate: {resume_cfg['candidate_name']}\n"
        f"Email: {resume_cfg['email']}\n"
        f"LinkedIn: {resume_cfg['linkedin']}\n"
        "IMPORTANT: The candidate's correct name is Ghazal Izadi (NOT Zahra). "
        "Fix any name/contact errors.\n"
        "Return plain text resume variant (no JSON).\n\n"
        f"Original resume:\n{parsed_resume.get('extracted_text','')[:3000]}"
    )
    msg = client.messages.create(
        model=model, max_tokens=1200,
        messages=[{"role": "user", "content": prompt}],
    )
    variant_text = msg.content[0].text
    out_file.write_text(variant_text, encoding="utf-8")
    return out_file
