"""The sticky app shell — one top navigation shared by every page.

From the design handoff (`design/wireframes/design_handoff_opportunity_map/`):
a 14px solid hatched strip reads as the top edge of the page, then the
wordmark and the MAP · TRACKER · PROFILE tab set over a hairline rule.
Tabs are plain links, so switching pages closes any open drawer by
construction. Counts are optional; a None renders nothing rather than a 0
that would have to be explained.
"""
from html import escape

_PAGES = [("/", "MAP"), ("/activity", "TRACKER"), ("/profile", "PROFILE")]

SHELL_CSS = """
.sh-nav{position:sticky;top:0;z-index:40;background:#F7F2E6}
.sh-strip{height:14px;background-image:repeating-linear-gradient(112deg,rgba(59,126,168,.3) 0 1px,transparent 1px 7px)}
.sh-row{display:flex;justify-content:center;border-bottom:1px solid #DED5C1}
.sh-in{width:100%;max-width:1180px;display:flex;align-items:center;justify-content:space-between;gap:28px;padding:12px 40px 11px}
.sh-brand{display:flex;align-items:baseline;gap:12px}
.sh-mark{font:600 27px/1 Caveat,cursive;color:#D6482B}
.sh-user{font:400 10px/1 'JetBrains Mono',monospace;color:#9AA3AE;letter-spacing:.12em}
.sh-tabs{display:flex;align-items:center;gap:4px}
.sh-tab{display:flex;align-items:center;gap:7px;padding:8px 13px 7px;border:1px solid transparent;border-bottom:2px solid transparent;background:transparent;border-radius:2px;color:#6E7787;font:500 11.5px/1 'JetBrains Mono',monospace;letter-spacing:.11em;white-space:nowrap;text-decoration:none}
.sh-tab:hover{color:#3A4557}
.sh-tab.sh-on{color:#D6482B;background:#FFFDF8;border-bottom-color:#D6482B}
.sh-tab.sh-on:hover{color:#D6482B}
.sh-count{font:400 10px/1 'JetBrains Mono',monospace;color:#A6AEB9;letter-spacing:.08em}
"""


def _e(value) -> str:
    return escape(str(value or ""), quote=True)


def shell_nav(active: str, counts: dict | None = None,
              user_label: str = "") -> str:
    """The sticky nav. `active` is the current path; `counts` maps a path
    to the number shown inside its tab ({"/": 14, "/activity": 5})."""
    counts = counts or {}
    tabs = []
    for href, label in _PAGES:
        n = counts.get(href)
        count = (f'<span class="sh-count">{int(n)}</span>'
                 if n is not None else "")
        if href == active:
            tabs.append(f'<span class="sh-tab sh-on" aria-current="page">'
                        f'{label}{count}</span>')
        else:
            tabs.append(f'<a class="sh-tab" href="{href}">{label}{count}</a>')

    # "default" is the single-user placeholder, not a person's name — the
    # shell shows an identity only when there is one to show.
    user = ""
    if user_label and user_label.lower() != "default":
        user = f'<span class="sh-user">{_e(user_label.upper())}</span>'

    return (
        '<div class="sh-nav">'
        '<div class="sh-strip"></div>'
        '<div class="sh-row"><div class="sh-in">'
        f'<div class="sh-brand"><span class="sh-mark">opportunity map</span>'
        f'{user}</div>'
        f'<div class="sh-tabs">{"".join(tabs)}</div>'
        '</div></div></div>'
    )
