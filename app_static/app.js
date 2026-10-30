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
      if (r.status === 401) {
        if (!local) { setTimeout(() => { location.href = '/login'; }, 1500); throw new Error('Your sign-in expired, opening the sign-in page'); }
        if (window.PedroAuth && window.PedroAuth.onUnauthorized) window.PedroAuth.onUnauthorized();
        return r;
      }
      throw new Error('Your PC app is restarting or unreachable, try again in a few seconds');
    }
    return r;
  };
}
let session = urlSession || localStorage.session || '';
let running = false;
const runningSessions = new Set();
function syncRunningButton() {
  running = runningSessions.has(session || '');
  const b = $('#send'); if (!b) return;
  const typed = running && $('#t') && $('#t').value.trim();   // 1.4.15: typing during a task -> Send (side message)
  b.classList.toggle('stop', running && !typed);
  b.title = running ? (typed ? 'Send to the running task' : 'Stop') : 'Send';
  b.innerHTML = running && !typed ? '<svg viewBox="0 0 24 24" fill="currentColor"><rect x="7" y="7" width="10" height="10" rx="2"/></svg>'
    : '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4"><path d="M12 19V5M5 12l7-7 7 7"/></svg>';
  const stopBtn = $('#hdr-stop'); if (stopBtn) stopBtn.hidden = !running;
  if (!running) setLiveStep('');
  markWorkingChats();
}
function markWorkingChats() {
  document.querySelectorAll('#bots .botitem').forEach((d) => {
    d.classList.toggle('working', runningSessions.has('bot-' + d.dataset.id));
  });
  document.querySelectorAll('#sessions .sess').forEach((d) => {
    if (d.dataset.session) d.classList.toggle('working', runningSessions.has(d.dataset.session));
  });
}
window.markWorkingChats = markWorkingChats;
window.chatIsRunning = (id) => runningSessions.has(id);
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
    let finished = false;
    const end = () => { if (finished) return; finished = true; voiceOpen = false; setMood('idle'); resolve(); };
    voiceAudio.onended = end; voiceAudio.onerror = end; voiceAudio.src = url;
    voiceOpen = true;
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
let voiceOpen = false; // stay on Speaking until the voice itself has finished
function setMood(state) {
  if (voiceOpen && state !== 'speaking') state = 'speaking';
  avatars.forEach((a) => a.setState(state));
  $('#mood').textContent = MOODS[state] || state;
  if (rowFace) rowFace.setState(state);
  levelPoll(state === 'speaking' ? 'speak' : state === 'listening' ? 'listen' : '');
}
function setLiveStep(text) {
  const el = $('#live-step'); if (!el) return;
  const t = String(text || '').trim();
  if (!t || t === 'Thinking…') { el.hidden = true; el.textContent = ''; return; }
  el.hidden = false; el.textContent = t;
}
// Real loudness: the voice while speaking, the microphone while listening.
let levelTimer = null; let levelBusy = false; let levelMode = '';
let micStream = null; let micAnalyser = null; let micAudioCtx = null; let micBuf = null;
function localMicLevel() {
  if (!micAnalyser) return null;
  micBuf = micBuf || new Uint8Array(micAnalyser.fftSize);
  micAnalyser.getByteTimeDomainData(micBuf);
  let sum = 0;
  for (let i = 0; i < micBuf.length; i++) { const v = (micBuf[i] - 128) / 128; sum += v * v; }
  return Math.min(1, Math.sqrt(sum / micBuf.length) * 3.2);
}
function releaseMicMeter() {
  if (micStream) micStream.getTracks().forEach((t) => t.stop());
  micStream = null; micAnalyser = null; micBuf = null;
  if (micAudioCtx) { micAudioCtx.close(); micAudioCtx = null; }
}
function armMicMeter() {
  if (micAnalyser || ON_PC || !navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) return;
  navigator.mediaDevices.getUserMedia({ audio: true }).then((stream) => {
    if (levelMode !== 'listen') { stream.getTracks().forEach((t) => t.stop()); return; }
    micStream = stream;
    micAudioCtx = new (window.AudioContext || window.webkitAudioContext)();
    const src = micAudioCtx.createMediaStreamSource(stream);
    micAnalyser = micAudioCtx.createAnalyser();
    micAnalyser.fftSize = 512;
    src.connect(micAnalyser);
  }).catch(() => {});
}
function applyLevel(v) {
  if (typeof v !== 'number') return;
  avatars.forEach((a) => a.setLevel(v));
  if (rowFace) rowFace.setLevel(v);
}
function levelPoll(mode) {
  if (mode === levelMode) return;
  levelMode = mode;
  clearInterval(levelTimer); levelTimer = null;
  if (mode !== 'listen') releaseMicMeter();
  if (!mode) return;
  if (mode === 'listen') armMicMeter();
  levelTimer = setInterval(async () => {
    if (levelBusy) return; levelBusy = true;
    try {
      if (mode === 'listen') {
        const local = localMicLevel();
        if (typeof local === 'number') { applyLevel(local); return; }
      }
      const r = await (await fetch('/api/level')).json();
      applyLevel(mode === 'listen' ? r.mic : r.level);
    } catch (e) { /* server busy; keep synthetic motion */ } finally { levelBusy = false; }
  }, 40);
}
function botFace() {
  const d = document.createElement('div'); d.className = 'face';
  const look = (window.currentBotLook && window.currentBotLook()) || {};
  d._av = createAvatar(d, look); return d;
}
// Stage directions like [chuckles] are for the voice only.
const STAGE = /[ \t]*\[(?:chuckles?|laughs?|laughing|giggles?|playful(?:ly)?|sighs?|smiles?|smile|grins?|winks?|gasps?|whispers?|clears throat|pauses?|sarcastic(?:ally)?|excited(?:ly)?|cheerful(?:ly)?|cheers|softly|happily|sadly|snorts?|hums?|coughs?|thoughtful(?:ly)?|warmly|gently|proudly|nervously|curious(?:ly)?|breathes?)\][ \t]*/gi;
// Markers people should never see (1.4.14): reactions, written tool calls, team protocol words, stray speaker tags.
const TEXT_CALL = /\[\[\s*[A-Za-z_][A-Za-z0-9_]{2,60}\s*\((?:[^\[\]]|\[[^\[\]]*\])*\)\s*\]\]/g;
const PROTO = /(^|\n)\s*\**\s*(?:ASSIGN\s+@?[A-Za-z0-9_\-]+\s*\**\s*[:\-]\s*|PROJECT\s+(?:DONE|COMPLETE)\s*[:\-]?\s*|ASK\s+USER\s*[:\-]\s*|DONE\s*[:\-]\s*|BLOCKED\s*[:\-]\s*)/g;
function stripStage(t) {
  return String(t || '')
    .replace(/\s*\[{1,2}react:[^\]\s]{1,16}\]{1,2}/g, '')
    .replace(/(?<!\[)\[@[A-Za-z0-9_\-]+\]\]\s*/g, '')
    .replace(TEXT_CALL, '')
    .replace(PROTO, '$1')
    .replace(/\s*\b(?:PROJECT\s+DONE|ASK\s+USER|ASSIGN\s+@[A-Za-z0-9_\-]+|DONE|BLOCKED)\s*:\s*/g, ' ')
    .replace(STAGE, ' ').replace(/ {2,}/g, ' ').replace(/^ +/gm, '');
}

// ---------- rendering ----------
// Stay put if Pedro scrolled up to read; the jump-to-latest button takes him back.
function scrollDown(force) { const l = $('#log'); if (!force && window.pbScrolledUp) return; l.scrollTop = l.scrollHeight; }
function showEmpty() { $('#empty').classList.toggle('hidden', $('#log').children.length > 0); }
function fileChip(f) {
  const a = document.createElement('a'); a.className = 'att'; a.href = f.url; a.target = '_blank'; a.rel = 'noopener';
  if (f.kind !== 'image') a.download = f.name;
  const n = document.createElement('span'); n.className = 'n'; n.textContent = '\u{1F4CE} ' + f.name; a.appendChild(n); return a;
}
function messageWhen(ts) {
  const n = Number(ts);
  const d = n ? new Date(n > 1e12 ? n : n * 1000) : new Date();
  if (Number.isNaN(d.getTime())) return '';
  const time = d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
  const now = new Date();
  let label = time;
  if (d.toDateString() !== now.toDateString()) {
    const yesterday = new Date(now);
    yesterday.setDate(now.getDate() - 1);
    label = (d.toDateString() === yesterday.toDateString()
      ? 'Yesterday'
      : d.toLocaleDateString([], { month: 'short', day: 'numeric' })) + ', ' + time;
  }
  return label;
}
function stampMessage(row, ts) {
  if (!row) return;
  const n = Number(ts);
  const d = n ? new Date(n > 1e12 ? n : n * 1000) : new Date();
  if (Number.isNaN(d.getTime())) return;
  let el = row.querySelector('.msg-time');
  if (!el) { el = document.createElement('time'); el.className = 'msg-time'; row.appendChild(el); }
  el.dateTime = d.toISOString();
  el.textContent = messageWhen(d.getTime());
  el.title = d.toLocaleString();
}
window.messageWhen = messageWhen;
function addUser(text, files, ts) {
  const row = document.createElement('div'); row.className = 'row user';
  const b = document.createElement('div'); b.className = 'bubble'; b.textContent = text === '(sent attachments)' && files && files.length ? '' : text;
  if (files && files.length) {
    const box = document.createElement('div'); box.className = 'atts';
    files.forEach((f) => {
      if (f.kind === 'image') { const im = document.createElement('img'); im.src = f.url; im.alt = f.name; im.title = f.name; im.loading = 'lazy'; im.onclick = () => window.open(f.url, '_blank'); box.appendChild(im); }
      else if (f.kind === 'video') { const v = document.createElement('video'); v.className = 'clip'; v.controls = true; v.preload = 'metadata'; v.src = f.url; v.title = f.name; box.appendChild(v); }
      else box.appendChild(fileChip(f));
    });
    b.appendChild(box);
  }
  row.dataset.replyText = text || '';
  row.appendChild(b); $('#log').appendChild(row); stampMessage(row, ts); showEmpty(); scrollDown();
  if (window.Reactions) Reactions.attach(row);
  addCopy(row);
  addReply(row);
  return row;
}
function addBot(ts) {
  const row = document.createElement('div'); row.className = 'row bot msg'; row.dataset.role = 'assistant';
  row.appendChild(botFace());
  const col = document.createElement('div'); col.className = 'bubble';
  const chips = document.createElement('div'); chips.className = 'chips';
  const body = document.createElement('div'); body.className = 'md';
  col.append(chips, body); row.appendChild(col); $('#log').appendChild(row); stampMessage(row, ts); showEmpty(); scrollDown();
  if (window.Reactions) Reactions.attach(row);
  addCopy(row);
  addReply(row);
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
      setLiveStep(text);
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
function mediaName(path) {
  const parts = String(path || '').split(/[\\/]/);
  return parts[parts.length - 1] || 'camera';
}
function addDownload(container, href, name, label) {
  const a = document.createElement('a');
  a.className = 'cam-dl';
  a.href = href;
  a.download = name;
  a.textContent = label;
  // 1.6.6: the PC window (pywebview) ignores <a download>; ask the PC app to copy the file into Downloads.
  // The Android app saves through its own DownloadListener (streams to Downloads, toast when done).
  a.addEventListener('click', async (e) => {
    const onPc = /^(127\.0\.0\.1|localhost)$/.test(location.hostname) && !/PedroAgentApp/.test(navigator.userAgent);
    if (!onPc) return;
    e.preventDefault();
    try {
      const u = new URL(href, location.href);
      const r = await (await fetch('/api/save_download', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: u.searchParams.get('path') || '', kind: u.pathname === '/api/image' ? 'image' : 'media' }) })).json();
      if (window.pbToast) window.pbToast(r.ok ? r.message : (r.error || 'Could not save it.'));
    } catch (err) { if (window.pbToast) window.pbToast('Could not save it.'); }
  });
  container.appendChild(a);
}
function addImage(container, path) {
  const img = document.createElement('img'); img.className = 'thumb'; img.alt = 'preview';
  img.src = '/api/image?path=' + encodeURIComponent(path) + '&t=' + Date.now();
  img.onclick = () => { $('#lightbox img').src = img.src; $('#lightbox').classList.add('open'); };
  container.appendChild(img);
  const name = mediaName(path);
  addDownload(container, '/api/image?path=' + encodeURIComponent(path) + '&download=1', name, 'Download image');
  scrollDown();
}
function addVideo(container, path) {
  const v = document.createElement('video');
  v.className = 'clip';
  v.controls = true;
  v.preload = 'metadata';
  v.src = '/api/media?path=' + encodeURIComponent(path);
  container.appendChild(v);
  const name = mediaName(path);
  addDownload(container, '/api/media?path=' + encodeURIComponent(path) + '&download=1', name, 'Download video');
  scrollDown();
}
function isCameraMedia(path) {
  const norm = String(path || '').replace(/\\/g, '/').toLowerCase();
  return /\/camera\/camera-[^/]+\.(png|jpe?g|mp4|webm)$/.test(norm) || /\/progress\/progress-[^/]+\.(png|jpe?g)$/.test(norm);
}
function addSavedMedia(row, paths) {
  if (!row) return;
  const bubble = row.querySelector('.bubble') || row;
  (paths || []).forEach((path) => {
    if (!isCameraMedia(path)) return;
    if (/\.(mp4|webm)$/i.test(path)) addVideo(bubble, path);
    else addImage(bubble, path);
  });
}
window.addImage = addImage;
window.addVideo = addVideo;
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
let sessionCache = []; let chatQuery = '';
function shortWhen(ts) {
  const n = Number(ts); if (!n) return '';
  const d = new Date(n * 1000); if (Number.isNaN(d.getTime())) return '';
  const now = new Date();
  if (d.toDateString() === now.toDateString()) return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  return d.toLocaleDateString([], { month: 'short', day: 'numeric' });
}
function drawSessions() {
  const box = $('#sessions'); if (!box) return; box.innerHTML = '';
  const q = chatQuery.trim().toLowerCase();
  const list = sessionCache.filter((s) => !String(s.session).startsWith('bot-') && !String(s.session).startsWith('group-'))
    .filter((s) => !q || ((s.title || '') + ' ' + (s.preview || '') + ' ' + (s.session || '')).toLowerCase().includes(q));
  if (!list.length) { const empty = document.createElement('div'); empty.className = 'sess-empty'; empty.textContent = q ? 'No chats match' : 'No chats yet'; box.appendChild(empty); return; }
  list.forEach((s) => {
    const d = document.createElement('div'); d.className = 'sess' + (s.session === session ? ' active' : '') + (s.pinned ? ' pinned' : '') + (runningSessions.has(s.session) ? ' working' : '');
    d.dataset.session = s.session;
    if (s.session === 'telegram') { const t = document.createElement('i'); t.className = 'tag'; t.textContent = 'Telegram'; d.appendChild(t); }
    const main = document.createElement('div'); main.className = 'sess-main';
    const sp = document.createElement('span'); sp.className = 'sess-title'; sp.textContent = s.title || s.session; main.appendChild(sp);
    const meta = document.createElement('small'); meta.className = 'sess-meta';
    const when = shortWhen(s.last); const preview = s.preview || '';
    meta.textContent = preview && when ? preview + ' · ' + when : (preview || when);
    main.appendChild(meta); d.appendChild(main);
    d.appendChild(pinBtn(s));
    d.appendChild(trashBtn('Delete chat', () => deleteChat(s.session, s.title || 'this chat')));
    let clickTimer = null;
    d.onclick = () => { clearTimeout(clickTimer); clickTimer = setTimeout(() => openSession(s.session), 220); };
    d.oncontextmenu = (e) => { e.preventDefault(); togglePin(s); };
    sp.ondblclick = (e) => { e.stopPropagation(); e.preventDefault(); clearTimeout(clickTimer); beginRename(main, sp, s); };
    box.appendChild(d);
  });
}
function pinBtn(s) {
  const b = document.createElement('button'); b.type = 'button'; b.className = 'pin';
  b.title = s.pinned ? 'Unpin' : 'Pin'; b.setAttribute('aria-label', s.pinned ? 'Unpin chat' : 'Pin chat');
  b.textContent = s.pinned ? '\u2605' : '\u2606';
  b.onclick = (e) => { e.stopPropagation(); e.preventDefault(); togglePin(s); };
  return b;
}
async function togglePin(s) {
  const r = await api('/api/pin', { session: s.session, on: !s.pinned });
  if (!r.ok) setStatus(r.error || 'Could not pin.', true);
  loadSessions();
}
function beginRename(main, titleEl, s) {
  const input = document.createElement('input'); input.className = 'sess-rename'; input.value = s.title || '';
  titleEl.replaceWith(input); input.focus(); input.select();
  let done = false;
  async function commit(save) {
    if (done) return; done = true;
    const name = input.value.trim();
    if (save && name && name !== (s.title || '')) {
      const r = await api('/api/rename', { session: s.session, title: name });
      if (!r.ok) setStatus(r.error || 'Could not rename.', true);
    }
    loadSessions();
  }
  input.onclick = (e) => e.stopPropagation();
  input.ondblclick = (e) => e.stopPropagation();
  input.onkeydown = (e) => { if (e.key === 'Enter') { e.preventDefault(); commit(true); } if (e.key === 'Escape') { e.preventDefault(); commit(false); } };
  input.onblur = () => commit(true);
}
async function loadSessions() {
  const rows = await api('/api/sessions'); sessionCache = Array.isArray(rows) ? rows : []; drawSessions();
}
window.loadSessions = loadSessions;
const chatFind = $('#chat-find');
if (chatFind) chatFind.oninput = () => { chatQuery = chatFind.value; drawSessions(); };
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
// 1.4.15: Delete all chats: red danger action, a count in the dialog, auto backup, Undo for 10 s.
function dangerDialog(title, body, okText) {
  return new Promise((resolve) => {
    const wrap = document.createElement('div'); wrap.className = 'pb-modal-wrap'; wrap.setAttribute('role', 'dialog'); wrap.setAttribute('aria-modal', 'true');
    const box = document.createElement('div'); box.className = 'pb-modal';
    const h = document.createElement('h3'); h.textContent = title;
    const p = document.createElement('p'); p.textContent = body;
    const row = document.createElement('div'); row.className = 'pb-modal-acts';
    const no = document.createElement('button'); no.type = 'button'; no.className = 'btn'; no.textContent = 'Cancel';
    const yes = document.createElement('button'); yes.type = 'button'; yes.className = 'btn danger-solid'; yes.textContent = okText;
    row.append(no, yes); box.append(h, p, row); wrap.appendChild(box); document.body.appendChild(wrap);
    const done = (v) => { wrap.remove(); resolve(v); };
    no.onclick = () => done(false); yes.onclick = () => done(true);
    wrap.onclick = (e) => { if (e.target === wrap) done(false); };
    no.focus();
  });
}
function undoBar(text, seconds, onUndo) {
  let bar = $('#pb-undo'); if (bar) bar.remove();
  bar = document.createElement('div'); bar.id = 'pb-undo'; bar.setAttribute('role', 'status');
  const msg = document.createElement('span'); msg.textContent = text;
  const btn = document.createElement('button'); btn.type = 'button'; btn.textContent = 'Undo';
  bar.append(msg, btn); document.body.appendChild(bar);
  const timer = setTimeout(() => bar.remove(), seconds * 1000);
  btn.onclick = async () => { clearTimeout(timer); btn.disabled = true; await onUndo(); bar.remove(); };
}
async function clearAllChats() {
  const c = await api('/api/chats_count');
  const n = (c && c.count) || 0;
  if (!n) { setStatus('There are no chats to delete.'); return; }
  const onPhone = !/^(127\.0\.0\.1|localhost)$/.test(location.hostname);
  const other = onPhone ? 'on your PC too' : 'on your phone too';
  const ok = await dangerDialog('Delete all chats?',
    'This deletes ' + n + ' chat' + (n === 1 ? '' : 's') + '. The phone mirrors the PC, so they are cleared ' + other + '. Bots, routines, groups and settings are kept. A backup is saved first.',
    'Delete');
  if (!ok) return;
  const r = await api('/api/clear_chats', { confirm: 'clear' });
  if (!String(session).startsWith('bot-') && !String(session).startsWith('group-')) $('#new').click(); else loadSessions();
  setStatus('Deleted ' + (r.deleted || 0) + ' chats.');
  undoBar('Deleted ' + (r.deleted || 0) + ' chats.', 10, async () => {
    const u = await api('/api/clear_chats/undo', {});
    setStatus(u && u.ok ? 'Restored ' + u.restored + ' chats.' : ((u && u.error) || 'Could not undo.'));
    loadSessions();
  });
}
if ($('#clear-chats')) $('#clear-chats').onclick = clearAllChats;
async function openSession(s) { window.openSession = openSession;
  if (!keepReply) clearReply();
  session = s; localStorage.session = s; $('#log').innerHTML = '';
  let rows = await api('/api/history?session=' + encodeURIComponent(s));
  // 1.4.18: Lite mode shows the newest messages of a long chat; the rest load on request
  const limit = window.LITE && window.LITE.on && !window.__allHistory ? window.LITE.historyLimit : 0;
  window.__allHistory = false;
  if (limit && rows.length > limit) {
    const hidden = rows.length - limit; rows = rows.slice(-limit);
    const more = document.createElement('button'); more.type = 'button'; more.className = 'hist-more';
    more.textContent = 'Show ' + hidden + ' earlier message' + (hidden === 1 ? '' : 's');
    more.onclick = () => { window.__allHistory = true; openSession(s); };
    $('#log').appendChild(more);
  }
  rows.forEach((m) => { if (m.card) { renderCard(m.card, m.ts); return; } if (/^\[\[card:[0-9a-f]{12}\]\]$/.test(m.text || '')) return; if (m.role === 'user') { const u = addUser(m.text, m.files, m.ts); if (window.Reactions) Reactions.attach(u, m.id, m.reactions); } else { if (!String(m.text || '').replace(/^\[\[@[a-z0-9-]+\]\]/, '').trim() && !(m.writes && m.writes.length)) return; const t = /^\[\[@([a-z0-9-]+)\]\]\s?/.exec(m.text || ''); const b = addBot(m.ts); b.row.dataset.replyText = t ? m.text.slice(t[0].length) : (m.text || ''); if (window.Reactions) Reactions.attach(b.row, m.id, m.reactions); if (t && window.markSpeaker) window.markSpeaker(b, t[1]); renderMd(b.body, t ? m.text.slice(t[0].length) : m.text); groupChips(b, m.chips); if (m.writes && m.writes.length) { addUndo(b.row, m.writes); addSavedMedia(b.row, m.writes); } } });
  showEmpty(); loadSessions(); syncRunningButton(); if (window.applyBotHeader) window.applyBotHeader();
}
$('#new').onclick = () => { session = ''; localStorage.session = ''; $('#log').innerHTML = ''; showEmpty(); loadSessions(); syncRunningButton(); if (window.applyBotHeader) window.applyBotHeader(); $('#t').focus(); };

// ---------- status ----------
function setStatus(msg, isErr) { const s = $('#status'); s.textContent = msg || ''; s.classList.toggle('err-text', !!isErr); }
let level = 0;
async function pollStatus() {
  try {
    const st = await api('/api/status');
    $('#st-agent').className = 'dot ' + (st.busy ? 'busy' : 'on'); $('#st-agent-t').textContent = st.busy ? 'working' : 'ready';
    $('#st-tg').className = 'dot ' + (st.telegram ? 'on' : ''); $('#st-tg-t').textContent = st.telegram ? 'connected' : 'off';
    const tgLine = $('#tg-line');
    if (tgLine) { tgLine.textContent = st.telegram ? 'Connected' : 'Not running'; tgLine.dataset.state = st.telegram ? 'on' : 'off'; }
    $('#st-voice').className = 'dot ' + (st.speaking || st.listening ? 'busy' : (speakOn ? 'on' : ''));
    $('#st-voice-t').textContent = st.speaking ? 'speaking' : st.listening ? 'listening' : (speakMode === 'always' ? 'on' : speakMode === 'never' ? 'off' : 'replies to voice');
    $('#st-model').textContent = st.model || '-';
    const hm = $('#hdr-model'); if (hm) hm.textContent = st.active_model || st.model || 'auto';
    showPaused(!!st.paused);
    if (typeof st.speech_level === 'number' && st.speaking) applyLevel(st.speech_level);
    if (typeof st.mic_level === 'number') level = st.mic_level;
    else if (!st.listening) level = 0;
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
async function stop() {
  voiceOpen = false; stopClip(); setMood('idle');
  setRunning(false); setStatus('Stopped');   // 1.4.15: show it at once; the server stops within ~0.5 s
  await fetch('/api/stop', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ session: session || '' }) });
}
function setRunning(on) {
  const key = session || '';
  if (on) runningSessions.add(key); else runningSessions.delete(key);
  syncRunningButton();
}
if ($('#hdr-stop')) $('#hdr-stop').onclick = () => { if (running) stop(); };
function replyBar(row) {
  const bubble = row && row.querySelector('.bubble'); if (!bubble) return null;
  // 1.6.6: actions sit under the bubble (small icons), not inside it
  let bar = row.querySelector('.msg-actions');
  if (!bar) { bar = document.createElement('div'); bar.className = 'msg-actions'; bubble.after(bar); }
  return bar;
}
const COPY_ICON = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h10"/></svg>';
function messageText(row) {
  if (row.classList.contains('user')) return row.dataset.replyText || '';
  const md = row.querySelector('.md'); return md ? md.innerText.trim() : '';
}
async function copyPlain(text) {
  try { await navigator.clipboard.writeText(text); return true; } catch (e) {
    const ta = document.createElement('textarea'); ta.value = text; ta.setAttribute('readonly', ''); ta.style.position = 'fixed'; ta.style.opacity = '0';
    document.body.appendChild(ta); ta.select(); let ok = false; try { ok = document.execCommand('copy'); } catch (e2) { ok = false; } ta.remove(); return ok;
  }
}
function toast(text) {
  let t = $('#pb-toast'); if (!t) { t = document.createElement('div'); t.id = 'pb-toast'; t.setAttribute('role', 'status'); document.body.appendChild(t); }
  t.textContent = text; t.classList.add('show'); clearTimeout(t._h); t._h = setTimeout(() => t.classList.remove('show'), 1300);
}
window.pbToast = toast;
async function copyRow(row) { const ok = await copyPlain(messageText(row)); toast(ok ? 'Copied' : 'Could not copy'); return ok; }
// 1.4.14: live terminal output inside the bot's message
function termEvent(bot, ev) {
  const col = bot.body && bot.body.parentNode; if (!col) return;
  if (ev.kind === 'start' || !bot.term) {
    const box = document.createElement('div'); box.className = 'term';
    const head = document.createElement('div'); head.className = 'term-head'; head.textContent = (ev.shell || 'terminal') + (ev.cwd ? '  ·  ' + ev.cwd : '');
    const cmd = document.createElement('div'); cmd.className = 'term-cmd'; cmd.textContent = '> ' + (ev.command || '');
    const pre = document.createElement('pre'); pre.className = 'term-out';
    box.append(head, cmd, pre); col.insertBefore(box, bot.body); bot.term = { box, pre, n: 0 };
  }
  const t = bot.term;
  if (ev.kind === 'line') { if (t.n < 400) { t.pre.textContent += ev.line + '\n'; t.n++; t.pre.scrollTop = t.pre.scrollHeight; } else if (t.n === 400) { t.pre.textContent += '… (more output in the reply)\n'; t.n++; } }
  if (ev.kind === 'end') { const f = document.createElement('div'); f.className = 'term-end' + (ev.code === 0 ? ' ok' : ' bad'); f.textContent = 'exit ' + ev.code + ' · ' + ev.seconds + ' s'; t.box.appendChild(f); bot.term = null; }
  scrollDown();
}
// 1.6.9: read a reply aloud in the bot's Gemini voice, with a tone that fits the words
const SPEAK_ICON = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M11 4.7a.7.7 0 0 0-1.2-.5L6.4 7.6A1.4 1.4 0 0 1 5.4 8H3a1 1 0 0 0-1 1v6a1 1 0 0 0 1 1h2.4a1.4 1.4 0 0 1 1 .4l3.4 3.4a.7.7 0 0 0 1.2-.5z"/><path d="M16 9a5 5 0 0 1 0 6"/><path d="M19.4 18.4a9 9 0 0 0 0-12.8"/></svg>';
const STOP_ICON = '<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><rect x="6" y="6" width="12" height="12" rx="2"/></svg>';
let speakingBtn = null;
function addSpeak(row, bar) {
  if (row.querySelector('.msg-speak')) return;
  const b = document.createElement('button'); b.type = 'button'; b.className = 'msg-speak'; b.title = 'Read aloud'; b.setAttribute('aria-label', 'Read aloud');
  b.innerHTML = SPEAK_ICON;
  b.onclick = async (e) => {
    e.stopPropagation();
    if (speakingBtn === b) { stopClip(); b.innerHTML = SPEAK_ICON; speakingBtn = null; return; }
    if (speakingBtn) { stopClip(); speakingBtn.innerHTML = SPEAK_ICON; }
    const text = messageText(row); if (!text) return;
    speakingBtn = b; b.innerHTML = STOP_ICON; b.classList.add('busy');
    const prev = row.previousElementSibling && row.previousElementSibling.classList.contains('user') ? messageText(row.previousElementSibling) : '';
    try {
      const r = await (await fetch('/api/speak_text', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text, user: prev, session: (typeof session === 'string' ? session : '') }) })).json();
      b.classList.remove('busy');
      if (!r.ok) { toast(r.error || 'Could not speak that.'); b.innerHTML = SPEAK_ICON; speakingBtn = null; return; }
      if (r.note) toast(r.note);
      if (r.tone) b.title = 'Read aloud (' + r.voice + ', ' + r.tone + ')';
      if (speakingBtn === b) await playClip(r.url);
    } catch (err) { toast('Could not speak that.'); }
    b.classList.remove('busy'); if (speakingBtn === b) { b.innerHTML = SPEAK_ICON; speakingBtn = null; }
  };
  bar.insertBefore(b, bar.children[1] || null);
}
window.pbAddSpeak = addSpeak;
function addCopy(row) {
  if (!row || row.querySelector('.msg-copy')) return;
  const bar = replyBar(row); if (!bar) return;
  const btn = document.createElement('button'); btn.type = 'button'; btn.className = 'msg-copy'; btn.title = 'Copy'; btn.setAttribute('aria-label', 'Copy message');
  btn.innerHTML = COPY_ICON; btn.onclick = (e) => { e.stopPropagation(); copyRow(row); };
  bar.insertBefore(btn, bar.firstChild);
  if (!row.classList.contains('user')) addSpeak(row, bar);
  // phone: long-press the bubble to copy
  const bubble = row.querySelector('.bubble'); let lp = 0;
  bubble.addEventListener('touchstart', (e) => { if (e.target.closest('button,a,img,input')) return; lp = setTimeout(() => { lp = 0; copyRow(row); if (navigator.vibrate) navigator.vibrate(15); }, 550); }, { passive: true });
  ['touchend', 'touchmove', 'touchcancel'].forEach((k) => bubble.addEventListener(k, () => { if (lp) { clearTimeout(lp); lp = 0; } }, { passive: true }));
}
window.pbCopyRow = copyRow;
let replyTo = null, keepReply = false;
function clearReply() {
  replyTo = null;
  document.querySelectorAll('.row.replying').forEach((r) => r.classList.remove('replying'));
  const bar = $('#reply-to'); if (bar) bar.hidden = true;
}
function chatLabel() {
  if (session && session.startsWith('bot-')) {
    const b = (window.pedroBots || []).find((x) => 'bot-' + x.id === session); if (b) return b.name;
  }
  if (session && session.startsWith('group-')) {
    const g = (window.pedroGroups || []).find((x) => 'group-' + x.id === session); if (g) return g.name;
  }
  if (!session) return 'This chat';
  const row = sessionCache.find((s) => s.session === session);
  const hdr = document.querySelector('.who b');
  return (row && row.title) || (hdr && hdr.textContent) || 'This chat';
}
function messageText(row) {
  if (row && row.dataset && row.dataset.replyText) return row.dataset.replyText;
  const md = row && row.querySelector('.md');
  return md ? md.innerText : '';
}
function showReply(row) {
  const M = window.MentionPick; if (!row || !M) return;
  document.querySelectorAll('.row.replying').forEach((r) => r.classList.remove('replying'));
  row.classList.add('replying');
  const name = (() => {
    const n = row.querySelector('.speaker-name');
    if (n && n.textContent) return n.textContent;
    if (row.classList.contains('user')) return 'You';
    const hdr = document.querySelector('.who b');
    return (hdr && hdr.textContent) || 'Pedro';
  })();
  const snippet = messageText(row).replace(/\s+/g, ' ').trim().slice(0, 240);
  const choices = M.replyChats(session || '', chatLabel(), window.pedroBots || [], window.pedroGroups || [], sessionCache);
  const sel = $('#reply-in'); sel.innerHTML = '';
  choices.forEach((c) => { const o = document.createElement('option'); o.value = c.id; o.textContent = c.name; sel.appendChild(o); });
  sel.value = session || '';
  $('#reply-to-name').textContent = name;
  $('#reply-to-text').textContent = snippet || '(empty message)';
  $('#reply-to').hidden = false;
  replyTo = { name, snippet };
  $('#t').focus();
}
function addReply(row) {
  if (!row || row.querySelector('.msg-reply')) return;
  const bar = replyBar(row); if (!bar) return;
  const btn = document.createElement('button'); btn.type = 'button'; btn.className = 'msg-reply'; btn.textContent = 'Reply';
  btn.title = 'Reply to this message in a chat you choose';
  btn.onclick = () => showReply(row);
  bar.appendChild(btn);
}
if ($('#reply-clear')) $('#reply-clear').onclick = () => clearReply();
function addUndo(row, paths) {
  const list = (paths || []).filter(Boolean);
  if (!row || !list.length || row.querySelector('.msg-undo')) return;
  const bar = replyBar(row); if (!bar) return;
  const btn = document.createElement('button'); btn.type = 'button'; btn.className = 'msg-undo'; btn.textContent = 'Undo';
  btn.onclick = async () => {
    btn.disabled = true;
    let r; try { r = await api('/api/undo', { paths: list }); } catch (e) { r = { ok: false, error: String(e) }; }
    btn.textContent = r.ok ? 'Undone' : (r.error || 'Not undone');
  };
  bar.appendChild(btn);
}
function finishPing() {
  const header = document.querySelector('main > header');
  if (header) {
    header.classList.remove('done-flash');
    void header.offsetWidth;
    header.classList.add('done-flash');
    setTimeout(() => header.classList.remove('done-flash'), 1300);
  }
  const oldTitle = document.title;
  document.title = 'Pedro finished';
  setTimeout(() => { if (document.title === 'Pedro finished') document.title = oldTitle; }, 2000);
  try {
    const Ctx = window.AudioContext || window.webkitAudioContext;
    const ctx = new Ctx();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = 'sine'; osc.frequency.value = 880; gain.gain.value = 0.05;
    osc.connect(gain); gain.connect(ctx.destination);
    osc.start(); osc.stop(ctx.currentTime + 0.15);
    osc.onended = () => ctx.close();
  } catch (e) {}
}
function groupChips(b, chips) {
  (chips || []).forEach((c) => { const el = chip(b.chips, c.text); el.classList.add(c.kind === 'blocked' ? 'bad' : 'ok', 'gchip'); });
}
// 1.4.10: question cards (ask_user) and Approve / Deny cards. Saved in the chat, so they survive reloads.
function renderCard(c, ts) {
  if (!c) return null;
  const old = document.querySelector('.pa-card[data-id="' + c.id + '"]'); if (old) old.closest('.row').remove();
  const row = document.createElement('div'); row.className = 'row bot msg'; row.dataset.role = 'assistant'; row.appendChild(botFace());
  const card = document.createElement('div'); card.className = 'bubble pa-card ' + c.status; card.dataset.id = c.id; card.dataset.kind = c.kind;
  const q = document.createElement('div'); q.className = 'pa-q'; q.textContent = c.kind === 'approval' && !c.order ? 'Waiting for you: ' + c.question : (c.order ? 'Place this order on ' + c.order.platform + '?' : c.question); card.appendChild(q);
  const done = c.status !== 'open'; const ans = c.answer || {};
  const note = (t) => { const n = document.createElement('div'); n.className = 'pa-note'; n.textContent = t; card.appendChild(n); };
  async function submit(body) {
    card.querySelectorAll('button,input').forEach((b) => (b.disabled = true));
    let r; try { r = await api('/api/card/answer', Object.assign({ id: c.id }, body)); } catch (e) { r = { ok: false, error: String(e) }; }
    if (!r.ok) { setStatus(r.error || 'Could not answer', true); if (r.card) renderCard(Object.assign({}, c, r.card)); else card.querySelectorAll('button,input').forEach((b) => (b.disabled = false)); return; }
    renderCard(r.card); if (running) { setStatus('Answer saved; sending when the current reply ends.'); const wait = setInterval(() => { if (!running) { clearInterval(wait); send(r.text); } }, 500); } else send(r.text);
  }
  if (c.kind === 'approval') {
    const o = c.order;
    if (o) {
      [['Item', o.item], ['Seller', o.seller], ['Qty', o.quantity], ['Price', o.item_price], ['Delivery / fees', o.delivery_and_fees],
       ['Total', o.total + (o.total_on_page === false ? '  (not found on page, check!)' : '')], ['Address', o.address], ['Payment', o.payment_method]]
        .forEach(([k, v]) => { if (v === undefined || v === null || v === '') return; const d = document.createElement('div'); d.className = 'pa-kv'; d.textContent = k + ': ' + v; card.appendChild(d); });
      if (o.screenshot_url) { const im = document.createElement('img'); im.className = 'pa-shot'; im.src = o.screenshot_url; im.onclick = () => window.open(o.screenshot_url, '_blank'); card.appendChild(im); }
    }
    const btns = document.createElement('div'); btns.className = 'pa-btns';
    const yes = document.createElement('button'); yes.type = 'button'; yes.className = 'pa-btn primary'; yes.textContent = 'Approve';
    const no = document.createElement('button'); no.type = 'button'; no.className = 'pa-btn danger'; no.textContent = 'Deny';
    yes.onclick = () => submit({ decision: 'approve' }); no.onclick = () => submit({ decision: 'deny' });
    if (done) { yes.disabled = no.disabled = true; if (ans.decision === 'approve') yes.classList.add('chosen'); if (ans.decision === 'deny') no.classList.add('chosen'); }
    btns.append(yes, no); card.appendChild(btns);
    if (c.status === 'expired') note('No longer waiting (answered or replaced).');
  } else {
    const opts = document.createElement('div'); opts.className = 'pa-opts'; const sel = new Set(ans.choices || []);
    (c.options || []).forEach((o) => {
      const b = document.createElement('button'); b.type = 'button'; b.className = 'pa-opt' + (sel.has(o) ? ' sel' : ''); b.textContent = o; b.disabled = done;
      b.onclick = () => { if (!c.multi) { submit({ choices: [o] }); return; } b.classList.toggle('sel'); if (sel.has(o)) sel.delete(o); else sel.add(o); };
      opts.appendChild(b);
    });
    card.appendChild(opts);
    let other = null;
    if (c.other) { other = document.createElement('input'); other.className = 'pa-other'; other.placeholder = 'Other…'; other.maxLength = 300; other.value = ans.other || ''; other.disabled = done; card.appendChild(other);
      other.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); go.click(); } }); }
    const go = document.createElement('button'); go.type = 'button'; go.className = 'pa-btn primary'; go.textContent = 'Send';
    go.onclick = () => submit({ choices: Array.from(sel), other: other ? other.value : '' });
    if ((c.multi || c.other) && !done) card.appendChild(go);
    if (c.multi && !done) note('Pick one or more, then Send.');
    if (c.status === 'expired') note('Expired.');
  }
  if (c.status === 'answered') note('Answered');
  row.appendChild(card); $('#log').appendChild(row); stampMessage(row, ts); showEmpty(); scrollDown(); return row;
}
async function send(text, isVoice, files) {
  const quoting = replyTo ? { name: replyTo.name, snippet: replyTo.snippet, session: ($('#reply-in') && $('#reply-in').value) || '' } : null;
  const target = quoting ? quoting.session : (session || '');
  if (quoting && target !== (session || '')) {
    keepReply = true;
    try { await openSession(target); } finally { keepReply = false; }
  }
  files = files || []; if (!text && files.length) text = '(sent attachments)';
  const payload = quoting && window.MentionPick ? window.MentionPick.quoteReply(quoting.name, quoting.snippet, text) : text;
  clearReply();
  const turnStarted = performance.now();
  let turnKey = target || '';
  isVoice = !!isVoice || nextIsVoice; nextIsVoice = false; const talk = willSpeak(isVoice); let clip = null;
  const userRow = addUser(payload || text, files); hands.turnStarted(); runningSessions.add(turnKey); syncRunningButton(); setMood('thinking');
  let bot = addBot(); rowFace = bot.row.querySelector('.face')._av; rowFace.setState('thinking');
  let act = activity(bot.body.parentNode); const labels = {};
  const chipsByName = {}; let barge = ''; let finalText = ''; let speaking = false;
  try {
    const body = { text: payload, session: turnKey, voice: isVoice, files: files.map((f) => f.id), client: CLIENT_ID };
    if (window.avatarMode && window.avatarMode.wantsVoice()) body.speak = true;
    const res = await fetch('/api/chat', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    const rd = res.body.getReader(); const dec = new TextDecoder(); let buf = '';
    while (true) {
      const { value, done } = await rd.read(); if (done) break;
      buf += dec.decode(value, { stream: true }); let i;
      while ((i = buf.indexOf('\n\n')) >= 0) {
        const line = buf.slice(0, i); buf = buf.slice(i + 2);
        if (!line.startsWith('data: ')) continue; let ev; try { ev = JSON.parse(line.slice(6)); } catch (e) { continue; }
        if (ev.event === 'session') {
          const next = ev.session || turnKey;
          if (next !== turnKey) { runningSessions.delete(turnKey); turnKey = next; runningSessions.add(turnKey); }
          session = turnKey; localStorage.session = session; syncRunningButton();
          continue;
        }
        if ((session || '') !== turnKey) continue;
        if (ev.event === 'speaker') {
          if (bot.used) { act.end(); renderMd(bot.body, bot.text || '', false); bot = addBot(); act = activity(bot.body.parentNode); }
          bot.used = true; if (window.markSpeaker) window.markSpeaker(bot, ev.id, ev); act.set((ev.name || 'A bot') + ' is thinking…');
          continue;
        }
        if (ev.event === 'group_done') { continue; }
        if (ev.event === 'writes') { addUndo(bot.row, ev.paths); continue; }
        if (ev.event === 'saved') { const row = ev.role === 'user' ? userRow : bot.row; if (window.Reactions) Reactions.attach(row, ev.id); if (ev.ts) stampMessage(row, ev.ts); continue; }
        if (ev.event === 'reactions') { if (window.Reactions) Reactions.update(ev.id, ev.reactions); continue; }
        if (ev.event === 'done' && ev.speaker) { bot.text = ev.text || ''; bot.row.dataset.replyText = bot.text; renderMd(bot.body, bot.text, false); groupChips(bot, ev.chips); scrollDown(); continue; }
        if (ev.event === 'step') { act.set(ev.label || 'Working…'); if (ev.name) { labels[ev.name] = ev.label; setMood('working'); } }
        else if (ev.event === 'plan') { renderPlan(bot, ev); const next = (ev.steps || []).find((x) => x.status === 'pending'); act.set(next ? 'Step ' + next.number + ': ' + next.text : 'All steps done, checking…'); }
        else if (ev.event === 'terminal') { termEvent(bot, ev); if (ev.kind === 'start') act.set('Running in ' + (ev.shell || 'the terminal') + '…'); }
        else if (ev.event === 'team_plan') { act.set('Team is planning ' + ((ev.steps || []).length) + ' tasks'); }
        else if (ev.event === 'token') { act.set('Writing the reply…'); bot.text += ev.raw ? ev.text : ((bot.text ? ' ' : '') + ev.text); bot.row.dataset.replyText = bot.text; renderMd(bot.body, bot.text, true); scrollDown(); if (talk && !speaking) { speaking = true; voiceOpen = true; setMood('speaking'); } }
        else if (ev.event === 'tool_start') { /* shown by the live activity line */ }
        else if (ev.event === 'tool_end') {
          act.finish(labels[ev.name] || ev.name.replace(/_/g, ' '), ev.ok); act.set('Thinking…'); setMood('thinking');
          if (!ev.ok) { const c = chip(bot.chips, labels[ev.name] || ev.name); c.classList.add('bad'); c.querySelector('.d').textContent = ev.detail || ''; }
          if (ev.image) addImage(bot.chips.parentNode.querySelector('.md').parentNode, ev.image);
          if (ev.video) addVideo(bot.chips.parentNode.querySelector('.md').parentNode, ev.video);
        }
        else if (ev.event === 'card') { renderCard(ev.card); }
        else if (ev.event === 'model_switch') {
          chip(bot.chips, 'switched to ' + ev.model).classList.add('ok');
        }
        else if (ev.event === 'error') { addError(bot.body.parentNode, ev.text); setStatus(ev.text, true); }
        else if (ev.event === 'barge') { barge = ev.text; }
        else if (ev.event === 'done') {
          act.end();
          if (ev.text) { bot.text = ev.text; finalText = ev.text; }
          else finalText = bot.text;
          bot.row.dataset.replyText = bot.text || '';
          renderMd(bot.body, bot.text || '', false); if (!bot.text) bot.body.innerHTML = '';
          if (!String(bot.text || '').trim() && !bot.row.querySelector('img,video,.card,.chip')) bot.row.remove();   // 1.5.6: no empty bubbles
          if (talk && bot.text) { voiceOpen = true; setMood('speaking'); } else if (!voiceOpen) setMood('idle');
        }
        else if (ev.event === 'audio') { clip = ev.url; if (ev.note) toast(ev.note); }
        else if (ev.event === 'speech_end') { if (!clip) { voiceOpen = false; setMood('idle'); } }
      }
    }
  } catch (e) { addError(bot.body.parentNode, 'Connection to the agent failed: ' + (e && e.message || e)); }
  finally {
    runningSessions.delete(turnKey); syncRunningButton();
    const here = (session || '') === turnKey && bot.row && bot.row.isConnected;
    if (here) {
      act.end();
      renderMd(bot.body, bot.text || '', false); if (!bot.text) bot.body.innerHTML = '';
          if (!String(bot.text || '').trim() && !bot.row.querySelector('img,video,.card,.chip')) bot.row.remove();   // 1.5.6: no empty bubbles
      if (performance.now() - turnStarted > 8000 && document.hidden) finishPing();
      if (clip) await playClip(clip);
      voiceOpen = false; setMood('idle'); rowFace = null;
    } else if ((session || '') === turnKey) {
      openSession(turnKey);
    } else if (!running) {
      voiceOpen = false; if (!hands.state.listening) setMood('idle');
    }
    loadSessions();
    const barged = barge && (session || '') === turnKey;
    if (!barged && window.avatarMode && window.avatarMode.onTurnEnd) window.avatarMode.onTurnEnd();
    if (barged) { hands.state.turnRunning = false; send(barge, true); } else hands.turnEnded();
  }
}
$('#composer').onsubmit = (e) => {
  e.preventDefault();
  const target = replyTo && $('#reply-in') ? ($('#reply-in').value || '') : (session || '');
  if (runningSessions.has(target)) {
    const typed = $('#t').value.trim();
    if (target === (session || '') && typed) { $('#t').value = ''; autosize(); syncRunningButton(); sideSend(typed); return; }
    if (target === (session || '')) stop(); else setStatus('That chat is still replying.', true);
    return;
  }
  const text = $('#t').value.trim(); const ready = Attach.ready();
  if (Attach.busy()) { setStatus('Wait for the files to finish uploading.', true); return; }
  if (!text && !ready.length) return; $('#t').value = ''; autosize(); Attach.clear(); send(text, false, ready);
};
// 1.4.15: message while it works. Answered at once from the task's live state; the task keeps running and adjusts.
const sideIds = new Set();
function sideRows(userText, replyText, ids) {
  const u = addUser(userText); u.classList.add('side');
  const b = addBot(); b.row.classList.add('side'); b.text = replyText || ''; renderMd(b.body, b.text || '…', false);
  (ids || []).forEach((i) => i && sideIds.add(i));
  return b;
}
async function sideSend(text) {
  const u = addUser(text); u.classList.add('side');
  const b = addBot(); b.row.classList.add('side'); renderMd(b.body, '…', false);
  try {
    const r = await api('/api/chat_side', { session: session || '', text });
    if (r && r.ok) { sideIds.add(r.user_id); sideIds.add(r.id); b.text = r.reply; renderMd(b.body, r.reply, false); if (r.kind === 'stop') setStatus('Stopped'); }
    else { b.row.remove(); u.remove(); send(text); }   // the task just ended: send it normally
  } catch (e) { renderMd(b.body, 'Could not reach the task: ' + (e && e.message || e), false); }
  scrollDown();
}
window.pbSideRows = sideRows; window.pbSideIds = sideIds;
// 1.4.9: attach pictures/files: button (PC + phone app file chooser), paste, drag and drop.
const Attach = (() => {
  const items = []; const tray = $('#att-tray');
  function draw() {
    tray.innerHTML = ''; tray.hidden = !items.length;
    items.forEach((it, i) => {
      const c = document.createElement('span'); c.className = 'att' + (it.state === 'busy' ? ' busy' : '') + (it.state === 'bad' ? ' bad' : '');
      if (it.preview) { const im = document.createElement('img'); im.src = it.preview; c.appendChild(im); }
      const n = document.createElement('span'); n.className = 'n'; n.textContent = it.state === 'bad' ? it.error : (it.state === 'busy' ? 'Uploading ' : '') + it.name; c.appendChild(n);
      const x = document.createElement('button'); x.type = 'button'; x.className = 'x'; x.textContent = '\u00d7'; x.title = 'Remove';
      x.onclick = () => { if (it.preview) URL.revokeObjectURL(it.preview); items.splice(i, 1); draw(); }; c.appendChild(x);
      tray.appendChild(c);
    });
  }
  async function add(fileList) {
    for (const f of Array.from(fileList || [])) {
      if (items.length >= 10) { setStatus('Up to 10 files per message.', true); break; }
      const name = f.name || ('pasted-' + Date.now() + '.' + ((f.type || 'image/png').split('/')[1] || 'png'));
      const isVid = /^video\//.test(f.type || '') || /\.(mp4|webm|mov|mkv|m4v|avi)$/i.test(name);
      const it = { name, state: 'busy', preview: /^image\//.test(f.type) ? URL.createObjectURL(f) : '' }; items.push(it); draw();
      const cap = isVid ? 100 : 15;
      if (f.size > cap * 1024 * 1024) { it.state = 'bad'; it.error = name + ' is over ' + cap + ' MB'; draw(); continue; }
      try {
        const r = await (await fetch('/api/upload', { method: 'POST', headers: { 'Content-Type': 'application/octet-stream', 'X-File-Name': encodeURIComponent(name) }, body: f })).json();
        if (r.ok) Object.assign(it, { state: 'ok', id: r.id, kind: r.kind, url: r.url, name: r.name }); else Object.assign(it, { state: 'bad', error: r.error || 'Upload failed' });
      } catch (e) { Object.assign(it, { state: 'bad', error: 'Upload failed: ' + (e.message || e) }); }
      draw();
    }
  }
  return {
    add, busy: () => items.some((i) => i.state === 'busy'),
    ready: () => items.filter((i) => i.state === 'ok').map((i) => ({ id: i.id, name: i.name, kind: i.kind, url: i.url })),
    clear: () => { items.forEach((i) => i.preview && URL.revokeObjectURL(i.preview)); items.length = 0; draw(); },
  };
})();
$('#attach').onclick = (e) => {
  const menu = $('#plus-menu');
  if (menu && document.body.classList.contains('grok-skin')) {
    e.stopPropagation();
    menu.hidden = !menu.hidden;
    return;
  }
  $('#att-file').click();
};
$('#att-file').onchange = (e) => { Attach.add(e.target.files); e.target.value = ''; };
const anyF = $('#att-file-any'), imgF = $('#att-file-img'), vidF = $('#att-file-vid');
if (anyF) anyF.onchange = (e) => { Attach.add(e.target.files); e.target.value = ''; };
if (imgF) imgF.onchange = (e) => { Attach.add(e.target.files); e.target.value = ''; };
if (vidF) vidF.onchange = (e) => { Attach.add(e.target.files); e.target.value = ''; };
$('#t').addEventListener('paste', (e) => { const fs = e.clipboardData && e.clipboardData.files; if (fs && fs.length) { e.preventDefault(); Attach.add(fs); } });
let dragDepth = 0;
document.addEventListener('dragenter', (e) => { if (e.dataTransfer && Array.from(e.dataTransfer.types || []).includes('Files')) { dragDepth++; document.body.classList.add('dropping'); } });
document.addEventListener('dragleave', () => { dragDepth = Math.max(0, dragDepth - 1); if (!dragDepth) document.body.classList.remove('dropping'); });
document.addEventListener('dragover', (e) => { if (e.dataTransfer && Array.from(e.dataTransfer.types || []).includes('Files')) e.preventDefault(); });
document.addEventListener('drop', (e) => { if (!e.dataTransfer || !e.dataTransfer.files.length) return; e.preventDefault(); dragDepth = 0; document.body.classList.remove('dropping'); Attach.add(e.dataTransfer.files); });
function autosize() { const t = $('#t'); t.style.height = 'auto'; t.style.height = Math.min(t.scrollHeight, 200) + 'px'; }
$('#t').addEventListener('input', autosize);
$('#t').addEventListener('input', () => { if (running) syncRunningButton(); });
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
// 1.4.8: phone voice. On the phone/remote page the PC microphone is useless, so listen on the
// phone itself (browser speech recognition over the https tunnel); replies already play here.
const ON_PC = /^(127\.0\.0\.1|localhost)$/.test(location.hostname);
const PhoneSR = window.SpeechRecognition || window.webkitSpeechRecognition;
let phoneRec = null;
function phoneListen() {
  if (!PhoneSR) { setStatus('Voice typing is not available in this browser. Use the keyboard mic, or the Ped Bot app.', true); return; }
  if (phoneRec) { try { phoneRec.stop(); } catch (e) {} return; }
  const r = new PhoneSR(); phoneRec = r;
  r.lang = navigator.language || 'en-IN'; r.interimResults = false; r.maxAlternatives = 1;
  r.onstart = () => { $('#mic').classList.add('on'); waveOn(true); setStatus('Listening…'); setMood('listening'); };
  r.onresult = (e) => { const t = ((e.results[0] || [])[0] || {}).transcript || ''; if (t.trim()) send(t.trim(), true); };
  r.onerror = (e) => setStatus(e.error === 'not-allowed' ? 'Allow the microphone for this page, then tap the mic again.' : (e.error === 'no-speech' ? "Didn't hear anything. Tap the mic and speak." : 'Voice error: ' + e.error), true);
  r.onend = () => { phoneRec = null; $('#mic').classList.remove('on'); waveOn(false); if (!running) setMood('idle'); };
  try { r.start(); } catch (e) { phoneRec = null; setStatus('Could not start voice: ' + e.message, true); }
}
$('#mic').onclick = () => { stopClip(); if (running) stop(); if (ON_PC) hands.listen(true); else phoneListen(); };
const setupBtn = $('#setup-check');
if (setupBtn) setupBtn.onclick = async () => { const o = $('#setup-out'); o.hidden = false; o.textContent = 'Checking…'; try { o.textContent = (await (await fetch('/api/checklist')).json()).message; } catch (e) { o.textContent = 'Could not check: ' + e.message; } };
document.addEventListener('keydown', (e) => {
  const tag = document.activeElement.tagName;
  if (e.code === 'Space' && tag !== 'TEXTAREA' && tag !== 'INPUT' && tag !== 'SELECT' && !e.repeat) { e.preventDefault(); if (running) stop(); if (ON_PC) hands.listen(true); else phoneListen(); }
  if (e.key === 'Escape') closeSettings();
});
function setHands(on) { $('#hands').classList.toggle('toggled', on); $('#hands2').checked = on; hands.setEnabled(on); }
window.pedroVoice = {
  send: (text) => send(text, true),
  stop: () => stop(),
  listen: () => { stopClip(); if (running) stop(); if (ON_PC) hands.listen(true); else phoneListen(); },
  setHands: setHands,
  handsOn: () => hands.state.enabled,
  onPc: () => ON_PC,
  running: () => running,
};
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
let rulesYamlDirty = false;
let rulesCatalog = { confirm_categories: [], defaults: {} };
function ruleRow(value) {
  const row = document.createElement('div'); row.className = 'rule-row';
  const input = document.createElement('input'); input.type = 'text'; input.value = value || '';
  const del = document.createElement('button'); del.type = 'button'; del.className = 'rule-del'; del.title = 'Remove'; del.textContent = '×';
  del.onclick = () => { row.remove(); rulesYamlDirty = false; };
  input.oninput = () => { rulesYamlDirty = false; };
  row.append(input, del); return row;
}
function fillRuleList(id, items) {
  const box = document.getElementById(id); if (!box) return;
  box.innerHTML = '';
  (items || []).forEach((v) => { const s = String(v || '').trim(); if (s) box.appendChild(ruleRow(s)); });
}
function readRuleList(id) {
  return Array.from(document.querySelectorAll('#' + id + ' .rule-row input')).map((el) => el.value.trim()).filter(Boolean);
}
function bindRuleAdd(formId, listId) {
  const form = document.getElementById(formId); if (!form) return;
  form.onsubmit = (e) => {
    e.preventDefault();
    const inp = form.querySelector('input'); const v = (inp && inp.value || '').trim();
    if (!v) return;
    const box = document.getElementById(listId); if (box) box.appendChild(ruleRow(v));
    if (inp) { inp.value = ''; inp.focus(); }
    rulesYamlDirty = false;
  };
}
function fillRuleChecks(id, items, selected) {
  const box = document.getElementById(id); if (!box) return;
  const on = new Set((selected || []).map((x) => String(x)));
  box.innerHTML = '';
  (items || []).forEach((item) => {
    const lab = document.createElement('label'); lab.className = 'rule-check';
    const cb = document.createElement('input'); cb.type = 'checkbox'; cb.value = item.id; cb.checked = on.has(item.id);
    cb.onchange = () => { rulesYamlDirty = false; };
    lab.append(cb, document.createTextNode(item.label || item.id));
    box.appendChild(lab);
  });
}
function readRuleChecks(id) {
  return Array.from(document.querySelectorAll('#' + id + ' input[type=checkbox]:checked')).map((el) => el.value);
}
function fillProtectChecks(selected) {
  const box = $('#rule-protect'); if (!box) return;
  const labels = {
    never_delete_drive_root: 'Never delete a drive root',
    never_delete_home_folder: 'Never delete your home folder',
    never_delete_agent_folder: 'Never delete Ped Bot itself',
    archive_path_safety: 'Block unsafe zip paths',
    git_unstage_secrets: 'Keep secrets out of git commits',
    skill_typing_stays_local: 'Keep skill typing on this PC'
  };
  const src = selected && typeof selected === 'object' ? selected : ((rulesCatalog.defaults || {}).protect || {});
  box.innerHTML = '';
  Object.keys(labels).forEach((key) => {
    const lab = document.createElement('label'); lab.className = 'rule-check';
    const cb = document.createElement('input'); cb.type = 'checkbox'; cb.dataset.key = key; cb.checked = src[key] !== false;
    cb.onchange = () => { rulesYamlDirty = false; };
    lab.append(cb, document.createTextNode(labels[key]));
    box.appendChild(lab);
  });
}
function readProtectChecks() {
  const out = {};
  document.querySelectorAll('#rule-protect input[type=checkbox]').forEach((el) => { out[el.dataset.key] = !!el.checked; });
  return out;
}
function fillRulesEditor(payload) {
  const data = payload.data || {};
  const defaults = payload.defaults || {};
  const paths = Object.assign({}, defaults.paths || {}, data.paths || {});
  const files = Object.assign({}, defaults.files || {}, data.files || {});
  const tools = Object.assign({}, data.tools || {});
  const confirm = Object.assign({}, defaults.confirm || {}, data.confirm || {});
  fillRuleList('rule-instructions', data.instructions || []);
  fillRuleList('rule-paths-allowed', paths.allowed || []);
  fillRuleList('rule-paths-blocked', paths.blocked || []);
  fillRuleList('rule-ext-blocked', files.blocked_extensions || []);
  fillRuleList('rule-tools-blocked', tools.blocked || []);
  fillRuleList('rule-confirm-extra', confirm.extra_tools || []);
  const on = $('#rule-confirm-on'); if (on) on.checked = confirm.enabled !== false;
  const exe = $('#rule-allow-exe'); if (exe) exe.checked = !!files.allow_exe_writes;
  fillRuleChecks('rule-confirm-cats', payload.confirm_categories || rulesCatalog.confirm_categories, confirm.categories || []);
  fillProtectChecks(Object.assign({}, defaults.protect || {}, data.protect || {}));
}
function collectRulesPatch() {
  const protect = readProtectChecks();
  return {
    instructions: readRuleList('rule-instructions'),
    paths: { allowed: readRuleList('rule-paths-allowed'), blocked: readRuleList('rule-paths-blocked') },
    files: { allow_exe_writes: !!($('#rule-allow-exe') && $('#rule-allow-exe').checked), blocked_extensions: readRuleList('rule-ext-blocked') },
    tools: { blocked: readRuleList('rule-tools-blocked') },
    confirm: {
      enabled: !!($('#rule-confirm-on') && $('#rule-confirm-on').checked),
      categories: readRuleChecks('rule-confirm-cats'),
      extra_tools: readRuleList('rule-confirm-extra')
    },
    protect
  };
}
async function loadRules() {
  const r = await api('/api/rules');
  rulesCatalog = { confirm_categories: r.confirm_categories || [], defaults: r.defaults || {} };
  if ($('#rules')) $('#rules').value = r.text || '';
  if ($('#rulespath')) $('#rulespath').textContent = r.path || '';
  if ($('#rulesmsg')) $('#rulesmsg').textContent = '';
  fillRulesEditor(r);
  rulesYamlDirty = false;
}
$('#reloadrules').onclick = loadRules;
if ($('#rules')) $('#rules').addEventListener('input', () => { rulesYamlDirty = true; });
['rule-confirm-on', 'rule-allow-exe'].forEach((id) => {
  const el = document.getElementById(id); if (el) el.onchange = () => { rulesYamlDirty = false; };
});
['rule-add-instructions', 'rule-add-allowed', 'rule-add-blocked', 'rule-add-ext', 'rule-add-tools', 'rule-add-extra'].forEach((id, i) => {
  bindRuleAdd(id, ['rule-instructions', 'rule-paths-allowed', 'rule-paths-blocked', 'rule-ext-blocked', 'rule-tools-blocked', 'rule-confirm-extra'][i]);
});
$('#saverules').onclick = async () => {
  const body = rulesYamlDirty ? { text: $('#rules').value } : { patch: collectRulesPatch() };
  const r = await api('/api/rules', body);
  const m = $('#rulesmsg'); m.textContent = r.ok ? 'Saved ✓' : 'Error: ' + r.error; m.style.color = r.ok ? 'var(--ok)' : 'var(--bad)';
  if (r.ok) loadRules();
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

$('#backup-save') && ($('#backup-save').onclick = async () => { const v = $('#backup-key').value.trim(); if (!v) return; const r = await api('/api/setup', { groq_api_key: v }); $('#backup-key').value = ''; $('#backup-msg').textContent = r.ok ? (r.backup_model ? ' Saved.' : ' Not saved.') : (' ' + (r.error || 'Could not save.')); });
$('#providers-save') && ($('#providers-save').onclick = async () => {
  const msg = $('#providers-msg');
  const gemini = ($('#gemini-keys').value || '').split(/[\s,;]+/).map((s) => s.trim()).filter(Boolean).join(',');
  const body = {};
  if (gemini) body.gemini_api_keys = gemini;
  [['openrouter-key', 'openrouter_api_key'], ['cerebras-key', 'cerebras_api_key'], ['nvidia-key', 'nvidia_api_key']].forEach(([id, key]) => {
    const v = ($(('#' + id)).value || '').trim(); if (v) body[key] = v;
  });
  if (!Object.keys(body).length) { msg.textContent = ' Paste a key first.'; return; }
  const r = await api('/api/setup', body);
  if (!r.ok) { msg.textContent = ' ' + (r.error || 'Could not save.'); return; }
  $('#gemini-keys').value = '';
  ['openrouter-key', 'cerebras-key', 'nvidia-key'].forEach((id) => { $('#' + id).value = ''; });
  const saved = [r.gemini_keys > 1 ? 'Gemini' : '', r.openrouter ? 'OpenRouter' : '', r.cerebras ? 'Cerebras' : '', r.nvidia ? 'NVIDIA' : ''].filter(Boolean);
  msg.textContent = saved.length ? (' Saved ' + saved.join(', ') + '.') : ' Not saved.';
});
$('#undo-last') && ($('#undo-last').onclick = async () => { const r = await api('/api/undo', {}); const el = $('#undo-msg'); if (el) el.textContent = ' ' + (r.ok ? (r.message || 'Undone.') : (r.error || 'Nothing to undo.')); });


// 1.4.8: Approve / Deny bar for a waiting send/delete (works in the phone app too; it never sends by itself)
(function approvalBar() {
  const bar = document.createElement('div');
  bar.id = 'approve-bar';
  bar.className = 'approve-bar';
  bar.style.display = 'none';
  bar.innerHTML = '<div id="approve-text"></div><div class="approve-btns"><button id="approve-yes" type="button" class="pa-btn primary">Approve</button><button id="approve-no" type="button" class="pa-btn danger">Deny</button></div>';
  // 1.4.19: sits in the page flow right above the composer (never floats over messages)
  const composer = document.querySelector('#composer, form.composer, .composer');
  if (composer && composer.parentNode) composer.parentNode.insertBefore(bar, composer); else document.body.appendChild(bar);
  // 1.4.19: answer the exact request id (never a typed yes into whatever chat is open); one tap, no repeats
  const answered = new Set();
  const answer = async (yes) => {
    const id = bar.dataset.id || ''; bar.style.display = 'none';
    if (!id) return; answered.add(id);
    bar.querySelectorAll('button').forEach((b) => { b.disabled = true; });
    try {
      const r = await api('/api/pending/answer', { id, approve: !!yes });
      if (r && r.text && r.session === session) { const row = addBot().row; renderMd(row.querySelector('.md'), r.text, false); scrollDown(); }
    } catch (e) {}
    bar.querySelectorAll('button').forEach((b) => { b.disabled = false; });
  };
  bar.querySelector('#approve-yes').onclick = () => answer(true);
  bar.querySelector('#approve-no').onclick = () => answer(false);
  setInterval(async () => {
    try {
      const r = await (await fetch('/api/pending', { cache: 'no-store' })).json();
      if (r.pending && document.querySelector('.pa-card.open[data-kind="approval"]')) { bar.style.display = 'none'; return; }   // the card in the chat is enough
      if (r.pending && answered.has(r.pending.id)) { bar.style.display = 'none'; return; }
      if (r.pending) {
        bar.dataset.id = r.pending.id || '';
        const o = r.pending.order; const t = bar.querySelector('#approve-text');
        if (o) {   // 1.4.10: order summary card; Approve is the only way an order is placed
          const key = JSON.stringify(o); if (t.dataset.k !== key) {
            t.dataset.k = key; t.innerHTML = '';
            const h = document.createElement('b'); h.textContent = 'Place this order on ' + o.platform + '?'; t.appendChild(h);
            const rows = [['Item', o.item], ['Seller', o.seller], ['Qty', o.quantity], ['Price', o.item_price], ['Delivery / fees', o.delivery_and_fees],
                          ['Total', o.total + (o.total_on_page ? '' : '  (not found on page, check!)')], ['Address', o.address], ['Payment', o.payment_method]];
            rows.forEach(([k, v]) => { if (v === undefined || v === null || v === '') return; const d = document.createElement('div'); d.textContent = k + ': ' + v; t.appendChild(d); });
            if (o.screenshot_url) { const im = document.createElement('img'); im.src = o.screenshot_url; im.style.cssText = 'max-width:100%;max-height:180px;border-radius:8px;margin-top:6px;cursor:zoom-in'; im.onclick = () => window.open(o.screenshot_url, '_blank'); t.appendChild(im); }
          }
          bar.style.flexDirection = 'column'; bar.style.alignItems = 'stretch';
        } else { t.dataset.k = ''; t.textContent = 'Waiting for you: ' + (r.pending.label || 'an action'); bar.style.flexDirection = 'column'; bar.style.alignItems = 'stretch'; }
        bar.style.display = 'flex';
      }
      else bar.style.display = 'none';
    } catch (e) {}
  }, 2500);
})();


// ---------- live sync (1.4.14): the PC window and the phone show the same thing, live ----------
const CLIENT_ID = (() => { try { return sessionStorage.pbClient || (sessionStorage.pbClient = Math.random().toString(36).slice(2, 12)); } catch (e) { return Math.random().toString(36).slice(2, 12); } })();
(function liveSync() {
  if (!window.EventSource) return;
  let reloadTimer = null, listTimer = null, lastSeq = 0, es = null, watching = false;
  const reloadSoon = (tries) => { clearTimeout(reloadTimer); reloadTimer = setTimeout(() => { if (!running && session) openSession(session); else if (running && (tries || 0) < 240) reloadSoon((tries || 0) + 1); }, 250); };
  const listSoon = () => { clearTimeout(listTimer); listTimer = setTimeout(() => loadSessions(), 400); };
  function handle(ev) {
    if (ev.seq) lastSeq = Math.max(lastSeq, ev.seq);
    if (ev.event === 'theme') { if (window.pbThemeEvent) window.pbThemeEvent(ev); return; }
    if (ev.event === 'hello' || ev.event === 'resync') { if (ev.event === 'resync') { reloadSoon(); listSoon(); } return; }
    if (ev.event === 'changed' || ev.event === 'paused' || ev.event === 'resumed') { listSoon(); reloadSoon(); if (window.refreshRoutines) window.refreshRoutines(); return; }
    if (ev.event === 'update') {                                     // natural progress note (1.4.14)
      if (ev.session === session) { setLiveStep(ev.text); setStatus(ev.text); reloadSoon(); }
      listSoon(); return;
    }
    if (ev.origin && ev.origin === CLIENT_ID) return;            // this window started it and already shows it
    if (ev.event === 'saved') listSoon();
    if (!ev.session || ev.session !== session) { if (ev.session) { runningSessions.add(ev.session); markWorkingChats(); if (ev.event === 'speech_end' || ev.event === 'final') { runningSessions.delete(ev.session); markWorkingChats(); } } return; }
    if (ev.event === 'side') {   // a mid-task message from another window (PC <-> phone)
      if (!sideIds.has(ev.id)) { sideIds.add(ev.id); const row = ev.role === 'user' ? addUser(ev.text) : addBot().row; row.classList.add('side'); if (ev.role !== 'user') renderMd(row.querySelector('.md'), ev.text, false); scrollDown(); }
      return;
    }
    if (ev.event === 'token' || ev.event === 'step' || ev.event === 'tool_start' || ev.event === 'speaker') {
      watching = true; setMood('working');
      const label = ev.label || (ev.name ? ('Running ' + String(ev.name).replace(/_/g, ' ')) : 'Typing…');
      setLiveStep(stripStage(label));
    }
    if (ev.event === 'saved' || ev.event === 'done' || ev.event === 'reactions' || ev.event === 'card') reloadSoon();
    if (ev.event === 'speech_end' || ev.event === 'final' || ev.event === 'error') { if (watching) { watching = false; setMood('idle'); setLiveStep(''); } reloadSoon(); }
  }
  function connect() {
    try { if (es) es.close(); } catch (e) {}
    es = new EventSource('/api/live' + (lastSeq ? ('?since=' + lastSeq) : ''));
    es.onmessage = (m) => { try { handle(JSON.parse(m.data)); } catch (e) {} };
    es.onerror = () => { try { es.close(); } catch (e) {} setTimeout(connect, 2000); };   // reconnect + catch up with ?since=
  }
  connect();
  window.liveSyncClient = CLIENT_ID;
})();


// ---------- Safe mode / Pause all (1.4.14) ----------
let pausedNow = false;
function showPaused(on) {
  pausedNow = on; const b = $('#pause-all'); if (!b) return;
  b.textContent = on ? 'Resume' : 'Pause all'; b.classList.toggle('on', on);
  b.title = on ? 'Safe mode is on: everything is paused. Click to let bots act again.' : 'Safe mode: pause every bot, routine and task now';
  document.body.classList.toggle('safe-mode', on);
}
if ($('#pause-all')) $('#pause-all').onclick = async () => {
  const r = await api(pausedNow ? '/api/resume_all' : '/api/pause_all', {});
  showPaused(!!r.paused); setStatus(r.message || '');
};

// ---- 1.4.14: floating "jump to latest" button with a new-messages badge ----
(function jumpToLatest() {
  const log = $('#log'); if (!log) return;
  const btn = document.createElement('button'); btn.type = 'button'; btn.id = 'jump-latest'; btn.hidden = true;
  btn.title = 'Jump to latest'; btn.setAttribute('aria-label', 'Jump to the latest message');
  btn.innerHTML = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 5v14M5 12l7 7 7-7"/></svg><span class="jl-badge" hidden></span>';
  (log.parentNode || document.body).appendChild(btn);
  const badge = btn.querySelector('.jl-badge'); let fresh = 0;
  const GAP = 160;
  function away() { return log.scrollHeight - log.scrollTop - log.clientHeight > GAP; }
  function paint() {
    btn.hidden = !window.pbScrolledUp;
    badge.hidden = !fresh; badge.textContent = fresh > 99 ? '99+' : String(fresh);
  }
  function update() { window.pbScrolledUp = away(); if (!window.pbScrolledUp) fresh = 0; paint(); }
  log.addEventListener('scroll', update, { passive: true });
  window.addEventListener('resize', update);
  btn.onclick = () => { fresh = 0; window.pbScrolledUp = false; log.scrollTo({ top: log.scrollHeight, behavior: 'smooth' }); paint(); };
  new MutationObserver((muts) => {
    if (!log.children.length) { window.pbScrolledUp = false; fresh = 0; paint(); return; }
    let added = 0, mine = false;
    muts.forEach((m) => m.addedNodes.forEach((n) => { if (n.nodeType === 1 && n.classList.contains('row')) { added++; if (n.classList.contains('user')) mine = true; } }));
    if (!added) return;
    if (mine) { fresh = 0; window.pbScrolledUp = false; log.scrollTop = log.scrollHeight; paint(); return; }   // he just sent one
    if (window.pbScrolledUp) { fresh += added; paint(); }
  }).observe(log, { childList: true });
  window.pbJump = { update, get count() { return fresh; } };
})();

// 1.4.15: proactive check-ins setting (PC and phone)
(async function checkinsSetting() {
  const on = $('#checkins-on'), fq = $('#checkins-freq'); if (!on || !fq) return;
  try { const s = await api('/api/checkins'); on.checked = !!s.enabled; fq.value = s.frequency || 'normal'; fq.disabled = !s.enabled; } catch (e) {}
  const save = async () => { fq.disabled = !on.checked; const s = await api('/api/checkins', { enabled: on.checked, frequency: fq.value }); setStatus(s.enabled ? 'Check-ins on (' + s.frequency + ').' : 'Check-ins off.'); };
  on.onchange = save; fq.onchange = save;
})();

// Grok chrome: account menu, search, usage, plus menu. Original IDs stay wired above.
(function grokChrome() {
  if (!document.body.classList.contains('grok-skin')) return;
  const hide = (el) => { if (el) el.hidden = true; };
  const show = (el) => { if (el) el.hidden = false; };
  const acct = $('#btn-account'), menu = $('#acct-menu'), conn = $('#btn-connect');
  const searchOv = $('#search-ov'), usageOv = $('#usage-ov'), helpOv = $('#help-ov'), plus = $('#plus-menu');
  function closeMenus() { hide(menu); hide(plus); }
  if (acct) acct.onclick = (e) => { e.stopPropagation(); if (menu) menu.hidden = !menu.hidden; };
  if (conn) conn.onclick = () => { hide(menu); const t = document.querySelector('.tab[data-pane="p-more"]'); openSettings(); if (t) t.click(); };
  document.addEventListener('click', () => closeMenus());
  if (menu) menu.addEventListener('click', (e) => {
    e.stopPropagation();
    if (e.target.closest('button')) hide(menu);
  });
  if (plus) plus.addEventListener('click', (e) => e.stopPropagation());
  const upFile = $('#btn-upload-file'), upImg = $('#btn-upload-image'), upVid = $('#btn-upload-video'), recVid = $('#btn-record-video'), shot = $('#btn-screenshot');
  if (upFile) upFile.onclick = () => { hide(plus); ($('#att-file-any') || $('#att-file')).click(); };
  if (upImg) upImg.onclick = () => { hide(plus); ($('#att-file-img') || $('#att-file')).click(); };
  if (upVid) upVid.onclick = () => { hide(plus); ($('#att-file-vid') || $('#att-file-any') || $('#att-file')).click(); };
  if (recVid) recVid.onclick = () => { hide(plus); send('Record 10 seconds with the PC camera.'); };
  if (shot) shot.onclick = () => { hide(plus); send('Take a screenshot and tell me what is open.'); };
  const proj = $('#acct-projects'); if (proj) proj.onclick = () => {
    hide(menu);
    document.body.classList.add('side-open');
    const side = $('#side'); if (side) side.classList.add('show');
    if (window.loadGroups) window.loadGroups();
    const g = $('#groups'); if (g) g.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    const label = document.querySelector('.side-label.row-label');
    if (label) label.scrollIntoView({ block: 'nearest' });
    // Only open the new-project editor when there are no projects yet.
    const items = document.querySelectorAll('#groups .botitem');
    if (!items.length) {
      const ng = $('#newgroup'); if (ng) ng.click();
    }
  };
  const upd = $('#acct-updates'); if (upd) upd.onclick = () => { hide(menu); const t = document.querySelector('.tab[data-pane="p-more"]'); openSettings(); if (t) t.click(); const el = $('#upd-check'); if (el) el.scrollIntoView({ block: 'nearest' }); };
  const helpBtn = $('#acct-help'), helpClose = $('#help-close');
  if (helpBtn) helpBtn.onclick = () => { hide(menu); show(helpOv); };
  if (helpClose) helpClose.onclick = () => hide(helpOv);
  if (helpOv) helpOv.onclick = (e) => { if (e.target === helpOv) hide(helpOv); };
  const usageBtn = $('#acct-usage'), usageClose = $('#usage-close'), usageBody = $('#usage-body');
  async function loadUsage() {
    if (!usageBody) return;
    try {
      const d = await fetch('/api/usage').then((r) => r.json());
      usageBody.innerHTML = '<pre></pre>';
      usageBody.querySelector('pre').textContent = JSON.stringify(d, null, 2);
    } catch (err) { usageBody.innerHTML = '<pre>Could not load usage.</pre>'; }
  }
  if (usageBtn) usageBtn.onclick = () => { hide(menu); show(usageOv); loadUsage(); };
  if (usageClose) usageClose.onclick = () => hide(usageOv);
  if (usageOv) usageOv.onclick = (e) => { if (e.target === usageOv) hide(usageOv); };
  const searchBtn = $('#btn-search'), searchIn = $('#search-input'), searchOut = $('#search-results');
  function openSearch() { show(searchOv); if (searchIn) { searchIn.value = ''; searchIn.focus(); } if (searchOut) searchOut.innerHTML = ''; }
  if (searchBtn) searchBtn.onclick = openSearch;
  document.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); openSearch(); }
    if (e.key === 'Escape') { hide(searchOv); hide(usageOv); hide(helpOv); const adminOv = $('#admin-ov'); if (adminOv) adminOv.hidden = true; closeMenus(); }
  });
  if (searchOv) searchOv.onclick = (e) => { if (e.target === searchOv) hide(searchOv); };
  let searchTimer = 0;
  if (searchIn) searchIn.addEventListener('input', () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(async () => {
      const q = searchIn.value.trim();
      if (q.length < 2) { if (searchOut) searchOut.innerHTML = ''; return; }
      try {
        const d = await fetch('/api/search?q=' + encodeURIComponent(q)).then((r) => r.json());
        const bits = [];
        (d.bots || []).forEach((b) => bits.push({ label: 'Bot · ' + b.name, go: () => { hide(searchOv); const el = document.querySelector('#bots .botitem[data-id="' + b.id + '"]'); if (el) el.click(); } }));
        (d.projects || []).forEach((g) => bits.push({ label: 'Project · ' + g.name, go: () => { hide(searchOv); document.body.classList.add('side-open'); const el = document.querySelector('#groups .botitem[data-id="' + g.id + '"]'); if (el) el.click(); else if (window.openSession) openSession(g.session); } }));
        (d.chats || []).forEach((c) => bits.push({ label: 'Chat · ' + c.title, go: () => { hide(searchOv); if (window.openSession) openSession(c.session); } }));
        (d.messages || []).forEach((m) => bits.push({ label: (m.role || 'msg') + ' · ' + m.preview, go: () => { hide(searchOv); if (window.openSession) openSession(m.session); } }));
        if (searchOut) {
          searchOut.innerHTML = '';
          bits.slice(0, 30).forEach((hit) => { const b = document.createElement('button'); b.type = 'button'; b.textContent = hit.label; b.onclick = hit.go; searchOut.appendChild(b); });
          if (!bits.length) searchOut.textContent = 'No matches.';
        }
      } catch (err) { if (searchOut) searchOut.textContent = 'Search failed.'; }
    }, 180);
  });
  const secBtn = $('#btn-new-section');
  if (secBtn) secBtn.onclick = async () => {
    const name = window.prompt('Section name');
    if (!name) return;
    try {
      const cur = await fetch('/api/sidebar').then((r) => r.json());
      const sections = cur.sections || [];
      sections.push({ id: 'sec-' + Date.now().toString(36), name: name, collapsed: false, bots: [] });
      await fetch('/api/sidebar', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ sections, unassigned: cur.unassigned || [] }) });
      if (window.renderBots) window.renderBots();
    } catch (err) { setStatus('Could not add section.', true); }
  };
  const rz = $('#side-resizer'), side = $('#side');
  if (rz && side) {
    rz.addEventListener('pointerdown', (e) => {
      e.preventDefault(); rz.setPointerCapture(e.pointerId);
      const startX = e.clientX, startW = side.getBoundingClientRect().width;
      const move = (ev) => { side.style.width = Math.max(200, Math.min(360, startW + (ev.clientX - startX))) + 'px'; };
      const up = () => { rz.releasePointerCapture(e.pointerId); window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', up); };
      window.addEventListener('pointermove', move); window.addEventListener('pointerup', up);
    });
  }
})();
