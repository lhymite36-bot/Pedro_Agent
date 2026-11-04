// 1.9.1 Ped Bot Pro (freemium). BYOK stays: AI always uses your own Gemini key.
// Upgrade page, lock icons on Pro features, Restore purchase, Razorpay Checkout (TEST mode only).
(function () {
  'use strict';
  const $ = (s, r) => (r || document).querySelector(s);
  const $$ = (s, r) => Array.from((r || document).querySelectorAll(s));
  const esc = (t) => String(t == null ? '' : t).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const LOCK = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/></svg>';
  const CHECK = '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg>';
  const STAR = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l2.5 5 5.5.8-4 3.9 1 5.5-5-2.7-5 2.7 1-5.5-4-3.9 5.5-.8z"/></svg>';
  let st = { isPro: false, plan: 'free', config: null };
  let period = localStorage.pbPlanPeriod || 'year';
  let inside = false;   // our own calls are not intercepted
  const rupees = (p) => '₹' + (p / 100).toLocaleString('en-IN');
  const api = (b) => { inside = true; const f = fetch('/api/plan', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) }); inside = false; return f.then((r) => r.json()).catch(() => ({ ok: false, error: 'Ped Bot is not reachable.' })); };
  async function refresh() { try { const r = await (await fetch('/api/plan', { cache: 'no-store' })).json(); if (r && r.config) st = r; } catch (e) {} decorate(); return st; }

  const ROWS = [
    ['Core chat with your own Gemini key', 'free'], ['Bots', 'free', 'Up to 2 on Free · unlimited on Pro'], ['Automations', 'free', '1 on Free · unlimited on Pro'],
    ['3D avatars (male + female)', 'pro'], ['All themes + custom colours', 'pro', 'Free: Grok Dark, Grok Light, Aurora'], ['Projects (group chats)', 'free', '1 on Free · unlimited on Pro'],
    ['YouTube autopilot', 'pro'], ['Studio', 'pro', 'WhatsApp drafts, trend radar, video edit, price watch…'], ['Lab', 'pro', 'Twin call, swarm research, bot company…'],
    ['Pro tools (Batch 2)', 'pro', 'Phone control, PC autopilot, memory, team tasks, Hey Ped…'],
  ];

  function page(msg) {
    let p = $('#plan191'); if (p) p.remove();
    p = document.createElement('div'); p.id = 'plan191';
    p.innerHTML = '<div class="pro-head"><button type="button" class="pro-x" aria-label="Close"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 6 6 18M6 6l12 12"/></svg></button><b>Ped Bot Pro</b><span class="pro-pill">' + (st.isPro ? 'Pro' : 'Free') + '</span></div><div class="pro-body"></div>';
    document.body.appendChild(p);
    $('.pro-x', p).onclick = () => p.remove();
    draw(p, msg);
    return p;
  }

  function draw(p, msg) {
    const c = st.config || { prices: { month: 19900, year: 149900 }, simulate: true };
    const body = $('.pro-body', p);
    $('.pro-pill', p).textContent = st.isPro ? 'Pro' : 'Free';
    const hero = st.isPro
      ? '<div class="pl191-hero"><b>You are on Pro</b><small>' + esc(st.period === 'year' ? 'Yearly' : 'Monthly') + ' · active until ' + esc(st.until) + (st.source === 'simulated' ? ' · simulated (test)' : ' · Razorpay test') + '</small></div>'
      : '<div class="pl191-hero"><b>Unlock everything Ped Bot can do</b><small>Your AI stays on your own Gemini key — free and private. Pro pays for the features, not the AI.</small></div>';
    body.innerHTML = (msg ? '<div class="pro-err">' + esc(msg) + '</div>' : '') + hero +
      '<span class="pl191-test">TEST MODE — no real money</span>' +
      (st.isPro ? '' : '<div class="pl191-per"><button type="button" data-p="month"><small>Monthly</small><b>' + rupees(c.prices.month) + '</b><small>per month</small></button>' +
        '<button type="button" data-p="year"><small>Yearly <span class="pl191-save">SAVE 37%</span></small><b>' + rupees(c.prices.year) + '</b><small>per year · ' + rupees(Math.round(c.prices.year / 12)) + '/mo</small></button></div>' +
        '<div class="pl191-cta"><button type="button" class="pro-go acc" id="pl-buy">Upgrade with Razorpay</button>' +
        (c.simulate ? '<button type="button" class="pro-go" id="pl-sim">Simulate purchase (dev)</button>' : '') + '</div>' +
        (c.note ? '<div class="pro-note">' + esc(c.note) + '</div>' : '')) +
      '<div class="pro-sec"><span>What you get</span></div>' +
      ROWS.map(([n, tier, sub]) => '<div class="pro-row' + (tier === 'free' ? ' pl191-row-free' : '') + '"><span class="pro-ic">' + (tier === 'pro' && !st.isPro ? '<span class="pl191-lock" style="margin:0">' + LOCK + '</span>' : CHECK) + '</span><div class="pro-txt"><b>' + esc(n) + '</b>' + (sub ? '<small>' + esc(sub) + '</small>' : '') + '</div><span class="pro-go">' + (tier === 'free' ? 'Free' : 'Pro') + '</span></div>').join('') +
      '<div class="pl191-cta"><button type="button" class="pro-go" id="pl-restore">Restore purchase</button>' +
      (st.isPro && st.source !== 'live' ? '<button type="button" class="pro-go" id="pl-reset">Back to Free (test reset)</button>' : '') + '</div>' +
      '<div class="pro-note">Payments run through Razorpay in test mode. Use Razorpay test cards or test UPI (success@razorpay). Signed-in purchases are saved to your Ped Bot account so Restore works on your other devices.</div><div class="st-out"></div>';
    $$('.pl191-per button', body).forEach((b) => { b.classList.toggle('on', b.dataset.p === period); b.onclick = () => { period = localStorage.pbPlanPeriod = b.dataset.p; draw(p); }; });
    const out = $('.st-out', body);
    const done = async (r) => {
      if (r && r.config === undefined) await refresh();
      if (r && r.ok) { draw(p); $('.st-out', p).innerHTML = '<div class="pl191-ok">' + esc(r.message || 'Done.') + '</div>'; }
      else out.innerHTML = '<div class="pro-err">' + esc((r && r.error) || 'Something went wrong.') + '</div>';
    };
    const buy = $('#pl-buy', body); if (buy) buy.onclick = () => checkout(buy, done);
    const sim = $('#pl-sim', body); if (sim) sim.onclick = async () => { sim.disabled = true; done(await api({ action: 'simulate', period })); };
    $('#pl-restore', body).onclick = async (e) => { e.target.disabled = true; out.innerHTML = '<div class="pro-note">Checking your account…</div>'; done(await api({ action: 'restore' })); };
    const rs = $('#pl-reset', body); if (rs) rs.onclick = async () => { if (confirm('Switch back to Free? (test reset)')) done(await api({ action: 'downgrade' })); };
  }

  function loadRzp() {
    if (window.Razorpay) return Promise.resolve(true);
    return new Promise((ok) => { const s = document.createElement('script'); s.src = 'https://checkout.razorpay.com/v1/checkout.js'; s.onload = () => ok(true); s.onerror = () => ok(false); document.head.appendChild(s); });
  }

  async function checkout(btn, done) {
    btn.disabled = true;
    const o = await api({ action: 'order', period });
    if (!o.ok) { btn.disabled = false; done(o); return; }
    if (!(await loadRzp())) { btn.disabled = false; done({ ok: false, error: 'Could not load Razorpay Checkout. Check the internet connection.' }); return; }
    const opts = {
      key: o.keyId, amount: o.amount, currency: o.currency, name: 'Ped Bot Pro',
      description: (period === 'year' ? 'Yearly' : 'Monthly') + ' plan (test mode)',
      theme: { color: '#1d6fe0' }, notes: { period },
      handler: async (resp) => done(await api(Object.assign({ action: 'verify', period }, resp))),
      modal: { ondismiss: () => { btn.disabled = false; } },
    };
    if (o.orderId) opts.order_id = o.orderId;
    try { const rz = new window.Razorpay(opts); rz.on('payment.failed', (e) => { btn.disabled = false; done({ ok: false, error: 'Payment failed: ' + ((e && e.error && e.error.description) || 'try again') }); }); rz.open(); }
    catch (e) { btn.disabled = false; done({ ok: false, error: 'Razorpay Checkout could not open.' }); }
  }

  function open(msg) { refresh().then(() => page(msg)); }

  // ---- locks ----
  const LOCKED_MENU = ['m184-avatar', 'm184-studio', 'm184-lab'];
  const FREE_THEMES = () => ((st.config && st.config.freeThemes) || ['grokDark', 'grokLight', 'aurora']);
  function badge(el) { if (!el || el.querySelector(':scope > .pl191-lock')) return; const s = document.createElement('span'); s.className = 'pl191-lock'; s.innerHTML = LOCK; s.title = 'Pro'; el.appendChild(s); }
  function unbadge() { $$('.pl191-lock').forEach((x) => { if (!x.closest('#plan191')) x.remove(); }); }
  function lockedEl(el) {
    if (st.isPro || !el) return '';
    const m = el.closest('#m184-avatar,#m184-studio,#m184-lab,[data-target="m184-avatar"],[data-target="m184-studio"],[data-target="m184-lab"],[data-pro190]');
    if (m) return 'This';
    const th = el.closest('.th-card');
    if (th && FREE_THEMES().indexOf(th.dataset.preset) < 0) return 'theme';
    if (el.closest('#th-accent,#th-wall,#th-blur,#th-alpha')) return 'theme';
    return '';
  }
  function decorate() {
    if (st.isPro) { unbadge(); }
    else {
      LOCKED_MENU.forEach((id) => { badge(document.getElementById(id)); $$('[data-target="' + id + '"]').forEach(badge); });
      $$('[data-pro190]').forEach(badge);
      $$('.th-card').forEach((c) => { if (FREE_THEMES().indexOf(c.dataset.preset) < 0) badge(c); });
    }
    menus();
  }
  function menus() {
    const label = st.isPro ? 'Ped Bot Pro ✓' : 'Upgrade to Pro';
    const m = $('#pd-menu');
    if (m) {
      let b = m.querySelector('[data-plan191]');
      if (!b) { b = document.createElement('button'); b.type = 'button'; b.dataset.plan191 = '1'; b.onclick = (e) => { e.stopPropagation(); m.classList.remove('open'); open(); }; m.insertBefore(b, m.firstChild); }
      if (b.textContent !== label) b.textContent = label;
    }
    const nav = $('#bottomnav');
    const after = nav && nav.querySelector('.pl-extra[data-target="acct-updates"]');
    if (nav && after) {
      let b = nav.querySelector('[data-plan191]');
      if (!b) { b = document.createElement('button'); b.type = 'button'; b.className = 'pl-extra'; b.dataset.plan191 = '1'; b.dataset.target = 'plan191'; b.innerHTML = STAR + '<span></span>';
        b.onclick = (e) => { e.stopPropagation(); document.body.classList.remove('pl-grid-open', 'pl-home-on'); open(); }; after.parentNode.insertBefore(b, after); }
      const sp = b.querySelector('span'); if (sp && sp.textContent !== label) sp.textContent = label;
    }
  }
  // click guard (capture) on locked entries
  ['click', 'pointerdown', 'focusin'].forEach((ev) => document.addEventListener(ev, (e) => {
    const why = lockedEl(e.target); if (!why) return;
    e.preventDefault(); e.stopImmediatePropagation();
    if (ev === 'click' || ev === 'focusin') { if (e.target.blur) e.target.blur(); open(why === 'theme' ? 'That theme is part of Ped Bot Pro.' : ''); }
  }, true));
  // wrap the feature entry points too (voice commands, shortcuts)
  function wrap() {
    if (window.pbOpenAvatar && !window.pbOpenAvatar._pl) { const f = window.pbOpenAvatar; window.pbOpenAvatar = function () { if (!st.isPro) return open('3D avatars are part of Ped Bot Pro.'); return f.apply(this, arguments); }; window.pbOpenAvatar._pl = 1; }
    [['pbStudio', 'Studio'], ['pbLab', 'Lab'], ['pbPro', 'Pro tools']].forEach(([k, n]) => {
      const o = window[k]; if (o && o.open && !o.open._pl) { const f = o.open; o.open = function () { if (!st.isPro) return open(n + ' is part of Ped Bot Pro.'); return f.apply(this, arguments); }; o.open._pl = 1; }
    });
  }
  // any /api answer that says pro_required opens the upgrade page
  // 1.9.2: only a request the user just started may open the page (background polls like Studio's call check must not)
  let lastAct = 0;
  ['pointerdown', 'keydown', 'touchstart'].forEach((ev) => document.addEventListener(ev, () => { lastAct = Date.now(); }, true));
  const userMade = () => Date.now() - lastAct < 4000;
  const POPS = /\/api\/(bots|theme|shorts)(\?|$)/;   // groups_ui shows its own message + opens Upgrade   // entry points of Studio/Lab/Pro tools/avatar are gated by the wrappers below
  const _f = window.fetch;
  window.fetch = function (u, o) {
    const p = _f.apply(this, arguments);
    if (inside || typeof u !== 'string' || !POPS.test(u)) return p;
    return p.then((r) => {
      if (r.status === 402 || (o && o.method === 'POST')) r.clone().json().then((j) => { if (j && j.code === 'pro_required' && userMade()) { open(j.error); if (u.indexOf('/api/theme') >= 0) { _f('/api/theme', { cache: 'no-store' }).then((x) => x.json()).then((t) => { try { localStorage.setItem('pb-theme', JSON.stringify(t)); } catch (e) {} }).catch(() => {}); } } }).catch(() => {});
      return r;
    });
  };
  let t = 0;
  function boot() {
    refresh(); wrap();
    new MutationObserver(() => { clearTimeout(t); t = setTimeout(() => { wrap(); decorate(); }, 80); }).observe(document.body, { childList: true, subtree: true });
    setInterval(refresh, 10 * 60 * 1000);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot); else boot();
  window.pbPlan = { open, refresh, state: () => st };
})();

/* 1.9.3: the header Model badge did nothing. Open Settings at the model picker. */
(function () {
  function openModel() {
    const set = document.getElementById('setbtn');
    if (set) set.click();
    setTimeout(() => {
      const sel = document.getElementById('model2'); if (!sel) return;
      let n = sel; while (n && n !== document.body) { if (n.hidden) n.hidden = false; n = n.parentElement; }
      const tab = sel.closest('[data-tab],[data-pane]');
      if (tab) { const k = tab.dataset.tab || tab.dataset.pane; const b = document.querySelector('[data-tab-btn="' + k + '"],[data-for="' + k + '"]'); if (b) b.click(); }
      sel.scrollIntoView({ block: 'center' }); sel.focus();
      const f = sel.closest('.field'); if (f) { f.style.outline = '2px solid #4c8dff'; setTimeout(() => { f.style.outline = ''; }, 1800); }
    }, 250);
  }
  function bind() { const hm = document.getElementById('hdr-model'); if (hm && !hm.dataset.b193) { hm.dataset.b193 = 1; hm.addEventListener('click', openModel); } }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', bind); else bind();
})();
