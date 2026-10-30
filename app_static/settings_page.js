// 1.7.2: Settings pages in the Grok "Connect apps" style (PC + phone): round X top-left, bold
// title, a status pill top-right, filter chips, "Section >" headers, icon list rows with pill
// buttons, and a floating search bar. It only re-arranges and decorates the existing settings
// markup, so every switch, button and id keeps working.
(function () {
  'use strict';
  const $ = (s, r) => (r || document).querySelector(s);
  const $$ = (s, r) => Array.from((r || document).querySelectorAll(s));
  const P = 'fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"';
  const ICON = {
    phone: '<rect x="7" y="2" width="10" height="20" rx="2"/><path d="M11 18h2"/>',
    undo: '<path d="M9 14 4 9l5-5"/><path d="M4 9h11a5 5 0 0 1 0 10h-3"/>',
    bell: '<path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a2 2 0 0 0 3.4 0"/>',
    trash: '<path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6"/>',
    key: '<circle cx="7.5" cy="15.5" r="4.5"/><path d="m10.7 12.3 9.8-9.8M17 6l3 3M15 8l2 2"/>',
    mic: '<rect x="9" y="2" width="6" height="12" rx="3"/><path d="M5 10a7 7 0 0 0 14 0M12 19v3"/>',
    voice: '<path d="M2 10v3M6 6v11M10 3v18M14 8v7M18 5v13M22 10v3"/>',
    shield: '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>',
    brain: '<path d="M9.5 2A2.5 2.5 0 0 1 12 4.5v15a2.5 2.5 0 0 1-4.96.44 2.5 2.5 0 0 1-2.96-3.08 3 3 0 0 1-.34-5.58 2.5 2.5 0 0 1 1.32-4.24A2.5 2.5 0 0 1 9.5 2z"/><path d="M14.5 2A2.5 2.5 0 0 0 12 4.5v15a2.5 2.5 0 0 0 4.96.44 2.5 2.5 0 0 0 2.96-3.08 3 3 0 0 0 .34-5.58 2.5 2.5 0 0 0-1.32-4.24A2.5 2.5 0 0 0 14.5 2z"/>',
    plug: '<path d="M9 2v6M15 2v6M7 8h10v4a5 5 0 0 1-10 0zM12 17v5"/>',
    puzzle: '<path d="M19.4 14.9a2.5 2.5 0 1 0 0-3.8V7a1 1 0 0 0-1-1h-4.1a2.5 2.5 0 1 0-3.8 0H6.4a1 1 0 0 0-1 1v4a2.5 2.5 0 1 1 0 4v4a1 1 0 0 0 1 1h4a2.5 2.5 0 1 1 4 0h4a1 1 0 0 0 1-1z"/>',
    chat: '<path d="M21 11.5a8.4 8.4 0 0 1-12.3 7.4L3 21l2.1-5.7A8.4 8.4 0 1 1 21 11.5z"/>',
    film: '<rect x="2" y="3" width="20" height="18" rx="2"/><path d="M7 3v18M17 3v18M2 8h5M2 16h5M17 8h5M17 16h5"/>',
    feather: '<path d="M20.2 12.2 12 20.4H7v-5l8.2-8.2a4.2 4.2 0 0 1 6 6zM16 8 2 22"/>',
    window: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 9h18"/>',
    power: '<path d="M12 2v10M18.4 6.6a9 9 0 1 1-12.8 0"/>',
    download: '<path d="M12 3v12M7 10l5 5 5-5M5 21h14"/>',
    bug: '<rect x="8" y="6" width="8" height="14" rx="4"/><path d="M19 7l-3 2M5 7l3 2M19 19l-3-2M5 19l3-2M20 13h-4M4 13h4M10 4l1 2M14 4l-1 2"/>',
    palette: '<circle cx="13.5" cy="6.5" r="1"/><circle cx="17.5" cy="10.5" r="1"/><circle cx="8.5" cy="7.5" r="1"/><circle cx="6.5" cy="12.5" r="1"/><path d="M12 2a10 10 0 0 0 0 20 2 2 0 0 0 2-2 2 2 0 0 1 2-2h2a4 4 0 0 0 4-4A10 10 0 0 0 12 2z"/>',
    gear: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
    mail: '<rect x="2" y="4" width="20" height="16" rx="2"/><path d="m22 6-10 7L2 6"/>',
    drive: '<path d="M8 3h8l6 10-4 7H6l-4-7z"/><path d="M8 3l8 17M16 3 6 20M2 13h20"/>',
    youtube: '<rect x="2" y="5" width="20" height="14" rx="4"/><path d="m10 9 5 3-5 3z"/>',
    calendar: '<rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/>',
  };
  const svg = (k) => '<svg width="22" height="22" viewBox="0 0 24 24" ' + P + '>' + (ICON[k] || ICON.puzzle) + '</svg>';
  const RULES = [
    [/phone|android/i, 'phone'], [/undo/i, 'undo'], [/check-?in|notification/i, 'bell'], [/delete|wipe/i, 'trash'],
    [/key|token|password|provider|backup model/i, 'key'], [/wake|listen|mic/i, 'mic'], [/voice|speak|read aloud/i, 'voice'],
    [/rule|block|confirm|allow|safe/i, 'shield'], [/memory|brain|model/i, 'brain'], [/whatsapp|telegram|discord|chat/i, 'chat'],
    [/short|video|buffer/i, 'film'], [/lite/i, 'feather'], [/start with|keep working|tray/i, 'power'], [/update/i, 'download'],
    [/crash/i, 'bug'], [/theme|color/i, 'palette'], [/gmail|mail/i, 'mail'], [/drive/i, 'drive'], [/youtube/i, 'youtube'],
    [/calendar/i, 'calendar'], [/connection/i, 'plug'], [/window/i, 'window'],
  ];
  function iconFor(t) { for (const [re, k] of RULES) if (re.test(t)) return k; return 'gear'; }
  function el(tag, cls, html) { const e = document.createElement(tag); if (cls) e.className = cls; if (html != null) e.innerHTML = html; return e; }
  function head(text, extra) { const h = el('div', 'sp-sec', '<span></span><svg width="16" height="16" viewBox="0 0 24 24" ' + P + '><path d="m9 6 6 6-6 6"/></svg>'); h.firstChild.textContent = text; if (extra) h.dataset.sec = extra; return h; }
  function titleOf(field) { const d = field.firstElementChild; if (!d) return ''; const c = d.cloneNode(true); $$('small', c).forEach((s) => s.remove()); return c.textContent.replace(/\s+/g, ' ').trim(); }

  function decorate(root) {
    $$('.field', root).forEach((f) => {
      if (f.dataset.sp) return; f.dataset.sp = '1';
      const t = titleOf(f); const ic = el('span', 'sp-ic', svg(iconFor(t + ' ' + (f.id || ''))));
      f.insertBefore(ic, f.firstChild); f.classList.add('sp-row');
    });
    $$('.btn', root).forEach((b) => b.classList.add('sp-pill'));
  }

  function build() {
    const S = $('#settings'); if (!S || S.dataset.sp) return; S.dataset.sp = '1'; S.classList.add('sp');
    // header: X left, title, pill right
    const sh = $(':scope > .set-head', S), close = $('#close-set');
    if (sh && close) {
      sh.classList.add('sp-head'); sh.insertBefore(close, sh.firstChild); close.classList.add('sp-x');
      const pill = el('span', 'sp-status'); pill.id = 'sp-status'; sh.appendChild(pill);
    }
    // Updates becomes its own page
    const tabs = $(':scope > .tabs', S), more = $('#p-more');
    if (tabs && more && !$('#p-updates')) {
      const upd = $('#upd-line') && $('#upd-line').closest('.field');
      const crash = $('#crash-list') && $('#crash-list').closest('.field');
      const pane = el('div', 'pane'); pane.id = 'p-updates';
      pane.appendChild(head('Ped Bot updates')); if (upd) pane.appendChild(upd);
      if (crash) { pane.appendChild(head('Crash reports')); pane.appendChild(crash); }
      more.after(pane);
      const tb = el('button', 'tab'); tb.type = 'button'; tb.dataset.pane = 'p-updates'; tb.textContent = 'Updates';
      tabs.appendChild(tb);
      tb.onclick = () => { $$('.tab', S).forEach((x) => x.classList.remove('active')); $$('.pane', S).forEach((p) => p.classList.remove('active')); tb.classList.add('active'); pane.classList.add('active'); status(); };
      // Connections: apps first, then the app's own options
      const conn = $('#conn-list') && $('#conn-list').closest('.field');
      const wa = $('#wa-box'), qbs = $('#qbs-on') && $('#qbs-on').closest('.field');
      const app = $$(':scope > .field', more).filter((f) => f !== conn && f !== wa && f !== qbs);
      more.innerHTML = '';
      more.appendChild(head('Connected apps', 'apps')); if (conn) { conn.classList.add('sp-conn'); more.appendChild(conn); }
      if (wa) more.appendChild(wa);
      if (qbs) { more.appendChild(head('Featured')); more.appendChild(qbs); }
      if (app.length) { more.appendChild(head('On this PC')); app.forEach((f) => more.appendChild(f)); }
    }
    // section headers for the other pages
    const heads = { 'p-general': 'For you', 'p-voice': 'Voice', 'p-rules': 'Safety rules', 'p-themes': 'Themes' };
    Object.keys(heads).forEach((id) => { const p = $('#' + id); if (p && !$(':scope > .sp-sec', p)) p.insertBefore(head(heads[id]), p.firstChild); });
    $$('.set-head', S).forEach((h) => { if (h !== sh) h.classList.add('sp-sec-old'); });
    decorate(S);
    // floating search
    const bar = el('div', 'sp-search', '<svg width="18" height="18" viewBox="0 0 24 24" ' + P + '><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg><input type="search" id="sp-q" placeholder="Search settings" autocomplete="off" aria-label="Search settings">');
    S.appendChild(bar);
    const qi = $('#sp-q', bar); qi.oninput = () => filter(qi.value);
    $$('.tab', S).forEach((t) => t.addEventListener('click', () => { qi.value = ''; filter(''); setTimeout(status, 0); const tb = t.parentNode; tb.scrollLeft = Math.max(0, t.offsetLeft - (tb.clientWidth - t.offsetWidth) / 2); }));
    // connected-apps rows (re-rendered by maintenance_ui.js)
    const list = $('#conn-list');
    if (list) { fixConn(); new MutationObserver(fixConn).observe(list, { childList: true }); }
    const wst = $('#wa-state'); if (wst) new MutationObserver(status).observe(wst, { childList: true, characterData: true, subtree: true });
    const th = $('#p-themes'); if (th) new MutationObserver(status).observe(th, { attributes: true, subtree: true, attributeFilter: ['class'] });
    status();
  }

  function fixConn() {
    const list = $('#conn-list'); if (!list) return;
    $$('.conn-row', list).forEach((row) => {
      if (row.dataset.sp) return; row.dataset.sp = '1';
      const span = row.querySelector('span'), b = row.querySelector('button'); if (!span || !b) return;
      const sm = span.querySelector('small'); const on = sm && /^connected/i.test(sm.textContent.trim());
      const name = span.childNodes[0] ? span.childNodes[0].textContent.trim() : span.textContent;
      span.className = 'sp-txt'; span.innerHTML = ''; const n = el('b'); n.textContent = name; const s = el('small');
      s.textContent = on ? 'Signed in on this PC' : 'Sign in once with Google'; span.append(n, s);
      row.insertBefore(el('span', 'sp-ic', svg(iconFor(name))), row.firstChild);
      b.classList.add('sp-pill');
      if (on) {
        b.classList.add('sp-on'); b.textContent = 'Connected'; b.title = 'Tap to disconnect';
        b.addEventListener('click', (e) => { if (!confirm('Disconnect ' + name + '?')) { e.stopImmediatePropagation(); e.preventDefault(); } }, true);
      } else if (!b.disabled) { b.classList.add('sp-accent'); b.textContent = 'Authorize'; }
    });
    status();
  }

  function filter(q) {
    const S = $('#settings'); q = q.trim().toLowerCase(); S.classList.toggle('sp-searching', !!q);
    $$('.pane', S).forEach((p) => {
      let any = false;
      $$('.field, .conn-row, .th-card', p).forEach((f) => { const hit = !q || f.textContent.toLowerCase().includes(q); f.classList.toggle('sp-hide', !hit); if (hit) any = true; });
      p.classList.toggle('sp-hit', !!q && any);
    });
  }

  let ver = '';
  async function status() {
    const pill = $('#sp-status'); if (!pill) return;
    const act = $('#settings .tab.active'); const pane = act ? act.dataset.pane : '';
    let t = '';
    if (pane === 'p-more') {
      let n = $$('#conn-list .sp-on').length;
      const wa = $('#wa-state'); if (wa && /^connected|linked|ready/i.test(wa.textContent.trim())) n++;
      const ph = $('#phone-on'); if (ph && ph.checked) n++;
      t = n + ' connected';
    } else if (pane === 'p-updates') {
      if (!ver) { try { ver = (await (await fetch('/api/update')).json()).current || ''; } catch (e) {} }
      if (!ver) { const m = (($('#upd-line') || {}).textContent || '').match(/(\d+\.\d+\.\d+)/); if (m) ver = m[1]; }
      t = ver ? 'v' + ver : 'Updates';
    } else if (pane === 'p-themes') {
      const on = $('#p-themes .th-card.on .th-name'); t = on ? on.textContent.trim() : 'Theme';
    } else {
      const titles = { 'p-general': 'General', 'p-voice': 'Voice', 'p-rules': 'Rules' }; t = titles[pane] || '';
    }
    pill.textContent = t; pill.hidden = !t;
    const names = { 'p-more': 'Connect apps', 'p-updates': 'Updates', 'p-themes': 'Themes', 'p-voice': 'Voice', 'p-rules': 'Rules' };
    const ttl = $('#settings .sp-head > b'); if (ttl) ttl.textContent = names[pane] || 'Settings';
  }

  function boot() { build(); setTimeout(() => { decorate($('#settings') || document); status(); }, 1200); }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot); else boot();
  window.pbSettingsPage = { status, filter, decorate, _iconFor: iconFor };
})();
