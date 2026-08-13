"""Tests for src/agents/resume_agent.py — role-specific resume variants."""
from src.agents.resume_agent import generate_role_variant
from tests.conftest import MockLLMClient

_RESUME = {
    "id": 1,
    "label": "analytics engineer",
    "extracted_text": "Ada Lovelace — ada@example.com — dbt, Airflow, Python",
}


def test_a_variant_is_written_and_returned(tmp_path):
    path = generate_role_variant("Data Engineer", _RESUME, tmp_path,
                                 MockLLMClient("Tailored resume text"))
    assert path.exists()
    assert path.read_text(encoding="utf-8") == "Tailored resume text"


def test_the_filename_is_safe_for_a_role_with_punctuation(tmp_path):
    path = generate_role_variant("Data Engineer / Analytics", _RESUME, tmp_path,
                                 MockLLMClient("text"))
    assert path.parent == tmp_path
    assert "/" not in path.name
    assert " " not in path.name


def test_an_existing_variant_is_reused_without_calling_the_llm(tmp_path):
    class Exploding(MockLLMClient):
        def complete(self, prompt, *, system="", max_tokens=1000):
            raise AssertionError("the cached variant should have been used")

    first = generate_role_variant("Data Engineer", _RESUME, tmp_path,
                                  MockLLMClient("first pass"))
    again = generate_role_variant("Data Engineer", _RESUME, tmp_path,
                                  Exploding("unused"))
    assert again == first
    assert again.read_text(encoding="utf-8") == "first pass"


def test_the_resume_text_reaches_the_prompt(tmp_path):
    class Capturing(MockLLMClient):
        def complete(self, prompt, *, system="", max_tokens=1000):
            self.seen = prompt
            return "text"

    llm = Capturing("text")
    generate_role_variant("Data Engineer", _RESUME, tmp_path, llm)
    assert "Ada Lovelace" in llm.seen
    assert "Data Engineer" in llm.seen


def test_no_candidate_is_hardcoded_in_the_prompt(tmp_path):
    """The prompt used to name one person. It works off the resume now."""
    class Capturing(MockLLMClient):
        def complete(self, prompt, *, system="", max_tokens=1000):
            self.seen = prompt
            return "text"

    llm = Capturing("text")
    generate_role_variant("Data Engineer", _RESUME, tmp_path, llm)
    assert "Ghazal" not in llm.seen


def test_parse_resume_is_gone():
    """The store holds the extracted text; the PDF cache was a second copy."""
    import src.agents.resume_agent as agent
    assert not hasattr(agent, "parse_resume")
