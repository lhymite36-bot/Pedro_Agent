// Animated agent avatar with shapes, colour, and idle life.
// createAvatar(el, {color, shape}) -> {setState, setLevel, setLook, state, destroy}
// States: idle | listening | thinking | working | speaking | done.
// One shared requestAnimationFrame loop drives every avatar at the display
// rate, paused when the tab is hidden; prefers-reduced-motion keeps it still.
(function (root) {
  'use strict';
  const SHAPES = ['round', 'robot', 'cat', 'ghost', 'square', 'bunny', 'spark', 'fox', 'bear', 'owl', 'alien', 'dino', 'panda', 'frog', 'chick', 'octopus', 'star'];
  const LABELS = { round: 'Blob', robot: 'Robot', cat: 'Cat', ghost: 'Ghost', square: 'Square bot', bunny: 'Bunny', spark: 'Spark', fox: 'Fox', bear: 'Bear', owl: 'Owl', alien: 'Alien', dino: 'Dino', panda: 'Panda', frog: 'Frog', chick: 'Chick', octopus: 'Octo', star: 'Star' };
  function mix(hex, to, a) {
    const m = /^#?([0-9a-f]{6})$/i.exec(hex || '') || [0, '7c8cff']; const n = parseInt(m[1], 16);
    const c = [n >> 16, (n >> 8) & 255, n & 255].map((v) => Math.round(v + (to - v) * a));
    return '#' + c.map((v) => v.toString(16).padStart(2, '0')).join('');
  }
  function body(shape, F) {
    switch (shape) {
      case 'robot': return `<g class="av-antenna"><line x1="60" y1="24" x2="60" y2="12" stroke="${F.dark}" stroke-width="3"/><circle class="av-bulb" cx="60" cy="10" r="5" fill="#ffd36b"/></g>
        <rect x="10" y="52" width="10" height="20" rx="4" fill="${F.dark}"/><rect x="100" y="52" width="10" height="20" rx="4" fill="${F.dark}"/>
        <rect x="18" y="24" width="84" height="76" rx="16" fill="${F.fill}"/><rect x="28" y="44" width="64" height="30" rx="12" fill="#0d0f1a" opacity=".28"/>`;
      case 'cat': return `<g class="av-ears"><path d="M24 46 L28 12 L52 30Z" fill="${F.dark}"/><path d="M96 46 L92 12 L68 30Z" fill="${F.dark}"/>
        <path d="M30 40 L31 22 L45 32Z" fill="#ff8ab3" opacity=".6"/><path d="M90 40 L89 22 L75 32Z" fill="#ff8ab3" opacity=".6"/></g>
        <circle cx="60" cy="62" r="42" fill="${F.fill}"/>
        <g stroke="#0d0f1a" stroke-width="1.4" opacity=".45" stroke-linecap="round"><path d="M26 74 L12 70M26 79 L12 82M94 74 L108 70M94 79 L108 82"/></g>`;
      case 'ghost': return `<path d="M18 64 Q18 18 60 18 Q102 18 102 64 L102 104 Q95 96 88 104 Q81 112 74 104 Q67 96 60 104 Q53 112 46 104 Q39 96 32 104 Q25 112 18 104Z" fill="${F.fill}"/>
        <path class="av-hem" d="M20 92 Q32 104 46 92 Q60 80 74 92 Q88 104 100 92" fill="none" stroke="${F.dark}" stroke-width="4" stroke-linecap="round"/>`;
      case 'square': return `<rect x="16" y="22" width="88" height="82" rx="22" fill="${F.fill}"/>`;
      case 'bunny': return `<g class="av-ears"><ellipse cx="42" cy="22" rx="9" ry="24" fill="${F.dark}" transform="rotate(-12 42 40)"/><ellipse cx="78" cy="22" rx="9" ry="24" fill="${F.dark}" transform="rotate(12 78 40)"/>
        <ellipse cx="42" cy="24" rx="4" ry="16" fill="#ff8ab3" opacity=".55" transform="rotate(-12 42 40)"/><ellipse cx="78" cy="24" rx="4" ry="16" fill="#ff8ab3" opacity=".55" transform="rotate(12 78 40)"/></g>
        <circle cx="60" cy="66" r="38" fill="${F.fill}"/>`;
      case 'spark': return `<circle class="av-sp" cx="104" cy="24" r="5" fill="${F.dark}"/><circle class="av-sp" cx="16" cy="34" r="3.5" fill="${F.dark}"/>
        <path d="M60 18 Q84 22 98 44 Q108 66 94 88 Q78 106 56 104 Q30 102 20 80 Q12 56 26 36 Q40 18 60 18Z" fill="${F.fill}"/>`;
      case 'fox': return `<g class="av-ears"><path d="M22 48 L30 8 L54 34Z" fill="${F.dark}"/><path d="M98 48 L90 8 L66 34Z" fill="${F.dark}"/>
        <path d="M28 42 L32 18 L46 34Z" fill="#ff8ab3" opacity=".55"/><path d="M92 42 L88 18 L74 34Z" fill="#ff8ab3" opacity=".55"/></g>
        <ellipse cx="60" cy="68" rx="40" ry="36" fill="${F.fill}"/>
        <path d="M48 90 L60 102 L72 90Z" fill="${F.dark}"/>`;
      case 'bear': return `<g class="av-ears"><circle cx="28" cy="34" r="16" fill="${F.dark}"/><circle cx="92" cy="34" r="16" fill="${F.dark}"/>
        <circle cx="28" cy="34" r="8" fill="#ff8ab3" opacity=".5"/><circle cx="92" cy="34" r="8" fill="#ff8ab3" opacity=".5"/></g>
        <circle cx="60" cy="66" r="40" fill="${F.fill}"/>
        <ellipse cx="60" cy="88" rx="14" ry="9" fill="${F.dark}" opacity=".55"/>`;
      case 'owl': return `<g class="av-ears"><path d="M30 40 L36 12 L50 36Z" fill="${F.dark}"/><path d="M90 40 L84 12 L70 36Z" fill="${F.dark}"/></g>
        <ellipse cx="60" cy="66" rx="38" ry="42" fill="${F.fill}"/>
        <path d="M54 88 L60 98 L66 88Z" fill="#e2a23a"/>`;
      case 'alien': return `<g class="av-antenna"><line x1="48" y1="28" x2="40" y2="8" stroke="${F.dark}" stroke-width="3"/><circle class="av-bulb" cx="38" cy="6" r="5" fill="#7dffb3"/>
        <line x1="72" y1="28" x2="80" y2="8" stroke="${F.dark}" stroke-width="3"/><circle class="av-bulb" cx="82" cy="6" r="5" fill="#7dffb3"/></g>
        <ellipse cx="60" cy="70" rx="34" ry="40" fill="${F.fill}"/>`;
      case 'dino': return `<circle class="av-sp" cx="34" cy="20" r="6" fill="${F.dark}"/><circle class="av-sp" cx="60" cy="12" r="7" fill="${F.dark}"/><circle class="av-sp" cx="86" cy="20" r="6" fill="${F.dark}"/>
        <ellipse cx="60" cy="70" rx="40" ry="34" fill="${F.fill}"/>
        <path d="M96 78 Q114 68 108 98 Q96 90 90 82Z" fill="${F.dark}"/>`;
      case 'panda': return `<g class="av-ears"><circle cx="26" cy="34" r="16" fill="#1a1c24"/><circle cx="94" cy="34" r="16" fill="#1a1c24"/></g>
        <circle cx="60" cy="66" r="40" fill="${F.fill}"/>
        <ellipse cx="40" cy="64" rx="14" ry="16" fill="#1a1c24" opacity=".85"/><ellipse cx="80" cy="64" rx="14" ry="16" fill="#1a1c24" opacity=".85"/>`;
      case 'frog': return `<g class="av-ears"><circle cx="32" cy="32" r="16" fill="${F.dark}"/><circle cx="88" cy="32" r="16" fill="${F.dark}"/></g>
        <ellipse cx="60" cy="76" rx="44" ry="30" fill="${F.fill}"/>
        <ellipse cx="60" cy="90" rx="18" ry="8" fill="${F.dark}" opacity=".35"/>`;
      case 'chick': return `<g class="av-antenna"><path d="M48 32 Q60 6 72 32 Q60 18 48 32Z" fill="#ffb020"/></g>
        <circle cx="60" cy="68" r="38" fill="${F.fill}"/>
        <path d="M52 88 L60 98 L68 88Z" fill="#e2a23a"/>`;
      case 'octopus': return `<ellipse cx="60" cy="50" rx="36" ry="30" fill="${F.fill}"/>
        <g class="av-hem"><path d="M28 68 Q20 98 34 110" fill="none" stroke="${F.dark}" stroke-width="5" stroke-linecap="round"/>
        <path d="M44 74 Q38 104 50 114" fill="none" stroke="${F.fill}" stroke-width="5" stroke-linecap="round"/>
        <path d="M60 78 Q66 110 58 116" fill="none" stroke="${F.dark}" stroke-width="5" stroke-linecap="round"/>
        <path d="M76 74 Q84 104 72 114" fill="none" stroke="${F.fill}" stroke-width="5" stroke-linecap="round"/>
        <path d="M92 68 Q102 98 86 110" fill="none" stroke="${F.dark}" stroke-width="5" stroke-linecap="round"/></g>`;
      case 'star': return `<circle class="av-sp" cx="16" cy="26" r="3.5" fill="${F.dark}"/><circle class="av-sp" cx="106" cy="20" r="4" fill="${F.dark}"/>
        <path d="M60 12 L72 44 L106 48 L80 70 L88 104 L60 84 L32 104 L40 70 L14 48 L48 44Z" fill="${F.fill}"/>`;
      default: return `<circle cx="60" cy="62" r="42" fill="${F.fill}"/>`;
    }
  }
  let uid = 0;
  // Flat, matte look: solid fills, huge round cartoon eyes, no gloss, highlights or sparkle.
  function svg(shape, color, id) {
    const F = { fill: color, dark: mix(color, 0, 0.35), soft: mix(color, 0, 0.18) };
    const eye = (x) => `<g class="av-eye" transform="translate(${x} 60)"><g class="av-pup"><ellipse class="av-ball" rx="11" ry="13" fill="#15171d"/></g>
      <path class="av-happy" d="M-10 3 Q0 -9 10 3" fill="none" stroke="#15171d" stroke-width="4" stroke-linecap="round" opacity="0"/></g>`;
    return `<svg viewBox="0 0 120 120" class="av-svg" aria-hidden="true">
      <circle class="av-ring" cx="60" cy="60" r="56" fill="none" stroke="${F.soft}" stroke-width="3" opacity=".7"/>
      <g class="av-body">${body(shape, F)}
        <g class="av-face">${eye(42)}${eye(78)}
        <path class="av-mouth" d="M49 77 Q60 84 71 77 Q60 87 49 77Z" fill="#15171d"/>
        <ellipse class="av-blush" cx="27" cy="78" rx="6" ry="3.5" fill="#ff8ab3" opacity=".45"/><ellipse class="av-blush" cx="93" cy="78" rx="6" ry="3.5" fill="#ff8ab3" opacity=".45"/></g></g>
      <g class="av-dots"><circle cx="96" cy="26" r="3"/><circle cx="104" cy="18" r="2.2"/><circle cx="110" cy="10" r="1.6"/></g></svg>`;
  }

  const live = new Set(); let loopOn = false; let last = 0;
  const mouse = { x: -1, y: -1, t: 0 };
  const reduced = typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (typeof addEventListener === 'function') {
    addEventListener('pointermove', (e) => { mouse.x = e.clientX; mouse.y = e.clientY; mouse.t = performance.now(); }, { passive: true });
    document.addEventListener('visibilitychange', () => { if (!document.hidden) kick(); });
  }
  function kick() { if (!loopOn && live.size) { loopOn = true; requestAnimationFrame(loop); } }
  function loop(now) {
    if ((typeof document !== 'undefined' && document.hidden) || !live.size) { loopOn = false; return; }
    const dt = Math.min(0.05, last ? (now - last) / 1000 : 0.016);
    last = now;
    live.forEach((a) => a.tick(now, dt));
    requestAnimationFrame(loop);
  }
  const approach = (a, b, dt, tau) => a + (b - a) * (1 - Math.exp(-Math.max(0, dt) / tau));

  function createAvatar(el, opts) {
    opts = opts || {}; const id = ++uid;
    let color = opts.color || '#5b6cff', shape = SHAPES.includes(opts.shape) ? opts.shape : 'round';
    let state = 'idle', level = 0, target = 0, real = false, doneUntil = 0;
    let parts = null;
    const s = { px: 0, py: 0, tx: 0, ty: 0, tilt: 0, ttilt: 0, bob: 0, open: 1, happy: 0, thappy: 0,
      nextLook: 0, nextBlink: 0, blinkT: -1, nextTilt: 0, nextCute: 0, cuteT: -1, squash: 1, see: 0, off: false, box: null };
    function build() {
      el.innerHTML = svg(shape, color, id); if (el.dataset) el.dataset.shape = shape;
      const q = (c) => (el.querySelectorAll ? Array.from(el.querySelectorAll(c)) : []);
      const one = (c) => (el.querySelector ? el.querySelector(c) : null);
      parts = { body: one('.av-body'), face: one('.av-face'), pup: q('.av-pup'), ball: q('.av-ball'), happy: q('.av-happy'), mouth: one('.av-mouth'), ears: one('.av-ears'), antenna: one('.av-antenna'), hem: one('.av-hem'), sparks: q('.av-sp') };
    }
    el.classList.add('avatar', 'idle'); build();
    const api = {
      tick(now, dt) {
        if (el.isConnected === false) { live.delete(api); return; }
        if (typeof el.getBoundingClientRect === 'function') {
          if ((s.see = (s.see + 1) % 6) === 1) {
            const box = el.getBoundingClientRect();
            const view = typeof innerHeight === 'number' ? innerHeight : 800;
            s.off = box.width < 1 || box.bottom < -40 || box.top > view + 40;
            s.box = box;
          }
          if (s.off) return;
        }
        const r = s.box;
        const st = (state === 'idle' && now < doneUntil) ? 'done' : state;
        // gaze: follow a recently moved cursor, else wander
        if (st === 'thinking') { s.tx = 2.6; s.ty = -3.2; }
        else if (st === 'working') { s.tx = Math.sin(now / 420) * 2.4; s.ty = 1.6; }
        else if (r && now - mouse.t < 1800 && mouse.x >= 0) {
          const dx = mouse.x - (r.left + r.width / 2), dy = mouse.y - (r.top + r.height / 2), d = Math.hypot(dx, dy) || 1, m = Math.min(1, d / 220);
          s.tx = dx / d * 3.4 * m; s.ty = dy / d * 3.4 * m;
        } else if (now > s.nextLook) { s.tx = (Math.random() * 2 - 1) * 3; s.ty = (Math.random() * 2 - 1) * 2.2; s.nextLook = now + 700 + Math.random() * 1800; }
        s.px = approach(s.px, s.tx, dt, 0.07); s.py = approach(s.py, s.ty, dt, 0.07);
        // blink
        if (s.blinkT < 0 && now > s.nextBlink) { s.blinkT = 0; s.nextBlink = now + 2200 + Math.random() * 3800; }
        if (s.blinkT >= 0) { s.blinkT += dt; const k = s.blinkT / 0.12; s.open = k < 1 ? Math.abs(1 - 2 * k) : 1; if (k >= 1) { s.blinkT = -1; s.open = 1; } }
        const squint = st === 'working' ? 0.62 : 1;
        // head tilt, nod, and bob
        if (st === 'done') {
          const p = 1 - Math.max(0, doneUntil - now) / 1700;
          s.ttilt = Math.sin(Math.min(1, p) * Math.PI) * 16;
        } else if (st === 'thinking') s.ttilt = -9;
        else if (st === 'working') s.ttilt = Math.sin(now / 520) * 3;
        else if (now > s.nextTilt) { s.ttilt = Math.random() < 0.45 ? (Math.random() < 0.5 ? -7 : 7) : 0; s.nextTilt = now + 1400 + Math.random() * 2800; }
        s.tilt = approach(s.tilt, s.ttilt, dt, st === 'done' ? 0.06 : 0.1);
        const bobAmp = st === 'done' ? 5 : st === 'speaking' ? 1.6 : st === 'working' ? 0.8 : 1.2;
        const bobSpd = st === 'done' ? 140 : 420;
        s.bob = st === 'done' ? -Math.abs(Math.sin(now / bobSpd)) * bobAmp : Math.sin(now / bobSpd) * bobAmp;
        s.squash = approach(s.squash, 1, dt, 0.07);
        // cute moments: happy squint now and then
        s.thappy = st === 'done' ? 1 : 0;
        if (st === 'idle') { if (s.cuteT < 0 && now > s.nextCute) { s.cuteT = 0; s.nextCute = now + 7000 + Math.random() * 9000; } }
        if (s.cuteT >= 0) { s.cuteT += dt; s.thappy = 1; if (s.cuteT > 1.1) s.cuteT = -1; }
        s.happy = approach(s.happy, s.thappy, dt, 0.1);
        if (parts.body && parts.body.setAttribute) {
          const sy = s.squash.toFixed(3);
          parts.body.setAttribute('transform', `translate(0 ${s.bob.toFixed(2)}) rotate(${s.tilt.toFixed(2)} 60 66) translate(60 66) scale(1 ${sy}) translate(-60 -66)`);
        }
        const op = (s.open * squint * (1 - s.happy)).toFixed(3);
        parts.pup.forEach((p) => p.setAttribute && p.setAttribute('transform', `translate(${s.px.toFixed(2)} ${s.py.toFixed(2)}) scale(1 ${Math.max(0.06, op)})`));
        parts.happy.forEach((p) => p.setAttribute && p.setAttribute('opacity', s.happy.toFixed(2)));
        if (parts.ears && parts.ears.setAttribute) {
          const twitch = (st === 'listening' ? level * 8 : 0) + Math.sin(now / 240) * (st === 'idle' || st === 'listening' ? 2.2 : 0.4);
          parts.ears.setAttribute('transform', `rotate(${twitch.toFixed(2)} 60 42)`);
        }
        if (parts.antenna && parts.antenna.setAttribute) {
          const flick = st === 'working' ? Math.sin(now / 90) * 12 : Math.sin(now / 380) * 4;
          parts.antenna.setAttribute('transform', `rotate(${flick.toFixed(2)} 60 24)`);
        }
        if (parts.hem && parts.hem.setAttribute) {
          parts.hem.setAttribute('transform', `translate(${(Math.sin(now / 280) * 3).toFixed(2)} 0)`);
        }
        parts.sparks.forEach((p, i) => {
          if (!p.setAttribute) return;
          const a = now / 360 + i * 2.2;
          p.setAttribute('transform', `translate(${(Math.cos(a) * (4 + i)).toFixed(2)} ${(Math.sin(a) * (3 + i)).toFixed(2)})`);
        });
        // mouth follows the real voice, the mic, or a sharp syllable shape
        if (st === 'speaking') {
          if (!real) target = 0.08 + 0.78 * Math.pow(Math.abs(Math.sin(now / 68) * Math.sin(now / 29 + 0.6)), 1.4);
        } else if (st === 'listening') {
          if (!real) target = 0.06 + 0.08 * Math.abs(Math.sin(now / 180));
        } else target = 0;
        level = approach(level, target, dt, 0.045);
        const smile = st === 'done' || s.happy > 0.5 ? 5 : st === 'thinking' ? -2 : 0;
        const w = 8 - level * 2, up = 84 - level * 4 - (st === 'thinking' ? 4 : 0), low = 88 + level * 12 + smile;
        if (parts.mouth && parts.mouth.setAttribute) parts.mouth.setAttribute('d', `M${(60 - w).toFixed(1)} 80 Q60 ${up.toFixed(1)} ${(60 + w).toFixed(1)} 80 Q60 ${low.toFixed(1)} ${(60 - w).toFixed(1)} 80Z`);
      },
      setState(n) {
        if (n === state) return;
        s.squash = 1.16;
        if (n === 'idle' && (state === 'thinking' || state === 'working' || state === 'speaking')) doneUntil = performance.now() + 1700;
        el.classList.remove(state); state = n; el.classList.add(n); if (n !== 'speaking' && n !== 'listening') real = false;
      },
      setLevel(v) { real = true; target = Math.max(0, Math.min(1, +v || 0)); },
      setLook(c, sh) { color = c || color; shape = SHAPES.includes(sh) ? sh : 'round'; build(); if (reduced) api.tick(performance.now(), 0); },
      celebrate() { doneUntil = performance.now() + 1600; },
      get state() { return state; },
      destroy() { live.delete(api); },
    };
    if (reduced) { requestAnimationFrame(() => api.tick(performance.now(), 0)); }
    else { live.add(api); kick(); }
    return api;
  }
  createAvatar.SHAPES = SHAPES; createAvatar.LABELS = LABELS; createAvatar.svg = svg;
  if (typeof module !== 'undefined' && module.exports) module.exports = { createAvatar, SHAPES, svg };
  else root.createAvatar = createAvatar;
})(this);
