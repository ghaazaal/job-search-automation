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
