"""The shared role-detail drawer.

One drawer, every page — the tracker's ROLE button and the map's REVIEW
ROLE open the same panel (design handoff, screen 2). Self-contained:
`dw-` prefixed classes so no page's own styles collide, and its own POST
wiring on `data-dw-*` attributes so a page's generic click handlers never
double-fire.

Two load-bearing details from the handoff: the panel is `height:100%`
with `box-sizing:border-box` (100vh pushed the footer below short
windows).

Laid out for the job, in order (UX pass, 2026-10-15): decide without
leaving the app (the posting text loads into the panel), then act in
the order the work happens - APPLY ON THEIR SITE, and on return a
"Did you apply?" prompt, because the app cannot see the
employer's site and asking beats relying on memory (Handshake and cord
ask the same way). PREV / NEXT (or the arrow keys) walk the page's list
without closing the panel, and NOT FOR ME hides with an UNDO and moves
straight on. On the map nothing reloads, so you keep your place.

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
.dw-foot{margin-top:20px;padding:16px 0 4px;border-top:1px solid #EBE3D2}
.dw-open{white-space:nowrap;padding:10px 16px;background:#D6482B;border:1px solid #D6482B;border-radius:3px;color:#FFFDF8;font:500 11.5px/1 'JetBrains Mono',monospace;letter-spacing:.07em;cursor:pointer;text-decoration:none}
.dw-open:hover{background:#A83519;border-color:#A83519;color:#FFFDF8}
.dw-sec{padding:10px 14px;border:1px solid #D5CDB9;background:transparent;border-radius:3px;color:#4C5768;font:400 11.5px/1 'JetBrains Mono',monospace;letter-spacing:.07em;white-space:nowrap;cursor:pointer;text-decoration:none}
.dw-sec:hover{border-color:#2E7D5B;color:#2E7D5B}
.dw-next{margin-left:auto;padding:10px 13px;border:1px solid transparent;background:transparent;border-radius:3px;color:#8A93A1;font:400 11.5px/1 'JetBrains Mono',monospace;letter-spacing:.07em;white-space:nowrap;cursor:pointer}
.dw-next:hover{color:#3A4557}
.dw-fetch{flex:none;margin-left:auto;padding:7px 13px;border:1px solid #D5CDB9;background:#FFFDF8;border-radius:3px;color:#D6482B;font:500 11px/1 'JetBrains Mono',monospace;letter-spacing:.06em;white-space:nowrap;cursor:pointer}
.dw-fetch:hover{border-color:#D6482B}
.dw-walk{display:flex;align-items:center;gap:6px}
.dw-esc:disabled{opacity:.4;cursor:default}
.dw-row{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.dw-row-q{gap:4px 14px;margin-top:12px}
.dw-q{padding:6px 0;border:0;background:transparent;color:#6E7787;font:500 11px/1 'JetBrains Mono',monospace;letter-spacing:.07em;white-space:nowrap;cursor:pointer;text-decoration:none}
.dw-q:hover{color:#D6482B}
.dw-in{color:#3B7EA8}
.dw-note{margin-top:12px;font:400 13px/1.5 Inter,sans-serif;color:#215E44}
.dw-note a{color:#D6482B}
.dw-ask{margin-top:16px;padding:14px 16px;border:1px solid #2E7D5B;background:#EAF2ED;border-radius:3px}
.dw-ask-t{font:600 22px/1 Caveat,cursive;color:#215E44}
.dw-ask-b{font:400 13px/1.55 Inter,sans-serif;color:#3A4557;margin-top:6px}
.dw-ask-a{display:flex;gap:10px;margin-top:12px;flex-wrap:wrap}
.dw-post{margin-top:24px;padding-top:18px;border-top:1px solid #EBE3D2}
.dw-gh-p{border-bottom:1px solid #EBE3D2}
.dw-post-b{font:400 13.5px/1.65 Inter,sans-serif;color:#3A4557;margin-top:12px;white-space:pre-line;overflow-wrap:anywhere}
.dw-clamp{max-height:15em;overflow:hidden;-webkit-mask-image:linear-gradient(#000 70%,transparent);mask-image:linear-gradient(#000 70%,transparent)}
.dw-more{margin-top:8px;padding:6px 0;border:0;background:transparent;color:#D6482B;font:500 11px/1 'JetBrains Mono',monospace;letter-spacing:.07em;cursor:pointer}
.dw-gone{display:none}
.dw-toast{position:fixed;left:50%;bottom:26px;transform:translateX(-50%);z-index:70;display:flex;align-items:center;gap:16px;padding:11px 14px 11px 18px;background:#2A3342;color:#FFFDF8;border-radius:4px;box-shadow:0 8px 24px -12px rgba(42,51,66,.6);font:400 13.5px/1.4 Inter,sans-serif;max-width:min(560px,92vw)}
.dw-toast button{flex:none;border:1px solid rgba(255,253,248,.4);background:transparent;color:#FFFDF8;border-radius:3px;padding:6px 11px;font:500 11px/1 'JetBrains Mono',monospace;letter-spacing:.07em;cursor:pointer}
"""

DRAWER_MOUNT = '<div id="dw" class="dw-shell dw-hidden"></div>'

_JS = """
(function () {
  'use strict';
  var DATA = __DW_DATA__;
  var RELOAD = __DW_RELOAD__;
  // Companies in the order the page lists them, so NEXT walks the list.
  var ORDER = Object.keys(DATA);
  var openKey = null, roleIdx = 0;
  var shell = document.getElementById('dw');
  var postings = {};   // rid -> posting text, fetched the first time it is shown
  var note = '';       // one line confirming the last action, under the buttons
  var undo = null;     // a NOT FOR ME still waiting to be saved
  // Set when APPLY ON THEIR SITE opens the posting. The app cannot see the
  // employer's site, so it asks on return (Handshake and cord do the same).
  // Kept in sessionStorage so a reload while away does not lose it.
  var ask = null;
  try { ask = JSON.parse(sessionStorage.getItem('dw-ask') || 'null'); } catch (e) { ask = null; }

  function esc(s){var d=document.createElement('div');d.textContent=s==null?'':s;return d.innerHTML;}
  function pillClass(b){return b==='STRONG FIT'?'dw-pill-strong':b==='PARTIAL FIT'?'dw-pill-partial':'dw-pill-stretch';}
  function saveAsk(){try{if(ask){sessionStorage.setItem('dw-ask',JSON.stringify(ask));}else{sessionStorage.removeItem('dw-ask');}}catch(e){}}
  function current(){var co=DATA[openKey];return co?co.roles[roleIdx]:null;}
  function findRole(rid){
    for(var i=0;i<ORDER.length;i++){var rs=DATA[ORDER[i]].roles;
      for(var j=0;j<rs.length;j++){if(String(rs[j].rid)===String(rid)){return [ORDER[i],j];}}}
    return null;
  }

  function postingBlock(r){
    if(!r.captured || r.rid == null){ return ''; }
    var text = postings[r.rid], body;
    if(text === undefined){
      postings[r.rid] = null;
      fetch('/api/roles/'+encodeURIComponent(r.rid)+'/posting')
        .then(function(x){return x.ok ? x.json() : {};})
        .catch(function(){return {};})
        .then(function(b){
          postings[r.rid] = (b && b.description) || '';
          var cur = current(), el = document.getElementById('dw-post');
          if(cur && cur.rid === r.rid && el){ el.outerHTML = postingBlock(r); }
        });
      text = null;
    }
    if(text === null){ body = '<div class="dw-gnote">Loading the posting&hellip;</div>'; }
    else if(text){ body = '<div class="dw-post-b dw-clamp">'+esc(text)+'</div>'
      + '<button type="button" class="dw-more" data-dw-more="1">READ THE WHOLE POSTING</button>'; }
    else { body = '<div class="dw-gnote">No posting text was stored for this role.</div>'; }
    return '<div class="dw-post" id="dw-post"><div class="dw-gh dw-gh-p">THE POSTING</div>'+body+'</div>';
  }

  function askBlock(r){
    if(!ask || r.rid == null || String(ask.rid) !== String(r.rid)){ return ''; }
    if(r.app_status && r.app_status !== 'SAVED'){ return ''; }
    return '<div class="dw-ask"><div class="dw-ask-t">Did you apply?</div>'
      + '<div class="dw-ask-b">This app cannot see the employer\\u2019s site, so it asks now, while you remember.</div>'
      + '<div class="dw-ask-a"><button type="button" class="dw-open" data-dw-status="APPLIED" data-dw-role="'+esc(r.rid)+'">YES, MARK APPLIED</button>'
      + '<button type="button" class="dw-sec" data-dw-notyet="1">NOT YET</button></div></div>';
  }

  function render(){
    var co = DATA[openKey]; if(!co){ close(); return; }
    if(roleIdx >= co.roles.length){ roleIdx = co.roles.length - 1; }
    var r = co.roles[roleIdx];
    var many = co.roles.length > 1;
    var tabs = many ? '<div class="dw-tabs">' + co.roles.map(function(x,i){
      return '<button type="button" class="dw-tab '+(i===roleIdx?'dw-tab-on':'')+'" data-dw-tab="'+i+'">'+esc(x.tab)+'</button>';
    }).join('') + '</div>' : '';
    var fit;
    if(!r.captured){
      // No fetch button: nothing can fetch a description after the run.
      fit = '<div class="dw-unchecked"><span><b>Not checked yet.</b> This listing arrived '
        + 'without a description, so no skills have been compared against it. '
        + (r.url ? 'Open the posting to read it yourself.' : '') + '</span></div>';
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

    // Walking the list without closing the panel: decide, move on.
    var pos = ORDER.indexOf(openKey);
    var walk = ORDER.length > 1
      ? '<button type="button" class="dw-esc" data-dw-step="-1" title="Previous (\\u2190 or K)"'+(pos<=0?' disabled':'')+'>\\u2190 PREV</button>'
      + '<button type="button" class="dw-esc" data-dw-step="1" title="Next (\\u2192 or J)"'+(pos>=ORDER.length-1?' disabled':'')+'>NEXT \\u2192</button>' : '';
    var where = ORDER.length > 1 ? ' \\u00b7 '+(pos+1)+' OF '+ORDER.length : '';

    // The actions follow the order of the job: apply, then record it.
    // One filled button; everything else is quieter.
    var tracked = r.app_status;
    var pending = !tracked || tracked === 'SAVED';
    var apply = r.url ? '<a class="dw-open" href="'+esc(r.url)+'" target="_blank" rel="noopener"'
      + (pending && r.rid != null ? ' data-dw-apply="1"' : '') + '>'
      + (pending ? 'APPLY ON THEIR SITE' : 'OPEN POSTING') + ' \\u2197</a>' : '';
    var save = r.rid == null ? ''
      : tracked ? '<a class="dw-q dw-in" href="/activity">IN TRACKER \\u00b7 '+esc(tracked)+'</a>'
      : '<button type="button" class="dw-q" data-dw-status="SAVED" data-dw-role="'+esc(r.rid)+'">SAVE FOR LATER</button>';
    var applied = (r.rid != null && pending)
      ? '<button type="button" class="dw-q" data-dw-status="APPLIED" data-dw-role="'+esc(r.rid)+'">ALREADY APPLIED</button>' : '';
    var hide = (r.rid != null && !tracked)
      ? '<button type="button" class="dw-q" data-dw-hide="1" title="Hide this role from the map">NOT FOR ME</button>' : '';
    // A path toward this one job needs the posting's text to quote from.
    var learn = (r.rid != null && r.captured)
      ? '<a class="dw-q" href="/learn/role/'+encodeURIComponent(r.rid)+'">LEARNING PATH FOR THIS JOB</a>' : '';

    shell.innerHTML = '<div class="dw-scrim" data-dw-close="1"></div><div class="dw-panel">'
      + '<div class="dw-crumbrow"><div class="dw-crumb">'+esc(co.name.toUpperCase()) + where
      + (many ? ' \\u00b7 ROLE '+(roleIdx+1)+' OF '+co.roles.length : '') + '</div>'
      + '<div class="dw-walk">' + walk
      + '<button type="button" class="dw-esc" data-dw-close="1" title="Close (Esc)">\\u2715 __DW_BACK__</button></div></div>'
      + askBlock(r)
      + '<div class="dw-title">'+esc(r.title)+'</div>'
      + '<div class="dw-meta">'+esc(r.meta)+'</div>'
      + tabs + fit
      + '<div class="dw-foot"><div class="dw-row">'+apply+'</div>'
      + '<div class="dw-row dw-row-q">'+save+applied+hide+learn+'</div>'
      + (note ? '<div class="dw-note">'+note+'</div>' : '') + '</div>'
      + grid + postingBlock(r) + why + '</div>';
    shell.classList.remove('dw-hidden');
    document.body.style.overflow = 'hidden';
  }

  function close(){
    shell.classList.add('dw-hidden');
    shell.innerHTML = '';
    openKey = null; note = '';
    document.body.style.overflow = '';
  }

  function open(key, idx){
    openKey = key; roleIdx = idx || 0; note = '';
    render();
    var p = shell.querySelector('.dw-panel'); if(p){ p.scrollTop = 0; }
  }

  function step(d){
    var p = ORDER.indexOf(openKey) + d;
    if(p >= 0 && p < ORDER.length){ open(ORDER[p], 0); }
  }

  function post(roleId, status, keepalive){
    return fetch('/api/roles/'+encodeURIComponent(roleId)+'/status', {
      method:'POST', keepalive: !!keepalive, headers:{'Content-Type':'application/json'},
      body: JSON.stringify({status: status})}).then(function(r){return r.ok;}, function(){return false;});
  }

  // The page under the panel shows the same roles; keep it in step
  // without a reload, which would close the panel and lose your place.
  function cardOf(rid){
    var b = document.querySelector('.card [data-role="'+rid+'"], .lead [data-role="'+rid+'"]');
    return b ? b.closest('.card,.lead') : null;
  }
  function syncPage(rid, status, wasTracked){
    document.querySelectorAll('[data-role="'+rid+'"][data-status="SAVED"]').forEach(function(b){
      var a = document.createElement('a');
      a.className = 'tracked'; a.href = '/activity';
      a.textContent = 'IN TRACKER \\u00b7 ' + status;
      b.replaceWith(a);
    });
    var badge = document.querySelector('.sh-tab[href="/activity"] .sh-count');
    if(badge && !wasTracked){ badge.textContent = (parseInt(badge.textContent,10) || 0) + 1; }
  }

  function flushUndo(){
    var u = undo; if(!u){ return; }
    undo = null; clearTimeout(u.timer); u.toast.remove();
    post(u.role.rid, 'HIDDEN', true).then(function(ok){
      if(!ok){ restore(u); alert('That did not save. Try again.'); }
    });
  }
  function restore(u){
    var co = DATA[u.key];
    co.roles.splice(u.idx, 0, u.role);
    if(ORDER.indexOf(u.key) < 0){ ORDER.splice(u.pos, 0, u.key); }
    if(u.card){ u.card.classList.remove('dw-gone'); }
  }
  function notForMe(){
    var r = current(); if(!r){ return; }
    flushUndo();
    var key = openKey, idx = roleIdx, co = DATA[key], pos = ORDER.indexOf(key);
    co.roles.splice(idx, 1);
    var card = null;
    if(!co.roles.length){
      ORDER.splice(pos, 1);
      card = cardOf(r.rid);
      if(card){ card.classList.add('dw-gone'); }
    }
    var toast = document.createElement('div');
    toast.className = 'dw-toast'; toast.setAttribute('role', 'status');
    toast.innerHTML = '<span>Hidden: '+esc(r.title)+'</span><button type="button" data-dw-undo="1">UNDO</button>';
    document.body.appendChild(toast);
    undo = {role: r, key: key, idx: idx, pos: pos, card: card, toast: toast,
            timer: setTimeout(flushUndo, 6000)};
    // Straight on to the next decision.
    if(co.roles.length){ open(key, Math.min(idx, co.roles.length - 1)); }
    else if(ORDER.length){ open(ORDER[Math.min(pos, ORDER.length - 1)], 0); }
    else { close(); }
  }

  function showAsk(){
    if(!ask){ return; }
    var hit = findRole(ask.rid); if(!hit){ return; }
    if(openKey !== hit[0] || roleIdx !== hit[1]){ openKey = hit[0]; roleIdx = hit[1]; note = ''; }
    render();
  }

  document.addEventListener('click', function(e){
    if(e.target.closest('[data-dw-undo]') && undo){
      var u = undo; undo = null; clearTimeout(u.timer); u.toast.remove();
      restore(u); open(u.key, u.idx); return;
    }
    if(e.target.closest('[data-dw-close]')){ close(); return; }
    var t = e.target.closest('[data-dw-tab]');
    if(t){ roleIdx = parseInt(t.getAttribute('data-dw-tab'),10); note = ''; render(); return; }
    var w = e.target.closest('[data-dw-step]');
    if(w){ step(parseInt(w.getAttribute('data-dw-step'),10)); return; }
    var m = e.target.closest('[data-dw-more]');
    if(m){
      var b = shell.querySelector('.dw-post-b');
      if(b){ var shut = b.classList.toggle('dw-clamp'); m.textContent = shut ? 'READ THE WHOLE POSTING' : 'SHOW LESS'; }
      return;
    }
    if(e.target.closest('[data-dw-apply]')){
      // Not re-rendered here: removing the link mid-click can cancel it.
      var cur = current(); if(cur){ ask = {rid: cur.rid}; saveAsk(); }
      return;
    }
    if(e.target.closest('[data-dw-notyet]')){ ask = null; saveAsk(); render(); return; }
    if(e.target.closest('[data-dw-hide]')){ notForMe(); return; }
    var s = e.target.closest('[data-dw-status]');
    if(s){
      var status = s.getAttribute('data-dw-status'), rid = s.getAttribute('data-dw-role');
      post(rid, status).then(function(ok){
        if(!ok){ alert('That did not save. Try again.'); return; }
        if(ask && String(ask.rid) === String(rid)){ ask = null; saveAsk(); }
        if(RELOAD){ window.location.reload(); return; }
        var hit = findRole(rid), was = null;
        if(hit){ var role = DATA[hit[0]].roles[hit[1]]; was = role.app_status; role.app_status = status; }
        syncPage(rid, status, was);
        note = 'On your tracker under ' + status + '. <a href="/activity">Open the tracker</a>';
        render();
      });
    }
  });
  document.addEventListener('keydown', function(e){
    if(openKey === null){ return; }
    if(e.key === 'Escape'){ close(); return; }
    var tag = (e.target.tagName || '').toUpperCase();
    if(tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT'){ return; }
    if(e.key === 'ArrowRight' || e.key === 'j'){ step(1); e.preventDefault(); }
    else if(e.key === 'ArrowLeft' || e.key === 'k'){ step(-1); e.preventDefault(); }
  });
  document.addEventListener('visibilitychange', function(){
    if(document.visibilityState === 'visible'){ showAsk(); }
  });
  window.addEventListener('pagehide', flushUndo);
  // Back from the posting after a reload: ask now.
  if(ask){ setTimeout(showAsk, 0); }

  window.Drawer = {
    open: open,
    isOpen: function(){ return openKey !== null; }
  };
})();
"""


def drawer_js(payload_json: str, back_label: str = "BACK TO MAP",
              reload_on_change: bool = False) -> str:
    """The drawer script with its data payload inlined.

    `payload_json` must already be `</`-escaped by the caller (every page
    builds it with json.dumps(...).replace("</", "<\\\\/")). `back_label`
    names the page underneath, on the close button. `reload_on_change`
    reloads after a status change, for a page (the tracker board) whose
    layout depends on status; the map stays put so triage keeps its place.
    Key order in the payload is the order NEXT walks."""
    return (_JS.replace("__DW_DATA__", payload_json)
                .replace("__DW_BACK__", back_label)
                .replace("__DW_RELOAD__", "true" if reload_on_change else "false"))
