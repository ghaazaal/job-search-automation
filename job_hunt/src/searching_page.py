"""The progress screen.

Renders every planned step from the first poll so the reader sees the whole
shape of the run immediately, rather than a list that grows.

Counts shown are only ones the run has actually produced. While scraping, the
total is unknown, so no denominator is displayed — inventing one would be the
fabricated-precision pattern this project bans.

Same paper palette as the map and the setup screens — see map_page.py's and
setup_page.py's own _CSS for the source of these tokens. DESIGN.md's dark
theme was never actually shipped; the live screens are the ground truth.
"""

_POLL_MS = 2000

# Progress unchanged for this long means nothing is watching the worker any
# more. Detected in the page rather than the database: it costs no schema
# change, and the only reader who cares is the one looking at the screen.
#
# Assumes no single scrape step legitimately takes this long — config.yaml's
# search.run_timeout defaults to 120s per call, well under this, but the two
# aren't linked, so raising run_timeout meaningfully could produce a false
# warning during genuine progress.
_STALL_MS = 180_000

_CSS = """
*{box-sizing:border-box}
html,body{margin:0;background:#F7F2E6}
body{font-family:Inter,system-ui,sans-serif;color:#2A3342;-webkit-font-smoothing:antialiased}
a{color:#D6482B;text-decoration:none}
a:hover{color:#A83519}
.page{min-height:100vh;background-image:radial-gradient(rgba(42,51,66,.14) 1px,transparent 1px);background-size:22px 22px;background-position:11px 11px;padding:0 0 80px}
.hatch{height:26px;background-image:repeating-linear-gradient(112deg,rgba(59,126,168,.28) 0 1px,transparent 1px 7px);mask-image:linear-gradient(to bottom,#000,transparent);-webkit-mask-image:linear-gradient(to bottom,#000,transparent)}
.head{display:flex;justify-content:center;padding:30px 40px 30px}
.head-in{flex:1;max-width:640px}
.title{font:600 46px/1 Caveat,cursive;color:#D6482B}
.sub{font:400 15px/1.6 Inter,sans-serif;color:#4C5768;margin-top:10px;max-width:48ch;text-wrap:pretty}
.wrap{display:flex;justify-content:center;padding:0 40px}
.col{flex:1;max-width:640px}
.steps{background:#FFFDF8;border:1px solid #E0D8C4;border-radius:4px;overflow:hidden}
.step{display:flex;align-items:center;gap:12px;padding:13px 18px;border-bottom:1px solid #EBE3D2;font:400 13px/1.4 'JetBrains Mono',monospace;color:#3A4557}
.step:last-child{border-bottom:none}
.dot{width:8px;height:8px;border-radius:50%;background:#D5CDB9;flex:none}
.step[data-state=running] .dot{background:#2A5F86}
.step[data-state=done] .dot{background:#2E7D5B}
.step[data-state=failed] .dot{background:#A83519}
.name{flex:1}
.found{color:#8A93A1}
.step[data-state=failed] .found{color:#A83519}
.note{margin-top:20px;font:400 13.5px/1.6 Inter,sans-serif;color:#8A93A1;min-height:20px;text-wrap:pretty}
.note.bad{color:#A83519}
a.retry{color:#D6482B;border-bottom:1px solid #D6482B}
a.retry:hover{color:#A83519;border-bottom-color:#A83519}
"""

_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Searching</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Caveat:wght@500;600&family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">
<style>{css}</style>
</head>
<body>
<div class="page">
<div class="hatch"></div>
<div class="head"><div class="head-in">
<div class="title">searching</div>
<div class="sub">Reading LinkedIn and Remote boards for the roles on your resumes.</div>
</div></div>
<div class="wrap"><div class="col">
<div class="steps" id="steps"></div>
<p class="note" id="note"></p>
</div></div>
</div>
<script>
const POLL = {poll_ms};
const STALL = {stall_ms};
const steps = document.getElementById('steps');
const note = document.getElementById('note');
function esc(s){{const d=document.createElement('div');d.textContent=s==null?'':s;return d.innerHTML;}}
let lastPayload = '';
let lastChange = Date.now();

function draw(list) {{
  steps.innerHTML = list.map(s => `
    <div class="step" data-state="${{s.state}}">
      <span class="dot"></span>
      <span class="name">${{esc(s.source)}}${{s.lane && s.lane !== 'worldwide' ? ' · ' + esc(s.lane) : ''}} / ${{esc(s.role)}}</span>
      <span class="found">${{s.state === 'failed' ? 'failed'
        : s.state === 'pending' ? 'waiting'
        : s.found + ' found'}}</span>
    </div>`).join('');
}}

async function tick() {{
  let body;
  try {{
    const r = await fetch('/api/runs/{run_id}');
    if (!r.ok) throw new Error('gone');
    body = await r.json();
  }} catch (e) {{
    note.textContent = 'Lost contact with the app.';
    note.className = 'note bad';
    return;
  }}

  draw((body.progress && body.progress.steps) || []);

  const snapshot = JSON.stringify(body.progress || {{}});
  if (snapshot !== lastPayload) {{ lastPayload = snapshot; lastChange = Date.now(); }}

  if (body.status === 'OK') {{
    window.location = '/';
    return;
  }}
  if (body.status === 'FAILED') {{
    note.innerHTML = esc(body.error || 'The search failed.') +
      ' <a class="retry" href="#" onclick="again();return false">retry</a>';
    note.className = 'note bad';
    return;
  }}
  if (Date.now() - lastChange > STALL) {{
    note.innerHTML = 'This may have stopped. ' +
      '<a class="retry" href="#" onclick="again();return false">retry</a>';
    note.className = 'note bad';
  }} else {{
    const n = (body.progress && body.progress.scraped) || 0;
    const dropped = (body.progress && body.progress.dropped) || 0;
    note.textContent = !n ? 'starting'
      : dropped > 0 ? n + ' found so far · ' + dropped + ' hidden (on-site elsewhere)'
      : n + ' found so far';
    note.className = 'note';
  }}
  setTimeout(tick, POLL);
}}

async function again() {{
  try {{
    const r = await fetch('/api/runs', {{method: 'POST'}});
    const body = await r.json();
    if (body.run_id) {{ window.location = '/searching/' + body.run_id; return; }}
    note.textContent = body.error || 'Could not start a new search.';
    note.className = 'note bad';
  }} catch (e) {{
    note.textContent = 'Could not reach the app to retry.';
    note.className = 'note bad';
  }}
}}

tick();
</script>
</body>
</html>
"""


def render(run_id: int) -> str:
    return _HTML.format(css=_CSS, run_id=int(run_id),
                        poll_ms=_POLL_MS, stall_ms=_STALL_MS)
