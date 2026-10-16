// Full avatar conversation: a separate video-call screen for the open chat.
// The same session, history, and tools stay in place. Voice is the main input.
// Talking over the reply stops it. Look and voice stay as chosen.
(function () {
  const $ = (s) => document.querySelector(s);
  const SHAPES = (window.createAvatar && createAvatar.SHAPES) || ['round'];
  const LABELS = (window.createAvatar && createAvatar.LABELS) || {};
  const VOICES = [
    { id: 'andrew', label: 'Andrew, calm' },
    { id: 'brian', label: 'Brian, clear' },
    { id: 'guy', label: 'Guy, direct' },
    { id: 'jenny', label: 'Jenny, warm' },
    { id: 'aria', label: 'Aria, bright' },
  ];
  const LOOK_KEY = 'avc-look';
  const SCRIPT_KEY = 'avc-transcript';

  let open = false;
  let face = null;
  let handsBefore = false;
  let look = loadLook();

  function loadLook() {
    try {
      const saved = JSON.parse(localStorage.getItem(LOOK_KEY) || '{}');
      const shape = SHAPES.indexOf(saved.shape) >= 0 ? saved.shape : '';
      const color = /^#[0-9a-fA-F]{6}$/.test(saved.color || '') ? saved.color : '';
      return { shape: shape, color: color, chosen: !!(saved.chosen && shape && color) };
    } catch (e) {
      return { shape: '', color: '', chosen: false };
    }
  }

  function saveLook() {
    localStorage.setItem(LOOK_KEY, JSON.stringify(look));
  }

  function activeLook() {
    const bot = (window.currentBotLook && window.currentBotLook()) || {};
    return {
      shape: look.chosen ? look.shape : (SHAPES.indexOf(bot.shape) >= 0 ? bot.shape : 'round'),
      color: look.chosen ? look.color : (/^#[0-9a-fA-F]{6}$/.test(bot.color || '') ? bot.color : '#5b6cff'),
    };
  }

  function mountFace() {
    const el = $('#avc-face');
    if (!el || !window.createAvatar) return;
    const next = activeLook();
    if (!face) {
      face = createAvatar(el, next);
      if (window.mainAvatars && window.mainAvatars.indexOf(face) < 0) window.mainAvatars.push(face);
    } else {
      face.setLook(next.color, next.shape);
    }
    const stage = $('#avc-stage');
    if (stage) stage.style.color = next.color;
    const shape = $('#avc-shape');
    const color = $('#avc-color');
    if (shape) shape.value = next.shape;
    if (color) color.value = next.color;
  }

  function lineText(row) {
    if (row.classList.contains('user')) {
      return String(row.dataset.replyText || '').trim();
    }
    const md = row.querySelector('.md');
    const spoken = md ? md.textContent.trim() : '';
    if (spoken) return spoken;
    const card = row.querySelector('.pa-card');
    return card ? card.textContent.replace(/\s+/g, ' ').trim().slice(0, 280) : '';
  }

  function paintTranscript() {
    const box = $('#avc-script');
    if (!box) return;
    const show = $('#avc-script-on') ? $('#avc-script-on').checked : true;
    box.hidden = !show;
    box.innerHTML = '';
    if (!show) return;
    Array.from(document.querySelectorAll('#log .row')).slice(-8).forEach((row) => {
      const text = lineText(row).replace(/\s+/g, ' ').trim();
      if (!text) return;
      const p = document.createElement('p');
      p.className = row.classList.contains('user') ? 'me' : 'them';
      const who = document.createElement('b');
      who.textContent = row.classList.contains('user') ? 'You' : 'Pedro';
      const span = document.createElement('span');
      span.textContent = text.slice(0, 500);
      p.append(who, span);
      box.appendChild(p);
    });
    box.scrollTop = box.scrollHeight;
  }

  function paintState() {
    const mood = ($('#mood') && $('#mood').textContent) || 'Idle';
    const el = $('#avc-state');
    const kind = /listen/i.test(mood) ? 'listening' : /think/i.test(mood) ? 'thinking' : /work/i.test(mood) ? 'working' : /speak/i.test(mood) ? 'speaking' : 'idle';
    if (el) {
      el.textContent = mood.replace(/\u2026/g, '').trim() || 'Idle';
      el.dataset.kind = kind;
    }
    const root = $('#avatar-mode');
    if (root) root.dataset.state = kind;
    const step = $('#live-step');
    const work = $('#avc-work');
    if (work) {
      const text = step && !step.hidden ? String(step.textContent || '').trim() : '';
      work.hidden = !text;
      work.textContent = text;
    }
    const cut = $('#avc-cut');
    if (cut) cut.textContent = (kind === 'speaking' || kind === 'thinking' || kind === 'working') ? 'Interrupt' : 'Talk';
  }

  function wantsVoice() { return open; }

  function enter() {
    if (open) return;
    open = true;
    document.body.classList.add('avatar-call');
    const root = $('#avatar-mode');
    if (root) root.hidden = false;
    const live = $('#livepane');
    if (live) live.classList.remove('open');
    $('#avc-open') && $('#avc-open').classList.add('on');
    $('#avcbtn') && $('#avcbtn').classList.add('on');
    mountFace();
    paintTranscript();
    paintState();
    const voice = window.pedroVoice;
    if (!voice) return;
    if (voice.onPc()) {
      handsBefore = voice.handsOn();
      voice.setHands(true);
    } else if (!voice.running()) {
      voice.listen();
    }
  }

  function leave() {
    if (!open) return;
    open = false;
    document.body.classList.remove('avatar-call');
    const root = $('#avatar-mode');
    if (root) root.hidden = true;
    $('#avc-open') && $('#avc-open').classList.remove('on');
    $('#avcbtn') && $('#avcbtn').classList.remove('on');
    const picker = $('#avc-picker');
    if (picker) picker.hidden = true;
    const voice = window.pedroVoice;
    if (voice && voice.onPc()) voice.setHands(handsBefore);
  }

  function toggle() { if (open) leave(); else enter(); }

  function fillPickers() {
    const shape = $('#avc-shape');
    if (shape && !shape.options.length) {
      SHAPES.forEach((name) => {
        const opt = document.createElement('option');
        opt.value = name;
        opt.textContent = LABELS[name] || name;
        shape.appendChild(opt);
      });
    }
    const voice = $('#avc-voice');
    if (voice && !voice.options.length) {
      VOICES.forEach((item) => {
        const opt = document.createElement('option');
        opt.value = item.id;
        opt.textContent = item.label;
        voice.appendChild(opt);
      });
    }
  }

  async function loadVoice() {
    try {
      const data = await (await fetch('/api/settings')).json();
      const voice = $('#avc-voice');
      if (voice && data.voice_style) voice.value = data.voice_style;
    } catch (e) { /* the picker keeps the last choice */ }
  }

  function bind() {
    fillPickers();
    const scriptOn = localStorage.getItem(SCRIPT_KEY) !== '0';
    const box = $('#avc-script-on');
    if (box) box.checked = scriptOn;
    $('#avc-open') && ($('#avc-open').onclick = toggle);
    $('#avcbtn') && ($('#avcbtn').onclick = toggle);
    $('#avc-chat') && ($('#avc-chat').onclick = leave);
    $('#avc-cut') && ($('#avc-cut').onclick = () => { if (window.pedroVoice) window.pedroVoice.listen(); });
    $('#avc-look') && ($('#avc-look').onclick = () => {
      const picker = $('#avc-picker');
      if (!picker) return;
      picker.hidden = !picker.hidden;
      if (!picker.hidden) { mountFace(); loadVoice(); }
    });
    if (box) box.onchange = () => { localStorage.setItem(SCRIPT_KEY, box.checked ? '1' : '0'); paintTranscript(); };
    const shape = $('#avc-shape');
    const color = $('#avc-color');
    function choose() {
      const next = activeLook();
      look = {
        shape: shape && SHAPES.indexOf(shape.value) >= 0 ? shape.value : next.shape,
        color: color && /^#[0-9a-fA-F]{6}$/.test(color.value) ? color.value : next.color,
        chosen: true,
      };
      saveLook();
      mountFace();
    }
    if (shape) shape.onchange = choose;
    if (color) color.oninput = choose;
    const voice = $('#avc-voice');
    if (voice) voice.onchange = async () => {
      const msg = $('#avc-msg');
      try {
        const res = await fetch('/api/settings', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ voice_style: voice.value }),
        });
        const data = await res.json();
        if (msg) msg.textContent = data.ok ? 'Voice saved. The next reply uses it.' : (data.error || 'Could not save that voice.');
      } catch (e) {
        if (msg) msg.textContent = 'Could not save that voice.';
      }
    };
    $('#avc-use-chat') && ($('#avc-use-chat').onclick = () => {
      look = { shape: '', color: '', chosen: false };
      saveLook();
      mountFace();
    });
    const form = $('#avc-type');
    if (form) form.onsubmit = (e) => {
      e.preventDefault();
      const input = $('#avc-text');
      const text = input ? input.value.trim() : '';
      if (!text || !window.pedroVoice) return;
      input.value = '';
      window.pedroVoice.send(text);
    };
    const log = $('#log');
    if (log && window.MutationObserver) {
      const watch = new MutationObserver(() => { if (open) { paintTranscript(); paintState(); } });
      watch.observe(log, { childList: true, subtree: true, characterData: true });
    }
    const mood = $('#mood');
    const step = $('#live-step');
    if (window.MutationObserver) {
      const watch = new MutationObserver(() => { if (open) paintState(); });
      if (mood) watch.observe(mood, { childList: true, characterData: true, subtree: true });
      if (step) watch.observe(step, { attributes: true, childList: true, characterData: true, subtree: true });
    }
    document.addEventListener('click', (e) => {
      if (!open || look.chosen) return;
      const hit = e.target && e.target.closest && e.target.closest('#sessions .sess, #bots .sess, #groups .sess');
      if (hit) setTimeout(mountFace, 60);
    });
  }

  window.avatarMode = {
    wantsVoice: wantsVoice,
    isOpen: () => open,
    onTurnEnd: () => {
      if (!open) return;
      paintTranscript();
      paintState();
      const voice = window.pedroVoice;
      if (voice && !voice.onPc() && !voice.running()) voice.listen();
    },
  };

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', bind);
  else bind();
})();
