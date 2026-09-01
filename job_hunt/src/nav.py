"""Cross-page navigation links.

One helper so the three screens agree on what exists and what it is
called. It returns inner HTML only — each page wraps and styles it in
its own palette, so this module knows nothing about CSS.
"""

_PAGES = [("/", "MAP"), ("/activity", "TRACKER"), ("/profile", "PROFILE")]


def nav_links(current: str) -> str:
    """Links to every page, with the current one marked, not linked."""
    parts = [
        (f'<span class="nav-here" aria-current="page">{label}</span>'
         if href == current else f'<a href="{href}">{label}</a>')
        for href, label in _PAGES
    ]
    return " &middot; ".join(parts)
