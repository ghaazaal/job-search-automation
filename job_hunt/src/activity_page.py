"""Renders the activity screen.

Reuses the paper palette from the handoff. Four live columns plus a closed
section, oldest first within each column so the thing waiting longest is on top.
"""
from datetime import date, datetime
from html import escape

_COLUMNS = [("SAVED", "saved"), ("APPLIED", "applied"),
            ("INTERVIEWING", "interviewing"), ("OFFER", "offer")]

_CSS = """
*{box-sizing:border-box}
html,body{margin:0;background:#F7F2E6}
body{font-family:Inter,system-ui,sans-serif;color:#2A3342;-webkit-font-smoothing:antialiased}
a{color:#D6482B;text-decoration:none}
.page{min-height:100vh;background-image:radial-gradient(rgba(42,51,66,.14) 1px,transparent 1px);background-size:22px 22px;background-position:11px 11px;padding:0 0 80px}
.hatch{height:26px;background-image:repeating-linear-gradient(112deg,rgba(59,126,168,.28) 0 1px,transparent 1px 7px);mask-image:linear-gradient(to bottom,#000,transparent);-webkit-mask-image:linear-gradient(to bottom,#000,transparent)}
.head{display:flex;justify-content:center;padding:30px 40px 30px}
.head-in{flex:1;max-width:1180px;display:flex;align-items:flex-end;justify-content:space-between;gap:32px}
.title{font:600 46px/1 Caveat,cursive;color:#D6482B}
.sub{font:400 15px/1.6 Inter,sans-serif;color:#4C5768;margin-top:10px;max-width:46ch}
.nav{font:500 11px/1 'JetBrains Mono',monospace;color:#6E7787;letter-spacing:.1em}
.wrap{display:flex;justify-content:center;padding:0 40px}
.cols{flex:1;max-width:1180px;display:grid;grid-template-columns:repeat(4,1fr);gap:14px}
.colhead{display:flex;align-items:baseline;gap:8px;padding-bottom:10px;border-bottom:1px solid #E0D8C4}
.colname{font:600 22px/1.2 Caveat,cursive;color:#2E7D5B}
.colcount{margin-left:auto;font:500 10.5px/1 'JetBrains Mono',monospace;color:#8A93A1;letter-spacing:.1em}
.stack{display:flex;flex-direction:column;gap:10px;margin-top:14px}
.card{background:#FFFDF8;border:1px solid #E0D8C4;border-radius:4px;padding:13px 15px}
.co{font:500 10.5px/1 'JetBrains Mono',monospace;color:#8A93A1;letter-spacing:.1em;text-transform:uppercase}
.rt{font:500 15px/1.3 Inter,sans-serif;color:#1F2937;margin-top:6px}
.loc{font:400 11.5px/1 'JetBrains Mono',monospace;color:#6E7787;margin-top:6px}
.log{margin-top:10px;padding-top:9px;border-top:1px solid #EBE3D2}
.ev{font:400 11.5px/1.6 'JetBrains Mono',monospace;color:#8A93A1}
.empty{font:400 13px/1.6 Inter,sans-serif;color:#8A93A1;margin-top:14px}
.closed{max-width:1180px;margin:34px auto 0;padding:0 40px}
.closed-h{font:600 22px/1.2 Caveat,cursive;color:#6E7787;padding-bottom:10px;border-bottom:1px solid #E0D8C4}
.closed-l{font:400 13px/1.9 Inter,sans-serif;color:#8A93A1;margin-top:12px}
"""


def _e(value) -> str:
    return escape(str(value or ""), quote=True)


def _days(iso: str) -> str:
    try:
        then = datetime.fromisoformat(str(iso).replace("Z", "")).date()
        n = max(0, (date.today() - then).days)
        return "today" if n == 0 else f"{n}d"
    except (ValueError, TypeError):
        return ""


def _card(card: dict) -> str:
    events = "".join(
        f'<div class="ev">{_e(str(e["at"])[:10])} &middot; '
        f'{_e((e["to_status"] or "").lower())}</div>'
        for e in card.get("events") or []
    )
    log = f'<div class="log">{events}</div>' if events else ""
    return (
        f'<div class="card"><div class="co">{_e(card["company"])}</div>'
        f'<div class="rt"><a href="{_e(card["url"])}" target="_blank" '
        f'rel="noopener">{_e(card["title"])}</a></div>'
        f'<div class="loc">{_e(card.get("location"))} &middot; '
        f'{_e(_days(card.get("updated_at")))} in this state</div>{log}</div>'
    )


def _column(key: str, label: str, cards: list[dict]) -> str:
    body = ("".join(_card(c) for c in cards) if cards
            else '<div class="empty">nothing here yet</div>')
    return (
        f'<div><div class="colhead"><div class="colname">{label}</div>'
        f'<div class="colcount">{len(cards)}</div></div>'
        f'<div class="stack">{body}</div></div>'
    )


def render(board: dict) -> str:
    """Render the activity board. `board` comes from queries.activity_board."""
    columns = "".join(_column(key, label, board.get(key) or [])
                      for key, label in _COLUMNS)
    closed = board.get("CLOSED") or []
    closed_html = ""
    if closed:
        items = "".join(
            f'<div class="closed-l">{_e(c["company"])} &middot; {_e(c["title"])} '
            f'&middot; {_e(c["status"].lower())}</div>' for c in closed)
        closed_html = (f'<div class="closed"><div class="closed-h">closed</div>'
                       f'{items}</div>')
    live = sum(len(board.get(k) or []) for k, _ in _COLUMNS)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Activity</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Caveat:wght@500;600&family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">
<style>{_CSS}</style>
</head>
<body>
<div class="page">
<div class="hatch"></div>
<div class="head"><div class="head-in">
<div>
<div class="title">in flight</div>
<div class="sub">{live} things you have moved on. Oldest at the top of each column.</div>
</div>
<div class="nav"><a href="/">&larr; BACK TO MAP</a></div>
</div></div>
<div class="wrap"><div class="cols">{columns}</div></div>
{closed_html}
</div>
</body>
</html>
"""
