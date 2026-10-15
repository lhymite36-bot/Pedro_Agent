// Live PC view (screen stream + activity feed + optional remote control),
// mobile bottom nav, and PWA registration.
(function (root) {
  'use strict';
  function clampFps(v, max) { v = parseFloat(v); if (!(v > 0)) v = 10; return Math.max(0.5, Math.min(max || 30, v)); }
  function clampSize(v) { v = parseFloat(v); if (!(v >= 40)) v = 62; return Math.max(40, Math.min(100, v)); }
  function normPoint(clientX, clientY, rect) {
    return { x: Math.max(0, Math.min(1, (clientX - rect.left) / rect.width)), y: Math.max(0, Math.min(1, (clientY - rect.top) / rect.height)) };
  }
  function containedPoint(clientX, clientY, rect, naturalW, naturalH) {
    const rw = rect.width, rh = rect.height;
    if (!(rw > 0) || !(rh > 0)) return null;
    if (!(naturalW > 0) || !(naturalH > 0)) {
      if (clientX < rect.left || clientY < rect.top || clientX > rect.left + rw || clientY > rect.top + rh) return null;
      return normPoint(clientX, clientY, rect);
    }
    const scale = Math.min(rw / naturalW, rh / naturalH);
    const dw = naturalW * scale, dh = naturalH * scale;
    const left = rect.left + (rw - dw) / 2, top = rect.top + (rh - dh) / 2;
    if (clientX < left || clientY < top || clientX > left + dw || clientY > top + dh) return null;
    return { x: Math.max(0, Math.min(1, (clientX - left) / dw)), y: Math.max(0, Math.min(1, (clientY - top) / dh)) };
  }
  function ago(ts, now) { const s = Math.max(0, Math.round((now || Date.now() / 1000) - ts)); return s < 60 ? s + 's' : Math.round(s / 60) + 'm'; }
  if (typeof module !== 'undefined' && module.exports) { module.exports = { clampFps, clampSize, normPoint, containedPoint, ago }; return; }

  const $ = (s) => document.querySelector(s);
  const pane = $('#livepane'); if (!pane) return;
  let lastId = 0, feedTimer = null, frameTimer = null, open = false, control = false, localMode = false;
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
      localMode = !!r.local;
      control = true;
      armControl();
      const feedBox = $('#live-feed');
      (r.items || []).forEach((a) => {
        lastId = Math.max(lastId, a.id);
        const d = document.createElement('div'); d.className = 'feed-item ' + a.kind;
        const b = document.createElement('b'); b.textContent = a.label; const sp = document.createElement('span'); sp.textContent = ' ' + a.text;
        const t = document.createElement('time'); t.textContent = ago(a.t); d.append(b, sp, t); feedBox.prepend(d);
      });
      while (feedBox.children.length > 80) feedBox.lastChild.remove();
    } catch (e) { $('#live-now').textContent = 'Offline'; }
  }
  function show(on) {
    open = on; pane.classList.toggle('open', on); document.body.classList.toggle('live-open', on);
    clearInterval(feedTimer);
    if (on) { armControl(); startView(); feed(); feedTimer = setInterval(feed, 1500); } else stopView();
    setNav(on ? 'live' : 'chats');
  }
  root.showLive = show;
  $('#live-fps').onchange = () => { if (open) startView(); };
  $('#live-mode').onchange = () => { if (open) startView(); };
  $('#live-close').onclick = () => show(false);
  $('#livebtn').onclick = () => show(true);

  function narrowScreen() { return window.matchMedia('(max-width: 760px)').matches; }
  function applySize(v) {
    const n = clampSize(v);
    const img = $('#live-img');
    if (img) {
      if (narrowScreen()) {
        img.style.width = n + '%';
        img.style.maxWidth = n + '%';
        img.style.maxHeight = '80vh';
      } else {
        img.style.width = '';
        img.style.maxWidth = '100%';
        img.style.maxHeight = n + 'vh';
      }
    }
    const label = $('#live-size-v'); if (label) label.textContent = String(Math.round(n));
    const slider = $('#live-size'); if (slider && String(slider.value) !== String(Math.round(n))) slider.value = String(Math.round(n));
    try { localStorage.liveSize = String(Math.round(n)); } catch (e) {}
  }
  const sizeSlider = $('#live-size');
  if (sizeSlider) {
    try { applySize(localStorage.liveSize || sizeSlider.value); } catch (e) { applySize(sizeSlider.value); }
    sizeSlider.oninput = () => applySize(sizeSlider.value);
    window.addEventListener('resize', () => applySize(sizeSlider.value));
  }
  const resizeHandle = $('#live-resize');
  if (resizeHandle) {
    resizeHandle.addEventListener('pointerdown', (e) => {
      e.preventDefault(); e.stopPropagation();
      const startY = e.clientY, start = clampSize(sizeSlider ? sizeSlider.value : 62);
      const vh = window.innerHeight || 800;
      function move(ev) { applySize(start + ((ev.clientY - startY) / vh) * 100); }
      function up() { window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', up); }
      window.addEventListener('pointermove', move);
      window.addEventListener('pointerup', up);
    });
  }

  function aiming() { return $('#live-ctl-on') && $('#live-ctl-on').checked; }
  function aimCursor() { const img = $('#live-img'); if (img) img.classList.toggle('live-aim', aiming()); }
  function armControl() {
    const bar = $('#live-control'); if (bar) bar.style.display = '';
    const allowBtn = $('#live-allow'); if (allowBtn) allowBtn.hidden = true;
    const box = $('#live-ctl-on');
    if (box && !box.dataset.set) {
      try { box.checked = localStorage.liveControl !== '0'; } catch (e) { box.checked = true; }
      box.dataset.set = '1';
      const label = $('#live-ctl-label'); if (label) label.textContent = 'Tap, drag, and scroll';
    }
    aimCursor();
  }
  const ctlBox = $('#live-ctl-on');
  if (ctlBox) ctlBox.addEventListener('change', () => {
    try { localStorage.liveControl = ctlBox.checked ? '1' : '0'; } catch (e) {}
    aimCursor();
  });
  function noteCtl(r) { const el = $('#live-ctl-msg'); if (el) el.textContent = r && r.ok ? (r.message || 'Sent') : ((r && r.error) || 'Blocked'); }
  let controlChain = Promise.resolve();
  function sendCtl(body) {
    controlChain = controlChain.then(() => post('/live/control', body).then(noteCtl).catch(() => {}));
    return controlChain;
  }
  function picturePoint(e) {
    const img = $('#live-img');
    return containedPoint(e.clientX, e.clientY, img.getBoundingClientRect(), img.naturalWidth, img.naturalHeight);
  }

  // A signed-in phone uses the same picture gestures as this PC.
  const liveImg = $('#live-img');
  let hold = null;
  const pointers = new Set();
  let pinch = null;
  liveImg.addEventListener('pointerdown', (e) => {
    if (!aiming() || e.button > 2) return;
    pointers.add(e.pointerId);
    if (pointers.size > 1) {
      if (hold && hold.sentDown) sendCtl({ type: 'up', x: hold.x, y: hold.y, button: hold.button });
      const p = picturePoint(e);
      hold = null;
      pinch = { y: e.clientY, acc: 0, x: p ? p.x : 0.5, yNorm: p ? p.y : 0.5 };
      e.preventDefault();
      return;
    }
    const p = picturePoint(e); if (!p) return;
    e.preventDefault();
    hold = { x: p.x, y: p.y, cx: e.clientX, cy: e.clientY, button: e.button === 2 ? 'right' : 'left', moved: false, sentDown: false, last: 0 };
    try { liveImg.setPointerCapture(e.pointerId); } catch (err) {}
  });
  liveImg.addEventListener('pointermove', (e) => {
    if (pointers.size > 1 && pinch && aiming()) {
      e.preventDefault();
      pinch.acc += e.clientY - pinch.y;
      pinch.y = e.clientY;
      if (Math.abs(pinch.acc) < 28) return;
      sendCtl({ type: 'scroll', x: pinch.x, y: pinch.yNorm, delta: pinch.acc > 0 ? 80 : -80 });
      pinch.acc = 0;
      return;
    }
    if (!hold) return;
    if (Math.hypot(e.clientX - hold.cx, e.clientY - hold.cy) < 7 && !hold.moved) return;
    const p = picturePoint(e); if (!p) return;
    hold.moved = true; hold.x2 = p.x; hold.y2 = p.y;
    const now = Date.now();
    if (!hold.sentDown) {
      hold.sentDown = true;
      sendCtl({ type: 'down', x: hold.x, y: hold.y, button: hold.button });
    }
    if (now - hold.last < 50) return;
    hold.last = now;
    sendCtl({ type: 'move', x: p.x, y: p.y });
  });
  function endHold(e) {
    if (e && e.pointerId != null) pointers.delete(e.pointerId);
    if (pointers.size < 2) pinch = null;
    if (!hold) return;
    const start = hold; hold = null;
    const p = (e && picturePoint(e)) || { x: start.x2 || start.x, y: start.y2 || start.y };
    if (start.moved) sendCtl({ type: 'up', x: p.x, y: p.y, button: start.button });
    else sendCtl({ type: 'click', x: p.x, y: p.y, button: start.button });
  }
  liveImg.addEventListener('pointerup', endHold);
  liveImg.addEventListener('pointercancel', endHold);
  liveImg.addEventListener('contextmenu', (e) => { if (aiming()) e.preventDefault(); });
  liveImg.addEventListener('wheel', (e) => {
    if (!aiming()) return;
    const p = picturePoint(e); if (!p) return;
    e.preventDefault();
    sendCtl({ type: 'scroll', x: p.x, y: p.y, delta: e.deltaY });
  }, { passive: false });
  $('#live-type').onsubmit = async (e) => {
    e.preventDefault(); const t = $('#live-text').value; if (!t) return;
    const r = await post('/live/control', { type: 'type', text: t }); $('#live-text').value = '';
    noteCtl(r.ok ? { ok: true, message: 'Typed' } : r);
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
