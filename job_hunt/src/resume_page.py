"""Renders the RESUME tab, the tailor page and the print view.

Same paper shell and 820px measure as the LEARN page. The master resume
is edited as plain Markdown in a text box; a tailored resume is shown as
a page, with what was brought forward, what the posting asks for that the
master does not show, and every line the check put back.
"""
import json
from datetime import datetime
from html import escape

from .shell import SHELL_CSS, shell_nav
from .tailor import document

_FONTS = ('<link rel="preconnect" href="https://fonts.googleapis.com">'
          '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
          '<link href="https://fonts.googleapis.com/css2?family=Caveat:wght@500;600'
          '&family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;500;700'
          '&display=swap" rel="stylesheet">')

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
.sub{font:400 15px/1.6 Inter,sans-serif;color:#4C5768;margin-top:9px;max-width:62ch;text-wrap:pretty}
.crumb{font:500 10.5px/1 'JetBrains Mono',monospace;color:#6E7787;letter-spacing:.1em;margin-bottom:12px}
.wrap{display:flex;justify-content:center;padding:0 40px}
.col{flex:1;max-width:820px;display:flex;flex-direction:column;gap:16px;min-width:0}
.card{background:#FFFDF8;border:1px solid #E0D8C4;border-radius:4px;padding:18px 20px 20px}
.card.sunk{background:#F4EFE1}
.card.err{border-color:#E3B4A6;background:#FBF1EC}
.lab-row{display:flex;align-items:baseline;justify-content:space-between;gap:12px;flex-wrap:wrap}
.lab{font:500 10.5px/1 'JetBrains Mono',monospace;color:#6E7787;letter-spacing:.11em}
.lab-m{font:400 10.5px/1 'JetBrains Mono',monospace;color:#A6AEB9;letter-spacing:.1em}
.gline{font:400 14.5px/1.6 Inter,sans-serif;color:#3A4557;margin-top:10px;text-wrap:pretty}
.note{font:400 13px/1.6 Inter,sans-serif;color:#8A93A1;margin-top:10px;text-wrap:pretty}
.foot{display:flex;align-items:center;gap:10px;margin-top:16px;padding-top:14px;border-top:1px solid #EBE3D2;flex-wrap:wrap}
.btn-p{display:inline-block;padding:10px 16px;border:1px solid #D6482B;background:#D6482B;border-radius:3px;color:#FFFDF8;font:500 11.5px/1 'JetBrains Mono',monospace;letter-spacing:.07em;white-space:nowrap;cursor:pointer;text-decoration:none}
.btn-p:hover{background:#A83519;border-color:#A83519;color:#FFFDF8}
.btn-p[disabled]{opacity:.5;cursor:default}
.btn-s{display:inline-block;padding:10px 14px;border:1px solid #D5CDB9;background:transparent;border-radius:3px;color:#4C5768;font:400 11.5px/1 'JetBrains Mono',monospace;letter-spacing:.07em;white-space:nowrap;cursor:pointer;text-decoration:none}
.btn-s:hover{border-color:#2E7D5B;color:#2E7D5B}
.btn-s[disabled]{opacity:.5;cursor:default}
.msg{font:400 13px/1.5 Inter,sans-serif;color:#8A93A1}
.msg.err{color:#A83519}
.msg.ok{color:#2E7D5B}
textarea.md{width:100%;min-height:520px;margin-top:12px;padding:14px 16px;border:1px solid #E0D8C4;border-radius:3px;background:#FFFEFB;color:#2A3342;font:400 12.5px/1.6 'JetBrains Mono',monospace;resize:vertical}
textarea.md:focus{outline:none;border-color:#CBBFA5}
.file{font:400 12.5px/1.4 Inter,sans-serif;color:#4C5768}
ul.lst{margin:8px 0 0;padding-left:18px;font:400 14px/1.6 Inter,sans-serif;color:#3A4557}
ul.lst li{margin-top:3px}
.miss{font:400 11px/1.4 'JetBrains Mono',monospace;color:#A83519;letter-spacing:.03em}
.chip{display:inline-block;padding:4px 8px;margin:6px 6px 0 0;border-radius:2px;font:400 12.5px/1.2 Inter,sans-serif;background:transparent;border:1px dashed #C9BFA8;color:#4C5768}
table.tl{width:100%;border-collapse:collapse;margin-top:10px}
.tl td{padding:9px 6px;border-bottom:1px solid #F0EADB;font:400 14px/1.4 Inter,sans-serif;color:#2A3342;vertical-align:top}
.tl .n{font:400 11.5px/1.4 'JetBrains Mono',monospace;color:#8A93A1;white-space:nowrap;text-align:right}
.rv{border:1px solid #E0D8C4;border-radius:3px;background:#FFFEFB;padding:28px 34px;margin-top:12px}
.rv h1{font:600 24px/1.2 Inter,sans-serif;color:#1F2937;margin:0;letter-spacing:-.01em}
.rv .hl{font:400 13px/1.6 Inter,sans-serif;color:#4C5768}
.rv h2{font:500 10.5px/1 'JetBrains Mono',monospace;color:#D6482B;letter-spacing:.12em;text-transform:uppercase;margin:22px 0 8px;padding-bottom:6px;border-bottom:1px solid #EBE3D2}
.rv h3{font:600 14.5px/1.35 Inter,sans-serif;color:#1F2937;margin:12px 0 0}
.rv .mt{font:400 12px/1.5 'JetBrains Mono',monospace;color:#6E7787}
.rv p{font:400 14px/1.6 Inter,sans-serif;color:#2A3342;margin:6px 0 0;text-wrap:pretty}
.rv ul{margin:6px 0 0;padding-left:18px}
.rv li{font:400 14px/1.55 Inter,sans-serif;color:#2A3342;margin-top:3px;text-wrap:pretty}
@media (max-width:700px){.head,.wrap{padding-left:16px;padding-right:16px}.rv{padding:18px 16px}}
"""

_PRINT_CSS = """
*{box-sizing:border-box}
body{margin:0;background:#fff;color:#111;font-family:Inter,system-ui,sans-serif}
.rv{max-width:780px;margin:0 auto;padding:36px 40px}
.rv h1{font:600 24px/1.2 Inter,sans-serif;margin:0}
.rv .hl{font:400 12.5px/1.55 Inter,sans-serif;color:#333}
.rv h2{font:600 11px/1 Inter,sans-serif;letter-spacing:.12em;text-transform:uppercase;margin:18px 0 6px;padding-bottom:5px;border-bottom:1px solid #bbb}
.rv h3{font:600 13.5px/1.35 Inter,sans-serif;margin:10px 0 0}
.rv .mt{font:400 11.5px/1.5 Inter,sans-serif;color:#444}
.rv p{font:400 13px/1.55 Inter,sans-serif;margin:5px 0 0}
.rv ul{margin:4px 0 0;padding-left:17px}
.rv li{font:400 13px/1.5 Inter,sans-serif;margin-top:2px}
.bar{max-width:780px;margin:16px auto 0;padding:0 40px;font:400 12px/1.4 'JetBrains Mono',monospace;color:#666}
@media print{.bar{display:none}.rv{padding:0}@page{margin:16mm 15mm}}
"""


def _e(value) -> str:
    return escape(str(value if value is not None else ""), quote=True)


def _date(value) -> str:
    try:
        return datetime.fromisoformat(str(value)).strftime("%b %d, %Y")
    except (TypeError, ValueError):
        return ""


def _usd(usage: dict | None) -> str:
    usd = (usage or {}).get("usd")
    if usd is None:
        return ""
    return f"${usd:.2f}" if usd >= 0.01 else "under $0.01"


def doc_html(markdown: str) -> str:
    """A resume's Markdown as HTML, from the same parse the check uses."""
    doc = document.parse(markdown)
    out = ['<div class="rv">']
    if doc.get("name"):
        out.append(f"<h1>{_e(doc['name'])}</h1>")
    out.extend(f'<div class="hl">{_e(line)}</div>' for line in doc["header"])
    for section in doc["sections"]:
        out.append(f"<h2>{_e(section['title'])}</h2>")
        for block in section["blocks"]:
            if block["kind"] == "para":
                out.append(f"<p>{_e(block['text'])}</p>")
                continue
            if block.get("heading"):
                out.append(f"<h3>{_e(block['heading'])}</h3>")
                out.extend(f'<div class="mt">{_e(m)}</div>'
                           for m in block.get("meta") or [])
            if block["bullets"]:
                out.append("<ul>" + "".join(
                    f"<li>{_e(b['text'])}</li>" for b in block["bullets"])
                    + "</ul>")
    out.append("</div>")
    return "".join(out)


def _page(title: str, active: str, nav: dict, head: str, body: list[str],
          js: str = "") -> str:
    top_nav = shell_nav(active,
                        counts={"/": nav.get("map_count"),
                                "/activity": nav.get("tracker_count")},
                        user_label=nav.get("user_label") or "")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_e(title)}</title>
{_FONTS}
<style>{_CSS}{SHELL_CSS}</style>
</head>
<body>
<div class="page">
{top_nav}
<div class="head"><div class="head-in">{head}</div></div>
<div class="wrap"><div class="col">{"".join(body)}</div></div>
</div>
<script>{js}</script>
</body>
</html>"""


# ── RESUME tab ────────────────────────────────────────────────────────────

_MASTER_JS = """
(function(){
  function say(el,t,c){ if(el){el.className='msg'+(c?' '+c:''); el.textContent=t;} }
  var build=document.getElementById('mr-build'), bmsg=document.getElementById('mr-bmsg');
  if(build){ build.addEventListener('click',function(){
    if(__HAS_MASTER__ && !confirm('Rebuild the master from your resumes? Edits you made by hand will be replaced.')){return;}
    var fd=new FormData(), f=document.getElementById('mr-files');
    if(f){ for(var i=0;i<f.files.length;i++){ fd.append('sources', f.files[i]); } }
    build.disabled=true; say(bmsg,'Claude is reading your resumes. This takes a minute or two.');
    fetch('/api/master-resume/build',{method:'POST',body:fd}).then(function(r){
      return r.json().then(function(d){return {ok:r.ok,d:d};});
    }).then(function(x){
      if(x.ok){ location.reload(); }
      else{ build.disabled=false; say(bmsg,x.d.error||'That did not work.','err'); }
    }).catch(function(){ build.disabled=false; say(bmsg,'Could not reach the app.','err'); });
  }); }
  var save=document.getElementById('mr-save'), smsg=document.getElementById('mr-smsg');
  if(save){ save.addEventListener('click',function(){
    save.disabled=true; say(smsg,'Saving…');
    fetch('/api/master-resume',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({markdown:document.getElementById('mr-md').value})}).then(function(r){
      return r.json().then(function(d){return {ok:r.ok,d:d};});
    }).then(function(x){
      save.disabled=false;
      if(x.ok){ say(smsg,'Saved.','ok'); } else { say(smsg,x.d.error||'That did not save.','err'); }
    }).catch(function(){ save.disabled=false; say(smsg,'Could not reach the app.','err'); });
  }); }
})();
"""


def _left_out_card(report: dict) -> str:
    left = report.get("left_out") or []
    warn = report.get("warnings") or []
    if not left and not warn:
        return ""
    items = []
    for item in left:
        items.append(f'<li>{_e(item["text"])}<br><span class="miss">NOT IN '
                     f'YOUR RESUMES: {_e(", ".join(item.get("missing") or []))}'
                     '</span></li>')
    for item in warn:
        items.append(f'<li>{_e(item["text"])}<br><span class="miss">KEPT, '
                     f'CHECK IT: {_e(", ".join(item.get("missing") or []))}'
                     '</span></li>')
    return ('<div class="card sunk"><div class="lab">LEFT OUT OF THE MASTER'
            '</div><div class="note">Claude wrote these, but your resumes do '
            'not say the named things or figures in them, so they were not '
            'kept. If one is true, add it to the master by hand.</div>'
            f'<ul class="lst">{"".join(items)}</ul></div>')


def render_resume(master: dict | None, tailored: list[dict],
                  resumes: list[dict], nav: dict | None = None) -> str:
    nav = nav or {}
    body = []
    labels = ", ".join(r["label"] for r in resumes) or "none yet"
    if master:
        built = _date(master.get("created_at"))
        sources = ", ".join(s.get("label", "") for s in master.get("sources")
                            or []) or "your resumes"
        edited = " · EDITED BY HAND" if master.get("edited") else ""
        body.append(
            '<div class="card"><div class="lab-row"><div class="lab">MASTER '
            f'RESUME</div><div class="lab-m">BUILT {_e(built.upper())}'
            f'{edited}</div></div>'
            f'<div class="note">Built from {_e(sources)}. This is the one '
            'source every tailored resume is cut from: tailoring may reorder, '
            'shorten and reword it, never add to it. Edit it here when '
            'something is missing or wrong.</div>'
            f'<textarea class="md" id="mr-md" spellcheck="true">'
            f'{_e(master["markdown"])}</textarea>'
            '<div class="note"># your name, then headline and contact lines; '
            '## a section; ### a job or degree, with its dates on the next '
            'line; - a bullet.</div>'
            '<div class="foot"><button type="button" class="btn-p" '
            'id="mr-save">SAVE MASTER</button><span class="msg" id="mr-smsg">'
            '</span></div></div>')
        body.append(_left_out_card(master.get("report") or {}))

    body.append(
        '<div class="card' + (' sunk' if master else '') + '">'
        f'<div class="lab">{"REBUILD THE MASTER" if master else "BUILD YOUR MASTER RESUME"}</div>'
        f'<div class="gline">Claude merges the resumes you uploaded '
        f'({_e(labels)}) into one complete resume: every job, bullet and '
        'figure, duplicates merged. Add older CVs or a LinkedIn profile PDF '
        'below to fold them in too; they are read for the master only and '
        'do not change your search.</div>'
        '<div class="foot"><input class="file" type="file" id="mr-files" '
        'accept="application/pdf,.pdf" multiple>'
        f'<button type="button" class="btn-{"s" if master else "p"}" '
        f'id="mr-build">{"REBUILD" if master else "BUILD MASTER"}</button>'
        '<span class="msg" id="mr-bmsg"></span></div>'
        '<div class="note">One Claude Opus call, about $0.10 to $0.30 '
        'depending on how many pages it reads.</div></div>')

    if tailored:
        rows = "".join(
            f'<tr><td><a href="/tailor/{t["role_id"]}">{_e(t["title"])}</a>'
            f'<div class="note" style="margin-top:2px">{_e(t["company"])}</div></td>'
            f'<td class="n">{_e(_date(t["created_at"]).upper())}</td></tr>'
            for t in tailored)
        body.append('<div class="card"><div class="lab">TAILORED RESUMES</div>'
                    f'<table class="tl">{rows}</table></div>')
    else:
        body.append('<div class="card sunk"><div class="lab">TAILORED RESUMES'
                    '</div><div class="note">None yet. Open a role on the map '
                    'or the tracker and choose TAILOR RESUME.</div></div>')

    head = ('<div class="title">your resume</div><div class="sub">One master '
            'resume with everything you have done, cut down and reordered '
            'for each posting you apply to.</div>')
    js = _MASTER_JS.replace("__HAS_MASTER__", json.dumps(bool(master)))
    return _page("Your resume", "/resume", nav, head, body, js)


# ── tailor page ───────────────────────────────────────────────────────────

_TAILOR_JS = """
(function(){
  var go=document.getElementById('tl-go'), msg=document.getElementById('tl-msg');
  if(go){ go.addEventListener('click',function(){
    go.disabled=true; msg.className='msg';
    msg.textContent='Claude is tailoring your master to this posting. This takes about a minute.';
    fetch('/api/roles/__ROLE__/tailor',{method:'POST'}).then(function(r){
      return r.json().then(function(d){return {ok:r.ok,d:d};});
    }).then(function(x){
      if(x.ok){ location.reload(); }
      else{ go.disabled=false; msg.className='msg err'; msg.textContent=x.d.error||'That did not work.'; }
    }).catch(function(){ go.disabled=false; msg.className='msg err'; msg.textContent='Could not reach the app.'; });
  }); }
  var cp=document.getElementById('tl-copy');
  if(cp){ cp.addEventListener('click',function(){
    var t=document.getElementById('tl-md').value;
    navigator.clipboard.writeText(t).then(function(){ cp.textContent='COPIED'; });
  }); }
})();
"""


def _report_cards(report: dict, usage: dict) -> list[str]:
    cards = []
    emphasis = report.get("emphasis") or []
    if emphasis:
        cards.append('<div class="card"><div class="lab">WHAT WAS BROUGHT '
                     'FORWARD</div><ul class="lst">'
                     + "".join(f"<li>{_e(x)}</li>" for x in emphasis)
                     + '</ul><div class="note">Claude\'s note on its choices. '
                     'It is not part of the resume.</div></div>')
    missing = report.get("not_in_master") or []
    if missing:
        cards.append('<div class="card sunk"><div class="lab">THE POSTING '
                     'ASKS FOR, YOUR MASTER DOES NOT SHOW</div><div>'
                     + "".join(f'<span class="chip">{_e(x)}</span>'
                               for x in missing)
                     + '</div><div class="note">Left out of the resume on '
                     'purpose. If you do have one of these, add it to your '
                     'master and tailor again; otherwise it is a line for the '
                     'cover letter, not the resume.</div></div>')
    reverted = report.get("reverted") or []
    dropped = report.get("dropped") or []
    lines = [f"{report.get('rewritten', 0)} lines reworded and "
             f"{report.get('kept_as_is', 0)} kept word for word passed the "
             "check: every figure, tool and name in them is in the master "
             "lines they came from."]
    items = []
    for item in reverted:
        kept = (f'<br><span class="note">Kept the master\'s words instead: '
                f'{_e(item["kept"])}</span>' if item.get("kept") else
                '<br><span class="note">Left out.</span>')
        items.append(f'<li>{_e(item["text"])}<br><span class="miss">NOT IN '
                     f'THE MASTER: {_e(", ".join(item.get("missing") or []))}'
                     f'</span>{kept}</li>')
    for item in dropped:
        items.append(f'<li>{_e(item["text"])}<br><span class="miss">'
                     f'LEFT OUT: {_e(item.get("why"))}</span></li>')
    cost = _usd(usage)
    cost_line = (f'<div class="note">This tailoring cost {cost} '
                 f'({usage.get("input", 0) + usage.get("cache_read", 0) + usage.get("cache_write", 0):,} '
                 f'tokens in, {usage.get("output", 0):,} out).</div>'
                 if cost else "")
    cards.append('<div class="card sunk"><div class="lab">CHECKED AGAINST '
                 f'YOUR MASTER</div><div class="gline">{_e(lines[0])}</div>'
                 + (f'<div class="note">Put back or left out:</div>'
                    f'<ul class="lst">{"".join(items)}</ul>' if items else
                    '<div class="note">Nothing had to be put back.</div>')
                 + '<div class="note">The check catches new figures, tools '
                 'and names. Read the resume once before you send it: it '
                 'cannot catch a plain-word claim the master does not '
                 'make.</div>' + cost_line + '</div>')
    return cards


def render_tailor(role: dict, latest: dict | None, master: dict | None,
                  nav: dict | None = None) -> str:
    nav = nav or {}
    body = []
    posting = (f' · <a href="{_e(role["url"])}" target="_blank" '
               'rel="noopener">OPEN POSTING ↗</a>' if role.get("url") else "")
    can_tailor = bool(master) and bool(role.get("description_captured"))
    if not master:
        body.append('<div class="card err"><div class="lab">NO MASTER RESUME '
                    'YET</div><div class="gline">Tailoring cuts from your '
                    'master resume. <a href="/resume">Build it on the RESUME '
                    'tab</a> first; it takes a minute.</div></div>')
    elif not role.get("description_captured"):
        body.append('<div class="card err"><div class="lab">NO POSTING TEXT'
                    '</div><div class="gline">This listing arrived without a '
                    'description, so there is nothing to tailor against.'
                    '</div></div>')
    if can_tailor:
        again = latest is not None
        stale = (latest is not None
                 and latest.get("master_markdown") != master["markdown"])
        note = ("Your master has changed since this one was made."
                if stale else "")
        body.append(
            '<div class="card"><div class="lab">'
            f'{"TAILOR AGAIN" if again else "TAILOR YOUR MASTER TO THIS POSTING"}'
            '</div><div class="gline">Claude reorders, trims and rewords your '
            'master for this posting. It may not add anything your master '
            'does not say, and every line is checked against the master '
            f'afterwards. {_e(note)}</div>'
            '<div class="foot"><button type="button" class="btn-'
            f'{"s" if again and not stale else "p"}" id="tl-go">'
            f'{"TAILOR AGAIN" if again else "TAILOR RESUME"}</button>'
            '<span class="msg" id="tl-msg">About $0.10 to $0.20 per resume.'
            '</span></div></div>')
    if latest:
        tid = latest["id"]
        body.append(
            '<div class="card"><div class="lab-row"><div class="lab">TAILORED '
            f'RESUME</div><div class="lab-m">{_e(_date(latest["created_at"]).upper())}'
            f'</div></div>{doc_html(latest["markdown"])}'
            '<div class="foot">'
            f'<a class="btn-p" href="/tailored/{tid}/print" target="_blank" '
            'rel="noopener">PRINT · SAVE AS PDF</a>'
            f'<a class="btn-s" href="/tailored/{tid}.md">DOWNLOAD .MD</a>'
            '<button type="button" class="btn-s" id="tl-copy">COPY TEXT'
            '</button></div>'
            f'<textarea id="tl-md" hidden>{_e(latest["markdown"])}</textarea>'
            '</div>')
        body.extend(_report_cards(latest.get("report") or {},
                                  latest.get("usage") or {}))
    head = (f'<div class="crumb">{_e((role.get("company") or "").upper())}'
            f'{posting}</div><div class="title">tailored resume</div>'
            f'<div class="sub">{_e(role.get("title"))}</div>')
    js = _TAILOR_JS.replace("__ROLE__", str(int(role["id"])))
    return _page(f"Resume for {role.get('title') or ''}", "/resume", nav,
                 head, body, js)


def render_print(tailored: dict) -> str:
    """A bare page for the browser's Print → Save as PDF."""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_e(document.parse(tailored["markdown"]).get("name") or "Resume")} - {_e(tailored.get("company"))}</title>
{_FONTS}
<style>{_PRINT_CSS}</style>
</head>
<body>
<div class="bar">Use your browser's Print and choose Save as PDF. This line does not print.</div>
{doc_html(tailored["markdown"])}
<script>window.addEventListener('load',function(){{setTimeout(function(){{window.print();}},400);}});</script>
</body>
</html>"""
