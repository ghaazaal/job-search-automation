"""Renders the activity screen as a kanban board.

The paper surface from the design handoff (`design/wireframes/
design_handoff_opportunity_map/`, tracker screen) — deliberately not a
dark "tool" theme; the handoff supersedes the earlier dark build. One
column per application status, oldest first within each column so the
thing waiting longest is on top.

The store has six statuses, not the design's five: REJECTED sits between
OFFER and CLOSED and is styled like CLOSED (sunk, finished) — dropping
the column would hide real cards. Cards move one stage with their ←/→
arrows (clamped, no wrap) or by drag-and-drop across columns; both POST
to the existing /api/roles/<id>/status endpoint. ROLE opens the shared
role drawer over the board.
"""
import json
from datetime import date, datetime
from html import escape

from .drawer import DRAWER_CSS, DRAWER_MOUNT, drawer_js
from .shell import SHELL_CSS, shell_nav

_COLUMNS = [("SAVED", "saved"), ("APPLIED", "applied"),
            ("INTERVIEWING", "interviewing"), ("OFFER", "offer"),
            ("REJECTED", "rejected"), ("CLOSED", "closed")]

# The arrow ladder. REJECTED and CLOSED are both outcomes; the ladder
# only decides what one click of → or ← means, clamped at both ends.
_LADDER = [key for key, _ in _COLUMNS]

# The four states that count as "in flight" in the header and the shell
# badge. Rejected and closed are outcomes, not motion.
_LIVE = ("SAVED", "APPLIED", "INTERVIEWING", "OFFER")

# Columns that read as finished: visibly sunk, muted label.
_SUNK = ("REJECTED", "CLOSED")

_BAND = {"STRONG FIT": ("accent-strong", "tpill-strong"),
         "PARTIAL FIT": ("accent-partial", "tpill-partial"),
         "STRETCH": ("accent-stretch", "tpill-stretch")}

_CSS = """
*{box-sizing:border-box}
html,body{margin:0;background:#F7F2E6}
body{font-family:Inter,system-ui,sans-serif;color:#2A3342;-webkit-font-smoothing:antialiased}
a{color:#D6482B;text-decoration:none}
a:hover{color:#A83519}
::selection{background:rgba(46,125,91,.18)}
.page{min-height:100vh;background:#F7F2E6;background-image:radial-gradient(rgba(42,51,66,.14) 1px,transparent 1px);background-size:22px 22px;background-position:11px 11px;padding:0 0 90px}
.head{display:flex;justify-content:center;padding:30px 40px 26px}
.head-in{flex:1;max-width:1180px;display:flex;align-items:flex-end;justify-content:space-between;gap:32px}
.title{font:600 42px/1 Caveat,cursive;color:#D6482B}
.sub{font:400 15px/1.6 Inter,sans-serif;color:#4C5768;margin-top:9px;max-width:52ch;text-wrap:pretty}
.meta-r{flex:none;text-align:right;padding-bottom:4px}
.meta-1{font:500 11px/1 'JetBrains Mono',monospace;color:#4C5768;letter-spacing:.1em}
.meta-2{font:400 11px/1 'JetBrains Mono',monospace;color:#8A93A1;letter-spacing:.1em;margin-top:9px}
.wrap{display:flex;justify-content:center;padding:0 40px}
.scroller{width:100%;max-width:1180px;min-width:0;overflow-x:auto;overscroll-behavior-x:contain;padding-bottom:10px}
.board{display:grid;grid-template-columns:repeat(6,minmax(176px,1fr));gap:14px;align-items:start}
.col{background:#FBF7EC;border:1px solid #E0D8C4;border-radius:4px;padding:14px 13px 16px;min-height:230px}
.col.sunk{background:#F4EFE1}
.col.drop-target{border-color:#2E7D5B}
.colhead{display:flex;align-items:baseline;justify-content:space-between;gap:8px;padding-bottom:9px;border-bottom:1px solid #CBBFA5}
.sunk .colhead{border-bottom-color:#DED5C1}
.colname{font:500 10.5px/1 'JetBrains Mono',monospace;letter-spacing:.11em;color:#3A4557;text-transform:uppercase}
.sunk .colname{color:#8A93A1}
.colcount{font:400 10.5px/1 'JetBrains Mono',monospace;color:#A6AEB9}
.stack{display:flex;flex-direction:column;gap:11px;margin-top:12px;min-height:24px}
.card{background:#FFFDF8;border:1px solid #E0D8C4;border-left:3px solid #E0D8C4;border-radius:3px;padding:12px 13px 11px;cursor:grab}
.card:hover{border-color:#CBBFA5}
.card.dragging{opacity:.5}
.accent-strong{border-left-color:#2E7D5B}
.accent-partial{border-left-color:#2A5F86}
.accent-stretch{border-left-color:#B9C4D0}
.co{font:400 9.5px/1.3 'JetBrains Mono',monospace;color:#8A93A1;letter-spacing:.11em;text-transform:uppercase}
.rt{font:500 15px/1.35 Inter,sans-serif;color:#1F2937;margin-top:6px;text-wrap:pretty}
.tpill{display:inline-block;font:700 9px/1.2 'JetBrains Mono',monospace;letter-spacing:.1em;padding:3px 8px;border-radius:2px;margin-top:9px}
.tpill-strong{background:#2E7D5B;border:1px solid #2E7D5B;color:#FFFDF8}
.tpill-partial{background:transparent;border:1px solid #2A5F86;color:#2A5F86}
.tpill-stretch{background:transparent;border:1px solid #B9C4D0;color:#6E7787}
.cmeta{font:400 10px/1.5 'JetBrains Mono',monospace;color:#9AA3AE;letter-spacing:.05em;margin-top:9px}
.cfoot{display:flex;align-items:center;gap:6px;margin-top:11px;padding-top:9px;border-top:1px solid #EFE8D8}
.step{width:26px;padding:5px 0;border:1px solid #E0D8C4;background:transparent;border-radius:2px;color:#8A93A1;font:400 11px/1 'JetBrains Mono',monospace;white-space:nowrap;cursor:pointer}
.step-back:hover{border-color:#CBBFA5;color:#3A4557}
.step-fwd:hover{border-color:#D6482B;color:#D6482B}
.role-btn{margin-left:auto;padding:5px 8px;border:1px solid transparent;background:transparent;border-radius:2px;color:#D6482B;font:500 10px/1 'JetBrains Mono',monospace;letter-spacing:.07em;white-space:nowrap;cursor:pointer}
.role-btn:hover{border-color:#D6482B}
.empty{border:1px dashed #D5CDB9;border-radius:3px;padding:14px 13px;font:400 13px/1.5 Inter,sans-serif;color:#A6AEB9}
.err{font:400 11px/1.5 'JetBrains Mono',monospace;color:#A83519;margin-top:8px}
@media (prefers-reduced-motion: reduce){
  *{transition:none !important;animation:none !important}
}
"""

_JS = """
(function () {
  'use strict';

  var LADDER = __LADDER__;
  var LIVE = __LIVE__;

  function post(roleId, status) {
    return fetch('/api/roles/' + encodeURIComponent(roleId) + '/status', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({status: status})
    });
  }

  function refreshCounts() {
    var live = 0;
    document.querySelectorAll('.col').forEach(function (col) {
      var n = col.querySelectorAll('.card').length;
      col.querySelector('.colcount').textContent = n;
      if (LIVE.indexOf(col.getAttribute('data-status')) !== -1) { live += n; }
    });
    var header = document.getElementById('live-count');
    if (header) { header.textContent = live; }
    var badge = document.querySelector('.sh-on .sh-count');
    if (badge) { badge.textContent = live; }
  }

  function flashError(card, message) {
    var note = document.createElement('div');
    note.className = 'err';
    note.textContent = message;
    card.appendChild(note);
    setTimeout(function () { note.remove(); }, 4000);
  }

  function fixPlaceholders() {
    // A stack a card just left shows the empty note again; a stack a
    // card just entered drops it.
    document.querySelectorAll('.stack').forEach(function (stack) {
      var cards = stack.querySelectorAll('.card').length;
      var note = stack.querySelector('.empty');
      if (cards && note) { note.remove(); }
      if (!cards && !note) {
        var div = document.createElement('div');
        div.className = 'empty';
        div.textContent = 'nothing here yet';
        stack.appendChild(div);
      }
    });
  }

  function moveCard(card, targetCol) {
    var fromStack = card.parentElement;
    // Captured before the move so a failed POST puts the card back where
    // it was — appending on revert would break oldest-first until reload.
    var anchor = card.nextElementSibling;
    var status = targetCol.getAttribute('data-status');
    if (fromStack === targetCol.querySelector('.stack')) { return; }
    targetCol.querySelector('.stack').appendChild(card);
    fixPlaceholders();
    refreshCounts();
    post(card.getAttribute('data-role-id'), status).then(function (r) {
      if (!r.ok) { throw new Error('HTTP ' + r.status); }
    }).catch(function () {
      fromStack.insertBefore(card, anchor);
      fixPlaceholders();
      refreshCounts();
      flashError(card, 'could not move — reverted');
    });
  }

  function step(card, dir) {
    var current = card.closest('.col').getAttribute('data-status');
    var i = LADDER.indexOf(current) + dir;
    // Clamped at both ends — no wrap.
    if (i < 0 || i >= LADDER.length) { return; }
    var col = document.querySelector('.col[data-status="' + LADDER[i] + '"]');
    if (col) { moveCard(card, col); }
  }

  document.addEventListener('click', function (e) {
    var back = e.target.closest('.step-back');
    if (back) { step(back.closest('.card'), -1); return; }
    var fwd = e.target.closest('.step-fwd');
    if (fwd) { step(fwd.closest('.card'), 1); return; }
    var role = e.target.closest('[data-drawer-key]');
    if (role) { window.Drawer.open(role.getAttribute('data-drawer-key'), 0); }
  });

  document.querySelectorAll('.card').forEach(function (card) {
    card.addEventListener('dragstart', function (e) {
      card.classList.add('dragging');
      e.dataTransfer.setData('text/plain', card.getAttribute('data-role-id'));
      e.dataTransfer.effectAllowed = 'move';
    });
    card.addEventListener('dragend', function () {
      card.classList.remove('dragging');
      // A cancelled drag can strand a highlight; clear them all.
      document.querySelectorAll('.col').forEach(function (col) {
        col._dragDepth = 0;
        col.classList.remove('drop-target');
      });
    });
  });

  document.querySelectorAll('.col').forEach(function (col) {
    // dragenter/dragleave fire again for every child element crossed, so
    // a bare add/remove flickers while the pointer moves over cards. The
    // depth counter nets them out; the .card.dragging guard keeps foreign
    // drags (selected text, links) from highlighting or dropping.
    col._dragDepth = 0;
    col.addEventListener('dragenter', function (e) {
      if (!document.querySelector('.card.dragging')) { return; }
      e.preventDefault();
      col._dragDepth += 1;
      col.classList.add('drop-target');
    });
    col.addEventListener('dragover', function (e) {
      if (!document.querySelector('.card.dragging')) { return; }
      e.preventDefault();
    });
    col.addEventListener('dragleave', function () {
      if (col._dragDepth > 0) { col._dragDepth -= 1; }
      if (col._dragDepth === 0) { col.classList.remove('drop-target'); }
    });
    col.addEventListener('drop', function (e) {
      col._dragDepth = 0;
      col.classList.remove('drop-target');
      var card = document.querySelector('.card.dragging');
      if (!card) { return; }
      e.preventDefault();
      moveCard(card, col);
    });
  });
})();
"""


def _e(value) -> str:
    return escape(str(value or ""), quote=True)


def _days(iso) -> str:
    try:
        then = datetime.fromisoformat(str(iso).replace("Z", "")).date()
        n = max(0, (date.today() - then).days)
        return "today" if n == 0 else f"{n}d"
    except (ValueError, TypeError):
        return ""


def _card_meta(card: dict) -> str:
    """e.g. `APPLIED 6d AGO · POSTED 12d`. Every clause is derived from a
    stored timestamp — nothing here is invented."""
    status = card.get("status") or ""
    stamp = (card.get("applied_at") if status == "APPLIED" else None) \
        or card.get("updated_at")
    age = _days(stamp)
    bits = []
    if age == "today":
        bits.append(f"{status} TODAY")
    elif age:
        bits.append(f"{status} {age} AGO")
    posted = _days(card.get("date"))
    if posted and posted != "today":
        bits.append(f"POSTED {posted}")
    return " · ".join(bits)


def _pill(card: dict) -> str:
    """The band pill alone — the reason sentence lives one click away in
    the drawer (the ROLE button), which is the handoff's own answer to
    rule 2 on this dense surface. It still only renders when the pair
    exists in the store, and never when no description was captured
    (rule 3 — nothing was checked, so nothing may imply it was)."""
    band, reason = card.get("band"), card.get("reason")
    if not band or not reason or not card.get("description_captured"):
        return ""
    _, pill_cls = _BAND.get(band, ("", "tpill-stretch"))
    return f'<div><span class="tpill {pill_cls}">{_e(band)}</span></div>'


def _accent(card: dict) -> str:
    band = card.get("band")
    if not band or not card.get("description_captured"):
        return ""
    accent, _ = _BAND.get(band, ("", ""))
    return f" {accent}" if accent else ""


def _card(card: dict) -> str:
    return (
        f'<div class="card{_accent(card)}" draggable="true" '
        f'data-role-id="{_e(card["role_id"])}">'
        f'<div class="co">{_e(card["company"])}</div>'
        f'<div class="rt">{_e(card["title"])}</div>'
        f'{_pill(card)}'
        f'<div class="cmeta">{_e(_card_meta(card))}</div>'
        f'<div class="cfoot">'
        f'<button type="button" class="step step-back" aria-label="Move back">'
        f'&larr;</button>'
        f'<button type="button" class="step step-fwd" aria-label="Move forward">'
        f'&rarr;</button>'
        f'<button type="button" class="role-btn" '
        f'data-drawer-key="r{_e(card["role_id"])}">ROLE</button>'
        f'</div></div>'
    )


def _column(key: str, label: str, cards: list[dict]) -> str:
    sunk = " sunk" if key in _SUNK else ""
    body = ("".join(_card(c) for c in cards) if cards
            else '<div class="empty">nothing here yet</div>')
    return (
        f'<div class="col{sunk}" data-status="{key}">'
        f'<div class="colhead"><span class="colname">{label}</span>'
        f'<span class="colcount">{len(cards)}</span></div>'
        f'<div class="stack">{body}</div></div>'
    )


def _role_meta(card: dict) -> str:
    bits = [card.get("work_mode") or "", card.get("location") or ""]
    posted = _days(card.get("date"))
    if posted:
        bits.append(f"POSTED {posted}")
    if card.get("salary"):
        bits.append(card["salary"])
    if not card.get("description_captured"):
        bits.append("NO DESCRIPTION CAPTURED")
    return " · ".join(b for b in bits if b).upper()


def _drawer_payload(board: dict) -> dict:
    """One drawer entry per tracked role. The board has no company-level
    evidence line, so the drawer's "why this company" section stays out
    rather than being invented."""
    out: dict = {}
    for cards in board.values():
        for c in cards:
            out[f"r{c['role_id']}"] = {
                "name": c["company"],
                "why": "",
                "roles": [{
                    "title": c.get("title") or "",
                    "tab": (c.get("title") or "")[:28],
                    "meta": _role_meta(c),
                    "band": c.get("band"),
                    "reason": c.get("reason") or "",
                    "matched": list(c.get("matched") or []),
                    "gaps": list(c.get("gaps") or []),
                    "captured": bool(c.get("description_captured")),
                    "url": c.get("url") or "",
                    "rid": c["role_id"],
                    "app_status": c.get("status"),
                }],
            }
    return out


def _last_move(board: dict) -> str:
    stamps = [c.get("updated_at") for cards in board.values() for c in cards
              if c.get("updated_at")]
    if not stamps:
        return ""
    age = _days(max(stamps))
    return "LAST MOVE TODAY" if age == "today" else f"LAST MOVE {age} AGO"


def _subtitle(live: int) -> str:
    if live == 0:
        return ("Nothing is moving yet. Save or apply to a role on the map "
                "and it lands here.")
    lead = ("One thing is moving." if live == 1
            else f"{live} things are moving.")
    return (f"{lead} Oldest sits at the top of each column — move a card "
            "with its arrows when something changes.")


def render(board: dict, nav: dict | None = None) -> str:
    """Render the activity board. `board` comes from queries.activity_board;
    `nav` carries the shell's MAP badge count (`map_count`) and the user
    label."""
    nav = nav or {}
    columns = "".join(_column(key, label, board.get(key) or [])
                      for key, label in _COLUMNS)
    live = sum(len(board.get(k) or []) for k in _LIVE)

    payload = json.dumps(_drawer_payload(board), ensure_ascii=False)
    payload = payload.replace("</", "<\\/")

    js = (_JS.replace("__LADDER__", json.dumps(_LADDER))
             .replace("__LIVE__", json.dumps(list(_LIVE))))

    top_nav = shell_nav("/activity",
                        counts={"/": nav.get("map_count"), "/activity": live},
                        user_label=nav.get("user_label") or "")

    last_move = _last_move(board)
    meta_2 = f'<div class="meta-2">{_e(last_move)}</div>' if last_move else ""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>In flight</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Caveat:wght@500;600&family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">
<style>{_CSS}{SHELL_CSS}{DRAWER_CSS}</style>
</head>
<body>
<div class="page">
{top_nav}
<div class="head"><div class="head-in">
<div>
<div class="title">in flight</div>
<div class="sub">{_subtitle(live)}</div>
</div>
<div class="meta-r">
<div class="meta-1"><span id="live-count">{live}</span> IN FLIGHT</div>
{meta_2}
</div>
</div></div>
<div class="wrap"><div class="scroller"><div class="board">{columns}</div></div></div>
</div>
{DRAWER_MOUNT}
<script>{drawer_js(payload, back_label="BACK TO BOARD")}</script>
<script>{js}</script>
</body>
</html>
"""
