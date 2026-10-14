// Pedro_Agent chat window. Plain JS, no external libraries.
const $ = (s) => document.querySelector(s);
const $$ = (s) => Array.from(document.querySelectorAll(s));
const urlSession = new URLSearchParams(location.search).get('session');
// Friendly handling when the PC app is restarting or the sign-in expired (browser only;
// the Android app injects its own wrapper that signs in again automatically).
if (!/PedroAgentApp/.test(navigator.userAgent)) {
  const rawFetch = window.fetch.bind(window);
  window.fetch = async (u, o) => {
    const r = await rawFetch(u, o);
    const url = String((u && u.url) || u); const ct = r.headers.get('content-type') || '';
    if (url.indexOf('/api') >= 0 && (r.status === 401 || ct.indexOf('text/html') >= 0 || (r.status >= 500 && ct.indexOf('json') < 0))) {
      const local = /^(127\.0\.0\.1|localhost)$/.test(location.hostname);
      if (r.status === 401 && !local) { setTimeout(() => { location.href = '/login'; }, 1500); throw new Error('Your sign-in expired, opening the sign-in page'); }
      throw new Error('Your PC app is restarting or unreachable, try again in a few seconds');
    }
    return r;
  };
}
let session = urlSession || localStorage.session || '';
let running = false;
let speakOn = false; let speakMode = 'voice';
// Phone app: the Android shell calls window.__pedroHeard(text) after speech
// recognition. Wrap whatever it installs so that message is marked as voice.
let nextIsVoice = false;
(function () {
  let fn = window.__pedroHeard;
  try {
    Object.defineProperty(window, '__pedroHeard', {
      configurable: true,
      get() { return fn ? function (t) { if (t) nextIsVoice = true; return fn.apply(this, arguments); } : undefined; },
      set(v) { fn = v; },
    });
  } catch (e) {}
})();
// Browser audio for spoken replies (phone / remote). Unlock on the first tap
// so later replies can autoplay.
const voiceAudio = new Audio(); voiceAudio.preload = 'auto';
// a few ms of silence, built at runtime (used once to unlock autoplay)
const SILENT = (() => { const n = 800, b = new ArrayBuffer(44 + n * 2), v = new DataView(b), w = (o, t) => { for (let i = 0; i < t.length; i++) v.setUint8(o + i, t.charCodeAt(i)); };
  w(0, 'RIFF'); v.setUint32(4, 36 + n * 2, true); w(8, 'WAVEfmt '); v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true);
  v.setUint32(24, 8000, true); v.setUint32(28, 16000, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true); w(36, 'data'); v.setUint32(40, n * 2, true);
  try { return URL.createObjectURL(new Blob([b], { type: 'audio/wav' })); } catch (e) { return ''; } })();
let audioUnlocked = false;
function unlockAudio() { if (audioUnlocked) return; audioUnlocked = true; try { voiceAudio.src = SILENT; const p = voiceAudio.play(); if (p) p.catch(() => { audioUnlocked = false; }); } catch (e) {} }
['pointerdown', 'touchstart', 'keydown'].forEach((n) => document.addEventListener(n, unlockAudio, { capture: true }));
function playClip(url) {
  return new Promise((resolve) => {
    let finished = false; const end = () => { if (finished) return; finished = true; setMood('idle'); resolve(); };
    voiceAudio.onended = end; voiceAudio.onerror = end; voiceAudio.src = url;
    setMood('speaking');
    const p = voiceAudio.play();
    if (p) p.catch(() => { setStatus('Tap anywhere to allow voice replies, then try again.', true); end(); });
  });
}
function stopClip() { try { voiceAudio.pause(); } catch (e) {} }
function willSpeak(isVoice) { return speakMode === 'always' || (speakMode === 'voice' && isVoice); }
const avatars = [createAvatar($('#hdr-avatar')), createAvatar($('#brand-avatar')), createAvatar($('#empty-avatar'))];
const MOODS = { idle: 'Idle', listening: 'Listening…', thinking: 'Thinking…', working: 'Working…', speaking: 'Speaking…' };
let rowFace = null; // avatar of the reply being produced
window.mainAvatars = avatars;
function setMood(state) {
  avatars.forEach((a) => a.setState(state));
  $('#mood').textContent = MOODS[state] || state;
  if (rowFace) rowFace.setState(state);
  levelPoll(state === 'speaking');
}
// Real TTS loudness: poll /api/level fast only while speaking.
let levelTimer = null; let levelBusy = false;
function levelPoll(on) {
  clearInterval(levelTimer); levelTimer = null;
  if (!on) return;
  levelTimer = setInterval(async () => {
    if (levelBusy) return; levelBusy = true;
    try {
      const r = await (await fetch('/api/level')).json();
      if (typeof r.level === 'number') { avatars.forEach((a) => a.setLevel(r.level)); if (rowFace) rowFace.setLevel(r.level); }
    } catch (e) { /* server busy; keep synthetic motion */ } finally { levelBusy = false; }
  }, 60);
}
function botFace() {
  const d = document.createElement('div'); d.className = 'face';
  const look = (window.currentBotLook && window.currentBotLook()) || {};
  d._av = createAvatar(d, look); return d;
}
// Stage directions like [chuckles] are for the voice only.
const STAGE = /\s*[\[(](?:chuckles?|laughs?|laughing|giggles?|sighs?|smiles?|grins?|winks?|gasps?|whispers?|clears throat|pause|sarcastic(?:ally)?|excited(?:ly)?|cheerful(?:ly)?|softly|happily|sadly|snorts?|hums?|coughs?)[\])]\s*/gi;
function stripStage(t) { return String(t || '').replace(STAGE, ' ').replace(/ {2,}/g, ' ').replace(/^ +/gm, ''); }

// ---------- rendering ----------
function scrollDown() { const l = $('#log'); l.scrollTop = l.scrollHeight; }
function showEmpty() { $('#empty').classList.toggle('hidden', $('#log').children.length > 0); }
function addUser(text) {
  const row = document.createElement('div'); row.className = 'row user';
  const b = document.createElement('div'); b.className = 'bubble'; b.textContent = text;
  row.appendChild(b); $('#log').appendChild(row); showEmpty(); scrollDown();
}
function addBot() {
  const row = document.createElement('div'); row.className = 'row bot';
  row.appendChild(botFace());
  const col = document.createElement('div'); col.className = 'bubble';
  const chips = document.createElement('div'); chips.className = 'chips';
  const body = document.createElement('div'); body.className = 'md';
  col.append(chips, body); row.appendChild(col); $('#log').appendChild(row); showEmpty(); scrollDown();
  return { row, chips, body, text: '' };
}
function renderMd(el, text, streaming) {
  el.innerHTML = Markdown.render(stripStage(text));
  el.classList.toggle('caret', !!streaming);
}
// Live activity line (Grok Bot style) + collapsible finished steps.
// Live task checklist (create_task_plan / complete_plan_step / revise_task_plan).
function renderPlan(bot, ev) {
  const col = bot.body.parentNode; let box = col.querySelector('.plan');
  if (!box) { box = document.createElement('div'); box.className = 'plan'; col.insertBefore(box, bot.body); }
  box.innerHTML = '';
  const g = document.createElement('div'); g.className = 'plan-goal'; g.textContent = ev.goal || 'Plan'; box.appendChild(g);
  (ev.steps || []).forEach((st) => {
    const r = document.createElement('div'); r.className = 'plan-step ' + (st.status || 'pending');
    const m = document.createElement('i'); m.textContent = st.status === 'done' ? '✓' : st.status === 'blocked' ? '!' : '○';
    const t = document.createElement('span'); t.textContent = st.number + '. ' + st.text; r.append(m, t); box.appendChild(r);
  });
  scrollDown();
}
function activity(bubble) {
  const a = document.createElement('div'); a.className = 'activity';
  a.innerHTML = '<i class="orb"></i><div class="lbl"></div>';
  bubble.insertBefore(a, bubble.firstChild);
  const lbl = a.querySelector('.lbl'); let cur = null; const done = []; let t0 = performance.now(); let ended = false;
  const api = {
    set(text) {
      if (cur && cur.textContent === text) return;
      const n = document.createElement('span'); n.className = 'in'; n.textContent = text; lbl.appendChild(n);
      requestAnimationFrame(() => requestAnimationFrame(() => n.classList.remove('in')));
      if (cur) { const o = cur; o.classList.add('out'); setTimeout(() => o.remove(), 400); }
      cur = n;
    },
    finish(text, ok) { if (text && text !== 'Thinking…') done.push({ text, ok: ok !== false }); },
    end() {
      if (ended) return; ended = true; a.remove();
      if (!done.length) return;
      const d = document.createElement('details'); d.className = 'steps';
      const secs = Math.max(1, Math.round((performance.now() - t0) / 1000));
      d.innerHTML = '<summary></summary><ol></ol>';
      d.querySelector('summary').textContent = done.length + (done.length === 1 ? ' step' : ' steps') + ' · ' + secs + 's';
      done.forEach((s) => { const li = document.createElement('li'); li.textContent = s.text; if (!s.ok) li.className = 'bad'; d.querySelector('ol').appendChild(li); });
      bubble.insertBefore(d, bubble.querySelector('.md'));
    },
  };
  api.set('Thinking…'); return api;
}
function chip(container, name) {
  const c = document.createElement('span'); c.className = 'chip';
  c.innerHTML = '<i class="s"></i><b></b><span class="d"></span>';
  c.querySelector('b').textContent = name.replace(/_/g, ' ');
  container.appendChild(c); scrollDown(); return c;
}
function addImage(container, path) {
  const img = document.createElement('img'); img.className = 'thumb'; img.alt = 'preview';
  img.src = '/api/image?path=' + encodeURIComponent(path) + '&t=' + Date.now();
  img.onclick = () => { $('#lightbox img').src = img.src; $('#lightbox').classList.add('open'); };
  container.appendChild(img); scrollDown();
}
function addError(container, text) {
  const e = document.createElement('div'); e.className = 'err'; e.textContent = text; container.appendChild(e); scrollDown();
}
document.addEventListener('click', (e) => {
  if (e.target.classList.contains('copy')) {
    const code = e.target.closest('.code').querySelector('code').textContent;
    navigator.clipboard && navigator.clipboard.writeText(code);
    e.target.textContent = 'Copied'; setTimeout(() => (e.target.textContent = 'Copy'), 1200);
  }
});
$('#lightbox').onclick = () => $('#lightbox').classList.remove('open');

// ---------- sessions ----------
async function api(path, body) {
  const opt = body === undefined ? {} : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) };
  const r = await fetch(path, opt); return r.json();
}
async function loadSessions() {
  const list = await api('/api/sessions'); const box = $('#sessions'); box.innerHTML = '';
  list.filter((s) => !String(s.session).startsWith('bot-') && !String(s.session).startsWith('group-')).forEach((s) => {
    const d = document.createElement('div'); d.className = 'sess' + (s.session === session ? ' active' : '');
    if (s.session === 'telegram') { const t = document.createElement('i'); t.className = 'tag'; t.textContent = 'Telegram'; d.appendChild(t); }
    const sp = document.createElement('span'); sp.textContent = s.title || s.session; d.appendChild(sp);
    d.appendChild(trashBtn('Delete chat', () => deleteChat(s.session, s.title || 'this chat')));
    d.onclick = () => openSession(s.session); box.appendChild(d);
  });
}
// ---------- delete (always asks first) ----------
function trashBtn(title, onDel) {
  const b = document.createElement('button'); b.type = 'button'; b.className = 'trash'; b.title = title; b.setAttribute('aria-label', title);
  b.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13"/></svg>';
  b.onclick = (e) => { e.stopPropagation(); onDel(); }; return b;
}
window.trashBtn = trashBtn;
async function deleteChat(id, title) {
  if (!confirm('Delete the chat "' + title + '"? This can\'t be undone.')) return;
  await api('/api/delete_session', { session: id, confirm: true });
  if (session === id) $('#new').click(); else loadSessions();
}
async function clearAllChats() {
  if (!confirm('Delete ALL your chats? Bots, groups and their rooms are kept. This can\'t be undone.')) return;
  const r = await api('/api/clear_chats', { confirm: 'clear' });
  if (!String(session).startsWith('bot-') && !String(session).startsWith('group-')) $('#new').click(); else loadSessions();
  setStatus('Deleted ' + (r.deleted || 0) + ' chats.');
}
if ($('#clear-chats')) $('#clear-chats').onclick = clearAllChats;
async function openSession(s) {
  session = s; localStorage.session = s; $('#log').innerHTML = '';
  const rows = await api('/api/history?session=' + encodeURIComponent(s));
  rows.forEach((m) => { if (m.role === 'user') addUser(m.text); else { const t = /^\[\[@([a-z0-9-]+)\]\]\s?/.exec(m.text || ''); const b = addBot(); if (t && window.markSpeaker) window.markSpeaker(b, t[1]); renderMd(b.body, t ? m.text.slice(t[0].length) : m.text); groupChips(b, m.chips); } });
  showEmpty(); loadSessions(); if (window.applyBotHeader) window.applyBotHeader();
}
$('#new').onclick = () => { session = ''; localStorage.session = ''; $('#log').innerHTML = ''; showEmpty(); loadSessions(); if (window.applyBotHeader) window.applyBotHeader(); $('#t').focus(); };

// ---------- status ----------
function setStatus(msg, isErr) { const s = $('#status'); s.textContent = msg || ''; s.classList.toggle('err-text', !!isErr); }
let level = 0;
async function pollStatus() {
  try {
    const st = await api('/api/status');
    $('#st-agent').className = 'dot ' + (st.busy ? 'busy' : 'on'); $('#st-agent-t').textContent = st.busy ? 'working' : 'ready';
    $('#st-tg').className = 'dot ' + (st.telegram ? 'on' : ''); $('#st-tg-t').textContent = st.telegram ? 'connected' : 'off';
    $('#tg-line').textContent = st.telegram ? 'Connected' : 'Not running';
    $('#st-voice').className = 'dot ' + (st.speaking || st.listening ? 'busy' : (speakOn ? 'on' : ''));
    $('#st-voice-t').textContent = st.speaking ? 'speaking' : st.listening ? 'listening' : (speakMode === 'always' ? 'on' : speakMode === 'never' ? 'off' : 'replies to voice');
    $('#st-model').textContent = st.model || '-';
    if (typeof st.speech_level === 'number' && st.speaking) avatars.forEach((a) => a.setLevel(st.speech_level));
    if (typeof st.mic_level === 'number') level = st.mic_level;
  } catch (e) { $('#st-agent').className = 'dot'; $('#st-agent-t').textContent = 'offline'; }
}
setInterval(pollStatus, 1500); pollStatus();

// ---------- waveform ----------
const wave = $('#wave');
for (let i = 0; i < 18; i++) wave.appendChild(document.createElement('i'));
let waveTimer = null;
function waveOn(on) {
  wave.classList.toggle('on', on); $('#t').style.display = on ? 'none' : '';
  clearInterval(waveTimer);
  if (on) waveTimer = setInterval(() => {
    const base = level > 0 ? level : 0.35;
    Array.from(wave.children).forEach((b, i) => { b.style.height = (6 + Math.abs(Math.sin(Date.now() / 140 + i * 0.7)) * 26 * base * (0.6 + Math.random() * 0.8)) + 'px'; });
  }, 80);
}

// ---------- chat ----------
async function stop() { stopClip(); await fetch('/api/stop', { method: 'POST' }); }
function setRunning(on) {
  running = on; const b = $('#send'); b.classList.toggle('stop', on);
  b.innerHTML = on ? '<svg viewBox="0 0 24 24" fill="currentColor"><rect x="7" y="7" width="10" height="10" rx="2"/></svg>'
    : '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4"><path d="M12 19V5M5 12l7-7 7 7"/></svg>';
}
function groupChips(b, chips) {
  (chips || []).forEach((c) => { const el = chip(b.chips, c.text); el.classList.add(c.kind === 'blocked' ? 'bad' : 'ok', 'gchip'); });
}
async function send(text, isVoice) {
  isVoice = !!isVoice || nextIsVoice; nextIsVoice = false; const talk = willSpeak(isVoice); let clip = null;
  addUser(text); hands.turnStarted(); setRunning(true); setMood('thinking');
  let bot = addBot(); rowFace = bot.row.querySelector('.face')._av; rowFace.setState('thinking');
  let act = activity(bot.body.parentNode); const labels = {};
  const chipsByName = {}; let barge = ''; let finalText = ''; let speaking = false;
  try {
    const res = await fetch('/api/chat', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text, session, voice: isVoice }) });
    const rd = res.body.getReader(); const dec = new TextDecoder(); let buf = '';
    while (true) {
      const { value, done } = await rd.read(); if (done) break;
      buf += dec.decode(value, { stream: true }); let i;
      while ((i = buf.indexOf('\n\n')) >= 0) {
        const line = buf.slice(0, i); buf = buf.slice(i + 2);
        if (!line.startsWith('data: ')) continue; let ev; try { ev = JSON.parse(line.slice(6)); } catch (e) { continue; }
        if (ev.event === 'speaker') {
          if (bot.used) { act.end(); renderMd(bot.body, bot.text || '', false); bot = addBot(); act = activity(bot.body.parentNode); }
          bot.used = true; if (window.markSpeaker) window.markSpeaker(bot, ev.id, ev); act.set((ev.name || 'A bot') + ' is thinking…');
          continue;
        }
        if (ev.event === 'group_done') { continue; }
        if (ev.event === 'done' && ev.speaker) { bot.text = ev.text || ''; renderMd(bot.body, bot.text, false); groupChips(bot, ev.chips); scrollDown(); continue; }
        if (ev.event === 'session') { session = ev.session; localStorage.session = session; }
        else if (ev.event === 'step') { act.set(ev.label || 'Working…'); if (ev.name) { labels[ev.name] = ev.label; setMood('working'); } }
        else if (ev.event === 'plan') { renderPlan(bot, ev); const next = (ev.steps || []).find((x) => x.status === 'pending'); act.set(next ? 'Step ' + next.number + ': ' + next.text : 'All steps done, checking…'); }
        else if (ev.event === 'team_plan') { act.set('Team is planning ' + ((ev.steps || []).length) + ' tasks'); }
        else if (ev.event === 'token') { act.set('Writing the reply…'); bot.text += (bot.text ? ' ' : '') + ev.text; renderMd(bot.body, bot.text, true); scrollDown(); if (talk && !speaking) { speaking = true; setMood('speaking'); } }
        else if (ev.event === 'tool_start') { /* shown by the live activity line */ }
        else if (ev.event === 'tool_end') {
          act.finish(labels[ev.name] || ev.name.replace(/_/g, ' '), ev.ok); act.set('Thinking…'); setMood('thinking');
          if (!ev.ok) { const c = chip(bot.chips, labels[ev.name] || ev.name); c.classList.add('bad'); c.querySelector('.d').textContent = ev.detail || ''; }
          if (ev.image) addImage(bot.chips.parentNode.querySelector('.md').parentNode, ev.image);
        }
        else if (ev.event === 'model_switch') { chip(bot.chips, 'switched to ' + ev.model).classList.add('ok'); }
        else if (ev.event === 'error') { addError(bot.body.parentNode, ev.text); setStatus(ev.text, true); }
        else if (ev.event === 'barge') { barge = ev.text; }
        else if (ev.event === 'done') {
          act.end();
          finalText = ev.text || bot.text; if (!bot.text && finalText) bot.text = finalText;
          renderMd(bot.body, bot.text || '', false); if (!bot.text) bot.body.innerHTML = '';
          if (talk && bot.text) setMood('speaking'); else setMood('idle');
        }
        else if (ev.event === 'audio') { clip = ev.url; }
        else if (ev.event === 'speech_end') { if (!clip) setMood('idle'); }
      }
    }
  } catch (e) { addError(bot.body.parentNode, 'Connection to the agent failed: ' + (e && e.message || e)); }
  finally {
    act.end(); if (rowFace) { const f = rowFace; f.setState('idle'); f.celebrate(); }
    renderMd(bot.body, bot.text || '', false); if (!bot.text) bot.body.innerHTML = '';
    setRunning(false); setMood('idle'); rowFace = null; loadSessions();
    if (clip) await playClip(clip);
    if (barge) { hands.state.turnRunning = false; send(barge, true); } else hands.turnEnded();
  }
}
$('#composer').onsubmit = (e) => {
  e.preventDefault(); if (running) { stop(); return; }
  const text = $('#t').value.trim(); if (!text) return; $('#t').value = ''; autosize(); send(text);
};
function autosize() { const t = $('#t'); t.style.height = 'auto'; t.style.height = Math.min(t.scrollHeight, 200) + 'px'; }
$('#t').addEventListener('input', autosize);
$('#t').addEventListener('keydown', (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); $('#composer').requestSubmit(); } });
$$('.hint').forEach((h) => (h.onclick = () => send(h.textContent)));

// ---------- voice ----------
const hands = createHandsFree({
  listenApi: async () => (await fetch('/api/listen', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{"timeout": 10}' })).json(),
  onText: (t) => send(t, true),
  onError: (m) => setStatus('🎤 ' + m, true),
  onSilence: () => setStatus("Didn't hear anything. Click the mic and speak (it listens for 10 seconds)."),
  onState: (st) => {
    const on = st === 'listening'; $('#mic').classList.toggle('on', on); waveOn(on);
    if (on) { setStatus('Listening…'); setMood('listening'); } else if (!running) setMood('idle');
  },
});
$('#mic').onclick = () => { stopClip(); if (running) stop(); hands.listen(true); };
document.addEventListener('keydown', (e) => {
  const tag = document.activeElement.tagName;
  if (e.code === 'Space' && tag !== 'TEXTAREA' && tag !== 'INPUT' && tag !== 'SELECT' && !e.repeat) { e.preventDefault(); if (running) stop(); hands.listen(true); }
  if (e.key === 'Escape') closeSettings();
});
function setHands(on) { $('#hands').classList.toggle('toggled', on); $('#hands2').checked = on; hands.setEnabled(on); }
$('#hands').onclick = () => setHands(!hands.state.enabled);
$('#hands2').onchange = (e) => setHands(e.target.checked);
let wakeTimer = null;
$('#wake').onchange = async (e) => {
  try {
    const r = await api('/api/wake', { on: e.target.checked });
    $('#wake-small').textContent = r.wake ? 'Say "' + r.phrase + '" to start.' : 'Listen in the background for the wake phrase.';
    clearInterval(wakeTimer);
    if (r.wake) wakeTimer = setInterval(async () => { if (running || hands.state.listening) return; try { const w = await api('/api/wake'); if (w.text) send(w.text, true); } catch (err) {} }, 500);
  } catch (err) { setStatus('Wake word: ' + err, true); }
};
$('#speak').onchange = async (e) => { speakMode = e.target.value; speakOn = speakMode === 'always'; await api('/api/settings', { speak_mode: speakMode }); };

// ---------- settings ----------
function openSettings() { $('#settings').classList.add('open'); $('#overlay').classList.add('open'); loadRules(); }
function closeSettings() { $('#settings').classList.remove('open'); $('#overlay').classList.remove('open'); }
$('#setbtn').onclick = openSettings; $('#close-set').onclick = closeSettings; $('#overlay').onclick = closeSettings;
$$('.tab').forEach((t) => (t.onclick = () => { $$('.tab').forEach((x) => x.classList.remove('active')); $$('.pane').forEach((p) => p.classList.remove('active')); t.classList.add('active'); $('#' + t.dataset.pane).classList.add('active'); }));
async function loadRules() { const r = await api('/api/rules'); $('#rules').value = r.text; $('#rulespath').textContent = r.path; $('#rulesmsg').textContent = ''; }
$('#reloadrules').onclick = loadRules;
$('#saverules').onclick = async () => {
  const r = await api('/api/rules', { text: $('#rules').value });
  const m = $('#rulesmsg'); m.textContent = r.ok ? 'Saved ✓' : 'Error: ' + r.error; m.style.color = r.ok ? 'var(--ok)' : 'var(--bad)';
};
async function initSettings() {
  const s = await api('/api/settings'); speakMode = s.speak_mode || (s.speak ? 'always' : 'voice'); speakOn = speakMode === 'always'; $('#speak').value = speakMode; $('#wake').checked = !!s.wake;
  [$('#model2')].forEach((sel) => { sel.innerHTML = ''; (s.models || [s.model]).forEach((m) => { const o = document.createElement('option'); o.textContent = m; sel.appendChild(o); }); sel.value = s.model; });
}
[$('#model2')].forEach((sel) => (sel.onchange = async (e) => { await api('/api/settings', { model: e.target.value }); $('#model2').value = e.target.value; pollStatus(); }));
initSettings();
if (session) openSession(session); else { loadSessions(); showEmpty(); }

// ---------- first-run setup (your own keys, saved only in .env on this PC) ----------
(async function firstRun() {
  try {
    const local = /^(127\.0\.0\.1|localhost)$/.test(location.hostname);
    const s = await api('/api/setup'); if (!s.needs_setup || !local) return;
    $('#firstrun').hidden = false;
    $('#fr-form').onsubmit = async (e) => {
      e.preventDefault();
      const r = await api('/api/setup', { gemini_api_key: $('#fr-key').value, telegram_bot_token: $('#fr-tg').value, telegram_chat_id: $('#fr-chat').value });
      if (r.ok) { $('#firstrun').hidden = true; if (r.telegram) $('#fr-err').textContent = ''; } else $('#fr-err').textContent = r.error || 'Could not save.';
    };
  } catch (e) { /* setup check is best-effort */ }
})();
