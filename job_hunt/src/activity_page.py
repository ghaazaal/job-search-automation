"""Renders the activity screen as a kanban board.

One column per application status. Dark design system per DESIGN.md — the
paper palette is retired. Oldest first within each column so the thing
waiting longest is on top. Cards move between columns by drag-and-drop or
by the per-card status select; both POST to the existing
/api/roles/<id>/status endpoint.
"""
from datetime import date, datetime
from html import escape

from .nav import nav_links

_COLUMNS = [("SAVED", "saved"), ("APPLIED", "applied"),
            ("INTERVIEWING", "interviewing"), ("OFFER", "offer"),
            ("REJECTED", "rejected"), ("CLOSED", "closed")]

# The four states that count as "in flight" in the header. Rejected and
# closed are outcomes, not motion.
_LIVE = ("SAVED", "APPLIED", "INTERVIEWING", "OFFER")

_BAND_CLASS = {"STRONG FIT": "band-strong",
               "PARTIAL FIT": "band-partial",
               "STRETCH": "band-stretch"}

_CSS = """
*{box-sizing:border-box}
html,body{margin:0;background:#0A0E1A}
body{font-family:Inter,system-ui,sans-serif;color:#FFFFFF;-webkit-font-smoothing:antialiased}
a{color:#00D4FF;text-decoration:none}
a:hover{text-decoration:underline}
.head{display:flex;align-items:flex-end;justify-content:space-between;gap:32px;padding:24px 24px 20px;border-bottom:1px solid #1E2A3A;background:#0D1117}
.title{font:700 20px/1.3 'JetBrains Mono',monospace;letter-spacing:.08em;text-transform:uppercase;color:#FFFFFF}
.sub{font:400 13px/1.7 Inter,sans-serif;color:#8B9CB0;margin-top:6px}
.sub b{font:500 13px/1 'JetBrains Mono',monospace;color:#00D4FF}
.nav{font:500 11px/1 'JetBrains Mono',monospace;letter-spacing:.1em;color:#8B9CB0}
.nav a{color:#8B9CB0}
.nav .nav-here{color:#00D4FF}
.board{display:flex;gap:14px;align-items:flex-start;padding:20px 24px 80px;overflow-x:auto;min-height:70vh}
.col{flex:0 0 280px;min-width:280px;background:#0D1117;border:1px solid #1E2A3A;padding:12px}
.col.drop-target{border-color:#00D4FF;background:#0F1F35}
.colhead{display:flex;align-items:baseline;gap:8px;padding-bottom:10px;border-bottom:1px solid #1E2A3A}
.colname{font:500 11px/1 'JetBrains Mono',monospace;letter-spacing:.1em;text-transform:uppercase;color:#8B9CB0}
.colcount{margin-left:auto;font:500 11px/1 'JetBrains Mono',monospace;color:#4B5563}
.stack{display:flex;flex-direction:column;gap:10px;margin-top:12px;min-height:24px}
.card{display:flex;flex-direction:column;align-items:stretch;background:#111827;border:1px solid #1E2A3A;padding:12px 14px;cursor:grab;transition:background-color 150ms ease-out}
.card:hover{background:#0F1F35}
.card.dragging{opacity:.5}
.co{font:500 10px/1 'JetBrains Mono',monospace;color:#4B5563;letter-spacing:.1em;text-transform:uppercase}
.rt{font:500 14px/1.5 Inter,sans-serif;margin-top:6px}
.loc{font:400 11px/1.5 'JetBrains Mono',monospace;color:#8B9CB0;margin-top:6px}
.pill{display:inline-block;font:500 10px/1.4 'JetBrains Mono',monospace;letter-spacing:.05em;text-transform:uppercase;padding:2px 8px;border-radius:3px;border:1px solid;margin-top:10px}
.band-strong{color:#00D9A3;border-color:rgba(0,217,163,.35);background:rgba(0,217,163,.15)}
.band-partial{color:#F59E0B;border-color:rgba(245,158,11,.35);background:rgba(245,158,11,.15)}
.band-stretch{color:#E05C5C;border-color:rgba(224,92,92,.35);background:rgba(224,92,92,.15)}
.pill-dim{color:#8B9CB0;border-color:#4B5563;background:transparent}
.reason{font:400 13px/1.7 Inter,sans-serif;color:#8B9CB0;margin-top:6px}
.move{margin-top:10px;font:500 10px/1.4 'JetBrains Mono',monospace;letter-spacing:.05em;text-transform:uppercase;color:#8B9CB0;background:#0D1117;border:1px solid #1E2A3A;border-radius:4px;padding:4px 6px}
.err{font:400 11px/1.5 'JetBrains Mono',monospace;color:#E05C5C;margin-top:8px}
.log{margin-top:10px;padding-top:9px;border-top:1px solid #1E2A3A}
.ev{font:400 11px/1.6 'JetBrains Mono',monospace;color:#4B5563}
.empty{font:400 13px/1.6 Inter,sans-serif;color:#4B5563;margin-top:12px}
@media (prefers-reduced-motion: reduce){
  *{transition:none !important;animation:none !important}
}
"""

_JS = """
(function () {
  'use strict';

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
      if (col.hasAttribute('data-live')) { live += n; }
    });
    var header = document.getElementById('live-count');
    if (header) { header.textContent = live; }
  }

  function flashError(card, message) {
    var note = document.createElement('div');
    note.className = 'err';
    note.textContent = message;
    card.appendChild(note);
    setTimeout(function () { note.remove(); }, 4000);
  }

  function moveCard(card, targetCol, onRevert) {
    var fromStack = card.parentElement;
    // Captured before the move so a failed POST puts the card back where
    // it was — appending on revert would break oldest-first until reload.
    var anchor = card.nextElementSibling;
    var status = targetCol.getAttribute('data-status');
    if (fromStack === targetCol.querySelector('.stack')) { return; }
    targetCol.querySelector('.stack').appendChild(card);
    refreshCounts();
    var select = card.querySelector('.move');
    var previous = select ? select.getAttribute('data-current') : null;
    if (select) {
      select.value = status;
      select.setAttribute('data-current', status);
    }
    post(card.getAttribute('data-role-id'), status).then(function (r) {
      if (!r.ok) { throw new Error('HTTP ' + r.status); }
    }).catch(function () {
      fromStack.insertBefore(card, anchor);
      if (select && previous !== null) {
        select.value = previous;
        select.setAttribute('data-current', previous);
      }
      refreshCounts();
      flashError(card, 'could not move — reverted');
      if (onRevert) { onRevert(); }
    });
  }

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

  document.querySelectorAll('.move').forEach(function (select) {
    select.addEventListener('change', function () {
      var card = select.closest('.card');
      var col = document.querySelector(
        '.col[data-status="' + select.value + '"]');
      if (card && col) { moveCard(card, col); }
    });
  });
})();
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


def _pill(card: dict) -> str:
    """Fit band pill + reason. A pill without its reason sentence is a bug,
    so band and reason must both be present or nothing renders. When no
    description was captured the pill is muted — it must not imply a
    verified skill match."""
    band, reason = card.get("band"), card.get("reason")
    if not band or not reason:
        return ""
    if card.get("description_captured"):
        cls = f"pill {_BAND_CLASS.get(band, 'pill-dim')}"
    else:
        cls = "pill pill-dim"
    return (f'<div><span class="{cls}">{_e(band.lower())}</span></div>'
            f'<div class="reason">{_e(reason)}</div>')


def _move_control(status: str) -> str:
    options = "".join(
        f'<option value="{key}"{" selected" if key == status else ""}>'
        f'{label}</option>'
        for key, label in _COLUMNS)
    return (f'<select class="move" data-current="{_e(status)}" '
            f'aria-label="Move to status">{options}</select>')


def _card(card: dict) -> str:
    events = "".join(
        f'<div class="ev">{_e(str(e["at"])[:10])} &middot; '
        f'{_e((e["to_status"] or "").lower())}</div>'
        for e in card.get("events") or []
    )
    log = f'<div class="log">{events}</div>' if events else ""
    return (
        f'<div class="card" draggable="true" '
        f'data-role-id="{_e(card["role_id"])}">'
        f'<div class="co">{_e(card["company"])}</div>'
        f'<div class="rt"><a href="{_e(card["url"])}" target="_blank" '
        f'rel="noopener">{_e(card["title"])}</a></div>'
        f'<div class="loc">{_e(card.get("location"))} &middot; '
        f'{_e(_days(card.get("updated_at")))} in this state</div>'
        f'{_pill(card)}'
        f'{_move_control(card.get("status") or "")}'
        f'{log}</div>'
    )


def _column(key: str, label: str, cards: list[dict], live: bool) -> str:
    body = ("".join(_card(c) for c in cards) if cards
            else '<div class="empty">nothing here yet</div>')
    return (
        f'<div class="col" data-status="{key}"'
        f'{" data-live=\"1\"" if live else ""}>'
        f'<div class="colhead"><div class="colname">{label}</div>'
        f'<div class="colcount">{len(cards)}</div></div>'
        f'<div class="stack">{body}</div></div>'
    )


def render(board: dict) -> str:
    """Render the activity board. `board` comes from queries.activity_board."""
    columns = "".join(_column(key, label, board.get(key) or [], key in _LIVE)
                      for key, label in _COLUMNS)
    live = sum(len(board.get(k) or []) for k in _LIVE)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Activity</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">
<style>{_CSS}</style>
</head>
<body>
<div class="head">
<div>
<div class="title">In Flight</div>
<div class="sub"><b id="live-count">{live}</b> in flight. Oldest at the top of each column.
Drag a card, or use its status control.</div>
</div>
<div class="nav">{nav_links("/activity")}</div>
</div>
<div class="board">{columns}</div>
<script>{_JS}</script>
</body>
</html>
"""
