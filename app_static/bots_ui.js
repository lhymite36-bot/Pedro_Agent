// Custom bots: sidebar list, own chat threads (session "bot-<id>"), editor.
(function (root) {
  'use strict';
  const BASE_HUE = 233; // hue of the default accent #7c8cff
  function hueOf(hex) {
    const m = /^#?([0-9a-f]{6})$/i.exec(hex || ''); if (!m) return BASE_HUE;
    const n = parseInt(m[1], 16), r = (n >> 16) / 255, g = ((n >> 8) & 255) / 255, b = (n & 255) / 255;
    const max = Math.max(r, g, b), min = Math.min(r, g, b), d = max - min; if (!d) return BASE_HUE;
    let h = max === r ? ((g - b) / d) % 6 : max === g ? (b - r) / d + 2 : (r - g) / d + 4;
    h = Math.round(h * 60); return h < 0 ? h + 360 : h;
  }
  function hueShift(hex) { return ((hueOf(hex) - BASE_HUE) % 360 + 360) % 360; }
  function scheduleLabel(t) {
    if (t.watch && t.watch.path) return 'when ' + t.watch.path + ' changes';
    if (!t.schedule) return 'one-off';
    if (t.schedule.every_minutes) return 'every ' + t.schedule.every_minutes + ' min';
    return 'daily ' + t.schedule.daily;
  }
  if (typeof module !== 'undefined' && module.exports) { module.exports = { hueShift, hueOf, scheduleLabel }; return; }

  const $ = (s) => document.querySelector(s);
  let bots = [], allTools = [], editing = null, recording = false;
  const DEFAULT = { color: '#f2f2f2', shape: 'pedbot' };   // 1.4.17: Ped Bot's own look
  function look(bot) { return bot ? { color: bot.color || '#1683f5', shape: bot.avatar || 'round' } : DEFAULT; }
  function tint(av, bot) { const l = look(bot); av.setLook(l.color, l.shape); }
  root.currentBotLook = () => look(current());
  function current() { return (typeof session === 'string' && session.startsWith('bot-')) ? bots.find((b) => 'bot-' + b.id === session) : null; }

  function applyHeader() {
    const bot = current(); const hdr = $('#hdr-avatar');
    const grp = root.currentGroup && root.currentGroup();
    $('.who b').textContent = grp ? grp.name : bot ? bot.name : 'Ped Bot';
    $('#t').placeholder = 'Message ' + (grp ? grp.name + ' (@ to mention)' : bot ? bot.name : 'Ped Bot') + '…';
    const l = grp ? { color: grp.color || DEFAULT.color, shape: grp.avatar || 'round' } : look(bot); const key = l.color + l.shape;
    let pic = $('#hdr-pic'); if (!pic) { pic = document.createElement('img'); pic.id = 'hdr-pic'; pic.alt = ''; hdr.appendChild(pic); }
    pic.hidden = !(grp && grp.picture); if (grp && grp.picture) pic.src = grp.picture;
    if (hdr.dataset.look !== key && root.mainAvatars) { hdr.dataset.look = key; root.mainAvatars[0].setLook(l.color, l.shape); root.mainAvatars[2].setLook(l.color, l.shape); }
    if (!grp) document.querySelectorAll('#log .row.bot .face').forEach((f) => { if (f._av && f.dataset.look !== key) { f.dataset.look = key; f._av.setLook(l.color, l.shape); } });
    document.querySelectorAll('#bots .sess').forEach((d) => d.classList.toggle('active', bot && d.dataset.id === bot.id));
  }
  root.applyBotHeader = function () { applyHeader(); if (root.updateMentionButton) root.updateMentionButton(); };

  async function load() {
    const r = await (await fetch('/api/bots')).json(); bots = r.bots || []; root.pedroBots = bots; allTools = r.tools || [];
    const box = $('#bots'); box.innerHTML = '';
    bots.forEach((b) => {
      const d = document.createElement('div'); d.className = 'sess botitem' + (window.chatIsRunning && window.chatIsRunning('bot-' + b.id) ? ' working' : ''); d.dataset.id = b.id;
      const face = document.createElement('div'); face.className = 'mini-face'; const l = look(b); createAvatar(face, l);
      const sp = document.createElement('span'); sp.textContent = b.name;
      const ed = document.createElement('button'); ed.type = 'button'; ed.className = 'edit'; ed.title = 'Edit bot'; ed.textContent = '✎';
      ed.onclick = (e) => { e.stopPropagation(); openEditor(b); };
      d.append(face, sp, ed, root.trashBtn('Delete bot', () => deleteBot(b))); d.onclick = () => { openSession('bot-' + b.id).then(applyHeader); };
      box.appendChild(d);
    });
    applyHeader();
  }
  root.loadBots = load;
  async function deleteBot(b) {
    if (!confirm('Delete the bot "' + b.name + '" and its chat? It will also leave any groups it is in.')) return false;
    await fetch('/api/bots/delete', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id: b.id, confirm: true }) });
    if (session === 'bot-' + b.id) $('#new').click();
    await load(); if (root.loadGroups) root.loadGroups(); return true;
  }

  function sizeTask(row) {
    const kind = row.querySelector('.tk').value;
    const box = row.querySelector('.tv');
    box.style.width = kind === 'watch' ? '160px' : '80px';
    box.placeholder = kind === 'watch' ? 'Downloads *.pdf' : (kind === 'daily' ? '08:00' : '30');
  }
  function taskRow(t) {
    const row = document.createElement('div'); row.className = 'task';
    const kind = t.watch ? 'watch' : t.schedule ? (t.schedule.every_minutes ? 'every' : 'daily') : 'once';
    row.innerHTML = '<input class="tt" placeholder="Task, e.g. Summarise my unread email">' +
      '<select class="tk"><option value="once">One-off</option><option value="every">Every N min</option><option value="daily">Daily at</option><option value="watch">When files arrive</option></select>' +
      '<input class="tv" placeholder="30 or 08:00"><button type="button" class="ib run" title="Run now">▶</button><button type="button" class="ib del" title="Remove">✕</button>';
    row.querySelector('.tt').value = t.text || ''; row.querySelector('.tk').value = kind;
    if (t.watch) row.querySelector('.tv').value = (t.watch.path || '') + (t.watch.pattern && t.watch.pattern !== '*' ? ' ' + t.watch.pattern : '');
    else row.querySelector('.tv').value = t.schedule ? (t.schedule.every_minutes || t.schedule.daily || '') : '';
    sizeTask(row);
    row.querySelector('.tk').onchange = () => sizeTask(row);
    row.dataset.id = t.id || ''; row.dataset.last = t.last_result || '';
    row.querySelector('.del').onclick = () => row.remove();
    row.querySelector('.run').onclick = async () => {
      if (!editing || !row.dataset.id) { $('#botmsg').textContent = 'Save the bot first.'; return; }
      await fetch('/api/bots/run_task', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id: editing.id, task: row.dataset.id }) });
      $('#botmsg').textContent = 'Task started — the result appears in the bot\'s chat.';
    };
    return row;
  }

  function lessonRow(item, listName) {
    const row = document.createElement('div'); row.className = 'bot-skill';
    const sp = document.createElement('span'); sp.textContent = item.name || item.text; sp.title = item.text || '';
    const del = document.createElement('button'); del.type = 'button'; del.className = 'ib'; del.title = 'Remove'; del.textContent = '✕';
    del.onclick = () => {
      if (!editing) return;
      editing[listName] = (editing[listName] || []).filter((x) => x !== item && x.id !== item.id);
      row.remove();
    };
    row.append(sp, del); return row;
  }
  function showLessons() {
    const skills = $('#bot-skills'); const notes = $('#bot-notes');
    if (skills) { skills.innerHTML = ''; (editing && editing.skills || []).forEach((s) => skills.appendChild(lessonRow(s, 'skills'))); }
    if (notes) { notes.innerHTML = ''; (editing && editing.notes || []).forEach((n) => notes.appendChild(lessonRow(n, 'notes'))); }
    if ($('#bot-teach-stop')) $('#bot-teach-stop').hidden = !recording;
    if ($('#bot-teach')) $('#bot-teach').hidden = recording;
  }
  function openEditor(bot) {
    editing = bot ? Object.assign({}, bot, { notes: (bot.notes || []).slice(), skills: (bot.skills || []).slice() }) : null;
    const b = editing || { name: '', color: '#7c8cff', avatar: 'round', role: '', model: '', tools: [], rules: {}, tasks: [] };
    $('#bot-name').value = b.name; $('#bot-color').value = b.color; $('#bot-shape').value = b.avatar;
    $('#bot-role').value = b.role; $('#bot-model').value = b.model || '';
    $('#bot-rules').value = Object.keys(b.rules || {}).length ? JSON.stringify(b.rules, null, 2) : '';
    const tl = $('#bot-tools'); tl.innerHTML = '';
    allTools.forEach((name) => {
      const l = document.createElement('label'); l.dataset.name = name;
      l.innerHTML = '<input type="checkbox"> <span></span>'; l.querySelector('span').textContent = name;
      l.querySelector('input').checked = (b.tools || []).includes(name); tl.appendChild(l);
    });
    $('#bot-toolfilter').value = '';
    const tasks = $('#bot-tasks'); tasks.innerHTML = ''; (b.tasks || []).forEach((t) => tasks.appendChild(taskRow(t)));
    if ($('#bot-lesson')) $('#bot-lesson').value = '';
    if ($('#bot-teachmsg')) $('#bot-teachmsg').textContent = '';
    showLessons();
    $('#bot-delete').style.display = bot ? '' : 'none'; $('#botmsg').textContent = '';
    $('#boted-title').textContent = bot ? 'Edit bot' : 'New bot';
    previewTint(); $('#boted').classList.add('open'); $('#overlay').classList.add('open');
  }
  function closeEditor() { $('#boted').classList.remove('open'); $('#overlay').classList.remove('open'); }
  let previewAv = null;
  function previewTint() {
    const c = $('#bot-color').value, sh = $('#bot-shape').value;
    if (previewAv) previewAv.setLook(c, sh);
    document.querySelectorAll('#shape-pick button').forEach((b) => { b.classList.toggle('on', b.dataset.shape === sh); b._av.setLook(c, b.dataset.shape); });
  }
  function buildPicker() {
    const box = $('#shape-pick'); if (!box) return; box.innerHTML = '';
    createAvatar.SHAPES.forEach((sh) => {
      const b = document.createElement('button'); b.type = 'button'; b.dataset.shape = sh; b.title = createAvatar.LABELS[sh];
      const f = document.createElement('div'); f.className = 'pf'; b.appendChild(f);
      const t = document.createElement('div'); t.textContent = createAvatar.LABELS[sh]; b.appendChild(t);
      b._av = createAvatar(f, { color: $('#bot-color').value, shape: sh });
      b.onclick = () => { $('#bot-shape').value = sh; previewTint(); previewAv && previewAv.celebrate(); };
      box.appendChild(b);
    });
  }

  function collect() {
    const tasks = Array.from(document.querySelectorAll('#bot-tasks .task')).map((r) => {
      const kind = r.querySelector('.tk').value, v = r.querySelector('.tv').value.trim();
      let schedule = null, watch = null;
      if (kind === 'every') schedule = { every_minutes: parseInt(v, 10) || 60 };
      else if (kind === 'daily') schedule = { daily: v || '08:00' };
      else if (kind === 'watch') {
        const bits = v.split(/\s+/).filter(Boolean);
        let pattern = '*', path = v || 'Downloads';
        if (bits.length > 1 && /[*?]/.test(bits[bits.length - 1])) { pattern = bits.pop(); path = bits.join(' '); }
        watch = { path: path, pattern: pattern };
      }
      return { id: r.dataset.id || undefined, text: r.querySelector('.tt').value, schedule, watch };
    }).filter((t) => t.text.trim());
    let rulesObj = {}; const raw = $('#bot-rules').value.trim();
    if (raw) rulesObj = JSON.parse(raw);
    const tools = Array.from(document.querySelectorAll('#bot-tools label')).filter((l) => l.querySelector('input').checked).map((l) => l.dataset.name);
    return { id: editing ? editing.id : undefined, created: editing ? editing.created : undefined, name: $('#bot-name').value,
      color: $('#bot-color').value, avatar: $('#bot-shape').value, role: $('#bot-role').value, model: $('#bot-model').value, tools, rules: rulesObj, tasks,
      notes: editing ? (editing.notes || []) : [], skills: editing ? (editing.skills || []) : [] };
  }

  function wire() {
    if (!$('#boted')) return;
    $('#newbot').onclick = () => openEditor(null);
    $('#close-boted').onclick = closeEditor;
    $('#overlay').addEventListener('click', closeEditor);
    $('#bot-color').oninput = previewTint;
    $('#bot-addtask').onclick = () => $('#bot-tasks').appendChild(taskRow({}));
    if ($('#bot-teach')) $('#bot-teach').onclick = async () => {
      if (!editing || !editing.id) { $('#bot-teachmsg').textContent = 'Save the bot first, then record.'; return; }
      const name = ($('#bot-lesson').value || '').trim() || 'lesson';
      $('#bot-teachmsg').textContent = 'Starting…';
      const r = await (await fetch('/api/bots/teach', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id: editing.id, name }) })).json();
      if (!r.ok) { $('#bot-teachmsg').textContent = r.error || 'Could not record.'; return; }
      recording = true; $('#bot-teach').hidden = true; $('#bot-teach-stop').hidden = false;
      $('#bot-teachmsg').textContent = 'Recording on this PC. Do the task, then press Stop and save.';
    };
    if ($('#bot-teach-stop')) $('#bot-teach-stop').onclick = async () => {
      $('#bot-teachmsg').textContent = 'Saving what you did…';
      const r = await (await fetch('/api/bots/teach_stop', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })).json();
      recording = false; $('#bot-teach').hidden = false; $('#bot-teach-stop').hidden = true;
      if (!r.ok) { $('#bot-teachmsg').textContent = r.error || 'Could not save the lesson.'; return; }
      await load();
      const saved = (root.pedroBots || []).find((b) => editing && b.id === editing.id) || r.saved;
      if (saved) openEditor(saved);
      $('#bot-teachmsg').textContent = r.message || 'Lesson saved.';
    };
    $('#bot-toolfilter').oninput = (e) => { const q = e.target.value.toLowerCase(); document.querySelectorAll('#bot-tools label').forEach((l) => { l.style.display = l.dataset.name.includes(q) ? '' : 'none'; }); };
    $('#bot-save').onclick = async () => {
      let body; try { body = collect(); } catch (e) { $('#botmsg').textContent = 'Rules override must be JSON: ' + e.message; return; }
      const r = await (await fetch('/api/bots', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })).json();
      if (!r.ok) { $('#botmsg').textContent = r.error || 'Could not save.'; return; }
      editing = r.bot; await load(); openEditor(r.bot); $('#botmsg').textContent = 'Saved.';
    };
    $('#bot-delete').onclick = async () => { if (editing && await deleteBot(editing)) closeEditor(); };
    previewAv = createAvatar($('#bot-preview')); buildPicker();
    load();
  }
  wire();
})(this);
