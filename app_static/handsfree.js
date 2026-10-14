// Hands-free voice controller for the Pedro_Agent chat window.
// Pure logic (no DOM) so it can be tested with node: tests/test_handsfree.js.
//
// Rules:
//  - listen() never runs twice at once, and the "listening" flag is reset in
//    finally on every path (speech, silence, error, network failure).
//  - After a turn (reply + speech finished, failed, or skipped) turnEnded()
//    restarts listening when hands-free is on.
//  - A watchdog restarts listening if hands-free is on and nothing has been
//    happening (not listening, no turn running) for more than idleMs (2 s).
//  - Silence just listens again. Errors are reported and retried with a
//    short backoff so a flaky mic does not stop hands-free for good.
(function (root) {
  function createHandsFree(opts) {
    const o = Object.assign({ idleMs: 2000, tickMs: 500, now: () => Date.now(),
      setInterval: (f, ms) => setInterval(f, ms), clearInterval: (t) => clearInterval(t),
      setTimeout: (f, ms) => setTimeout(f, ms) }, opts);
    const s = { enabled: false, listening: false, turnRunning: false,
      idleSince: o.now(), errors: 0, timer: null, retryAt: 0 };

    function markIdle() { s.idleSince = o.now(); }

    async function listen(manual) {
      if (s.listening) return;
      if (s.turnRunning && !manual) return;
      s.listening = true;
      o.onState && o.onState('listening');
      let r = null;
      try {
        r = await o.listenApi();
      } catch (e) {
        r = { ok: false, kind: 'error', error: (e instanceof SyntaxError || /JSON|Unexpected token/.test(String(e && e.message))) ? 'Your PC app is restarting or the sign-in expired, try again in a few seconds' : 'Could not reach the app: ' + (e && e.message || e) };
      } finally {
        s.listening = false;
        markIdle();
        o.onState && o.onState('idle');
      }
      if (r && r.ok && r.text) {
        s.errors = 0;
        o.onText(r.text);
        return;
      }
      if (r && r.kind === 'error' || r && r.kind === 'busy') {
        s.errors += 1;
        o.onError && o.onError(r.error || 'Microphone error');
        s.retryAt = o.now() + Math.min(1000 * s.errors, 5000);
        return;  // watchdog retries after the backoff
      }
      s.errors = 0;
      o.onSilence && o.onSilence();
      if (s.enabled && !s.turnRunning) o.setTimeout(() => listen(false), 150);
    }

    function tick() {
      if (!s.enabled || s.listening || s.turnRunning) return;
      if (o.now() < s.retryAt) return;
      if (o.now() - s.idleSince > o.idleMs) listen(false);
    }

    return {
      state: s,
      listen,
      tick,
      setEnabled(on) {
        s.enabled = !!on;
        if (s.timer) { o.clearInterval(s.timer); s.timer = null; }
        if (s.enabled) {
          s.timer = o.setInterval(tick, o.tickMs);
          if (!s.turnRunning) listen(false);
        }
      },
      turnStarted() { s.turnRunning = true; },
      turnEnded() {
        s.turnRunning = false;
        markIdle();
        if (s.enabled) listen(false);
      },
    };
  }
  if (typeof module !== 'undefined' && module.exports) module.exports = { createHandsFree };
  else root.createHandsFree = createHandsFree;
})(this);
