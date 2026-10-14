// Live PC view (screen stream + activity feed + optional remote control),
// mobile bottom nav, and PWA registration.
(function (root) {
  'use strict';
  function clampFps(v, max) { v = parseFloat(v); if (!(v > 0)) v = 10; return Math.max(0.5, Math.min(max || 30, v)); }
  function normPoint(clientX, clientY, rect) {
    return { x: Math.max(0, Math.min(1, (clientX - rect.left) / rect.width)), y: Math.max(0, Math.min(1, (clientY - rect.top) / rect.height)) };
  }
  function ago(ts, now) { const s = Math.max(0, Math.round((now || Date.now() / 1000) - ts)); return s < 60 ? s + 's' : Math.round(s / 60) + 'm'; }
  if (typeof module !== 'undefined' && module.exports) { module.exports = { clampFps, normPoint, ago }; return; }

  const $ = (s) => document.querySelector(s);
  const pane = $('#livepane'); if (!pane) return;
  let lastId = 0, feedTimer = null, frameTimer = null, open = false, control = false;
  const post = (p, b) => fetch(p, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b || {}) }).then((r) => r.json());

  function startView() {
    const img = $('#live-img'), fps = clampFps($('#live-fps').value, 30); $('#live-fps-v').textContent = fps + ' fps';
    clearInterval(frameTimer); img.onerror = null;
    if ($('#live-mode').value === 'stream') {
      img.src = '/live/stream.mjpg?fps=' + fps + '&r=' + Date.now();
      img.onerror = () => { $('#live-mode').value = 'frames'; startView(); }; // some webviews lack MJPEG
    } else {
      const tick = () => { const n = new Image(); n.onload = () => { img.src = n.src; }; n.src = '/live/frame.jpg?r=' + Date.now(); };
      tick(); frameTimer = setInterval(tick, 1000 / fps);
    }
  }
  function stopView() { clearInterval(frameTimer); $('#live-img').src = ''; }
  async function feed() {
    try {
      const r = await (await fetch('/live/activity?after=' + lastId)).json();
      $('#live-now').textContent = r.busy ? 'Working: ' + r.now : 'Idle';
      $('#live-now').classList.toggle('busy', !!r.busy);
      control = !!r.control; $('#live-control').style.display = control ? '' : 'none';
      const box = $('#live-feed');
      (r.items || []).forEach((a) => {
        lastId = Math.max(lastId, a.id);
        const d = document.createElement('div'); d.className = 'feed-item ' + a.kind;
        const b = document.createElement('b'); b.textContent = a.label; const sp = document.createElement('span'); sp.textContent = ' ' + a.text;
        const t = document.createElement('time'); t.textContent = ago(a.t); d.append(b, sp, t); box.prepend(d);
      });
      while (box.children.length > 80) box.lastChild.remove();
    } catch (e) { $('#live-now').textContent = 'Offline'; }
  }
  function show(on) {
    open = on; pane.classList.toggle('open', on); document.body.classList.toggle('live-open', on);
    clearInterval(feedTimer);
    if (on) { startView(); feed(); feedTimer = setInterval(feed, 1500); } else stopView();
    setNav(on ? 'live' : 'chats');
  }
  root.showLive = show;
  $('#live-fps').onchange = () => { if (open) startView(); };
  $('#live-mode').onchange = () => { if (open) startView(); };
  $('#live-close').onclick = () => show(false);
  $('#livebtn').onclick = () => show(true);

  // Remote control (only when rules.yaml remote.allow_control is true).
  $('#live-allow').onclick = async () => {
    const r = await post('/live/control/allow', { confirm: 'yes' });
    $('#live-ctl-msg').textContent = r.ok ? r.message : (r.error || 'Not allowed');
  };
  $('#live-img').addEventListener('click', async (e) => {
    if (!control || !$('#live-ctl-on').checked) return;
    const p = normPoint(e.clientX, e.clientY, e.target.getBoundingClientRect());
    const r = await post('/live/control', { type: 'click', x: p.x, y: p.y });
    $('#live-ctl-msg').textContent = r.ok ? 'Clicked' : (r.error || 'Blocked');
  });
  $('#live-type').onsubmit = async (e) => {
    e.preventDefault(); const t = $('#live-text').value; if (!t) return;
    const r = await post('/live/control', { type: 'type', text: t }); $('#live-text').value = '';
    $('#live-ctl-msg').textContent = r.ok ? 'Typed' : (r.error || 'Blocked');
  };

  // Mobile bottom nav.
  function setNav(name) { document.querySelectorAll('#bottomnav button').forEach((b) => b.classList.toggle('active', b.dataset.nav === name)); }
  function sideOpen(on, focus) {
    const was = document.body.classList.contains('side-open');
    document.body.classList.toggle('side-open', on);
    if (on && !was) { try { history.pushState({ side: 1 }, ''); } catch (e) {} }
    else if (!on && was && history.state && history.state.side) { try { history.back(); } catch (e) {} }
    if (on && focus) { const el = $(focus); if (el) el.scrollIntoView({ block: 'start' }); }
  }
  root.closeMobileSide = () => sideOpen(false);
  document.querySelectorAll('#bottomnav button').forEach((b) => b.addEventListener('click', () => {
    const n = b.dataset.nav;
    if (n !== 'live' && open) show(false);
    if (n === 'chats') { sideOpen(!document.body.classList.contains('side-open'), '#sessions'); setNav('chats'); }
    else if (n === 'bots') { sideOpen(true, '#bots'); setNav('bots'); }
    else if (n === 'live') { sideOpen(false); show(true); }
    else if (n === 'settings') { sideOpen(false); $('#setbtn').click(); }
  }));
  document.getElementById('side').addEventListener('click', (e) => { if ((e.target.closest('.sess') || e.target.closest('#new') || e.target.closest('#livebtn') || e.target.closest('#setbtn')) && !e.target.closest('.edit')) sideOpen(false); });
  $('#menubtn').onclick = () => sideOpen(true, '#sessions');
  $('#sidescrim').addEventListener('click', () => sideOpen(false));
  window.addEventListener('popstate', () => { if (document.body.classList.contains('side-open')) document.body.classList.remove('side-open'); });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') sideOpen(false); });
  (function () { // swipe left to close the drawer
    const s = document.getElementById('side'); let x0 = null, y0 = 0;
    s.addEventListener('touchstart', (e) => { x0 = e.touches[0].clientX; y0 = e.touches[0].clientY; }, { passive: true });
    s.addEventListener('touchend', (e) => { if (x0 === null) return; const t = e.changedTouches[0];
      if (x0 - t.clientX > 60 && Math.abs(t.clientY - y0) < 60) sideOpen(false); x0 = null; }, { passive: true });
  })();

  // PWA: installable on Android (needs https, e.g. the Cloudflare link, or localhost).
  if ('serviceWorker' in navigator && (location.protocol === 'https:' || location.hostname === '127.0.0.1' || location.hostname === 'localhost')) {
    navigator.serviceWorker.register('/sw.js').catch(() => {});
  }
})(this);
