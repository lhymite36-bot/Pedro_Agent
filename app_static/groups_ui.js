// Bot groups: sidebar list, editor drawer, speaker name/avatar in group chats.
(function (root) {
  const $ = (s) => document.querySelector(s);
  let groups = [], main = { id: 'pedro', name: 'Pedro_Agent', color: '#5b6cff', avatar: 'round' }, editing = null;
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
    const r = await (await fetch('/api/groups')).json(); groups = r.groups || []; if (r.main) main = r.main;
    const box = $('#groups'); if (!box) return; box.innerHTML = '';
    groups.forEach((g) => {
      const d = document.createElement('div'); d.className = 'sess botitem' + (current() && current().id === g.id ? ' active' : ''); d.dataset.id = g.id;
      const ic = document.createElement('i'); ic.className = 'grp-ic'; ic.textContent = '👥';
      const sp = document.createElement('span'); sp.textContent = g.name; sp.title = g.purpose || '';
      const ed = document.createElement('button'); ed.type = 'button'; ed.className = 'edit'; ed.title = 'Edit group'; ed.textContent = '✎';
      ed.onclick = (e) => { e.stopPropagation(); openEditor(g); };
      d.append(ic, sp, ed); d.onclick = () => openSession('group-' + g.id).then(() => { load(); root.applyBotHeader && root.applyBotHeader(); }); box.appendChild(d);
    });
    root.applyBotHeader && root.applyBotHeader();
  }
  root.loadGroups = load;
  function memberBoxes(sel) {
    const box = $('#grp-members'); box.innerHTML = '';
    const pa = document.createElement('label'); pa.innerHTML = '<input type="checkbox" checked disabled> Pedro_Agent (always in)'; box.appendChild(pa);
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
    editing = g; $('#grped-title').textContent = g ? 'Edit group' : 'New group';
    $('#grp-name').value = g ? g.name : ''; $('#grp-purpose').value = g ? g.purpose : ''; $('#grp-coord').value = '';
    memberBoxes(g ? g.members : []); coordOptions(); $('#grp-delete').style.display = g ? '' : 'none'; $('#grpmsg').textContent = '';
    $('#grped').classList.add('open'); $('#overlay').classList.add('open');
  }
  function closeEditor() { $('#grped').classList.remove('open'); $('#overlay').classList.remove('open'); }
  function wire() {
    if (!$('#grped')) return;
    $('#newgroup').onclick = () => openEditor(null);
    $('#close-grped').onclick = closeEditor; $('#overlay').addEventListener('click', closeEditor);
    $('#grp-save').onclick = async () => {
      const r = await post('/api/groups', { id: editing ? editing.id : '', name: $('#grp-name').value, purpose: $('#grp-purpose').value, members: chosen(), coordinator: $('#grp-coord').value });
      if (!r.ok) { $('#grpmsg').textContent = r.error || 'Could not save.'; return; }
      closeEditor(); await load(); openSession(r.session).then(load);
    };
    $('#grp-delete').onclick = async () => {
      if (!editing || !confirm('Delete the group "' + editing.name + '" and its chat? The bots themselves stay.')) return;
      await post('/api/groups/delete', { id: editing.id, confirm: true });
      if (session === 'group-' + editing.id) $('#new').click();
      closeEditor(); load();
    };
    setTimeout(load, 300);
  }
  wire();
})(this);
