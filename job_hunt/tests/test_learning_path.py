"""Tests for the market learning path (src/skills/, src/store/learning.py,
src/learning_page.py and its routes).

The model is always a fake. What these pin down is the grounding: a skill
without a real quote never reaches the store, a "you have it" without the
resume's words never reaches the page, and the planner cannot add a skill
the ranking did not hand it.
"""
import pytest

from src.app import create_app
from src.skills import compare, extract, market, path, pipeline, rank
from src.store import learning
from src.store.db import connect
from src.store.ingest import ensure_user, upsert_jobs
from src.store.profile import create_resume, set_profile, update_resume
from src.store.runs import finish_run, start_run
from src.store.schema import SCHEMA_VERSION, init_db


# ── helpers ────────────────────────────────────────────────────────────────
POSTINGS = {
    "https://x/1": ("Data Engineer",
                    "We need strong SQL and Apache Airflow. Snowflake is a plus."),
    "https://x/2": ("Senior Data Engineer",
                    "Must know SQL, Snowflake and dbt. Kafka nice to have."),
    "https://x/3": ("Data Analyst",
                    "Advanced SQL and Tableau. Great communication skills."),
}


def _job(url):
    title, description = POSTINGS[url]
    return {"company": "Acme " + url[-1], "title": title, "url": url,
            "location": "Remote", "salary": "", "platform": "LinkedIn",
            "date": "2026-10-01", "description": description,
            "description_captured": True, "match_score": 7,
            "band": "PARTIAL FIT", "reason": "r", "matched": [], "gaps": [],
            "location_scope": "open"}


def _store(tmp_path):
    db = tmp_path / "test.db"
    conn = connect(db)
    init_db(conn)
    user_id = ensure_user(conn, "G")
    resume_id = create_resume(
        conn, user_id, label="ae", orig_filename="ae.pdf", sha256="abc",
        stored_path="r.pdf",
        extracted_text="Built pipelines in Apache Airflow and Power BI "
                       "dashboards. Wrote SQL daily.")
    update_resume(conn, user_id, resume_id, label="ae",
                  target_roles=[{"title": "Data Engineer", "aliases": []}],
                  skills=[{"name": "SQL", "tier": "core", "aliases": []},
                          {"name": "Apache Airflow", "tier": "core",
                           "aliases": ["airflow"]},
                          {"name": "Power BI", "tier": "core", "aliases": []}],
                  seniority="senior")
    set_profile(conn, user_id, location="Yerevan, Armenia", country="am",
                work_modes=["remote"])
    run_id = start_run(conn, user_id)
    upsert_jobs(conn, user_id, run_id, [_job(u) for u in POSTINGS])
    finish_run(conn, run_id, scraped=3, kept=3)
    return db, conn, user_id


def _role_ids(conn):
    return {row["url"]: row["id"] for row in
            conn.execute("SELECT id, url FROM role")}


class FakeModel:
    """Answers each kind of request from canned data, keyed by its prompt."""
    model = "fake-model"

    def __init__(self, ids, extraction=None, fail=False):
        self.ids = ids
        self.calls = []
        self.prompts = []
        self.fail = fail
        self.extraction = extraction

    def __call__(self, *, system, prompt, schema, effort="low",
                 max_tokens=16000):
        self.calls.append(system)
        self.prompts.append(prompt)
        if self.fail:
            raise RuntimeError("401 invalid x-api-key")
        if system == extract.SYSTEM:
            return self._extract(prompt)
        if system == market.MERGE_SYSTEM:
            return {"groups": []}
        if system == compare.SYSTEM:
            return {"skills": [
                {"name": "Snowflake", "status": "adjacent",
                 "related_to": "SQL", "evidence": "Wrote SQL daily"},
                # The resume never says this: must not become "have".
                {"name": "dbt", "status": "have", "related_to": "",
                 "evidence": "Led dbt migrations"},
            ]}
        if system == path.SYSTEM:
            return {"summary": "Start with the warehouse.",
                    "stages": [{"title": "Warehouse", "skills":
                                ["Snowflake", "Underwater basketry"],
                                "goal": "g", "why_now": "w",
                                "learn": ["a"], "project": "p",
                                "show_it": "s", "effort": "small"}],
                    "left_out": []}
        raise AssertionError("unexpected prompt")

    def _extract(self, prompt):
        answer = self.extraction or {
            self.ids["https://x/1"]: [
                ("SQL", "language", "required", "strong SQL"),
                ("Apache Airflow", "tool", "required", "and Apache Airflow"),
                ("Snowflake", "platform", "preferred", "Snowflake is a plus"),
                # Invented: the posting never says this.
                ("Rust", "language", "required", "expert Rust programmer"),
            ],
            self.ids["https://x/2"]: [
                ("SQL", "language", "required", "Must know SQL"),
                ("Snowflake", "platform", "required", "SQL, Snowflake and dbt"),
                ("dbt", "tool", "required", "Snowflake and dbt"),
                ("Kafka", "tool", "preferred", "Kafka nice to have"),
            ],
            self.ids["https://x/3"]: [
                ("SQL", "language", "required", "Advanced SQL"),
                ("Tableau", "tool", "required", "SQL and Tableau"),
                ("Communication", "soft", "required",
                 "Great communication skills"),
            ],
        }
        postings = []
        for role_id, skills in answer.items():
            if f'id="{role_id}"' not in prompt:
                continue
            postings.append({"id": role_id, "skills": [
                {"name": n, "category": c, "requirement": r, "evidence": e}
                for n, c, r, e in skills]})
        return {"postings": postings}


# ── schema ─────────────────────────────────────────────────────────────────
def test_schema_has_the_learning_tables(tmp_path):
    conn = connect(tmp_path / "s.db")
    init_db(conn)
    tables = {r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"skill_extraction", "posting_skill", "learning_path"} <= tables
    assert SCHEMA_VERSION == 11


# ── quote verification ────────────────────────────────────────────────────
def test_quote_check_ignores_punctuation_and_mangled_apostrophes():
    posting = "Help us push beyond what�s known — dbt • Airflow."
    assert extract.verified("beyond what's known", posting)
    assert extract.verified("dbt, Airflow", posting)


def test_quote_check_rejects_words_not_in_the_posting():
    assert not extract.verified("expert Rust programmer", "We use Python.")


def test_quote_check_rejects_quotes_too_short_to_prove_anything():
    assert not extract.verified("SQL", "We use NoSQL stores.")


# ── extraction ────────────────────────────────────────────────────────────
def test_extraction_stores_only_quoted_skills(tmp_path):
    _, conn, user_id = _store(tmp_path)
    model = FakeModel(_role_ids(conn))
    totals = extract.extract_pending(conn, user_id, model, ["SQL"])
    assert totals["read"] == 3
    assert totals["unverified"] == 1
    names = {r["name"] for r in conn.execute("SELECT name FROM posting_skill")}
    assert "Rust" not in names
    assert {"SQL", "Snowflake", "dbt", "Tableau"} <= names


def test_a_read_posting_is_never_read_twice(tmp_path):
    _, conn, user_id = _store(tmp_path)
    model = FakeModel(_role_ids(conn))
    extract.extract_pending(conn, user_id, model, [])
    calls = len(model.calls)
    extract.extract_pending(conn, user_id, model, [])
    assert len(model.calls) == calls


def test_a_posting_the_answer_skipped_stays_unread(tmp_path):
    _, conn, user_id = _store(tmp_path)
    ids = _role_ids(conn)
    model = FakeModel(ids, extraction={ids["https://x/1"]: []})
    extract.extract_pending(conn, user_id, model, [])
    unread = {r["id"] for r in extract.pending_roles(conn, user_id)}
    assert unread == {ids["https://x/2"], ids["https://x/3"]}


def test_a_posting_naming_nothing_is_recorded_as_read(tmp_path):
    _, conn, user_id = _store(tmp_path)
    ids = _role_ids(conn)
    model = FakeModel(ids, extraction={ids["https://x/1"]: []})
    extract.extract_pending(conn, user_id, model, [])
    row = conn.execute("SELECT kept FROM skill_extraction WHERE role_id = ?",
                       (ids["https://x/1"],)).fetchone()
    assert row["kept"] == 0


def test_repeated_failures_stop_early_and_mark_nothing_read(tmp_path,
                                                            monkeypatch):
    _, conn, user_id = _store(tmp_path)
    monkeypatch.setattr(extract, "BATCH_SIZE", 1)
    model = FakeModel(_role_ids(conn), fail=True)
    totals = extract.extract_pending(conn, user_id, model, [], workers=1)
    assert totals["aborted"]
    assert "401" in totals["error"]
    assert len(extract.pending_roles(conn, user_id)) == 3


# ── market ────────────────────────────────────────────────────────────────
def test_spellings_that_differ_only_in_punctuation_merge():
    rows = [{"name": "Power BI"}, {"name": "PowerBI"}, {"name": "Power BI"}]
    assert set(market.spelling_groups(rows).values()) == {"Power BI"}


def test_synonym_groups_naming_unknown_skills_are_ignored():
    from collections import Counter

    class Merger:
        def __call__(self, **_):
            return {"groups": [
                {"canonical": "AWS", "names": ["AWS", "Amazon Web Services"]},
                {"canonical": "Spark", "names": ["Spark", "Hadoop"]},
            ]}
    counts = Counter({"AWS": 9, "Amazon Web Services": 3, "Spark": 4})
    mapping = market.merge_synonyms(Merger(), counts)
    assert mapping == {"AWS": "AWS", "Amazon Web Services": "AWS"}


def _rows(conn, user_id):
    model = FakeModel(_role_ids(conn))
    extract.extract_pending(conn, user_id, model, [])
    return (extract.evidence_rows(conn, user_id),
            extract.read_postings(conn, user_id))


FAMILIES = [{"name": "Data Engineer", "phrases": ["data engineer"]},
            {"name": "Data Analyst", "phrases": ["data analyst"]}]


def test_market_counts_postings_not_mentions(tmp_path):
    _, conn, user_id = _store(tmp_path)
    rows, postings = _rows(conn, user_id)
    view = market.build(rows, postings, FAMILIES, {})
    sql = next(s for s in view["skills"] if s["name"] == "SQL")
    assert view["postings"] == 3
    assert sql["postings"] == 3 and sql["required"] == 3
    snow = next(s for s in view["skills"] if s["name"] == "Snowflake")
    assert snow["postings"] == 2 and snow["required"] == 1
    assert {f["name"]: f["postings"] for f in view["families"]} == {
        "Data Engineer": 2, "Data Analyst": 1}


def test_trends_say_why_when_history_is_too_short(tmp_path):
    _, conn, user_id = _store(tmp_path)
    rows, postings = _rows(conn, user_id)
    trends = market.build(rows, postings, FAMILIES, {})["trends"]
    assert trends["available"] is False
    assert "at least" in trends["reason"]


def test_trends_call_a_skill_rising_from_counts():
    postings, rows = [], []
    for i in range(120):
        day = "2026-08-01" if i < 60 else "2026-10-01"
        postings.append({"id": i, "title": "Data Engineer",
                         "posted_date": day, "first_seen": day})
        # dbt in 5 of the old postings, 30 of the new ones.
        if (i < 60 and i < 5) or (i >= 60 and i < 90):
            rows.append({"role_id": i, "name": "dbt", "category": "tool",
                         "requirement": "required", "evidence": "dbt",
                         "title": "t", "company": "c", "url": "u"})
    trends = market.build(rows, postings, FAMILIES, {})["trends"]
    assert trends["available"]
    assert [t["name"] for t in trends["rising"]] == ["dbt"]


# ── resume comparison ─────────────────────────────────────────────────────
RESUME = {"skills": [{"name": "SQL", "aliases": []},
                     {"name": "Apache Airflow", "aliases": ["airflow"]}],
          "extracted_text": "Wrote SQL daily. Built Go-to-market dashboards "
                            "and reports in Excel."}


def test_a_listed_skill_is_had():
    status = compare.exact_status({"name": "Airflow", "variants": []}, RESUME)
    assert status["status"] == compare.HAVE and status["how"] == "listed"


def test_a_skill_named_in_the_resume_text_is_had_with_its_words():
    status = compare.exact_status({"name": "Excel", "variants": []}, RESUME)
    assert status["how"] == "text" and "Excel" in status["evidence"]


def test_a_two_letter_name_in_prose_is_not_evidence():
    assert compare.exact_status({"name": "Go", "variants": []}, RESUME) is None


def test_claude_claims_need_a_quote_from_the_resume():
    demand = [{"name": "Snowflake", "category": "platform", "variants": []},
              {"name": "dbt", "category": "tool", "variants": []}]

    class Judge:
        def __call__(self, **_):
            return {"skills": [
                {"name": "Snowflake", "status": "adjacent",
                 "related_to": "SQL", "evidence": "Wrote SQL daily"},
                {"name": "dbt", "status": "have", "related_to": "",
                 "evidence": "Led dbt migrations"}]}
    result = compare.compare(demand, RESUME, Judge())
    assert result["Snowflake"]["status"] == compare.ADJACENT
    assert result["dbt"]["status"] == compare.MISSING


# ── ranking ───────────────────────────────────────────────────────────────
def _market(skills, total):
    return {"postings": total, "skills": skills, "trends": {}}


def _skill(name, roles, required, category="tool"):
    return {"name": name, "category": category, "postings": len(roles),
            "required": len(required), "role_ids": roles,
            "required_ids": required, "samples": []}


def test_soft_skills_and_skills_you_have_are_not_gaps():
    view = _market([_skill("SQL", [1, 2], [1, 2]),
                    _skill("Communication", [1, 2], [1, 2], "soft"),
                    _skill("dbt", [1], [1])], 2)
    statuses = {"SQL": {"status": "have"}, "dbt": {"status": "missing"},
                "Communication": {"status": "missing"}}
    names = [g["name"] for g in rank.rank(view, statuses)["gaps"]]
    assert names == ["dbt"]


def test_a_near_miss_gap_outranks_an_equally_demanded_one():
    # Both named as a requirement by two postings. Kafka is the only thing
    # standing between the user and postings 1-2; Rust sits beside three
    # other missing skills in 3-4.
    view = _market([
        _skill("SQL", [1, 2], [1, 2]),
        _skill("Kafka", [1, 2], [1, 2]),
        _skill("Rust", [3, 4], [3, 4]),
        _skill("A", [3, 4], [3, 4]), _skill("B", [3, 4], [3, 4]),
        _skill("C", [3, 4], [3, 4])], 4)
    statuses = {n: {"status": "missing"} for n in "Kafka Rust A B C".split()}
    statuses["SQL"] = {"status": "have"}
    ranked = rank.rank(view, statuses)
    assert ranked["gaps"][0]["name"] == "Kafka"
    assert any("last 2 missing" in r for r in ranked["gaps"][0]["reasons"])
    assert ranked["coverage"]["within_two"] == 2
    assert ranked["after"]["meets_all"] == 4


def test_reasons_are_counts_and_never_the_score():
    view = _market([_skill("dbt", [1, 2, 3], [1, 2])], 3)
    gap = rank.rank(view, {"dbt": {"status": "adjacent",
                                   "related_to": "SQL"}})["gaps"][0]
    text = " ".join(gap["reasons"])
    assert "Named in 3 of 3 postings (2 as a requirement)." in text
    assert "Builds on SQL" in text
    assert str(gap["_score"]) not in text


# ── path validation ───────────────────────────────────────────────────────
GAPS = [{"name": "Snowflake", "category": "platform", "reasons": ["r"]},
        {"name": "dbt", "category": "tool", "reasons": ["r"]}]


def test_the_planner_cannot_add_a_skill_the_ranking_did_not_give_it():
    plan = path.validate({"summary": "s", "stages": [
        {"title": "t", "skills": ["snowflake", "Rust"], "goal": "g",
         "why_now": "w", "learn": [], "project": "p", "show_it": "s",
         "effort": "small"}], "left_out": []}, GAPS)
    assert plan["stages"][0]["skills"] == ["Snowflake"]
    assert [x["skill"] for x in plan["left_out"]] == ["dbt"]


def test_a_stage_with_no_ranked_skill_is_dropped():
    plan = path.validate({"summary": "", "stages": [
        {"title": "t", "skills": ["Rust"], "goal": "", "why_now": "",
         "learn": [], "project": "", "show_it": "", "effort": "huge"}],
        "left_out": []}, GAPS)
    assert plan["stages"] == []


def test_links_are_stripped_from_advice():
    plan = path.validate({"summary": "See https://example.com/course now",
                          "stages": [], "left_out": []}, GAPS)
    assert "http" not in plan["summary"]


# ── pipeline, store, page, routes ─────────────────────────────────────────
def _settings_and_vocab():
    return {"workers": 2, "top_gaps": 5}, {"skill_names": ["SQL"],
                                           "role_families": FAMILIES}


def test_pipeline_writes_one_grounded_snapshot(tmp_path, monkeypatch):
    db, conn, user_id = _store(tmp_path)
    model = FakeModel(_role_ids(conn))
    monkeypatch.setattr(pipeline, "load_settings", _settings_and_vocab)
    path_id = learning.start(conn, user_id)
    conn.close()
    pipeline.work(db, user_id, path_id, model)

    conn = connect(db)
    row = learning.get(conn, path_id)
    assert row["status"] == "OK", row["error"]
    analysis, plans = row["analysis"], row["path"]
    overall = analysis["views"][0]
    assert overall["key"] == "all"
    plan = plans["all"]
    gaps = [g["name"] for g in overall["gaps"]]
    assert "SQL" not in gaps and "Apache Airflow" not in gaps
    assert "Communication" not in gaps
    assert gaps[0] == "Snowflake"
    assert plan["stages"][0]["skills"] == ["Snowflake"]
    assert analysis["unverified"] == 1


def test_pipeline_failure_is_recorded_on_the_row(tmp_path, monkeypatch):
    db, conn, user_id = _store(tmp_path)
    monkeypatch.setattr(pipeline, "load_settings", _settings_and_vocab)
    path_id = learning.start(conn, user_id)
    conn.close()
    pipeline.work(db, user_id, path_id, FakeModel({}, fail=True))
    conn = connect(db)
    row = learning.get(conn, path_id)
    assert row["status"] == "FAILED"
    assert "401" in row["error"]


def test_only_one_analysis_runs_at_a_time(tmp_path):
    _, conn, user_id = _store(tmp_path)
    assert learning.start(conn, user_id) is not None
    assert learning.start(conn, user_id) is None


@pytest.fixture
def app_client(tmp_path, monkeypatch):
    db, conn, user_id = _store(tmp_path)
    model = FakeModel(_role_ids(conn))
    conn.close()
    monkeypatch.setattr(pipeline, "load_settings", _settings_and_vocab)
    app = create_app(db_path=db, user_name="G", run_in_thread=False,
                     learning_model=model)
    app.config.update(TESTING=True)
    return app.test_client()


def test_learn_page_offers_to_build_a_path_when_there_is_none(app_client):
    r = app_client.get("/learn")
    assert r.status_code == 200
    assert b"BUILD MY PATH" in r.data
    assert b'href="/learn"' not in r.data  # the active tab is not a link
    assert b"LEARN" in r.data


def test_building_a_path_renders_stages_and_evidence(app_client):
    r = app_client.post("/api/learning-path")
    assert r.status_code == 201
    poll = app_client.get(f"/api/learning-path/{r.get_json()['path_id']}")
    assert poll.get_json()["status"] == "OK"
    page = app_client.get("/learn").data.decode()
    assert "Warehouse" in page
    assert "Snowflake is a plus" in page          # the posting's words
    assert "Underwater basketry" not in page      # the planner's invention
    assert "Wrote SQL daily" in page              # the resume's words
    assert "_score" not in page


def test_other_pages_link_to_learn(app_client):
    assert b'href="/learn"' in app_client.get("/profile").data


def test_polling_an_unknown_analysis_is_404(app_client):
    assert app_client.get("/api/learning-path/999").status_code == 404


# ── the Claude wrapper ────────────────────────────────────────────────────
class _Block:
    def __init__(self, text):
        self.type, self.text = "text", text


class _Response:
    def __init__(self, text, stop="end_turn"):
        self.content, self.stop_reason = [_Block(text)], stop


class _Endpoint:
    def __init__(self, response):
        self.response, self.kwargs = response, None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return self.response


class _Client:
    def __init__(self, response):
        self.messages = _Endpoint(response)
        self.beta = type("B", (), {"messages": _Endpoint(response)})()


def test_wrapper_asks_for_structured_json_with_refusal_fallback():
    from src.skills.claude import ClaudeJson
    client = _Client(_Response('{"ok": true}'))
    model = ClaudeJson("claude-opus-5-5", client=client)
    assert model(system="s", prompt="p", schema={"type": "object"}) == {"ok": True}
    sent = client.beta.messages.kwargs
    assert sent["output_config"]["format"]["type"] == "json_schema"
    assert sent["betas"] == ["server-side-fallback-2026-07-01"]
    assert sent["extra_body"] == {"fallbacks": "default"}
    assert "thinking" not in sent  # Opus 5.5 runs adaptive by default


def test_wrapper_raises_on_refusal_and_truncation():
    from src.skills.claude import ClaudeJson, ModelError
    for stop in ("refusal", "max_tokens"):
        model = ClaudeJson("claude-haiku-5-5",
                           client=_Client(_Response("{}", stop)))
        with pytest.raises(ModelError):
            model(system="s", prompt="p", schema={})


def test_reading_and_planning_can_use_different_models(tmp_path, monkeypatch):
    db, conn, user_id = _store(tmp_path)
    ids = _role_ids(conn)
    planner, reader = FakeModel(ids), FakeModel(ids)
    monkeypatch.setattr(pipeline, "load_settings", _settings_and_vocab)
    settings, vocab = _settings_and_vocab()
    pipeline.analyse(conn, user_id, planner, settings, vocab, reader=reader)
    assert extract.SYSTEM in reader.calls and market.MERGE_SYSTEM in reader.calls
    assert extract.SYSTEM not in planner.calls
    assert compare.SYSTEM in planner.calls and path.SYSTEM in planner.calls


def test_config_names_a_separate_reader(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-not-a-key")
    planner, reader = pipeline.build_models(
        {"model": "claude-opus-5-5", "read_model": "claude-haiku-5-5"})
    assert (planner.model, reader.model) == ("claude-opus-5-5",
                                             "claude-haiku-5-5")
    same, also = pipeline.build_models({"model": "claude-opus-5-5"})
    assert same is also



class BatchingModel(FakeModel):
    """FakeModel plus the Batch API: answers every request at once."""

    def __init__(self, ids, errored=(), create_fails=False):
        super().__init__(ids)
        self.errored, self.create_fails = set(errored), create_fails
        self.batched = 0

    def batch(self, requests, *, schema, effort="low", on_wait=None):
        if self.create_fails:
            raise RuntimeError("401 invalid x-api-key")
        if on_wait:
            on_wait(0, len(requests))
        self.batched += len(requests)
        return {cid: (RuntimeError("batch request errored")
                      if cid in self.errored
                      else self(system=system, prompt=prompt, schema=schema))
                for cid, system, prompt in requests}


def test_batch_reading_stores_the_same_grounded_skills(tmp_path, monkeypatch):
    _, conn, user_id = _store(tmp_path)
    monkeypatch.setattr(extract, "BATCH_SIZE", 1)
    model = BatchingModel(_role_ids(conn))
    totals = extract.extract_pending(conn, user_id, model, [], use_batch=True)
    assert model.batched == 3 and totals["read"] == 3
    names = {r["name"] for r in conn.execute("SELECT name FROM posting_skill")}
    assert "Rust" not in names and "Snowflake" in names


def test_an_errored_batch_request_leaves_its_postings_unread(tmp_path,
                                                             monkeypatch):
    _, conn, user_id = _store(tmp_path)
    monkeypatch.setattr(extract, "BATCH_SIZE", 1)
    model = BatchingModel(_role_ids(conn), errored={"0"})
    totals = extract.extract_pending(conn, user_id, model, [], use_batch=True)
    assert totals["read"] == 2 and totals["failed_batches"] == 1
    assert len(extract.pending_roles(conn, user_id)) == 1


def test_a_batch_that_cannot_be_created_stops_the_analysis(tmp_path):
    _, conn, user_id = _store(tmp_path)
    model = BatchingModel(_role_ids(conn), create_fails=True)
    totals = extract.extract_pending(conn, user_id, model, [], use_batch=True)
    assert totals["aborted"] and "401" in totals["error"]
    assert len(extract.pending_roles(conn, user_id)) == 3


def test_small_reads_skip_the_batch_wait(tmp_path, monkeypatch):
    db, conn, user_id = _store(tmp_path)
    model = BatchingModel(_role_ids(conn))
    settings = {"batch": True, "batch_min_postings": 50}
    pipeline.analyse(conn, user_id, model, settings,
                     _settings_and_vocab()[1])
    assert model.batched == 0


def test_wrapper_sends_a_batch_and_parses_each_result():
    from types import SimpleNamespace as NS
    from src.skills.claude import ClaudeJson, ModelError

    class Batches:
        def create(self, requests):
            self.sent = requests
            return NS(id="b1")

        def retrieve(self, _id):
            return NS(processing_status="ended")

        def results(self, _id):
            return [NS(custom_id="0", result=NS(
                        type="succeeded",
                        message=_Response('{"postings": []}'))),
                    NS(custom_id="1", result=NS(type="errored"))]

    client = _Client(_Response("{}"))
    client.messages.batches = Batches()
    model = ClaudeJson("claude-sonnet-5-5", client=client)
    out = model.batch([("0", "s", "p0"), ("1", "s", "p1")], schema={})
    assert out["0"] == {"postings": []}
    assert isinstance(out["1"], ModelError)
    sent = client.messages.batches.sent[0]["params"]
    assert sent["output_config"]["format"]["type"] == "json_schema"
    assert "extra_body" not in sent  # no fallbacks on the Batch API


def test_the_window_leaves_older_postings_unread_and_uncounted(tmp_path):
    _, conn, user_id = _store(tmp_path)
    ids = _role_ids(conn)
    conn.execute("UPDATE role SET posted_date = '2026-01-05' WHERE id = ?",
                 (ids["https://x/3"],))
    since = "2026-09-01"
    pending = {r["id"] for r in extract.pending_roles(conn, user_id,
                                                      since=since)}
    assert ids["https://x/3"] not in pending and len(pending) == 2
    extract.extract_pending(conn, user_id, FakeModel(ids), [], since=since)
    counted = {p["id"] for p in extract.read_postings(conn, user_id, since)}
    assert counted == {ids["https://x/1"], ids["https://x/2"]}
    assert not any(r["role_id"] == ids["https://x/3"]
                   for r in extract.evidence_rows(conn, user_id, since))



def _family_settings():
    return ({"workers": 2, "top_gaps": 5, "min_family_postings": 2},
            {"skill_names": [], "role_families": FAMILIES})


def test_each_kind_of_role_with_enough_postings_gets_its_own_path(
        tmp_path, monkeypatch):
    db, conn, user_id = _store(tmp_path)
    model = FakeModel(_role_ids(conn))
    monkeypatch.setattr(pipeline, "load_settings", _family_settings)
    path_id = learning.start(conn, user_id)
    conn.close()
    pipeline.work(db, user_id, path_id, model)
    row = learning.get(connect(db), path_id)
    keys = [v["key"] for v in row["analysis"]["views"]]
    # Data Analyst has one posting, below the minimum of two.
    assert keys == ["all", "data-engineer"]
    assert set(row["path"]) == {"all", "data-engineer"}
    engineer = row["analysis"]["views"][1]
    assert engineer["postings"] == 2
    # Tableau is only asked for by the analyst posting.
    assert "Tableau" not in [s["name"] for s in engineer["skills"]]
    assert any("for Data Engineer roles" in c for c in model.prompts)


def test_the_page_shows_the_chosen_kind_of_role(tmp_path, monkeypatch):
    db, conn, user_id = _store(tmp_path)
    model = FakeModel(_role_ids(conn))
    conn.close()
    monkeypatch.setattr(pipeline, "load_settings", _family_settings)
    app = create_app(db_path=db, user_name="G", run_in_thread=False,
                     learning_model=model)
    client = app.test_client()
    client.post("/api/learning-path")
    page = client.get("/learn?role=data-engineer").data.decode()
    assert "YOUR PATH · DATA ENGINEER" in page
    assert 'href="/learn?role=all"' in page
    assert "BY KIND OF ROLE" not in page
    # An unknown role falls back to all roles rather than erroring.
    assert "YOUR PATH · ALL ROLES" in client.get("/learn?role=nope").data.decode()


def test_a_path_stored_before_the_split_still_renders():
    from src.learning_page import render
    row = {"id": 1, "status": "OK", "finished_at": "2026-10-14T08:51:03+00:00",
           "model": "m", "path": {"summary": "s", "stages": [], "left_out": []},
           "analysis": {"postings": 3, "skills": [], "gaps": [],
                        "coverage": {}, "after": None, "trends": {},
                        "families": [], "resume_labels": ["ae"]}}
    page = render(row, row)
    assert "YOUR PATH · ALL ROLES" in page
    assert "CHOOSE A KIND OF ROLE" not in page
