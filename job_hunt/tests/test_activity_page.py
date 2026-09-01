"""Tests for src/activity_page.py — the kanban activity board.

The paper surface from the design handoff. The board renders the store's
six statuses (the design draws five; REJECTED would otherwise hide real
cards), moves cards with clamped arrows or drag-and-drop, and opens the
shared role drawer from each card's ROLE button.
"""
import re

from src.activity_page import render

_STATUSES = ["SAVED", "APPLIED", "INTERVIEWING", "OFFER", "REJECTED", "CLOSED"]


def _card(title="Analytics Engineer", company="Acme", status="SAVED",
          band="STRONG FIT", reason="matches dbt and Snowflake",
          description_captured=True, url="https://example.com/1",
          role_id=1):
    return {"role_id": role_id, "title": title, "company": company,
            "company_id": 11, "location": "Remote", "url": url,
            "status": status, "applied_at": None,
            "updated_at": "2026-08-10T09:00:00",
            "band": band, "reason": reason,
            "description_captured": description_captured,
            "matched": ["dbt", "Snowflake"], "gaps": ["Kafka"],
            "work_mode": "remote", "salary": None, "date": "2026-08-05",
            "events": [{"from_status": "NEW", "to_status": "SAVED",
                        "at": "2026-08-10T09:00:00"}]}


def _board(**kw):
    base = {s: [] for s in _STATUSES}
    return {**base, **kw}


def _visible(html: str) -> str:
    """The document with its CSS and JS stripped — what a reader actually
    sees. A `%` in a stylesheet is not a percentage on the screen."""
    return re.sub(r"<(style|script)\b.*?</\1>", "", html, flags=re.DOTALL)


def _board_js(html: str) -> str:
    """The board's own script block (the drawer's comes first)."""
    return html.split("<script>")[-1]


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
    html = render(_board(SAVED=[_card(), _card(title="Data Engineer",
                                               role_id=2)]))
    assert 'class="colcount">2<' in html


def test_card_meta_is_derived_from_stored_timestamps():
    html = render(_board(SAVED=[_card()]))
    assert re.search(r"SAVED (TODAY|\d+d AGO)", html)


def test_no_numeric_score_is_rendered():
    html = _visible(render(_board(SAVED=[_card()])))
    assert "match_score" not in html
    assert not re.search(r"\d+%", html)


def test_output_is_a_full_document():
    html = render(_board())
    assert html.lstrip().startswith("<!DOCTYPE html>")


def test_titles_are_escaped():
    html = render(_board(SAVED=[_card(title="<script>alert(1)</script>")]))
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_urls_cannot_break_out_of_markup():
    evil = 'https://x/1" onmouseover="alert(1)'
    html = render(_board(SAVED=[_card(url=evil)]))
    assert '" onmouseover="' not in html


def test_paper_design_tokens_are_used():
    """The handoff supersedes the dark build: paper surface, Caveat
    headings, vermilion accents — and no dark tokens left behind."""
    html = render(_board())
    assert "#F7F2E6" in html
    assert "#FFFDF8" in html
    assert "Caveat" in html
    assert "#D6482B" in html
    assert "#0A0E1A" not in html
    assert "#0D1117" not in html


def test_rejected_and_closed_columns_read_as_finished():
    html = render(_board())
    assert html.count('class="col sunk"') == 2


def test_band_pill_on_the_card():
    html = render(_board(SAVED=[_card()]))
    assert "STRONG FIT" in html


def test_the_reason_reaches_the_drawer_payload():
    """The card shows the band alone; the sentence is one click away in
    the shared drawer, so it must be in the payload."""
    html = render(_board(SAVED=[_card()]))
    assert "matches dbt and Snowflake" in html


def test_no_pill_without_a_band():
    html = render(_board(SAVED=[_card(band=None)]))
    assert 'class="tpill' not in html


def test_no_pill_without_a_reason():
    """A band pill whose reason sentence exists nowhere on the surface is
    a bug — no reason stored, no pill shown."""
    html = render(_board(SAVED=[_card(reason=None)]))
    assert 'class="tpill' not in html


def test_no_pill_when_no_description_captured():
    """Nothing was checked, so nothing may imply a verified match."""
    html = render(_board(SAVED=[_card(description_captured=False)]))
    assert 'class="tpill' not in html


def test_band_colors_the_card_accent():
    html = render(_board(SAVED=[_card()]))
    assert "accent-strong" in html


def test_cards_carry_role_id_and_are_draggable():
    html = render(_board(SAVED=[_card()]))
    assert 'data-role-id="1"' in html
    assert 'draggable="true"' in html


def test_cards_move_with_clamped_arrows():
    html = render(_board(SAVED=[_card()]))
    assert "step-back" in html
    assert "step-fwd" in html
    js = _board_js(html)
    # The ladder is clamped at both ends — no wrap.
    assert "i < 0 || i >= LADDER.length" in js


def test_the_arrow_ladder_covers_all_six_statuses():
    js = _board_js(render(_board(SAVED=[_card()])))
    for status in _STATUSES:
        assert status in js


def test_status_updates_post_to_the_existing_endpoint():
    html = render(_board(SAVED=[_card()]))
    assert "/api/roles/" in html
    assert "fetch(" in html


def test_role_button_opens_the_shared_drawer():
    html = render(_board(SAVED=[_card()]))
    assert 'data-drawer-key="r1"' in html
    assert 'id="dw"' in html
    assert "window.Drawer.open" in html


def test_the_drawer_payload_carries_the_evidence():
    html = render(_board(SAVED=[_card()]))
    assert '"matched"' in html
    assert '"gaps"' in html
    assert '"rid": 1' in html or '"rid":1' in html


def test_board_has_navigation_to_the_other_pages():
    html = render(_board())
    assert 'href="/"' in html
    assert 'href="/profile"' in html
    assert 'aria-current="page"' in html
    assert ">TRACKER<" in html


def test_empty_columns_say_so():
    html = render(_board())
    assert "nothing here yet" in html


def test_reduced_motion_is_honored():
    html = render(_board())
    assert "prefers-reduced-motion" in html


def test_the_board_scrolls_inside_its_own_container():
    """Load-bearing: without the scroller the six intrinsic tracks drag
    the whole page (including the sticky nav) sideways."""
    html = render(_board())
    assert "overflow-x:auto" in html
    assert "overscroll-behavior-x:contain" in html


def test_failed_move_reverts_to_original_position():
    """The revert must restore the card where it was, not append it to the
    bottom of its origin column — oldest-first survives a failed POST."""
    js = _board_js(render(_board(SAVED=[_card()])))
    assert "nextElementSibling" in js
    assert "insertBefore" in js


def test_drop_highlight_survives_child_hover_and_ignores_foreign_drags():
    """dragleave fires for every child element crossed, and dragover fires
    for any drag (selected text, a link). A depth counter keeps the
    highlight steady, and a .card.dragging guard keeps foreign drags from
    highlighting or dropping."""
    js = _board_js(render(_board()))
    assert "dragenter" in js
    assert "_dragDepth" in js
    # The guard must gate dragenter/dragover AND the drop itself.
    assert js.count(".card.dragging") >= 3


def test_header_live_count_is_wired_for_js_refresh():
    """The in-flight number must not drift after a move: the header count
    and the shell badge both carry hooks refreshCounts can find."""
    html = render(_board(SAVED=[_card()],
                         REJECTED=[_card(status="REJECTED", role_id=2)]))
    assert 'id="live-count">1<' in html
    js = _board_js(html)
    assert "live-count" in js
    assert ".sh-on .sh-count" in js


def test_the_subtitle_counts_only_live_items():
    html = render(_board(SAVED=[_card()],
                         CLOSED=[_card(status="CLOSED", role_id=2)]))
    assert "One thing is moving." in html


def test_last_move_is_derived_not_invented():
    with_cards = render(_board(SAVED=[_card()]))
    assert "LAST MOVE" in with_cards
    empty = render(_board())
    assert "LAST MOVE" not in empty
