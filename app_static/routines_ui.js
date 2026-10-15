// Routines page (PC side panel button + phone bottom-nav tab) and run notifications.
(function () {
  const $ = (s) => document.querySelector(s);
  const esc = (t) => String(t == null ? '' : t).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const get = (p) => fetch(p).then((r) => r.json());
  const post = (p, b) => fetch(p, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) }).then((r) => r.json());

  const panel = document.createElement('section');
  panel.id = 'routines'; panel.className = 'rt-panel'; panel.hidden = true; panel.setAttribute('aria-label', 'Routines');
  panel.innerHTML = '<div class="rt-head"><h2>Routines</h2><button type="button" class="rt-x" aria-label="Close">&times;</button></div>' +
    '<p class="rt-hint">Ask any bot, e.g. "every weekday at 8 AM check my mail" or "tomorrow 6 PM remind me to call home". Times are IST.</p>' +
    '<div id="rt-list"></div><p id="rt-msg" class="rt-msg"></p>';
  document.body.appendChild(panel);

  const side = document.createElement('button');
  side.className = 'side-btn'; side.id = 'rtbtn'; side.type = 'button';
  side.innerHTML = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>Routines';
  const setb = $('#setbtn'); if (setb && setb.parentNode) setb.parentNode.insertBefore(side, setb);
  const nav = $('#bottomnav');
  let navb = null;
  if (nav) {
    navb = document.createElement('button'); navb.type = 'button'; navb.dataset.nav = 'routines';
    navb.innerHTML = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg><span>Routines</span>';
    const last = nav.querySelector('[data-nav="settings"]'); nav.insertBefore(navb, last);
  }

  function show(on) {
    panel.hidden = !on;
    if (navb) document.querySelectorAll('#bottomnav button').forEach((b) => b.classList.toggle('active', on && b === navb));
    if (on) { if (window.closeMobileSide) window.closeMobileSide(); load(); }
  }
  side.onclick = () => show(panel.hidden);
  if (navb) navb.onclick = () => show(panel.hidden);
  panel.querySelector('.rt-x').onclick = () => show(false);
  if (nav) nav.addEventListener('click', (e) => { const b = e.target.closest('button'); if (b && b !== navb) show(false); });

  async function load() {
    const d = await get('/api/routines'); const box = $('#rt-list'); box.innerHTML = '';
    const list = d.routines || [];
    if (!list.length) box.innerHTML = '<p class="rt-empty">No routines yet.</p>';
    list.forEach((r) => {
      const el = document.createElement('div'); el.className = 'rt-item' + (r.paused ? ' paused' : '');
      el.innerHTML = '<div class="rt-name">' + esc(r.name) + (r.bot ? ' <span class="rt-bot">' + esc(r.bot) + '</span>' : '') + '</div>' +
        '<div class="rt-sub">' + esc(r.schedule) + '</div>' +
        '<div class="rt-sub">' + (r.paused ? 'Paused' : 'Next: ' + esc(r.next_run || 'done')) +
        (r.last_run ? ' &middot; Last: ' + esc(r.last_run) + ' ' + esc(r.last_status) : '') + '</div>' +
        '<div class="rt-prompt">' + esc(r.prompt) + '</div>' +
        '<div class="rt-acts">' +
        '<button data-a="run">Run now</button>' +
        '<button data-a="' + (r.paused ? 'resume' : 'pause') + '">' + (r.paused ? 'Resume' : 'Pause') + '</button>' +
        '<button data-a="edit">Edit</button><button data-a="delete" class="danger">Delete</button></div>';
      el.querySelectorAll('button').forEach((b) => b.onclick = () => act(r, b.dataset.a));
      box.appendChild(el);
    });
  }
  async function act(r, a) {
    const body = { id: r.id, action: a };
    if (a === 'delete') { if (!confirm('Delete the routine "' + r.name + '"?')) return; body.confirm = true; }
    if (a === 'edit') {
      const when = prompt('When? (e.g. every day at 7 PM, tomorrow 9 AM)', r.when || ''); if (when === null) return;
      const p = prompt('What should it do?', r.prompt || ''); if (p === null) return;
      body.when = when; body.prompt = p;
    }
    const res = await post('/api/routines/update', body);
    $('#rt-msg').textContent = res.message || res.error || '';
    load();
  }

  // Run notifications: toast + phone notification (Android app) / browser notification.
  let since = Date.now() / 1000;
  function notify(f) {
    const title = 'Routine: ' + f.routine; const body = (f.status === 'ok' ? '' : '[' + f.status + '] ') + (f.text || 'Done');
    try { if (window.PedroNative && window.PedroNative.notify) window.PedroNative.notify(title, body);
      else if (window.Notification && Notification.permission === 'granted' && document.hidden) new Notification(title, { body }); } catch (e) {}
    const t = document.createElement('div'); t.className = 'rt-toast'; const ic = document.createElement('img'); ic.src = '/avatars/round.png'; ic.alt = ''; ic.className = 'rt-ic';
    t.appendChild(ic); t.appendChild(document.createTextNode(title + ' - ' + body.slice(0, 120)));
    t.onclick = () => { t.remove(); }; document.body.appendChild(t); setTimeout(() => t.remove(), 8000);
  }
  async function poll() {
    try {
      const d = await get('/api/routines/feed?since=' + since);
      (d.feed || []).forEach((f) => { since = Math.max(since, f.t); notify(f); });
      if ((d.feed || []).length) { if (!panel.hidden) load(); if (window.loadSessions) try { window.loadSessions(); } catch (e) {} }
    } catch (e) {}
  }
  setInterval(poll, 15000);
  side.addEventListener('click', () => { try { if (window.Notification && Notification.permission === 'default') Notification.requestPermission(); } catch (e) {} });
  if (location.hash === '#routines') show(true);
  window.PedroRoutines = { show, load };
})();
