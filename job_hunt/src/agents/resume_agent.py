"""Role-specific resume variants.

The canonical resume text comes from the store — it was extracted once at
upload time and does not need a second cache keyed on a PDF's md5. What is
cached here is the LLM's rewrite for one target role, which is expensive and
worth keeping.
"""
import logging
import re
from pathlib import Path

from ..llm.base import LLMClient

logger = logging.getLogger(__name__)


def _safe(role: str) -> str:
    """A filename fragment from a role title. Never used as a path itself."""
    cleaned = re.sub(r"[^\w\s-]", "_", role or "").strip()
    return re.sub(r"\s+", "_", cleaned) or "role"


def generate_role_variant(role: str, resume: dict, output_dir: Path,
                          llm: LLMClient) -> Path:
    """Rewrite the resume's highlights for one role. Cached per role."""
    out_file = Path(output_dir) / f"resume_{_safe(role)}.txt"
    if out_file.exists():
        logger.info("Role variant cached: %s", out_file)
        return out_file

    logger.info("Generating role variant: %s", role)
    prompt = (
        f"Rewrite the resume highlights below for the role '{role}'.\n"
        "Keep the candidate's own name and contact details exactly as they "
        "appear in the resume — do not invent or substitute any.\n"
        "Return plain text (no JSON, no markdown fences).\n\n"
        f"Original resume:\n{(resume.get('extracted_text') or '')[:3000]}"
    )
    out_file.write_text(llm.complete(prompt, max_tokens=1200), encoding="utf-8")
    return out_file
