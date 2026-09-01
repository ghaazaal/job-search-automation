"""Renders the profile page.

The design handoff's fourth surface: what the daily search looks for —
resumes, scope, match rules, watchlist — and the visible half of
"nothing is filtered silently". Same paper shell as the map and the
tracker, same 820px measure as the map.

Every fact on the page comes from the store. Claims the app cannot make
(a run schedule it does not own, a "checked daily" cadence, a reject-log
page that does not exist) are omitted rather than hardcoded — a label
that drifts from reality is worse than silence.
"""
import json
from datetime import datetime
from html import escape

from .shell import SHELL_CSS, shell_nav

_CSS = """
*{box-sizing:border-box}
html,body{margin:0;background:#F7F2E6}
body{font-family:Inter,system-ui,sans-serif;color:#2A3342;-webkit-font-smoothing:antialiased}
a{color:#D6482B;text-decoration:none}
a:hover{color:#A83519}
::selection{background:rgba(46,125,91,.18)}
.page{min-height:100vh;background:#F7F2E6;background-image:radial-gradient(rgba(42,51,66,.14) 1px,transparent 1px);background-size:22px 22px;background-position:11px 11px;padding:0 0 90px}
.head{display:flex;justify-content:center;padding:30px 40px 28px}
.head-in{flex:1;max-width:820px}
.title{font:600 42px/1 Caveat,cursive;color:#D6482B}
.sub{font:400 15px/1.6 Inter,sans-serif;color:#4C5768;margin-top:9px;max-width:52ch;text-wrap:pretty}
.wrap{display:flex;justify-content:center;padding:0 40px}
.col{flex:1;max-width:820px;display:flex;flex-direction:column;gap:16px;min-width:0}
.card{background:#FFFDF8;border:1px solid #E0D8C4;border-radius:4px;padding:18px 20px 20px}
.card.em{border-color:#CBBFA5;padding:20px 24px 22px}
.card.sunk{background:#F4EFE1;padding:18px 20px}
.lab-row{display:flex;align-items:baseline;justify-content:space-between;gap:12px}
.lab{font:500 10.5px/1 'JetBrains Mono',monospace;color:#6E7787;letter-spacing:.11em}
.lab-m{font:400 10.5px/1 'JetBrains Mono',monospace;color:#A6AEB9;letter-spacing:.1em}
.rlist{display:flex;flex-direction:column;gap:10px;margin-top:14px}
.ritem{border:1px solid #E0D8C4;border-left:3px solid #E0D8C4;border-radius:3px;padding:13px 15px;display:flex;align-items:center;gap:14px}
.ritem.on{border-left-color:#2E7D5B}
.ritem.off{opacity:.65}
.rbody{min-width:0}
.rname{font:500 16px/1.3 Inter,sans-serif;color:#1F2937}
.rmeta{font:400 10.5px/1 'JetBrains Mono',monospace;color:#8A93A1;letter-spacing:.08em;margin-top:7px}
.racts{margin-left:auto;flex:none;display:flex;gap:6px}
.btn-o{padding:7px 11px;border:1px solid #E0D8C4;background:transparent;border-radius:2px;color:#4C5768;font:400 10.5px/1 'JetBrains Mono',monospace;letter-spacing:.07em;white-space:nowrap;cursor:pointer;text-decoration:none}
.btn-o:hover{border-color:#CBBFA5;color:#4C5768}
.btn-g{padding:7px 11px;border:1px solid transparent;background:transparent;border-radius:2px;color:#9AA3AE;font:400 10.5px/1 'JetBrains Mono',monospace;letter-spacing:.07em;white-space:nowrap;cursor:pointer}
.btn-g:hover{color:#A83519}
.foot{display:flex;align-items:center;gap:10px;margin-top:18px;padding-top:16px;border-top:1px solid #EBE3D2}
.btn-p{display:inline-block;padding:10px 16px;border:1px solid #D6482B;background:#D6482B;border-radius:3px;color:#FFFDF8;font:500 11.5px/1 'JetBrains Mono',monospace;letter-spacing:.07em;white-space:nowrap;cursor:pointer;text-decoration:none}
.btn-p:hover{background:#A83519;border-color:#A83519;color:#FFFDF8}
.btn-s{padding:10px 15px;border:1px solid #D5CDB9;background:transparent;border-radius:3px;color:#4C5768;font:400 11.5px/1 'JetBrains Mono',monospace;letter-spacing:.07em;white-space:nowrap;cursor:pointer}
.btn-s:hover{border-color:#2E7D5B;color:#2E7D5B}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.gline{font:400 15px/1.6 Inter,sans-serif;color:#3A4557;margin-top:11px}
.chips{display:flex;flex-wrap:wrap;gap:7px;margin-top:13px}
.chip{display:inline-block;padding:5px 10px;border-radius:2px;font:400 12.5px/1.2 Inter,sans-serif;white-space:nowrap}
.chip-m{background:#EAF2ED;border:1px solid #C3DACD;color:#215E44}
.chip-d{background:transparent;border:1px dashed #C9BFA8;color:#4C5768}
.note{font:400 13px/1.6 Inter,sans-serif;color:#8A93A1;margin-top:12px;text-wrap:pretty}
.note a{color:#D6482B}
.wl{display:flex;flex-direction:column;gap:2px;margin-top:6px}
.wrow{display:flex;align-items:center;gap:14px;padding:12px 2px;border-bottom:1px solid #F0EADB}
.wname{font:500 15.5px/1.3 Inter,sans-serif;color:#1F2937}
.wmeta{margin-left:auto;flex:none;font:400 10.5px/1 'JetBrains Mono',monospace;color:#8A93A1;letter-spacing:.08em}
.btn-add{margin-top:14px;padding:9px 14px;border:1px dashed #C9BFA8;background:transparent;border-radius:3px;color:#D6482B;font:500 11px/1 'JetBrains Mono',monospace;letter-spacing:.07em;white-space:nowrap;cursor:pointer}
.btn-add:hover{border-color:#D6482B}
.wform{display:none;margin-top:12px;gap:8px;flex-wrap:wrap}
.wform.open{display:flex}
.wform input{flex:1;min-width:150px;padding:9px 11px;border:1px solid #E0D8C4;border-radius:3px;background:#FFFDF8;font:400 13.5px/1.4 Inter,sans-serif;color:#2A3342}
.wform input:focus{outline:0;border-color:#2E7D5B}
.sunk-t{font:600 24px/1 Caveat,cursive;color:#2E7D5B}
.sunk-b{font:400 14px/1.7 Inter,sans-serif;color:#4C5768;margin-top:9px;max-width:64ch;text-wrap:pretty}
.msg{font:400 13px/1.6 Inter,sans-serif;color:#8A93A1}
.msg.err{color:#A83519}
"""

_JS = """
const RESUMES = __RESUMES__;

async function post(url, body){
  const r = await fetch(url, {method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify(body)});
  if(r.ok) return null;
  const data = await r.json().catch(function(){return {};});
  return data.error || 'That did not save.';
}
async function startRun(){
  const r = await fetch('/api/runs', {method:'POST'});
  const body = await r.json();
  if(body.run_id){ window.location = '/searching/' + body.run_id; }
  else { alert(body.error || 'Could not start a search.'); }
}
document.addEventListener('click', async function(e){
  const t = e.target.closest('[data-toggle]');
  if(t){
    // The update endpoint overwrites everything the confirm screen owns,
    // so the pause toggle must send the resume back whole — sending only
    // the flag would wipe its roles and skills.
    const r = RESUMES[t.dataset.toggle];
    if(!r) return;
    const err = await post('/api/resumes/' + t.dataset.toggle, {
      label: r.label, target_roles: r.target_roles, skills: r.skills,
      seniority: r.seniority, is_active: !r.is_active});
    if(err){ alert(err); } else { location.reload(); }
    return;
  }
  const d = e.target.closest('[data-delete]');
  if(d){
    if(!confirm('Delete this resume? Roles it already scored keep their scores.')) return;
    const r = await fetch('/api/resumes/' + d.dataset.delete, {method:'DELETE'});
    if(r.ok){ location.reload(); } else { alert('That did not delete.'); }
    return;
  }
  const u = e.target.closest('[data-unwatch]');
  if(u){
    const r = await fetch('/api/watchlist/' + u.dataset.unwatch, {method:'DELETE'});
    if(r.ok){ location.reload(); }
    return;
  }
  if(e.target.id === 'w-toggle'){
    document.getElementById('w-form').classList.toggle('open');
    return;
  }
  const sg = e.target.closest('[data-suggest]');
  if(sg){
    const err = await post('/api/watchlist', {
      name: sg.dataset.suggest, domain: sg.dataset.suggestDomain,
      linkedin_url: ''});
    if(err){ alert(err); } else { location.reload(); }
    return;
  }
  if(e.target.id === 'w-add'){
    const err = await post('/api/watchlist', {
      name: document.getElementById('w-name').value,
      domain: document.getElementById('w-domain').value,
      linkedin_url: document.getElementById('w-url').value});
    if(err){ alert(err); } else { location.reload(); }
  }
  if(e.target.id === 'run-now'){ startRun(); }
});
"""


def _e(value) -> str:
    return escape(str(value or ""), quote=True)


def _payload(value) -> str:
    return json.dumps(value, ensure_ascii=False).replace("</", "<\\/")


def _added(created_at) -> str:
    try:
        d = datetime.fromisoformat(str(created_at).replace("Z", ""))
        return d.strftime("ADDED %b %Y").upper()
    except (ValueError, TypeError):
        return ""


def _resume_row(resume: dict) -> str:
    active = bool(resume.get("is_active"))
    roles = len(resume.get("target_roles") or [])
    skills = len(resume.get("skills") or [])
    noun = "TARGET ROLE" if roles == 1 else "TARGET ROLES"
    snoun = "SKILL" if skills == 1 else "SKILLS"
    bits = [f"{roles} {noun}", f"{skills} {snoun}",
            (resume.get("seniority") or "unset").upper()]
    added = _added(resume.get("created_at"))
    if added:
        bits.append(added)
    if not active:
        bits.append("PAUSED")
    rid = int(resume["id"])
    return (
        f'<div class="ritem{" on" if active else " off"}">'
        f'<div class="rbody"><div class="rname">{_e(resume["label"])}</div>'
        f'<div class="rmeta">{" &middot; ".join(bits)}</div></div>'
        f'<div class="racts">'
        f'<a class="btn-o" href="/setup/confirm/{rid}">EDIT</a>'
        f'<button type="button" class="btn-g" data-toggle="{rid}">'
        f'{"PAUSE" if active else "RESUME"}</button>'
        f'<button type="button" class="btn-g" data-delete="{rid}">DELETE</button>'
        f'</div></div>'
    )


def _resumes_card(resumes: list[dict], can_search: bool) -> str:
    n_active = sum(1 for r in resumes if r.get("is_active"))
    n_paused = len(resumes) - n_active
    meta = f"{n_active} ACTIVE"
    if n_paused:
        meta += f" &middot; {n_paused} PAUSED"
    listing = (f'<div class="rlist">'
               f'{"".join(_resume_row(r) for r in resumes)}</div>'
               if resumes else
               '<div class="note">No resumes yet — the search has nothing '
               'to look for until one is in.</div>')
    search = ('<button type="button" class="btn-s" id="run-now">'
              'RUN THE SEARCH NOW</button>' if can_search else "")
    return (
        f'<div class="card em"><div class="lab-row">'
        f'<span class="lab">YOUR RESUMES</span>'
        f'<span class="lab-m">{meta}</span></div>'
        f'{listing}'
        f'<div class="foot"><a class="btn-p" href="/setup">ADD A RESUME</a>'
        f'{search}</div></div>'
    )


def _where_card(profile: dict, resumes: list[dict]) -> str:
    if profile.get("setup_complete"):
        where = profile.get("location") or "not set"
        modes = profile.get("work_modes") or []
        line = _e(where)
        if modes:
            line += f' &middot; {_e(" or ".join(modes))}'
        chips = "".join(f'<span class="chip chip-m">{_e(m)}</span>'
                        for m in modes)
        country = (profile.get("country") or "").upper()
        if country:
            chips += f'<span class="chip chip-d">country: {_e(country)}</span>'
        body = (f'<div class="gline">{line}</div>'
                f'<div class="chips">{chips}</div>')
    else:
        fix = (f"/setup/confirm/{int(resumes[0]['id'])}" if resumes
               else "/setup")
        body = (f'<div class="note">Not set. <a href="{fix}">Add it</a> '
                'before searching.</div>')
    return (f'<div class="card"><span class="lab">WHERE YOU ARE LOOKING'
            f'</span>{body}</div>')


def _match_card(resumes: list[dict]) -> str:
    """Skills from the ACTIVE resumes — the same set the scorer reads.
    Core skills use the matched-chip style, working skills the dashed one,
    mirroring how the drawer draws evidence."""
    seen: dict[str, str] = {}      # lower-cased name -> tier
    display: dict[str, str] = {}   # lower-cased name -> first-seen casing
    for r in resumes:
        if not r.get("is_active"):
            continue
        for s in r.get("skills") or []:
            name = (s.get("name") or "").strip()
            if not name:
                continue
            key = name.lower()
            display.setdefault(key, name)
            # core wins over working when two resumes disagree
            if seen.get(key) != "core":
                seen[key] = s.get("tier") or "working"
    core = [display[k] for k, tier in seen.items() if tier == "core"]
    working = [display[k] for k, tier in seen.items() if tier != "core"]
    if not core and not working:
        body = ('<div class="note">No skills yet — they come from your '
                'active resumes.</div>')
    else:
        chips = "".join(f'<span class="chip chip-m">{_e(s)}</span>'
                        for s in core)
        chips += "".join(f'<span class="chip chip-d">{_e(s)}</span>'
                         for s in working)
        body = (f'<div class="chips">{chips}</div>'
                '<div class="note">These come from your active resumes. A '
                'posting must name them in its own description before any '
                'fit is claimed.</div>')
    return (f'<div class="card"><span class="lab">WHAT COUNTS AS A MATCH'
            f'</span>{body}</div>')


# Remote-first companies known to hire globally — market facts, offered
# as one-click adds and never pre-added. This list describes companies,
# not the user, so it may live in code.
_SUGGESTIONS = [
    ("GitLab", "gitlab.com"), ("Supabase", "supabase.com"),
    ("Wikimedia", "wikimedia.org"), ("Zapier", "zapier.com"),
    ("Deel", "deel.com"), ("Remote.com", "remote.com"),
    ("PostHog", "posthog.com"), ("Buffer", "buffer.com"),
    ("Doist", "doist.com"),
]


def _watch_row(row: dict) -> str:
    state = (row.get("resolution") or "unresolved").upper()
    meta = state
    yield_n = row.get("last_yield_count")
    if yield_n is not None:
        meta += f" &middot; {int(yield_n)} LAST FETCH"
    note = row.get("resolution_note")
    if state == "UNRESOLVED" and note:
        meta += f" &middot; {_e(note)}"
    return (
        f'<div class="wrow"><span class="wname">{_e(row["company_name"])}'
        f'</span><span class="wmeta">{meta}</span>'
        f'<button type="button" class="btn-g" data-unwatch="{int(row["id"])}">'
        f'REMOVE</button></div>'
    )


def _watchlist_card(watched: list[dict]) -> str:
    """The companies this user watches. Watching changes where we search,
    not what qualifies as a job — this card manages fetch targets,
    nothing about scoring."""
    n = len(watched)
    noun = "COMPANY" if n == 1 else "COMPANIES"
    listing = (f'<div class="wl">{"".join(_watch_row(w) for w in watched)}'
               f'</div>' if watched else
               '<div class="note">No companies watched yet.</div>')
    form = (
        '<div class="wform" id="w-form">'
        '<input id="w-name" placeholder="Company name">'
        '<input id="w-domain" placeholder="domain (optional)">'
        '<input id="w-url" placeholder="LinkedIn company URL (optional)">'
        '<button type="button" class="btn-s" id="w-add">WATCH</button>'
        '</div>')
    already = {w["company_name"].strip().lower() for w in watched}
    chips = "".join(
        f'<button type="button" class="chip chip-d" style="cursor:pointer" '
        f'data-suggest="{_e(name)}" data-suggest-domain="{_e(domain)}">'
        f'{_e(name)}</button>'
        for name, domain in _SUGGESTIONS
        if name.lower() not in already)
    suggest = (f'<div class="note">Suggestions:</div>'
               f'<div class="chips">{chips}</div>' if chips else "")
    return (
        f'<div class="card"><div class="lab-row" style="padding-bottom:11px;'
        f'border-bottom:1px solid #EBE3D2">'
        f'<span class="lab">YOUR WATCHLIST</span>'
        f'<span class="lab-m">{n} {noun}</span></div>'
        f'{listing}'
        f'<button type="button" class="btn-add" id="w-toggle">'
        f'+ ADD A COMPANY</button>{form}{suggest}</div>'
    )


def _filtered_card(filtered: dict) -> str:
    """The visible half of "nothing is filtered silently"."""
    closed = filtered.get("closed") or 0
    unverified = filtered.get("unverified") or 0
    offtopic = filtered.get("offtopic") or 0
    if not (closed or unverified or offtopic):
        body = ("Nothing has been filtered out yet — after a search, the "
                "count of postings set aside (and why) appears here and in "
                "the map header.")
    else:
        clauses = [f"{closed} postings are not open to someone hiring from "
                   f"where you are" if closed else "",
                   f"{unverified} could not be verified either way"
                   if unverified else "",
                   f"{offtopic} were not one of your target roles"
                   if offtopic else ""]
        joined = ", ".join(c for c in clauses if c)
        body = (f"Right now: {joined}. The map header carries the same "
                "counts — nothing is dropped silently.")
    return (
        f'<div class="card sunk"><div class="sunk-t">what got filtered out'
        f'</div><div class="sunk-b">{body}</div></div>'
    )


def render(resumes: list[dict], profile: dict,
           watched: list[dict] | None = None,
           filtered: dict | None = None,
           nav: dict | None = None) -> str:
    """One person, many resumes. Each active one adds its roles to the search."""
    nav = nav or {}
    watched = watched or []
    can_search = bool(resumes and profile.get("setup_complete")
                      and any(r.get("is_active") for r in resumes))

    body = (
        _resumes_card(resumes, can_search)
        + f'<div class="grid2">{_where_card(profile, resumes)}'
        + f'{_match_card(resumes)}</div>'
        + _watchlist_card(watched)
        + _filtered_card(filtered or {})
    )

    slim = {str(int(r["id"])): {
        "label": r.get("label"), "target_roles": r.get("target_roles") or [],
        "skills": r.get("skills") or [], "seniority": r.get("seniority") or "mid",
        "is_active": bool(r.get("is_active"))} for r in resumes}
    js = _JS.replace("__RESUMES__", _payload(slim))

    top_nav = shell_nav("/profile",
                        counts={"/": nav.get("map_count"),
                                "/activity": nav.get("tracker_count")},
                        user_label=nav.get("user_label") or "")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Your profile</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Caveat:wght@500;600&family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">
<style>{_CSS}{SHELL_CSS}</style>
</head>
<body>
<div class="page">
{top_nav}
<div class="head"><div class="head-in">
<div class="title">your profile</div>
<div class="sub">One person, many resumes. Each active resume adds its target roles to the next search.</div>
</div></div>
<div class="wrap"><div class="col">{body}</div></div>
</div>
<script>{js}</script>
</body>
</html>
"""
