// 1.4.14 Settings > Connections & updates: updates, Google sign-ins, local crash reports.
(function () {
  const q = (s) => document.querySelector(s);
  const get = async (p) => (await fetch(p)).json();
  const post = async (p, b) => (await fetch(p, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b || {}) })).json();
  function esc(t) { const d = document.createElement('div'); d.textContent = String(t == null ? '' : t); return d.innerHTML; }

  async function showUpdate(info) {
    info = info || await get('/api/update');
    const line = q('#upd-line'); if (!line) return;
    line.textContent = info.message || ('Ped Bot ' + (info.current || '') + (info.update_available ? '' : ' is up to date.'));
    q('#upd-get').hidden = !info.update_available || !!info.downloaded;
    q('#upd-install').hidden = !info.downloaded;
    const banner = q('#update-banner');
    if (info.update_available && !banner) {
      const b = document.createElement('button'); b.id = 'update-banner'; b.className = 'btn update-banner'; b.type = 'button';
      b.textContent = 'Update available: ' + info.latest; b.onclick = () => { const s = document.querySelector('[data-nav="settings"]'); if (s) s.click(); const t = document.querySelector('[data-pane="p-updates"]'); if (t) t.click(); };
      const hdr = document.querySelector('header') || document.body; hdr.appendChild(b);
    }
  }
  if (q('#upd-check')) {
    q('#upd-check').onclick = async () => { q('#upd-line').textContent = 'Checking…'; showUpdate(await post('/api/update/check')); };
    q('#upd-get').onclick = async () => { q('#upd-line').textContent = 'Downloading and checking the SHA-256…'; const r = await post('/api/update/download'); q('#upd-line').textContent = r.message || r.error; if (r.ok) { q('#upd-get').hidden = true; q('#upd-install').hidden = false; } };
    q('#upd-install').onclick = async () => { if (!confirm('Install the update now? Ped Bot will close; your chats and settings stay.')) return; const r = await post('/api/update/install', { confirm: 'yes' }); q('#upd-line').textContent = r.message || r.error; };
  }

  async function showConnections() {
    const box = q('#conn-list'); if (!box) return;
    const st = await get('/api/connections');
    q('#conn-setup').textContent = st.setup || '';
    box.innerHTML = '';
    (st.services || []).forEach((s) => {
      const row = document.createElement('div'); row.className = 'conn-row';
      row.innerHTML = '<span>' + esc(s.label) + ' <small>' + (s.connected ? 'connected' : 'not connected') + '</small></span>';
      const b = document.createElement('button'); b.className = 'btn'; b.type = 'button'; b.textContent = s.connected ? 'Disconnect' : 'Connect';
      b.disabled = !s.connected && !st.client_ready;
      b.onclick = async () => {
        b.disabled = true; b.textContent = s.connected ? 'Disconnecting…' : 'Sign in on the Google page…';
        const r = await post(s.connected ? '/api/connections/disconnect' : '/api/connections/connect', { service: s.id });
        if (!r.ok && r.error) q('#conn-setup').textContent = r.error;
        showConnections();
      };
      row.appendChild(b); box.appendChild(row);
    });
  }

  async function showCrashes() {
    const box = q('#crash-list'); if (!box) return;
    const r = await get('/api/crashes'); box.innerHTML = '';
    if (!(r.reports || []).length) { box.innerHTML = '<small>No crash reports.</small>'; return; }
    r.reports.forEach((c) => {
      const row = document.createElement('div'); row.className = 'conn-row';
      row.innerHTML = '<span><b>' + esc(new Date(c.when * 1000).toLocaleString()) + '</b> <small>' + esc(c.summary) + '</small></span>';
      const b = document.createElement('button'); b.className = 'btn'; b.type = 'button'; b.textContent = 'Copy report';
      b.onclick = async () => { const t = await get('/api/crashes?name=' + encodeURIComponent(c.name)); try { await navigator.clipboard.writeText(t.text); b.textContent = 'Copied'; } catch (e) { const ta = document.createElement('textarea'); ta.value = t.text; document.body.appendChild(ta); ta.select(); document.execCommand('copy'); ta.remove(); b.textContent = 'Copied'; } };
      row.appendChild(b); box.appendChild(row);
    });
  }
  if (q('#crash-open')) q('#crash-open').onclick = async () => { const r = await post('/api/crashes/open'); if (!r.ok) alert(r.error || 'Could not open the folder.'); };

  async function showBackground() {
    const st = await get('/api/background');
    const map = { '#bg-keep': 'keep_running', '#bg-start': 'start_with_windows', '#bg-notes': 'notifications' };
    Object.entries(map).forEach(([sel, key]) => {
      const el = q(sel); if (!el) return; el.checked = !!st[key];
      el.onchange = async () => { const r = await post('/api/background', { [key]: el.checked }); el.checked = !!r[key]; };
    });
  }
  async function showShorts() {
    const st = await get('/api/shorts'); if (!q('#qbs-on')) return;
    q('#qbs-on').checked = !!st.enabled; q('#qbs-vts').value = st.vts_dir || '';
    if (q('#qbs-yt-channel')) q('#qbs-yt-channel').value = st.youtube_channel || '';
    if (q('#qbs-tt-channel')) q('#qbs-tt-channel').value = st.tiktok_channel || '';
    if (q('#qbs-ai')) q('#qbs-ai').checked = !!st.mark_ai_generated;
    const last = (st.last_run && (st.last_run.error || st.last_run.message)) ? (' Last run: ' + (st.last_run.ok === false ? ('failed — ' + (st.last_run.error || 'error')) : 'ok') + '.') : '';
    q('#qbs-line').textContent = (st.token_set ? 'Buffer token saved on this PC.' : 'No Buffer token yet.') + (st.missing && st.missing.length ? ' Still needed: ' + st.missing.join(', ') + '.' : ' Ready to post when switched on.') + last;
    q('#qbs-on').onchange = async () => { const r = await post('/api/shorts', { enabled: q('#qbs-on').checked }); q('#qbs-on').checked = !!r.enabled; };
    q('#qbs-vts').onchange = () => post('/api/shorts', { vts_dir: q('#qbs-vts').value.trim() });
    const saveExtra = () => post('/api/shorts', {
      youtube_channel: q('#qbs-yt-channel') ? q('#qbs-yt-channel').value.trim() : undefined,
      tiktok_channel: q('#qbs-tt-channel') ? q('#qbs-tt-channel').value.trim() : undefined,
      mark_ai_generated: q('#qbs-ai') ? !!q('#qbs-ai').checked : undefined,
    });
    if (q('#qbs-yt-channel')) q('#qbs-yt-channel').onchange = saveExtra;
    if (q('#qbs-tt-channel')) q('#qbs-tt-channel').onchange = saveExtra;
    if (q('#qbs-ai')) q('#qbs-ai').onchange = saveExtra;
    q('#qbs-save').onclick = async () => { const r = await post('/api/shorts/token', { token: q('#qbs-token').value }); q('#qbs-token').value = ''; q('#qbs-line').textContent = r.message || r.error; };
    q('#qbs-dry').onclick = async () => { q('#qbs-line').textContent = 'Planning (nothing is posted)…'; const r = await post('/api/shorts/dry_run'); q('#qbs-line').textContent = r.message || r.error; };
  }
  const tab0 = document.querySelector('[data-pane="p-more"]');
  if (tab0) tab0.addEventListener('click', () => { showShorts().catch(() => {}); });
  const tab = document.querySelector('[data-pane="p-more"]');
  if (tab) tab.addEventListener('click', () => { showBackground().catch(() => {}); });
  if (tab) tab.addEventListener('click', () => { showUpdate(); showConnections(); showCrashes(); });
  setTimeout(() => showUpdate().catch(() => {}), 40000);
})();
