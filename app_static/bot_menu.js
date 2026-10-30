// 1.6.8: long-press (phone, ~450ms + haptic) / right-click (PC) menu for a bot row, Grok style.
// Mark Unread, Pin, Move to >, Share as Template, Hide, More > (Copy ID, Duplicate, Delete).
// State (sections, pinned, hidden, unread) lives on the PC in storage/bot_home.json via /api/bot_home.
(function () {
  const S = (d) => '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">' + d + '</svg>';
  const IC = {   // Lucide icons (MIT), bundled inline
    unread: S('<path d="M11.7 3H5a2 2 0 0 0-2 2v16l4-4h12a2 2 0 0 0 2-2v-2.7"/><circle cx="18" cy="6" r="3"/>'),
    pin: S('<path d="M12 17v5"/><path d="M9 10.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24V16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-.76a2 2 0 0 0-1.11-1.79l-1.78-.9A2 2 0 0 1 15 10.76V7a1 1 0 0 1 1-1 2 2 0 0 0 0-4H8a2 2 0 0 0 0 4 1 1 0 0 1 1 1z"/>'),
    folder: S('<path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/>'),
    folderPlus: S('<path d="M12 10v6M9 13h6"/><path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/>'),
    share: S('<path d="M12 2v13"/><path d="m16 6-4-4-4 4"/><path d="M4 12v8a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-8"/>'),
    hide: S('<path d="M10.73 5.08A10.43 10.43 0 0 1 12 5c7 0 10 7 10 7a13.16 13.16 0 0 1-1.67 2.68"/><path d="M6.61 6.61A13.53 13.53 0 0 0 2 12s3 7 10 7a9.74 9.74 0 0 0 5.39-1.61"/><path d="M14.12 14.12a3 3 0 1 1-4.24-4.24"/><path d="m2 2 20 20"/>'),
    eye: S('<path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/>'),
    more: S('<circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/><circle cx="5" cy="12" r="1"/>'),
    copy: S('<rect width="14" height="14" x="8" y="8" rx="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/>'),
    dup: S('<rect width="18" height="18" x="3" y="3" rx="2"/><path d="M8 12h8M12 8v8"/>'),
    trash: S('<path d="M3 6h18"/><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"/><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/><path d="M10 11v6M14 11v6"/>'),
    right: S('<path d="m9 18 6-6-6-6"/>'), left: S('<path d="m15 18-6-6 6-6"/>'), check: S('<path d="M20 6 9 17l-5-5"/>'),
  };
  let home = { sections: [], pinned: [], hidden: [], unread: [] };
  const listeners = [];
  const post = (u, b) => fetch(u, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b || {}) }).then((r) => r.json());
  const toast = (t) => { if (window.pbToast) window.pbToast(t); else { const d = document.createElement('div'); d.className = 'bm-toast'; d.textContent = t; document.body.appendChild(d); setTimeout(() => d.remove(), 2200); } };
  function changed() { listeners.forEach((f) => { try { f(home); } catch (e) {} }); }
  async function load() { try { const r = await (await fetch('/api/bot_home')).json(); if (r && r.sections) home = r; } catch (e) {} return home; }
  async function op(name, data) {
    const r = await post('/api/bot_home', Object.assign({ op: name }, data || {}));
    if (r && r.ok) { home = r.home; changed(); } else toast((r && r.error) || 'That did not work.');
    return r;
  }
  function el(t, c, x) { const e = document.createElement(t); if (c) e.className = c; if (x != null) e.textContent = x; return e; }
  function close() { const m = document.getElementById('bm-wrap'); if (m) m.remove(); }
  function item(icon, label, fn, opts) {
    const b = el('button', 'bm-item' + (opts && opts.red ? ' red' : '')); b.type = 'button';
    b.innerHTML = '<span class="bm-ic">' + icon + '</span>'; b.appendChild(el('span', 'bm-label', label));
    if (opts && opts.sub) b.insertAdjacentHTML('beforeend', '<span class="bm-chev">' + IC.right + '</span>');
    if (opts && opts.check) b.insertAdjacentHTML('beforeend', '<span class="bm-chev">' + IC.check + '</span>');
    b.onclick = (e) => { e.stopPropagation(); fn(); };
    return b;
  }
  function header(label, back) {
    const h = el('button', 'bm-head'); h.type = 'button'; h.innerHTML = '<span class="bm-ic">' + IC.left + '</span>';
    h.appendChild(el('span', 'bm-label', label)); h.onclick = (e) => { e.stopPropagation(); back(); }; return h;
  }
  function sectionOf(id) { return (home.sections.find((s) => s.ids.includes(id)) || {}).id || ''; }
  async function share(bot) {
    try {
      if (window.PedroNative && window.PedroNative.shareText) {
        const t = await (await fetch('/api/bots/template?id=' + encodeURIComponent(bot.id))).text();
        window.PedroNative.shareText(bot.name + ' - Ped Bot template', t); return;
      }
      const onPc = /^(127\.0\.0\.1|localhost)$/.test(location.hostname);
      if (onPc) { const r = await post('/api/bots/template_save', { id: bot.id }); toast(r.ok ? r.message : (r.error || 'Could not save it.')); return; }
      const a = document.createElement('a'); a.href = '/api/bots/template?id=' + encodeURIComponent(bot.id); a.download = bot.id + '-template.json';
      document.body.appendChild(a); a.click(); a.remove(); toast('Template downloaded');
    } catch (e) { toast('Could not share it.'); }
  }
  async function copyId(bot) {
    let ok = false;
    try { if (window.PedroNative && window.PedroNative.copyText) { window.PedroNative.copyText(bot.id); ok = true; } } catch (e) {}
    if (!ok) try { await navigator.clipboard.writeText(bot.id); ok = true; } catch (e) {}
    if (!ok) { const t = el('textarea'); t.value = bot.id; document.body.appendChild(t); t.select(); try { ok = document.execCommand('copy'); } catch (e) {} t.remove(); }
    toast(ok ? 'Copied ID: ' + bot.id : 'Could not copy');
  }
  function confirmBox(title, text, yes, fn) {
    const w = el('div', 'bm-dim'); w.id = 'bm-confirm'; const c = el('div', 'bm-dialog');
    c.append(el('h3', '', title), el('p', '', text));
    const row = el('div', 'bm-actions');
    const no = el('button', 'bm-btn', 'Cancel'); no.type = 'button'; no.onclick = () => w.remove();
    const ok = el('button', 'bm-btn red', yes); ok.type = 'button'; ok.onclick = () => { w.remove(); fn(); };
    row.append(no, ok); c.appendChild(row); w.appendChild(c); w.onclick = (e) => { if (e.target === w) w.remove(); };
    document.body.appendChild(w); return w;
  }
  function promptBox(title, value, fn) {
    const w = el('div', 'bm-dim'); w.id = 'bm-prompt'; const c = el('div', 'bm-dialog'); c.appendChild(el('h3', '', title));
    const inp = el('input', 'bm-input'); inp.value = value || ''; inp.maxLength = 40; c.appendChild(inp);
    const row = el('div', 'bm-actions');
    const no = el('button', 'bm-btn', 'Cancel'); no.type = 'button'; no.onclick = () => w.remove();
    const ok = el('button', 'bm-btn blue', 'Create'); ok.type = 'button';
    ok.onclick = () => { const v = inp.value.trim(); if (!v) return; w.remove(); fn(v); };
    inp.onkeydown = (e) => { if (e.key === 'Enter') ok.click(); };
    row.append(no, ok); c.appendChild(row); w.appendChild(c); document.body.appendChild(w); setTimeout(() => inp.focus(), 30);
  }
  function open(bot, anchor, hooks) {
    close(); hooks = hooks || {};
    const wrap = el('div'); wrap.id = 'bm-wrap';
    const menu = el('div', 'bm-menu'); wrap.appendChild(menu);
    wrap.addEventListener('click', (e) => { if (e.target === wrap) close(); });
    wrap.addEventListener('contextmenu', (e) => { e.preventDefault(); close(); });
    const done = () => { close(); };
    function main() {
      menu.textContent = ''; menu.dataset.view = 'main';
      const unread = home.unread.includes(bot.id), pinned = home.pinned.includes(bot.id);
      menu.append(
        item(IC.unread, unread ? 'Mark Read' : 'Mark Unread', () => { done(); op('unread', { id: bot.id, on: !unread }); }),
        item(IC.pin, pinned ? 'Unpin' : 'Pin', () => { done(); op('pin', { id: bot.id, on: !pinned }).then(() => toast(pinned ? 'Unpinned' : 'Pinned to top')); }),
        item(IC.folder, 'Move to', move, { sub: true }),
        item(IC.share, 'Share as Template', () => { done(); share(bot); }),
        item(IC.hide, 'Hide', () => { done(); op('hide', { id: bot.id, on: true }).then(() => toast(bot.name + ' hidden - unhide it from Hidden bots')); }, { red: true }),
        item(IC.more, 'More', more, { sub: true }));
    }
    function more() {
      menu.textContent = ''; menu.dataset.view = 'more';
      menu.append(header('More', main),
        item(IC.copy, 'Copy ID', () => { done(); copyId(bot); }),
        item(IC.dup, 'Duplicate', async () => {
          done(); const r = await post('/api/bots/duplicate', { id: bot.id });
          if (r.ok) { toast('Made ' + r.bot.name); await load(); changed(); if (hooks.reload) hooks.reload(); } else toast(r.error || 'Could not duplicate');
        }),
        item(IC.trash, 'Delete', () => {
          done(); confirmBox('Delete ' + bot.name + '?', 'Its chat, memory notes and lessons are removed. This cannot be undone.', 'Delete', async () => {
            const r = await post('/api/bots/delete', { id: bot.id, confirm: true });
            if (r.ok) { toast(bot.name + ' deleted'); await load(); changed(); if (hooks.reload) hooks.reload(); } else toast(r.error || 'Could not delete');
          });
        }, { red: true }));
    }
    function move() {
      menu.textContent = ''; menu.dataset.view = 'move';
      const cur = sectionOf(bot.id);
      menu.appendChild(header('Move to', main));
      home.sections.forEach((s) => menu.appendChild(item(IC.folder, s.name, () => { done(); op('move', { id: bot.id, section: s.id }).then(() => toast('Moved to ' + s.name)); }, { check: cur === s.id })));
      menu.appendChild(item(IC.folder, 'Unassigned', () => { done(); op('move', { id: bot.id, section: '' }); }, { check: !cur }));
      menu.appendChild(item(IC.folderPlus, 'New section', () => { done(); promptBox('New section', 'New section ' + home.sections.length, (name) => op('move', { id: bot.id, new_section: name }).then(() => toast('Moved to ' + name))); }));
    }
    main();
    document.body.appendChild(wrap);
    // anchor under the row (above it if no room), kept inside the screen
    const r = anchor && anchor.getBoundingClientRect ? anchor.getBoundingClientRect() : anchor;
    const mw = Math.min(300, window.innerWidth - 24); menu.style.width = mw + 'px';
    const x = r ? Math.max(12, Math.min((r.x != null && r.point ? r.x : r.left + 4), window.innerWidth - mw - 12)) : 12;
    const h = 6 * 51 + 12; let y = r ? (r.point ? r.y : r.bottom + 4) : 80;
    if (y + h > window.innerHeight - 8) y = Math.max(8, (r && !r.point ? r.top : y) - h - 4);
    menu.style.left = x + 'px'; menu.style.top = y + 'px';
    return { main, more, move, menu };
  }
  // long-press (450ms, haptic) + right-click on a row; swallows the click after a long-press
  function bind(row, getBot, hooks) {
    let t = 0, sx = 0, sy = 0, fired = false;
    const start = (x, y) => { fired = false; sx = x; sy = y; clearTimeout(t); row.classList.add('bm-press');
      t = setTimeout(() => { fired = true; row.classList.remove('bm-press');
        try { if (window.PedroNative && window.PedroNative.haptic) window.PedroNative.haptic(); else if (navigator.vibrate) navigator.vibrate(18); } catch (e) {}
        open(getBot(), row, hooks); }, 450); };
    const cancel = () => { clearTimeout(t); row.classList.remove('bm-press'); };
    row.addEventListener('touchstart', (e) => { const p = e.touches[0]; start(p.clientX, p.clientY); }, { passive: true });
    row.addEventListener('touchmove', (e) => { const p = e.touches[0]; if (Math.abs(p.clientX - sx) > 10 || Math.abs(p.clientY - sy) > 10) cancel(); }, { passive: true });
    row.addEventListener('touchend', (e) => { cancel(); if (fired) e.preventDefault(); });
    row.addEventListener('touchcancel', cancel);
    row.addEventListener('mousedown', (e) => { if (e.button === 0 && !('ontouchstart' in window)) start(e.clientX, e.clientY); });
    row.addEventListener('mouseup', cancel); row.addEventListener('mouseleave', cancel);
    row.addEventListener('contextmenu', (e) => { e.preventDefault(); cancel(); fired = true;
      open(getBot(), e.pointerType === 'touch' || e.button !== 2 ? row : { point: true, x: e.clientX, y: e.clientY }, hooks); });
    row.addEventListener('click', (e) => { if (fired) { e.stopImmediatePropagation(); e.preventDefault(); fired = false; } }, true);
  }
  // visible bots in display order: pinned first, then by last message; hidden removed
  function arrange(bots, lastOf) {
    const vis = bots.filter((b) => !home.hidden.includes(b.id));
    const pin = (b) => { const i = home.pinned.indexOf(b.id); return i < 0 ? 1e9 : i; };
    return vis.sort((a, b) => (pin(a) - pin(b)) || (Number(lastOf(b) || 0) - Number(lastOf(a) || 0)));
  }
  function openedBot(id) { if (home.unread.includes(id)) op('unread', { id, on: false }); }
  function hiddenSheet(bots, reload) {
    const w = el('div', 'bm-dim'); w.id = 'bm-hidden'; const c = el('div', 'bm-dialog bm-list'); c.appendChild(el('h3', '', 'Hidden bots'));
    const draw = () => {
      c.querySelectorAll('.bm-item,.bm-none').forEach((n) => n.remove());
      const hid = bots.filter((b) => home.hidden.includes(b.id));
      if (!hid.length) c.appendChild(el('p', 'bm-none', 'No hidden bots.'));
      hid.forEach((b) => c.appendChild(item(IC.eye, 'Unhide ' + b.name, () => op('hide', { id: b.id, on: false }).then(() => { draw(); if (reload) reload(); }))));
    };
    draw(); const row = el('div', 'bm-actions'); const ok = el('button', 'bm-btn', 'Done'); ok.type = 'button'; ok.onclick = () => w.remove();
    row.appendChild(ok); c.appendChild(row); w.appendChild(c); w.onclick = (e) => { if (e.target === w) w.remove(); }; document.body.appendChild(w);
  }
  window.pbBotMenu = { open, close, bind, load, op, arrange, openedBot, hiddenSheet, onChange: (f) => listeners.push(f),
                       get home() { return home; }, IC, confirmBox, promptBox };
})();
