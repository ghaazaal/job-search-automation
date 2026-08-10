"""Tests for src/map_page.py — the rendered opportunity map.

These assert the product rules survive rendering. Visual fidelity is checked
by eye against the handoff; the rules are checked here.
"""
import re

from src.map_page import render

_ROLE = {"title": "Senior Analytics Engineer", "location": "Remote, US",
         "date": "2026-08-08", "salary": "$145-170k", "platform": "LinkedIn",
         "url": "https://example.com/job/1", "description": "We use dbt.",
         "band": "STRONG FIT", "match_score": 9, "matched": ["dbt", "airflow"],
         "gaps": ["snowflake"], "description_captured": True,
         "reason": "matches dbt and airflow from your resume"}

_UNCHECKED = {**_ROLE, "title": "Data Engineer", "url": "https://example.com/2",
              "band": None, "description_captured": False, "matched": [],
              "gaps": [], "description": "",
              "reason": "this listing arrived without a description, "
                        "so no skills have been compared against it"}


def _map(name="Acme Analytics", state="ACT_NOW", roles=None, why="2 roles match"):
    return {"name": name, "state": state, "why": why,
            "roles": [_ROLE] if roles is None else roles}


# ── Rule 1: no numeric score anywhere ─────────────────────────────────────────

def test_no_match_score_is_rendered():
    html = render([_map()])
    assert "match_score" not in html
    assert ">9<" not in html


def test_no_percentage_is_rendered():
    html = render([_map()])
    assert not re.search(r"\d+%", html)


# ── Rule 2: band never without its reason ─────────────────────────────────────

def test_band_and_reason_both_appear():
    html = render([_map()])
    assert "STRONG FIT" in html
    assert "matches dbt and airflow from your resume" in html


# ── Rule 3: low confidence is its own state ───────────────────────────────────

def _body(html: str) -> str:
    """Rendered markup only — the drawer script names bands as constants."""
    return html.split("<script>")[0]


def test_unchecked_listing_shows_no_band_pill():
    body = _body(render([_map(roles=[_UNCHECKED])]))
    assert "STRETCH" not in body
    assert "PARTIAL FIT" not in body
    assert 'class="pill' not in body


def test_unchecked_listing_shows_the_not_checked_block():
    html = render([_map(roles=[_UNCHECKED])])
    assert "Not checked yet" in html
    assert "FETCH POSTING" in html


def test_not_checked_sentence_starts_capitalised():
    """It follows 'Not checked yet.' so it must read as a new sentence."""
    html = render([_map(roles=[_UNCHECKED])])
    assert "This listing arrived without a description" in html


# ── Rule 4: company owns the card ─────────────────────────────────────────────

def test_company_name_precedes_role_title():
    html = render([_map()])
    assert html.index("Acme Analytics") < html.index("Senior Analytics Engineer")


def test_company_why_is_rendered():
    html = render([_map(why="2 roles match your target titles")])
    assert "2 roles match your target titles" in html


# ── Rule 5: watch entries are a separate shelf ────────────────────────────────

def test_watch_company_appears_in_the_shelf():
    html = render([_map(name="Initech", state="WATCH", roles=[],
                        why="no role open")])
    assert "keeping an eye on" in html
    assert "Initech" in html


def test_watch_company_has_no_review_action():
    html = render([_map(name="Initech", state="WATCH", roles=[], why="x")])
    assert "REVIEW ROLE" not in html


# ── Structure ─────────────────────────────────────────────────────────────────

def test_first_map_is_the_lead_card():
    html = render([_map(name="First Co"), _map(name="Second Co")])
    assert html.index("First Co") < html.index("Second Co")


def test_quiet_day_header_when_nothing_is_act_now():
    html = render([_map(state="DISCOVER")])
    assert "nothing to apply to today" in html


def test_no_quiet_day_header_when_something_is_act_now():
    html = render([_map(state="ACT_NOW")])
    assert "nothing to apply to today" not in html


def test_role_url_is_linked():
    assert "https://example.com/job/1" in render([_map()])


def test_output_is_a_full_document():
    html = render([_map()])
    assert html.lstrip().startswith("<!DOCTYPE html>")
    assert "</html>" in html.rstrip()


def test_empty_input_still_renders():
    html = render([])
    assert "<!DOCTYPE html>" in html


# ── Escaping ──────────────────────────────────────────────────────────────────

def test_company_names_are_escaped():
    html = render([_map(name="<script>alert(1)</script>")])
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


# ── Sections ──────────────────────────────────────────────────────────────────

def test_earlier_section_gets_a_heading():
    new = _map(name="Fresh Co")
    new["section"] = "new"
    old = _map(name="Older Co")
    old["section"] = "earlier"
    body = _body(render([new, old]))
    assert "still here from earlier" in body
    assert body.index("Fresh Co") < body.index("still here from earlier")
    assert body.index("still here from earlier") < body.index("Older Co")


def test_no_earlier_heading_when_nothing_is_earlier():
    m = _map()
    m["section"] = "new"
    assert "still here from earlier" not in render([m])


def test_maps_without_a_section_are_treated_as_new():
    """Keeps the in-memory render path working before the store exists."""
    body = _body(render([_map()]))
    assert "Acme Analytics" in body
    assert "still here from earlier" not in body


# ── Wiring to the store ───────────────────────────────────────────────────────

def test_buttons_carry_their_role_and_company_ids():
    m = _map()
    m["id"] = 7
    m["roles"][0]["id"] = 42
    html = render([m])
    assert 'data-role="42"' in html
    assert 'data-company="7"' in html


def test_save_and_hide_actions_are_present():
    m = _map()
    m["id"] = 7
    m["roles"][0]["id"] = 42
    body = _body(render([m]))
    assert 'data-status="SAVED"' in body
    assert 'data-status="HIDDEN"' in body


def test_watch_posts_a_company_state():
    m = _map()
    m["id"] = 7
    m["roles"][0]["id"] = 42
    assert 'data-state="WATCH"' in _body(render([m]))


def test_missing_ids_do_not_break_rendering():
    """Rendering from an in-memory run, before the store exists, still works."""
    html = render([_map()])
    assert "Acme Analytics" in html


def test_zero_is_a_valid_id_not_a_missing_one():
    """0 or "" in Python treats 0 as falsy — a real trap for an id field."""
    m = _map()
    m["id"] = 0
    m["roles"][0]["id"] = 0
    html = render([m])
    assert 'data-role="0"' in html
    assert 'data-company="0"' in html
