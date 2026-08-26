"""Tests for the progress screen's markup."""
import re

from src.searching_page import render


def _visible(html: str) -> str:
    html = re.sub(r"<style.*?</style>", "", html, flags=re.S)
    html = re.sub(r"<script.*?</script>", "", html, flags=re.S)
    return re.sub(r"<[^>]+>", " ", html)


def test_the_run_id_is_embedded_for_polling():
    assert "42" in render(42)


def test_it_polls_the_run_endpoint():
    assert "/api/runs/42" in render(42)


def test_it_polls_every_two_seconds():
    assert "2000" in render(42)


def test_it_sends_the_reader_to_the_map_when_the_run_is_ok():
    html = render(42)
    assert "OK" in html and "'/'" in html


def test_a_failed_run_offers_a_retry():
    assert "retry" in render(42).lower()


def test_it_warns_when_progress_stops_changing():
    """A worker killed with the tab open would otherwise spin forever."""
    assert "may have stopped" in render(42).lower()


def test_no_score_or_percentage_appears():
    html = render(42)
    assert "match_score" not in html
    assert "%" not in _visible(html)


def test_the_page_uses_the_project_palette():
    assert "#F7F2E6" in render(42)


def test_dropped_jobs_are_surfaced_in_the_progress_note():
    """Drops are the one silent policy exception — the progress screen
    still has to say so, not just the final map."""
    html = render(42)
    assert "progress.dropped" in html
    assert "hidden" in html.lower()


def test_the_step_row_can_label_the_local_lane():
    """The page appends ' · <lane>' from the step's lane field — the
    source name itself stays clean for the scraper lookup. Labeling now
    covers any non-worldwide lane (local, probe hybrid, probe onsite),
    not just 'local' specifically."""
    html = render(7)
    assert "s.lane !== 'worldwide'" in html


def test_any_non_worldwide_lane_is_labeled():
    html = render(9)
    assert "s.lane !== 'worldwide'" in html
