// 1.6.1 Settings > Connections > WhatsApp: QR link, status dot, disconnect/logout, ask-before-sending, allowlist.
(function () {
  const q = (s) => document.getElementById(s);
  if (!q('wa-box')) return;
  const get = async (p) => (await fetch(p)).json();
  const post = async (p, b) => (await fetch(p, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b || {}) })).json();
  const LABEL = { off: 'off', starting: 'starting…', qr: 'scan the QR code', connected: 'connected', reconnecting: 'reconnecting…', logged_out: 'logged out', error: 'error', stopped: 'stopped' };
  let timer = null, editing = false;
  function paint(s) {
    const st = s.state || 'off', on = st === 'connected';
    q('wa-state').textContent = (LABEL[st] || st) + (on && s.me && s.me.name ? ' as ' + s.me.name : '');
    for (const id of ['wa-dot', 'st-wa']) { const d = q(id); if (d) { d.classList.toggle('on', on); d.style.background = on ? '#3ecf8e' : st === 'qr' || st === 'reconnecting' || st === 'starting' ? '#e0b341' : ''; } }
    if (q('st-wa-t')) q('st-wa-t').textContent = LABEL[st] || st;
    const qr = q('wa-qr'); qr.hidden = st !== 'qr' || !s.qr_svg; if (!qr.hidden) qr.innerHTML = s.qr_svg;
    q('wa-connect').hidden = !!s.enabled && st !== 'error' && st !== 'logged_out' && st !== 'stopped';
    q('wa-disconnect').hidden = !s.enabled; q('wa-logout').hidden = !(s.enabled || s.me);
    q('wa-ask').checked = s.ask_before_sending !== false;
    if (!editing) q('wa-allow').value = (s.allowlist || []).join(', ');
    q('wa-notice').textContent = s.notice || '';
    q('wa-err').textContent = s.node === false ? 'Node.js is missing; reinstall Ped Bot.' : (s.error || '');
    clearTimeout(timer); timer = setTimeout(refresh, st === 'qr' || st === 'starting' || st === 'reconnecting' ? 2000 : 10000);
  }
  async function refresh() { try { paint(await get('/api/whatsapp/status')); } catch (e) { clearTimeout(timer); timer = setTimeout(refresh, 15000); } }
  q('wa-connect').onclick = async () => { q('wa-state').textContent = 'starting…'; paint(await post('/api/whatsapp/connect')); };
  q('wa-disconnect').onclick = async () => paint(await post('/api/whatsapp/disconnect'));
  q('wa-logout').onclick = async () => { if (!confirm('Log out of WhatsApp on this PC and delete the saved link? You will need to scan a new QR code.')) return; paint(await post('/api/whatsapp/logout', { confirm: true })); };
  q('wa-ask').onchange = async () => paint({ ...(await post('/api/whatsapp/settings', { ask_before_sending: q('wa-ask').checked })), state: undefined }) || refresh();
  q('wa-allow').onfocus = () => { editing = true; };
  q('wa-allow').onchange = async () => { editing = false; await post('/api/whatsapp/settings', { allowlist: q('wa-allow').value.split(/[,\s]+/).filter(Boolean) }); refresh(); };
  refresh();
})();
