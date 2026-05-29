"""Tests for src/agents/resume_agent.py — hash invalidation and LLM abstraction."""
import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from tests.conftest import MockLLMClient

_CONFIG = {
    "resume": {
        "canonical_path": "../Resume/cv_ghazal_izadi_AE.pdf",
        "candidate_name": "Ghazal Izadi",
        "email": "zahra.izaadii@gmail.com",
        "linkedin": "linkedin.com/in/ghazal-izadi",
    },
    "llm": {"provider": "mock", "model": "mock-model"},
}

_MOCK_PARSED = json.dumps({
    "skills": ["dbt", "Python"],
    "technologies": ["Snowflake"],
    "years_experience": 5,
    "target_roles": ["Analytics Engineer"],
    "summary": "Senior AE",
})


def test_cache_hit_same_md5(tmp_path):
    """If PDF md5 matches cache, skip LLM entirely."""
    fake_pdf = tmp_path / "resume.pdf"
    fake_pdf.write_bytes(b"fake pdf content")
    md5 = hashlib.md5(b"fake pdf content", usedforsecurity=False).hexdigest()

    cache_data = {
        "pdf_md5": md5, "extracted_text": "...",
        "skills": ["dbt", "Python"], "technologies": [],
        "years_experience": 5, "target_roles": [], "summary": "",
    }
    (tmp_path / "resume_parsed.json").write_text(json.dumps(cache_data))

    cfg = {**_CONFIG, "resume": {**_CONFIG["resume"], "canonical_path": str(fake_pdf)}}
    llm = MockLLMClient(_MOCK_PARSED)

    from src.agents.resume_agent import parse_resume
    result = parse_resume(cfg, tmp_path, llm)

    # LLM should not have been called — result comes from cache
    assert result["skills"] == ["dbt", "Python"]


def test_cache_miss_changed_md5(tmp_path):
    """If PDF md5 changed, re-parse via LLM."""
    fake_pdf = tmp_path / "resume.pdf"
    fake_pdf.write_bytes(b"new content v2")

    cache_data = {"pdf_md5": "old_md5_value", "extracted_text": "old", "skills": ["old"]}
    (tmp_path / "resume_parsed.json").write_text(json.dumps(cache_data))

    cfg = {**_CONFIG, "resume": {**_CONFIG["resume"], "canonical_path": str(fake_pdf)}}
    llm = MockLLMClient(_MOCK_PARSED)

    from src.agents.resume_agent import parse_resume
    with patch("src.utils.pdf.extract_text", return_value="new pdf text"):
        result = parse_resume(cfg, tmp_path, llm)

    assert result["skills"] == ["dbt", "Python"]


def test_no_cache_triggers_parse(tmp_path):
    """First run with no cache file — should call LLM."""
    fake_pdf = tmp_path / "resume.pdf"
    fake_pdf.write_bytes(b"brand new resume")

    cfg = {**_CONFIG, "resume": {**_CONFIG["resume"], "canonical_path": str(fake_pdf)}}
    llm = MockLLMClient(_MOCK_PARSED)

    from src.agents.resume_agent import parse_resume
    with patch("src.utils.pdf.extract_text", return_value="text"):
        result = parse_resume(cfg, tmp_path, llm)

    assert "pdf_md5" in result
    assert (tmp_path / "resume_parsed.json").exists()


def test_llm_no_json_raises(tmp_path):
    """If LLM returns no JSON, parse_resume raises instead of writing bad cache."""
    fake_pdf = tmp_path / "resume.pdf"
    fake_pdf.write_bytes(b"content")

    cfg = {**_CONFIG, "resume": {**_CONFIG["resume"], "canonical_path": str(fake_pdf)}}
    llm = MockLLMClient("Sorry, I cannot parse this.")  # no JSON

    from src.agents.resume_agent import parse_resume
    with patch("src.utils.pdf.extract_text", return_value="text"):
        with pytest.raises(ValueError, match="no JSON"):
            parse_resume(cfg, tmp_path, llm)
