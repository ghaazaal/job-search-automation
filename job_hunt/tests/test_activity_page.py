"""Tests for src/activity_page.py — the kanban activity board."""
import re

from src.activity_page import render

_STATUSES = ["SAVED", "APPLIED", "INTERVIEWING", "OFFER", "REJECTED", "CLOSED"]


def _card(title="Analytics Engineer", company="Acme", status="SAVED",
          band="STRONG FIT", reason="matches dbt and Snowflake",
          description_captured=True, url="https://example.com/1"):
    return {"role_id": 1, "title": title, "company": company,
            "location": "Remote", "url": url,
            "status": status, "updated_at": "2026-08-10T09:00:00",
            "band": band, "reason": reason,
            "description_captured": description_captured,
            "events": [{"from_status": "NEW", "to_status": "SAVED",
                        "at": "2026-08-10T09:00:00"}]}


def _board(**kw):
    base = {s: [] for s in _STATUSES}
    return {**base, **kw}


def test_all_six_columns_render_even_when_empty():
    html = render(_board()).lower()
    for label in ("saved", "applied", "interviewing", "offer",
                  "rejected", "closed"):
        assert label in html


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


def test_urls_cannot_break_out_of_attributes():
    evil = 'https://x/1" onmouseover="alert(1)'
    html = render(_board(SAVED=[_card(url=evil)]))
    assert '" onmouseover="' not in html
    assert "&quot;" in html


def test_dark_design_tokens_are_used():
    html = render(_board())
    assert "#0A0E1A" in html
    assert "#0D1117" in html
    assert "#1E2A3A" in html
    assert "#00D4FF" in html
    # The retired paper palette must be gone.
    assert "#F7F2E6" not in html
    assert "Caveat" not in html


def test_band_pill_rendered_with_reason():
    html = render(_board(SAVED=[_card()]))
    assert "strong fit" in html.lower()
    assert "matches dbt and Snowflake" in html


def test_no_pill_without_a_band():
    html = render(_board(SAVED=[_card(band=None)]))
    assert 'class="pill' not in html


def test_no_pill_without_a_reason():
    """A band pill without its reason sentence is a bug."""
    html = render(_board(SAVED=[_card(reason=None)]))
    assert 'class="pill' not in html


def test_reduced_confidence_when_no_description_captured():
    html = render(_board(SAVED=[_card(description_captured=False)]))
    assert 'class="pill pill-dim"' in html


def test_full_confidence_pill_when_description_captured():
    html = render(_board(SAVED=[_card()]))
    assert 'class="pill pill-dim"' not in html


def test_cards_carry_role_id_and_are_draggable():
    html = render(_board(SAVED=[_card()]))
    assert 'data-role-id="1"' in html
    assert 'draggable="true"' in html


def test_move_control_lists_all_six_statuses():
    html = render(_board(SAVED=[_card()]))
    for status in _STATUSES:
        assert f'value="{status}"' in html


def test_status_updates_post_to_the_existing_endpoint():
    html = render(_board(SAVED=[_card()]))
    assert "/api/roles/" in html
    assert "fetch(" in html


def test_back_link_to_map_and_inflight_count():
    html = render(_board(SAVED=[_card()], REJECTED=[_card(status="REJECTED")]))
    assert 'href="/"' in html


def test_board_has_navigation_to_the_other_pages():
    html = render(_board())
    assert 'href="/"' in html
    assert 'href="/profile"' in html
    assert 'aria-current="page"' in html
    assert ">TRACKER<" in html


def test_reduced_motion_is_honored():
    html = render(_board())
    assert "prefers-reduced-motion" in html


def test_cards_are_square_structural_containers():
    """DESIGN.md Layout: no rounding on structural containers. 4px is for
    buttons/inputs/small controls only — the .move select keeps it."""
    html = render(_board())
    card_rule = re.search(r"\.card\{[^}]*\}", html).group(0)
    assert "border-radius" not in card_rule


def test_hover_state_uses_only_palette_colors():
    """#2A3A4E appears nowhere in DESIGN.md; hover affordances come from
    tokens (here --bg-row-sel)."""
    html = render(_board())
    assert "#2A3A4E" not in html
    assert "#0F1F35" in html


def test_failed_move_reverts_to_original_position():
    """The revert must restore the card where it was, not append it to the
    bottom of its origin column — oldest-first survives a failed POST."""
    html = render(_board(SAVED=[_card()]))
    js = html.split("<script>")[1]
    assert "nextElementSibling" in js
    assert "insertBefore" in js


def test_drop_highlight_survives_child_hover_and_ignores_foreign_drags():
    """dragleave fires for every child element crossed, and dragover fires
    for any drag (selected text, a link). A depth counter keeps the
    highlight steady, and a .card.dragging guard keeps foreign drags from
    highlighting or dropping."""
    html = render(_board())
    js = html.split("<script>")[1]
    assert "dragenter" in js
    assert "_dragDepth" in js
    # The guard must gate dragenter/dragover AND the drop itself.
    assert js.count(".card.dragging") >= 3


def test_header_live_count_is_wired_for_js_refresh():
    """The in-flight number must not drift after a drag: the header count
    carries an id and the live columns a data-live mark so refreshCounts
    can recompute both."""
    html = render(_board(SAVED=[_card()], REJECTED=[_card(status="REJECTED")]))
    assert 'id="live-count">1<' in html
    for status in ("SAVED", "APPLIED", "INTERVIEWING", "OFFER"):
        assert f'data-status="{status}" data-live="1"' in html
    for status in ("REJECTED", "CLOSED"):
        assert f'data-status="{status}" data-live' not in html
    assert "live-count" in html.split("<script>")[1]
