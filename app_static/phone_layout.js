// 1.6.5 spacious phone layout (<=520px): minimal top bar, '...' menu, grid button + pill input,
// recent chats on the home screen. The PC layout is untouched (everything is gated by body.pl).
(function () {
  const $ = (s) => document.querySelector(s);
  const mq = window.matchMedia('all');
  const ICON = {
    more: '<svg viewBox="0 0 24 24" fill="currentColor"><circle cx="5" cy="12" r="2"/><circle cx="12" cy="12" r="2"/><circle cx="19" cy="12" r="2"/></svg>',
    plus: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M12 5v14M5 12h14"/></svg>',
    grid: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="4" y="4" width="6" height="6" rx="1.5"/><rect x="14" y="4" width="6" height="6" rx="1.5"/><rect x="4" y="14" width="6" height="6" rx="1.5"/><rect x="14" y="14" width="6" height="6" rx="1.5"/></svg>'
  };
  function btn(id, html, title) { const b = document.createElement('button'); b.type = 'button'; b.id = id; b.className = 'pl-round'; b.innerHTML = html; b.title = title; b.setAttribute('aria-label', title); return b; }
  function click(sel) { const el = $(sel); if (el) el.click(); }
  function closeAll() { document.body.classList.remove('pl-menu-open', 'pl-grid-open'); }

  function build() {
    const header = $('header'); if (!header || $('#pl-more')) return;
    const right = document.createElement('div'); right.id = 'pl-right';
    const plus = btn('pl-new', ICON.plus, 'New chat');
    const more = btn('pl-more', ICON.more, 'More');
    plus.onclick = () => { closeAll(); click('#new'); };
    more.onclick = (e) => { e.stopPropagation(); document.body.classList.toggle('pl-menu-open'); document.body.classList.remove('pl-grid-open'); syncMenu(); };
    right.append(plus, more); header.appendChild(right);
    const dot = document.createElement('span'); dot.id = 'pl-dot'; dot.title = 'Status';
    const pill = $('#btn-bot-info'); if (pill) pill.appendChild(dot);

    const menu = document.createElement('div'); menu.id = 'pl-menu'; menu.setAttribute('role', 'menu');
    menu.innerHTML = '<div id="pl-status"></div>' +
      '<button type="button" data-do="new">New chat</button>' +
      '<button type="button" data-do="avatar">Talk face to face (Avatar)</button>' +
      '<button type="button" data-do="search">Search</button>' +
      '<button type="button" data-do="model" id="pl-model">Model</button>' +
      '<button type="button" data-do="pause" class="danger" id="pl-pause">Pause all</button>';
    menu.onclick = (e) => {
      const d = e.target.closest('button'); if (!d) return; closeAll();
      ({ new: () => click('#new'), avatar: () => click('#avc-open'), search: () => click('#btn-search'), model: () => click('#hdr-model'), pause: () => click('#pause-all') })[d.dataset.do]();
    };
    document.body.appendChild(menu);
    const scrim = document.createElement('div'); scrim.id = 'pl-scrim'; scrim.onclick = closeAll; document.body.appendChild(scrim);

    const box = $('#composer .box');
    if (box) { const g = btn('pl-grid', ICON.grid, 'Apps'); g.onclick = (e) => { e.stopPropagation(); document.body.classList.toggle('pl-grid-open'); document.body.classList.remove('pl-menu-open'); }; box.parentNode.insertBefore(g, box); }
    const nav = $('#bottomnav'); if (nav) nav.addEventListener('click', () => setTimeout(closeAll, 0));

    const empty = $('#empty');
    if (empty && !$('#pl-name')) {
      const name = document.createElement('div'); name.id = 'pl-name'; name.textContent = 'Ped Bot';
      const av = $('#empty-avatar'); if (av) av.after(name);
      const rec = document.createElement('div'); rec.id = 'pl-recent'; empty.appendChild(rec);
    }
    const t = $('#t');
    if (t) {
      const ask = () => { if (document.body.classList.contains('pl') && /^Message /.test(t.placeholder)) t.placeholder = t.placeholder.replace(/^Message /, 'Ask '); };
      ask(); new MutationObserver(ask).observe(t, { attributes: true, attributeFilter: ['placeholder'] });
    }
    watch();
  }
  function ago(ts) {
    const s = Math.max(0, Date.now() / 1000 - Number(ts || 0));
    if (s < 60) return 'now'; if (s < 3600) return Math.floor(s / 60) + 'm'; if (s < 86400) return Math.floor(s / 3600) + 'h';
    return Math.floor(s / 86400) + 'd';
  }
  async function recent() {
    const rec = $('#pl-recent'); if (!rec || !document.body.classList.contains('pl')) return;
    try {
      const rows = await (await fetch('/api/sessions')).json();
      const list = (Array.isArray(rows) ? rows : []).filter((s) => !String(s.session).startsWith('group-')).slice(0, 8);
      rec.textContent = '';
      if (!list.length) return;
      const h = document.createElement('div'); h.className = 'pl-rec-h'; h.textContent = 'Recent'; rec.appendChild(h);
      list.forEach((s) => {
        const r = document.createElement('button'); r.type = 'button'; r.className = 'pl-rec';
        const a = document.createElement('span'); a.className = 'pl-rec-av'; a.textContent = String(s.title || s.session || '?').trim().charAt(0).toUpperCase();
        const m = document.createElement('span'); m.className = 'pl-rec-main';
        const n = document.createElement('b'); n.textContent = String(s.title || s.session).replace(/\s+/g, ' ').slice(0, 60);
        const p = document.createElement('small'); p.textContent = String(s.preview || '').replace(/\s+/g, ' ').slice(0, 90);
        m.append(n, p);
        const tm = document.createElement('time'); tm.textContent = ago(s.last);
        r.append(a, m, tm); r.onclick = () => { if (window.openSession) window.openSession(s.session); };
        rec.appendChild(r);
      });
    } catch (e) {}
  }
  function syncMenu() {
    const st = $('#pl-status');
    const banner = $('#pb-banner');
    const mood = $('#mood');
    if (st) st.textContent = banner ? banner.textContent.replace('⚙', '').trim() : ('PC: ' + (mood ? mood.textContent : 'online'));
    const hm = $('#hdr-model'), pm = $('#pl-model'); if (hm && pm) pm.textContent = 'Model: ' + (hm.textContent || 'auto');
    const pa = $('#pause-all'), pp = $('#pl-pause');
    if (pa && pp) pp.textContent = pa.classList.contains('on') ? 'Resume everything' : 'Pause all';
  }
  function watch() {
    const log = $('#log');
    const upd = () => {
      const chat = !!(log && log.children.length);
      document.body.classList.toggle('pl-chat', chat);
      const banner = $('#pb-banner');
      document.body.classList.toggle('pl-offline', !!banner && /offline/i.test(banner.textContent));
      if (banner && !banner.dataset.pl) { banner.dataset.pl = '1'; }
      const pa = $('#pause-all'); document.body.classList.toggle('pl-paused', !!(pa && pa.classList.contains('on')));
    };
    if (log) new MutationObserver(upd).observe(log, { childList: true });
    new MutationObserver(upd).observe(document.body, { childList: true });
    const pa = $('#pause-all'); if (pa) new MutationObserver(upd).observe(pa, { attributes: true });
    upd();
    const dot = $('#pl-dot'); if (dot) dot.onclick = (e) => { e.stopPropagation(); const b = $('#pb-banner'); if (b) b.click(); else { document.body.classList.add('pl-menu-open'); syncMenu(); } };
  }
  function apply() {
    document.body.classList.toggle('pl', mq.matches);
    if (mq.matches) { build(); recent(); } else closeAll();
  }
  if (mq.addEventListener) mq.addEventListener('change', apply);
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeAll(); });
  window.addEventListener('popstate', closeAll);
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', apply); else apply();
  setInterval(() => { if (document.body.classList.contains('pl') && !document.body.classList.contains('pl-chat') && !document.hidden) recent(); }, 30000);
})();

// 1.6.6 phone home: the first screen lists the bots (Grok-style). The slide-out chat drawer
// is gone on phone; top-left is the initials avatar (settings), '...' has History.
(function () {
  const $ = (s) => document.querySelector(s);
  const mq = window.matchMedia('all');
  const SEARCH = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="7"/><path d="M16.5 16.5L21 21"/></svg>';
  const BACK = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M15 5l-7 7 7 7"/></svg>';
  const CHEV = '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><path d="M6 9l6 6 6-6"/></svg>';
  const GRID = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="4" y="4" width="6" height="6" rx="1.5"/><rect x="14" y="4" width="6" height="6" rx="1.5"/><rect x="4" y="14" width="6" height="6" rx="1.5"/><path d="M17 14v6M14 17h6"/></svg>';
  let bots = [], sessions = [], query = '', collapsed = false, built = false;
  function el(tag, cls, text) { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; }
  function when(ts) {
    const d = new Date(Number(ts || 0) * 1000); if (!ts) return '';
    const now = new Date(); const days = Math.floor((new Date(now.toDateString()) - new Date(d.toDateString())) / 86400000);
    if (days <= 0) return d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
    if (days === 1) return 'Yesterday';
    if (days < 7) return d.toLocaleDateString([], { weekday: 'long' });
    return d.toLocaleDateString([], { month: 'short', day: 'numeric' });
  }
  function initials() {
    let name = '';
    try { const t = window.PedroAuth && window.PedroAuth.user && window.PedroAuth.user(); const u = t && (t.user || t); name = (u && ((u.user_metadata && (u.user_metadata.full_name || u.user_metadata.name)) || u.email)) || ''; } catch (e) {}
    if (!name) { const w = $('#who'); name = w ? w.textContent : ''; }
    name = String(name || 'Pedro').split('@')[0].replace(/[._-]+/g, ' ').trim();
    const parts = name.split(/\s+/).filter(Boolean);
    return ((parts[0] || 'P')[0] + (parts[1] ? parts[1][0] : (parts[0] || '').slice(1, 2))).toUpperCase();
  }
  function face(box, look) { box.textContent = ''; if (window.createAvatar) { try { window.createAvatar(box, look); return; } catch (e) {} } box.textContent = '•'; }
  function look(b) { return b ? { color: b.color || '#1683f5', shape: b.avatar || 'round' } : { color: '#f2f2f2', shape: 'pedbot' }; }
  function openChat(id) {
    hide();
    try { history.pushState({ plchat: 1 }, ''); } catch (e) {}
    if (id) { if (window.openSession) window.openSession('bot-' + id).then(() => { if (window.applyBotHeader) window.applyBotHeader(); }); }
    else { const s = sessions.find((r) => !/^(bot-|group-)/.test(String(r.session))); if (s && window.openSession) window.openSession(s.session).then(() => { if (window.applyBotHeader) window.applyBotHeader(); }); else { const n = $('#new'); if (n) n.click(); } }
  }
  function show() { document.body.classList.add('pl-home-on'); load(); }
  function hide() { document.body.classList.remove('pl-home-on', 'pl-grid-open', 'pl-menu-open'); }
  function build() {
    if (built) return; built = true;
    const h = el('section'); h.id = 'pl-home';
    const top = el('div', 'plh-top');
    const me = el('button', 'pl-round plh-me'); me.type = 'button'; me.title = 'Profile and settings'; me.id = 'plh-me';
    me.onclick = () => { hide(); const s = $('#setbtn'); if (s) s.click(); };
    const add = el('button', 'pl-round'); add.type = 'button'; add.title = 'New bot'; add.id = 'plh-add';
    add.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M12 5v14M5 12h14"/></svg>';
    add.onclick = newBot;
    top.append(me, add);
    const hero = el('button', 'plh-hero'); hero.type = 'button'; hero.title = 'Open Ped Bot';
    const hf = el('div', 'plh-hero-face'); const star = el('span', 'plh-star', '★');
    const hn = el('div', 'plh-hero-name', 'Ped Bot'); hero.append(hf, star, hn); hero.onclick = () => openChat('');
    const list = el('div'); list.id = 'plh-list';
    const bottom = el('div', 'plh-bottom');
    const g = el('button', 'pl-round'); g.type = 'button'; g.title = 'Apps'; g.innerHTML = GRID; g.id = 'plh-grid';
    g.onclick = (e) => { e.stopPropagation(); document.body.classList.toggle('pl-grid-open'); };
    const sb = el('label', 'plh-search'); sb.innerHTML = SEARCH; const inp = el('input'); inp.id = 'plh-q'; inp.placeholder = 'Search'; inp.autocomplete = 'off';
    inp.oninput = () => { query = inp.value.trim().toLowerCase(); draw(); }; sb.appendChild(inp);
    bottom.append(g, sb);
    h.append(top, hero, list, bottom);
    document.body.appendChild(h);
    face(hf, look(null));
    // header: back button replaces the hamburger in a chat
    const header = $('header');
    if (header && !$('#pl-back')) {
      const back = el('button', 'pl-round'); back.type = 'button'; back.id = 'pl-back'; back.title = 'Back'; back.innerHTML = BACK;
      back.onclick = () => { show(); };
      header.insertBefore(back, header.firstChild);
    }
    const menu = $('#pl-menu');
    if (menu && !menu.querySelector('[data-do2="history"]')) {
      const hb = el('button', '', 'History'); hb.type = 'button'; hb.dataset.do2 = 'history';
      hb.onclick = (e) => { e.stopPropagation(); document.body.classList.remove('pl-menu-open'); historySheet(); };
      menu.insertBefore(hb, menu.children[2] || null);
    }
    const nav = $('#bottomnav'); if (nav) nav.addEventListener('click', () => hide(), true);
    window.addEventListener('popstate', () => { if (mq.matches && !document.body.classList.contains('pl-home-on')) show(); });
  }
  function newBot() { hide(); if (window.showNewBot) window.showNewBot(); else { const b = $('#newbot'); if (b) b.click(); } }
  async function load() {
    try { const r = await (await fetch('/api/bots')).json(); bots = (r && r.bots) || []; } catch (e) {}
    try { const s = await (await fetch('/api/sessions')).json(); sessions = Array.isArray(s) ? s : []; } catch (e) {}
    const me = $('#plh-me'); if (me) me.textContent = initials();
    draw();
  }
  function draw() {
    const list = $('#plh-list'); if (!list) return; list.textContent = '';
    const by = {}; sessions.forEach((s) => { by[s.session] = s; });
    if (!bots.length) {
      const e = el('div', 'plh-empty');
      e.append(el('b', '', 'No bots yet'), el('p', '', 'Make a bot for a job you do often - it gets its own face, chat and skills.'));
      const c = el('button', 'plh-create', 'Create a bot'); c.type = 'button'; c.onclick = newBot; e.appendChild(c);
      list.appendChild(e); return;
    }
    const rows = bots.map((b) => ({ b, s: by['bot-' + b.id] || {} }))
      .filter((r) => !query || (r.b.name + ' ' + (r.s.preview || '') + ' ' + (r.b.role || '')).toLowerCase().includes(query))
      .sort((a, b) => (Number(b.s.last || 0) - Number(a.s.last || 0)));
    const head = el('button', 'plh-sec' + (collapsed ? ' closed' : '')); head.type = 'button';
    head.append(el('span', '', 'Unassigned'), el('small', '', String(rows.length))); head.insertAdjacentHTML('beforeend', CHEV);
    head.onclick = () => { collapsed = !collapsed; draw(); };
    list.appendChild(head);
    if (collapsed) return;
    if (!rows.length) { list.appendChild(el('div', 'plh-none', 'No bots match "' + query + '"')); return; }
    rows.forEach(({ b, s }) => {
      const r = el('button', 'plh-row'); r.type = 'button';
      const f = el('div', 'plh-face'); const m = el('div', 'plh-main'); const top = el('div', 'plh-l1');
      top.append(el('b', '', b.name), el('time', '', when(s.last)));
      m.append(top, el('small', '', String(s.preview || b.role || 'Say hi to ' + b.name).replace(/\s+/g, ' ')));
      r.append(f, m); r.onclick = () => openChat(b.id); list.appendChild(r);
      face(f, look(b));
    });
  }
  async function historySheet() {
    let s = []; try { s = await (await fetch('/api/sessions')).json(); } catch (e) {}
    const cur = (typeof session === 'string') ? session : (localStorage.session || '');
    const isBot = /^bot-/.test(cur);
    const items = (Array.isArray(s) ? s : []).filter((r) => isBot ? r.session === cur : !/^(bot-|group-)/.test(String(r.session)));
    let sh = $('#plh-hist'); if (sh) sh.remove();
    sh = el('div'); sh.id = 'plh-hist';
    const card = el('div', 'plh-hist-card'); card.appendChild(el('h3', '', 'History'));
    if (!items.length) card.appendChild(el('p', 'plh-none', 'No earlier chats yet.'));
    items.slice(0, 40).forEach((r) => {
      const b = el('button', 'plh-row'); b.type = 'button'; const m = el('div', 'plh-main'); const t = el('div', 'plh-l1');
      t.append(el('b', '', String(r.title || r.session).replace(/\s+/g, ' ').slice(0, 70)), el('time', '', when(r.last)));
      m.append(t, el('small', '', String(r.preview || '').replace(/\s+/g, ' '))); b.appendChild(m);
      b.onclick = () => { sh.remove(); if (window.openSession) window.openSession(r.session); };
      card.appendChild(b);
    });
    sh.onclick = (e) => { if (e.target === sh) sh.remove(); };
    sh.appendChild(card); document.body.appendChild(sh);
  }
  function apply() {
    document.body.classList.toggle('pl-nodrawer', mq.matches);
    if (!mq.matches) { document.body.classList.remove('pl-home-on'); return; }
    build(); document.body.classList.remove('side-open');
    if (!apply.once) { apply.once = true; show(); }   // first screen = the bots home
  }
  if (mq.addEventListener) mq.addEventListener('change', apply);
  const start = () => setTimeout(apply, 0);
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();
  setInterval(() => { if (document.body.classList.contains('pl-home-on') && !document.hidden) load(); }, 30000);
  window.pbShowHome = show;
})();

// 1.6.6: every drawer menu item lives in the apps grid on phone.
(function () {
  const $ = (s) => document.querySelector(s);
  const P = (d) => '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' + d + '</svg>';
  const EXTRA = [
    ['avcbtn', 'Avatar', P('<circle cx="12" cy="9" r="4"/><path d="M4 21c1.5-4 4.5-6 8-6s6.5 2 8 6"/>')],
    ['acct-projects', 'Projects', P('<path d="M3 7h6l2 2h10v10H3z"/>')],
    ['btn-connect', 'Connect apps', P('<path d="M9 15l6-6M10 6l1-1a4 4 0 0 1 6 6l-1 1M14 18l-1 1a4 4 0 0 1-6-6l1-1"/>')],
    ['acct-usage', 'Usage', P('<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>')],
    ['acct-updates', 'Updates', P('<path d="M12 4v11M7 10l5 5 5-5M5 20h14"/>')],
    ['acct-help', 'Help', P('<circle cx="12" cy="12" r="9"/><path d="M9.5 9a2.5 2.5 0 1 1 3.5 2.3c-.6.3-1 .9-1 1.7M12 17h.01"/>')],
    ['acct-admin', 'Users', P('<circle cx="9" cy="8" r="3.5"/><path d="M2 20c1-3.5 3.8-5 7-5s6 1.5 7 5M16 4.5a3.5 3.5 0 0 1 0 7M18 15c2 .6 3.4 2.2 4 5"/>')],
    ['acct-logout', 'Log out', P('<path d="M15 4h4v16h-4M10 8l-4 4 4 4M6 12h11"/>')]
  ];
  function add() {
    const nav = $('#bottomnav'); if (!nav || nav.querySelector('.pl-extra')) return;
    const settings = nav.querySelector('[data-nav="settings"]');
    EXTRA.forEach(([id, label, icon]) => {
      const src = document.getElementById(id); if (!src) return;
      const b = document.createElement('button'); b.type = 'button'; b.className = 'pl-extra'; b.dataset.target = id;
      b.innerHTML = icon; b.appendChild(document.createTextNode(label));
      b.onclick = (e) => { e.stopPropagation(); document.body.classList.remove('pl-grid-open', 'pl-home-on'); src.click(); };
      if (id === 'acct-admin') { const sync = () => { b.hidden = src.hidden; }; sync(); new MutationObserver(sync).observe(src, { attributes: true }); }
      nav.insertBefore(b, settings ? settings.nextSibling : null);
      if (settings) settings.after(b);
    });
    // keep order: Settings first then extras in list order
    let after = settings; EXTRA.forEach(([id]) => { const b = nav.querySelector('.pl-extra[data-target="' + id + '"]'); if (b && after) { after.after(b); after = b; } });
  }
  const go = () => setTimeout(add, 400);
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', go); else go();
})();

// 1.6.6: '...' > Memory - what this bot remembers (survives clearing chats); view, add, delete.
(function () {
  const $ = (s) => document.querySelector(s);
  function el(t, c, x) { const e = document.createElement(t); if (c) e.className = c; if (x != null) e.textContent = x; return e; }
  const post = (u, b) => fetch(u, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b || {}) }).then((r) => r.json());
  async function sheet() {
    const cur = (typeof session === 'string') ? session : (localStorage.session || '');
    const botId = /^bot-/.test(cur) ? cur.slice(4) : '';
    let items = [], bot = null, err = '';
    try {
      if (botId) { const r = await (await fetch('/api/bots')).json(); bot = (r.bots || []).find((b) => b.id === botId) || null; items = (bot && bot.notes || []).map((n) => ({ id: n.id, text: n.text })); }
      else { const r = await (await fetch('/api/memory')).json(); if (!r.ok) throw 0; items = r.memories || []; }
    } catch (e) { err = 'Memory is kept on your PC. Open this when your PC is online.'; }
    let sh = $('#plh-hist'); if (sh) sh.remove();
    sh = el('div'); sh.id = 'plh-hist'; const card = el('div', 'plh-hist-card');
    card.appendChild(el('h3', '', (bot ? bot.name : 'Ped Bot') + ' remembers'));
    card.appendChild(el('p', 'plh-none', 'Things you teach it ("remember that…") are kept here, even after you clear or delete a chat.'));
    if (err) card.appendChild(el('p', 'plh-none', err));
    const list = el('div'); card.appendChild(list);
    function draw() {
      list.textContent = '';
      if (!items.length && !err) list.appendChild(el('p', 'plh-none', 'Nothing saved yet.'));
      items.forEach((m) => {
        const row = el('div', 'plm-row'); row.appendChild(el('span', '', m.text));
        const x = el('button', 'plm-del', 'Delete'); x.type = 'button';
        x.onclick = async () => {
          if (!confirm('Forget this?\n\n' + m.text)) return;
          if (bot) { bot.notes = (bot.notes || []).filter((n) => n.id !== m.id); await post('/api/bots', bot); }
          else await post('/api/memory/forget', { id: m.id });
          items = items.filter((i) => i !== m); draw();
        };
        row.appendChild(x); list.appendChild(row);
      });
    }
    draw();
    if (!err) {
      const f = el('form', 'plm-add'); const i = el('input'); i.placeholder = 'Add something to remember'; i.maxLength = 500;
      const b = el('button', '', 'Save'); b.type = 'submit'; f.append(i, b);
      f.onsubmit = async (e) => {
        e.preventDefault(); const t = i.value.trim(); if (!t) return;
        if (bot) { bot.notes = (bot.notes || []).concat([{ id: Math.random().toString(16).slice(2, 10), text: t, at: Date.now() / 1000 }]); const r = await post('/api/bots', bot); if (r.bot) bot = r.bot; items = (bot.notes || []).map((n) => ({ id: n.id, text: n.text })); }
        else { await post('/api/memory/add', { text: t }); const r = await (await fetch('/api/memory')).json(); items = r.memories || []; }
        i.value = ''; draw();
      };
      card.appendChild(f);
    }
    sh.onclick = (e) => { if (e.target === sh) sh.remove(); };
    sh.appendChild(card); document.body.appendChild(sh);
  }
  function add() {
    const menu = $('#pl-menu'); if (!menu) { setTimeout(add, 500); return; }
    if (menu.querySelector('[data-do2="memory"]')) return;
    const b = el('button', '', 'Memory'); b.type = 'button'; b.dataset.do2 = 'memory';
    b.onclick = (e) => { e.stopPropagation(); document.body.classList.remove('pl-menu-open'); sheet(); };
    const h = menu.querySelector('[data-do2="history"]'); if (h) h.after(b); else menu.appendChild(b);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', () => setTimeout(add, 600)); else setTimeout(add, 600);
})();
// 1.6.6: with no drawer, the grid's Chats and Bots go to the bots home.
document.addEventListener('click', (e) => {
  const b = e.target.closest && e.target.closest('#bottomnav [data-nav="chats"], #bottomnav [data-nav="bots"]');
  if (!b || !document.body.classList.contains('pl')) return;
  e.stopPropagation(); e.preventDefault();
  document.body.classList.remove('pl-grid-open', 'side-open');
  if (window.pbShowHome) window.pbShowHome();
}, true);
