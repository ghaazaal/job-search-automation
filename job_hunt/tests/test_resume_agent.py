"""Tests for src/agents/resume_agent.py — hash invalidation logic."""
import json
import hashlib
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

_CONFIG = {
    "resume": {
        "canonical_path": "../Resume/cv_ghazal_izadi_AE.pdf",
        "candidate_name": "Ghazal Izadi",
        "email": "zahra.izaadii@gmail.com",
        "linkedin": "linkedin.com/in/ghazal-izadi",
    },
    "anthropic": {"model": "claude-sonnet-4-6"},
}


def _make_mock_claude_response(skills: list[str]) -> MagicMock:
    resp = MagicMock()
    resp.content = [MagicMock(
        text=json.dumps({
            "skills": skills,
            "technologies": ["Snowflake"],
            "years_experience": 5,
            "target_roles": ["Analytics Engineer"],
            "summary": "Senior AE",
        })
    )]
    return resp


def test_cache_hit_same_md5(tmp_path):
    """If PDF md5 matches cache, skip Claude entirely."""
    fake_pdf = tmp_path / "resume.pdf"
    fake_pdf.write_bytes(b"fake pdf content")
    md5 = hashlib.md5(b"fake pdf content").hexdigest()

    cache_data = {
        "pdf_md5": md5, "extracted_text": "...",
        "skills": ["dbt", "Python"], "technologies": [],
        "years_experience": 5, "target_roles": [], "summary": "",
    }
    (tmp_path / "resume_parsed.json").write_text(json.dumps(cache_data))

    cfg = dict(_CONFIG)
    cfg["resume"] = dict(_CONFIG["resume"])
    cfg["resume"]["canonical_path"] = str(fake_pdf)

    from src.agents.resume_agent import parse_resume
    with patch("src.agents.resume_agent._parse_with_claude") as mock_parse:
        result = parse_resume(cfg, tmp_path)
    mock_parse.assert_not_called()
    assert result["skills"] == ["dbt", "Python"]


def test_cache_miss_changed_md5(tmp_path):
    """If PDF md5 changed, re-parse via Claude."""
    fake_pdf = tmp_path / "resume.pdf"
    fake_pdf.write_bytes(b"new content v2")

    cache_data = {
        "pdf_md5": "old_md5_value",
        "extracted_text": "old text",
        "skills": ["old"],
    }
    (tmp_path / "resume_parsed.json").write_text(json.dumps(cache_data))

    cfg = dict(_CONFIG)
    cfg["resume"] = dict(_CONFIG["resume"])
    cfg["resume"]["canonical_path"] = str(fake_pdf)

    mock_resp = _make_mock_claude_response(["dbt", "Airflow"])

    from src.agents.resume_agent import parse_resume
    with patch("src.agents.resume_agent._parse_with_claude",
               return_value={"skills": ["dbt", "Airflow"], "extracted_text": "new text"}):
        with patch("src.utils.pdf.extract_text", return_value="new pdf text"):
            import os
            with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test"}):
                result = parse_resume(cfg, tmp_path)

    assert result["skills"] == ["dbt", "Airflow"]


def test_no_cache_file_triggers_parse(tmp_path):
    """First run with no cache — should parse."""
    fake_pdf = tmp_path / "resume.pdf"
    fake_pdf.write_bytes(b"brand new resume")

    cfg = dict(_CONFIG)
    cfg["resume"] = dict(_CONFIG["resume"])
    cfg["resume"]["canonical_path"] = str(fake_pdf)

    from src.agents.resume_agent import parse_resume
    with patch("src.agents.resume_agent._parse_with_claude",
               return_value={"skills": ["Python"], "extracted_text": "text"}):
        with patch("src.utils.pdf.extract_text", return_value="text"):
            import os
            with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test"}):
                result = parse_resume(cfg, tmp_path)

    assert "pdf_md5" in result
    cache_file = tmp_path / "resume_parsed.json"
    assert cache_file.exists()
