"""Tests for src/activity_page.py."""
import re

from src.activity_page import render


def _card(title="Analytics Engineer", company="Acme", status="SAVED"):
    return {"role_id": 1, "title": title, "company": company,
            "location": "Remote", "url": "https://example.com/1",
            "status": status, "updated_at": "2026-08-10T09:00:00",
            "events": [{"from_status": "NEW", "to_status": "SAVED",
                        "at": "2026-08-10T09:00:00"}]}


def _board(**kw):
    base = {"SAVED": [], "APPLIED": [], "INTERVIEWING": [], "OFFER": [],
            "CLOSED": []}
    return {**base, **kw}


def test_all_columns_render_even_when_empty():
    html = render(_board())
    for label in ("saved", "applied", "interviewing", "offer"):
        assert label in html.lower()


def test_cards_appear_in_their_column():
    html = render(_board(APPLIED=[_card(status="APPLIED")]))
    assert "Analytics Engineer" in html
    assert "Acme" in html


def test_column_counts_are_shown():
    html = render(_board(SAVED=[_card(), _card(title="Data Engineer")]))
    assert "2" in html


def test_event_log_is_rendered():
    html = render(_board(SAVED=[_card()]))
    assert "2026-08-10" in html


def test_no_numeric_score_is_rendered():
    html = render(_board(SAVED=[_card()]))
    assert "match_score" not in html
    assert not re.search(r"\d+%", html)


def test_output_is_a_full_document():
    html = render(_board())
    assert html.lstrip().startswith("<!DOCTYPE html>")


def test_titles_are_escaped():
    html = render(_board(SAVED=[_card(title="<script>alert(1)</script>")]))
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html
