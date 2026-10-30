// 1.8.0 batch 1 in the app: 3D avatar, live Hindi->English translation, screen tutor, offline mode, "Hey Ped".
(function () {
  'use strict';
  const $ = (s) => document.querySelector(s);
  const post = (p, b) => fetch(p, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b || {}) }).then((r) => r.json());
  function el(t, c, h) { const e = document.createElement(t); if (c) e.className = c; if (h != null) e.innerHTML = h; return e; }
  let clip = null;
  async function say(text, gender) {
    try { const r = await post('/api/speak_text', { text, gender: gender || 'female' }); if (r.ok && r.url) { if (clip) clip.pause(); clip = new Audio(r.url); await clip.play(); } } catch (e) {}
  }

  // 3D avatar overlay (iframe so the 3D page stays separate from the chat)
  function openAvatar(cmd) {
    if ($('#av3d')) return;
    const f = el('iframe'); f.id = 'av3d'; f.title = 'Avatar'; f.allow = 'microphone; autoplay';
    f.src = '/avatar3d/index.html' + (cmd ? '?do=' + encodeURIComponent(cmd) : '');
    document.body.appendChild(f); document.body.classList.add('b180-open');
  }
  window.pbCloseAvatar = () => { const f = $('#av3d'); if (f) f.remove(); document.body.classList.remove('b180-open'); };
  window.pbOpenAvatar = openAvatar;

  function page(id, title, pill) {
    const old = $('#' + id); if (old) old.remove();
    const p = el('div', 'b180-page'); p.id = id;
    p.innerHTML = '<div class="b180-head"><button type="button" class="b180-x" aria-label="Close"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M18 6 6 18M6 6l12 12"/></svg></button><b></b><span class="b180-pill"></span></div><div class="b180-body"></div>';
    p.querySelector('b').textContent = title; p.querySelector('.b180-pill').textContent = pill || '';
    p.querySelector('.b180-x').onclick = () => { p.dispatchEvent(new Event('close')); p.remove(); };
    document.body.appendChild(p); return p;
  }

  // Live translate: listen in Hindi, show + speak English
  function openTranslate() {
    const p = page('b180-tr', 'Live translate', 'Hindi → English'); const body = p.querySelector('.b180-body');
    body.innerHTML = '<div class="b180-sec">Speak Hindi, hear English</div><div class="b180-log" id="tr-log"></div>' +
      '<div class="b180-bar"><input id="tr-in" placeholder="Or type Hindi / Hinglish…" autocomplete="off"><button type="button" class="b180-btn" id="tr-mic">Start listening</button></div>' +
      '<label class="b180-row"><input type="checkbox" id="tr-speak" checked> Speak the English aloud</label>';
    const log = body.querySelector('#tr-log');
    async function go(text) {
      text = text.trim(); if (!text) return;
      const row = el('div', 'b180-item'); row.innerHTML = '<small></small><div>Translating…</div>'; row.querySelector('small').textContent = text; log.prepend(row);
      const r = await post('/api/translate', { text });
      row.querySelector('div').textContent = r.ok ? r.english : (r.error || 'Could not translate.');
      if (r.ok && body.querySelector('#tr-speak').checked) say(r.english, localStorage.pbAvatarGender === 'male' ? 'male' : 'female');
    }
    body.querySelector('#tr-in').onkeydown = (e) => { if (e.key === 'Enter') { go(e.target.value); e.target.value = ''; } };
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition; let rec = null;
    const mic = body.querySelector('#tr-mic');
    mic.onclick = () => {
      if (rec) { rec.stop(); rec = null; mic.textContent = 'Start listening'; mic.classList.remove('on'); return; }
      if (!SR) {
        if (window.PedroApp && window.PedroApp.listen) { window.__pedroHeard = (t) => { if (t) go(t); }; window.PedroApp.listen(); return; }
        mic.textContent = 'Voice not available here - type instead'; return;
      }
      rec = new SR(); rec.lang = 'hi-IN'; rec.continuous = true; rec.interimResults = false;
      rec.onresult = (e) => { const r = e.results[e.results.length - 1]; if (r.isFinal) go(r[0].transcript); };
      rec.onend = () => { if (rec) try { rec.start(); } catch (e) {} };
      rec.start(); mic.textContent = 'Stop'; mic.classList.add('on');
    };
    p.addEventListener('close', () => { if (rec) { const r = rec; rec = null; r.stop(); } });
  }

  // Screen tutor: look at the PC screen, explain aloud
  function openTutor() {
    const p = page('b180-tu', 'Screen tutor', 'Watching'); const body = p.querySelector('.b180-body');
    body.innerHTML = '<div class="b180-sec">Explains your PC screen out loud</div><img id="tu-img" alt="" class="b180-shot">' +
      '<div class="b180-bar"><input id="tu-q" placeholder="Ask about your screen (optional)…" autocomplete="off"><button type="button" class="b180-btn acc" id="tu-go">Explain</button></div>' +
      '<label class="b180-row"><input type="checkbox" id="tu-auto"> Keep watching (explains every 30 s)</label><div class="b180-log" id="tu-log"></div>';
    const img = body.querySelector('#tu-img'); let timer = 0, busy = false;
    const pic = () => { const n = new Image(); n.onload = () => { img.src = n.src; img.classList.add('on'); }; n.src = '/live/frame.jpg?r=' + Date.now(); };
    pic(); const pt = setInterval(pic, 2500);
    async function explain() {
      if (busy) return; busy = true; const q = body.querySelector('#tu-q').value.trim(); body.querySelector('#tu-q').value = '';
      const row = el('div', 'b180-item'); row.innerHTML = '<small></small><div>Looking…</div>'; row.querySelector('small').textContent = q || 'What is on my screen?'; body.querySelector('#tu-log').prepend(row);
      const r = await post('/api/tutor', { question: q }); busy = false;
      row.querySelector('div').textContent = r.ok ? r.text : (r.error || 'Could not explain.');
      if (r.ok) say(r.text, localStorage.pbAvatarGender === 'male' ? 'male' : 'female');
    }
    body.querySelector('#tu-go').onclick = explain;
    body.querySelector('#tu-q').onkeydown = (e) => { if (e.key === 'Enter') explain(); };
    body.querySelector('#tu-auto').onchange = (e) => { clearInterval(timer); if (e.target.checked) { explain(); timer = setInterval(explain, 30000); } };
    p.addEventListener('close', () => { clearInterval(timer); clearInterval(pt); if (clip) clip.pause(); });
  }

  // Settings rows: offline mode + wake phrase
  async function addSettings() {
    const gen = $('#p-general'); if (!gen || $('#off-on')) return;
    const f = el('div', 'field', '<div>Offline mode<small id="off-line">Answer with a free model on this PC (Ollama) instead of Gemini. Works with no internet.</small></div><label class="switch"><input type="checkbox" id="off-on"><span></span></label>');
    const f2 = el('div', 'field', '<div>3D avatar<small>A full-body avatar that walks, waves, dances and talks. Tell it what to do.</small></div><button class="btn" type="button" id="av-open">Open</button>');
    gen.appendChild(f2); gen.appendChild(f);
    if (window.pbSettingsPage) window.pbSettingsPage.decorate(gen);
    $('#av-open').onclick = () => openAvatar();
    const sync = (r) => { $('#off-on').checked = !!r.on; $('#off-line').textContent = r.on ? (r.ollama ? 'On - answering with Ollama on this PC.' : r.note) : 'Answer with a free model on this PC (Ollama) instead of Gemini. Works with no internet.'; };
    try { sync(await post('/api/offline', {})); } catch (e) {}
    $('#off-on').onchange = async (e) => sync(await post('/api/offline', { on: e.target.checked }));
  }

  function addMenu() {
    const items = [['avatar3d', '3D avatar', () => openAvatar()], ['translate', 'Live translate (Hindi → English)', openTranslate], ['tutor', 'Screen tutor', openTutor]];
    const menu = $('#pl-menu');
    if (menu) items.forEach(([k, label, fn]) => { if (menu.querySelector('[data-b180="' + k + '"]')) return; const b = el('button', '', label); b.type = 'button'; b.dataset.b180 = k; b.onclick = (e) => { e.stopPropagation(); document.body.classList.remove('pl-menu-open'); fn(); }; menu.appendChild(b); });
    const side = $('#side .side-scroll') || $('#side');
    if (side && !$('#b180-side') && !document.body.classList.contains('pl')) {
      const box = el('div', 'b180-side'); box.id = 'b180-side';
      items.forEach(([k, label, fn]) => { const b = el('button', 'side-btn', label); b.type = 'button'; b.onclick = fn; box.appendChild(b); });
      side.appendChild(box);
    }
  }
  function boot() { addMenu(); addSettings(); setTimeout(() => { addMenu(); addSettings(); }, 1500); }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot); else boot();
  window.pb180 = { openAvatar, openTranslate, openTutor };
})();
