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
  side.innerHTML = ICON + 'Tasks <span class="tb-count" id="tb-count" hidden></span>';
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
  async function load() {
    let d; try { d = await get('/api/tasks'); } catch (e) { return; }
    const list = d.tasks || []; const box = $('#tb-list');
    const cnt = $('#tb-count'); cnt.hidden = !d.running; cnt.textContent = d.running || '';
    $('#tb-max').textContent = d.max_running || 5;
    if (panel.hidden) return;
    const kids = new Set(); list.forEach((t) => (t.children || []).forEach((c) => kids.add(c)));
    const html = (t, child) => '<div class="rt-item tb-item tb-' + t.status + (child ? ' tb-child' : '') + '" data-id="' + t.id + '">' +
      '<div class="rt-name">' + esc(t.title) + (t.bot ? ' <span class="rt-bot">' + esc(t.bot) + '</span>' : '') + '</div>' +
      '<div class="rt-sub">' + esc(LABEL[t.status] || t.status) + (t.seconds ? ' &middot; ' + t.seconds + ' s' : '') + (t.model ? ' &middot; ' + esc(t.model.replace('backup:', '')) : '') + (t.needs ? ' &middot; ' + esc(t.needs) : '') + '</div>' +
      '<div class="tb-bar"><i style="width:' + (t.progress || 0) + '%"></i></div>' +
      (t.steps && t.steps.length && t.status !== 'done' ? '<div class="rt-sub">' + esc(t.steps[t.steps.length - 1]) + '</div>' : '') +
      (t.result && (t.status === 'done' || t.status === 'approval') && !child ? '<div class="rt-prompt">' + esc(t.result.slice(0, 600)) + '</div>' : '') +
      (t.error ? '<div class="rt-sub">' + esc(t.error) + '</div>' : '') +
      '<div class="rt-acts">' + buttons(t) + '</div></div>';
    const byId = {}; list.forEach((t) => byId[t.id] = t);
    let out = '';
    list.slice().reverse().forEach((t) => { if (kids.has(t.id)) return; out += html(t, false); (t.children || []).forEach((c) => { if (byId[c]) out += html(byId[c], true); }); });
    box.innerHTML = out || '<p class="rt-empty">No tasks yet. Ask any bot to do something "in the background", or add one here.</p>';
    box.querySelectorAll('.tb-item button').forEach((b) => b.onclick = async () => {
      const id = b.closest('.tb-item').dataset.id; const a = b.dataset.a;
      const r = await post('/api/tasks', { action: a, id }); $('#tb-stat').textContent = r.message || r.error || ''; load();
    });
  }
  window.refreshTasks = load;
  setInterval(load, 1500); load();
})();
