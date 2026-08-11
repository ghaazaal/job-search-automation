"""Tests for the setup routes in src/app.py.

No network: the LLM is injected. The PDF is a real, minimal one so pdfminer
does the extraction it will do in production.
"""
import io
import json
import re

import pytest

from src.app import create_app
from src.store.db import connect
from src.store.ingest import ensure_user
from src.store.schema import init_db
from tests.conftest import MockLLMClient

# A handcrafted PDF with one line of text. pdfminer reads it without an xref.
_PDF = (
    b"%PDF-1.4\n"
    b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 300 300]"
    b"/Resources<</Font<</F1 4 0 R>>>>/Contents 5 0 R>>endobj\n"
    b"4 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n"
    b"5 0 obj<</Length 62>>stream\n"
    b"BT /F1 12 Tf 20 200 Td (Power BI and SQL and dbt) Tj ET\n"
    b"endstream\nendobj\n"
    b"trailer<</Root 1 0 R/Size 6>>\n"
)

# A different resume, for the tests that need two. The replacement is exactly
# 24 bytes, the same as the text it replaces, so `/Length 62` stays honest.
_OTHER_PDF = _PDF.replace(b"Power BI and SQL and dbt",
                          b"Airflow and Python dbt..")
assert len(_OTHER_PDF) == len(_PDF)


def _visible(html: str) -> str:
    """The document with its CSS and JS stripped — what a reader sees."""
    return re.sub(r"<(style|script)\b.*?</\1>", "", html, flags=re.DOTALL)


_PARSE_REPLY = json.dumps({
    "target_roles": [{"title": "BI Developer", "aliases": ["bi engineer"]}],
    "skills": [{"name": "Power BI", "tier": "core", "aliases": ["dax"]}],
    "seniority": "senior",
})


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "test.db"
    conn = connect(path)
    init_db(conn)
    ensure_user(conn, "G")
    conn.close()
    return path


@pytest.fixture
def client(db, tmp_path):
    app = create_app(db_path=db, user_name="G",
                     data_root=tmp_path / "data",
                     llm_factory=lambda: MockLLMClient(_PARSE_REPLY))
    app.config.update(TESTING=True)
    return app.test_client()


def _upload(client, name="Ghazal BI.pdf", data=_PDF):
    return client.post("/api/resumes",
                       data={"resume": (io.BytesIO(data), name)},
                       content_type="multipart/form-data")


def test_the_setup_screen_renders(client):
    response = client.get("/setup")
    assert response.status_code == 200
    assert b"YOUR RESUME" in response.data


def test_uploading_a_pdf_returns_a_resume_id(client):
    response = _upload(client)
    assert response.status_code == 201
    assert isinstance(response.get_json()["resume_id"], int)


def test_uploading_stores_the_file_under_the_data_root(client, tmp_path):
    _upload(client)
    written = list((tmp_path / "data" / "resumes").rglob("*.pdf"))
    assert len(written) == 1
    assert written[0].read_bytes() == _PDF


def test_uploading_runs_the_parse_and_saves_the_result(client, db):
    resume_id = _upload(client).get_json()["resume_id"]
    from src.store.profile import get_resume
    conn = connect(db)
    resume = get_resume(conn, 1, resume_id)
    conn.close()
    assert resume["seniority"] == "senior"
    assert resume["target_roles"][0]["title"] == "BI Developer"
    assert resume["skills"][0]["name"] == "Power BI"
    assert "Power BI" in resume["extracted_text"]


def test_the_label_comes_from_the_filename(client, db):
    resume_id = _upload(client, name="Ghazal BI.pdf").get_json()["resume_id"]
    from src.store.profile import get_resume
    conn = connect(db)
    label = get_resume(conn, 1, resume_id)["label"]
    conn.close()
    assert label == "ghazal bi"


def test_a_second_file_with_the_same_name_gets_its_own_label(client, db):
    _upload(client, name="resume.pdf", data=_PDF)
    resume_id = _upload(client, name="resume.pdf",
                        data=_OTHER_PDF).get_json()["resume_id"]
    from src.store.profile import get_resume
    conn = connect(db)
    label = get_resume(conn, 1, resume_id)["label"]
    conn.close()
    assert label == "resume 2"


def test_the_same_file_twice_is_refused(client):
    _upload(client)
    response = _upload(client, name="a different name.pdf")
    assert response.status_code == 409
    assert "already uploaded" in response.get_json()["error"]


def test_a_non_pdf_is_refused_with_its_own_message(client):
    response = _upload(client, name="resume.docx", data=b"PK\x03\x04zip")
    assert response.status_code == 400
    assert "not a PDF" in response.get_json()["error"]


def test_an_oversized_pdf_is_refused_with_its_own_message(client):
    response = _upload(client, data=_PDF + b"x" * (5 * 1024 * 1024))
    assert response.status_code == 400
    assert "5 MB" in response.get_json()["error"]


def test_a_request_body_far_over_the_cap_is_rejected_by_flask_itself(client):
    huge = _PDF + b"x" * (21 * 1024 * 1024)
    response = _upload(client, data=huge)
    assert response.status_code == 413


def test_sending_no_file_is_a_400(client):
    response = client.post("/api/resumes", data={},
                           content_type="multipart/form-data")
    assert response.status_code == 400


def test_a_failing_parse_still_stores_the_resume(db, tmp_path):
    """The confirm screen asks for the details by hand rather than 500ing."""
    def _explode():
        raise RuntimeError("no API key")

    app = create_app(db_path=db, user_name="G", data_root=tmp_path / "data",
                     llm_factory=_explode)
    app.config.update(TESTING=True)
    response = _upload(app.test_client())
    assert response.status_code == 201

    from src.store.profile import get_resume
    conn = connect(db)
    resume = get_resume(conn, 1, response.get_json()["resume_id"])
    conn.close()
    assert resume["target_roles"] == []
    assert resume["seniority"] is None


def test_the_confirm_screen_shows_what_was_parsed(client):
    resume_id = _upload(client).get_json()["resume_id"]
    response = client.get(f"/setup/confirm/{resume_id}")
    assert response.status_code == 200
    body = response.data.decode("utf-8")
    assert "BI Developer" in body
    assert "Power BI" in body


def test_the_first_resume_is_asked_where_you_live(client):
    resume_id = _upload(client).get_json()["resume_id"]
    body = client.get(f"/setup/confirm/{resume_id}").data.decode("utf-8")
    assert 'id="location"' in body


def test_a_missing_resume_is_a_404(client):
    assert client.get("/setup/confirm/9999").status_code == 404


def test_saving_edits_overwrites_roles_skills_and_seniority(client, db):
    resume_id = _upload(client).get_json()["resume_id"]
    response = client.post(f"/api/resumes/{resume_id}", json={
        "label": "BI Dev",
        "target_roles": [{"title": "BI Analyst", "aliases": []}],
        "skills": [{"name": "SQL", "tier": "working", "aliases": []}],
        "seniority": "mid"})
    assert response.status_code == 200

    from src.store.profile import get_resume
    conn = connect(db)
    resume = get_resume(conn, 1, resume_id)
    conn.close()
    assert resume["label"] == "bi dev"
    assert resume["target_roles"] == [{"title": "BI Analyst", "aliases": []}]
    assert resume["seniority"] == "mid"


def test_saving_without_a_label_is_a_400(client):
    resume_id = _upload(client).get_json()["resume_id"]
    response = client.post(f"/api/resumes/{resume_id}", json={
        "label": "  ", "target_roles": [], "skills": [], "seniority": "mid"})
    assert response.status_code == 400


def test_saving_an_unknown_seniority_is_a_400(client):
    resume_id = _upload(client).get_json()["resume_id"]
    response = client.post(f"/api/resumes/{resume_id}", json={
        "label": "x", "target_roles": [], "skills": [],
        "seniority": "grand wizard"})
    assert response.status_code == 400


def test_saving_a_missing_resume_is_a_404(client):
    response = client.post("/api/resumes/9999", json={
        "label": "x", "target_roles": [], "skills": [], "seniority": "mid"})
    assert response.status_code == 404


def test_reusing_another_resumes_label_is_a_409(client):
    first = _upload(client, name="one.pdf").get_json()["resume_id"]
    second = _upload(client, name="two.pdf",
                     data=_OTHER_PDF).get_json()["resume_id"]
    assert first != second
    response = client.post(f"/api/resumes/{second}", json={
        "label": "one", "target_roles": [], "skills": [], "seniority": "mid"})
    assert response.status_code == 409


def test_a_non_list_target_roles_is_treated_as_empty_not_a_500(client, db):
    """A malformed payload degrades gracefully instead of crashing list()."""
    resume_id = _upload(client).get_json()["resume_id"]
    response = client.post(f"/api/resumes/{resume_id}", json={
        "label": "x", "target_roles": 5, "skills": [], "seniority": "mid"})
    assert response.status_code == 200

    from src.store.profile import get_resume
    conn = connect(db)
    resume = get_resume(conn, 1, resume_id)
    conn.close()
    assert resume["target_roles"] == []


def test_deleting_a_resume_removes_the_row_and_the_file(client, db, tmp_path):
    resume_id = _upload(client).get_json()["resume_id"]
    assert list((tmp_path / "data" / "resumes").rglob("*.pdf"))

    response = client.delete(f"/api/resumes/{resume_id}")
    assert response.status_code == 200

    from src.store.profile import get_resume
    conn = connect(db)
    assert get_resume(conn, 1, resume_id) is None
    conn.close()
    assert not list((tmp_path / "data" / "resumes").rglob("*.pdf"))


def test_deleting_a_missing_resume_is_a_404(client):
    assert client.delete("/api/resumes/9999").status_code == 404


def test_saving_the_profile_records_location_and_work_modes(client, db):
    response = client.post("/api/profile", json={
        "location": "Toronto, ON", "country": "CA",
        "work_modes": ["remote", "hybrid"]})
    assert response.status_code == 200

    from src.store.profile import get_profile as read
    conn = connect(db)
    profile = read(conn, 1)
    conn.close()
    assert profile == {"location": "Toronto, ON", "country": "ca",
                       "work_modes": ["remote", "hybrid"],
                       "setup_complete": True}


def test_saving_the_profile_with_no_work_mode_is_a_400(client):
    response = client.post("/api/profile", json={
        "location": "Toronto", "country": "ca", "work_modes": []})
    assert response.status_code == 400


def test_saving_the_profile_with_an_unknown_work_mode_is_a_400(client):
    response = client.post("/api/profile", json={
        "location": "Toronto", "country": "ca", "work_modes": ["telepathic"]})
    assert response.status_code == 400


def test_a_non_list_work_modes_is_a_400_not_a_500(client):
    """Same malformed-payload class as target_roles: degrade, don't crash."""
    response = client.post("/api/profile", json={
        "location": "Toronto", "country": "ca", "work_modes": 5})
    assert response.status_code == 400


def test_a_second_resume_is_not_asked_where_you_live_again(client):
    client.post("/api/profile", json={"location": "Toronto, ON",
                                      "country": "ca",
                                      "work_modes": ["remote"]})
    resume_id = _upload(client, name="second.pdf",
                        data=_OTHER_PDF).get_json()["resume_id"]
    body = client.get(f"/setup/confirm/{resume_id}").data.decode("utf-8")
    assert 'id="location"' not in body


def test_the_profile_screen_lists_the_uploaded_resume(client):
    _upload(client, name="Ghazal BI.pdf")
    response = client.get("/profile")
    assert response.status_code == 200
    assert b"ghazal bi" in response.data


def test_the_profile_screen_works_before_anything_is_uploaded(client):
    response = client.get("/profile")
    assert response.status_code == 200
    assert b"No resumes yet" in response.data


def test_the_profile_screen_shows_the_saved_location(client):
    client.post("/api/profile", json={"location": "Toronto, ON",
                                      "country": "ca",
                                      "work_modes": ["remote", "hybrid"]})
    body = client.get("/profile").data.decode("utf-8")
    assert "Toronto, ON" in body
    assert "remote, hybrid" in body


_NEW_ROUTES = ["/setup", "/profile"]


def test_no_new_screen_leaks_a_score(client):
    """CLAUDE.md: the numeric score is internal. No new route may emit it,
    and no new route may render a bare percentage."""
    _upload(client)
    for route in _NEW_ROUTES:
        body = _visible(client.get(route).data.decode("utf-8"))
        assert "match_score" not in body, route
        assert "%" not in body, route


def test_the_confirm_screen_leaks_no_score(client):
    resume_id = _upload(client).get_json()["resume_id"]
    body = _visible(
        client.get(f"/setup/confirm/{resume_id}").data.decode("utf-8"))
    assert "match_score" not in body
    assert "%" not in body


def test_no_json_response_leaks_a_score(client):
    resume_id = _upload(client).get_json()["resume_id"]
    responses = [
        _upload(client, name="second.pdf", data=_OTHER_PDF),
        client.post(f"/api/resumes/{resume_id}", json={
            "label": "x", "target_roles": [], "skills": [], "seniority": "mid"}),
        client.post("/api/profile", json={"location": "T", "country": "ca",
                                          "work_modes": ["remote"]}),
        client.delete(f"/api/resumes/{resume_id}"),
    ]
    for response in responses:
        body = response.data.decode("utf-8")
        assert "match_score" not in body
        assert "%" not in body


def test_the_extracted_text_never_reaches_a_screen(client):
    """A whole resume rendered into a page is a lot of personal data on
    screen for no reason. Only the parsed profile is shown."""
    _upload(client)
    for route in _NEW_ROUTES:
        assert b"Power BI and SQL and dbt" not in client.get(route).data
