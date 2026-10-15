"""Tests for resume tailoring (src/tailor/, src/store/tailoring.py,
src/resume_page.py and its routes).

The model is always a fake. What these pin down is the grounding: a
tailored line that names a tool, figure or employer its cited master lines
do not is put back to the master's words, a bullet cannot borrow from
another job, and the program — not the model — writes titles, companies
and dates.
"""
from src.app import create_app
from src.drawer import drawer_js
from src.shell import shell_nav
from src.store import tailoring
from src.store.db import connect
from src.store.ingest import ensure_user, upsert_jobs
from src.store.profile import create_resume, set_profile, update_resume
from src.store.runs import finish_run, start_run
from src.store.schema import init_db
from src.tailor import document, grounding
from src.tailor.tailor import apply, build_master, cost, tailor

MASTER = """# Ada Example
Senior Analytics Engineer
Yerevan, Armenia · ada@example.com

## Summary

Analytics Engineer with 5+ years building data pipelines and dashboards
in fintech.

## Skills
- Languages: SQL, Python
- BI: Power BI, Tableau

## Experience

### Senior Analytics Engineer | PayCo
Sep 2022 – Present · Remote
- Cut the core query from 45s to 6s by pre-joining context tables
- Built 15+ Airflow pipelines for incremental loading
- Delivered 30+ Power BI dashboards used daily by finance

### BI Developer | Farda
Dec 2019 – Jun 2022
- Designed data warehouse models in SQL Server
"""

TERMS = ["Snowflake", "dbt", "SQL", "Python", "Power BI", "Airflow",
         "Tableau", "Looker"]


class FakeModel:
    def __init__(self, answer):
        self.answer = answer
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return self.answer


# ── document ───────────────────────────────────────────────────────────────

def test_parse_gives_every_piece_an_id_and_round_trips():
    doc = document.parse(MASTER)
    assert doc["name"] == "Ada Example"
    assert doc["header"] == ["Senior Analytics Engineer",
                             "Yerevan, Armenia · ada@example.com"]
    titles = [s["title"] for s in doc["sections"]]
    assert titles == ["Summary", "Skills", "Experience"]
    summary = doc["sections"][0]["blocks"][0]
    assert summary["kind"] == "para" and summary["id"] == "p1"
    assert summary["text"].endswith("dashboards in fintech.")
    payco = doc["sections"][2]["blocks"][0]
    assert payco["heading"] == "Senior Analytics Engineer | PayCo"
    assert payco["meta"] == ["Sep 2022 – Present · Remote"]
    assert [b["id"] for b in payco["bullets"]] == ["b3", "b4", "b5"]
    again = document.parse(document.render(doc))
    assert document.index(again) == document.index(doc)


def test_indented_line_continues_a_bullet():
    doc = document.parse("# A\n## Experience\n### X | Y\n- first half\n"
                         "  second half\n- next\n")
    bullets = doc["sections"][0]["blocks"][0]["bullets"]
    assert [b["text"] for b in bullets] == ["first half second half", "next"]


# ── grounding ──────────────────────────────────────────────────────────────

def test_rewording_passes_but_a_new_tool_or_figure_does_not():
    src = "Built 15+ Airflow pipelines for incremental loading"
    assert grounding.unsupported(
        "Engineered 15+ incremental-loading pipelines in Airflow", src,
        TERMS) == []
    assert grounding.unsupported(
        "Built 15+ Airflow and Snowflake pipelines", src, TERMS) == ["Snowflake"]
    assert grounding.unsupported(
        "Built 20+ Airflow pipelines", src, TERMS) == ["20"]
    assert grounding.unsupported(
        "Built 15+ Airflow pipelines at Google", src, TERMS) == ["Google"]


def test_pdf_broken_apostrophes_and_dashes_still_match():
    src = "Iran�s leading BNPL platform, Sep 2022 – Present"
    assert grounding.unsupported("Iran's leading BNPL platform", src,
                                 TERMS) == []


def test_lower_case_tool_names_are_caught_from_the_dictionary():
    assert grounding.unsupported("Modelled data in dbt", "Modelled data",
                                 TERMS) == ["dbt"]


def test_term_dictionary_takes_vocabulary_and_resume_skills():
    terms = grounding.term_dictionary(
        {"market_tools": ["snowflake"], "skill_names": ["R", "SQL"]},
        [{"skills": [{"name": "ClickHouse", "aliases": ["ch db"]}]}])
    assert "snowflake" in terms and "ClickHouse" in terms
    assert "ch db" in terms and "R" not in terms


# ── apply: the model's choices, checked ────────────────────────────────────

def _answer(**overrides):
    answer = {"paragraphs": [], "groups": [], "section_order": [],
              "emphasis": ["Led with query speed"], "not_in_master": ["dbt"]}
    answer.update(overrides)
    return answer


def test_reordered_and_reworded_bullets_are_kept():
    master = document.parse(MASTER)
    doc, report = apply(master, _answer(groups=[{"id": "g2", "bullets": [
        {"text": "Delivered 30+ Power BI dashboards used daily by finance",
         "sources": ["b5"]},
        {"text": "Reduced core query time from 45s to 6s by pre-joining "
                 "context tables", "sources": ["b3"]}]}]), TERMS)
    payco = doc["sections"][2]["blocks"][0]
    assert [b["text"] for b in payco["bullets"]] == [
        "Delivered 30+ Power BI dashboards used daily by finance",
        "Reduced core query time from 45s to 6s by pre-joining context tables"]
    assert report["rewritten"] == 1 and report["kept_as_is"] == 1
    assert report["reverted"] == [] and report["not_in_master"] == ["dbt"]


def test_an_invented_tool_reverts_to_the_master_words():
    master = document.parse(MASTER)
    doc, report = apply(master, _answer(groups=[{"id": "g2", "bullets": [
        {"text": "Built 15+ Airflow and Snowflake pipelines for incremental "
                 "loading", "sources": ["b4"]}]}]), TERMS)
    payco = doc["sections"][2]["blocks"][0]
    assert [b["text"] for b in payco["bullets"]] == [
        "Built 15+ Airflow pipelines for incremental loading"]
    assert report["reverted"][0]["missing"] == ["Snowflake"]


def test_a_bullet_cannot_borrow_from_another_job():
    master = document.parse(MASTER)
    doc, report = apply(master, _answer(groups=[{"id": "g3", "bullets": [
        {"text": "Built 15+ Airflow pipelines for incremental loading",
         "sources": ["b4"]}]}]), TERMS)
    farda = doc["sections"][2]["blocks"][1]
    # Nothing valid survived, so the entry keeps the master's bullets.
    assert [b["text"] for b in farda["bullets"]] == [
        "Designed data warehouse models in SQL Server"]
    assert report["dropped"][0]["why"] == "it cites nothing from this entry"


def test_summary_rewrite_is_checked_against_the_whole_master():
    master = document.parse(MASTER)
    good = {"id": "p1", "sources": ["p1", "b4"],
            "text": "Analytics Engineer with 5+ years, 15+ Airflow pipelines."}
    bad = {"id": "p1", "sources": ["p1"],
           "text": "Analytics Engineer with 8 years of Snowflake."}
    doc, _ = apply(master, _answer(paragraphs=[good]), TERMS)
    assert doc["sections"][0]["blocks"][0]["text"] == good["text"]
    doc, report = apply(master, _answer(paragraphs=[bad]), TERMS)
    assert doc["sections"][0]["blocks"][0]["text"].startswith(
        "Analytics Engineer with 5+ years building")
    assert set(report["reverted"][0]["missing"]) == {"8", "Snowflake"}


def test_headings_dates_and_header_come_from_the_master_only():
    master = document.parse(MASTER)
    doc, _ = apply(master, _answer(section_order=["s3", "s1", "bogus"]),
                   TERMS)
    assert [s["title"] for s in doc["sections"]] == [
        "Experience", "Summary", "Skills"]
    rendered = document.render(doc)
    assert "### Senior Analytics Engineer | PayCo" in rendered
    assert "Sep 2022 – Present · Remote" in rendered
    assert rendered.startswith("# Ada Example\nSenior Analytics Engineer")


def test_tailor_sends_the_annotated_master_and_the_posting():
    model = FakeModel(_answer())
    role = {"title": "Analytics Engineer", "company": "Acme",
            "description": "We want SQL and dbt."}
    result = tailor(MASTER, role, model, TERMS)
    prompt = model.calls[0]["prompt"]
    assert "[b3] Cut the core query" in prompt and "We want SQL and dbt." in prompt
    assert "Never add a skill" in model.calls[0]["system"]
    assert result["markdown"] == document.render(document.parse(MASTER))


# ── building the master ────────────────────────────────────────────────────

def test_build_master_leaves_out_what_no_source_says():
    model = FakeModel({
        "name": "Ada Example",
        "header_lines": ["ada@example.com", "github.com/ada-invented"],
        "sections": [{"title": "Experience", "paragraphs": [], "groups": [{
            "heading": "Analyst | PayCo", "meta": ["2022 - 2024"],
            "bullets": ["Built Airflow pipelines",
                        "Migrated the warehouse to Snowflake"]}]}]})
    sources = [{"label": "cv", "text": "Ada Example ada@example.com "
                "Analyst at PayCo 2022 - 2024. Built Airflow pipelines."}]
    built = build_master(sources, model, TERMS)
    assert "Built Airflow pipelines" in built["markdown"]
    assert "Snowflake" not in built["markdown"]
    left = {x["text"] for x in built["report"]["left_out"]}
    assert left == {"Migrated the warehouse to Snowflake",
                    "github.com/ada-invented"}


def test_cost_prices_cache_reads_and_writes():
    counts = {"input": 1_000_000, "output": 100_000, "cache_write": 0,
              "cache_read": 0}
    assert cost("claude-opus-5-5", counts) == 6.0
    assert cost("some-unknown-model", counts) is None


# ── routes and pages ───────────────────────────────────────────────────────

def _app(tmp_path, model=None, with_master=True):
    db = tmp_path / "t.db"
    conn = connect(db)
    init_db(conn)
    user_id = ensure_user(conn, "default")
    resume_id = create_resume(conn, user_id, label="ae", orig_filename="a.pdf",
                              sha256="x", stored_path="a.pdf",
                              extracted_text="Ada Example. Built Airflow "
                                             "pipelines at PayCo.")
    update_resume(conn, user_id, resume_id, label="ae",
                  target_roles=[{"title": "Analytics Engineer",
                                 "aliases": []}],
                  skills=[{"name": "SQL", "tier": "core", "aliases": []}],
                  seniority="senior")
    set_profile(conn, user_id, location="Yerevan", country="am",
                work_modes=["remote"])
    run_id = start_run(conn, user_id)
    upsert_jobs(conn, user_id, run_id, [
        {"company": "Acme", "title": "Analytics Engineer",
         "url": "https://x/1", "location": "Remote", "salary": "",
         "platform": "LinkedIn", "date": "2026-10-01",
         "description": "We want SQL, Airflow and dbt.",
         "description_captured": True, "match_score": 7,
         "band": "PARTIAL FIT", "reason": "r", "matched": [], "gaps": [],
         "location_scope": "open"}])
    finish_run(conn, run_id, scraped=1, kept=1)
    if with_master:
        tailoring.save_master(conn, user_id, MASTER, sources=[], report={})
    role_id = conn.execute("SELECT id FROM role").fetchone()["id"]
    conn.close()
    app = create_app(db_path=db, run_in_thread=False)
    app.config["TAILOR_MODEL"] = model
    return app.test_client(), role_id, db


def test_tailor_route_stores_a_checked_resume_and_shows_it(tmp_path):
    model = FakeModel(_answer(groups=[{"id": "g2", "bullets": [
        {"text": "Built 15+ Airflow and Snowflake pipelines",
         "sources": ["b4"]}]}]))
    client, role_id, _ = _app(tmp_path, model)
    assert b"TAILOR RESUME" in client.get(f"/tailor/{role_id}").data

    resp = client.post(f"/api/roles/{role_id}/tailor")
    assert resp.status_code == 201
    page = client.get(f"/tailor/{role_id}").data.decode()
    assert "Built 15+ Airflow pipelines for incremental loading" in page
    assert "NOT IN THE MASTER: Snowflake" in page
    assert "THE POSTING ASKS FOR" in page and "dbt" in page

    tid = resp.get_json()["tailored_id"]
    md = client.get(f"/tailored/{tid}.md")
    assert md.headers["Content-Disposition"].startswith("attachment;")
    assert b"### Senior Analytics Engineer | PayCo" in md.data
    assert b"window.print" in client.get(f"/tailored/{tid}/print").data
    assert b"Analytics Engineer" in client.get("/resume").data


def test_tailor_needs_a_master(tmp_path):
    client, role_id, _ = _app(tmp_path, FakeModel(_answer()),
                              with_master=False)
    assert b"NO MASTER RESUME" in client.get(f"/tailor/{role_id}").data
    resp = client.post(f"/api/roles/{role_id}/tailor")
    assert resp.status_code == 400
    assert "RESUME tab" in resp.get_json()["error"]


def test_build_route_saves_the_master_from_stored_resumes(tmp_path):
    model = FakeModel({"name": "Ada Example", "header_lines": [],
                       "sections": [{"title": "Experience", "paragraphs": [],
                                     "groups": [{"heading": "Engineer | PayCo",
                                                 "meta": [], "bullets": [
                                                     "Built Airflow pipelines"]}]}]})
    client, _, db = _app(tmp_path, model, with_master=False)
    resp = client.post("/api/master-resume/build")
    assert resp.status_code == 201
    assert "Built Airflow pipelines at PayCo" in model.calls[0]["prompt"]
    page = client.get("/resume").data.decode()
    assert "- Built Airflow pipelines" in page and "SAVE MASTER" in page


def test_saving_an_edited_master(tmp_path):
    client, _, db = _app(tmp_path)
    resp = client.post("/api/master-resume",
                       json={"markdown": MASTER + "- Added by hand\n"})
    assert resp.status_code == 200
    conn = connect(db)
    master = tailoring.get_master(conn, ensure_user(conn, "default"))
    assert master["edited"] == 1 and "Added by hand" in master["markdown"]
    assert client.post("/api/master-resume",
                       json={"markdown": "no sections"}).status_code == 400


def test_nav_and_drawer_offer_tailoring():
    assert 'href="/resume"' in shell_nav("/")
    assert "/tailor/" in drawer_js("{}") and "TAILOR RESUME" in drawer_js("{}")


def test_units_after_a_number_are_judged_with_the_number():
    src = "ClickHouse at 1B+ row scale across 10M+ users"
    assert grounding.unsupported("ClickHouse at 1B+ rows, 10M+ users", src,
                                 TERMS) == []
    assert grounding.unsupported("ClickHouse at 2B+ rows", src,
                                 TERMS) == ["2"]


def test_header_lines_are_chosen_never_written():
    master = document.parse(MASTER)
    doc, _ = apply(master, _answer(header=["h2", "h9", "x1"]), TERMS)
    assert doc["header"] == ["Yerevan, Armenia · ada@example.com"]
    doc, _ = apply(master, _answer(header=[]), TERMS)
    assert doc["header"] == master["header"]


def test_unlisted_paragraphs_drop_only_when_the_section_kept_one():
    two = MASTER.replace("in fintech.\n", "in fintech.\n\nA second summary.\n")
    master = document.parse(two)
    doc, _ = apply(master, _answer(paragraphs=[
        {"id": "p2", "text": "A second summary.", "sources": ["p2"]}]), TERMS)
    assert [b["text"] for b in doc["sections"][0]["blocks"]] == [
        "A second summary."]
    doc, _ = apply(master, _answer(), TERMS)
    assert len(doc["sections"][0]["blocks"]) == 2


def test_a_skills_heading_repeating_its_section_is_dropped():
    doc = document.from_structure({"name": "A", "header_lines": [],
                                   "sections": [{"title": "Skills",
                                                 "paragraphs": [],
                                                 "groups": [{"heading": "Skills",
                                                             "meta": [],
                                                             "bullets": ["SQL"]}]}]})
    assert "### Skills" not in document.render(doc)
    assert doc["sections"][0]["blocks"][0]["bullets"][0]["text"] == "SQL"


def test_joined_forms_of_master_words_pass_but_new_parts_do_not():
    src = "Analytics Engineer, BI Developer. Git (branching, code reviews)"
    assert grounding.unsupported("Analytics/BI engineer with Git-based "
                                 "reviews", src, TERMS) == []
    assert grounding.unsupported("Analytics/Looker engineer", src,
                                 TERMS) == ["Looker", "Analytics/Looker"]
