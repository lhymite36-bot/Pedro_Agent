// Ped Bot avatars: the flat blob set (one colour body, two white pill eyes).
// createAvatar(el, {color, shape}) -> {setState, setLevel, setLook, celebrate, state, destroy}
// States: idle | listening | thinking | working | speaking | done | sleeping.
// Animation is plain CSS (avatars.css): idle -> pb-idle, thinking -> pb-thinking,
// working -> pb-roll (big) / pb-spin (small), done -> pb-happy, sleeping -> pb-sleepy.
(function (root) {
  'use strict';
  const SHAPES = ['circle', 'ball', 'square', 'pill', 'triangle', 'hexagon', 'cloud', 'drop', 'clover', 'star', 'heart'];
  const LABELS = { star: 'Star', heart: 'Heart', circle: 'Circle', ball: 'Ball', square: 'Rounded square', pill: 'Pill', triangle: 'Triangle', hexagon: 'Hexagon', cloud: 'Cloud', drop: 'Drop', clover: 'Clover' };
  const COLORS = [
    ['brown', '#8b5a32'], ['red', '#e5383b'], ['orange', '#ff6a00'], ['amber', '#f5a524'], ['green', '#00c473'],
    ['teal', '#14b8a6'], ['blue', '#1683f5'], ['purple', '#8b5cf6'], ['pink', '#ec4899'], ['grey', '#7a7a7a'],
  ];
  // Older bots used animal shapes; they get the nearest new shape and keep their colour.
  const LEGACY = { round: 'circle', blob: 'ball', spark: 'ball', ghost: 'drop', robot: 'square', octopus: 'cloud', cat: 'ball', bunny: 'ball', fox: 'triangle', bear: 'circle', owl: 'circle', alien: 'drop', dino: 'clover', panda: 'circle', frog: 'pill', chick: 'star' };
  function norm(sh) { return SHAPES.indexOf(sh) >= 0 ? sh : (LEGACY[sh] || 'ball'); }
  function E(x, y, w, h, r) {
    return `<g transform="rotate(${r || 0} ${x} ${y})"><rect x="${x - w / 2}" y="${y - h / 2}" width="${w}" height="${h}" rx="${Math.min(w, h) / 2}" fill="#fff"/></g>`;
  }
  const PARTS = {
    circle: (c) => [`<circle cx="100" cy="108" r="74"/>`, E(84, 100, 14, 30) + E(116, 100, 14, 30)],
    star: (c) => [`<path d="M100,44 L118,92 L168,94 L128,124 L142,172 L100,144 L58,172 L72,124 L32,94 L82,92Z" stroke="${c}" stroke-width="16" stroke-linejoin="round"/>`, E(86, 112, 12, 26) + E(114, 112, 12, 26)],
    heart: (c) => [`<path d="M100,176 C60,146 28,120 28,88 C28,62 48,46 70,46 C84,46 94,54 100,66 C106,54 116,46 130,46 C152,46 172,62 172,88 C172,120 140,146 100,176Z"/>`, E(85, 100, 14, 30) + E(115, 100, 14, 30)],
    blob: (c) => [`<path d="M100,34 C146,34 176,62 176,108 C176,152 150,180 100,180 C50,180 24,154 24,110 C24,66 56,34 100,34Z" transform="rotate(-8 100 108)"/>`, E(86, 102, 14, 30, 8) + E(118, 98, 14, 30, 8)],
    square: (c) => [`<rect x="30" y="38" width="140" height="140" rx="40"/>`, E(84, 104, 14, 32) + E(116, 104, 14, 32)],
    pill: (c) => [`<rect x="22" y="58" width="156" height="108" rx="54"/>`, E(80, 108, 20, 38) + E(118, 108, 20, 38)],
    triangle: (c) => [`<path d="M100,48 L162,160 L38,160Z" stroke="${c}" stroke-width="40" stroke-linejoin="round"/>`, E(90, 138, 11, 24) + E(112, 138, 11, 24)],
    hexagon: (c) => [`<path d="M100,40 L160,74 L160,142 L100,176 L40,142 L40,74Z" stroke="${c}" stroke-width="22" stroke-linejoin="round"/>`, E(86, 106, 14, 30) + E(114, 106, 14, 30)],
    cloud: (c) => [`<circle cx="70" cy="115" r="44"/><circle cx="108" cy="82" r="42"/><circle cx="140" cy="112" r="40"/><circle cx="96" cy="140" r="40"/><circle cx="142" cy="145" r="30"/><circle cx="58" cy="148" r="28"/>`, E(92, 98, 30, 11, 22) + E(132, 114, 30, 11, 22)],
    drop: (c) => [`<path d="M100,24 C128,56 170,86 170,128 C170,166 138,182 100,182 C62,182 30,166 30,128 C30,86 72,56 100,24Z"/>`, E(84, 120, 15, 32) + E(112, 120, 15, 32)],
    clover: (c) => [`<g transform="rotate(-12 100 110)"><circle cx="72" cy="78" r="38"/><circle cx="130" cy="80" r="38"/><circle cx="70" cy="140" r="38"/><circle cx="132" cy="140" r="38"/><rect x="62" y="72" width="80" height="78"/></g>`, E(96, 118, 11, 28, 25) + E(122, 110, 11, 28, 25)],
    ball: (c) => [`<circle cx="100" cy="110" r="72"/>`, E(78, 88, 12, 26, 30) + E(108, 82, 12, 26, 30)],
  };
  function safeColor(c) { return /^#[0-9a-fA-F]{6}$/.test(c || '') ? c : '#1683f5'; }
  function svg(shape, color) {
    const c = safeColor(color); const p = PARTS[norm(shape)](c);
    return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200" class="pb-svg" aria-hidden="true"><g class="pb-body" fill="${c}">${p[0]}<g class="pb-eyes">${p[1]}</g></g></svg>`;
  }
  const STATE_CLASS = { done: 'pb-happy', idle: 'pb-idle', listening: 'pb-look', thinking: 'pb-thinking', speaking: 'pb-hop', done: 'pb-happy', sleeping: 'pb-sleepy' };
  const ALL = ['pb-idle', 'pb-look', 'pb-thinking', 'pb-hop', 'pb-happy', 'pb-sleepy', 'pb-roll', 'pb-spin'];
  const SLEEP_AFTER = 5 * 60 * 1000;
  function unref(t) { if (t && typeof t.unref === 'function') t.unref(); return t; }

  // 1.4.14: the 3D engine (pedbot-avatars.js) drives every avatar when it is loaded.
  const ENGINE_STATE = { idle: 'idle', listening: 'look', thinking: 'thinking', working: 'working', speaking: 'hop', done: 'done', sleeping: 'sleepy' };
  function create3d(el, opts) {
    const PB = root.PedBot; let shape = norm(opts.shape), color = safeColor(opts.color || '#1683f5'), state = 'idle', sleepTimer = 0;
    el.classList.add('pb3d'); el.innerHTML = '';
    const big = (el.clientWidth || 0) >= 80 || !!opts.follow;
    let bot = PB.create(el, { shape: shape, color: color, follow: big, seed: (Math.random() * 1e6) | 0 });
    function armSleep() { clearTimeout(sleepTimer); if (state === 'idle') sleepTimer = setTimeout(() => { if (state === 'idle') { bot.setState('sleepy'); state = 'sleeping'; } }, SLEEP_AFTER); }
    armSleep();
    const api = {
      setState(n) {
        if (n === state) return; const busy = state === 'thinking' || state === 'working' || state === 'speaking';
        el.classList.remove(state); state = n; el.classList.add(n);
        bot.setState(n === 'idle' && busy ? 'done' : (ENGINE_STATE[n] || 'idle')); armSleep();
      },
      setLevel() {},
      setLook(c, sh) {
        const ns = norm(sh || shape), nc = safeColor(c || color);
        if (nc !== color) { color = nc; bot.setColor(nc); }
        if (ns !== shape) { shape = ns; bot.setShape(ns); }
      },
      celebrate() { bot.setState('done'); },
      wake() { if (state === 'sleeping') { state = 'idle'; bot.setState('idle'); armSleep(); } },
      poke() { bot.poke(); },
      get state() { return state; },
      get shape() { return shape; },
      destroy() { clearTimeout(sleepTimer); bot.destroy(); },
    };
    return api;
  }

  function createAvatar(el, opts) {
    opts = opts || {};
    if (root.PedBot && root.PedBot.create && typeof document !== 'undefined' && el && el.appendChild && el.nodeType === 1) return create3d(el, opts);
    let color = safeColor(opts.color || '#1683f5'), shape = norm(opts.shape), state = 'idle', happy = false, doneTimer = 0, sleepTimer = 0;
    el.classList.add('pb-avatar'); el.classList.add('idle');
    function cls() {
      let c = happy && state === 'idle' ? 'pb-happy' : (STATE_CLASS[state] || 'pb-idle');
      if (state === 'working') c = (el.clientWidth || 0) >= 90 ? 'pb-roll' : 'pb-spin';
      ALL.forEach((k) => { if (k === c) el.classList.add(k); else el.classList.remove(k); });
    }
    function build() { el.innerHTML = svg(shape, color); if (el.dataset) el.dataset.shape = shape; cls(); }
    function armSleep() {
      clearTimeout(sleepTimer);
      if (state === 'idle') sleepTimer = unref(setTimeout(() => { if (state === 'idle') { el.classList.remove('idle'); state = 'sleeping'; el.classList.add('sleeping'); cls(); } }, SLEEP_AFTER));
    }
    build(); armSleep();
    const api = {
      setState(n) {
        if (n === state) return;
        const busy = state === 'thinking' || state === 'working' || state === 'speaking';
        el.classList.remove(state); state = n; el.classList.add(n);
        clearTimeout(doneTimer);
        happy = n === 'done' || (n === 'idle' && busy);
        if (happy) doneTimer = unref(setTimeout(() => { happy = false; if (state === 'done') { el.classList.remove('done'); state = 'idle'; el.classList.add('idle'); } cls(); armSleep(); }, 1700));
        cls(); armSleep();
      },
      setLevel() {},
      setLook(c, sh) { color = safeColor(c || color); shape = norm(sh || shape); build(); },
      celebrate() { happy = true; cls(); clearTimeout(doneTimer); doneTimer = unref(setTimeout(() => { happy = false; cls(); armSleep(); }, 1600)); },
      wake() { if (state === 'sleeping') { state = 'idle'; cls(); armSleep(); } },
      get state() { return state; },
      get shape() { return shape; },
      destroy() { clearTimeout(doneTimer); clearTimeout(sleepTimer); },
    };
    return api;
  }
  createAvatar.SHAPES = SHAPES; createAvatar.LABELS = LABELS; createAvatar.COLORS = COLORS;
  createAvatar.svg = svg; createAvatar.norm = norm;
  if (typeof module !== 'undefined' && module.exports) module.exports = { createAvatar, SHAPES, COLORS, svg, norm };
  else root.createAvatar = createAvatar;
})(this);
