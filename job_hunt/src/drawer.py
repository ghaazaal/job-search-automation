"""The shared role-detail drawer.

One drawer, every page — the tracker's ROLE button and the map's REVIEW
ROLE open the same panel (design handoff, screen 2). Self-contained:
`dw-` prefixed classes so no page's own styles collide, and its own POST
wiring on `data-dw-*` attributes so a page's generic click handlers never
double-fire.

Two load-bearing details from the handoff: the panel is `height:100%`
with `box-sizing:border-box` (100vh pushed the footer below short
windows), and MARK APPLIED navigates to the tracker — the label says so,
so the jump is not a surprise.

The payload shape is the map's `_drawer_payload`: `{key: {name, why,
roles:[{title, tab, meta, band, reason, matched, gaps, captured, url,
rid, app_status}]}}`. Rule 2 and rule 3 are enforced in the render
function: a band renders only beside its reason, and an uncaptured
listing renders the dashed "Not checked yet" block, never a pill.
"""

DRAWER_CSS = """
.dw-shell{position:fixed;inset:0;z-index:60;display:flex;justify-content:flex-end}
.dw-hidden{display:none}
.dw-scrim{position:absolute;inset:0;background:rgba(42,51,66,.26)}
.dw-panel{position:relative;width:min(560px,94vw);height:100%;box-sizing:border-box;overflow:auto;overscroll-behavior:contain;background:#FFFDF8;border-left:1px solid #CBBFA5;padding:28px 32px 32px;box-shadow:-18px 0 40px -26px rgba(42,51,66,.55)}
.dw-crumbrow{display:flex;align-items:center;justify-content:space-between;gap:12px}
.dw-crumb{font:500 10.5px/1 'JetBrains Mono',monospace;color:#6E7787;letter-spacing:.1em}
.dw-esc{border:1px solid #E0D8C4;background:#FFFDF8;border-radius:3px;color:#8A93A1;font:400 11px/1 'JetBrains Mono',monospace;padding:6px 9px;white-space:nowrap;cursor:pointer}
.dw-esc:hover{border-color:#CBBFA5;color:#3A4557}
.dw-title{font:500 24px/1.25 Inter,sans-serif;color:#1F2937;letter-spacing:-.02em;margin-top:16px}
.dw-meta{font:400 11.5px/1.75 'JetBrains Mono',monospace;color:#6E7787;letter-spacing:.05em;margin-top:9px}
.dw-tabs{display:flex;flex-wrap:wrap;gap:7px;margin-top:16px;padding-top:14px;border-top:1px solid #EBE3D2}
.dw-tab{display:inline-block;padding:6px 11px;border:1px solid #E0D8C4;background:transparent;border-radius:2px;font:400 11.5px/1.2 Inter,sans-serif;color:#6E7787;white-space:nowrap;cursor:pointer}
.dw-tab:hover{border-color:#CBBFA5;color:#3A4557}
.dw-tab-on{border-color:#2E7D5B;background:#EAF2ED;color:#215E44;font-weight:500}
.dw-band{display:flex;align-items:flex-start;gap:13px;margin-top:18px;padding:15px 16px;background:#F4EFE1;border:1px solid #E0D8C4;border-radius:3px}
.dw-pill{flex:none;font:700 10px/1 'JetBrains Mono',monospace;letter-spacing:.11em;border-radius:2px}
.dw-pill-strong{padding:5px 11px;background:#2E7D5B;color:#FFFDF8}
.dw-pill-partial{padding:4px 10px;border:1px solid #2A5F86;color:#2A5F86}
.dw-pill-stretch{padding:4px 10px;border:1px solid #B9C4D0;color:#6E7787}
.dw-reason{font:400 14.5px/1.6 Inter,sans-serif;color:#3A4557;text-wrap:pretty}
.dw-unchecked{display:flex;align-items:center;gap:12px;margin-top:18px;padding:11px 13px;border:1px dashed #C9BFA8;border-radius:3px;background:#F4EFE1}
.dw-unchecked span{font:400 13.5px/1.6 Inter,sans-serif;color:#6E7787;text-wrap:pretty}
.dw-unchecked b{color:#3A4557;font-weight:400}
.dw-grid{display:grid;grid-template-columns:1fr 1fr;gap:22px;margin-top:24px}
.dw-gh{font:500 9.5px/1.4 'JetBrains Mono',monospace;color:#6E7787;letter-spacing:.11em;padding-bottom:10px}
.dw-gh-m{border-bottom:1px solid #2E7D5B}
.dw-gh-g{border-bottom:1px dashed #C9BFA8}
.dw-chips{display:flex;flex-wrap:wrap;gap:7px;margin-top:13px}
.dw-chip{display:inline-block;white-space:nowrap;font:400 12.5px/1.2 Inter,sans-serif;padding:5px 10px;border-radius:2px}
.dw-chip-m{background:#EAF2ED;border:1px solid #C3DACD;color:#215E44}
.dw-chip-g{background:transparent;border:1px dashed #C9BFA8;color:#4C5768}
.dw-gnote{font:400 12.5px/1.6 Inter,sans-serif;color:#8A93A1;margin-top:12px;text-wrap:pretty}
.dw-why{margin-top:24px;padding-top:18px;border-top:1px solid #EBE3D2}
.dw-why-h{font:600 22px/1 Caveat,cursive;color:#2E7D5B}
.dw-why-b{font:400 13.5px/1.65 Inter,sans-serif;color:#4C5768;margin-top:9px;text-wrap:pretty}
.dw-foot{display:flex;align-items:center;gap:10px;margin-top:22px;padding-top:16px;border-top:1px solid #EBE3D2;flex-wrap:wrap}
.dw-open{white-space:nowrap;padding:10px 16px;background:#D6482B;border:1px solid #D6482B;border-radius:3px;color:#FFFDF8;font:500 11.5px/1 'JetBrains Mono',monospace;letter-spacing:.07em;cursor:pointer;text-decoration:none}
.dw-open:hover{background:#A83519;border-color:#A83519;color:#FFFDF8}
.dw-sec{padding:10px 14px;border:1px solid #D5CDB9;background:transparent;border-radius:3px;color:#4C5768;font:400 11.5px/1 'JetBrains Mono',monospace;letter-spacing:.07em;white-space:nowrap;cursor:pointer;text-decoration:none}
.dw-sec:hover{border-color:#2E7D5B;color:#2E7D5B}
.dw-next{margin-left:auto;padding:10px 13px;border:1px solid transparent;background:transparent;border-radius:3px;color:#8A93A1;font:400 11.5px/1 'JetBrains Mono',monospace;letter-spacing:.07em;white-space:nowrap;cursor:pointer}
.dw-next:hover{color:#3A4557}
.dw-fetch{flex:none;margin-left:auto;padding:7px 13px;border:1px solid #D5CDB9;background:#FFFDF8;border-radius:3px;color:#D6482B;font:500 11px/1 'JetBrains Mono',monospace;letter-spacing:.06em;white-space:nowrap;cursor:pointer}
.dw-fetch:hover{border-color:#D6482B}
"""

DRAWER_MOUNT = '<div id="dw" class="dw-shell dw-hidden"></div>'

_JS = """
(function () {
  'use strict';
  var DATA = __DW_DATA__;
  var openKey = null, roleIdx = 0;
  var shell = document.getElementById('dw');

  function esc(s){var d=document.createElement('div');d.textContent=s==null?'':s;return d.innerHTML;}
  function pillClass(b){return b==='STRONG FIT'?'dw-pill-strong':b==='PARTIAL FIT'?'dw-pill-partial':'dw-pill-stretch';}

  function render(){
    var co = DATA[openKey]; if(!co){return;}
    var r = co.roles[roleIdx];
    var many = co.roles.length > 1;
    var tabs = many ? '<div class="dw-tabs">' + co.roles.map(function(x,i){
      return '<button type="button" class="dw-tab '+(i===roleIdx?'dw-tab-on':'')+'" data-dw-tab="'+i+'">'+esc(x.tab)+'</button>';
    }).join('') + '</div>' : '';
    var fit;
    if(!r.captured){
      fit = '<div class="dw-unchecked"><span><b>Not checked yet.</b> This listing arrived '
        + 'without a description, so no skills have been compared against it.</span>'
        + '<button type="button" class="dw-fetch">FETCH POSTING</button></div>';
    } else if(r.band && r.reason){
      fit = '<div class="dw-band"><span class="dw-pill '+pillClass(r.band)+'">'+esc(r.band)+'</span>'
        + '<span class="dw-reason">'+esc(r.reason)+'</span></div>';
    } else { fit = ''; }
    var chips = function(a,c){return a.length ? a.map(function(x){
      return '<span class="dw-chip '+c+'">'+esc(x)+'</span>';}).join('')
      : '<span class="dw-gnote">none</span>';};
    var grid = r.captured ? '<div class="dw-grid"><div>'
      + '<div class="dw-gh dw-gh-m">MATCHED FROM YOUR RESUME</div>'
      + '<div class="dw-chips">'+chips(r.matched,'dw-chip-m')+'</div></div>'
      + '<div><div class="dw-gh dw-gh-g">IN THE POST, NOT ON YOUR RESUME</div>'
      + '<div class="dw-chips">'+chips(r.gaps,'dw-chip-g')+'</div>'
      + (r.gaps.length?'<div class="dw-gnote">Named in the posting, not found on your resume. Not a rejection \\u2014 worth a line in the cover letter.</div>':'')
      + '</div></div>' : '';
    var why = co.why ? '<div class="dw-why"><div class="dw-why-h">why this company</div>'
      + '<div class="dw-why-b">'+esc(co.why)+'</div></div>' : '';
    var nextLabel = roleIdx < co.roles.length-1 ? 'NEXT ROLE HERE \\u2192' : '__DW_BACK__ \\u2192';
    var track = r.rid == null ? ''
      : r.app_status
        ? '<a class="dw-sec" href="/activity">IN TRACKER \\u00b7 '+esc(r.app_status)+'</a>'
        : '<button type="button" class="dw-sec" data-dw-status="SAVED" data-dw-role="'+esc(r.rid)+'">ADD TO TRACKER</button>'
          + '<button type="button" class="dw-sec" data-dw-status="APPLIED" data-dw-role="'+esc(r.rid)+'">MARK APPLIED \\u00b7 GOES TO TRACKER</button>';
    var posting = r.url ? '<a class="dw-open" href="'+esc(r.url)+'" target="_blank" rel="noopener">OPEN POSTING \\u2197</a>' : '';
    shell.innerHTML = '<div class="dw-scrim" data-dw-close="1"></div><div class="dw-panel">'
      + '<div class="dw-crumbrow"><div class="dw-crumb">'+esc(co.name.toUpperCase())
      + ' \\u00b7 ROLE '+(roleIdx+1)+' OF '+co.roles.length+'</div>'
      + '<button type="button" class="dw-esc" data-dw-close="1">ESC</button></div>'
      + '<div class="dw-title">'+esc(r.title)+'</div>'
      + '<div class="dw-meta">'+esc(r.meta)+'</div>'
      + tabs + fit + grid + why
      + '<div class="dw-foot">'+posting+track
      + '<button type="button" class="dw-next" data-dw-next="1">'+nextLabel+'</button></div></div>';
    shell.classList.remove('dw-hidden');
    document.body.style.overflow = 'hidden';
  }

  function close(){
    shell.classList.add('dw-hidden');
    shell.innerHTML = '';
    openKey = null;
    document.body.style.overflow = '';
  }

  async function post(roleId, status){
    var r = await fetch('/api/roles/'+encodeURIComponent(roleId)+'/status', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({status: status})});
    return r.ok;
  }

  document.addEventListener('click', function(e){
    if(e.target.closest('[data-dw-close]')){ close(); return; }
    var t = e.target.closest('[data-dw-tab]');
    if(t){ roleIdx = parseInt(t.getAttribute('data-dw-tab'),10); render(); return; }
    var n = e.target.closest('[data-dw-next]');
    if(n){
      var co = DATA[openKey];
      if(co && roleIdx < co.roles.length-1){ roleIdx++; render(); } else { close(); }
      return;
    }
    var s = e.target.closest('[data-dw-status]');
    if(s){
      var status = s.getAttribute('data-dw-status');
      post(s.getAttribute('data-dw-role'), status).then(function(ok){
        if(!ok){ alert('That did not save. Try again.'); return; }
        if(status === 'APPLIED'){ window.location = '/activity'; }
        else { window.location.reload(); }
      });
    }
  });
  document.addEventListener('keydown', function(e){
    if(e.key === 'Escape' && openKey !== null){ close(); }
  });

  window.Drawer = {
    open: function(key, idx){ openKey = key; roleIdx = idx || 0; render(); },
    isOpen: function(){ return openKey !== null; }
  };
})();
"""


def drawer_js(payload_json: str, back_label: str = "BACK TO MAP") -> str:
    """The drawer script with its data payload inlined.

    `payload_json` must already be `</`-escaped by the caller (every page
    builds it with json.dumps(...).replace("</", "<\\\\/")). `back_label`
    is what the next-control says on the last role — it closes the
    drawer, and the label must name the page underneath."""
    return (_JS.replace("__DW_DATA__", payload_json)
                .replace("__DW_BACK__", back_label))
