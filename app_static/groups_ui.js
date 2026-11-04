// Bot groups: sidebar list, editor drawer, speaker name/avatar in group chats.
(function (root) {
  const $ = (s) => document.querySelector(s);
  let groups = [], main = { id: 'pedro', name: 'Ped Bot', color: '#5b6cff', avatar: 'round' }, editing = null;
  const post = async (u, b) => (await fetch(u, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) })).json();
  function current() { return (typeof session === 'string' && session.startsWith('group-')) ? groups.find((g) => 'group-' + g.id === session) : null; }
  root.currentGroup = current;
  function who(id) {
    if (id === 'pedro') return main;
    const b = (root.pedroBots || []).find((x) => x.id === id); return b ? { id: b.id, name: b.name, color: b.color, avatar: b.avatar } : { id, name: id, color: '#5b6cff', avatar: 'round' };
  }
  // Give a reply bubble its speaker's name and avatar look.
  root.markSpeaker = function (row, id, info) {
    const w = info && info.name ? info : who(id);
    const f = row.row.querySelector('.face'); if (f && f._av) { f.dataset.look = 'speaker'; f._av.setLook(w.color || '#5b6cff', w.avatar || 'round'); }
    const n = document.createElement('div'); n.className = 'speaker-name'; n.textContent = w.name; n.style.color = w.color || '';
    row.body.parentNode.insertBefore(n, row.body.parentNode.firstChild);
  };
  async function load() {
    let r = {};
    try { r = await (await fetch('/api/groups')).json(); } catch (e) { r = { groups: [], error: String(e) }; }
    groups = r.groups || []; root.pedroGroups = groups; if (r.main) main = r.main;
    const box = $('#groups'); if (!box) return; box.innerHTML = '';
    if (r.error && !groups.length) {
      const err = document.createElement('div'); err.className = 'dim'; err.style.padding = '8px';
      err.textContent = 'Could not load projects. Sign in and try again.'; box.appendChild(err);
    }
    groups.forEach((g) => {
      const d = document.createElement('div'); d.className = 'sess botitem' + (current() && current().id === g.id ? ' active' : ''); d.dataset.id = g.id;
      const ic = groupFace(g);
      const sp = document.createElement('span'); sp.textContent = g.name; sp.title = g.purpose || '';
      const ed = document.createElement('button'); ed.type = 'button'; ed.className = 'edit'; ed.title = 'Edit project'; ed.textContent = '✎';
      ed.onclick = (e) => { e.stopPropagation(); openEditor(g); };
      d.append(ic, sp, ed, root.trashBtn('Delete project', () => delGroup(g))); d.onclick = () => {
        const open = window.openSession || (typeof openSession === 'function' ? openSession : null);
        if (open) open('group-' + g.id).then(() => { load(); root.applyBotHeader && root.applyBotHeader(); });
      }; box.appendChild(d);
    });
    root.applyBotHeader && root.applyBotHeader(); root.updateMentionButton && root.updateMentionButton();
  }
  root.loadGroups = load;
  // 1.9.3: opening a project used to show a blank "What can I do for you?" page with nothing about the project.
  // Now an empty project shows its name, goal, team and quick starts.
  root.pbProjectEmpty = function () {
    const empty = document.getElementById('empty'); if (!empty) return;
    let card = document.getElementById('pj-card');
    const g = current();
    empty.classList.toggle('pj-mode', !!g);
    if (!g) { if (card) card.remove(); return; }
    if (card && card.dataset.id === g.id && card.dataset.v === JSON.stringify([g.name, g.purpose, g.members])) return;
    if (card) card.remove();
    card = document.createElement('div'); card.id = 'pj-card'; card.dataset.id = g.id; card.dataset.v = JSON.stringify([g.name, g.purpose, g.members]);
    const esc = (t) => String(t == null ? '' : t).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
    const team = ['pedro'].concat(g.members || []).map(who);
    card.innerHTML = '<div class="pj-k">Project</div><h2>' + esc(g.name) + '</h2>' +
      '<p class="pj-goal">' + esc(g.purpose || 'No goal yet. Add one so the team knows what to work on.') + '</p>' +
      '<div class="pj-team">' + team.map((m) => '<span class="pj-mem"><i style="background:' + esc(m.color || '#5b6cff') + '"></i>' + esc(m.name) + '</span>').join('') + '</div>' +
      ((g.members || []).length ? '' : '<p class="pj-tip">Only Ped Bot is in this project. Add bots to make it a team.</p>') +
      '<div class="pj-acts"><button type="button" class="pj-btn" data-a="edit">Edit project</button>' +
      '<button type="button" class="pj-btn acc" data-a="plan">Plan the next steps</button>' +
      '<button type="button" class="pj-btn" data-a="status">What\'s the status?</button></div>';
    empty.appendChild(card);
    card.querySelector('[data-a="edit"]').onclick = () => root.openGroupEditor(g);
    const ask = (t) => { const box = document.getElementById('t'); if (!box) return; box.value = t; box.dispatchEvent(new Event('input', { bubbles: true })); const f = box.form; const sendBtn = document.getElementById('send'); if (sendBtn) sendBtn.click(); else if (f) f.requestSubmit(); };
    card.querySelector('[data-a="plan"]').onclick = () => ask('Plan the next steps for this project' + (g.purpose ? ' (' + g.purpose + ')' : '') + '. Split the work between the team.');
    card.querySelector('[data-a="status"]').onclick = () => ask('Give me a short status update on this project.');
  };
  // 1.9.3: phone Projects page (the sidebar list is hidden in the phone layout, so Projects used to show nothing)
  root.openProjectsSheet = async function () {
    await load();
    let p = document.getElementById('pb-projects'); if (p) p.remove();
    p = document.createElement('div'); p.id = 'pb-projects'; p.className = 'pb-sheetpage';
    const esc = (t) => String(t == null ? '' : t).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
    p.innerHTML = '<div class="pro-head"><button type="button" class="pro-x" aria-label="Close"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 6 6 18M6 6l12 12"/></svg></button><b>Projects</b><button type="button" class="pro-pill" id="pj-new">+ New project</button></div><div class="pro-body"></div>';
    document.body.appendChild(p);
    const close = () => p.remove();
    p.querySelector('.pro-x').onclick = close;
    p.querySelector('#pj-new').onclick = () => { close(); root.openGroupEditor(null); };
    const body = p.querySelector('.pro-body');
    if (!groups.length) body.innerHTML = '<div class="pj-empty"><b>No projects yet</b><small>A project is a chat room where several bots work together on one goal.</small><button type="button" class="pro-go acc" id="pj-new2">Create your first project</button></div>';
    groups.forEach((g) => {
      const row = document.createElement('div'); row.className = 'pro-row';
      const ic = document.createElement('span'); ic.className = 'pro-ic'; ic.appendChild(groupFace(g));
      const t = document.createElement('div'); t.className = 'pro-txt'; t.innerHTML = '<b>' + esc(g.name) + '</b><small>' + esc(g.purpose || ((g.members || []).length + ' bot' + ((g.members || []).length === 1 ? '' : 's'))) + '</small>';
      const edb = document.createElement('button'); edb.type = 'button'; edb.className = 'pro-go'; edb.textContent = 'Edit';
      edb.onclick = (e) => { e.stopPropagation(); close(); root.openGroupEditor(g); };
      row.append(ic, t, edb);
      row.onclick = () => { close(); document.body.classList.remove('pl-home-on'); const open = window.openSession || (typeof openSession === 'function' ? openSession : null); if (open) open('group-' + g.id).then(load); };
      body.appendChild(row);
    });
    const n2 = p.querySelector('#pj-new2'); if (n2) n2.onclick = () => { close(); root.openGroupEditor(null); };
  };
  function groupFace(g) {
    if (g.picture) { const im = document.createElement('img'); im.className = 'grp-pic'; im.src = g.picture; im.alt = ''; return im; }
    const f = document.createElement('div'); f.className = 'mini-face'; createAvatar(f, { color: g.color || '#5b9dff', shape: g.avatar || 'round' }); return f;
  }
  // ----- picture: upload, square crop with zoom, resize to 160px; or preset look -----
  let picSrc = null, picData = '';
  function drawPic() {
    const c = $('#grp-crop'); const x = c.getContext('2d'); x.clearRect(0, 0, 160, 160);
    if (!picSrc) { picData = ''; showPic(); return; }
    const z = parseFloat($('#grp-zoom').value) || 1, side = Math.min(picSrc.width, picSrc.height) / z;
    const sx = (picSrc.width - side) * Number($('#grp-panx').value), sy = (picSrc.height - side) * Number($('#grp-pany').value);
    x.drawImage(picSrc, sx, sy, side, side, 0, 0, 160, 160); picData = c.toDataURL('image/jpeg', 0.85); showPic();
  }
  function showPic() {
    const has = !!picData; $('#grp-crop').hidden = !has; $('#grp-cropctl').hidden = !(has && picSrc);
    $('#grp-preview').hidden = has; $('#grp-picclear').hidden = !has;
    if (!has && grpPrev) grpPrev.setLook($('#grp-color').value, $('#grp-avatar').value);
  }
  let grpPrev = null;
  async function delGroup(g, skipAsk) {
    // 1.6.8+: dark confirm dialog (same as Delete bot) instead of the browser's confirm()
    if (!skipAsk) {
      const ok = await new Promise((res) => { if (window.pbBotMenu) window.pbBotMenu.confirmBox('Delete ' + g.name + '?', 'The project and its chat are removed. The bots themselves stay.', 'Delete', () => res(true)); else res(confirm('Delete the project "' + g.name + '"?')); setTimeout(() => { const c = document.getElementById('bm-confirm'); if (c) c.addEventListener('click', (e) => { if (e.target === c || e.target.textContent === 'Cancel') res(false); }); }, 0); });
      if (!ok) return false;
    }
    const r = await post('/api/groups/delete', { id: g.id, confirm: true });
    if (session === 'group-' + g.id) { if (window.pbShowHome && document.body.classList.contains('pl')) window.pbShowHome(); $('#new').click(); }
    await load(); if (window.pbToast) window.pbToast(r.ok ? g.name + ' deleted' : 'Could not delete');
    if (root.onGroupsChanged) root.onGroupsChanged(); return !!r.ok;
  }
  root.deleteGroup = delGroup;
  root.groupFace = (g) => groupFace(g);
  function memberBoxes(sel) {
    const box = $('#grp-members'); box.innerHTML = '';
    const pa = document.createElement('label'); pa.innerHTML = '<input type="checkbox" checked disabled> Ped Bot (always in)'; box.appendChild(pa);
    (root.pedroBots || []).forEach((b) => {
      const l = document.createElement('label'); const c = document.createElement('input'); c.type = 'checkbox'; c.value = b.id; c.checked = sel.includes(b.id);
      c.onchange = coordOptions; l.append(c, document.createTextNode(' ' + b.name)); box.appendChild(l);
    });
    if (!(root.pedroBots || []).length) { const p = document.createElement('small'); p.textContent = 'Make some bots first (Bots → +).'; box.appendChild(p); }
  }
  function chosen() { return Array.from(document.querySelectorAll('#grp-members input:not([disabled])')).filter((c) => c.checked).map((c) => c.value); }
  function coordOptions() {
    const s = $('#grp-coord'); const keep = s.value || (editing && editing.coordinator) || 'pedro'; s.innerHTML = '';
    ['pedro'].concat(chosen()).forEach((id) => { const o = document.createElement('option'); o.value = id; o.textContent = who(id).name; s.appendChild(o); });
    s.value = Array.from(s.options).some((o) => o.value === keep) ? keep : 'pedro';
  }
  function openEditor(g) {
    editing = g; $('#grped-title').textContent = g ? 'Edit project' : 'New project';
    picSrc = null; picData = g && g.picture ? g.picture : ''; $('#grp-color').value = (g && g.color) || '#5b9dff'; $('#grp-avatar').value = (g && g.avatar) || 'round';
    if (picData) { const im = new Image(); im.onload = () => { const c = $('#grp-crop'); c.getContext('2d').drawImage(im, 0, 0, 160, 160); }; im.src = picData; }
    showPic();
    $('#grp-name').value = g ? g.name : ''; $('#grp-purpose').value = g ? g.purpose : ''; $('#grp-coord').value = '';
    memberBoxes(g ? g.members : []); coordOptions(); $('#grp-delete').style.display = g ? '' : 'none'; $('#grpmsg').textContent = '';
    $('#grped').classList.add('open'); $('#overlay').classList.add('open');
  }
  root.openGroupEditor = (g) => { document.body.classList.remove('pl-home-on'); openEditor(g || null); };
  function closeEditor() { $('#grped').classList.remove('open'); $('#overlay').classList.remove('open'); }
  function wire() {
    if (!$('#grped')) return;
    $('#newgroup').onclick = () => openEditor(null);
    grpPrev = createAvatar($('#grp-preview'), { color: '#5b9dff', shape: 'round' });
    $('#grp-file').onchange = (e) => {
      const f = e.target.files && e.target.files[0]; if (!f) return;
      if (!/^image\//.test(f.type)) { $('#grpmsg').textContent = 'Pick an image file.'; return; }
      const url = URL.createObjectURL(f); const im = new Image();
      im.onload = () => { picSrc = im; $('#grp-zoom').value = 1; $('#grp-panx').value = 0.5; $('#grp-pany').value = 0.5; drawPic(); URL.revokeObjectURL(url); };
      im.onerror = () => { $('#grpmsg').textContent = 'Could not read that image.'; }; im.src = url; e.target.value = '';
    };
    ['#grp-zoom', '#grp-panx', '#grp-pany'].forEach((k) => { $(k).oninput = drawPic; });
    $('#grp-picclear').onclick = () => { picSrc = null; picData = ''; showPic(); };
    $('#grp-color').oninput = showPic; $('#grp-avatar').onchange = showPic;
    $('#close-grped').onclick = closeEditor; $('#overlay').addEventListener('click', closeEditor);
    $('#grp-save').onclick = async () => {
      const r = await post('/api/groups', { id: editing ? editing.id : '', name: $('#grp-name').value, picture: picData, color: $('#grp-color').value, avatar: $('#grp-avatar').value, purpose: $('#grp-purpose').value, members: chosen(), coordinator: $('#grp-coord').value });
      if (!r.ok) {
        $('#grpmsg').textContent = r.error || 'Could not save.';
        if (r.code === 'pro_required' && window.pbPlan) window.pbPlan.open(r.error);
        return;
      }
      const wasEdit = !!editing;
      closeEditor(); await load(); if (root.onGroupsChanged) root.onGroupsChanged();
      if (window.pbToast) window.pbToast(wasEdit ? 'Project saved' : 'Project created');
      const open = window.openSession || (typeof openSession === 'function' ? openSession : null);
      if (open && r.session) open(r.session).then(load);
    };
    $('#grp-delete').onclick = async () => { if (editing && await delGroup(editing)) closeEditor(); };
    setTimeout(load, 300);
  }
  // ----- @mention picker (type @ or press + in a group chat) -----
  function picker() {
    const t = $('#t'); if (!t || !root.MentionPick) return;
    const M = root.MentionPick;
    const box = $('#composer .box');
    const plus = document.createElement('button'); plus.type = 'button'; plus.className = 'ib'; plus.id = 'mention-btn';
    plus.title = 'Mention a member'; plus.textContent = '+'; plus.hidden = true; box.insertBefore(plus, t);
    const pop = document.createElement('div'); pop.id = 'mention-pop'; pop.setAttribute('role', 'listbox'); pop.hidden = true;
    $('#composer').appendChild(pop);
    let items = [], sel = 0, start = null;
    function close() { pop.hidden = true; items = []; start = null; }
    function render() {
      pop.innerHTML = '';
      items.forEach((m, i) => {
        const r = document.createElement('div'); r.className = 'mention-item' + (i === sel ? ' sel' : ''); r.setAttribute('role', 'option');
        const f = document.createElement('div'); f.className = 'mini-face'; createAvatar(f, { color: m.color || '#5b6cff', shape: m.avatar || 'round' });
        const n = document.createElement('span'); n.textContent = m.name; const id = document.createElement('small'); id.textContent = '@' + m.id;
        r.append(f, n, id);
        r.addEventListener('mousedown', (e) => { e.preventDefault(); choose(i); });
        r.addEventListener('touchstart', (e) => { e.preventDefault(); choose(i); }, { passive: false });
        pop.appendChild(r);
      });
      pop.hidden = !items.length;
    }
    function open(q, st) {
      const g = current(); if (!g) return close();
      items = M.filterMembers(M.roster(g, root.pedroBots || [], main), q); sel = 0; start = st; render();
    }
    function choose(i) {
      const m = items[i]; if (!m) return;
      const caret = t.selectionStart; const r = M.applyMention(t.value, start, caret, m.id);
      t.value = r.text; t.focus(); t.setSelectionRange(r.caret, r.caret); close();
      t.dispatchEvent(new Event('input'));
    }
    t.addEventListener('input', () => {
      if (!current()) return close();
      const q = M.mentionQuery(t.value, t.selectionStart); if (q) open(q.query, q.start); else close();
    });
    t.addEventListener('keydown', (e) => {
      if (pop.hidden) return;
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); e.stopImmediatePropagation(); sel = (sel + (e.key === 'ArrowDown' ? 1 : items.length - 1)) % items.length; render(); }
      else if (e.key === 'Enter' || e.key === 'Tab') { e.preventDefault(); e.stopImmediatePropagation(); choose(sel); }
      else if (e.key === 'Escape') { e.preventDefault(); e.stopImmediatePropagation(); close(); }
    }, true);
    t.addEventListener('blur', () => setTimeout(() => { if (document.activeElement !== t) close(); }, 150));
    plus.addEventListener('click', () => { t.focus(); open('', t.selectionStart); });
    root.updateMentionButton = () => { plus.hidden = !current(); if (!current()) close(); };
  }
  picker();
  wire();
  load();  // NEW2: populate Projects on startup (was never called)
})(this);
