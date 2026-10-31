// 1.9.0 Pro page: nine Batch 2 tools, Settings › Advanced toggles, PC menu + phone apps grid.
(function () {
  'use strict';
  const $ = (s, r) => (r || document).querySelector(s);
  const $$ = (s, r) => Array.from((r || document).querySelectorAll(s));
  const api = (b) => fetch('/api/pro', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b || {}) })
    .then((r) => r.json()).catch(() => ({ ok: false, error: 'Ped Bot is not reachable.' }));
  const esc = (t) => String(t == null ? '' : t).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const P = 'fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"';
  const svg = (d) => '<svg width="22" height="22" viewBox="0 0 24 24" ' + P + '>' + d + '</svg>';
  const ICONS = {
    phone: '<rect x="7" y="2" width="10" height="20" rx="2"/><path d="M11 18h2"/>',
    pc: '<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/>',
    brain: '<path d="M9.5 2A2.5 2.5 0 0 1 12 4.5v15a2.5 2.5 0 0 1-4.96.44 2.5 2.5 0 0 1-2.96-3.08 3 3 0 0 1-.34-5.58 2.5 2.5 0 0 1 1.32-4.24A2.5 2.5 0 0 1 9.5 2z"/>',
    team: '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
    mic: '<rect x="9" y="2" width="6" height="12" rx="3"/><path d="M5 10a7 7 0 0 0 14 0M12 19v3"/>',
    cam: '<path d="M23 7l-7 5 7 5z"/><rect x="1" y="5" width="15" height="14" rx="2"/>',
    code: '<path d="m16 18 6-6-6-6M8 6l-6 6 6 6"/>',
    home: '<path d="M3 11 12 3l9 8"/><path d="M5 10v10h14V10"/>',
    cash: '<rect x="2" y="6" width="20" height="12" rx="2"/><circle cx="12" cy="12" r="3"/>',
  };
  const FEATURES = [
    { k: 'phone', name: 'Phone control', desc: 'Tap and type on this phone after you Allow each step.', chip: 'Phone', flag: 'phone_control', icon: 'phone' },
    { k: 'autopilot', name: 'PC autopilot', desc: 'Sees the screen, then clicks — one Allow per step.', chip: 'PC', flag: 'pc_autopilot', icon: 'pc' },
    { k: 'memory', name: 'Long-term memory', desc: 'Each bot keeps facts. View, edit, delete, export.', chip: 'Bots', flag: 'memory', icon: 'brain' },
    { k: 'team', name: 'Team tasks', desc: 'Planner, workers and a checker. Live progress board.', chip: 'Bots', flag: 'team', icon: 'team' },
    { k: 'voice', name: 'My real voice', desc: 'Local clone on this PC. Needs Lab › My voice consent.', chip: 'Voice', flag: 'voice_clone', icon: 'mic' },
    { k: 'live', name: 'Live video avatar', desc: 'Virtual webcam for Zoom/Meet with an AI assistant label.', chip: 'Voice', flag: 'live_cam', icon: 'cam' },
    { k: 'skill', name: 'Self-coding skills', desc: 'Writes a plugin, tests it, goes live only after Approve.', chip: 'PC', flag: 'self_skills', icon: 'code' },
    { k: 'home', name: 'Hey Ped + home', desc: 'Music, volume, lock, timers, optional Home Assistant.', chip: 'Voice', flag: 'hey_home', icon: 'home' },
    { k: 'income', name: 'Income bots', desc: 'Finds public gigs and drafts proposals. You send them.', chip: 'Work', flag: 'income', icon: 'cash' },
  ];
  const native = () => window.PedroNative || null;
  const busy = (b, on) => { if (b) { b.disabled = on; b.classList.toggle('busy', on); } };
  let flags = {};

  function page() {
    let p = $('#pro190');
    if (p) return p;
    p = document.createElement('div'); p.id = 'pro190';
    p.innerHTML = '<div class="pro-head"><button type="button" class="pro-x" aria-label="Close"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 6 6 18M6 6l12 12"/></svg></button><b>Pro</b><span class="pro-pill">9 tools</span></div>' +
      '<div class="pro-chips"></div><div class="pro-body"></div>' +
      '<div class="pro-search"><svg width="18" height="18" viewBox="0 0 24 24" ' + P + '><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg><input id="pro-q" type="search" placeholder="Search Pro" autocomplete="off"></div>';
    document.body.appendChild(p);
    $('.pro-x', p).onclick = () => { p.remove(); };
    return p;
  }

  function chips(p, on) {
    const box = $('.pro-chips', p);
    const all = ['All', 'Phone', 'PC', 'Bots', 'Voice', 'Work'];
    box.innerHTML = all.map((c) => '<button type="button" data-c="' + c + '"' + (c === on ? ' class="on"' : '') + '>' + c + '</button>').join('');
    $$('button', box).forEach((b) => (b.onclick = () => { localStorage.pbProChip = b.dataset.c; home(b.dataset.c, $('#pro-q', p).value); }));
  }

  async function refreshFlags() {
    const r = await api({ tool: 'flags' });
    flags = (r && r.flags) || flags;
    return r;
  }

  function home(chip, q) {
    const p = page();
    chip = chip || localStorage.pbProChip || 'All';
    chips(p, chip);
    const body = $('.pro-body', p);
    q = (q || '').trim().toLowerCase();
    const rows = FEATURES.filter((f) => (chip === 'All' || f.chip === chip) && (!q || (f.name + f.desc).toLowerCase().includes(q)));
    body.innerHTML = '<div class="pro-sec"><span>Batch 2</span><svg width="16" height="16" viewBox="0 0 24 24" ' + P + '><path d="m9 6 6 6-6 6"/></svg></div>' +
      rows.map((f) => {
        const on = flags[f.flag];
        return '<div class="pro-row" data-k="' + f.k + '"><span class="pro-ic">' + svg(ICONS[f.icon]) + '</span><div class="pro-txt"><b>' + esc(f.name) + '</b><small>' + esc(f.desc) + '</small></div><button type="button" class="pro-go' + (on ? ' acc' : '') + '">' + (on ? 'Open' : 'Off') + '</button></div>';
      }).join('') + (rows.length ? '' : '<div class="pro-note">Nothing matches.</div>');
    $$('.pro-row', body).forEach((row) => (row.onclick = () => show(row.dataset.k)));
    const qi = $('#pro-q', p); qi.oninput = () => home(chip, qi.value);
  }

  const V = {
    async phone(body) {
      const how = await api({ tool: 'phone', action: 'how' });
      const a11y = native() && native().a11yStatus ? JSON.parse(native().a11yStatus() || '{}') : { enabled: false };
      body.innerHTML = '<div class="pro-sec"><span>Phone control</span></div>' +
        '<div class="pro-item"><small>Why this exists</small>' + esc((how.why) || 'Say “open YouTube and search X” and Ped Bot taps for you — only after you Allow.') + '</div>' +
        '<div class="pro-item"><small>Turn it on yourself</small>Android Settings › Accessibility › Ped Bot control. Ped Bot can then see the screen tree and tap. Every action shows Allow / Stop. A big red STOP stays on screen. Banking, password and payment screens are blocked.</div>' +
        '<div class="pro-item"><small>Status</small>' + (a11y.enabled ? 'Accessibility is on.' : 'Accessibility is off — open Android Settings to enable it.') + '</div>' +
        '<div class="pro-bar"><input id="ph-q" placeholder="e.g. open YouTube and search lofi beats"><button type="button" class="pro-go acc" id="ph-go">Plan</button></div>' +
        '<div class="pro-bar"><button type="button" class="pro-go" id="ph-set">Open Accessibility settings</button><button type="button" class="pro-go danger" id="ph-stop">STOP</button></div><div class="st-out"></div>';
      const out = $('.st-out', body);
      $('#ph-set', body).onclick = () => { if (native() && native().a11ySettings) native().a11ySettings(); };
      $('#ph-stop', body).onclick = () => { if (native() && native().a11yStop) native().a11yStop(); out.innerHTML = '<div class="pro-item">Stopped.</div>'; };
      $('#ph-go', body).onclick = async (e) => {
        busy(e.target, true);
        const r = await api({ tool: 'phone', action: 'plan', command: $('#ph-q', body).value });
        busy(e.target, false);
        if (!r.ok) { out.innerHTML = '<div class="pro-err">' + esc(r.error) + '</div>'; return; }
        out.innerHTML = (r.steps || []).map((s, i) => '<div class="pro-item"><small>Step ' + (i + 1) + ' · ' + esc(s.action) + '</small>' + esc(s.preview || s.say) + '</div>').join('') +
          '<button type="button" class="pro-go acc" id="ph-run">Run on this phone</button><div class="pro-note">' + esc(r.note || '') + '</div>';
        const run = $('#ph-run', out);
        if (run) run.onclick = () => {
          if (!native() || !native().a11yRun) { out.innerHTML += '<div class="pro-err">Open this on the Android app with Ped Bot control turned on.</div>'; return; }
          native().a11yRun(JSON.stringify(r.steps || []));
        };
      };
    },
    async autopilot(body) {
      const st = await api({ tool: 'autopilot', action: 'status' });
      body.innerHTML = '<div class="pro-sec"><span>PC autopilot</span></div>' +
        '<div class="pro-note">Step mode: you Allow every click. “Allow this task” runs the rest of this goal. Corner failsafe + Ctrl+Shift+Esc then P stop it. Logs: Documents\\Ped Bot Logs.</div>' +
        '<div class="pro-bar"><input id="ap-g" placeholder="e.g. open Notepad and type hello"><button type="button" class="pro-go acc" id="ap-go">Start (step)</button></div>' +
        '<div class="pro-bar"><button type="button" class="pro-go" id="ap-task">Allow this task</button><button type="button" class="pro-go danger" id="ap-stop">STOP</button></div>' +
        '<div id="ap-pend"></div><div id="ap-log"></div>';
      const draw = (s) => {
        const pend = s.pending;
        $('#ap-pend', body).innerHTML = pend ? '<div class="pro-allow"><b>' + esc(pend.preview) + '</b><div class="row"><button type="button" class="pro-go danger" id="ap-no">Stop</button><button type="button" class="pro-go acc" id="ap-yes">Allow</button></div></div>' : '';
        if (pend) {
          $('#ap-yes', body).onclick = async () => draw(await api({ tool: 'autopilot', action: 'allow' }));
          $('#ap-no', body).onclick = async () => draw(await api({ tool: 'autopilot', action: 'stop' }));
        }
        $('#ap-log', body).innerHTML = (s.log || []).slice(-8).map((l) => '<div class="pro-item"><small>log</small>' + esc(l) + '</div>').join('') || '<div class="pro-note">' + esc(s.stop_hint || '') + '</div>';
      };
      draw(st);
      $('#ap-go', body).onclick = async (e) => { busy(e.target, true); draw(await api({ tool: 'autopilot', action: 'start', goal: $('#ap-g', body).value, mode: 'step' })); busy(e.target, false); };
      $('#ap-task', body).onclick = async () => draw(await api({ tool: 'autopilot', action: 'allow', task: true }));
      $('#ap-stop', body).onclick = async () => draw(await api({ tool: 'autopilot', action: 'stop' }));
      const t = setInterval(async () => { if (!document.body.contains(body)) return clearInterval(t); draw(await api({ tool: 'autopilot', action: 'status' })); }, 1200);
    },
    async memory(body) {
      const bots = (await api({ tool: 'bots' })).bots || [];
      body.innerHTML = '<div class="pro-sec"><span>Long-term memory</span></div>' +
        '<div class="pro-bar"><select id="mm-b"></select><button type="button" class="pro-go" id="mm-ex">Export</button></div>' +
        '<div class="pro-bar"><input id="mm-t" placeholder="Add a fact"><button type="button" class="pro-go acc" id="mm-add">Save</button></div>' +
        '<div class="pro-bar"><input id="mm-q" placeholder="Search"><button type="button" class="pro-go" id="mm-s">Search</button></div><div class="st-list"></div>';
      const sel = $('#mm-b', body);
      (bots.length ? bots : [{ id: 'default', name: 'Default' }]).forEach((b) => { const o = document.createElement('option'); o.value = b.id; o.textContent = b.name; sel.appendChild(o); });
      const list = $('.st-list', body);
      const draw = (r) => {
        const items = r.items || r.facts || [];
        list.innerHTML = items.map((i) => '<div class="pro-item"><small>' + esc(i.source || '') + '</small><div contenteditable="true" data-id="' + esc(i.id) + '">' + esc(i.text) + '</div>' +
          '<div class="row" style="margin-top:8px;display:flex;gap:8px"><button type="button" class="pro-go" data-ed="' + esc(i.id) + '">Save edit</button><button type="button" class="pro-go danger" data-del="' + esc(i.id) + '">Delete</button></div></div>').join('') || '<div class="pro-note">No memories yet.</div>';
        $$('[data-del]', list).forEach((b) => (b.onclick = async () => { if (!confirm('Delete this memory?')) return; draw(await api({ tool: 'memory', action: 'delete', bot: sel.value, id: b.dataset.del, confirm: true })); }));
        $$('[data-ed]', list).forEach((b) => (b.onclick = async () => { const t = list.querySelector('[data-id="' + b.dataset.ed + '"]'); draw(await api({ tool: 'memory', action: 'edit', bot: sel.value, id: b.dataset.ed, text: t.textContent })); }));
      };
      const load = async () => draw(await api({ tool: 'memory', action: 'list', bot: sel.value }));
      sel.onchange = load; load();
      $('#mm-add', body).onclick = async () => { await api({ tool: 'memory', action: 'add', bot: sel.value, text: $('#mm-t', body).value }); $('#mm-t', body).value = ''; load(); };
      $('#mm-s', body).onclick = async () => draw(await api({ tool: 'memory', action: 'search', bot: sel.value, query: $('#mm-q', body).value, k: 8 }));
      $('#mm-ex', body).onclick = async () => { const r = await api({ tool: 'memory', action: 'export', bot: sel.value }); list.innerHTML = '<div class="pro-item"><small>' + esc(r.file || '') + '</small>' + esc(r.text || r.error) + '</div>'; };
    },
    async team(body) {
      body.innerHTML = '<div class="pro-sec"><span>Team tasks</span></div>' +
        '<div class="pro-note">Planner splits the work. Workers do the parts. Checker reviews. Failed parts retry up to 3 times.</div>' +
        '<textarea id="tm-g" rows="3" placeholder="e.g. research 3 Short ideas and write a hook for each" style="width:100%;background:#1c1d1f;color:#fff;border:1px solid #2f3033;border-radius:14px;padding:12px;font:inherit"></textarea>' +
        '<button type="button" class="pro-go acc" id="tm-go" style="margin:10px 0">Start team</button><div id="tm-board" class="pro-board"></div>';
      let job = '';
      const draw = (s) => {
        const board = s.board || [];
        $('#tm-board', body).innerHTML = board.map((r) => '<div class="pro-item"><div><b>' + esc(r.who) + '</b><small>' + esc(r.status) + '</small><div>' + esc(r.text) + '</div></div></div>').join('') +
          (s.answer ? '<div class="pro-item"><small>Final</small>' + esc(s.answer) + '</div>' : '') +
          (s.error ? '<div class="pro-err">' + esc(s.error) + '</div>' : '');
      };
      $('#tm-go', body).onclick = async (e) => {
        busy(e.target, true);
        const r = await api({ tool: 'team', action: 'start', goal: $('#tm-g', body).value });
        busy(e.target, false);
        job = r.job || ''; draw(r);
        const t = setInterval(async () => {
          if (!job || !document.body.contains(body)) return clearInterval(t);
          const s = await api({ tool: 'team', action: 'status', job }); draw(s);
          if (s.status && s.status !== 'working') clearInterval(t);
        }, 1500);
      };
    },
    async voice(body) {
      const r = await api({ tool: 'voice', action: 'status' });
      body.innerHTML = '<div class="pro-sec"><span>My real voice (PC)</span></div>' +
        '<div class="pro-item"><small>Consent ' + (r.consent ? '✓' : 'needed') + ' · samples ' + (r.samples || 0) + '</small>' + esc(r.note || '') + '</div>' +
        '<div class="pro-item"><small>Engine</small>' + (r.engine && r.engine.ready ? esc(r.engine.kind) : 'Not installed — will use the closest Gemini voice') + '</div>' +
        '<div class="pro-bar"><input id="vc-t" placeholder="Say this in my voice"><button type="button" class="pro-go acc" id="vc-go">Speak</button></div><div class="st-out"></div>' +
        '<div class="pro-note">Record consent + samples in Lab › My voice. Samples never leave this PC.</div>';
      $('#vc-go', body).onclick = async (e) => {
        busy(e.target, true);
        const x = await api({ tool: 'voice', action: 'speak', text: $('#vc-t', body).value });
        busy(e.target, false);
        $('.st-out', body).innerHTML = x.ok ? '<div class="pro-item">' + esc(x.message || (x.fallback ? 'Used Gemini voice ' + (x.voice || '') : 'Spoke with the local engine.')) + '</div>' : '<div class="pro-err">' + esc(x.error) + '</div>';
        if (x.file) try { new Audio('/media?p=' + encodeURIComponent(x.file)).play(); } catch (err) {}
      };
    },
    async live(body) {
      const r = await api({ tool: 'live', action: 'status' });
      body.innerHTML = '<div class="pro-sec"><span>Live video avatar</span></div>' +
        '<div class="pro-item"><small>OBS Virtual Camera ' + (r.detect && r.detect.virtual_cam ? 'found' : 'missing') + ' · VB-Cable ' + (r.detect && r.detect.vb_cable ? 'found' : 'missing') + '</small>' + esc((r.detect && r.detect.note) || '') + '</div>' +
        '<div class="pro-note">The twin talks only when you press Speak for me, or in Q&amp;A after you approve each answer. The video always shows “AI assistant”.</div>' +
        '<div class="pro-bar"><button type="button" class="pro-go acc" id="lv-on">Start camera</button><button type="button" class="pro-go" id="lv-qa">Q&A mode</button><button type="button" class="pro-go danger" id="lv-off">Stop</button></div>' +
        '<div class="pro-bar"><input id="lv-t" placeholder="Speak for me…"><button type="button" class="pro-go acc" id="lv-say">Speak for me</button></div><div class="st-out"></div>';
      const out = $('.st-out', body);
      $('#lv-on', body).onclick = async () => { const x = await api({ tool: 'live', action: 'start', mode: 'push' }); out.textContent = x.ok ? 'Virtual camera on. Pick OBS Virtual Camera in Zoom/Meet.' : (x.error || ''); };
      $('#lv-qa', body).onclick = async () => { await api({ tool: 'live', action: 'start', mode: 'qa' }); out.textContent = 'Q&A mode — approve each answer.'; };
      $('#lv-off', body).onclick = async () => { await api({ tool: 'live', action: 'stop' }); out.textContent = 'Stopped.'; };
      $('#lv-say', body).onclick = async () => { const x = await api({ tool: 'live', action: 'speak', text: $('#lv-t', body).value, approve: true }); out.textContent = x.ok ? (x.message || x.preview || 'Spoken.') : (x.error || ''); };
    },
    async skill(body) {
      body.innerHTML = '<div class="pro-sec"><span>Self-coding skills</span></div>' +
        '<div class="pro-note">The bot writes a plugin, tests it in a sandbox, and shows the code. It goes live only after you Approve. Skills cannot touch system folders or secrets. Disable and Undo always work.</div>' +
        '<div class="pro-bar"><input id="sk-t" placeholder="e.g. count words in the last message"><button type="button" class="pro-go acc" id="sk-go">Write skill</button></div>' +
        '<div class="st-out"></div><div class="st-list"></div>';
      const list = $('.st-list', body), out = $('.st-out', body);
      const draw = async () => {
        const r = await api({ tool: 'skill', action: 'list' });
        const row = (s, draft) => '<div class="pro-item"><small>' + (s.live ? (s.enabled ? 'live' : 'disabled') : 'draft') + (s.test_ok ? ' · test ok' : '') + '</small><b>' + esc(s.title || s.name) + '</b><pre class="pro">' + esc((s.code || '').slice(0, 800)) + '</pre>' +
          (s.test_result ? '<small>' + esc(s.test_result) + '</small>' : '') +
          (draft ? '<button type="button" class="pro-go acc" data-ap="' + esc(s.id) + '">Approve</button>' : '<button type="button" class="pro-go" data-dis="' + esc(s.id) + '">' + (s.enabled ? 'Disable' : 'Enable') + '</button>') +
          '</div>';
        list.innerHTML = (r.drafts || []).map((s) => row(s, true)).join('') + (r.live || []).map((s) => row(s, false)).join('') +
          '<button type="button" class="pro-go" id="sk-un">Undo last Approve</button>';
        $$('[data-ap]', list).forEach((b) => (b.onclick = async () => { await api({ tool: 'skill', action: 'approve', id: b.dataset.ap }); draw(); }));
        $$('[data-dis]', list).forEach((b) => (b.onclick = async () => { await api({ tool: 'skill', action: b.textContent === 'Disable' ? 'disable' : 'enable', id: b.dataset.dis }); draw(); }));
        const u = $('#sk-un', list); if (u) u.onclick = async () => { await api({ tool: 'skill', action: 'undo' }); draw(); };
      };
      $('#sk-go', body).onclick = async (e) => {
        busy(e.target, true);
        const r = await api({ tool: 'skill', action: 'draft', task: $('#sk-t', body).value });
        busy(e.target, false);
        out.innerHTML = r.ok ? '<div class="pro-item"><small>sandbox test ' + (r.draft.test_ok ? 'passed' : 'failed') + '</small><pre class="pro">' + esc(r.draft.code) + '</pre><div>' + esc(r.draft.test_result) + '</div></div>' : '<div class="pro-err">' + esc(r.error) + '</div>';
        draw();
      };
      draw();
    },
    async home(body) {
      const r = await api({ tool: 'home', action: 'status' });
      const bat = native() && native().batteryPct ? native().batteryPct() : null;
      body.innerHTML = '<div class="pro-sec"><span>Hey Ped + smart home</span></div>' +
        '<div class="pro-item"><small>Wake word is in Settings › Voice. Phone listener pauses below 20% battery.' + (bat != null ? ' Now: ' + bat + '%' : '') + '</small>' + esc(r.note || '') + '</div>' +
        '<div class="pro-item"><small>Home Assistant</small>' + (r.ha ? 'Linked (local URL in .env).' : 'Optional. Add HOME_ASSISTANT_URL and HOME_ASSISTANT_TOKEN to this PC’s .env.') + '</div>' +
        '<div class="pro-bar"><input id="hm-q" placeholder="play lofi · volume up · lock the pc · timer 5 minutes · lights off"><button type="button" class="pro-go acc" id="hm-go">Do it</button></div><div class="st-out"></div>';
      $('#hm-go', body).onclick = async (e) => {
        busy(e.target, true);
        const x = await api({ tool: 'home', action: 'do', text: $('#hm-q', body).value, battery: bat });
        busy(e.target, false);
        $('.st-out', body).innerHTML = x.ok ? '<div class="pro-item">' + esc(x.message) + (x.links ? '<br><a href="' + esc(x.links.youtube_music) + '" target="_blank" rel="noopener">YouTube Music</a> · <a href="' + esc(x.links.spotify) + '" target="_blank" rel="noopener">Spotify</a>' : '') + '</div>' : '<div class="pro-err">' + esc(x.error) + '</div>';
      };
    },
    async income(body) {
      body.innerHTML = '<div class="pro-sec"><span>Income bots</span></div>' +
        '<div class="pro-note">Searches public free boards (RemoteOK, We Work Remotely, Jobicy) for Shorts, apps, Tableau/data. Drafts a proposal in your style. You send it yourself.</div>' +
        '<div class="pro-bar"><input id="in-s" value="shorts, apps, tableau, python" placeholder="Skills"><button type="button" class="pro-go acc" id="in-go">Find gigs</button></div>' +
        '<div class="st-list"></div><div class="pro-sec"><span>Earnings</span></div>' +
        '<div class="pro-bar"><input id="in-a" inputmode="decimal" placeholder="Amount"><input id="in-n" placeholder="Note"><button type="button" class="pro-go" id="in-add">Add</button></div>' +
        '<div class="pro-chart" id="in-ch"></div><div id="in-earn"></div>';
      const list = $('.st-list', body);
      $('#in-go', body).onclick = async (e) => {
        busy(e.target, true);
        const r = await api({ tool: 'income', action: 'search', skills: $('#in-s', body).value });
        busy(e.target, false);
        if (!r.ok) { list.innerHTML = '<div class="pro-err">' + esc(r.error) + '</div>'; return; }
        list.innerHTML = (r.jobs || []).map((j, i) => '<div class="pro-item"><small>' + esc(j.source) + ' · ' + esc(j.company) + '</small><b>' + esc(j.title) + '</b><div>' + esc(j.description || '') + '</div>' +
          (j.url ? '<a class="pro-go" target="_blank" rel="noopener" href="' + esc(j.url) + '">Open</a> ' : '') +
          '<button type="button" class="pro-go acc" data-i="' + i + '">Draft proposal</button></div>').join('') || '<div class="pro-note">No matching gigs right now.</div><div class="pro-note">' + esc(r.note || '') + '</div>';
        $$('[data-i]', list).forEach((b) => (b.onclick = async () => {
          const x = await api({ tool: 'income', action: 'draft', job: r.jobs[+b.dataset.i] });
          b.parentNode.insertAdjacentHTML('beforeend', x.ok ? '<div class="pro-item"><small>Draft — you send it</small>' + esc(x.draft) + '</div>' : '<div class="pro-err">' + esc(x.error) + '</div>');
        }));
      };
      const earn = async () => {
        const r = await api({ tool: 'income', action: 'earnings', op: 'list' });
        const items = r.items || [];
        const max = Math.max(1, ...items.map((i) => Math.abs(i.amount || 0)));
        $('#in-ch', body).innerHTML = items.slice(-24).map((i) => '<i title="' + esc(i.note) + ' ' + i.amount + '" style="height:' + Math.max(6, Math.abs(i.amount) / max * 100) + '%"></i>').join('');
        $('#in-earn', body).innerHTML = '<div class="pro-item"><small>Total</small><b>' + (r.total || 0).toFixed(2) + '</b></div>' +
          items.slice().reverse().slice(0, 12).map((i) => '<div class="pro-item st-row" style="display:flex;justify-content:space-between"><div>' + esc(i.note || '') + ' · ' + i.amount + '</div><button type="button" class="pro-go" data-del="' + i.id + '">✕</button></div>').join('');
        $$('[data-del]', body).forEach((b) => (b.onclick = async () => { await api({ tool: 'income', action: 'earnings', op: 'delete', id: b.dataset.del }); earn(); }));
      };
      $('#in-add', body).onclick = async () => { await api({ tool: 'income', action: 'earnings', op: 'add', amount: $('#in-a', body).value, note: $('#in-n', body).value }); $('#in-a', body).value = ''; earn(); };
      earn();
    },
  };

  async function show(k) {
    const p = page();
    chips(p, 'All');
    const body = $('.pro-body', p);
    const f = FEATURES.find((x) => x.k === k);
    if (f && flags[f.flag] === false) {
      body.innerHTML = '<div class="pro-sec"><span>' + esc(f.name) + '</span></div><div class="pro-err">This is off. Turn it on in Settings › Advanced.</div><button type="button" class="pro-go" id="pro-back">Back</button>';
      $('#pro-back', body).onclick = () => home();
      return;
    }
    body.innerHTML = '<div class="pro-note">Loading…</div>';
    await (V[k] || V.phone)(body);
  }

  async function open(tab) {
    page();
    await refreshFlags();
    if (tab) show(tab); else home();
  }

  async function addAdvanced() {
    const S = $('#settings'); if (!S) return;
    let pane = $('#p-advanced');
    if (!pane) {
      pane = document.createElement('div'); pane.className = 'pane'; pane.id = 'p-advanced';
      const more = $('#p-more') || $('#p-rules');
      if (more && more.parentNode) more.parentNode.insertBefore(pane, more.nextSibling);
      else S.appendChild(pane);
      const tabs = $(':scope > .tabs', S);
      if (tabs && !tabs.querySelector('[data-pane="p-advanced"]')) {
        const tb = document.createElement('button'); tb.type = 'button'; tb.className = 'tab'; tb.dataset.pane = 'p-advanced'; tb.textContent = 'Advanced';
        tabs.appendChild(tb);
        tb.onclick = () => { $$('.tab', S).forEach((x) => x.classList.remove('active')); $$('.pane', S).forEach((p) => p.classList.remove('active')); tb.classList.add('active'); pane.classList.add('active'); };
      }
    }
    if (pane.dataset.pro) return; pane.dataset.pro = '1';
    const r = await refreshFlags();
    pane.innerHTML = '<p class="rule-hint">Batch 2 tools. Risky ones stay off until you switch them on. Bots still never send, post, spend or delete without an Approve tap.</p>';
    (r.items || FEATURES.map((f) => ({ id: f.flag, name: f.name, on: !!flags[f.flag], risky: true }))).forEach((it) => {
      const row = document.createElement('div'); row.className = 'field';
      row.innerHTML = '<div>' + esc(it.name) + '<small>' + (it.risky ? 'Risky — default off. ' : '') + 'Used from the Pro page.</small></div><label class="switch"><input type="checkbox" data-flag="' + esc(it.id) + '"' + (it.on ? ' checked' : '') + '><span></span></label>';
      pane.appendChild(row);
      const inp = row.querySelector('input');
      inp.onchange = async () => { const patch = {}; patch[it.id] = inp.checked; await api({ tool: 'flags', flags: patch }); flags[it.id] = inp.checked; };
    });
    if (window.pbSettingsPage) window.pbSettingsPage.decorate(pane);
    const voice = $('#p-voice');
    if (voice && !$('#real-voice')) {
      const f = document.createElement('div'); f.className = 'field';
      f.innerHTML = '<div>My real voice (PC)<small>Local clone when Piper or XTTS is installed and Lab › My voice consent is on. Otherwise the closest Gemini voice.</small></div><button class="btn" type="button" id="real-voice">Open</button>';
      voice.appendChild(f);
      $('#real-voice').onclick = () => open('voice');
      if (window.pbSettingsPage) window.pbSettingsPage.decorate(voice);
    }
  }

  const ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l2.5 5 5.5.8-4 3.9 1 5.5-5-2.7-5 2.7 1-5.5-4-3.9 5.5-.8z"/></svg>';
  function menus() {
    const m = $('#pd-menu');
    if (m && !m.querySelector('[data-pro190]')) {
      const help = Array.from(m.children).find((b) => b.tagName === 'BUTTON' && b.textContent.trim() === 'Help');
      const b = document.createElement('button'); b.type = 'button'; b.dataset.pro190 = '1'; b.textContent = 'Pro';
      b.onclick = (e) => { e.stopPropagation(); m.classList.remove('open'); open(); };
      if (help) m.insertBefore(b, help); else m.appendChild(b);
    }
    const nav = $('#bottomnav');
    if (nav && !nav.querySelector('[data-pro190]')) {
      let after = nav.querySelector('.pl-extra[data-target="m184-lab"]') || nav.querySelector('.pl-extra[data-m184]');
      if (!after) return;
      const last = $$('.pl-extra[data-m184]', nav).pop(); if (last) after = last;
      const b = document.createElement('button'); b.type = 'button'; b.className = 'pl-extra'; b.dataset.pro190 = '1';
      b.innerHTML = ICON; b.appendChild(document.createTextNode('Pro'));
      b.onclick = (e) => { e.stopPropagation(); document.body.classList.remove('pl-grid-open', 'pl-home-on'); open(); };
      after.after(b);
    }
  }

  function boot() {
    addAdvanced(); menus();
    setTimeout(() => { addAdvanced(); menus(); }, 1600);
    new MutationObserver(() => menus()).observe(document.body, { childList: true, subtree: true });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot); else boot();
  window.pbPro = { open, show, home };
})();
