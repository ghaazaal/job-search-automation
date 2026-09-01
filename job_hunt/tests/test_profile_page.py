"""Tests for src/profile_page.py — rendering only, no database, no Flask.

The profile page is the design handoff's fourth surface. What matters
here: every fact rendered comes from the inputs, the shell nav is
present, no numeric score or fabricated cadence appears, and hostile
input cannot break out of markup or script.
"""
import re

from src.profile_page import render

_RESUMES = [
    {"id": 1, "label": "bi developer", "seniority": "senior",
     "is_active": True, "created_at": "2026-03-14T09:00:00",
     "target_roles": [{"title": "BI Developer", "aliases": []}],
     "skills": [{"name": "Power BI", "tier": "core", "aliases": []},
                {"name": "Airflow", "tier": "working", "aliases": []}]},
    {"id": 2, "label": "data engineer", "seniority": "mid",
     "is_active": False, "created_at": "2026-08-02T09:00:00",
     "target_roles": [], "skills": []},
]
_SET_PROFILE = {"location": "Toronto, ON", "country": "ca",
                "work_modes": ["remote"], "setup_complete": True}
_EMPTY_PROFILE = {"location": "", "country": "", "work_modes": [],
                  "setup_complete": False}
_WATCHED = [
    {"id": 7, "company_name": "DataArt", "resolution": "ats",
     "last_yield_count": 10},
    {"id": 8, "company_name": "Andersen Lab", "resolution": "linkedin",
     "last_yield_count": None},
]


def _visible(html: str) -> str:
    """The document with its CSS and JS stripped — what a reader actually
    sees. The product rules are about what reaches the reader, and a `%`
    in a stylesheet is not a percentage on the screen."""
    return re.sub(r"<(style|script)\b.*?</\1>", "", html, flags=re.DOTALL)


def test_output_is_a_full_document():
    html = render(_RESUMES, _SET_PROFILE)
    assert html.startswith("<!DOCTYPE html>")
    assert "</html>" in html


def test_the_shell_nav_is_present_with_profile_active():
    html = render(_RESUMES, _SET_PROFILE)
    assert 'href="/"' in html
    assert 'href="/activity"' in html
    assert 'aria-current="page"' in html
    assert "opportunity map" in html


def test_every_resume_is_listed():
    html = render(_RESUMES, _SET_PROFILE)
    assert "bi developer" in html
    assert "data engineer" in html


def test_a_paused_resume_is_marked_and_offers_resume():
    html = render(_RESUMES, _SET_PROFILE)
    assert "PAUSED" in html
    assert "RESUME</button>" in html


def test_an_active_resume_offers_pause():
    assert "PAUSE</button>" in render(_RESUMES, _SET_PROFILE)


def test_resume_counts_in_the_card_meta():
    html = render(_RESUMES, _SET_PROFILE)
    assert "1 ACTIVE" in html
    assert "1 PAUSED" in html


def test_each_resume_links_to_its_confirm_screen():
    html = render(_RESUMES, _SET_PROFILE)
    assert 'href="/setup/confirm/1"' in html
    assert 'data-delete="2"' in html
    assert 'data-toggle="1"' in html


def test_the_pause_toggle_carries_the_whole_resume():
    """The update endpoint overwrites roles and skills, so the page's
    payload must carry them for the toggle to send back."""
    html = render(_RESUMES, _SET_PROFILE)
    assert "BI Developer" in html
    assert '"is_active"' in html


def test_where_you_are_looking_shows_the_profile():
    html = render(_RESUMES, _SET_PROFILE)
    assert "Toronto, ON" in html
    assert "remote" in html


def test_an_incomplete_profile_points_at_setup():
    html = render(_RESUMES, _EMPTY_PROFILE)
    assert "Not set" in html
    assert 'href="/setup/confirm/1"' in html


def test_match_card_lists_active_skills_only():
    html = render(_RESUMES, _SET_PROFILE)
    assert "Power BI" in html
    assert "WHAT COUNTS AS A MATCH" in html


def test_watchlist_rows_render_with_remove():
    html = render(_RESUMES, _SET_PROFILE, watched=_WATCHED)
    assert "DataArt" in html
    assert 'data-unwatch="7"' in html
    assert "2 COMPANIES" in html


def test_no_cadence_is_claimed_for_the_watchlist():
    """The run schedule lives outside the app; the page must not claim
    one."""
    html = _visible(render(_RESUMES, _SET_PROFILE, watched=_WATCHED))
    assert "DAILY" not in html
    assert "WEEKLY" not in html


def test_filtered_card_states_the_real_counts():
    html = render(_RESUMES, _SET_PROFILE,
                  filtered={"closed": 570, "unverified": 34, "offtopic": 5})
    assert "what got filtered out" in html
    assert "570" in html
    assert "34" in html
    assert "5 were not one of your target roles" in html


def test_filtered_card_with_nothing_filtered_says_so():
    html = render(_RESUMES, _SET_PROFILE, filtered={})
    assert "Nothing has been filtered out yet" in html


def test_with_no_resumes_it_points_at_the_upload_screen():
    html = render([], _EMPTY_PROFILE)
    assert "No resumes yet" in html
    assert 'href="/setup"' in html


def test_run_the_search_appears_only_when_it_can_run():
    assert "RUN THE SEARCH NOW" in render(_RESUMES, _SET_PROFILE)
    assert "RUN THE SEARCH NOW" not in render([], _EMPTY_PROFILE)
    paused = [{**_RESUMES[0], "is_active": False}]
    assert "RUN THE SEARCH NOW" not in render(paused, _SET_PROFILE)


def test_never_shows_a_score():
    html = _visible(render(_RESUMES, _SET_PROFILE, watched=_WATCHED,
                           filtered={"closed": 3, "unverified": 1,
                                     "offtopic": 0}))
    assert "match_score" not in html
    assert "%" not in html


def test_names_are_escaped():
    """The markup escapes the label; the JS payload may carry it raw
    inside a JSON string (breakout is prevented by `</` escaping, tested
    below), so only the visible document is checked here."""
    evil = [{"id": 3, "label": '<img src=x onerror=alert(1)>',
             "seniority": "mid", "is_active": True, "created_at": None,
             "target_roles": [], "skills": []}]
    html = _visible(render(evil, _SET_PROFILE))
    assert "<img src=x" not in html


def test_a_hostile_skill_cannot_break_out_of_the_script_block():
    evil = [{**_RESUMES[0], "skills": [
        {"name": "</script><script>alert(1)</script>", "tier": "core",
         "aliases": []}]}]
    html = render(evil, _SET_PROFILE)
    assert "</script><script>alert(1)</script>" not in html


def test_suggestions_offer_one_click_watches():
    html = render(_RESUMES, _SET_PROFILE, watched=_WATCHED)
    assert 'data-suggest="GitLab"' in html


def test_an_already_watched_suggestion_is_not_offered():
    watched = [{"id": 9, "company_name": "GitLab", "resolution": "ats",
                "last_yield_count": 2}]
    html = render(_RESUMES, _SET_PROFILE, watched=watched)
    assert 'data-suggest="GitLab"' not in html
