"""Tests for src/config.py — keeping personal details out of the repo."""
import pytest

from src.config import apply_env_overrides

_ENV_KEYS = ["CANDIDATE_NAME", "CANDIDATE_EMAIL", "CANDIDATE_LINKEDIN",
             "RESUME_PATH"]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_env_supplies_personal_details(monkeypatch):
    monkeypatch.setenv("CANDIDATE_NAME", "Ada Lovelace")
    monkeypatch.setenv("CANDIDATE_EMAIL", "ada@example.com")
    monkeypatch.setenv("CANDIDATE_LINKEDIN", "linkedin.com/in/ada")
    monkeypatch.setenv("RESUME_PATH", "../Resume/ada.pdf")

    cfg = apply_env_overrides({"resume": {}})

    assert cfg["resume"]["candidate_name"] == "Ada Lovelace"
    assert cfg["resume"]["email"] == "ada@example.com"
    assert cfg["resume"]["linkedin"] == "linkedin.com/in/ada"
    assert cfg["resume"]["canonical_path"] == "../Resume/ada.pdf"


def test_env_overrides_a_value_left_in_config(monkeypatch):
    monkeypatch.setenv("CANDIDATE_EMAIL", "ada@example.com")
    cfg = apply_env_overrides({"resume": {"email": "stale@example.com"}})
    assert cfg["resume"]["email"] == "ada@example.com"


def test_config_value_kept_when_env_absent():
    cfg = apply_env_overrides({"resume": {"candidate_name": "From yaml"}})
    assert cfg["resume"]["candidate_name"] == "From yaml"


def test_missing_everywhere_yields_empty_string():
    """A fresh clone with no .env must not crash on a KeyError."""
    cfg = apply_env_overrides({})
    assert cfg["resume"]["email"] == ""
    assert cfg["resume"]["candidate_name"] == ""


def test_other_config_sections_untouched():
    cfg = apply_env_overrides({"search": {"days_posted": 7}, "resume": {}})
    assert cfg["search"] == {"days_posted": 7}


def test_original_config_not_mutated():
    original = {"resume": {"email": "yaml@example.com"}}
    apply_env_overrides(original)
    assert original == {"resume": {"email": "yaml@example.com"}}
