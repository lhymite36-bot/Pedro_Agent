// Run: node tests/test_ui.js  (also run by tests/test_upgrade.py)
const assert = require('assert');
const { render } = require('../app_static/markdown.js');

// XSS: raw HTML is escaped everywhere
assert.ok(!render('<img src=x onerror=alert(1)>').includes('<img'));
assert.ok(!render('[x](javascript:alert(1))').includes('href="javascript'));
assert.ok(!render('```\n<script>bad()</script>\n```').includes('<script>'));
// features
assert.ok(render('**b** and *i* and `c`').includes('<strong>b</strong>'));
assert.ok(render('**b** and *i* and `c`').includes('<em>i</em>'));
assert.ok(render('**b** and *i* and `c`').includes('<code>c</code>'));
const code = render('```python\nprint(1)\n```');
assert.ok(code.includes('class="code"') && code.includes('python') && code.includes('print(1)'));
assert.ok(render('- a\n- b').includes('<ul><li>a</li><li>b</li></ul>'));
assert.ok(render('1. a\n2. b').startsWith('<ol>'));
assert.ok(render('see https://example.com now').includes('href="https://example.com"'));
assert.ok(render('# Title').includes('<h3>Title</h3>'));

// avatar state machine with a minimal DOM stub
global.requestAnimationFrame = () => 1; global.cancelAnimationFrame = () => {};
const { createAvatar } = require('../app_static/avatar.js');
const classes = new Set(); let mouthD = '';
const el = { set innerHTML(v) { this._h = v; }, classList: { add: (...c) => c.forEach((x) => classes.add(x)), remove: (c) => classes.delete(c) },
  querySelector: () => ({ setAttribute: (k, v) => { mouthD = v; } }) };
const av = createAvatar(el);
assert.ok(el._h.includes('<svg') && classes.has('idle'));
for (const s of ['listening', 'thinking', 'speaking', 'idle']) { av.setState(s); assert.strictEqual(av.state, s); assert.ok(classes.has(s)); }
assert.strictEqual(classes.has('speaking'), false);
for (const s of ['working', 'idle']) { av.setState(s); assert.strictEqual(av.state, s); }
assert.ok(el._h.includes('avg'));
const kinds = new Set(require('../app_static/avatar.js').SHAPES.map((sh) => { const e2 = { set innerHTML(v) { this._h = v; }, classList: { add() {}, remove() {} }, querySelector: () => ({ setAttribute() {} }) }; createAvatar(e2, { shape: sh, color: '#ff0000' }); assert.ok(e2._h.includes('#ff0000')); return e2._h; }));
assert.ok(kinds.size >= 5, 'at least 5 distinct characters');
console.log('ui js: all tests passed');

// ---- bots_ui helpers ----
{
  const assert = require('assert');
  const B = require('../app_static/bots_ui.js');
  assert.strictEqual(B.hueShift('#7c8cff'), 0);
  assert.ok(B.hueShift('#ff0000') > 100);
  assert.strictEqual(B.scheduleLabel({ schedule: null }), 'one-off');
  assert.strictEqual(B.scheduleLabel({ schedule: { every_minutes: 5 } }), 'every 5 min');
  assert.strictEqual(B.scheduleLabel({ schedule: { daily: '08:00' } }), 'daily 08:00');
  console.log('bots_ui ok');
}

// ---- live_ui helpers ----
{
  const assert = require('assert');
  const L = require('../app_static/live_ui.js');
  assert.strictEqual(L.clampFps(10, 5), 5);
  assert.strictEqual(L.clampFps('x', 5), 3);
  const p = L.normPoint(150, 100, { left: 100, top: 50, width: 200, height: 100 });
  assert.deepStrictEqual(p, { x: 0.25, y: 0.5 });
  assert.deepStrictEqual(L.normPoint(0, 0, { left: 100, top: 50, width: 200, height: 100 }), { x: 0, y: 0 });
  assert.strictEqual(L.ago(100, 130), '30s');
  console.log('live_ui ok');
}
