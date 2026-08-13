"""The tailoring prompt must describe whoever's resume is loaded."""
from src.agents.tailoring_agent import build_system_prompt, tailor_job
from tests.conftest import MockLLMClient

_RESUME = {
    "label": "bi developer",
    "seniority": "senior",
    "target_roles": [{"title": "BI Developer", "aliases": []},
                     {"title": "Data Analyst", "aliases": []}],
    "skills": [{"name": "Power BI", "tier": "core", "aliases": []},
               {"name": "SQL", "tier": "core", "aliases": []},
               {"name": "Tableau", "tier": "working", "aliases": []}],
}


def test_the_prompt_names_the_resumes_skills():
    prompt = build_system_prompt(_RESUME)
    assert "Power BI" in prompt
    assert "SQL" in prompt


def test_the_prompt_names_the_resumes_target_roles():
    prompt = build_system_prompt(_RESUME)
    assert "BI Developer" in prompt
    assert "Data Analyst" in prompt


def test_the_prompt_states_the_seniority():
    assert "senior" in build_system_prompt(_RESUME)


def test_no_candidate_is_hardcoded():
    """It used to describe one person by name, whoever was using it."""
    assert "Ghazal" not in build_system_prompt(_RESUME)


def test_an_empty_resume_still_produces_a_usable_prompt():
    prompt = build_system_prompt({})
    assert "resume coach" in prompt.lower()


def test_tailor_job_uses_the_resume_derived_prompt():
    class Capturing(MockLLMClient):
        def complete(self, prompt, *, system="", max_tokens=1000):
            self.system = system
            return '{"cover_letter":"c","highlights":["a"]}'

    llm = Capturing("{}")
    tailor_job("a job description", "resume text", "BI Developer", "Acme",
               llm, resume=_RESUME)
    assert "Power BI" in llm.system
