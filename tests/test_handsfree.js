// Run: node tests/test_handsfree.js  (also run by tests/test_upgrade.py)
const assert = require('assert');
const { createHandsFree } = require('../app_static/handsfree.js');

function harness(results) {
  let t = 0; const timeouts = []; const log = { texts: [], errors: [], calls: 0 };
  const hf = createHandsFree({
    now: () => t, setInterval: () => 1, clearInterval: () => {},
    setTimeout: (f) => timeouts.push(f),
    listenApi: async () => { log.calls++; const r = results.shift(); if (r instanceof Error) throw r; return r || { ok: false, kind: 'silence' }; },
    onText: (x) => log.texts.push(x), onError: (e) => log.errors.push(e),
  });
  return { hf, log, timeouts, advance: (ms) => { t += ms; } };
}
const flush = () => new Promise((r) => setImmediate(r));

(async () => {
  // 1. First phrase, reply, then it listens again for the second phrase.
  let h = harness([{ ok: true, text: 'one', kind: 'speech' }, { ok: true, text: 'two', kind: 'speech' }]);
  h.hf.setEnabled(true); await flush();
  assert.deepStrictEqual(h.log.texts, ['one']);
  h.hf.turnStarted(); h.hf.turnEnded(); await flush();
  assert.deepStrictEqual(h.log.texts, ['one', 'two'], 'relistens after the turn');

  // 2. Silence: listens again immediately, flag reset.
  h = harness([{ ok: false, kind: 'silence', error: 'No speech heard.' }, { ok: true, text: 'hi' }]);
  h.hf.setEnabled(true); await flush();
  assert.strictEqual(h.hf.state.listening, false);
  h.timeouts.shift()(); await flush();
  assert.deepStrictEqual(h.log.texts, ['hi']);

  // 3. Error is surfaced, flag reset, watchdog retries after backoff.
  h = harness([{ ok: false, kind: 'error', error: 'Microphone access failed' }, { ok: true, text: 'back' }]);
  h.hf.setEnabled(true); await flush();
  assert.deepStrictEqual(h.log.errors, ['Microphone access failed']);
  assert.strictEqual(h.hf.state.listening, false);
  h.advance(500); h.hf.tick(); await flush();
  assert.strictEqual(h.log.calls, 1, 'waits for backoff');
  h.advance(2600); h.hf.tick(); await flush();
  assert.deepStrictEqual(h.log.texts, ['back']);

  // 4. Network failure (fetch throws) still resets and reports.
  h = harness([new Error('Failed to fetch')]);
  h.hf.setEnabled(true); await flush();
  assert.strictEqual(h.hf.state.listening, false);
  assert.ok(h.log.errors[0].includes('Failed to fetch'));

  // 5. Watchdog: idle > 2 s with hands-free on restarts listening, but not during a turn.
  h = harness([{ ok: true, text: 'a' }, { ok: true, text: 'b' }]);
  h.hf.setEnabled(true); await flush();
  h.hf.turnStarted(); h.advance(5000); h.hf.tick(); await flush();
  assert.strictEqual(h.log.calls, 1, 'no listening while a turn runs');
  h.hf.state.turnRunning = false;            // turn end event lost
  h.hf.tick(); await flush();
  assert.deepStrictEqual(h.log.texts, ['a', 'b'], 'watchdog recovered');

  // 6. Hands-free off: no relisten.
  h = harness([{ ok: true, text: 'x' }]);
  h.hf.listen(true); await flush(); h.hf.turnStarted(); h.hf.turnEnded(); h.advance(9999); h.hf.tick(); await flush();
  assert.strictEqual(h.log.calls, 1);

  // 7. No double listen.
  h = harness([]);
  h.hf.listen(true); h.hf.listen(true); await flush();
  assert.strictEqual(h.log.calls, 1);
  console.log('handsfree.js: all tests passed');
})().catch((e) => { console.error(e); process.exit(1); });
