"""Renders the opportunity map page.

Recreates `docs/design_handoff_opportunity_map/Opportunity Map Notebook.dc.html`
as a self-contained page generated from pipeline data. Vanilla HTML/CSS/JS —
the project generates static pages from Python and has no JS toolchain.

The product rules from the handoff are enforced here, not just described:
no numeric score is ever emitted, a band never renders without its reason, and
an uncaptured description renders as its own "not checked yet" state rather
than as a weak band.
"""
import json
from datetime import date, datetime
from html import escape

# Tokens from the handoff. Percentages are deliberately avoided in the output
# so a stray "45%" can never look like a score to a reader or a test.
_CSS = """
*{box-sizing:border-box}
html,body{margin:0;background:#F7F2E6}
body{font-family:Inter,system-ui,sans-serif;color:#2A3342;-webkit-font-smoothing:antialiased}
a{color:#D6482B;text-decoration:none}
a:hover{color:#A83519}
::selection{background:rgba(46,125,91,.18)}
.page{min-height:100vh;background:#F7F2E6;background-image:radial-gradient(rgba(42,51,66,.14) 1px,transparent 1px);background-size:22px 22px;background-position:11px 11px;padding:0 0 80px}
.hatch{height:26px;background-image:repeating-linear-gradient(112deg,rgba(59,126,168,.28) 0 1px,transparent 1px 7px);mask-image:linear-gradient(to bottom,#000,transparent);-webkit-mask-image:linear-gradient(to bottom,#000,transparent)}
.head{display:flex;justify-content:center;padding:30px 40px 34px}
.head-in{flex:1;max-width:1180px;display:flex;align-items:flex-end;justify-content:space-between;gap:32px}
.title{font:600 46px/1 Caveat,cursive;color:#D6482B;letter-spacing:.01em}
.sub{font:400 15px/1.6 Inter,sans-serif;color:#4C5768;margin-top:10px;max-width:46ch;text-wrap:pretty}
.meta-r{flex:none;text-align:right;padding-bottom:4px}
.meta-1{font:500 11px/1 'JetBrains Mono',monospace;color:#4C5768;letter-spacing:.1em}
.meta-2{font:400 11px/1 'JetBrains Mono',monospace;color:#8A93A1;letter-spacing:.1em;margin-top:9px}
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
.rule{height:1px;background:#EBE3D2;margin:18px 0;border:0}
.rtitle{font:500 17px/1.3 Inter,sans-serif;color:#1F2937}
.rmeta{font:400 11.5px/1 'JetBrains Mono',monospace;color:#6E7787;letter-spacing:.06em;margin-top:9px}
.brow{display:flex;gap:13px;align-items:flex-start;margin-top:15px}
.reason{font:400 14.5px/1.6 Inter,sans-serif;color:#3A4557;text-wrap:pretty}
.card .reason{font-size:14px}
.pill{flex:none;font:700 9.5px/1 'JetBrains Mono',monospace;letter-spacing:.11em;border-radius:2px}
.pill-strong{padding:5px 11px;background:#2E7D5B;color:#FFFDF8}
.pill-partial{padding:4px 10px;border:1px solid #2A5F86;color:#2A5F86}
.pill-stretch{padding:4px 10px;border:1px solid #B9C4D0;color:#6E7787}
.unchecked{display:flex;align-items:center;gap:12px;margin-top:13px;padding:11px 13px;border:1px dashed #C9BFA8;border-radius:3px;background:#F4EFE1}
.unchecked span{font:400 13.5px/1.6 Inter,sans-serif;color:#6E7787;text-wrap:pretty}
.unchecked b{color:#3A4557;font-weight:400}
.acts{display:flex;align-items:center;gap:10px;margin-top:16px}
.card .acts{margin-top:14px;gap:12px}
.btn{padding:7px 13px;border:1px solid #E0D8C4;background:transparent;border-radius:3px;color:#D6482B;font:500 11px/1 'JetBrains Mono',monospace;letter-spacing:.06em;cursor:pointer}
.btn:hover{border-color:#D6482B}
.btn-fetch{flex:none;margin-left:auto;background:#FFFDF8;border-color:#D5CDB9}
.btn-q{padding:7px 13px;border:1px solid transparent;background:transparent;border-radius:3px;color:#8A93A1;font:400 11px/1 'JetBrains Mono',monospace;letter-spacing:.06em;cursor:pointer}
.btn-q:hover{color:#4C5768}
.btn-hide{margin-left:auto;color:#9AA3AE}
.fold{display:flex;align-items:center;gap:14px;margin-top:4px}
.fold span{flex:none;font:400 10.5px/1 'JetBrains Mono',monospace;color:#8A93A1;letter-spacing:.1em}
.fold i{flex:1;height:1px;background:#DED5C1}
.shelf{margin-top:34px}
.shelf-h{display:flex;align-items:baseline;gap:14px;padding-bottom:12px;border-bottom:1px solid #E0D8C4}
.shelf-t{font:600 26px/1.2 Caveat,cursive;color:#2E7D5B}
.shelf-m{margin-left:auto;font:400 10.5px/1 'JetBrains Mono',monospace;color:#8A93A1;letter-spacing:.1em}
.tiles{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:16px}
.tile{background:#F4EFE1;border:1px solid #E0D8C4;border-radius:3px;padding:13px 15px}
.tile-n{font:500 14.5px/1.3 Inter,sans-serif;color:#3A4557}
.tile-r{font:400 13px/1.55 Inter,sans-serif;color:#8A93A1;margin-top:5px}
.quiet{background:#FFFDF8;border:1px solid #E0D8C4;border-radius:4px;padding:24px 26px;margin-bottom:4px}
.quiet-t{font:600 26px/1.2 Caveat,cursive;color:#2A3342}
.quiet-b{font:400 14.5px/1.65 Inter,sans-serif;color:#4C5768;margin-top:8px;max-width:52ch;text-wrap:pretty}
.scrim{position:absolute;inset:0;background:rgba(42,51,66,.26)}
.shell{position:fixed;inset:0;z-index:60;display:flex;justify-content:flex-end}
.panel{position:relative;width:min(560px,94vw);height:100vh;overflow:auto;overscroll-behavior:contain;background:#FFFDF8;border-left:1px solid #CBBFA5;padding:28px 32px 32px;box-shadow:-18px 0 40px -26px rgba(42,51,66,.55)}
.crumb{display:flex;align-items:center;gap:12px;font:500 10.5px/1 'JetBrains Mono',monospace;color:#6E7787;letter-spacing:.1em}
.esc{margin-left:auto;padding:5px 9px;border:1px solid #E0D8C4;background:transparent;border-radius:3px;color:#8A93A1;font:400 11px/1 'JetBrains Mono',monospace;cursor:pointer}
.dtitle{font:500 24px/1.25 Inter,sans-serif;color:#1F2937;letter-spacing:-.02em;margin-top:16px}
.dmeta{font:400 11.5px/1.75 'JetBrains Mono',monospace;color:#6E7787;letter-spacing:.05em;margin-top:8px}
.tabs{display:flex;flex-wrap:wrap;gap:7px;margin-top:18px;padding-bottom:14px;border-bottom:1px solid #EBE3D2}
.tab{padding:5px 11px;border:1px solid #E0D8C4;background:transparent;border-radius:3px;color:#6E7787;font:400 11.5px/1.3 Inter,sans-serif;cursor:pointer}
.tab:hover{border-color:#CBBFA5;color:#3A4557}
.tab-on{border-color:#2E7D5B;background:#EAF2ED;color:#215E44;font-weight:500}
.dband{background:#F4EFE1;border:1px solid #E0D8C4;border-radius:3px;padding:15px 16px;display:flex;gap:13px;align-items:flex-start;margin-top:18px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:22px;margin-top:24px}
.gh{font:500 9.5px/1 'JetBrains Mono',monospace;color:#6E7787;letter-spacing:.11em;padding-bottom:10px}
.gh-m{border-bottom:1px solid #2E7D5B}
.gh-g{border-bottom:1px dashed #C9BFA8}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin-top:12px}
.chip{font:400 12.5px/1.3 Inter,sans-serif;padding:5px 10px;border-radius:2px;white-space:nowrap}
.chip-m{background:#EAF2ED;border:1px solid #C3DACD;color:#215E44}
.chip-g{background:transparent;border:1px dashed #C9BFA8;color:#4C5768}
.gnote{font:400 12.5px/1.6 Inter,sans-serif;color:#8A93A1;margin-top:12px;text-wrap:pretty}
.dsec{font:600 22px/1.2 Caveat,cursive;color:#2E7D5B;margin-top:26px;padding-bottom:10px;border-bottom:1px solid #EBE3D2}
.dsec-b{font:400 13.5px/1.65 Inter,sans-serif;color:#4C5768;margin-top:12px;text-wrap:pretty}
.foot{display:flex;align-items:center;gap:10px;margin-top:26px;padding-top:18px;border-top:1px solid #EBE3D2}
.btn-p{padding:8px 15px;border:1px solid #D6482B;background:#D6482B;border-radius:3px;color:#FFFDF8;font:500 11px/1 'JetBrains Mono',monospace;letter-spacing:.06em;cursor:pointer}
.btn-p:hover{background:#A83519;border-color:#A83519}
.btn-s{padding:8px 15px;border:1px solid #D5CDB9;background:transparent;border-radius:3px;color:#6E7787;font:500 11px/1 'JetBrains Mono',monospace;letter-spacing:.06em;cursor:pointer}
.btn-s:hover{border-color:#2E7D5B;color:#2E7D5B}
.btn-n{margin-left:auto;border:0;background:transparent;color:#8A93A1;font:400 11px/1 'JetBrains Mono',monospace;letter-spacing:.06em;cursor:pointer}
.btn-n:hover{color:#3A4557}
.hidden{display:none}
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
    bits = [role.get("location") or "", f"POSTED {_days_ago(role.get('date'))}"
            if _days_ago(role.get("date")) else "", role.get("salary") or ""]
    if not role.get("description_captured"):
        bits.append("NO DESCRIPTION CAPTURED")
    return " · ".join(b for b in bits if b).upper()


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
    """Rule 3 — its own state, never a weak band."""
    return (
        '<div class="unchecked"><span><b>Not checked yet.</b> '
        f'{_e(_sentence(role.get("reason")))}</span>'
        '<button type="button" class="btn btn-fetch">FETCH POSTING</button></div>'
    )


def _fit_block(role: dict, lead: bool) -> str:
    if not role.get("description_captured"):
        return _unchecked_block(role)
    pill = _band_pill(role)
    reason = _e(role.get("reason") or "")
    if not pill or not reason:
        # Rule 2 — rather than show a band alone, show neither.
        return ""
    return f'<div class="brow">{pill}<span class="reason">{reason}</span></div>'


def _actions(company_key: str, watchable: bool = True) -> str:
    watch = ('<button type="button" class="btn-q">WATCH</button>'
             if watchable else "")
    return (
        f'<div class="acts">'
        f'<button type="button" class="btn" data-open="{_e(company_key)}">REVIEW ROLE</button>'
        f'{watch}'
        f'<button type="button" class="btn-q btn-hide">HIDE</button></div>'
    )


def _lead_card(m: dict, key: str) -> str:
    role = m["roles"][0]
    n = len(m["roles"])
    noun = "ROLE" if n == 1 else "ROLES"
    return (
        f'<div class="lead"><div class="crow">'
        f'<div class="cname">{_e(m["name"])}</div>'
        f'<div class="cmeta">{n} {noun} OPEN</div></div>'
        f'<div class="cwhy">{_e(m["why"])}</div>'
        f'<hr class="rule">'
        f'<div class="rtitle">{_e(role.get("title"))}</div>'
        f'<div class="rmeta">{_e(_role_meta(role))}</div>'
        f'{_fit_block(role, True)}'
        f'{_actions(key)}</div>'
    )


def _compact_card(m: dict, key: str) -> str:
    role = m["roles"][0]
    n = len(m["roles"])
    noun = "ROLE" if n == 1 else "ROLES"
    tag = "NEW TO YOU · " if m.get("state") == "DISCOVER" else ""
    age = _days_ago(role.get("date"))
    meta = f'{tag}{n} {noun}' + (f' · {age}' if age else "")
    return (
        f'<div class="card"><div class="crow">'
        f'<div class="cname">{_e(m["name"])}</div>'
        f'<div class="cmeta">{_e(meta.upper())}</div></div>'
        f'<div class="cwhy">{_e(m["why"])}</div>'
        f'{_fit_block(role, False)}'
        f'{_actions(key)}</div>'
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
    fetch = (f'<button type="button" class="btn">FETCH {unchecked} MISSING '
             f'DESCRIPTIONS</button>' if unchecked else "")
    return (
        '<div class="quiet"><div class="quiet-t">nothing to apply to today</div>'
        f'<div class="quiet-b">{open_count} postings came in; none named enough '
        'of your stack to earn the top of the list. That is the check working, '
        'not a dry spell.</div>'
        f'<div class="acts">{fetch}'
        '<button type="button" class="btn-q">WIDEN SOURCES</button></div></div>'
    )


def _drawer_payload(maps: list[dict]) -> dict:
    """Data the drawer needs. The internal score is deliberately excluded."""
    out: dict = {}
    for i, m in enumerate(maps):
        if not m.get("roles"):
            continue
        out[f"c{i}"] = {
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
            } for r in m["roles"]],
        }
    return out


_JS = """
const DATA = __DATA__;
let openKey = null, roleIdx = 0;
const shell = document.getElementById('shell');
function pillClass(b){return b==='STRONG FIT'?'pill-strong':b==='PARTIAL FIT'?'pill-partial':'pill-stretch';}
function esc(s){const d=document.createElement('div');d.textContent=s==null?'':s;return d.innerHTML;}
function render(){
  const co = DATA[openKey]; if(!co){return;}
  const r = co.roles[roleIdx]; const many = co.roles.length > 1;
  const tabs = many ? '<div class="tabs">' + co.roles.map((x,i)=>
    '<button type="button" class="tab '+(i===roleIdx?'tab-on':'')+'" data-i="'+i+'">'+esc(x.tab)+'</button>').join('') + '</div>' : '';
  const fit = !r.captured
    ? '<div class="unchecked"><span><b>Not checked yet.</b> '+esc(r.reason)+'</span>'
      + '<button type="button" class="btn btn-fetch">FETCH POSTING</button></div>'
    : '<div class="dband"><span class="pill '+pillClass(r.band)+'">'+esc(r.band)+'</span>'
      + '<span class="reason">'+esc(r.reason)+'</span></div>';
  const chips = (a,c)=>a.length? a.map(x=>'<span class="chip '+c+'">'+esc(x)+'</span>').join('') : '<span class="gnote">none</span>';
  const grid = r.captured ? '<div class="grid"><div><div class="gh gh-m">MATCHED FROM YOUR RESUME</div>'
      + '<div class="chips">'+chips(r.matched,'chip-m')+'</div></div>'
      + '<div><div class="gh gh-g">IN THE POST, NOT ON YOUR RESUME</div>'
      + '<div class="chips">'+chips(r.gaps,'chip-g')+'</div>'
      + (r.gaps.length?'<div class="gnote">Named in the posting, not found on your resume. Not a rejection — worth a line in the cover letter.</div>':'')
      + '</div></div>' : '';
  const nextLabel = roleIdx < co.roles.length-1 ? 'NEXT ROLE HERE \\u2192' : 'BACK TO MAP \\u2192';
  shell.innerHTML = '<div class="scrim" data-close="1"></div><div class="panel">'
    + '<div class="crumb">'+esc(co.name.toUpperCase())+' \\u00b7 ROLE '+(roleIdx+1)+' OF '+co.roles.length
    + '<button type="button" class="esc" data-close="1">ESC</button></div>'
    + '<div class="dtitle">'+esc(r.title)+'</div>'
    + '<div class="dmeta">'+esc(r.meta)+'</div>'
    + tabs + fit + grid
    + '<div class="dsec">why this company</div><div class="dsec-b">'+esc(co.why)+'</div>'
    + '<div class="foot"><a class="btn-p" href="'+esc(r.url)+'" target="_blank" rel="noopener">OPEN POSTING \\u2197</a>'
    + '<button type="button" class="btn-s">MARK APPLIED</button>'
    + '<button type="button" class="btn-n" data-next="1">'+nextLabel+'</button></div></div>';
  shell.classList.remove('hidden');
}
function close(){shell.classList.add('hidden');shell.innerHTML='';openKey=null;document.body.style.overflow='';}
document.addEventListener('click',function(e){
  const o=e.target.closest('[data-open]');
  if(o){openKey=o.getAttribute('data-open');roleIdx=0;document.body.style.overflow='hidden';render();return;}
  if(e.target.closest('[data-close]')){close();return;}
  const t=e.target.closest('.tab'); if(t){roleIdx=parseInt(t.getAttribute('data-i'),10);render();return;}
  const n=e.target.closest('[data-next]');
  if(n){const co=DATA[openKey]; if(roleIdx<co.roles.length-1){roleIdx++;render();}else{close();}}
});
document.addEventListener('keydown',function(e){if(e.key==='Escape'&&openKey){close();}});
"""


def render(maps: list[dict], meta: dict | None = None) -> str:
    """Build the full opportunity map page."""
    meta = meta or {}
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

    visible = listed[:_LEAD_VISIBLE]
    for i, m in enumerate(visible):
        if not m.get("roles"):
            continue
        key = keys[id(m)]
        body.append(_lead_card(m, key) if i == 0 and act_now
                    else _compact_card(m, key))

    remaining = len(listed) - len(visible)
    if remaining > 0:
        noun = "COMPANY" if remaining == 1 else "COMPANIES"
        body.append(f'<div class="fold"><i></i><span>{remaining} MORE {noun} '
                    f'WITH OPEN ROLES</span><i></i></div>')

    n_co = meta.get("companies", len(maps))
    n_ro = meta.get("roles", sum(len(m.get("roles") or []) for m in maps))
    scraped = meta.get("scraped") or datetime.now().strftime("%H:%M")

    payload = json.dumps(_drawer_payload(maps), ensure_ascii=False)
    payload = payload.replace("</", "<\\/")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Opportunity map</title>
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
<div class="title">today</div>
<div class="sub">Companies worth twenty minutes. Everything below them is here for a reason you can read.</div>
</div>
<div class="meta-r">
<div class="meta-1">{n_co} COMPANIES &middot; {n_ro} ROLES</div>
<div class="meta-2">SCRAPED {_e(scraped)}</div>
</div>
</div></div>
<div class="wrap"><div class="col">
{"".join(body)}
{_watch_shelf(watching)}
</div></div>
</div>
<div id="shell" class="shell hidden"></div>
<script>{_JS.replace("__DATA__", payload)}</script>
</body>
</html>
"""
