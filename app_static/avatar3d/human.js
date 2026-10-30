// 1.8.1 realistic full-body avatars (male + female) with visemes, blinks and expressions.
// Engine: TalkingHead (MIT, Mika Suominen) on three.js, all files bundled on this PC.
// Models: male = MPFB/MakeHuman base human (CC0); female = Ready Player Me "brunette" sample
// (CC BY-NC 4.0, personal use). Both carry ARKit + Oculus viseme blendshapes and a Mixamo rig.
// Same commands as 1.8.0: /api/avatar/plan -> chained steps (action, expression, say, to).
import { TalkingHead } from './th/talkinghead.mjs';

const P = window.parent && window.parent !== window ? window.parent : window;
const api = (path, body) => P.fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) }).then((r) => r.json());
const $ = (s) => document.querySelector(s);
const status = (t) => { $('#status').textContent = t; };
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const MODELS = {
  male: { url: './th/models/male.glb?v=181', body: 'M', voice: 'Puck' },
  female: { url: './th/models/mpfb.glb?v=181', body: 'F', voice: 'Sulafat' },
};
const MOOD = { neutral: 'neutral', happy: 'happy', sad: 'sad', angry: 'angry', surprised: 'fear' };
const FACE = { surprised: '😮', happy: '😊', sad: '😢', angry: '😡' };
let gender = localStorage.pbAvatarGender === 'female' ? 'female' : 'male';
let head = null, runId = 0, x = 0, loading = false;

head = new TalkingHead($('#stage'), {
  ttsEndpoint: 'none', lipsyncModules: ['en'], lipsyncLang: 'en', cameraView: 'full', cameraRotateEnable: true,
  avatarMood: 'neutral', modelFPS: 30, cameraZoomEnable: true, cameraPanEnable: false,
});
window.__head = head;

async function load() {
  if (loading) return; loading = true; status('Loading the avatar…');
  const m = MODELS[gender];
  try {
    await head.showAvatar({ url: m.url, body: m.body, avatarMood: 'neutral', lipsyncLang: 'en' }, (ev) => {
      if (ev.lengthComputable) status('Loading the avatar… ' + Math.round(ev.loaded / ev.total * 100) + '%');
    });
    tune(); x = 0; status('Tell me what to do — or tap the floor.');
    const l = $('#load'); if (l) l.remove();
    window.__avatarReady = true;
  } catch (e) { status('Could not load the avatar: ' + e.message); }
  loading = false;
  $('#g-male').classList.toggle('on', gender === 'male'); $('#g-female').classList.toggle('on', gender === 'female');
}
// Tune the free base models toward Pedro's references (deep brown skin, short black hair,
// dark outfit, white sneakers). Colour multiplies on the original textures only - not a scan.
function tune() {
  const SKIN = gender === 'male' ? 0x6a4030 : 0x74472f;
  head.armature.traverse((o) => {
    if (!o.isMesh) return;
    [].concat(o.material).forEach((m) => {
      if (gender === 'male') {   // the male is built from CC0 MakeHuman assets already textured toward Pedro
        const n = (m.name || '') + ' ' + o.name;
        if (/short0|eyebrow|eyelash/i.test(n)) { m.transparent = true; m.alphaTest = 0.3; m.depthWrite = true; }
        else if (/high-poly/i.test(n)) { m.transparent = false; m.alphaTest = 0.5; m.depthWrite = true; }   // eyes: cut-out cornea shell (MASK)
        else if (!/high-poly/i.test(n)) { m.transparent = false; m.alphaTest = 0; m.depthWrite = true; }   // exported as BLEND; opaque fixes see-through faces
        if (/short0|eyebrow/i.test(n)) m.color.setHex(0x2a2220);
        m.needsUpdate = true;
        return;
      }
      const n = (m.name || '') + ' ' + o.name;
      if (/body|head|skin|high-poly/i.test(n) && !/eye|teeth|tongue|lash/i.test(n)) m.color.setHex(SKIN);
      else if (/hair|ponytail|eyebrow/i.test(n)) m.color.setHex(0x1a1412);
      else if (/shoe|footwear/i.test(n)) m.color.setHex(0xffffff);
      else if (/look|outfit|casualsuit/i.test(n)) m.color.setHex(0x5d6a60);
      m.needsUpdate = true;
    });
  });
}
load();
$('#g-male').onclick = async () => { if (gender === 'male') return; gender = 'male'; localStorage.pbAvatarGender = gender; window.__avatarReady = false; await load(); run([{ action: 'Wave', expression: 'happy', say: "Hey Pedro, it's me.", to: '', seconds: 2 }]); };
$('#g-female').onclick = async () => { if (gender === 'female') return; gender = 'female'; localStorage.pbAvatarGender = gender; window.__avatarReady = false; await load(); run([{ action: 'Wave', expression: 'happy', say: 'Hi Pedro! Nice to meet you.', to: '', seconds: 2 }]); };
$('#g-robot').onclick = () => { location.href = './index.html'; };
$('#close').onclick = () => { try { head.stopSpeaking(); } catch (e) {} if (P.pbCloseAvatar) P.pbCloseAvatar(); };

// ---- speech with lip sync: Gemini voice audio + estimated word timings -> visemes ----
let actx = null;
async function speak(text, tone) {
  if (!text) return;
  $('#say').textContent = text; $('#say').style.display = 'block';
  try {
    const r = await api('/api/speak_text', { text, gender, tone: tone || '', name: MODELS[gender].voice });
    if (!r.ok || !r.url) return;
    const buf = await (await P.fetch(r.url)).arrayBuffer();
    actx = actx || head.audioCtx || new AudioContext();
    const audio = await (head.audioCtx || actx).decodeAudioData(buf);
    const words = text.split(/\s+/).filter(Boolean); const total = audio.duration * 1000;
    const chars = words.reduce((a, w) => a + w.length + 1, 0); let t = 80; const wtimes = [], wdurations = [];
    words.forEach((w) => { const d = (total - 160) * (w.length + 1) / chars; wtimes.push(t); wdurations.push(d * 0.9); t += d; });
    await new Promise((ok) => { head.speakAudio({ audio, words, wtimes, wdurations }, null, null); head.speakMarker(ok); setTimeout(ok, total + 1500); });
  } catch (e) { /* speech optional */ } finally { setTimeout(() => { $('#say').style.display = 'none'; }, 500); }
}

// ---- actions ----
function anim(name) { try { const a = head.animEmojis[name]; if (a) head.animQueue.push(head.animFactory(a)); } catch (e) {} }
async function moveTo(tx, running) {
  const arm = head.armature; if (!arm) return;
  const from = arm.position.x, dist = Math.abs(tx - from); if (dist < 0.05) return;
  const dir = Math.sign(tx - from); arm.rotation.y = dir * Math.PI / 2;
  head.playAnimation('./th/anims/walking.fbx?v=181', null, 60, 0, 0.01);
  const speed = running ? 1.6 : 0.8, t0 = performance.now(), dur = dist / speed * 1000;
  await new Promise((ok) => {
    const step = () => { const k = Math.min(1, (performance.now() - t0) / dur); arm.position.x = from + (tx - from) * k; if (k < 1) requestAnimationFrame(step); else ok(); };
    step();
  });
  head.stopAnimation(); arm.rotation.y = 0; x = tx;
}
// keep within the camera frame on a narrow phone screen
const SPAN = () => Math.max(0.25, Math.min(1.0, 0.62 * innerWidth / innerHeight));
const PLACES = { center: 0, get left() { return -SPAN(); }, get right() { return SPAN(); }, front: 0, back: 0 };
async function jump() {
  const arm = head.armature; const y0 = arm.position.y; head.playPose('wide', null, 1.2);
  for (let i = 0; i < 2; i++) {
    const t0 = performance.now();
    await new Promise((ok) => { const f = () => { const k = (performance.now() - t0) / 520; arm.position.y = y0 + Math.max(0, Math.sin(Math.min(1, k) * Math.PI)) * 0.35; if (k < 1) requestAnimationFrame(f); else { arm.position.y = y0; ok(); } }; f(); });
    await wait(120);
  }
}
async function dance(sec) {
  const poses = ['hip', 'side', 'wide', 'turn']; const end = performance.now() + sec * 1000; let i = 0;
  head.setMood('happy');
  while (performance.now() < end) { head.playPose(poses[i % poses.length], null, 0.9); head.playGesture(i % 2 ? 'handup' : 'shrug', 0.8, i % 2 === 0); await wait(700); i++; }
  head.playPose('straight', null, 1);
}
async function doAction(a, sec) {
  switch (a) {
    case 'Wave': anim('👋'); head.playGesture('handup', 2.2); break;
    case 'ThumbsUp': head.playGesture('thumbup', 2.4); break;
    case 'Yes': anim('yes'); break;
    case 'No': anim('no'); break;
    case 'Punch': head.playGesture('index', 1.6); break;
    case 'Sitting': head.playPose('sitting', null, Math.max(4, sec)); break;
    case 'Standing': head.playPose('straight', null, 1); break;
    case 'Death': head.playPose('kneel', null, Math.max(3, sec)); head.setMood('sad'); break;
    case 'Jump': await jump(); return;
    case 'Dance': await dance(Math.max(3, sec)); return;
    case 'Running': case 'Walking': await moveTo(x === 0 ? (Math.random() < 0.5 ? -SPAN() : SPAN()) : 0, a === 'Running'); return;
    default: head.playPose('straight', null, 1);
  }
  await wait(Math.max(1.5, sec) * 1000);
}
const TONE = { happy: 'excited', sad: 'sad', angry: 'serious', surprised: 'excited', neutral: '' };
async function run(steps) {
  const id = ++runId;
  for (const s of steps) {
    if (id !== runId) return;
    const e = s.expression || 'neutral'; head.setMood(MOOD[e] || 'neutral'); if (FACE[e]) head.speakEmoji(FACE[e]);
    status(s.action + (e !== 'neutral' ? ' · ' + e : ''));
    const talk = speak(s.say, TONE[e]);
    if (s.to && PLACES[s.to] != null) await moveTo(PLACES[s.to], s.action === 'Running');
    else if (s.to === 'here' && lastX != null) await moveTo(lastX, false);
    if (s.to && (s.action === 'Walking' || s.action === 'Running')) { await talk; continue; }
    await Promise.all([doAction(s.action, s.seconds || 3), talk]);
  }
  if (id !== runId) return; head.setMood('neutral'); status('Ready — what next?');
}
async function command(text) {
  text = String(text || '').trim(); if (!text || !window.__avatarReady) return;
  status('Thinking…');
  let plan; try { plan = await api('/api/avatar/plan', { command: text, gender }); } catch (e) { plan = null; }
  if (!plan || !plan.ok) { status((plan && plan.error) || 'Could not plan that.'); return; }
  run(plan.steps);
}
window.avatarCommand = command; window.avatarRun = run;

// tap left/right of the avatar to walk there
let lastX = null;
$('#stage').addEventListener('pointerup', (e) => {
  if (e.target.closest && e.target.closest('button')) return;
  if (e.clientY < innerHeight * 0.55) return; // floor area only
  lastX = ((e.clientX / innerWidth) - 0.5) * 2 * SPAN(); runId++; moveTo(lastX, Math.abs(lastX - x) > 1.6).then(() => status('Ready — what next?'));
});

['Wave', 'Dance', 'Sit down', 'Jump', 'Walk left', 'Run right', 'Thumbs up', 'Look surprised', 'Act sad then cheer up', 'Say hi to Pedro'].forEach((t) => {
  const b = document.createElement('button'); b.type = 'button'; b.textContent = t; b.onclick = () => command(t); $('#chips').appendChild(b);
});
$('#bar').onsubmit = (e) => { e.preventDefault(); const v = $('#cmd').value; $('#cmd').value = ''; command(v); };
const SR = window.SpeechRecognition || window.webkitSpeechRecognition || P.SpeechRecognition || P.webkitSpeechRecognition;
$('#mic').onclick = () => {
  if (!SR && P.PedroApp && P.PedroApp.listen) { P.__pedroHeard = (t) => { $('#mic').classList.remove('on'); if (t) command(t); }; $('#mic').classList.add('on'); P.PedroApp.listen(); return; }
  if (!SR) { status('Voice input is not available here; type the command.'); return; }
  const r = new SR(); r.lang = navigator.language || 'en-IN'; $('#mic').classList.add('on'); status('Listening…');
  r.onresult = (e) => command(e.results[0][0].transcript); r.onend = () => $('#mic').classList.remove('on'); r.start();
};
document.addEventListener('visibilitychange', () => { if (document.hidden) head.stop(); else head.start(); });
const q = new URLSearchParams(location.search).get('do'); if (q) { const go = () => (window.__avatarReady ? command(q) : setTimeout(go, 400)); go(); }
