// 1.4.18 Task board (PC side button + phone bottom-nav tab): every task's progress with Pause, Stop and reorder.
(function () {
  const $ = (s) => document.querySelector(s);
  const esc = (t) => String(t == null ? '' : t).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const get = (p) => fetch(p).then((r) => r.json());
  const post = (p, b) => fetch(p, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) }).then((r) => r.json());
  const ICON = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 9h6M7 13h10M7 17h4"/></svg>';
  const LABEL = { waiting: 'Waiting', held: 'Paused (waiting)', running: 'Running', paused: 'Paused', approval: 'Needs your OK', done: 'Done', failed: 'Failed', stopped: 'Stopped' };

  const panel = document.createElement('section');
  panel.id = 'tasks'; panel.className = 'rt-panel tb-panel'; panel.hidden = true; panel.setAttribute('aria-label', 'Task board');
  panel.innerHTML = '<div class="rt-head"><h2>Task board</h2><button type="button" class="rt-x" aria-label="Close">&times;</button></div>' +
    '<p class="rt-hint">Each task runs in its own worker, so chat and other bots stay free. Up to <b id="tb-max">5</b> run at once; changes still wait for your OK, one at a time.</p>' +
    '<div class="tb-new"><textarea id="tb-goal" rows="2" placeholder="New task, e.g. summarise the 5 newest PDFs in Documents"></textarea>' +
    '<div class="rt-acts"><button type="button" id="tb-add">Run as a task</button><button type="button" id="tb-split">Split into parallel parts</button></div></div>' +
    '<p id="tb-stat" class="rt-msg"></p><div id="tb-list"></div>';
  document.body.appendChild(panel);

  const side = document.createElement('button');
  side.className = 'side-btn'; side.id = 'tbbtn'; side.type = 'button';
  side.innerHTML = ICON + 'Tasks <span class="tb-count" id="tb-count" style="visibility:hidden"></span>';
  const anchor = $('#rtbtn') || $('#setbtn'); if (anchor && anchor.parentNode) anchor.parentNode.insertBefore(side, anchor);
  const nav = $('#bottomnav'); let navb = null;
  if (nav) {
    navb = document.createElement('button'); navb.type = 'button'; navb.dataset.nav = 'tasks';
    navb.innerHTML = ICON.replace('width="18" height="18"', 'width="20" height="20"') + '<span>Tasks</span>';
    const last = nav.querySelector('[data-nav="settings"]'); nav.insertBefore(navb, last);
  }
  let timer = null;
  function show(on) {
    panel.hidden = !on;
    if (navb) document.querySelectorAll('#bottomnav button').forEach((b) => b.classList.toggle('active', on && b === navb));
    if (on) { if (window.closeMobileSide) window.closeMobileSide(); load(); }
  }
  side.onclick = () => show(panel.hidden);
  if (navb) navb.onclick = () => show(panel.hidden);
  panel.querySelector('.rt-x').onclick = () => show(false);
  if (nav) nav.addEventListener('click', (e) => { const b = e.target.closest('button'); if (b && b !== navb) show(false); });

  const session = () => localStorage.session || '';
  $('#tb-add').onclick = async () => { const g = $('#tb-goal').value.trim(); if (!g) return; const r = await post('/api/tasks', { action: 'add', goal: g, session: session() }); $('#tb-goal').value = ''; $('#tb-stat').textContent = r.message || r.error || ''; load(); };
  $('#tb-split').onclick = async () => { const g = $('#tb-goal').value.trim(); if (!g) return; const r = await post('/api/tasks', { action: 'split', goal: g, session: session() }); $('#tb-goal').value = ''; $('#tb-stat').textContent = r.message || r.error || ''; load(); };

  function buttons(t) {
    const live = ['running', 'paused', 'approval', 'waiting', 'held'].includes(t.status);
    const b = [];
    if (t.status === 'approval') b.push(['approve', 'Approve'], ['decline', 'Decline']);
    if (t.status === 'running' || t.status === 'waiting') b.push(['pause', 'Pause']);
    if (t.status === 'paused' || t.status === 'held') b.push(['resume', 'Resume']);
    if (live) b.push(['stop', 'Stop']);
    if (t.status === 'waiting' || t.status === 'held') b.push(['up', '\u2191'], ['down', '\u2193']);
    if (!live) b.push(['remove', 'Remove']);
    return b.map(([a, l]) => '<button data-a="' + a + '"' + (a === 'stop' ? ' class="danger"' : '') + '>' + l + '</button>').join('');
  }
  // 1.4.18: rows are keyed by task id and updated in place. Only the parts that changed are touched
  // (a full innerHTML re-render every poll made the board flicker on phones).
  const rows = new Map();
  function setText(el, t) { if (el.textContent !== t) el.textContent = t; }
  function makeRow(id) {
    const el = document.createElement('div'); el.dataset.id = id;
    el.innerHTML = '<div class="rt-name"></div><div class="rt-sub tb-state"></div><div class="tb-bar"><i></i></div>' +
      '<div class="rt-sub tb-step"></div><div class="rt-prompt tb-result"></div><div class="rt-sub tb-err"></div><div class="rt-acts"></div>';
    el.querySelector('.rt-acts').addEventListener('click', async (e) => {
      const b = e.target.closest('button'); if (!b) return;
      const r = await post('/api/tasks', { action: b.dataset.a, id }); setText($('#tb-stat'), r.message || r.error || ''); load();
    });
    return el;
  }
  function fill(el, t, child) {
    const cls = 'rt-item tb-item tb-' + t.status + (child ? ' tb-child' : '');
    if (el.className !== cls) el.className = cls;
    setText(el.querySelector('.rt-name'), t.title + (t.bot ? '  \u00b7 ' + t.bot : ''));
    setText(el.querySelector('.tb-state'), (LABEL[t.status] || t.status) + (t.seconds ? ' \u00b7 ' + Math.round(t.seconds) + ' s' : '') +
      (t.model ? ' \u00b7 ' + t.model.replace('backup:', '') : '') + (t.needs ? ' \u00b7 ' + t.needs : ''));
    const bar = el.querySelector('.tb-bar i'); const w = (t.progress || 0) + '%'; if (bar.style.width !== w) bar.style.width = w;
    const step = t.steps && t.steps.length && t.status !== 'done' ? t.steps[t.steps.length - 1] : '';
    const se = el.querySelector('.tb-step'); setText(se, step); se.style.display = step ? '' : 'none';
    const res = t.result && (t.status === 'done' || t.status === 'approval') && !child ? t.result.slice(0, 600) : '';
    const re = el.querySelector('.tb-result'); setText(re, res); re.style.display = res ? '' : 'none';
    const ee = el.querySelector('.tb-err'); setText(ee, t.error || ''); ee.style.display = t.error ? '' : 'none';
    const acts = buttons(t); const box = el.querySelector('.rt-acts'); if (box.dataset.k !== acts) { box.dataset.k = acts; box.innerHTML = acts; }
  }
  let busy = false;
  async function load() {
    if (busy || document.hidden) return; busy = true;
    let d; try { d = await get('/api/tasks'); } catch (e) { busy = false; return; }
    busy = false;
    const list = d.tasks || [];
    const cnt = $('#tb-count'); const c = String(d.running || ''); setText(cnt, c); cnt.style.visibility = d.running ? 'visible' : 'hidden';
    setText($('#tb-max'), String(d.max_running || 5));
    if (panel.hidden) return;
    const box = $('#tb-list');
    const kids = new Set(); list.forEach((t) => (t.children || []).forEach((k) => kids.add(k)));
    const byId = {}; list.forEach((t) => byId[t.id] = t);
    const wanted = [];
    list.slice().reverse().forEach((t) => { if (kids.has(t.id)) return; wanted.push([t, false]); (t.children || []).forEach((k) => { if (byId[k]) wanted.push([byId[k], true]); }); });
    const keep = new Set(wanted.map(([t]) => t.id));
    rows.forEach((el, id) => { if (!keep.has(id)) { el.remove(); rows.delete(id); } });
    let empty = box.querySelector('.rt-empty');
    if (!wanted.length && !empty) { empty = document.createElement('p'); empty.className = 'rt-empty'; empty.textContent = 'No tasks yet. Ask any bot to do something "in the background", or add one here.'; box.appendChild(empty); }
    if (wanted.length && empty) empty.remove();
    let prev = null;
    wanted.forEach(([t, child]) => {
      let el = rows.get(t.id); if (!el) { el = makeRow(t.id); rows.set(t.id, el); }
      fill(el, t, child);
      const want = prev ? prev.nextSibling : box.firstChild;
      if (want !== el) box.insertBefore(el, want);   // moves only rows whose place changed
      prev = el;
    });
  }
  window.refreshTasks = load;
  // Poll fast only while the board is open; the badge refreshes slowly otherwise. Nothing runs while hidden.
  setInterval(() => { if (!panel.hidden) load(); }, 1500);
  setInterval(() => { if (panel.hidden) load(); }, 8000);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) load(); });
  load();
})();
