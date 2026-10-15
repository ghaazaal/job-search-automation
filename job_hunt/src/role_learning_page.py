"""Renders /learn/role/<id>: a learning path toward one posting.

Same paper shell and cards as the LEARN page. Every gap shows the posting's
own words; every "you have it" shows the resume's, or says it came from the
confirmed skill list. Counts are postings, never a score.
"""
from .learning_page import (_CSS, _date, _e, _left_out_card, _quotes,
                            _resume_words, _stage_card, script)
from .shell import SHELL_CSS, shell_nav

_EXTRA_CSS = """
.have{display:flex;flex-direction:column;gap:6px;margin-top:10px}
.hrow{font:400 14px/1.5 Inter,sans-serif;color:#3A4557}
.hrow b{font-weight:500;color:#215E44}
.links{display:flex;gap:14px;flex-wrap:wrap;margin-top:12px;font:500 11px/1 'JetBrains Mono',monospace;letter-spacing:.08em}
"""


def _action(label: str, running_id) -> str:
    return (f'<div class="foot"><button class="btn-p" id="lp-go">{_e(label)}'
            f'</button><span class="msg" id="lp-msg">'
            f'{"Working…" if running_id else ""}</span></div>')


def _links(role: dict) -> str:
    posting = (f'<a href="{_e(role["url"])}" target="_blank" rel="noopener">'
               'OPEN POSTING ↗</a>' if role.get("url") else "")
    return (f'<div class="links">{posting}'
            '<a href="/learn">ALL LEARNING PATHS</a></div>')


def _empty_card(role: dict, running_id) -> str:
    if not role.get("description_captured"):
        return ('<div class="card em"><div class="lab">NO REQUIREMENTS TO READ</div>'
                '<div class="lead">This posting was stored without its '
                'description, so there is nothing to compare your resume '
                'against.</div>' + _links(role) + '</div>')
    return (
        '<div class="card em"><div class="lab">NO PATH FOR THIS JOB YET</div>'
        '<div class="lead">Claude reads this posting for the skills it asks '
        'for, quoting each one, compares them with your resume, and builds '
        'a path toward the ones you are missing.</div>'
        '<div class="note">A few calls to Claude, about a minute. If the '
        'posting has already been read for the market path, it is not read '
        'again.</div>'
        + _action("BUILD PATH FOR THIS JOB", running_id) + _links(role)
        + '</div>')


def _summary_card(row: dict, running_id) -> str:
    analysis, plan = row["analysis"], row["path"]
    required, have = analysis.get("required", 0), analysis.get("have_required", 0)
    gaps = analysis.get("gaps") or []
    if required:
        line = (f'This posting names <b>{required}</b> technical '
                f'requirement{"" if required == 1 else "s"}; your resume shows '
                f'<b>{have}</b>.')
    else:
        line = 'This posting names no technical requirements outright.'
    if not gaps:
        line += (' Every technical skill it asks for is already on your '
                 'resume, so there is nothing to learn for it: tailor the '
                 'resume to its wording instead.')
    summary = (f'<div class="lead">{_e(plan.get("summary"))}</div>'
               if plan.get("summary") else "")
    return (
        '<div class="card em"><div class="lab-row">'
        '<span class="lab">PATH TO THIS JOB</span>'
        f'<span class="lab-m">BUILT {_e(_date(row.get("finished_at")).upper())}'
        '</span></div>'
        f'{summary}<div class="gline">{line}</div>'
        + _action("REBUILD", running_id) + _links(analysis) + '</div>')


def _have_card(analysis: dict) -> str:
    have = analysis.get("have") or []
    if not have:
        return ""
    rows = []
    for skill in have:
        source = ("on your resume's skill list" if skill.get("how") == "listed"
                  else "in your resume")
        rows.append(
            f'<div class="hrow"><b>{_e(skill["name"])}</b> — '
            f'{_e("required" if skill["requirement"] == "required" else "nice to have")}'
            f', found {source}'
            f'{_quotes(skill.get("samples") or [{"quote": skill["posting_evidence"], "title": analysis["title"], "company": analysis["company"], "url": analysis.get("url")}], _resume_words(skill))}'
            '</div>')
    return ('<div class="card"><div class="lab">WHAT YOU ALREADY BRING</div>'
            f'<div class="have">{"".join(rows)}</div></div>')


def _soft_card(analysis: dict) -> str:
    soft = analysis.get("soft") or []
    if not soft:
        return ""
    names = ", ".join(_e(s["name"]) for s in soft)
    return ('<div class="card sunk"><div class="lab">ALSO ASKED FOR</div>'
            f'<div class="note">{names}. Soft skills are not planned here; '
            'show them through examples in the cover letter.</div></div>')


def render(role: dict, latest_ok: dict | None, latest_any: dict | None,
           nav: dict | None = None) -> str:
    nav = nav or {}
    running_id = (latest_any["id"] if latest_any
                  and latest_any["status"] == "RUNNING" else None)
    body = []
    if (latest_any and latest_any["status"] == "FAILED"
            and (not latest_ok or latest_any["id"] > latest_ok["id"])):
        body.append('<div class="card err"><div class="lab">THE LAST BUILD '
                    'DID NOT FINISH</div>'
                    f'<div class="gline">{_e(latest_any.get("error"))}</div></div>')

    if latest_ok and latest_ok.get("analysis") is not None:
        analysis, plan = latest_ok["analysis"], latest_ok["path"] or {}
        gaps = {g["name"]: g for g in analysis.get("gaps") or []}
        body.append(_summary_card(latest_ok, running_id))
        for number, stage in enumerate(plan.get("stages") or [], 1):
            body.append(_stage_card(number, stage, gaps))
        body.append(_left_out_card(plan.get("left_out") or [], gaps))
        body.append(_have_card(analysis))
        body.append(_soft_card(analysis))
    else:
        body.append(_empty_card(role, running_id))

    top_nav = shell_nav("/learn",
                        counts={"/": nav.get("map_count"),
                                "/activity": nav.get("tracker_count")},
                        user_label=nav.get("user_label") or "")
    rid = int(role["id"])
    js = script(running_id, f"/api/roles/{rid}/learning-path",
                "/api/role-learning-path/")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Path to this job</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Caveat:wght@500;600&family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">
<style>{_CSS}{_EXTRA_CSS}{SHELL_CSS}</style>
</head>
<body>
<div class="page">
{top_nav}
<div class="head"><div class="head-in">
<div class="title">path to this job</div>
<div class="sub">{_e(role["title"])} · {_e(role["company"])}</div>
</div></div>
<div class="wrap"><div class="col">{"".join(body)}</div></div>
</div>
<script>{js}</script>
</body>
</html>
"""
