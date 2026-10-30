// 1.8.3 Lab: twin call, camera vision, swarm research, bot coach, predictive, bot company, YouTube autopilot, Ped OS, co-pilot, voice.
(function () {
  'use strict';
  const $ = (s, r) => (r || document).querySelector(s);
  const api = (b) => fetch('/api/lab', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) }).then((r) => r.json()).catch(() => ({ ok: false, error: 'Ped Bot is not reachable.' }));
  const esc = (t) => String(t == null ? '' : t).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const b64 = (blob) => new Promise((ok) => { const r = new FileReader(); r.onload = () => ok(String(r.result).split(',')[1] || ''); r.readAsDataURL(blob); });
  const err = (r) => '<div class="st-err">' + esc(r.error || 'Something went wrong.') + '</div>';
  const busy = (b, on) => { b.disabled = on; b.classList.toggle('busy', on); };
  const out = (body, html) => { let o = $('.st-out', body); if (!o) { o = document.createElement('div'); o.className = 'st-out'; body.appendChild(o); } o.innerHTML = html; return o; };
  const say = async (text) => { try { const s = await fetch('/api/speak_text', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text }) }).then((x) => x.json()); if (s.url) new Audio(s.url).play(); } catch (e) {} };
  async function pollJob(id, body, draw) {
    for (;;) {
      await new Promise((r) => setTimeout(r, 2500)); const j = await api({ tool: 'job', job: id });
      if (!document.body.contains(body)) return;
      if (j.status === 'working') { out(body, '<div class="b180-item">' + (j.log || []).slice(-6).map(esc).join('<br>') + '</div>'); continue; }
      out(body, j.status === 'done' ? draw(j.result) : err({ error: j.error || 'Failed.' })); return;
    }
  }
  const TOOLS = [['twin', 'Call my twin'], ['vision', 'Camera'], ['swarm', 'Swarm research'], ['coach', 'Bot coach'], ['predict', 'Predict'],
    ['company', 'Bot company'], ['autopilot', 'YouTube autopilot'], ['os', 'Ped OS'], ['copilot', 'Co-pilot'], ['voice', 'My voice']];
  function open(tab) {
    const old = $('#lab183'); if (old) old.remove();
    const p = document.createElement('div'); p.id = 'lab183'; p.className = 'b180-page st182';
    p.innerHTML = '<div class="b180-head"><button type="button" class="b180-x" aria-label="Close"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M18 6 6 18M6 6l12 12"/></svg></button><b>Lab</b><span class="b180-pill">10 tools</span></div>' +
      '<div class="st-tabs">' + TOOLS.map(([k, l]) => '<button type="button" data-k="' + k + '">' + l + '</button>').join('') + '</div><div class="b180-body st-body"></div>';
    document.body.appendChild(p);
    $('.b180-x', p).onclick = () => { p.dispatchEvent(new Event('close')); p.remove(); };
    p.querySelectorAll('.st-tabs button').forEach((b) => (b.onclick = () => show(b.dataset.k)));
    function show(k) {
      p.dispatchEvent(new Event('close'));
      p.querySelectorAll('.st-tabs button').forEach((b) => b.classList.toggle('on', b.dataset.k === k));
      const t = $('.st-tabs', p), b = $('.on', t); if (b) t.scrollLeft = b.offsetLeft - 16;
      const body = $('.st-body', p); body.innerHTML = ''; (V[k] || V.twin)(body, p); localStorage.pbLabTab = k;
    }
    show(tab || localStorage.pbLabTab || 'twin');
  }
  const V = {
    twin(body) {
      body.innerHTML = '<div class="b180-sec">A face-to-face call with your 3D AI twin</div><div class="b180-item">Talk normally - your twin listens, answers in its own voice with lip sync, and reacts with its whole body.</div>' +
        '<button type="button" class="b180-btn acc" id="tw-m">📞 Call my twin (male · Puck)</button><button type="button" class="b180-btn" id="tw-f">📞 Call my twin (female · Sulafat)</button>';
      const call = (g) => { localStorage.pbAvatarGender = g; $('#lab183').remove(); if (window.pbCloseAvatar) window.pbCloseAvatar(); const f = document.createElement('iframe'); f.id = 'av3d'; f.title = 'Call'; f.allow = 'microphone; autoplay'; f.src = '/avatar3d/human.html?call=1'; document.body.appendChild(f); document.body.classList.add('b180-open'); };
      $('#tw-m', body).onclick = () => call('male'); $('#tw-f', body).onclick = () => call('female');
    },
    vision(body, p) {
      body.innerHTML = '<div class="b180-sec">Point your camera, ask anything</div><video id="cv-v" playsinline muted class="lab-cam"></video>' +
        '<div class="b180-bar"><input id="cv-q" placeholder="e.g. what plant is this? is this wire safe?" autocomplete="off"><button type="button" class="b180-btn acc" id="cv-go">Ask</button></div>' +
        '<div class="b180-bar"><button type="button" class="b180-btn" id="cv-flip">Flip camera</button><label class="b180-row"><input type="checkbox" id="cv-auto"> Keep watching (every 20 s)</label></div>';
      const v = $('#cv-v', body); let stream = null, face = 'environment', timer = 0;
      const start = async () => { try { if (stream) stream.getTracks().forEach((t) => t.stop()); stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: face }, audio: false }); v.srcObject = stream; await v.play(); } catch (e) { out(body, err({ error: 'Camera not available here.' })); } };
      start();
      const ask = async () => {
        if (!v.videoWidth) return; const c = document.createElement('canvas'); const s = Math.min(1, 1024 / v.videoWidth); c.width = v.videoWidth * s; c.height = v.videoHeight * s;
        c.getContext('2d').drawImage(v, 0, 0, c.width, c.height); const blob = await new Promise((r) => c.toBlob(r, 'image/jpeg', 0.8));
        const q = $('#cv-q', body).value; out(body, '<div class="b180-item">Looking…</div>');
        const r = await api({ tool: 'vision', image: await b64(blob), question: q });
        out(body, r.ok ? '<div class="b180-item">' + esc(r.text) + '</div>' : err(r)); if (r.ok) say(r.text);
      };
      $('#cv-go', body).onclick = ask; $('#cv-q', body).onkeydown = (e) => { if (e.key === 'Enter') ask(); };
      $('#cv-flip', body).onclick = () => { face = face === 'user' ? 'environment' : 'user'; start(); };
      $('#cv-auto', body).onchange = (e) => { clearInterval(timer); if (e.target.checked) timer = setInterval(ask, 20000); };
      p.addEventListener('close', () => { clearInterval(timer); if (stream) stream.getTracks().forEach((t) => t.stop()); }, { once: true });
    },
    swarm(body) {
      body.innerHTML = '<div class="b180-sec">4 research agents + a judge</div><textarea id="sw-q" rows="3" placeholder="e.g. best free way to grow a Shorts channel in India in 2026"></textarea><button type="button" class="b180-btn acc" id="sw-go">Start swarm</button>';
      $('#sw-go', body).onclick = async (e) => {
        busy(e.target, true); const r = await api({ tool: 'swarm', question: $('#sw-q', body).value }); busy(e.target, false);
        if (!r.ok) return out(body, err(r));
        pollJob(r.job, body, (x) => '<div class="b180-item"><small>Confidence: ' + esc(x.confidence) + '</small><div>' + esc(x.answer) + '</div></div>' +
          (x.agree && x.agree.length ? '<div class="b180-item"><small>Agents agree</small><div>' + x.agree.map(esc).join('<br>') + '</div></div>' : '') +
          (x.disagree && x.disagree.length ? '<div class="b180-item"><small>Disagree / unsure</small><div>' + x.disagree.map(esc).join('<br>') + '</div></div>' : '') +
          (x.next_steps && x.next_steps.length ? '<div class="b180-item"><small>Next steps</small><div>' + x.next_steps.map(esc).join('<br>') + '</div></div>' : '') +
          '<details class="b180-item"><summary>Each agent\'s notes</summary>' + (x.agents || []).map((a) => '<p><b>' + esc(a.agent) + '</b><br>' + esc(a.notes).replace(/\n/g, '<br>') + '</p>').join('') + '</details>');
      };
    },
    async coach(body) {
      body.innerHTML = '<div class="b180-sec">Bots learn from your chats and 👍 / 👎</div><div class="b180-bar"><select id="co-b"></select><button type="button" class="b180-btn acc" id="co-go">Review</button></div>';
      const r = await api({ tool: 'bots' }); const sel = $('#co-b', body);
      (r.bots || []).forEach((b) => { const o = document.createElement('option'); o.value = b.id; o.textContent = b.name; sel.appendChild(o); });
      if (!(r.bots || []).length) out(body, '<small class="st-note">Make a bot first (menu → Bots).</small>');
      $('#co-go', body).onclick = async (e) => {
        busy(e.target, true); const x = await api({ tool: 'improve', bot: sel.value }); busy(e.target, false);
        if (!x.ok) return out(body, err(x));
        const o = out(body, '<div class="b180-item"><small>What it learned</small><div>' + (x.lessons || []).map(esc).join('<br>') + '</div></div><div class="b180-item"><small>New instructions</small><textarea id="co-role" rows="8">' + esc(x.role) + '</textarea></div>' +
          (x.skills || []).map((s) => '<div class="b180-item"><small>New skill</small><b>' + esc(s.name) + '</b><div>' + esc(s.steps) + '</div></div>').join('') +
          '<div class="b180-bar"><button type="button" class="b180-btn acc" id="co-ap">Apply</button><button type="button" class="b180-btn" id="co-un">Undo last</button></div>');
        $('#co-ap', o).onclick = async () => { const a = await api({ tool: 'improve', bot: sel.value, apply: { role: $('#co-role', o).value, skills: x.skills || [] } }); $('#co-ap', o).textContent = a.ok ? 'Applied ✓' : 'Failed'; };
        $('#co-un', o).onclick = async () => { const a = await api({ tool: 'improve_undo', bot: sel.value }); $('#co-un', o).textContent = a.ok ? 'Undone ✓' : (a.error || 'Nothing to undo'); };
      };
    },
    async predict(body) {
      body.innerHTML = '<div class="b180-sec">What you\'ll probably want right now</div>'; out(body, '<div class="b180-item">Thinking about your routine…</div>');
      const r = await api({ tool: 'predict' });
      if (!r.ok) return out(body, err(r));
      const o = out(body, (r.suggestions || []).map((s) => '<div class="b180-item st-row"><div><b>' + esc(s.label) + '</b><small>' + esc(s.why) + '</small></div><button type="button" class="b180-btn acc" data-c="' + esc(s.command) + '">Do it</button></div>').join('') +
        '<small class="st-note">' + esc(r.note || ('Learned from ' + r.learned_from + ' of your messages around ' + r.hour + ':00.')) + '</small>');
      o.querySelectorAll('[data-c]').forEach((b) => (b.onclick = () => { const i = document.querySelector('#input, #msg, textarea'); $('#lab183').remove(); if (i) { i.value = b.dataset.c; i.dispatchEvent(new Event('input')); const s = document.querySelector('#send, .send'); if (s) s.click(); } }));
    },
    company(body) {
      body.innerHTML = '<div class="b180-sec">A CEO bot hires a team and delivers</div><textarea id="cp-g" rows="3" placeholder="e.g. plan a 30-day launch for my Quiet Brain channel"></textarea><button type="button" class="b180-btn acc" id="cp-go">Start company</button>';
      $('#cp-go', body).onclick = async (e) => {
        busy(e.target, true); const r = await api({ tool: 'company', goal: $('#cp-g', body).value }); busy(e.target, false);
        if (!r.ok) return out(body, err(r));
        pollJob(r.job, body, (x) => '<div class="b180-item"><small>Team</small><div>' + (x.team || []).map((t) => '<b>' + esc(t.role) + '</b> - ' + esc(t.task)).join('<br>') + '</div></div><div class="b180-item lab-md">' + esc(x.final).replace(/\n/g, '<br>') + '</div><small class="st-note">Saved: ' + esc(x.file) + '</small>');
      };
    },
    autopilot(body) {
      body.innerHTML = '<div class="b180-sec">Plans 2D Shorts that ride your daily routine</div><button type="button" class="b180-btn acc" id="ap-go">Plan 3 Shorts</button>';
      $('#ap-go', body).onclick = async (e) => {
        busy(e.target, true); out(body, '<div class="b180-item">Checking Buffer and writing ideas…</div>'); const r = await api({ tool: 'autopilot', count: 3 }); busy(e.target, false);
        if (!r.ok) return out(body, err(r));
        const o = out(body, '<div class="b180-item"><small>Buffer</small><div>' + r.buffer_scheduled + ' / ' + r.buffer_limit + ' scheduled · routine slots ' + esc(r.routine_slots.join(', ')) + ' · queued ' + r.queued + '</div></div>' +
          r.plan.map((i, k) => '<div class="b180-item"><small>2D · isAiGenerated = false</small><b>' + esc(i.title) + '</b><div>' + esc(i.hook) + '</div><details><summary>Script</summary>' + esc(i.script) + '</details><button type="button" class="b180-btn acc" data-i="' + k + '">Queue</button></div>').join('') +
          '<small class="st-note">' + esc(r.note) + '</small>');
        o.querySelectorAll('[data-i]').forEach((b) => (b.onclick = async () => { const q = await api({ tool: 'autopilot_queue', index: +b.dataset.i }); b.textContent = q.ok ? 'Queued ✓' : (q.error || 'Failed'); }));
      };
    },
    async os(body) {
      body.innerHTML = '<div class="b180-sec">Ped OS - everything at a glance</div>'; out(body, '<div class="b180-item">Loading…</div>');
      const r = await api({ tool: 'os' }); if (!r.ok) return out(body, err(r));
      const tile = (k, v) => '<div class="lab-tile"><small>' + esc(k) + '</small><b>' + esc(v) + '</b></div>';
      const s = r.studio || {}, sh = r.shorts || {};
      out(body, '<div class="lab-grid">' + tile('Bots', (r.bots || []).length) + tile('Daily Shorts', sh.enabled ? 'On · ' + sh.per_day + '/day' : 'Off') + tile('Calls set', s.calls ?? '-') + tile('Price watches', s.prices ?? '-') +
        tile('Shortcuts', s.shortcuts ?? '-') + tile('Offline mode', r.offline && r.offline.on ? 'On' : 'Off') + tile('CPU', r.cpu != null ? r.cpu + '%' : '-') + tile('RAM', r.ram != null ? r.ram + '%' : '-') +
        tile('Disk free', r.disk ? r.disk.free_gb + ' GB' : '-') + tile('Battery', r.battery != null ? r.battery + '%' : '-') + '</div>' +
        '<div class="b180-bar"><button type="button" class="b180-btn" data-go="studio">Open Studio</button><button type="button" class="b180-btn" data-go="avatar">3D avatar</button></div>' +
        (r.bots || []).map((b) => '<div class="b180-item st-row"><div><b>' + esc(b.name) + '</b><small>' + b.tasks + ' scheduled tasks</small></div></div>').join(''));
      body.querySelectorAll('[data-go]').forEach((b) => (b.onclick = () => { $('#lab183').remove(); if (b.dataset.go === 'studio' && window.pbStudio) window.pbStudio.open(); if (b.dataset.go === 'avatar' && window.pbOpenAvatar) window.pbOpenAvatar(); }));
    },
    copilot(body) {
      body.innerHTML = '<div class="b180-sec">A small helper bubble that watches your PC screen</div><label class="b180-row"><input type="checkbox" id="cop-on"> Co-pilot on (a tip every 3 minutes, tap the bubble to ask)</label><small class="st-note">Uses the same screen view as Screen tutor. It only looks and suggests; it never clicks.</small>';
      const c = $('#cop-on', body); c.checked = localStorage.pbCopilot === '1'; c.onchange = () => { localStorage.pbCopilot = c.checked ? '1' : '0'; copilot(); };
    },
    async voice(body) {
      body.innerHTML = '<div class="b180-sec">Your own voice - only with your consent</div><div class="st-list"></div>';
      const draw = (r) => {
        $('.st-list', body).innerHTML = '<div class="b180-item"><small>Step 1 · consent ' + (r.consent ? '✓' : '') + '</small><div>Read this out loud:<br><b>“' + esc(r.consent_text) + '”</b></div><button type="button" class="b180-btn ' + (r.consent ? '' : 'acc') + '" data-k="consent">● Record consent</button></div>' +
          '<div class="b180-item"><small>Step 2 · samples (' + r.samples + ')</small><div>Talk naturally for 20-30 seconds, 3 times.</div><button type="button" class="b180-btn ' + (r.consent ? 'acc' : '') + '" data-k="sample">● Record sample</button></div>' +
          '<div class="b180-item"><small>Step 3 · match</small><div>' + (r.match ? 'Closest free voice: <b>' + esc(r.match) + '</b><br><small>' + esc(r.describe || '') + '</small>' : 'Find the closest free Gemini voice.') + '</div><button type="button" class="b180-btn" id="vc-m">Match my voice</button></div>' +
          '<button type="button" class="b180-btn" id="vc-del">Delete my recordings</button><small class="st-note">' + esc(r.note) + '</small>';
        body.querySelectorAll('[data-k]').forEach((b) => (b.onclick = () => rec(b, b.dataset.k)));
        $('#vc-m', body).onclick = async (e) => { busy(e.target, true); const x = await api({ tool: 'voice', action: 'match' }); busy(e.target, false); x.ok ? draw(x) : out(body, err(x)); };
        $('#vc-del', body).onclick = async () => { if (confirm('Delete all voice recordings?')) draw(await api({ tool: 'voice', action: 'delete' })); };
      };
      let mr = null;
      async function rec(btn, kind) {
        if (mr) { mr.stop(); return; }
        try { const s = await navigator.mediaDevices.getUserMedia({ audio: true }); const ch = []; mr = new MediaRecorder(s); mr.ondataavailable = (d) => ch.push(d.data);
          mr.onstop = async () => { s.getTracks().forEach((t) => t.stop()); mr = null; const x = await api({ tool: 'voice', action: 'record', kind, audio: await b64(new Blob(ch, { type: 'audio/webm' })) }); x.ok ? draw(x) : out(body, err(x)); };
          mr.start(); btn.textContent = '■ Stop'; } catch (e) { out(body, err({ error: 'Microphone not available here.' })); }
      }
      draw(await api({ tool: 'voice' }));
    },
  };

  // Co-pilot overlay bubble
  let copTimer = 0;
  function copilot() {
    clearInterval(copTimer); let b = $('#copilot');
    if (localStorage.pbCopilot !== '1') { if (b) b.remove(); return; }
    if (!b) { b = document.createElement('div'); b.id = 'copilot'; b.innerHTML = '<div class="cop-dot">P</div><div class="cop-tip">Co-pilot is watching for ways to help…</div>'; document.body.appendChild(b);
      b.onclick = async () => { const q = prompt('Ask your co-pilot about the screen:'); if (!q) return; tip(q); }; }
    const tip = async (q) => {
      $('.cop-tip', b).textContent = 'Looking…';
      try { const r = await fetch('/api/tutor', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ question: q || 'Give me ONE short, useful tip for what I am doing on screen right now (max 20 words).' }) }).then((x) => x.json());
        $('.cop-tip', b).textContent = r.ok ? r.text : (r.error || 'Could not see the screen.'); b.classList.add('new'); setTimeout(() => b.classList.remove('new'), 4000); } catch (e) {}
    };
    tip(); copTimer = setInterval(() => { if (!document.hidden) tip(); }, 180000);   // every 3 min keeps the free Gemini quota safe
  }

  function addMenu() {
    const menu = $('#pl-menu');
    if (menu && !menu.querySelector('[data-lab183]')) { const b = document.createElement('button'); b.type = 'button'; b.dataset.lab183 = '1'; b.textContent = 'Lab (twin call, camera, swarm…)'; b.onclick = (e) => { e.stopPropagation(); document.body.classList.remove('pl-menu-open'); open(); }; menu.appendChild(b); }
    const box = $('#b180-side');
    if (box && !box.querySelector('[data-lab183]')) { const b = document.createElement('button'); b.type = 'button'; b.className = 'side-btn'; b.dataset.lab183 = '1'; b.textContent = 'Lab'; b.onclick = () => open(); box.appendChild(b); }
  }
  function boot() { addMenu(); setTimeout(addMenu, 1800); if (!document.body.classList.contains('pl')) copilot(); }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot); else boot();
  window.pbLab = { open, copilot };
})();
