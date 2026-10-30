// 1.6.5 spacious phone layout (<=520px): minimal top bar, '...' menu, grid button + pill input,
// recent chats on the home screen. The PC layout is untouched (everything is gated by body.pl).
(function () {
  const $ = (s) => document.querySelector(s);
  const mq = window.matchMedia('(max-width: 520px)');
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
      '<button type="button" data-do="pause" class="danger" id="pl-pause">Pause all</button>';
    menu.onclick = (e) => {
      const d = e.target.closest('button'); if (!d) return; closeAll();
      ({ new: () => click('#new'), avatar: () => click('#avc-open'), search: () => click('#btn-search'), pause: () => click('#pause-all') })[d.dataset.do]();
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
