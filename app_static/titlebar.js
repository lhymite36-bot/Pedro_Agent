// Frameless desktop window (pywebview): drag strip, min/max/close glyphs, edge resize.
(function () {
  function init() {
    const api = window.pywebview && window.pywebview.api;
    if (!api || !api.toggle_maximize) return;
    document.documentElement.classList.add('desktop-app');
    const strip = document.createElement('div'); strip.id = 'dragstrip'; strip.className = 'pywebview-drag-region';
    document.body.appendChild(strip);
    const hdr = document.querySelector('header'); if (hdr) hdr.classList.add('pywebview-drag-region');
    const box = document.createElement('div'); box.id = 'winctl';
    const ico = {
      min: '<svg viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.15" stroke-linecap="round"><path d="M2 6h8"/></svg>',
      max: '<svg viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.15" stroke-linejoin="round"><rect x="2.2" y="2.2" width="7.6" height="7.6" rx="0.8"/></svg>',
      res: '<svg viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.15" stroke-linejoin="round"><rect x="1.8" y="3.4" width="6.6" height="6.6" rx="0.6"/><path d="M4.2 3.4V2.2h6.6v6.6H9.6"/></svg>',
      close: '<svg viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.15" stroke-linecap="round"><path d="M2.6 2.6l6.8 6.8M9.4 2.6l-6.8 6.8"/></svg>' };
    const mk = (id, title, svg, fn) => { const b = document.createElement('button'); b.type = 'button'; b.id = id; b.title = title; b.innerHTML = svg; b.onclick = fn; box.appendChild(b); return b; };
    mk('wc-min', 'Minimise', ico.min, () => api.minimize());
    const mx = mk('wc-max', 'Maximise', ico.max, async () => { const on = await api.toggle_maximize(); mx.innerHTML = on ? ico.res : ico.max; mx.title = on ? 'Restore' : 'Maximise'; });
    mk('wc-close', 'Close', ico.close, () => api.close());
    document.body.appendChild(box);
    // 1.4.19/1.5.0: a press on the header (not on its buttons/inputs) starts Windows' own move loop, so snap works
    const native = async () => { for (let i = 0; i < 20; i++) { try { if (api.snap_ready && await api.snap_ready()) return true; } catch (e) { return false; } await new Promise((r) => setTimeout(r, 500)); } return false; };
    native().then((ok) => {
      if (!ok) return;
      [strip, hdr].forEach((el) => { if (!el) return; el.classList.remove('pywebview-drag-region');
        el.addEventListener('mousedown', (e) => {
          if (e.button !== 0 || e.detail > 1) return;
          if (e.target.closest('button, a, input, select, textarea, [contenteditable], .no-drag')) return;
          api.start_drag();
        });
      });
    });
    if (hdr) hdr.addEventListener('dblclick', (e) => { if (e.target === hdr || e.target.closest('.who')) mx.click(); });
    // edge resize: right, bottom, corner
    ['r', 'b', 'rb', 'l'].forEach((edge) => {
      const h = document.createElement('div'); h.className = 'rz rz-' + edge; document.body.appendChild(h);
      h.addEventListener('pointerdown', async (e) => {
        e.preventDefault(); h.setPointerCapture(e.pointerId);
        const g = await api.geometry(); const sx = e.screenX, sy = e.screenY; let busy = false, last = null;
        const move = (ev) => { last = ev; if (busy) return; busy = true; requestAnimationFrame(async () => {
          const dx = last.screenX - sx, dy = last.screenY - sy;
          let { x, y, w, h: hh } = g;
          if (edge.includes('r')) w += dx; if (edge.includes('b')) hh += dy; if (edge === 'l') { x += dx; w -= dx; }
          await api.set_geometry(x, y, w, hh); busy = false; }); };
        const up = () => { h.removeEventListener('pointermove', move); h.removeEventListener('pointerup', up); };
        h.addEventListener('pointermove', move); h.addEventListener('pointerup', up);
      });
    });
  }
  if (window.pywebview) init(); else window.addEventListener('pywebviewready', init);
})();
