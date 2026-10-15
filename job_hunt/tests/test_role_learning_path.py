"""Tests for the learning path toward one posting (src/skills/role_path.py,
src/role_learning_page.py and its routes). The model is always a fake."""
import pytest

from src.app import create_app
from src.skills import extract, pipeline, role_path
from src.store import learning
from src.store.db import connect

from tests.test_learning_path import (FakeModel, _role_ids,
                                      _settings_and_vocab, _store)

ENGINEER = "https://x/2"   # SQL, Snowflake, dbt required; Kafka preferred


def _build(tmp_path, monkeypatch, url=ENGINEER, model=None):
    db, conn, user_id = _store(tmp_path)
    ids = _role_ids(conn)
    model = model or FakeModel(ids)
    monkeypatch.setattr(role_path, "load_settings", _settings_and_vocab)
    row_id = learning.role_start(conn, user_id, ids[url])
    conn.close()
    role_path.work(db, user_id, row_id, ids[url], model)
    conn = connect(db)
    return conn, ids, model, learning.role_get(conn, row_id)


def test_the_gaps_are_this_postings_quoted_requirements(tmp_path, monkeypatch):
    _, _, _, row = _build(tmp_path, monkeypatch)
    assert row["status"] == "OK", row["error"]
    analysis = row["analysis"]
    gaps = [g["name"] for g in analysis["gaps"]]
    # Required first, preferred last; SQL is on the resume.
    assert gaps[-1] == "Kafka" and set(gaps) == {"Snowflake", "dbt", "Kafka"}
    assert "SQL" in [h["name"] for h in analysis["have"]]
    assert (analysis["required"], analysis["have_required"]) == (3, 1)
    snow = next(g for g in analysis["gaps"] if g["name"] == "Snowflake")
    assert "A requirement in this posting" in snow["reasons"][0]
    assert "Builds on SQL" in " ".join(snow["reasons"])


def test_a_have_claim_without_a_resume_quote_stays_a_gap(tmp_path,
                                                          monkeypatch):
    # The fake says the resume shows dbt, quoting words the resume lacks.
    _, _, _, row = _build(tmp_path, monkeypatch)
    dbt = next(g for g in row["analysis"]["gaps"] if g["name"] == "dbt")
    assert dbt["status"] == "missing"


def test_the_path_only_plans_this_postings_gaps(tmp_path, monkeypatch):
    _, _, _, row = _build(tmp_path, monkeypatch)
    planned = [s for stage in row["path"]["stages"] for s in stage["skills"]]
    assert "Underwater basketry" not in planned and "Snowflake" in planned


def test_a_posting_already_read_is_not_read_again(tmp_path, monkeypatch):
    db, conn, user_id = _store(tmp_path)
    ids = _role_ids(conn)
    model = FakeModel(ids)
    extract.extract_pending(conn, user_id, model, [])
    model.calls.clear()
    monkeypatch.setattr(role_path, "load_settings", _settings_and_vocab)
    row_id = learning.role_start(conn, user_id, ids[ENGINEER])
    conn.close()
    role_path.work(db, user_id, row_id, ids[ENGINEER], model)
    assert extract.SYSTEM not in model.calls


def test_an_unread_posting_is_read_on_its_own(tmp_path, monkeypatch):
    conn, ids, model, row = _build(tmp_path, monkeypatch)
    assert model.calls.count(extract.SYSTEM) == 1
    assert extract.is_read(conn, ids[ENGINEER])
    # The other postings stay unread for the market analysis.
    assert not extract.is_read(conn, ids["https://x/1"])


def test_no_technical_gap_means_no_path_and_no_planner_call(tmp_path,
                                                            monkeypatch):
    db, conn, user_id = _store(tmp_path)
    ids = _role_ids(conn)
    model = FakeModel(ids, extraction={ids[ENGINEER]: [
        ("SQL", "language", "required", "Must know SQL"),
        ("Communication", "soft", "required", "Must know SQL, Snowflake")]})
    monkeypatch.setattr(role_path, "load_settings", _settings_and_vocab)
    row_id = learning.role_start(conn, user_id, ids[ENGINEER])
    conn.close()
    role_path.work(db, user_id, row_id, ids[ENGINEER], model)
    row = learning.role_get(connect(db), row_id)
    assert row["analysis"]["gaps"] == [] and row["path"]["stages"] == []
    assert [s["name"] for s in row["analysis"]["soft"]] == ["Communication"]
    from src.skills import path
    assert path.SYSTEM not in model.calls


def test_a_posting_without_a_description_fails_with_a_reason(tmp_path,
                                                             monkeypatch):
    db, conn, user_id = _store(tmp_path)
    ids = _role_ids(conn)
    conn.execute("UPDATE role SET description_captured = 0 WHERE id = ?",
                 (ids[ENGINEER],))
    monkeypatch.setattr(role_path, "load_settings", _settings_and_vocab)
    row_id = learning.role_start(conn, user_id, ids[ENGINEER])
    conn.close()
    role_path.work(db, user_id, row_id, ids[ENGINEER], FakeModel(ids))
    row = learning.role_get(connect(db), row_id)
    assert row["status"] == "FAILED" and "description" in row["error"]


def test_only_one_build_per_job_runs_at_a_time(tmp_path):
    _, conn, user_id = _store(tmp_path)
    role_id = _role_ids(conn)[ENGINEER]
    assert learning.role_start(conn, user_id, role_id) is not None
    assert learning.role_start(conn, user_id, role_id) is None


# ── routes and pages ──────────────────────────────────────────────────────
@pytest.fixture
def app_setup(tmp_path, monkeypatch):
    db, conn, user_id = _store(tmp_path)
    ids = _role_ids(conn)
    conn.close()
    monkeypatch.setattr(role_path, "load_settings", _settings_and_vocab)
    monkeypatch.setattr(pipeline, "load_settings", _settings_and_vocab)
    app = create_app(db_path=db, user_name="G", run_in_thread=False,
                     learning_model=FakeModel(ids))
    return app.test_client(), ids


def test_the_job_page_offers_to_build_a_path(app_setup):
    client, ids = app_setup
    page = client.get(f"/learn/role/{ids[ENGINEER]}").data.decode()
    assert "BUILD PATH FOR THIS JOB" in page
    assert "Senior Data Engineer" in page


def test_building_from_the_page_shows_gaps_with_the_postings_words(app_setup):
    client, ids = app_setup
    r = client.post(f"/api/roles/{ids[ENGINEER]}/learning-path")
    assert r.status_code == 201
    poll = client.get(f"/api/role-learning-path/{r.get_json()['path_id']}")
    assert poll.get_json()["status"] == "OK"
    page = client.get(f"/learn/role/{ids[ENGINEER]}").data.decode()
    assert "PATH TO THIS JOB" in page
    assert "SQL, Snowflake and dbt" in page        # the posting's words
    assert "Wrote SQL daily" in page               # the resume's words
    assert "Underwater basketry" not in page
    assert "WHAT YOU ALREADY BRING" in page
    # The LEARN page lists it.
    learn = client.get("/learn").data.decode()
    assert f'href="/learn/role/{ids[ENGINEER]}"' in learn


def test_a_role_that_is_not_yours_is_404(app_setup):
    client, _ = app_setup
    assert client.get("/learn/role/999").status_code == 404
    assert client.post("/api/roles/999/learning-path").status_code == 404
    assert client.get("/api/role-learning-path/999").status_code == 404


def test_the_drawer_links_to_the_job_path():
    from src.drawer import drawer_js
    js = drawer_js("{}")
    assert "LEARNING PATH FOR THIS JOB" in js
    assert "/learn/role/" in js
