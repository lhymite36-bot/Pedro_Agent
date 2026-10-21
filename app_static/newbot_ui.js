// 1.4.14: dark "New bot" screen (big live preview, colour dots, shape row, name,
// Get started, suggestions) and a store-like "Bots" page with presets.
(function (root) {
  'use strict';
  const $ = (s) => document.querySelector(s);
  const COLORS = createAvatar.COLORS, SHAPES = createAvatar.SHAPES, LABELS = createAvatar.LABELS;
  const C = Object.fromEntries(COLORS);
  // Preset bots. role = the bot's standing instructions (same field as the editor).
  const PRESETS = [
    { id: 'night-shift', name: 'Night Shift', cat: 'Ped Bot', color: C.orange, shape: 'hexagon', featured: true,
      desc: 'Works overnight and preps your morning digest',
      role: 'You work while Pedro sleeps. Finish queued tasks, then leave a short morning digest: what got done, what is waiting for his yes, anything that broke. Never send, delete, buy or pay without his yes.' },
    { id: 'inbox-triage', name: 'Inbox Triage', cat: 'Work', color: C.pink, shape: 'cloud', featured: true,
      desc: 'Sorts your email and drafts replies in your voice',
      role: 'Sort new email into Needs reply, FYI and Ignore. Draft short replies in Pedro\'s voice for the Needs reply ones and show them for approval. Never send without his yes.' },
    { id: 'shorts-poster', name: 'Shorts Poster', cat: 'Content', color: C.red, shape: 'drop', featured: true,
      desc: 'Plans, checks and schedules Quiet Brain Shorts',
      role: 'You run the Quiet Brain Shorts backup: fresh funny, sarcastic 2D psychology ideas not in posted.json, captions with #fyp #quietbrain, YouTube titles with #shorts. Use quiet_brain_shorts_dry_run first and report; real posting only when the routine is turned on.' },
    { id: 'pc-tidy', name: 'PC Tidy', cat: 'PC & Files', color: C.purple, shape: 'square', featured: true,
      desc: 'Keeps Downloads and Desktop in order',
      role: 'Keep Downloads and Desktop tidy: group files into folders by type and date, list big or duplicate files, and ask before deleting anything.' },
    { id: 'research-buddy', name: 'Research Buddy', cat: 'Learning', color: C.teal, shape: 'star',
      desc: 'Finds sources and writes a short brief with links', role: 'Research the question on the web, read 3-5 good sources and write a short brief with links. Say what is uncertain.' },
    { id: 'blender-helper', name: 'Blender Helper', cat: 'Content', color: C.amber, shape: 'ball',
      desc: 'Models, textures and renders in Blender', role: 'Use the Blender docs and guides (blender_docs_search, blender_guide) and run_blender_task. Show the render and scene check as proof.' },
    { id: 'game-mods', name: 'Mod Manager', cat: 'Personal', color: C.green, shape: 'clover',
      desc: 'Installs and checks game mods safely', role: 'Help install and organise game mods. Back up files before changing them and list exactly what changed.' },
    { id: 'study-coach', name: 'Study Coach', cat: 'Learning', color: C.blue, shape: 'circle',
      desc: 'Quizzes you and explains what you got wrong', role: 'Coach Pedro: short explanations, then a few quiz questions. Never do graded tests or assignments for him.' },
    { id: 'money-watch', name: 'Spend Watch', cat: 'Personal', color: C.grey, shape: 'pill',
      desc: 'Summarises spending from statements you share', role: 'Summarise spending from files Pedro shares. Never type card numbers, passwords, OTPs or PINs, and never pay for anything.' },
    { id: 'social-planner', name: 'Post Planner', cat: 'Content', color: C.brown, shape: 'triangle',
      desc: 'Drafts a week of posts for approval', role: 'Draft a week of social posts with times. Everything waits for Pedro\'s yes before it is scheduled.' },
    { id: 'meeting-notes', name: 'Meeting Notes', cat: 'Work', color: C.teal, shape: 'pill',
      desc: 'Turns recordings and notes into action lists', role: 'Turn meeting notes or recordings into a summary, decisions and an action list with owners.' },
    { id: 'app-builder', name: 'App Builder', cat: 'Work', color: C.teal, shape: 'square',
      desc: 'Builds complete apps: spec, code, test, screenshots, polish',
      role: 'You are the App Builder. For any app request call build_app with the goal (it writes a spec first, then a multi-file app in Projects\\PedBot-Builds, runs it, fixes errors, screenshots it, has the screenshots reviewed and polishes). Follow it with app_builder_status and report the screens, files, final errors, review scores and screenshot paths. Use web_search for docs. Installs (builder_install) and GitHub pushes (ship_app target github) always wait for Pedro\'s yes. Never claim something was built unless the tools say so.' },
    { id: 'pc-doctor', name: 'PC Doctor', cat: 'PC & Files', color: C.red, shape: 'square',
      desc: 'Checks what is slowing the PC down', role: 'Run system_diagnostics, explain what slows the PC down in plain words and offer fixes. Ask before closing or removing anything.' },
  ];
  const CATS = ['All', 'Ped Bot', 'Work', 'Content', 'PC & Files', 'Personal', 'Learning'];
  root.pedBotPresets = PRESETS;

  function face(el, color, shape, state) { const a = createAvatar(el, { color, shape }); if (state) a.setState(state); return a; }
  function el(tag, cls, text) { const d = document.createElement(tag); if (cls) d.className = cls; if (text != null) d.textContent = text; return d; }

  async function createBot(p) {
    const body = { name: p.name, color: p.color, avatar: p.shape, role: p.role || '', model: '', tools: [], rules: {}, tasks: [] };
    const r = await (await fetch('/api/bots', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })).json();
    if (!r.ok) throw new Error(r.error || 'Could not create the bot.');
    if (root.loadBots) await root.loadBots();
    return r.bot;
  }
  function openBot(bot) { hideAll(); if (bot && root.openSession) root.openSession('bot-' + bot.id).then(() => root.applyBotHeader && root.applyBotHeader()); }

  // ---------- New bot screen ----------
  let nb = null, pick = { color: C.blue, shape: 'circle', role: '' }, big = null;
  function buildNew() {
    nb = el('section', 'pb-screen'); nb.id = 'nb-screen'; nb.hidden = true;
    nb.innerHTML = `<div class="pb-top"><div class="pb-mini" id="nb-mini"></div><b>New Bot</b><button class="pb-x" id="nb-close" type="button" title="Close">✕</button></div>
      <div class="nb-center"><div class="nb-preview" id="nb-preview"></div>
      <div class="nb-dots" id="nb-dots" role="radiogroup" aria-label="Colour"></div>
      <div class="nb-shapes" id="nb-shapes" role="radiogroup" aria-label="Shape"></div>
      <label class="nb-label" for="nb-name">Name</label><input id="nb-name" class="nb-input" placeholder="New Bot" maxlength="60" autocomplete="off">
      <button class="nb-go" id="nb-go" type="button" disabled>Get started</button><div class="nb-msg" id="nb-msg"></div>
      <button class="nb-more" id="nb-more" type="button">More settings…</button></div>
      <div class="nb-sugg-title">Suggestions</div><div class="nb-sugg" id="nb-sugg"></div>`;
    $('main').appendChild(nb);
    big = face($('#nb-preview'), pick.color, pick.shape); const mini = face($('#nb-mini'), pick.color, pick.shape);
    COLORS.forEach(([name, hex]) => {
      const b = el('button', 'nb-dot'); b.type = 'button'; b.title = name; b.dataset.color = hex; b.style.background = hex; b.setAttribute('aria-label', name);
      b.onclick = () => { pick.color = hex; sync(); }; $('#nb-dots').appendChild(b);
    });
    SHAPES.forEach((sh) => {
      const b = el('button', 'nb-shape'); b.type = 'button'; b.title = LABELS[sh]; b.dataset.shape = sh; const f = el('div', 'nb-sface'); b.appendChild(f);
      b._av = face(f, pick.color, sh); b.onclick = () => { pick.shape = sh; sync(); }; $('#nb-shapes').appendChild(b);
    });
    PRESETS.filter((p) => ['night-shift', 'inbox-triage', 'shorts-poster', 'pc-tidy'].includes(p.id)).forEach((p) => {
      const c = el('button', 'nb-card'); c.type = 'button'; const f = el('div', 'nb-cface'); face(f, p.color, p.shape);
      const t = el('div', 'nb-ctext'); t.append(el('b', '', p.name), el('span', '', p.desc)); c.append(f, t);
      c.onclick = () => { pick = { color: p.color, shape: p.shape, role: p.role }; $('#nb-name').value = p.name; sync(); }; $('#nb-sugg').appendChild(c);
    });
    function sync() {
      big.setLook(pick.color, pick.shape); mini.setLook(pick.color, pick.shape);
      document.querySelectorAll('#nb-dots .nb-dot').forEach((d) => d.classList.toggle('on', d.dataset.color === pick.color));
      document.querySelectorAll('#nb-shapes .nb-shape').forEach((d) => { d.classList.toggle('on', d.dataset.shape === pick.shape); d._av.setLook(pick.color, d.dataset.shape); });
      $('#nb-go').disabled = !$('#nb-name').value.trim();
    }
    nb._sync = sync;
    $('#nb-name').oninput = sync;
    $('#nb-name').onkeydown = (e) => { if (e.key === 'Enter' && !$('#nb-go').disabled) $('#nb-go').click(); };
    $('#nb-close').onclick = hideAll;
    $('#nb-more').onclick = () => { hideAll(); const b = $('#newbot'); if (b && b._editor) b._editor(); };
    $('#nb-go').onclick = async () => {
      $('#nb-go').disabled = true; $('#nb-msg').textContent = '';
      try { big.setState('working'); const bot = await createBot({ name: $('#nb-name').value.trim(), color: pick.color, shape: pick.shape, role: pick.role });
        big.setState('idle'); openBot(bot); } catch (e) { big.setState('idle'); $('#nb-msg').textContent = e.message; $('#nb-go').disabled = false; }
    };
    sync();
  }
  function showNew() {
    if (!nb) buildNew(); hideAll(); pick = { color: C.blue, shape: 'circle', role: '' }; $('#nb-name').value = ''; nb._sync();
    nb.hidden = false; document.body.classList.add('pb-screen-open'); setTimeout(() => $('#nb-name').focus(), 30);
  }

  // ---------- Bots store ----------
  let st = null, cat = 'All';
  function buildStore() {
    st = el('section', 'pb-screen'); st.id = 'store-screen'; st.hidden = true;
    st.innerHTML = `<div class="pb-top"><b>Bots</b><button class="pb-x" id="st-close" type="button" title="Close">✕</button></div>
      <div class="st-wrap"><h1>Bots</h1><div class="st-chips" id="st-chips"></div>
      <input id="st-q" class="st-search" placeholder="Search bots by name or job" autocomplete="off">
      <div id="st-body"></div></div>`;
    $('main').appendChild(st);
    CATS.forEach((c) => { const b = el('button', 'st-chip', c); b.type = 'button'; b.onclick = () => { cat = c; render(); }; $('#st-chips').appendChild(b); });
    $('#st-q').oninput = render; $('#st-close').onclick = hideAll;
  }
  function have(p) { return (root.pedroBots || []).find((b) => (b.name || '').toLowerCase() === p.name.toLowerCase()); }
  function addBtn(p) {
    const b = el('button', 'st-add'); b.type = 'button'; const mine = have(p); b.textContent = mine ? 'Open' : 'Add';
    b.onclick = async (e) => {
      e.stopPropagation(); const m = have(p); if (m) { openBot(m); return; }
      b.disabled = true; b.textContent = 'Adding…';
      try { const bot = await createBot(p); b.textContent = 'Open'; b.disabled = false; b.onclick = (ev) => { ev.stopPropagation(); openBot(bot); }; }
      catch (err) { b.textContent = 'Add'; b.disabled = false; alert(err.message); }
    };
    return b;
  }
  function render() {
    document.querySelectorAll('#st-chips .st-chip').forEach((c) => c.classList.toggle('on', c.textContent === cat));
    const q = ($('#st-q').value || '').toLowerCase().trim(); const body = $('#st-body'); body.innerHTML = '';
    const list = PRESETS.filter((p) => (cat === 'All' || p.cat === cat) && (!q || (p.name + ' ' + p.desc + ' ' + p.cat).toLowerCase().includes(q)));
    if (!list.length) { body.appendChild(el('div', 'st-empty', 'No bots match that.')); return; }
    const feat = list.filter((p) => p.featured);
    if (feat.length && !q) {
      body.appendChild(el('h2', '', 'Featured')); const g = el('div', 'st-feat');
      feat.forEach((p) => { const c = el('div', 'st-fcard'); const f = el('div', 'st-fface'); face(f, p.color, p.shape);
        const n = el('div', 'st-fname', p.name); n.style.color = p.color; c.append(f, n, el('div', 'st-fdesc', p.desc), addBtn(p)); g.appendChild(c); });
      body.appendChild(g);
    }
    const groups = cat === 'All' ? CATS.slice(1) : [cat];
    groups.forEach((g) => {
      const items = list.filter((p) => p.cat === g); if (!items.length) return;
      body.appendChild(el('h2', '', g === 'Ped Bot' ? 'From Ped Bot' : g)); const grid = el('div', 'st-grid');
      items.forEach((p) => { const r = el('div', 'st-row'); const f = el('div', 'st-rface'); face(f, p.color, p.shape);
        const t = el('div', 'st-rtext'); t.append(el('b', '', p.name), el('span', '', p.desc)); r.append(f, t, addBtn(p)); grid.appendChild(r); });
      body.appendChild(grid);
    });
  }
  function showStore() { if (!st) buildStore(); hideAll(); render(); st.hidden = false; document.body.classList.add('pb-screen-open'); }
  function hideAll() { [nb, st].forEach((s) => { if (s) s.hidden = true; }); document.body.classList.remove('pb-screen-open'); }

  root.showNewBot = showNew; root.showBotStore = showStore; root.hideBotScreens = hideAll;
  function wire() {
    const plus = $('#newbot');
    if (plus) { const old = plus.onclick; plus._editor = () => old && old.call(plus); plus.onclick = showNew; }
    const sb = $('#storebtn'); if (sb) sb.onclick = showStore;
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && document.body.classList.contains('pb-screen-open')) hideAll(); });
    if (/[?&]screen=newbot/.test(location.search)) showNew();
    if (/[?&]screen=bots/.test(location.search)) showStore();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', wire); else wire();
})(this);
