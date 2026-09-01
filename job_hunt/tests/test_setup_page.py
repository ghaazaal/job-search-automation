"""Tests for src/setup_page.py — rendering only, no database, no Flask."""
import re

from src.setup_page import render_upload


def _visible(html: str) -> str:
    """The document with its CSS and JS stripped — what a reader actually
    sees. The product rules are about what reaches the reader, and a `%` in a
    stylesheet is not a percentage on the screen."""
    return re.sub(r"<(style|script)\b.*?</\1>", "", html, flags=re.DOTALL)


def test_the_upload_screen_is_a_whole_document():
    html = render_upload()
    assert html.startswith("<!DOCTYPE html>")
    assert "</html>" in html


def test_the_upload_screen_offers_a_pdf_file_field():
    html = render_upload()
    assert 'type="file"' in html
    assert 'name="resume"' in html
    assert 'accept="application/pdf"' in html


def test_the_upload_screen_states_the_limits():
    html = render_upload()
    assert "PDF only" in html
    assert "5 MB" in html


def test_a_message_is_shown_when_one_is_passed():
    assert "That is not a PDF." in render_upload("That is not a PDF.")


def test_a_message_is_escaped():
    """The page carries its own <script> block, so check for the escaped
    form rather than the absence of the tag."""
    html = render_upload("<script>alert(1)</script>")
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "alert(1)</script>" not in html


from src.setup_page import render_confirm

_RESUME = {
    "id": 3,
    "label": "bi developer",
    "seniority": "senior",
    "target_roles": [{"title": "BI Developer", "aliases": ["bi engineer"]}],
    "skills": [{"name": "Power BI", "tier": "core", "aliases": ["dax"]},
               {"name": "Airflow", "tier": "working", "aliases": []}],
}
_EMPTY_PROFILE = {"location": "", "country": "", "work_modes": [],
                  "setup_complete": False}
_SET_PROFILE = {"location": "Toronto, ON", "country": "ca",
                "work_modes": ["remote"], "setup_complete": True}


def test_the_confirm_screen_carries_the_parsed_values_into_its_state():
    html = render_confirm(_RESUME, _EMPTY_PROFILE, ask_location=True)
    assert "BI Developer" in html
    assert "Power BI" in html
    assert '"tier": "core"' in html or '"tier":"core"' in html


def test_the_confirm_screen_preselects_the_parsed_seniority():
    html = render_confirm(_RESUME, _EMPTY_PROFILE, ask_location=True)
    assert 'value="senior" checked' in html
    assert 'value="junior" checked' not in html


def test_the_first_resume_is_asked_for_location_and_work_mode():
    html = render_confirm(_RESUME, _EMPTY_PROFILE, ask_location=True)
    assert 'id="location"' in html
    assert 'name="mode"' in html


def test_a_later_resume_skips_the_location_block():
    html = render_confirm(_RESUME, _SET_PROFILE, ask_location=False)
    assert 'id="location"' not in html
    assert 'name="mode"' not in html


def test_an_unparsed_resume_says_so_rather_than_showing_nothing():
    blank = {**_RESUME, "target_roles": [], "skills": [], "seniority": None}
    html = render_confirm(blank, _EMPTY_PROFILE, ask_location=True)
    assert "could not read this resume" in html
    assert 'value="mid" checked' in html


def test_the_resume_id_reaches_the_script():
    html = render_confirm(_RESUME, _EMPTY_PROFILE, ask_location=True)
    assert "const RESUME_ID = 3;" in html


def test_the_confirm_screen_never_shows_a_score():
    html = _visible(render_confirm(_RESUME, _EMPTY_PROFILE, ask_location=True))
    assert "match_score" not in html
    assert "%" not in html


def test_a_hostile_skill_name_cannot_break_out_of_the_script_block():
    evil = {**_RESUME, "skills": [
        {"name": "</script><script>alert(1)</script>", "tier": "core", "aliases": []}]}
    html = render_confirm(evil, _EMPTY_PROFILE, ask_location=True)
    assert "</script><script>alert(1)</script>" not in html
