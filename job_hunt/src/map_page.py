"""Renders the opportunity map page.

Recreates the map surface of
`design/wireframes/design_handoff_opportunity_map/Opportunity Map App.dc.html`
as a self-contained page generated from pipeline data. Vanilla HTML/CSS/JS —
the project generates static pages from Python and has no JS toolchain.

The page sits under the shared app shell (`shell.py`) and opens the shared
role drawer (`drawer.py`). The product rules from the handoff are enforced
here, not just described: no numeric score is ever emitted, a band never
renders without its reason, and an uncaptured description renders as its
own "not checked yet" state rather than as a weak band.
"""
import json
from datetime import date, datetime
from html import escape

from .drawer import DRAWER_CSS, DRAWER_MOUNT, drawer_js
from .shell import SHELL_CSS, shell_nav

# Tokens from the handoff. Percentages are deliberately avoided in the output
# so a stray "45%" can never look like a score to a reader or a test.
_CSS = """
*{box-sizing:border-box}
html,body{margin:0;background:#F7F2E6}
body{font-family:Inter,system-ui,sans-serif;color:#2A3342;-webkit-font-smoothing:antialiased}
a{color:#D6482B;text-decoration:none}
a:hover{color:#A83519}
::selection{background:rgba(46,125,91,.18)}
.page{min-height:100vh;background:#F7F2E6;background-image:radial-gradient(rgba(42,51,66,.14) 1px,transparent 1px);background-size:22px 22px;background-position:11px 11px;padding:0 0 90px}
.head{display:flex;justify-content:center;padding:30px 40px 30px}
.head-in{flex:1;max-width:820px;display:flex;align-items:flex-end;justify-content:space-between;gap:32px}
.title{font:600 42px/1 Caveat,cursive;color:#D6482B;letter-spacing:.01em}
.sub{font:400 15px/1.6 Inter,sans-serif;color:#4C5768;margin-top:9px;max-width:46ch;text-wrap:pretty}
.meta-r{flex:none;max-width:380px;text-align:right;padding-bottom:4px}
.meta-1{font:500 11px/1.7 'JetBrains Mono',monospace;color:#4C5768;letter-spacing:.1em}
.meta-2{font:400 11px/1.7 'JetBrains Mono',monospace;color:#8A93A1;letter-spacing:.1em;margin-top:7px}
.wrap{display:flex;justify-content:center;padding:0 40px}
.col{flex:1;max-width:820px;display:flex;flex-direction:column;gap:16px;min-width:0}
.lead{background:#FFFDF8;border:1px solid #CBBFA5;border-left:3px solid #2E7D5B;border-radius:4px;padding:22px 26px 20px;box-shadow:0 1px 0 rgba(42,51,66,.06)}
.card{background:#FFFDF8;border:1px solid #E0D8C4;border-radius:4px;padding:17px 22px}
.card:hover{border-color:#CBBFA5}
.crow{display:flex;align-items:baseline;gap:14px}
.cname{font:500 21px/1.25 Inter,sans-serif;color:#1F2937;letter-spacing:-.015em}
.card .cname{font:500 18px/1.3 Inter,sans-serif;letter-spacing:-.01em}
.cmeta{margin-left:auto;flex:none;font:500 11px/1 'JetBrains Mono',monospace;color:#8A93A1;letter-spacing:.1em}
.card .cmeta{font-size:10.5px}
.cwhy{font:400 15px/1.65 Inter,sans-serif;color:#4C5768;margin-top:9px;text-wrap:pretty}
.card .cwhy{font-size:14px;color:#6E7787;margin-top:7px}
.card .cwhy .creason{color:#3A4557}
.rule{height:1px;background:#EBE3D2;margin:18px 0;border:0}
.rtitle{font:500 17px/1.3 Inter,sans-serif;color:#1F2937}
.rmeta{font:400 11.5px/1 'JetBrains Mono',monospace;color:#6E7787;letter-spacing:.06em;margin-top:9px}
.brow{display:flex;gap:13px;align-items:flex-start;margin-top:15px}
.reason{font:400 14.5px/1.6 Inter,sans-serif;color:#3A4557;text-wrap:pretty}
.pill{flex:none;font:700 10px/1 'JetBrains Mono',monospace;letter-spacing:.11em;border-radius:2px}
.card .pill{font-size:9.5px}
.pill-strong{padding:5px 11px;background:#2E7D5B;color:#FFFDF8}
.pill-partial{padding:4px 10px;border:1px solid #2A5F86;color:#2A5F86}
.pill-stretch{padding:4px 10px;border:1px solid #B9C4D0;color:#6E7787}
.unchecked{display:flex;align-items:center;gap:12px;margin-top:13px;padding:11px 13px;border:1px dashed #C9BFA8;border-radius:3px;background:#F4EFE1}
.unchecked span{font:400 13.5px/1.6 Inter,sans-serif;color:#6E7787;text-wrap:pretty}
.unchecked b{color:#3A4557;font-weight:400}
.acts{display:flex;align-items:center;gap:10px;margin-top:16px}
.lead .acts{padding-top:18px;border-top:1px solid #EBE3D2}
.card .acts{margin-top:14px;gap:12px}
.btn-lead{padding:10px 18px;border:1px solid #D6482B;background:#D6482B;border-radius:3px;color:#FFFDF8;font:500 11.5px/1 'JetBrains Mono',monospace;letter-spacing:.07em;white-space:nowrap;cursor:pointer}
.btn-lead:hover{background:#A83519;border-color:#A83519}
.btn{padding:7px 13px;border:1px solid #E0D8C4;background:transparent;border-radius:3px;color:#D6482B;font:500 11px/1 'JetBrains Mono',monospace;letter-spacing:.06em;white-space:nowrap;cursor:pointer}
.btn:hover{border-color:#D6482B}
.btn-fetch{flex:none;margin-left:auto;background:#FFFDF8;border-color:#D5CDB9}
.btn-q{padding:7px 13px;border:1px solid transparent;background:transparent;border-radius:3px;color:#8A93A1;font:400 11px/1 'JetBrains Mono',monospace;letter-spacing:.06em;white-space:nowrap;cursor:pointer}
.btn-q:hover{color:#4C5768}
.tracked{padding:7px 0;color:#3B7EA8;font:500 11px/1 'JetBrains Mono',monospace;letter-spacing:.06em;text-decoration:none;white-space:nowrap}
.btn-hide{margin-left:auto;color:#9AA3AE}
.fold{display:flex;align-items:center;gap:16px;margin-top:4px}
.fold span{flex:none;font:400 10.5px/1 'JetBrains Mono',monospace;color:#8A93A1;letter-spacing:.1em}
.fold i{flex:1;height:1px;background:#DED5C1}
.shelf{margin-top:34px}
.shelf-h{display:flex;align-items:baseline;justify-content:space-between;gap:16px;padding-bottom:12px;border-bottom:1px solid #E0D8C4}
.shelf-t{font:600 26px/1 Caveat,cursive;color:#2E7D5B}
.shelf-m{flex:none;font:400 10.5px/1 'JetBrains Mono',monospace;color:#8A93A1;letter-spacing:.1em}
.tiles{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:16px}
.tile{background:#F4EFE1;border:1px solid #E0D8C4;border-radius:3px;padding:13px 15px}
.tile-n{font:500 14.5px/1.3 Inter,sans-serif;color:#3A4557}
.tile-r{font:400 13px/1.55 Inter,sans-serif;color:#8A93A1;margin-top:5px}
.quiet{background:#FFFDF8;border:1px solid #E0D8C4;border-radius:4px;padding:24px 26px;margin-bottom:4px}
.quiet-t{font:600 26px/1.2 Caveat,cursive;color:#2A3342}
.quiet-b{font:400 14.5px/1.65 Inter,sans-serif;color:#4C5768;margin-top:8px;max-width:52ch;text-wrap:pretty}
.hidden{display:none}
.fold-btn{display:flex;align-items:center;gap:16px;margin-top:4px;align-self:stretch;border:0;background:transparent;padding:6px 0;cursor:pointer;text-align:left}
.fold-btn span.lbl{flex:none;font:400 10.5px/1 'JetBrains Mono',monospace;color:#8A93A1;letter-spacing:.1em}
.fold-btn:hover span.lbl{color:#4C5768}
.fold-btn i{flex:1;height:1px;background:#DED5C1}
.banner{display:block;margin:0 0 20px;padding:11px 16px;border-radius:4px;
background:#FBEFE9;border:1px solid #E8B9A6;color:#A83519;
font:500 12.5px/1.3 'JetBrains Mono',monospace;letter-spacing:.02em}
.empty{padding:64px 0;text-align:center;color:#8A93A1}
.go{margin-top:16px;display:inline-block;padding:9px 18px;border-radius:3px;
cursor:pointer;background:#D6482B;color:#FFFDF8;border:1px solid #D6482B;
font:500 11px/1 'JetBrains Mono',monospace;letter-spacing:.06em}
.go:hover{background:#A83519;border-color:#A83519}
.go.alt{background:transparent;color:#D6482B}
.go.alt:hover{background:transparent;color:#A83519}
.go-head{margin-top:14px}
.card,.lead{cursor:pointer}
.card:hover{border-color:#B9AC8F;box-shadow:0 1px 0 rgba(42,51,66,.08)}
.mline{margin-top:3px}
.mline b{font-weight:500;color:#4C5768}
.mc{white-space:nowrap;cursor:help;border-bottom:1px dotted #C9BFA8}
.btn-on{color:#2A5F86}
.btn-on:hover{color:#1F4A69}
.gone-card{display:none}
.toast{position:fixed;left:50%;bottom:26px;transform:translateX(-50%);z-index:50;display:flex;align-items:center;gap:16px;padding:11px 14px 11px 18px;background:#2A3342;color:#FFFDF8;border-radius:4px;box-shadow:0 8px 24px -12px rgba(42,51,66,.6);font:400 13.5px/1.4 Inter,sans-serif;max-width:min(560px,92vw)}
.toast button{flex:none;border:1px solid rgba(255,253,248,.4);background:transparent;color:#FFFDF8;border-radius:3px;padding:6px 11px;font:500 11px/1 'JetBrains Mono',monospace;letter-spacing:.07em;cursor:pointer}
.toast button:hover{border-color:#FFFDF8}
"""

_PILL_CLASS = {"STRONG FIT": "pill-strong",
               "PARTIAL FIT": "pill-partial",
               "STRETCH": "pill-stretch"}

_LEAD_VISIBLE = 4


def _e(value) -> str:
    return escape(str(value or ""), quote=True)


def _days_ago(posted) -> str:
    try:
        if isinstance(posted, (date, datetime)):
            d = posted.date() if isinstance(posted, datetime) else posted
        else:
            d = datetime.strptime(str(posted)[:10], "%Y-%m-%d").date()
        n = max(0, (date.today() - d).days)
        return "today" if n == 0 else f"{n}d"
    except (ValueError, TypeError):
        return ""


def _role_meta(role: dict) -> str:
    bits = [role.get("work_mode") or "",
            role.get("location") or "", f"POSTED {_days_ago(role.get('date'))}"
            if _days_ago(role.get("date")) else "", role.get("salary") or ""]
    if not role.get("description_captured"):
        bits.append("NO DESCRIPTION CAPTURED")
    return " · ".join(b for b in bits if b).upper()


def _last_search(finished) -> str:
    """'TODAY 14:54', 'YESTERDAY 14:54' or 'OCT 14, 14:54', in local
    time. `finished` is the run's stored UTC ISO stamp; anything
    unreadable renders nothing rather than a guess."""
    if not finished:
        return ""
    try:
        when = datetime.fromisoformat(str(finished).replace("Z", "+00:00"))
    except ValueError:
        return ""
    if when.tzinfo is not None:
        when = when.astimezone()
    days = (date.today() - when.date()).days
    day = ("TODAY" if days == 0 else "YESTERDAY" if days == 1
           else when.strftime("%b %d,").upper().replace(" 0", " "))
    return f"{day} {when.strftime('%H:%M')}"


def _clause(n: int, label: str, tip: str) -> str:
    """One header count, kept on one line, explained on hover."""
    return f'<span class="mc" title="{_e(tip)}">{int(n)} {_e(label)}</span>'


def _section_heading(label: str) -> str:
    return (f'<div class="fold"><i></i><span>{_e(label)}</span>'
            f'<i></i></div>')


def _band_pill(role: dict) -> str:
    """Rule 2 — only emitted by callers that also emit the reason."""
    band = role.get("band")
    if not band:
        return ""
    cls = _PILL_CLASS.get(band, "pill-stretch")
    return f'<span class="pill {cls}">{_e(band)}</span>'


def _sentence(text: str) -> str:
    """Reasons are composed lowercase; here one follows 'Not checked yet.'"""
    text = (text or "").strip()
    return text[:1].upper() + text[1:] if text else ""


def _unchecked_block(role: dict) -> str:
    """Rule 3 — its own state, never a weak band. The way out is the
    posting itself: nothing here can fetch a description after the run,
    so the button opens the original rather than promising a fetch."""
    url = role.get("url") or ""
    posting = (f'<a class="btn btn-fetch" href="{_e(url)}" target="_blank" '
               f'rel="noopener">OPEN POSTING &#8599;</a>' if url else "")
    return (
        '<div class="unchecked"><span><b>Not checked yet.</b> '
        f'{_e(_sentence(role.get("reason")))}</span>{posting}</div>'
    )


def _checked(role: dict) -> bool:
    """Whether the band+reason pair may render at all (rules 2 and 3)."""
    return bool(role.get("description_captured")
                and role.get("band") and role.get("reason"))


def _track_action(role_id, app_status: str | None, ids: str) -> str:
    """A role already on the tracker shows a marker leading to the board
    instead of SAVE — adding it again is not an action it needs."""
    if app_status:
        return (f'<a class="tracked" href="/activity">IN TRACKER &middot; '
                f'{_e(app_status)}</a>')
    if role_id is not None:
        return (f'<button type="button" class="btn-q" data-status="SAVED"'
                f'{ids}>SAVE</button>')
    return ""


def _ids(company_id, role_id) -> str:
    ids = ""
    if role_id is not None:
        ids += f' data-role="{_e(str(role_id))}"'
    if company_id is not None:
        ids += f' data-company="{_e(str(company_id))}"'
    return ids


def _watch_button(m: dict, ids: str) -> str:
    """WATCH keeps a company on the "keeping an eye on" shelf once its
    roles close. It changes nothing on the card itself, so the button
    has to show its own state or a click looks like it did nothing."""
    if m.get("user_state") == "WATCH":
        return (f'<button type="button" class="btn-q btn-on" data-state="NONE"'
                f' title="Click to stop watching"{ids}>WATCHING &#10003;'
                f'</button>')
    return (f'<button type="button" class="btn-q" data-state="WATCH" '
            f'title="Keep this company in view even when nothing is open"'
            f'{ids}>WATCH</button>')


def _hide_button(m: dict, ids: str) -> str:
    """HIDE removes the role shown on the card, not the whole company.
    The page waits a few seconds before saving it so a stray click can
    be undone (see _JS)."""
    more = ' data-more="1"' if len(m.get("roles") or []) > 1 else ""
    return (f'<button type="button" class="btn-q btn-hide" data-status="HIDDEN"'
            f' title="Hide this role from the map"{more}{ids}>HIDE</button>')


def _watch_chip(m: dict) -> str:
    """Marker only — watching changed what was fetched, never a rank."""
    if not m.get("watched"):
        return ""
    return ('<span style="color:#2A5F86;font:500 10px/1 \'JetBrains Mono\','
            'monospace;letter-spacing:.1em;margin-left:8px">WATCHLIST</span>')


def _lead_card(m: dict, key: str) -> str:
    role = m["roles"][0]
    n = len(m["roles"])
    noun = "ROLE" if n == 1 else "ROLES"
    ids = _ids(m.get("id"), role.get("id"))
    fit = (f'<div class="brow">{_band_pill(role)}'
           f'<span class="reason">{_e(role.get("reason"))}</span></div>'
           if _checked(role) else
           _unchecked_block(role) if not role.get("description_captured")
           else "")
    return (
        f'<div class="lead"><div class="crow">'
        f'<div class="cname">{_e(m["name"])}{_watch_chip(m)}</div>'
        f'<div class="cmeta">{n} {noun} OPEN</div></div>'
        f'<div class="cwhy">{_e(m["why"])}</div>'
        f'<hr class="rule">'
        f'<div class="rtitle">{_e(role.get("title"))}</div>'
        f'<div class="rmeta">{_e(_role_meta(role))}</div>'
        f'{fit}'
        f'<div class="acts">'
        f'<button type="button" class="btn-lead" data-open="{_e(key)}">'
        f'REVIEW ROLE</button>'
        f'{_track_action(role.get("id"), role.get("app_status"), ids)}'
        f'{_watch_button(m, ids)}'
        f'{_hide_button(m, ids)}'
        f'</div></div>'
    )


def _compact_card(m: dict, key: str) -> str:
    """A compact company card. Company evidence and the role's reason
    share one paragraph (evidence muted, reason darker), and the band
    pill leads the action row — the App file's compact anatomy."""
    role = m["roles"][0]
    n = len(m["roles"])
    noun = "ROLE" if n == 1 else "ROLES"
    tag = "NEW TO YOU · " if m.get("state") == "DISCOVER" else ""
    age = _days_ago(role.get("date"))
    meta = f'{tag}{n} {noun}' + (f' · {age}' if age else "")

    checked = _checked(role)
    # Two sentences about two different things: the company line counts
    # every matching role, the reason is about the one role on the card.
    # Run together they read as one contradictory sentence ("naming
    # Tableau ... nothing on your resume was named"), so the reason is
    # set apart and says which role it means.
    reason = (f'<span class="creason">Top role: {_e(role.get("reason"))}'
              f'</span>' if checked else "")
    company = _e(m["why"]) + ("." if m.get("why") and reason else "")
    why = f'<div class="cwhy">{company} {reason}</div>'
    unchecked = ("" if role.get("description_captured")
                 else _unchecked_block(role))
    # Rule 2 — the pill renders in the action row only because the reason
    # sentence rendered in the paragraph above it.
    pill = _band_pill(role) if checked else ""

    ids = _ids(m.get("id"), role.get("id"))
    return (
        f'<div class="card"><div class="crow">'
        f'<div class="cname">{_e(m["name"])}{_watch_chip(m)}</div>'
        f'<div class="cmeta">{_e(meta.upper())}</div></div>'
        f'{why}{unchecked}'
        f'<div class="acts">{pill}'
        f'<button type="button" class="btn" data-open="{_e(key)}">REVIEW ROLE</button>'
        f'{_track_action(role.get("id"), role.get("app_status"), ids)}'
        f'{_watch_button(m, ids)}'
        f'{_hide_button(m, ids)}'
        f'</div></div>'
    )


def _watch_shelf(watch_maps: list[dict]) -> str:
    if not watch_maps:
        return ""
    tiles = "".join(
        f'<div class="tile"><div class="tile-n">{_e(m["name"])}</div>'
        f'<div class="tile-r">{_e(m["why"])}</div></div>'
        for m in watch_maps
    )
    return (
        f'<div class="shelf"><div class="shelf-h">'
        f'<div class="shelf-t">keeping an eye on</div>'
        f'<div class="shelf-m">NO ROLE OPEN · {len(watch_maps)}</div></div>'
        f'<div class="tiles">{tiles}</div></div>'
    )


def _quiet_header(open_count: int, unchecked: int) -> str:
    # Both actions used to be buttons with nothing behind them (FETCH N
    # MISSING DESCRIPTIONS, WIDEN SOURCES). The real ways to widen the
    # search are the watchlist and the resumes, both on the profile.
    missing = (f' {unchecked} of them arrived without a description, so '
               'their skills could not be compared.' if unchecked else "")
    return (
        '<div class="quiet"><div class="quiet-t">nothing to apply to today</div>'
        f'<div class="quiet-b">{open_count} postings came in; none named enough '
        'of your stack to earn the top of the list. That is the check working, '
        f'not a dry spell.{missing}</div>'
        '<div class="acts">'
        '<a class="btn" href="/profile#watchlist">WATCH MORE COMPANIES</a>'
        '</div></div>'
    )


def _drawer_payload(maps: list[dict], keys: dict | None = None) -> dict:
    """Data the drawer needs. The internal score is deliberately excluded.

    `maps` comes in the order the page lists the cards, and the drawer's
    NEXT walks the payload in that order; `keys` maps id(m) to the key
    the card's REVIEW ROLE button opens."""
    out: dict = {}
    for i, m in enumerate(maps):
        if not m.get("roles"):
            continue
        out[(keys or {}).get(id(m), f"c{i}")] = {
            "name": m["name"],
            "why": m["why"],
            "roles": [{
                "title": r.get("title") or "",
                "tab": (r.get("title") or "")[:28],
                "meta": _role_meta(r),
                "band": r.get("band"),
                "reason": r.get("reason") or "",
                "matched": list(r.get("matched") or []),
                "gaps": list(r.get("gaps") or []),
                "captured": bool(r.get("description_captured")),
                "url": r.get("url") or "",
                "rid": r.get("id"),
                "app_status": r.get("app_status"),
            } for r in m["roles"]],
        }
    return out


# The page's own wiring: open the shared drawer, post card actions, unfold
# the folded groups. The drawer's internals live in drawer.py.
_JS = """
document.addEventListener('click',function(e){
  const o=e.target.closest('[data-open]');
  if(o){window.Drawer.open(o.getAttribute('data-open'),0);return;}
  // The whole card opens the role, not only its open button: a
  // bigger target, and where people click on a job card anyway. Its own
  // buttons and links keep their jobs; selecting text does not open it.
  const card=e.target.closest('.card,.lead');
  if(card&&!e.target.closest('button,a,input,select,label')&&!String(window.getSelection()).trim()){
    const k=card.querySelector('[data-open]');
    if(k){window.Drawer.open(k.getAttribute('data-open'),0);return;}
  }
  const f=e.target.closest('[data-expand]');
  if(f){const grp=document.getElementById(f.getAttribute('data-expand'));if(grp){grp.classList.remove('hidden');}f.remove();}
});
async function post(url, body){
  const r = await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  if(r.ok){location.reload();}else{alert('That did not save. Try again.');}
}
// HIDE waits before saving, with an UNDO, because nothing on any page
// can bring a hidden role back. Leaving the page saves it at once.
let pendingHide=null;
function flushHide(reload){
  const p=pendingHide; if(!p){return;}
  pendingHide=null; clearTimeout(p.timer); p.toast.remove();
  fetch('/api/roles/'+p.role+'/status',{method:'POST',keepalive:true,
    headers:{'Content-Type':'application/json'},body:JSON.stringify({status:p.status})})
    .then(function(r){if(!r.ok){throw new Error();} if(reload&&p.more){location.reload();}})
    .catch(function(){p.card.classList.remove('gone-card');alert('That did not save. Try again.');});
}
function hideWithUndo(btn){
  flushHide(false);
  const card=btn.closest('.card,.lead');
  const toast=document.createElement('div');
  toast.className='toast'; toast.setAttribute('role','status');
  toast.innerHTML='<span>Role hidden from the map.</span><button type="button" data-undo="1">UNDO</button>';
  document.body.appendChild(toast);
  if(card){card.classList.add('gone-card');}
  pendingHide={role:btn.dataset.role,status:btn.dataset.status,more:btn.dataset.more==='1',
    card:card||document.createElement('div'),toast:toast,timer:setTimeout(function(){flushHide(true);},6000)};
}
window.addEventListener('pagehide',function(){flushHide(false);});
document.addEventListener('click',function(e){
  if(e.target.closest('[data-undo]')&&pendingHide){
    const p=pendingHide; pendingHide=null; clearTimeout(p.timer);
    p.toast.remove(); p.card.classList.remove('gone-card'); return;
  }
  const s=e.target.closest('[data-status]');
  if(s&&s.dataset.role&&s.classList.contains('btn-hide')){hideWithUndo(s);return;}
  if(s&&s.dataset.role){post('/api/roles/'+s.dataset.role+'/status',{status:s.dataset.status});return;}
  const w=e.target.closest('[data-state]');
  if(w&&w.dataset.company){post('/api/companies/'+w.dataset.company+'/state',{state:w.dataset.state});}
});
"""


def render(maps: list[dict], meta: dict | None = None,
           running_run_id: int | None = None,
           nav: dict | None = None) -> str:
    """Build the full opportunity map page.

    `nav` carries the shell's counts and identity: `tracker_count` for
    the TRACKER tab badge and `user_label` beside the wordmark. The MAP
    badge is the company count this render already knows."""
    meta = meta or {}
    nav = nav or {}
    listed = [m for m in maps if m.get("state") != "WATCH"]
    watching = [m for m in maps if m.get("state") == "WATCH"]
    act_now = [m for m in listed if m.get("state") == "ACT_NOW"]

    keys = {id(m): f"c{i}" for i, m in enumerate(maps)}

    body: list[str] = []
    if not act_now:
        unchecked = sum(1 for m in listed for r in m["roles"]
                        if not r.get("description_captured"))
        roles_seen = sum(len(m["roles"]) for m in listed)
        body.append(_quiet_header(roles_seen, unchecked))

    fresh = [m for m in listed if m.get("section", "new") == "new"]
    earlier = [m for m in listed if m.get("section") == "earlier"]

    def _emit(group: list[dict], allow_lead: bool, group_id: str) -> None:
        for i, m in enumerate(group[:_LEAD_VISIBLE]):
            if not m.get("roles"):
                continue
            key = keys[id(m)]
            body.append(_lead_card(m, key) if i == 0 and allow_lead and act_now
                        else _compact_card(m, key))
        rest = [m for m in group[_LEAD_VISIBLE:] if m.get("roles")]
        if rest:
            noun = "COMPANY" if len(rest) == 1 else "COMPANIES"
            rest_html = "".join(_compact_card(m, keys[id(m)]) for m in rest)
            body.append(
                f'<button type="button" class="fold-btn" data-expand="{group_id}">'
                f'<i></i><span class="lbl">{len(rest)} MORE {noun} '
                f'WITH OPEN ROLES</span><i></i></button>'
                f'<div id="{group_id}" class="hidden">{rest_html}</div>')

    _emit(fresh, allow_lead=True, group_id="more-fresh")
    if earlier:
        body.append(_section_heading("still here from earlier"))
        _emit(earlier, allow_lead=False, group_id="more-earlier")

    n_co = meta.get("companies", len(maps))
    n_ro = meta.get("roles", sum(len(m.get("roles") or []) for m in maps))
    # The finish time of the last successful search. This used to fall
    # back to the clock at render time, so the header always claimed the
    # data was scraped a moment ago. No run, no claim.
    scraped = _last_search(meta.get("scraped"))

    # Hiding is never silent. The map lists roles proven open to this user
    # AND roles whose reach we simply could not judge; it hides only the
    # ones a posting's own words rule out. So the header carries the full
    # account of what was set aside and why.
    #
    # Ship 8 hid the unverified too. On the real store that was 1055
    # LinkedIn rows the user could see on LinkedIn itself — jobs they
    # could act on, behind a bare number. Unverified is not closed: a
    # LinkedIn location is a place, not a reach statement, so those roles
    # were never judged rather than judged and rejected. They rank below
    # the proven-open ones and say so on the card.
    #
    # Unconditional, unlike the clauses below: "0 OPEN" is the answer when
    # it is the answer, and suppressing it would make an empty map read as
    # broken rather than as checked.
    #
    # Laid out as two groups — what is ON the map, what was SET ASIDE —
    # each clause unbroken and carrying a plain-words tooltip. As one
    # run-on line the counts wrapped mid-clause ("HIDDEN (POSTING /
    # CLOSED)") and read as a wall of codes.
    on_map = [_clause(meta.get("open") or 0, "OPEN",
                      "Roles whose posting says it can hire where you are"),
              _clause(meta.get("unverified") or 0, "UNVERIFIED",
                      "Roles that do not say where they can hire from. "
                      "They are listed, below the proven-open ones")]
    aside = [_clause(meta.get("closed") or 0, "NOT OPEN",
                     "Postings whose own words rule out hiring where "
                     "you are")]

    # The other policy exception that removes postings still has to say so
    # somewhere the reader will see it — not just the run row.
    hidden = meta.get("hidden") or 0
    if hidden:
        aside.append(_clause(hidden, "HIDDEN (ON-SITE ELSEWHERE)",
                             "Hybrid or on-site roles in another country"))

    # A relevance-gate rejection is a different fact from a hidden-elsewhere
    # posting — wrong place vs. not this job at all — so it earns its own
    # clause rather than folding into the count above.
    offtopic = meta.get("offtopic") or 0
    if offtopic:
        aside.append(_clause(offtopic, "OFF-TOPIC (NOT A TARGET ROLE)",
                             "Job titles that are not one of your target "
                             "roles"))

    sep = " &middot; "
    meta_2 = (
        (f'<div class="mline">LAST SEARCH {_e(scraped)}</div>'
         if scraped else "")
        + f'<div class="mline"><b>ON THE MAP</b>{sep}{sep.join(on_map)}</div>'
        + f'<div class="mline"><b>SET ASIDE</b>{sep}{sep.join(aside)}'
          f'{sep}<a href="/profile#filtered">WHY?</a></div>')

    payload = json.dumps(_drawer_payload(fresh + earlier, keys),
                         ensure_ascii=False)
    payload = payload.replace("</", "<\\/")

    # Only counts the run has actually produced. While scraping, the total is
    # unknown, so the banner never shows a denominator — inventing one would
    # be the fabricated-precision pattern this project bans.
    banner = ""
    if running_run_id:
        banner = (f'<a class="banner" href="/searching/{running_run_id}">'
                  f'searching now &middot; see progress</a>')

    # Starting a new search sits in the header, beside when the last one
    # ran. It used to be the last thing on the page, below every folded
    # company - the main way to get fresh roles was the hardest to find.
    empty = ""
    again = ""
    if maps and not running_run_id:
        again = ('<button class="go alt go-head" onclick="startRun()">'
                 'SEARCH FOR NEW ROLES</button>')
    elif not maps:
        empty = ('<div class="empty"><p>nothing searched yet</p>'
                 '<button class="go" onclick="startRun()">START SEARCHING'
                 '</button></div>')

    starter = """<script>
async function startRun(){
  const r = await fetch('/api/runs', {method:'POST'});
  const body = await r.json();
  if(body.run_id){ window.location = '/searching/' + body.run_id; }
  else { alert(body.error || 'Could not start a search.'); }
}
</script>"""

    top_nav = shell_nav("/", counts={"/": n_co,
                                     "/activity": nav.get("tracker_count")},
                        user_label=nav.get("user_label") or "")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Opportunity map</title>
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
<div class="title">today</div>
<div class="sub">Companies worth twenty minutes. Everything below them is here for a reason you can read.</div>
{again}
</div>
<div class="meta-r">
<div class="meta-1">{n_co} COMPANIES &middot; {n_ro} ROLES</div>
<div class="meta-2">{meta_2}</div>
</div>
</div></div>
<div class="wrap"><div class="col">
{banner}
{empty}
{"".join(body)}
{_watch_shelf(watching)}
</div></div>
</div>
{DRAWER_MOUNT}
<script>{drawer_js(payload)}</script>
<script>{_JS}</script>
{starter}
</body>
</html>
"""


def open_browser(path) -> None:
    """Open a generated page in the system browser."""
    import os
    import subprocess

    try:
        os.startfile(str(path))              # Windows
    except AttributeError:
        subprocess.Popen(["open", str(path)])  # macOS
    except Exception:
        print(f"  Open manually: {path}")
