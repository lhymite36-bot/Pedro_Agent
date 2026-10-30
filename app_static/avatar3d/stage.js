// 1.8.0 interactive full-body 3D avatar. On-device three.js; free CC0 rigged model
// (RobotExpressive by Tomás Laulhé / Quaternius) with Idle, Walking, Running, Dance, Sitting,
// Standing, Jump, Yes, No, Wave, Punch, ThumbsUp, Death clips and Angry/Surprised/Sad face shapes.
// Commands go to /api/avatar/plan (Gemini, or a local keyword fallback) and come back as chained
// steps: action + expression + speech + where to walk. Speech uses the Gemini voices and drives
// the mouth live from the audio level (lip sync). Male pairs with Puck, female with Sulafat.
import * as THREE from './three.module.min.js';
import { GLTFLoader } from './GLTFLoader.js';

const P = window.parent && window.parent !== window ? window.parent : window;
const api = (path, body) => P.fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) }).then((r) => r.json());
const $ = (s) => document.querySelector(s);
const status = (t) => { $('#status').textContent = t; };

const canvas = $('#c');
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1)); renderer.shadowMap.enabled = true;
renderer.outputColorSpace = THREE.SRGBColorSpace;
const scene = new THREE.Scene(); scene.background = new THREE.Color(0x0b0c0e); scene.fog = new THREE.Fog(0x0b0c0e, 14, 30);
const camera = new THREE.PerspectiveCamera(42, 1, 0.1, 100);
scene.add(new THREE.HemisphereLight(0xffffff, 0x223344, 2.2));
const sun = new THREE.DirectionalLight(0xffffff, 2.4); sun.position.set(4, 10, 6); sun.castShadow = true;
sun.shadow.mapSize.set(1024, 1024); Object.assign(sun.shadow.camera, { left: -8, right: 8, top: 8, bottom: -8 }); scene.add(sun);
const floor = new THREE.Mesh(new THREE.CircleGeometry(9, 64), new THREE.MeshStandardMaterial({ color: 0x17191c, roughness: 0.95 }));
floor.rotation.x = -Math.PI / 2; floor.receiveShadow = true; scene.add(floor);
const ring = new THREE.Mesh(new THREE.RingGeometry(0.25, 0.32, 40), new THREE.MeshBasicMaterial({ color: 0x1d9bf0, transparent: true, opacity: 0 }));
ring.rotation.x = -Math.PI / 2; ring.position.y = 0.01; scene.add(ring);
const grid = new THREE.GridHelper(18, 18, 0x2a2d31, 0x1d1f22); grid.position.y = 0.002; scene.add(grid);

const PLACES = { center: [0, 0], left: [-3.2, 0], right: [3.2, 0], front: [0, 2.6], back: [0, -3.2] };
const ONCE = new Set(['Jump', 'Yes', 'No', 'Wave', 'Punch', 'ThumbsUp', 'Standing']);
const HOLD = new Set(['Sitting', 'Death']);
let baseScale = 1, model, mixer, actions = {}, current, face, head, mats = [], baseColors = [];
let gender = localStorage.pbAvatarGender === 'female' ? 'female' : 'male';
let target = null, moveClip = 'Walking', expr = { Angry: 0, Surprised: 0, Sad: 0 }, exprGoal = { Angry: 0, Surprised: 0, Sad: 0 };
let mouth = 0, analyser = null, abuf = null, actx = null, busy = Promise.resolve(), runId = 0;

function camDist() { return camera.aspect < 0.8 ? 10 / Math.max(0.42, camera.aspect) * 0.62 : 10.5; }
function resize() { const w = innerWidth || 360, h = innerHeight || 640; renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix(); }
addEventListener('resize', resize); resize(); camera.position.set(0, 4.4, camDist()); camera.lookAt(0, 1.9, 0);
window.__dbg = () => ({ cam: camera.position.toArray().map((v) => +v.toFixed(2)), h: window.__avatarH, s: baseScale, pos: model && model.position.toArray(), fps: fpsN });

new GLTFLoader().load('./RobotExpressive.glb?v=180', (g) => {
  model = g.scene; scene.add(model);
  model.traverse((o) => {
    if (o.isMesh) { o.castShadow = true; if (o.material && !mats.includes(o.material)) { mats.push(o.material); baseColors.push(o.material.color.clone()); } }
    if (o.morphTargetDictionary && o.morphTargetDictionary.Surprised != null) face = o;
    if (o.isBone && /^Head$/i.test(o.name)) head = o;
  });
  { const b = new THREE.Box3().setFromObject(model); const h = (b.max.y - b.min.y) || 1; baseScale = 3.4 / h; model.scale.setScalar(baseScale); window.__avatarH = h; }
  mixer = new THREE.AnimationMixer(model);
  g.animations.forEach((clip) => {
    const a = mixer.clipAction(clip); actions[clip.name] = a;
    if (ONCE.has(clip.name) || HOLD.has(clip.name)) { a.clampWhenFinished = true; a.loop = THREE.LoopOnce; }
  });
  mixer.addEventListener('finished', (e) => { if (ONCE.has(e.action.getClip().name)) fade('Idle', 0.3); });
  fade('Idle', 0); applyGender(); $('#load').remove();
  window.__avatarReady = true;
}, undefined, () => { $('#load').textContent = 'Could not load the avatar.'; });

function fade(name, t = 0.35) {
  const next = actions[name] || actions.Idle; if (!next || next === current) { if (next && ONCE.has(name)) next.reset().play(); return; }
  next.reset().setEffectiveWeight(1).fadeIn(t).play(); if (current) current.fadeOut(t); current = next;
}
function applyGender() {
  const female = gender === 'female';
  mats.forEach((m, i) => { const c = baseColors[i].clone(); if (female) { const hsl = {}; c.getHSL(hsl); if (hsl.s > 0.25) c.setHSL((hsl.h + 0.62) % 1, Math.min(1, hsl.s * 0.9), Math.min(0.75, hsl.l * 1.08)); } m.color.copy(c); });
  if (model) model.scale.setScalar(baseScale * (female ? 0.93 : 1));
  $('#g-male').classList.toggle('on', !female); $('#g-female').classList.toggle('on', female);
  localStorage.pbAvatarGender = gender;
}
$('#g-male').onclick = () => { gender = 'male'; applyGender(); run([{ action: 'Wave', expression: 'happy', say: "Hey, it's me again!", to: '', seconds: 2 }]); };
$('#g-female').onclick = () => { gender = 'female'; applyGender(); run([{ action: 'Wave', expression: 'happy', say: 'Hi Pedro! Nice to meet you.', to: '', seconds: 2 }]); };
$('#close').onclick = () => { stopAudio(); if (P.pbCloseAvatar) P.pbCloseAvatar(); else history.back(); };

function setExpr(e) {
  exprGoal = { Angry: e === 'angry' ? 1 : 0, Surprised: e === 'surprised' ? 1 : 0, Sad: e === 'sad' ? 1 : 0 };
  happy = e === 'happy';
}
let happy = false;

function walkTo(x, z, run) {
  return new Promise((done) => {
    moveClip = run ? 'Running' : 'Walking'; target = { x, z, done }; fade(moveClip, 0.25);
    ring.position.set(x, 0.01, z); ring.material.opacity = 0.9;
  });
}
const wait = (ms) => new Promise((r) => setTimeout(r, ms));

async function speak(text, tone) {
  if (!text) return;
  $('#say').textContent = text; $('#say').style.display = 'block';
  try {
    const r = await api('/api/speak_text', { text, gender, tone: tone || '', name: gender === 'female' ? 'Sulafat' : 'Puck' });
    if (!r.ok || !r.url) return;
    const buf = await (await P.fetch(r.url)).arrayBuffer();
    actx = actx || new (window.AudioContext || window.webkitAudioContext)(); if (actx.state === 'suspended') await actx.resume();
    const audio = await actx.decodeAudioData(buf);
    const src = actx.createBufferSource(); src.buffer = audio;
    analyser = actx.createAnalyser(); analyser.fftSize = 512; abuf = new Float32Array(analyser.fftSize);
    src.connect(analyser); analyser.connect(actx.destination); speaking = src;
    await new Promise((ok) => { src.onended = ok; src.start(); });
  } catch (e) { /* speech is optional */ } finally { speaking = null; analyser = null; setTimeout(() => { $('#say').style.display = 'none'; }, 600); }
}
let speaking = null;
function stopAudio() { try { speaking && speaking.stop(); } catch (e) {} speaking = null; }
const TONE = { happy: 'excited', sad: 'sad', angry: 'serious', surprised: 'excited', neutral: '' };

async function run(steps) {
  const id = ++runId; stopAudio();
  for (const s of steps) {
    if (id !== runId) return;
    setExpr(s.expression || 'neutral'); status(s.action + (s.expression && s.expression !== 'neutral' ? ' · ' + s.expression : ''));
    const talk = speak(s.say, TONE[s.expression] || '');
    if (s.action === 'Walking' || s.action === 'Running' || s.to) {
      const p = s.to === 'here' && lastClick ? [lastClick.x, lastClick.z] : (PLACES[s.to] || [model.position.x + (Math.random() * 4 - 2), model.position.z + (Math.random() * 3 - 1.5)]);
      await walkTo(p[0], p[1], s.action === 'Running');
      if (id !== runId) return;
      if (s.action !== 'Walking' && s.action !== 'Running') fade(s.action);
    } else fade(s.action);
    const secs = ONCE.has(s.action) ? Math.max(1.2, (actions[s.action] ? actions[s.action].getClip().duration : 1.5)) : s.seconds;
    await Promise.all([wait(secs * 1000), talk]);
  }
  if (id !== runId) return;
  if (!HOLD.has(current && current.getClip().name)) fade('Idle'); setExpr('neutral'); status('Ready — what next?');
}

async function command(text) {
  text = String(text || '').trim(); if (!text || !model) return;
  if (current && HOLD.has(current.getClip().name) && !/sit|die|faint|lie/i.test(text)) { fade('Standing', 0.3); await wait(900); }
  status('Thinking…');
  let plan; try { plan = await api('/api/avatar/plan', { command: text, gender }); } catch (e) { plan = null; }
  if (!plan || !plan.ok || !plan.steps) { status((plan && plan.error) || 'Could not plan that.'); return; }
  run(plan.steps);
}
window.avatarCommand = command; window.avatarRun = run;

// tap the floor: walk there
const ray = new THREE.Raycaster(), ndc = new THREE.Vector2(); let lastClick = null;
canvas.addEventListener('pointerdown', (e) => {
  if (!model) return; ndc.set((e.clientX / innerWidth) * 2 - 1, -(e.clientY / innerHeight) * 2 + 1); ray.setFromCamera(ndc, camera);
  const hit = ray.intersectObject(floor)[0]; if (!hit) return; lastClick = hit.point.clone();
  runId++; setExpr('neutral'); walkTo(hit.point.x, hit.point.z, hit.point.distanceTo(model.position) > 5).then(() => { fade('Idle'); status('Ready — what next?'); });
});

// chips + command bar + voice
['Wave', 'Dance', 'Sit down', 'Jump', 'Walk left', 'Run right', 'Thumbs up', 'Look surprised', 'Act sad then cheer up', 'Say hi to Pedro'].forEach((t) => {
  const b = document.createElement('button'); b.type = 'button'; b.textContent = t; b.onclick = () => command(t); $('#chips').appendChild(b);
});
$('#bar').onsubmit = (e) => { e.preventDefault(); const v = $('#cmd').value; $('#cmd').value = ''; command(v); };
const SR = window.SpeechRecognition || window.webkitSpeechRecognition || P.SpeechRecognition || P.webkitSpeechRecognition;
$('#mic').onclick = () => {
  const native = P.PedroApp && P.PedroApp.listen;
  if (!SR && native) { P.__pedroHeard = (t) => { $('#mic').classList.remove('on'); if (t) command(t); }; $('#mic').classList.add('on'); P.PedroApp.listen(); return; }
  if (!SR) { status('Voice input is not available here; type the command.'); return; }
  const r = new SR(); r.lang = navigator.language || 'en-IN'; $('#mic').classList.add('on'); status('Listening…');
  r.onresult = (e) => command(e.results[0][0].transcript); r.onend = () => $('#mic').classList.remove('on'); r.onerror = () => status('Did not catch that.');
  r.start();
};

// frame loop: movement, expressions, lip sync, idle life (head tilts, breathing)
const clock = new THREE.Clock(); let t = 0, fpsN = 0, lastW = 0, lastH = 0;
function frame() {
  requestAnimationFrame(frame); fpsN++; if (innerWidth !== lastW || innerHeight !== lastH) { lastW = innerWidth; lastH = innerHeight; resize(); } const dt = Math.min(0.05, clock.getDelta()); t += dt;
  if (mixer) mixer.update(dt);
  if (model && target) {
    const dx = target.x - model.position.x, dz = target.z - model.position.z, d = Math.hypot(dx, dz);
    const sp = moveClip === 'Running' ? 4.2 : 1.9;
    if (d < 0.08) { const done = target.done; target = null; ring.material.opacity = 0; fade('Idle', 0.25); done(); }
    else {
      const yaw = Math.atan2(dx, dz); let dy = yaw - model.rotation.y; dy = Math.atan2(Math.sin(dy), Math.cos(dy)); model.rotation.y += dy * Math.min(1, dt * 8);
      const step = Math.min(d, sp * dt); model.position.x += dx / d * step; model.position.z += dz / d * step;
    }
  } else if (model && !target) {   // turn back to face Pedro after a walk
    let dy = Math.atan2(Math.sin(-model.rotation.y), Math.cos(-model.rotation.y)); model.rotation.y += dy * Math.min(1, dt * 3);
  }
  if (analyser) { analyser.getFloatTimeDomainData(abuf); let s = 0; for (let i = 0; i < abuf.length; i++) s += abuf[i] * abuf[i]; mouth += (Math.min(1, Math.sqrt(s / abuf.length) * 9) - mouth) * 0.5; } else mouth *= 0.8;
  for (const k in expr) expr[k] += (exprGoal[k] - expr[k]) * Math.min(1, dt * 5);
  if (face) {
    const d = face.morphTargetDictionary, inf = face.morphTargetInfluences;
    inf[d.Angry] = expr.Angry; inf[d.Sad] = expr.Sad; inf[d.Surprised] = Math.min(1, expr.Surprised + mouth * 0.75 + (happy ? 0.12 : 0));
  }
  if (head) { head.rotation.z = Math.sin(t * 0.7) * 0.05 + (happy ? Math.sin(t * 3) * 0.04 : 0); head.rotation.x = mouth * 0.12 - expr.Sad * 0.25 + Math.sin(t * 0.5) * 0.03; }
  if (model) {
    const back = camDist();
    const f = new THREE.Vector3(model.position.x, 1.8, model.position.z);
    camera.position.lerp(new THREE.Vector3(f.x * 0.5, 4.4, f.z + back), Math.min(1, dt * 3)); camera.lookAt(f.x * 0.7, 1.9, f.z);
  } else { camera.position.set(0, 4.4, camDist()); camera.lookAt(0, 1.9, 0); }
  renderer.render(scene, camera);
}
frame();
const q = new URLSearchParams(location.search).get('do'); if (q) { const go = () => (window.__avatarReady ? command(q) : setTimeout(go, 300)); go(); }
