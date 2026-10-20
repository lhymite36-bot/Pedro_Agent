// 1.4.14 Themes: Liquid Glass presets + Custom. Saved on the PC and synced to the phone (/api/theme + live 'theme' event).
(function (root) {
  'use strict';
  const $ = (s) => document.querySelector(s);
  // w1..w5 wallpaper blobs, tint = glass colour, acc/acc2 = accent + highlight, base = backdrop
  const P = {
    aurora:   { name: 'Aurora', sub: 'Purple · blue · pink', w: ['rgba(124,77,255,.7)', 'rgba(46,120,255,.6)', 'rgba(255,64,170,.55)', 'rgba(70,40,200,.45)', 'rgba(160,90,255,.35)'], tint: '#1e1e2a', acc: '#8fa6ff', acc2: '#d08cff', base: '#07070c' },
    midnight: { name: 'Midnight Blue', sub: 'Deep navy glass', w: ['rgba(30,70,200,.7)', 'rgba(20,120,255,.5)', 'rgba(60,40,180,.5)', 'rgba(10,30,110,.6)', 'rgba(70,130,255,.3)'], tint: '#141c30', acc: '#6fa8ff', acc2: '#8f9dff', base: '#04060e' },
    crimson:  { name: 'Crimson', sub: 'Dark red, like the icon', w: ['rgba(200,20,50,.65)', 'rgba(120,10,40,.6)', 'rgba(255,70,90,.45)', 'rgba(80,0,20,.6)', 'rgba(230,40,80,.3)'], tint: '#2a1418', acc: '#ff5a6e', acc2: '#ff8f7a', base: '#0b0405' },
    emerald:  { name: 'Emerald', sub: 'Green glass', w: ['rgba(0,170,110,.6)', 'rgba(20,110,90,.6)', 'rgba(80,220,160,.4)', 'rgba(0,70,50,.6)', 'rgba(60,200,140,.3)'], tint: '#122420', acc: '#3fe0a0', acc2: '#7fe8c8', base: '#030a08' },
    sunset:   { name: 'Sunset', sub: 'Orange · pink', w: ['rgba(255,110,40,.6)', 'rgba(255,60,140,.55)', 'rgba(255,170,60,.45)', 'rgba(150,30,90,.55)', 'rgba(255,120,120,.3)'], tint: '#2a1a1e', acc: '#ff9a5c', acc2: '#ff6fae', base: '#0c0606' },
    ocean:    { name: 'Ocean Teal', sub: 'Teal · cyan', w: ['rgba(0,160,170,.6)', 'rgba(0,110,200,.55)', 'rgba(60,220,210,.4)', 'rgba(0,60,90,.6)', 'rgba(40,190,220,.3)'], tint: '#11222a', acc: '#3fd6e0', acc2: '#62a8ff', base: '#030a0d' },
    graphite: { name: 'Mono Graphite', sub: 'Neutral greys', w: ['rgba(120,120,130,.45)', 'rgba(80,80,90,.5)', 'rgba(160,160,170,.3)', 'rgba(40,40,46,.6)', 'rgba(110,110,120,.25)'], tint: '#1c1c20', acc: '#d7d7de', acc2: '#a9a9b6', base: '#070708' },
    lavender: { name: 'Lavender', sub: 'Soft lilac', w: ['rgba(170,130,255,.55)', 'rgba(210,150,255,.45)', 'rgba(140,120,230,.45)', 'rgba(90,60,170,.5)', 'rgba(230,180,255,.3)'], tint: '#221d30', acc: '#c7a6ff', acc2: '#f0b0ff', base: '#08060d' },
    goldnoir: { name: 'Gold Noir', sub: 'Black · gold', w: ['rgba(210,160,40,.5)', 'rgba(120,80,10,.55)', 'rgba(255,200,90,.35)', 'rgba(40,30,10,.7)', 'rgba(230,170,60,.25)'], tint: '#1e1a12', acc: '#f2c14e', acc2: '#ffdf8a', base: '#060503' },
    neon:     { name: 'Neon Cyber', sub: 'Magenta · cyan', w: ['rgba(255,0,200,.55)', 'rgba(0,240,255,.5)', 'rgba(140,0,255,.5)', 'rgba(0,80,160,.55)', 'rgba(0,255,170,.3)'], tint: '#151428', acc: '#22f0ff', acc2: '#ff3fd8', base: '#05030c' },
  };
  const WALLS = { aurora: 'aurora', nebula: 'neon', dusk: 'sunset', deep: 'midnight', plain: 'graphite' };
  const KEY = 'pb-theme';
  let theme = load();

  function load() { try { return JSON.parse(localStorage.getItem(KEY) || 'null') || { preset: 'aurora', custom: { accent: '#8fa6ff', wallpaper: 'aurora', blur: 26, alpha: 46 } }; } catch (e) { return { preset: 'aurora', custom: {} }; } }
  function mixHex(h, to, a) { const n = parseInt(h.slice(1), 16); const c = [n >> 16, (n >> 8) & 255, n & 255].map((v) => Math.round(v + (to - v) * a)); return '#' + c.map((v) => v.toString(16).padStart(2, '0')).join(''); }
  function resolve(t) {
    if (t.preset !== 'custom') return Object.assign({ blur: 26, alpha: 46 }, P[t.preset] || P.aurora);
    const c = t.custom || {}; const base = P[WALLS[c.wallpaper] || 'aurora'] || P.aurora; const acc = /^#[0-9a-f]{6}$/i.test(c.accent || '') ? c.accent : base.acc;
    return Object.assign({}, base, { acc: acc, acc2: mixHex(acc, 255, 0.35), blur: c.blur == null ? 26 : c.blur, alpha: c.alpha == null ? 46 : c.alpha });
  }
  function apply(t, save) {
    theme = t; const r = resolve(t); const s = document.documentElement.style;
    r.w.forEach((v, i) => s.setProperty('--w' + (i + 1), v));
    s.setProperty('--tint', r.tint); s.setProperty('--acc', r.acc); s.setProperty('--acc2', r.acc2); s.setProperty('--base', r.base);
    s.setProperty('--g-blurpx', r.blur + 'px'); s.setProperty('--g-alpha', String(r.alpha / 100));
    const meta = document.querySelector('meta[name="theme-color"]'); if (meta) meta.content = r.base;
    try { localStorage.setItem(KEY, JSON.stringify(t)); } catch (e) {}
    paint();
    if (save) fetch('/api/theme', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(t) }).catch(() => {});
  }
  root.pbApplyTheme = (t) => apply(t, false);
  root.pbThemes = P;

  function preview(el, p) {
    el.style.background = `radial-gradient(60% 70% at 20% 25%,${p.w[0]},transparent 70%),radial-gradient(55% 65% at 85% 20%,${p.w[1]},transparent 70%),radial-gradient(60% 70% at 70% 90%,${p.w[2]},transparent 70%),${p.base}`;
    const glass = `color-mix(in srgb,${p.tint} 55%,transparent)`;
    el.innerHTML = '';
    [['s', glass], ['b', `linear-gradient(135deg,${p.acc},${p.acc2})`], ['c', glass], ['d', glass]].forEach(([k, bg]) => { const i = document.createElement('i'); i.className = k; i.style.background = bg; el.appendChild(i); });
  }
  function paint() {
    document.querySelectorAll('.th-card').forEach((c) => c.classList.toggle('on', c.dataset.preset === theme.preset));
    const cu = theme.custom || {};
    if ($('#th-accent')) { $('#th-accent').value = cu.accent || '#8fa6ff'; $('#th-wall').value = cu.wallpaper || 'aurora'; $('#th-blur').value = cu.blur == null ? 26 : cu.blur; $('#th-alpha').value = cu.alpha == null ? 46 : cu.alpha; }
    const cp = $('.th-card[data-preset="custom"] .th-prev'); if (cp) preview(cp, resolve(Object.assign({}, theme, { preset: 'custom' })));
  }
  function build() {
    const pane = $('#p-themes'); if (!pane || pane.dataset.built) return; pane.dataset.built = '1';
    const grid = document.createElement('div'); grid.className = 'th-grid';
    Object.keys(P).concat('custom').forEach((k) => {
      const b = document.createElement('button'); b.type = 'button'; b.className = 'th-card'; b.dataset.preset = k;
      const pv = document.createElement('div'); pv.className = 'th-prev'; preview(pv, k === 'custom' ? resolve({ preset: 'custom', custom: theme.custom || {} }) : P[k]);
      const n = document.createElement('span'); n.className = 'th-name'; n.textContent = k === 'custom' ? 'Custom' : P[k].name;
      const sb = document.createElement('span'); sb.className = 'th-sub'; sb.textContent = k === 'custom' ? 'Your accent, wallpaper, blur' : P[k].sub;
      b.append(pv, n, sb); b.onclick = () => apply(Object.assign({}, theme, { preset: k }), true); grid.appendChild(b);
    });
    const cu = document.createElement('div'); cu.className = 'th-custom';
    cu.innerHTML = '<label for="th-accent">Accent colour</label><input id="th-accent" type="color">' +
      '<label for="th-wall">Wallpaper</label><select id="th-wall"><option value="aurora">Aurora</option><option value="nebula">Nebula</option><option value="dusk">Dusk</option><option value="deep">Deep sea</option><option value="plain">Plain</option></select>' +
      '<label for="th-blur">Glass blur</label><input id="th-blur" type="range" min="0" max="60">' +
      '<label for="th-alpha">Glass opacity</label><input id="th-alpha" type="range" min="15" max="95">';
    const h = document.createElement('div'); h.className = 'set-head'; h.textContent = 'Custom';
    pane.append(grid, h, cu);
    let tm = 0;
    const onCustom = (now) => { const t = { preset: 'custom', custom: { accent: $('#th-accent').value, wallpaper: $('#th-wall').value, blur: +$('#th-blur').value, alpha: +$('#th-alpha').value } };
      apply(t, false); clearTimeout(tm); tm = setTimeout(() => apply(t, true), now ? 0 : 350); };
    ['#th-accent', '#th-blur', '#th-alpha'].forEach((id) => { $(id).oninput = () => onCustom(false); });
    $('#th-wall').onchange = () => onCustom(true);
    paint();
  }
  apply(theme, false);   // instant paint from this device's copy
  function sync() { fetch('/api/theme', { cache: 'no-store' }).then((r) => r.json()).then((t) => { if (t && t.preset && JSON.stringify(t) !== JSON.stringify(theme)) apply(t, false); }).catch(() => {}); }
  function wire() { build(); sync(); }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', wire); else wire();
  root.pbThemeEvent = (ev) => { if (ev && ev.theme) apply(ev.theme, false); else sync(); };
})(this);
