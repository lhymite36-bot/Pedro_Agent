// 1.6.6 PC layout (>=521px), Grok desktop style: 250px bot sidebar with sections (drag bots in),
// floating bot pill, bubble chat, pill composer, and one avatar menu holding every old menu item.
(function () {
  const $ = (s) => document.querySelector(s);
  const mq = window.matchMedia('(min-width: 521px)');
  const KEY = 'pd.sections';
  const P = (d, w) => '<svg viewBox="0 0 24 24" width="' + (w || 18) + '" height="' + (w || 18) + '" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' + d + '</svg>';
  const IC = { search: P('<circle cx="11" cy="11" r="7"/><path d="M16.5 16.5L21 21"/>'), plus: P('<path d="M12 5v14M5 12h14"/>'), chev: P('<path d="M6 9l6 6 6-6"/>', 14) };
  let bots = [], sessions = [], built = false, dragId = '';
  function el(t, c, x) { const e = document.createElement(t); if (c) e.className = c; if (x != null) e.textContent = x; return e; }
  function click(id) { const e = document.getElementById(id); if (e) e.click(); }
  function nav(name) { const b = document.querySelector('#bottomnav [data-nav="' + name + '"]'); if (b) b.click(); }
  function sections() { try { const s = JSON.parse(localStorage.getItem(KEY) || 'null'); if (s && Array.isArray(s.list)) return s; } catch (e) {} return { list: [{ name: 'New section', ids: [] }] }; }
  function saveSections(s) { try { localStorage.setItem(KEY, JSON.stringify(s)); } catch (e) {} }
  function look(b) { return b ? { color: b.color || '#1683f5', shape: b.avatar || 'round' } : { color: '#f2f2f2', shape: 'pedbot' }; }
  function face(box, l) { if (window.createAvatar) { try { window.createAvatar(box, l); } catch (e) {} } }
  function initials() {
    let n = '';
    try { const t = window.PedroAuth && window.PedroAuth.user && window.PedroAuth.user(); const u = t && (t.user || t); n = (u && ((u.user_metadata && (u.user_metadata.full_name || u.user_metadata.name)) || u.email)) || ''; } catch (e) {}
    n = String(n || 'Pedro').split('@')[0].replace(/[._-]+/g, ' ').trim(); const p = n.split(/\s+/);
    return ((p[0] || 'P')[0] + (p[1] ? p[1][0] : (p[0] || '').slice(1, 2))).toUpperCase();
  }
  function curSession() { return (typeof session === 'string') ? session : (localStorage.session || ''); }
  function openBot(id) {
    const go = (s) => window.openSession && window.openSession(s).then(() => { if (window.applyBotHeader) window.applyBotHeader(); mark(); });
    if (id) go('bot-' + id);
    else { const s = sessions.find((r) => !/^(bot-|group-)/.test(String(r.session))); if (s) go(s.session); else { click('new'); setTimeout(mark, 300); } }
  }
  function build() {
    if (built) return; built = true;
    const side = el('aside'); side.id = 'pd-side';
    const top = el('div', 'pd-top');
    const sb = el('button', 'pd-r'); sb.type = 'button'; sb.title = 'Search'; sb.innerHTML = IC.search; sb.onclick = () => click('btn-search');
    const nb = el('button', 'pd-r'); nb.type = 'button'; nb.title = 'New bot'; nb.innerHTML = IC.plus; nb.onclick = () => { if (window.showNewBot) window.showNewBot(); else click('newbot'); };
    top.append(sb, nb);
    const tile = el('button', 'pd-tile'); tile.type = 'button'; tile.id = 'pd-main';
    const tf = el('div', 'pd-tile-face'); tile.append(tf, el('span', '', 'Ped Bot')); tile.onclick = () => openBot('');
    const list = el('div'); list.id = 'pd-list';
    const foot = el('div', 'pd-foot');
    const me = el('button', 'pd-me'); me.type = 'button'; me.id = 'pd-me'; me.title = 'Menu'; me.textContent = initials();
    me.onclick = (e) => { e.stopPropagation(); toggleMenu(); };
    const ca = el('button', 'pd-connect'); ca.type = 'button';
    ca.innerHTML = '<span>Connect apps</span><i class="pd-apps"><b style="background:#ea4335"></b><b style="background:#34a853"></b><b style="background:#4285f4"></b></i>';
    ca.onclick = () => click('btn-connect');
    foot.append(me, ca);
    side.append(top, tile, list, foot);
    document.body.appendChild(side);
    face(tf, look(null));
    // avatar menu: everything that used to be in the top bar and the drawer
    const m = el('div'); m.id = 'pd-menu';
    const items = [
      ['Model', () => click('hdr-model'), 'pd-model'], ['New chat', () => click('new')], ['Chat history', () => history()], ['Memory', () => memory()],
      ['Avatar', () => click('avc-open')], ['Pause all', () => click('pause-all'), 'pd-pause'], null,
      ['Live PC', () => click('livebtn')], ['Projects', () => click('acct-projects')], ['Tasks', () => nav('tasks')], ['Routines', () => nav('routines')],
      ['Connectors', () => nav('connectors')], ['Settings', () => click('setbtn')], ['Usage', () => click('acct-usage')], ['Updates', () => click('acct-updates')],
      ['Help', () => click('acct-help')], ['Users', () => click('acct-admin'), 'pd-users'], null, ['Log out', () => click('acct-logout'), 'pd-logout']
    ];
    items.forEach((it) => {
      if (!it) { m.appendChild(el('hr')); return; }
      const b = el('button', '', it[0]); b.type = 'button'; if (it[2]) b.id = it[2];
      b.onclick = (e) => { e.stopPropagation(); m.classList.remove('open'); it[1](); }; m.appendChild(b);
    });
    document.body.appendChild(m);
    document.addEventListener('click', (e) => { if (!m.contains(e.target)) m.classList.remove('open'); });
    // header: floating pill only
    const t = $('#t'); if (t) { const fix = () => { if (document.body.classList.contains('pd')) { /* keeps 'Message <Bot>…' */ } }; fix(); }
    load();
    setInterval(() => { if (!document.hidden && document.body.classList.contains('pd')) load(); }, 20000);
  }
  function toggleMenu() {
    const m = $('#pd-menu'); m.classList.toggle('open');
    const hm = $('#hdr-model'), pm = $('#pd-model'); if (hm && pm) pm.textContent = 'Model: ' + (hm.textContent || 'auto');
    const pa = $('#pause-all'), pp = $('#pd-pause'); if (pa && pp) pp.textContent = pa.classList.contains('on') ? 'Resume everything' : 'Pause all';
    const ad = $('#acct-admin'), pu = $('#pd-users'); if (ad && pu) pu.hidden = ad.hidden;
  }
  async function load() {
    try { const r = await (await fetch('/api/bots')).json(); bots = (r && r.bots) || []; } catch (e) {}
    try { const s = await (await fetch('/api/sessions')).json(); sessions = Array.isArray(s) ? s : []; } catch (e) {}
    if (window.pbBotMenu) { await window.pbBotMenu.load(); await migrate(); }
    draw();
  }
  const BMH = () => (window.pbBotMenu ? window.pbBotMenu.home : { sections: [], pinned: [], hidden: [], unread: [] });
  function row(b, by) {
    const H = BMH(), BM = window.pbBotMenu, unread = H.unread.includes(b.id);
    const r = el('div', 'pd-row' + (unread ? ' is-unread' : '')); r.draggable = true; r.dataset.id = b.id; r.tabIndex = 0;
    const f = el('div', 'pd-face'); const m = el('div', 'pd-main');
    const s = by['bot-' + b.id] || {};
    const nm = el('b', '', b.name); if (BM && H.pinned.includes(b.id)) nm.insertAdjacentHTML('beforeend', '<span class="bm-pinmark">' + BM.IC.pin + '</span>');
    m.append(nm, el('small', '', String(s.preview || b.role || '').replace(/\s+/g, ' ')));
    r.append(f, m); if (unread) r.appendChild(el('span', 'bm-dot')); face(f, look(b));
    r.onclick = () => { if (BM) BM.openedBot(b.id); openBot(b.id); };
    if (BM) BM.bind(r, () => b, { reload: load });
    r.addEventListener('dragstart', (e) => { dragId = b.id; r.classList.add('drag'); try { e.dataTransfer.setData('text/plain', b.id); e.dataTransfer.effectAllowed = 'move'; } catch (x) {} });
    r.addEventListener('dragend', () => { dragId = ''; r.classList.remove('drag'); });
    return r;
  }
  function dropZone(box, sid) {
    box.addEventListener('dragover', (e) => { e.preventDefault(); box.classList.add('over'); });
    box.addEventListener('dragleave', () => box.classList.remove('over'));
    box.addEventListener('drop', (e) => {
      e.preventDefault(); box.classList.remove('over');
      const id = dragId || (e.dataTransfer && e.dataTransfer.getData('text/plain')); if (!id || !window.pbBotMenu) return;
      window.pbBotMenu.op('move', { id, section: sid });
    });
  }
  async function migrate() {   // 1.6.8: sections used to live in this browser only; move them to the PC once
    const BM = window.pbBotMenu; if (!BM || localStorage.getItem(KEY + '.moved')) return;
    const old = sections(); localStorage.setItem(KEY + '.moved', '1');
    if (BM.home.sections.length) return;
    for (const sec of old.list) {
      if (sec.ids.length) { for (const id of sec.ids) await BM.op('move', { id, new_section: sec.name }); }
      else await BM.op('add_section', { name: sec.name });
    }
  }
  function draw() {
    const list = $('#pd-list'); if (!list) return; list.textContent = '';
    const by = {}; sessions.forEach((s) => { by[s.session] = s; });
    const H = BMH(), BM = window.pbBotMenu;
    const vis = BM ? BM.arrange(bots.slice(), (b) => (by['bot-' + b.id] || {}).last) : bots.slice();
    const placed = new Set();
    H.sections.forEach((sec) => {
      const box = el('div', 'pd-sec');
      const h = el('div', 'pd-sec-h' + (sec.collapsed ? ' closed' : '')); h.append(el('span', '', sec.name));
      const ids = vis.filter((b) => sec.ids.includes(b.id)); ids.forEach((b) => placed.add(b.id));
      h.appendChild(el('small', 'pd-count', String(ids.length))); h.insertAdjacentHTML('beforeend', IC.chev);
      h.onclick = () => BM.op('collapse', { section: sec.id, on: !sec.collapsed }); box.appendChild(h);
      if (!sec.collapsed) { if (!ids.length) box.appendChild(el('div', 'pd-drop', 'Drag Bots here')); ids.forEach((b) => box.appendChild(row(b, by))); }
      dropZone(box, sec.id); list.appendChild(box);
    });
    const un = el('div', 'pd-sec');
    const h = el('div', 'pd-sec-h'); h.append(el('span', '', 'Unassigned')); h.insertAdjacentHTML('beforeend', IC.chev); un.appendChild(h);
    const rest = vis.filter((b) => !placed.has(b.id));
    if (!bots.length) { const c = el('button', 'pd-create', 'Create a bot'); c.type = 'button'; c.onclick = () => { if (window.showNewBot) window.showNewBot(); else click('newbot'); }; un.appendChild(c); }
    rest.forEach((b) => un.appendChild(row(b, by)));
    dropZone(un, ''); list.appendChild(un);
    const hid = H.hidden.filter((id) => bots.some((b) => b.id === id)).length;
    if (hid && BM) { const l = el('button', 'bm-hidden-link', 'Hidden bots (' + hid + ')'); l.type = 'button'; l.onclick = () => BM.hiddenSheet(bots, load); list.appendChild(l); }
    mark();
  }
  function mark() {
    const cur = curSession();
    document.querySelectorAll('#pd-side .pd-row').forEach((r) => r.classList.toggle('active', cur === 'bot-' + r.dataset.id));
    const main = $('#pd-main'); if (main) main.classList.toggle('active', !/^bot-|^group-/.test(cur));
  }
  // History + Memory reuse the phone sheets when present; otherwise simple fallbacks.
  function history() { if (window.pbHistorySheet) window.pbHistorySheet(); }
  function memory() { if (window.pbMemorySheet) window.pbMemorySheet(); }
  function apply() {
    document.body.classList.toggle('pd', mq.matches);
    if (mq.matches) build();
  }
  if (mq.addEventListener) mq.addEventListener('change', apply);
  const start = () => setTimeout(apply, 0);
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();
  if (window.pbBotMenu) window.pbBotMenu.onChange(() => { if (document.body.classList.contains('pd')) draw(); });
  window.addEventListener('focus', () => { if (document.body.classList.contains('pd')) mark(); });
})();
