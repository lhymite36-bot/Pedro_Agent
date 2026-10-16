// Connectors page: sign a service in once, then Pedro can search it.
(function () {
  const $ = (s) => document.querySelector(s);
  const esc = (t) => String(t == null ? '' : t).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const get = (p) => fetch(p).then((r) => r.json());
  const post = (p, b) => fetch(p, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) }).then((r) => r.json());

  const panel = document.createElement('section');
  panel.id = 'connectors'; panel.className = 'cn-panel'; panel.hidden = true; panel.setAttribute('aria-label', 'Connectors');
  panel.innerHTML = '<div class="cn-head"><h2>Connectors</h2><button type="button" class="cn-x" aria-label="Close">&times;</button></div>' +
    '<p class="cn-hint">Connect a service once. Pedro can then read it when you ask. Sending still waits for a yes. Secrets stay on this PC.</p>' +
    '<input id="cn-find" class="cn-find" type="search" placeholder="Search connectors" autocomplete="off">' +
    '<div id="cn-list"></div><p id="cn-msg" class="cn-msg"></p>';
  document.body.appendChild(panel);

  const side = document.createElement('button');
  side.className = 'side-btn'; side.id = 'connbtn'; side.type = 'button';
  side.innerHTML = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 7V4a3 3 0 0 1 6 0v3"/><rect x="4" y="7" width="16" height="13" rx="2"/><path d="M12 12v3"/></svg>Connectors';
  const setb = $('#setbtn'); if (setb && setb.parentNode) setb.parentNode.insertBefore(side, setb);
  const nav = $('#bottomnav');
  let navb = null;
  if (nav) {
    navb = document.createElement('button'); navb.type = 'button'; navb.dataset.nav = 'connectors';
    navb.innerHTML = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 7V4a3 3 0 0 1 6 0v3"/><rect x="4" y="7" width="16" height="13" rx="2"/></svg><span>Connectors</span>';
    const last = nav.querySelector('[data-nav="settings"]'); nav.insertBefore(navb, last);
  }

  function show(on) {
    panel.hidden = !on;
    if (navb) document.querySelectorAll('#bottomnav button').forEach((b) => b.classList.toggle('active', on && b === navb));
    if (on) { if (window.closeMobileSide) window.closeMobileSide(); load(); }
  }
  side.onclick = () => show(panel.hidden);
  if (navb) navb.onclick = () => show(panel.hidden);
  panel.querySelector('.cn-x').onclick = () => show(false);
  if (nav) nav.addEventListener('click', (e) => { const b = e.target.closest('button'); if (b && b !== navb) show(false); });
  panel.querySelector('#cn-find').addEventListener('input', () => draw(window._cnRows || []));

  function formFor(row) {
    if (row.kind === 'gmail') {
      return '<label>Gmail address<input class="cn-address" type="email" autocomplete="off" placeholder="you@gmail.com"></label>' +
        '<label>App password<input class="cn-secret" type="password" autocomplete="off" placeholder="App password"></label>' +
        '<button type="button" class="cn-go">Connect</button>';
    }
    if (row.kind === 'token') {
      return '<label>Token<input class="cn-secret" type="password" autocomplete="off" placeholder="Paste token"></label>' +
        '<button type="button" class="cn-go">Connect</button>';
    }
    if (row.kind === 'youtube' && !row.connected) return '<button type="button" class="cn-go">Connect</button>';
    if (!row.connected && (row.kind === 'folder' || row.kind === 'github' || row.kind === 'outlook')) return '';
    return '';
  }

  function draw(rows) {
    const q = (panel.querySelector('#cn-find').value || '').trim().toLowerCase();
    const box = $('#cn-list'); box.innerHTML = '';
    rows.filter((row) => !q || (row.name + ' ' + row.blurb).toLowerCase().includes(q)).forEach((row) => {
      const card = document.createElement('article');
      card.className = 'cn-item' + (row.connected ? ' on' : '');
      card.innerHTML = '<div class="cn-top"><b>' + esc(row.name) + '</b><span class="cn-pill">' + (row.connected ? 'Connected' : 'Not connected') + '</span></div>' +
        '<p>' + esc(row.blurb) + '</p>' +
        (row.account ? '<p class="cn-account">' + esc(row.account) + '</p>' : '') +
        (row.detail ? '<p class="cn-detail">' + esc(row.detail) + '</p>' : '') +
        '<div class="cn-acts">' + formFor(row) + (row.connected && (row.kind === 'gmail' || row.kind === 'token') ? '<button type="button" class="cn-off">Disconnect</button>' : '') + '</div>';
      const go = card.querySelector('.cn-go');
      if (go) go.onclick = async () => {
        const secret = card.querySelector('.cn-secret');
        const address = card.querySelector('.cn-address');
        const body = { action: 'connect', id: row.id };
        if (address) body.address = address.value.trim();
        if (secret) body.secret = secret.value;
        $('#cn-msg').textContent = 'Connecting…';
        const result = await post('/api/connectors', body);
        if (secret) secret.value = '';
        $('#cn-msg').textContent = result.ok ? (result.message || 'Connected.') : (result.error || 'Could not connect.');
        if (result.ok) load();
      };
      const off = card.querySelector('.cn-off');
      if (off) off.onclick = async () => {
        const result = await post('/api/connectors', { action: 'disconnect', id: row.id });
        $('#cn-msg').textContent = result.ok ? (result.message || 'Disconnected.') : (result.error || 'Could not disconnect.');
        load();
      };
      box.appendChild(card);
    });
    if (!box.children.length) box.innerHTML = '<p class="cn-empty">No connectors match.</p>';
  }

  async function load() {
    const data = await get('/api/connectors');
    window._cnRows = data.connectors || [];
    draw(window._cnRows);
  }
  window.openConnectors = () => show(true);
})();
