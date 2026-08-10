"""Tests for src/scoring/scorer.py"""
import pytest
from pathlib import Path
from src.scoring.scorer import Scorer

_CONFIG = {
    "scoring": {
        "weights": {
            "title_match": 0.40, "category_bonus": 0.10,
            "seniority": 0.20, "skills": 0.20, "penalty": 0.10
        }
    }
}
_KW = Path(__file__).parent.parent / "keywords.yaml"


@pytest.fixture
def scorer():
    return Scorer(_CONFIG, _KW)


def test_core_ae_senior_scores_high(scorer):
    r = scorer.score_job("Senior Analytics Engineer", "Analytics Engineer",
                         "$120k-$150k", "https://example.com/job1")
    assert r["match_score"] >= 7


def test_core_de_scores_well(scorer):
    r = scorer.score_job("Data Engineer", "Data Engineer",
                         "$110k", "https://example.com/job2")
    assert r["match_score"] >= 5


def test_junior_penalty(scorer):
    r = scorer.score_job("Junior Data Engineer", "Data Engineer",
                         "", "https://example.com/job3")
    senior_r = scorer.score_job("Senior Data Engineer", "Data Engineer",
                                "", "https://example.com/job4")
    assert r["match_score"] < senior_r["match_score"]


def test_weak_keyword_scores_low(scorer):
    r = scorer.score_job("React Frontend Engineer", "Analytics Engineer",
                         "", "https://example.com/job5")
    assert r["match_score"] <= 3


def test_clearance_penalty(scorer):
    r_clear = scorer.score_job("Data Analyst clearance required",
                               "Data Analyst", "", "https://example.com/job6")
    r_normal = scorer.score_job("Data Analyst", "Data Analyst",
                                "", "https://example.com/job7")
    assert r_clear["match_score"] < r_normal["match_score"]


def test_seniority_exec_penalized(scorer):
    r_exec = scorer.score_job("VP of Data Engineering", "Data Engineer",
                              "", "https://example.com/job8")
    r_senior = scorer.score_job("Senior Data Engineer", "Data Engineer",
                                "", "https://example.com/job9")
    assert r_exec["match_score"] < r_senior["match_score"]


def test_tailoring_field_returned(scorer):
    r = scorer.score_job("Analytics Engineer", "Analytics Engineer",
                         "", "https://example.com/job12")
    assert r["tailoring"] in ("Minor", "Moderate", "Significant", "N/A")


# ── Description-aware scoring ─────────────────────────────────────────────────
# Skill keywords and penalty terms live in the job description, not the title.
# Scoring on the title alone left 80% of real listings with zero skill points.

def test_skills_in_description_raise_score(scorer):
    """A JD naming her stack should outscore the same title with no JD."""
    jd = ("We run dbt on Snowflake with Airflow orchestration. "
          "You will build Power BI dashboards over our ClickHouse warehouse.")
    with_jd = scorer.score_job("Data Analyst", "Data Analyst", "",
                               "https://example.com/job13", description=jd)
    without = scorer.score_job("Data Analyst", "Data Analyst", "",
                               "https://example.com/job13")
    assert with_jd["match_score"] > without["match_score"]


def test_clearance_in_description_penalized(scorer):
    """Clearance requirements appear in the JD body, never the title."""
    jd = "Applicants must hold an active TS/SCI security clearance."
    flagged = scorer.score_job("Data Analyst", "Data Analyst", "",
                               "https://example.com/job14", description=jd)
    clean = scorer.score_job("Data Analyst", "Data Analyst", "",
                             "https://example.com/job15", description="")
    assert flagged["match_score"] < clean["match_score"]


def test_frontend_stack_in_description_penalized(scorer):
    """A 'Data Analyst' role that is really React work should score down."""
    jd = "You will build React components and maintain our Angular frontend."
    flagged = scorer.score_job("Data Analyst", "Data Analyst", "",
                               "https://example.com/job16", description=jd)
    clean = scorer.score_job("Data Analyst", "Data Analyst", "",
                             "https://example.com/job17", description="")
    assert flagged["match_score"] < clean["match_score"]


def test_description_is_optional(scorer):
    """Callers that have no JD still get a score — no crash, no penalty."""
    r = scorer.score_job("Analytics Engineer", "Analytics Engineer", "",
                         "https://example.com/job18")
    assert 1 <= r["match_score"] <= 10


def test_common_words_do_not_trigger_short_token_penalties(scorer):
    """'optimize'/'adopt' must not fire the OPT visa penalty as substrings."""
    jd = ("You will optimize query performance, adopt best practices, "
          "and describe options to stakeholders.")
    innocuous = scorer.score_job("Data Analyst", "Data Analyst", "",
                                 "https://example.com/job21", description=jd)
    clean = scorer.score_job("Data Analyst", "Data Analyst", "",
                             "https://example.com/job22", description="")
    assert innocuous["match_score"] >= clean["match_score"]


def test_real_opt_requirement_still_penalized(scorer):
    """The genuine standalone term must still count against the job."""
    jd = "We cannot sponsor candidates on CPT or OPT at this time."
    flagged = scorer.score_job("Data Analyst", "Data Analyst", "",
                               "https://example.com/job23", description=jd)
    clean = scorer.score_job("Data Analyst", "Data Analyst", "",
                             "https://example.com/job24", description="")
    assert flagged["match_score"] < clean["match_score"]


def test_skill_score_respects_cap(scorer):
    """A JD stuffed with every keyword cannot outrank the skill_max budget."""
    every_kw = " ".join(["dbt", "airflow", "clickhouse", "power bi", "python",
                         "sql", "etl", "elt", "medallion", "governance",
                         "tableau", "plotly", "streamlit", "experimentation",
                         "data model", "kpi", "dashboard", "pipeline",
                         "warehouse", "quality", "analytics", "bi"])
    stuffed = scorer.score_job("Data Analyst", "Data Analyst", "",
                               "https://example.com/job19", description=every_kw)
    four_kws = scorer.score_job("Data Analyst", "Data Analyst", "",
                                "https://example.com/job20",
                                description="dbt airflow clickhouse power bi")
    assert stuffed["match_score"] == four_kws["match_score"]
