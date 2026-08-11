"""Renders the setup screens — upload, confirm, and the resume list.

Same paper palette as the map and the activity board, same shape: a module
holding its own CSS and JS, and functions that return whole documents. The
project generates static pages from Python and has no JS toolchain.

The confirm screen is the one place the scoring model is authored by hand, so
everything on it is editable. Aliases are carried in the page's JS state
rather than shown — a list of synonyms is not something a person wants to
proofread, and it is the model's job to get them roughly right.
"""
import json
from html import escape

_CSS = """
*{box-sizing:border-box}
html,body{margin:0;background:#F7F2E6}
body{font-family:Inter,system-ui,sans-serif;color:#2A3342;-webkit-font-smoothing:antialiased}
a{color:#D6482B;text-decoration:none}
a:hover{color:#A83519}
.page{min-height:100vh;background-image:radial-gradient(rgba(42,51,66,.14) 1px,transparent 1px);background-size:22px 22px;background-position:11px 11px;padding:0 0 80px}
.hatch{height:26px;background-image:repeating-linear-gradient(112deg,rgba(59,126,168,.28) 0 1px,transparent 1px 7px);mask-image:linear-gradient(to bottom,#000,transparent);-webkit-mask-image:linear-gradient(to bottom,#000,transparent)}
.head{display:flex;justify-content:center;padding:30px 40px 30px}
.head-in{flex:1;max-width:820px;display:flex;align-items:flex-end;justify-content:space-between;gap:32px}
.title{font:600 46px/1 Caveat,cursive;color:#D6482B}
.sub{font:400 15px/1.6 Inter,sans-serif;color:#4C5768;margin-top:10px;max-width:48ch;text-wrap:pretty}
.nav{font:500 11px/1 'JetBrains Mono',monospace;color:#6E7787;letter-spacing:.1em}
.wrap{display:flex;justify-content:center;padding:0 40px}
.col{flex:1;max-width:820px;display:flex;flex-direction:column;gap:16px;min-width:0}
.card{background:#FFFDF8;border:1px solid #E0D8C4;border-radius:4px;padding:22px 26px}
.lab{font:500 9.5px/1 'JetBrains Mono',monospace;color:#6E7787;letter-spacing:.11em;display:block;margin-bottom:9px}
.row{margin-top:20px}
.row:first-child{margin-top:0}
input[type=text]{width:100%;padding:9px 11px;border:1px solid #E0D8C4;border-radius:3px;background:#FFFDF8;font:400 14.5px/1.4 Inter,sans-serif;color:#2A3342}
input[type=text]:focus{outline:0;border-color:#2E7D5B}
.chips{display:flex;flex-wrap:wrap;gap:6px;align-items:center}
.chip{display:inline-flex;align-items:center;gap:7px;font:400 12.5px/1.3 Inter,sans-serif;padding:5px 9px;border-radius:2px;background:#EAF2ED;border:1px solid #C3DACD;color:#215E44}
.chip-w{background:transparent;border:1px dashed #C9BFA8;color:#4C5768}
.chip button{border:0;background:transparent;padding:0;cursor:pointer;color:inherit;font:400 13px/1 Inter,sans-serif}
.add{width:auto;min-width:190px;padding:5px 9px;font-size:12.5px}
.opts{display:flex;flex-wrap:wrap;gap:16px;font:400 14px/1.4 Inter,sans-serif;color:#3A4557}
.opts label{display:inline-flex;align-items:center;gap:7px;cursor:pointer}
.note{font:400 13px/1.6 Inter,sans-serif;color:#8A93A1;margin-top:9px;text-wrap:pretty}
.err{color:#A83519}
.warn{background:#F4EFE1;border:1px dashed #C9BFA8;border-radius:3px;padding:11px 13px;font:400 13.5px/1.6 Inter,sans-serif;color:#6E7787;margin-bottom:18px;text-wrap:pretty}
.foot{display:flex;align-items:center;gap:12px;margin-top:26px;padding-top:18px;border-top:1px solid #EBE3D2}
.btn-p{display:inline-block;padding:9px 16px;border:1px solid #D6482B;background:#D6482B;border-radius:3px;color:#FFFDF8;font:500 11px/1 'JetBrains Mono',monospace;letter-spacing:.06em;cursor:pointer}
.btn-p:hover{background:#A83519;border-color:#A83519;color:#FFFDF8}
.btn-q{display:inline-block;padding:9px 14px;border:1px solid transparent;background:transparent;border-radius:3px;color:#8A93A1;font:400 11px/1 'JetBrains Mono',monospace;letter-spacing:.06em;cursor:pointer}
.btn-q:hover{color:#4C5768}
.rlist{display:flex;flex-direction:column;gap:10px;margin-top:14px}
.ritem{display:flex;align-items:baseline;gap:12px;padding:12px 14px;border:1px solid #E0D8C4;border-radius:3px;background:#FFFDF8}
.rname{font:500 15px/1.3 Inter,sans-serif;color:#1F2937}
.rmeta{margin-left:auto;font:400 10.5px/1 'JetBrains Mono',monospace;color:#8A93A1;letter-spacing:.1em}
.off{opacity:.55}
"""


def _e(value) -> str:
    return escape(str(value or ""), quote=True)


def _payload(value) -> str:
    """JSON safe to inline in a <script> block."""
    return json.dumps(value, ensure_ascii=False).replace("</", "<\\/")


def _shell(title: str, heading: str, sub: str, body: str,
           script: str = "", nav: str = "") -> str:
    script_tag = f"<script>{script}</script>" if script else ""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_e(title)}</title>
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
<div class="title">{_e(heading)}</div>
<div class="sub">{_e(sub)}</div>
</div>
<div class="nav">{nav}</div>
</div></div>
<div class="wrap"><div class="col">{body}</div></div>
</div>
{script_tag}
</body>
</html>
"""


_UPLOAD_JS = """
const form = document.getElementById('up');
const out = document.getElementById('msg');
form.addEventListener('submit', async function(e){
  e.preventDefault();
  out.className = 'note';
  out.textContent = 'Reading your resume...';
  const r = await fetch('/api/resumes', {method:'POST', body:new FormData(form)});
  const data = await r.json().catch(function(){return {};});
  if(r.ok){ location.href = '/setup/confirm/' + data.resume_id; return; }
  out.className = 'note err';
  out.textContent = data.error || 'That did not upload. Try again.';
});
"""


def render_upload(message: str = "") -> str:
    """The first screen: one file field."""
    css = "note err" if message else "note"
    body = (
        '<div class="card"><form id="up">'
        '<div class="row"><span class="lab">YOUR RESUME</span>'
        '<input type="file" name="resume" accept="application/pdf" required>'
        '<div class="note">PDF only, up to 5 MB. It stays on this machine — '
        'the file is written next to the database, not sent anywhere.</div>'
        '</div>'
        '<div class="foot">'
        '<button type="submit" class="btn-p">READ MY RESUME</button>'
        f'<span id="msg" class="{css}">{_e(message)}</span>'
        '</div></form></div>'
    )
    return _shell(
        "Set up", "start here",
        "Your resume decides what gets searched and what counts as a good "
        "fit. Nothing runs until it is in.",
        body, _UPLOAD_JS)
