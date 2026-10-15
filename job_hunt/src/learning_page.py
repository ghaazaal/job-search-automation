"""Renders the LEARN page: the market, your gaps, and one learning path.

Same paper shell and 820px measure as the profile page. Every number on
the page is a count of stored postings; the scorer's weights never appear
(CLAUDE.md: no bare numbers). Every skill claim opens onto the postings'
own words, and every "you have this" onto the resume's.
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
.page{min-height:100vh;background:#F7F2E6;background-image:radial-gradient(rgba(42,51,66,.14) 1px,transparent 1px);background-size:22px 22px;background-position:11px 11px;padding:0 0 90px}
.head{display:flex;justify-content:center;padding:30px 40px 28px}
.head-in{flex:1;max-width:820px}
.title{font:600 42px/1 Caveat,cursive;color:#D6482B}
.sub{font:400 15px/1.6 Inter,sans-serif;color:#4C5768;margin-top:9px;max-width:60ch;text-wrap:pretty}
.wrap{display:flex;justify-content:center;padding:0 40px}
.col{flex:1;max-width:820px;display:flex;flex-direction:column;gap:16px;min-width:0}
.card{background:#FFFDF8;border:1px solid #E0D8C4;border-radius:4px;padding:18px 20px 20px}
.card.em{border-color:#CBBFA5;padding:20px 24px 22px}
.card.sunk{background:#F4EFE1;padding:18px 20px}
.card.err{border-color:#E3B4A6;background:#FBF1EC}
.lab-row{display:flex;align-items:baseline;justify-content:space-between;gap:12px;flex-wrap:wrap}
.lab{font:500 10.5px/1 'JetBrains Mono',monospace;color:#6E7787;letter-spacing:.11em}
.lab-m{font:400 10.5px/1 'JetBrains Mono',monospace;color:#A6AEB9;letter-spacing:.1em}
.lead{font:400 16px/1.65 Inter,sans-serif;color:#2A3342;margin-top:12px;text-wrap:pretty}
.gline{font:400 14.5px/1.6 Inter,sans-serif;color:#3A4557;margin-top:10px;text-wrap:pretty}
.note{font:400 13px/1.6 Inter,sans-serif;color:#8A93A1;margin-top:10px;text-wrap:pretty}
.foot{display:flex;align-items:center;gap:12px;margin-top:16px;padding-top:14px;border-top:1px solid #EBE3D2;flex-wrap:wrap}
.btn-p{display:inline-block;padding:10px 16px;border:1px solid #D6482B;background:#D6482B;border-radius:3px;color:#FFFDF8;font:500 11.5px/1 'JetBrains Mono',monospace;letter-spacing:.07em;white-space:nowrap;cursor:pointer}
.btn-p:hover{background:#A83519;border-color:#A83519}
.btn-p[disabled]{opacity:.5;cursor:default}
.msg{font:400 13px/1.5 Inter,sans-serif;color:#8A93A1}
.msg.err{color:#A83519}
.stage{display:flex;gap:18px}
.snum{flex:none;width:34px;height:34px;border-radius:50%;border:1.5px solid #D6482B;color:#D6482B;font:600 22px/31px Caveat,cursive;text-align:center}
.sbody{flex:1;min-width:0}
.stitle{font:600 26px/1.1 Caveat,cursive;color:#1F2937}
.effort{font:400 10px/1 'JetBrains Mono',monospace;color:#8A93A1;letter-spacing:.1em;border:1px solid #E0D8C4;border-radius:2px;padding:4px 7px;white-space:nowrap}
.skill{margin-top:12px;padding:10px 12px;border-left:3px solid #D6482B;background:#FBF7EE;border-radius:2px}
.skill.adj{border-left-color:#2E7D5B}
.sname{font:500 15px/1.3 Inter,sans-serif;color:#1F2937}
.why{font:400 13px/1.55 Inter,sans-serif;color:#4C5768;margin-top:4px}
.sec{font:500 10px/1 'JetBrains Mono',monospace;color:#8A93A1;letter-spacing:.11em;margin-top:14px}
ul.topics{margin:6px 0 0;padding-left:18px;font:400 14px/1.6 Inter,sans-serif;color:#3A4557}
.para{font:400 14px/1.6 Inter,sans-serif;color:#3A4557;margin-top:5px;text-wrap:pretty}
table.mk{width:100%;border-collapse:collapse;margin-top:12px}
.mk td,.mk th{padding:8px 6px;border-bottom:1px solid #F0EADB;text-align:left;vertical-align:top}
.mk th{font:500 10px/1 'JetBrains Mono',monospace;color:#8A93A1;letter-spacing:.1em}
.mk td{font:400 14px/1.4 Inter,sans-serif;color:#2A3342}
.mk .n{font:400 12px/1.4 'JetBrains Mono',monospace;color:#4C5768;white-space:nowrap}
.bar{height:6px;background:#EFE8D8;border-radius:3px;min-width:60px;margin-top:6px}
.bar i{display:block;height:6px;background:#3B7EA8;border-radius:3px}
.chip{display:inline-block;padding:4px 8px;border-radius:2px;font:400 12px/1.2 Inter,sans-serif;white-space:nowrap}
.c-have{background:#EAF2ED;border:1px solid #C3DACD;color:#215E44}
.c-adj{background:#FFF6E3;border:1px solid #EBD3A0;color:#8A5A12}
.c-miss{background:transparent;border:1px dashed #C9BFA8;color:#4C5768}
details{margin-top:4px}
summary{cursor:pointer;font:400 11px/1.4 'JetBrains Mono',monospace;color:#8A93A1;letter-spacing:.06em}
.quote{font:400 13px/1.5 Inter,sans-serif;color:#4C5768;margin:6px 0 0 2px;padding-left:10px;border-left:2px solid #E0D8C4}
.quote .src{display:block;font:400 11px/1.4 'JetBrains Mono',monospace;color:#A6AEB9;margin-top:2px}
.fam{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:12px}
.famc{border:1px solid #EBE3D2;border-radius:3px;padding:12px 14px}
.famn{font:500 14px/1.3 Inter,sans-serif;color:#1F2937}
.faml{font:400 13px/1.7 Inter,sans-serif;color:#4C5768;margin-top:6px}
.tr{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:10px}
.roles{display:flex;flex-wrap:wrap;gap:6px;margin-top:12px}
.role{display:inline-flex;align-items:baseline;gap:7px;padding:8px 12px 7px;border:1px solid #E0D8C4;border-radius:3px;background:#FFFDF8;color:#4C5768;font:500 11px/1 'JetBrains Mono',monospace;letter-spacing:.08em;white-space:nowrap}
.role:hover{border-color:#CBBFA5;color:#2A3342}
.role.on{border-color:#D6482B;color:#D6482B;background:#FFF6F2}
.role .rc{font-weight:400;color:#A6AEB9;letter-spacing:.06em}
@media (max-width:700px){.fam,.tr{grid-template-columns:1fr}.head,.wrap{padding-left:16px;padding-right:16px}}
"""

_JS = """
(function(){
  var btn=document.getElementById('lp-go'), msg=document.getElementById('lp-msg');
  var running=__RUNNING__;
  function poll(id){
    fetch('__POLL__'+id).then(function(r){return r.json()}).then(function(d){
      if(d.status==='RUNNING'){
        var p=d.progress||{}, t=d.stage||'starting';
        if(p.total){t+=' — '+(p.done||0)+' of '+p.total;}
        if(msg){msg.textContent=t+'…';}
        setTimeout(function(){poll(id)},4000);
      } else { location.reload(); }
    }).catch(function(){setTimeout(function(){poll(id)},8000);});
  }
  if(running){ if(btn){btn.disabled=true;} poll(running); }
  if(btn){ btn.addEventListener('click',function(){
    btn.disabled=true; if(msg){msg.className='msg';msg.textContent='Starting…';}
    fetch('__START__',{method:'POST'}).then(function(r){
      return r.json().then(function(d){return {ok:r.ok,d:d};});
    }).then(function(x){
      if(x.ok||x.d.path_id){poll(x.d.path_id);}
      else{btn.disabled=false; if(msg){msg.className='msg err';msg.textContent=x.d.error||'Could not start.';}}
    }).catch(function(){btn.disabled=false; if(msg){msg.className='msg err';msg.textContent='Could not reach the app.';}});
  }); }
})();
"""


def script(running_id, start_url: str, poll_url: str) -> str:
    """The build button and the progress poll, pointed at one endpoint pair."""
    return (_JS.replace("__RUNNING__", json.dumps(running_id))
            .replace("__START__", start_url).replace("__POLL__", poll_url))


def _e(value) -> str:
    return escape(str(value if value is not None else ""), quote=True)


def _pct(share) -> str:
    return f"{round((share or 0) * 100)}%"


def _date(value) -> str:
    try:
        return datetime.fromisoformat(str(value)).strftime("%b %d, %Y")
    except (TypeError, ValueError):
        return ""


def _status_chip(skill: dict) -> str:
    status = skill.get("status")
    if status == "have":
        return '<span class="chip c-have">you have it</span>'
    if status == "adjacent":
        related = skill.get("related_to") or "a related skill"
        return f'<span class="chip c-adj">builds on {_e(related)}</span>'
    if skill.get("category") == "soft":
        return '<span class="chip c-miss">soft skill, not planned</span>'
    return '<span class="chip c-miss">not on your resume</span>'


def _resume_words(skill: dict) -> str:
    """The resume's own words, when that is how the status was decided.
    A skill matched off the confirmed skill list has no quote to show."""
    if skill.get("how") in ("text", "claude"):
        return skill.get("resume_evidence") or ""
    return ""


def _quotes(samples: list[dict], resume_evidence: str = "") -> str:
    if not samples and not resume_evidence:
        return ""
    parts = []
    if resume_evidence:
        parts.append(f'<div class="quote">“{_e(resume_evidence)}”'
                     '<span class="src">YOUR RESUME</span></div>')
    for sample in samples or []:
        source = f"{sample.get('company', '')} · {sample.get('title', '')}"
        link = (f'<a href="{_e(sample["url"])}" target="_blank" rel="noopener">'
                f'{_e(source)}</a>' if sample.get("url") else _e(source))
        parts.append(f'<div class="quote">“{_e(sample.get("quote"))}”'
                     f'<span class="src">{link}</span></div>')
    return ("<details><summary>THE WORDS BEHIND THIS</summary>"
            + "".join(parts) + "</details>")


def _action(label: str, running_id: int | None) -> str:
    return (f'<div class="foot"><button class="btn-p" id="lp-go">{_e(label)}'
            f'</button><span class="msg" id="lp-msg">'
            f'{"Working…" if running_id else ""}</span></div>')


def _empty_card(running_id) -> str:
    return (
        '<div class="card em"><div class="lab">NO PATH YET</div>'
        '<div class="lead">Claude reads every posting your searches have '
        'stored, lists the skills each one asks for with a quote from the '
        'posting, compares them with your resume, and builds one path '
        'toward the skills the market asks for most.</div>'
        '<div class="note">The first analysis reads every stored posting, '
        'so it takes a while and uses the most API credit. After that only '
        'new postings are read.</div>'
        + _action("BUILD MY PATH", running_id) + '</div>')


def views_of(row: dict) -> tuple[list[dict], dict]:
    """(views, plans) from a stored analysis.

    Rows written before paths were split by kind of role hold one path at
    the top level; they read as a single "All roles" view.
    """
    analysis, stored = row["analysis"], row["path"]
    if analysis.get("views"):
        return analysis["views"], stored
    legacy = {k: analysis.get(k) for k in
              ("postings", "skills", "trends", "gaps", "coverage", "after")}
    return [{"key": "all", "name": "All roles", **legacy}], {"all": stored}


def _role_picker(views: list[dict], active: str) -> str:
    if len(views) < 2:
        return ""
    links = []
    for view in views:
        css = "role on" if view["key"] == active else "role"
        current = ' aria-current="page"' if view["key"] == active else ""
        links.append(f'<a class="{css}" href="/learn?role={_e(view["key"])}"'
                     f'{current}>{_e(view["name"].upper())}'
                     f'<span class="rc">{view["postings"]}</span></a>')
    return ('<div class="card"><div class="lab">CHOOSE A KIND OF ROLE</div>'
            f'<div class="roles">{"".join(links)}</div></div>')


def _summary_card(row: dict, view: dict, plan: dict, running_id) -> str:
    cov, after = view.get("coverage") or {}, view.get("after") or {}
    lines = []
    if cov.get("with_requirements"):
        lines.append(
            f'<div class="gline">Of the {cov["with_requirements"]} '
            f'{_e(_kind(view))}postings that name technical requirements, '
            f'you meet every one in '
            f'<b>{cov["meets_all"]}</b> and are within two skills of '
            f'<b>{cov["within_two"]}</b> more.')
        if after:
            lines.append(
                f' With the skills on this path, that becomes '
                f'<b>{after["meets_all"]}</b> and <b>{after["within_two"]}</b>.')
        lines.append("</div>")
    summary = (f'<div class="lead">{_e(plan.get("summary"))}</div>'
               if plan.get("summary") else "")
    built = _date(row.get("finished_at"))
    return (
        '<div class="card em"><div class="lab-row">'
        f'<span class="lab">YOUR PATH · {_e(view["name"].upper())}</span>'
        f'<span class="lab-m">BUILT {_e(built.upper())}</span></div>'
        f'{summary}{"".join(lines)}'
        + _action("REFRESH WITH NEW POSTINGS", running_id) + '</div>')


def _kind(view: dict) -> str:
    return "" if view["key"] == "all" else view["name"] + " "


def _stage_card(number: int, stage: dict, gaps: dict) -> str:
    skills = []
    for name in stage["skills"]:
        gap = gaps.get(name, {})
        css = "skill adj" if gap.get("status") == "adjacent" else "skill"
        reasons = " ".join(gap.get("reasons") or [])
        skills.append(
            f'<div class="{css}"><div class="sname">{_e(name)}</div>'
            f'<div class="why">{_e(reasons)}</div>'
            f'{_quotes(gap.get("samples") or [], _resume_words(gap))}'
            '</div>')
    topics = "".join(f"<li>{_e(t)}</li>" for t in stage.get("learn") or [])
    return (
        '<div class="card"><div class="stage">'
        f'<div class="snum">{number}</div><div class="sbody">'
        '<div class="lab-row">'
        f'<span class="stitle">{_e(stage.get("title"))}</span>'
        f'<span class="effort">{_e((stage.get("effort") or "").upper())} EFFORT</span>'
        '</div>'
        f'<div class="gline">{_e(stage.get("goal"))}</div>'
        f'{"".join(skills)}'
        f'<div class="sec">WHY NOW</div><div class="para">{_e(stage.get("why_now"))}</div>'
        f'<div class="sec">LEARN</div><ul class="topics">{topics}</ul>'
        f'<div class="sec">PROJECT</div><div class="para">{_e(stage.get("project"))}</div>'
        f'<div class="sec">SHOW IT</div><div class="para">{_e(stage.get("show_it"))}</div>'
        '</div></div></div>')


def _left_out_card(left_out: list[dict], gaps: dict) -> str:
    if not left_out:
        return ""
    rows = "".join(
        f'<div class="gline"><b>{_e(item["skill"])}</b> — {_e(item["reason"])}'
        f' <span class="note">{_e(" ".join(gaps.get(item["skill"], {}).get("reasons") or []))}</span></div>'
        for item in left_out)
    return ('<div class="card"><div class="lab">RANKED BUT NOT IN THE PATH</div>'
            f'{rows}</div>')


def _market_card(analysis: dict) -> str:
    skills = analysis.get("skills") or []
    if not skills:
        return ""
    top = max(s["share"] for s in skills) or 1
    rows = []
    for skill in skills[:25]:
        width = max(2, round(skill["share"] / top * 100))
        rows.append(
            f'<tr><td>{_e(skill["name"])}'
            f'<div class="bar"><i style="width:{width}%"></i></div>'
            f'{_quotes(skill.get("samples") or [], _resume_words(skill))}</td>'
            f'<td class="n">{skill["postings"]} · {_pct(skill["share"])}</td>'
            f'<td class="n">{skill["required"]}</td>'
            f'<td>{_status_chip(skill)}</td></tr>')
    return (
        '<div class="card"><div class="lab-row">'
        '<span class="lab">WHAT THE MARKET ASKS FOR</span>'
        f'<span class="lab-m">{analysis["postings"]} POSTINGS</span></div>'
        '<table class="mk"><tr><th>SKILL</th><th>POSTINGS</th>'
        '<th>AS A REQUIREMENT</th><th>YOU</th></tr>'
        + "".join(rows) + '</table></div>')


def _families_card(analysis: dict) -> str:
    families = [f for f in analysis.get("families") or [] if f.get("top")]
    if not families:
        return ""
    cards = []
    for family in families:
        line = ", ".join(f'{_e(s["name"])} {_pct(s["share"])}'
                         for s in family["top"][:6])
        cards.append(f'<div class="famc"><div class="famn">{_e(family["name"])}'
                     f' <span class="lab-m">{family["postings"]} '
                     f'{"POSTING" if family["postings"] == 1 else "POSTINGS"}'
                     f'</span>'
                     f'</div><div class="faml">{line}</div></div>')
    return ('<div class="card"><div class="lab">BY KIND OF ROLE</div>'
            '<div class="note">Share of that kind of posting naming each skill.</div>'
            f'<div class="fam">{"".join(cards)}</div></div>')


def _trends_card(analysis: dict) -> str:
    trends = analysis.get("trends") or {}
    if not trends.get("available"):
        reason = trends.get("reason") or "Not enough history yet."
        return ('<div class="card"><div class="lab">WHAT IS CHANGING</div>'
                f'<div class="note">{_e(reason)}</div></div>')

    def column(title, items):
        if not items:
            body = '<div class="note">Nothing moved enough to call.</div>'
        else:
            body = "".join(
                f'<div class="gline"><b>{_e(t["name"])}</b> — '
                f'{_pct(t["recent"])} of recent postings, {_pct(t["earlier"])} before</div>'
                for t in items)
        return f'<div><div class="sec">{title}</div>{body}</div>'

    return ('<div class="card"><div class="lab">WHAT IS CHANGING</div>'
            f'<div class="note">Postings after {_e(trends["cutoff"])} '
            f'({trends["recent_postings"]}) against before '
            f'({trends["earlier_postings"]}). A short history, so read these '
            'as early signals.</div>'
            f'<div class="tr">{column("RISING", trends.get("rising"))}'
            f'{column("FALLING", trends.get("falling"))}</div></div>')


def _method_card(row: dict) -> str:
    analysis = row["analysis"]
    span = ""
    if analysis.get("date_from") and analysis.get("date_to"):
        span = (f' posted or first seen between {_e(analysis["date_from"])} '
                f'and {_e(analysis["date_to"])}')
    window = (f' from the past {analysis["window_days"]} days'
              if analysis.get("window_days") else "")
    extra = []
    if analysis.get("unverified"):
        n = analysis["unverified"]
        extra.append(f'{n} skill {"mention was" if n == 1 else "mentions were"}'
                     ' dropped because the quote Claude gave could not be '
                     'found in the posting.')
    if analysis.get("unread"):
        n = analysis["unread"]
        extra.append(f'{n} {"posting has" if n == 1 else "postings have"} not'
                     ' been read yet; the next refresh reads them.')
    return (
        '<div class="card sunk"><div class="lab">HOW THIS WAS BUILT</div>'
        f'<div class="note">From {analysis["postings"]} stored postings{window}{span}, '
        f'and your resume ({_e(", ".join(analysis.get("resume_labels") or []))}). '
        'Claude listed the skills each posting asks for and had to quote the '
        'posting for every one. Counts are postings, not mentions. Gaps are '
        'ranked by how many postings ask for the skill, how many roles it '
        'would bring within reach, and whether your resume already has '
        'something it builds on. Soft skills appear in the market list but '
        f'are not planned. {" ".join(extra)} Model: {_e(row.get("model"))}.'
        '</div></div>')


def _role_paths_card(role_paths: list[dict]) -> str:
    """Paths built toward one job, newest first; and how to start one."""
    how = ('<div class="note">To build one, open a role on the MAP or the '
           'TRACKER and choose <b>LEARNING PATH FOR THIS JOB</b>.</div>')
    if not role_paths:
        return ('<div class="card"><div class="lab">PATHS FOR ONE JOB</div>'
                f'{how}</div>')
    rows = []
    for item in role_paths:
        gaps = item["gaps"]
        state = ("nothing technical missing" if not gaps
                 else f'{gaps} skill{"" if gaps == 1 else "s"} to close')
        rows.append(
            f'<div class="gline"><a href="/learn/role/{int(item["role_id"])}">'
            f'{_e(item["title"])} · {_e(item["company"])}</a> '
            f'<span class="note">{_e(state)}</span></div>')
    return ('<div class="card"><div class="lab">PATHS FOR ONE JOB</div>'
            f'{"".join(rows)}{how}</div>')


def render(latest_ok: dict | None, latest_any: dict | None,
           nav: dict | None = None, role: str = "all",
           role_paths: list[dict] | None = None) -> str:
    nav = nav or {}
    running_id = (latest_any["id"] if latest_any
                  and latest_any["status"] == "RUNNING" else None)
    body = []
    if (latest_any and latest_any["status"] == "FAILED"
            and (not latest_ok or latest_any["id"] > latest_ok["id"])):
        body.append('<div class="card err"><div class="lab">THE LAST '
                    'ANALYSIS DID NOT FINISH</div>'
                    f'<div class="gline">{_e(latest_any.get("error"))}</div></div>')

    if latest_ok and latest_ok.get("analysis") and latest_ok.get("path"):
        analysis = latest_ok["analysis"]
        views, plans = views_of(latest_ok)
        view = next((v for v in views if v["key"] == role), views[0])
        plan = plans.get(view["key"]) or {}
        gaps = {g["name"]: g for g in view.get("gaps") or []}
        body.append(_role_picker(views, view["key"]))
        body.append(_summary_card(latest_ok, view, plan, running_id))
        for number, stage in enumerate(plan.get("stages") or [], 1):
            body.append(_stage_card(number, stage, gaps))
        body.append(_left_out_card(plan.get("left_out") or [], gaps))
        body.append(_market_card(view))
        if view["key"] == "all":
            body.append(_families_card(analysis))
        body.append(_trends_card(view))
        body.append(_role_paths_card(role_paths or []))
        body.append(_method_card(latest_ok))
        sub = (f'A path for each kind of role you search, built from '
               f'{analysis["postings"]} postings and your resume.')
    else:
        body.append(_empty_card(running_id))
        # A path toward one job needs no market analysis first.
        if role_paths:
            body.append(_role_paths_card(role_paths))
        sub = ('One path for the whole market you search, built from the '
               'postings your searches have stored and your resume.')

    top_nav = shell_nav("/learn",
                        counts={"/": nav.get("map_count"),
                                "/activity": nav.get("tracker_count")},
                        user_label=nav.get("user_label") or "")
    js = script(running_id, "/api/learning-path", "/api/learning-path/")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Your learning path</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Caveat:wght@500;600&family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">
<style>{_CSS}{SHELL_CSS}</style>
</head>
<body>
<div class="page">
{top_nav}
<div class="head"><div class="head-in">
<div class="title">your learning path</div>
<div class="sub">{_e(sub)}</div>
</div></div>
<div class="wrap"><div class="col">{"".join(body)}</div></div>
</div>
<script>{js}</script>
</body>
</html>
"""
