"""What the routes need around `tailor`: settings, the term list, a model."""
from pathlib import Path

import yaml

from .grounding import term_dictionary

_ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_PATH = _ROOT / "config.yaml"
VOCABULARY_PATH = _ROOT / "vocabulary.yaml"

DEFAULT_MODEL = "claude-opus-5-5"


def settings() -> dict:
    try:
        with open(CONFIG_PATH, encoding="utf-8") as handle:
            config = yaml.safe_load(handle) or {}
    except OSError:
        config = {}
    return config.get("resume_tailoring") or {}


def terms(resumes: list[dict]) -> list[str]:
    with open(VOCABULARY_PATH, encoding="utf-8") as handle:
        vocabulary = yaml.safe_load(handle) or {}
    return term_dictionary(vocabulary, resumes)


def make_model():
    """A Claude client. Always Claude, whatever llm.provider says, like the
    learning path: the check depends on structured output."""
    from ..skills.claude import ClaudeJson
    return ClaudeJson(settings().get("model") or DEFAULT_MODEL)
