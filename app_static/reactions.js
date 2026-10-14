// Emoji reactions on chat messages: hover or long-press a bubble, pick an emoji.
// Pills under the bubble; tapping one you gave removes it. Saved on the PC (chat_history.db).
(function () {
  const QUICK = ['👍', '❤️', '😂', '😮', '😢', '🎉', '✅'];
  const MORE = ['🔥', '👏', '🙏', '💯', '🤔', '😍', '😎', '🥳', '😅', '🙌', '👀', '💪', '🚀', '⭐', '😡', '👎', '🤝', '💡', '🎯', '😴', '🤯', '🫡', '❌', '⚠️'];
  let pop = null;
  function close() { if (pop) { pop.remove(); pop = null; } }
  document.addEventListener('click', (e) => { if (pop && !pop.contains(e.target)) close(); });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') close(); });

  async function toggle(row, emoji) {
    const id = Number(row.dataset.mid || 0); if (!id) return;
    try {
      const r = await (await fetch('/api/react', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id, emoji }) })).json();
      if (r.ok) render(row, r.reactions);
    } catch (e) { /* offline */ }
  }
  function nameOf(w) { return w === 'you' ? 'You' : (window.speakerName ? window.speakerName(w) : w); }
  function render(row, list) {
    row._reactions = list || [];
    let bar = row.querySelector('.reacts');
    const host = row.querySelector('.bubble') || row;
    if (!bar) { bar = document.createElement('div'); bar.className = 'reacts'; host.after(bar); }
    bar.innerHTML = '';
    (list || []).forEach((r) => {
      const b = document.createElement('button'); b.type = 'button'; b.className = 'react-pill';
      const mine = (r.who || []).includes('you'); b.classList.toggle('mine', mine);
      b.textContent = r.emoji + (r.who.length > 1 ? ' ' + r.who.length : '');
      b.title = r.who.map(nameOf).join(', ') + (mine ? ' (tap to remove yours)' : '');
      b.onclick = (e) => { e.stopPropagation(); toggle(row, r.emoji); };
      bar.appendChild(b);
    });
    bar.classList.toggle('hidden', !(list && list.length));
  }
  function openPicker(row, anchor) {
    close(); if (!row.dataset.mid) return;
    pop = document.createElement('div'); pop.className = 'react-pop';
    const add = (e, cls) => { const b = document.createElement('button'); b.type = 'button'; b.textContent = e; if (cls) b.className = cls;
      b.onclick = (ev) => { ev.stopPropagation(); close(); toggle(row, e); }; return b; };
    QUICK.forEach((e) => pop.appendChild(add(e)));
    const plus = document.createElement('button'); plus.type = 'button'; plus.className = 'react-more'; plus.textContent = '＋'; plus.title = 'More emoji';
    plus.onclick = (ev) => {
      ev.stopPropagation(); if (pop.querySelector('.react-grid')) return;
      const g = document.createElement('div'); g.className = 'react-grid';
      MORE.forEach((e) => g.appendChild(add(e)));
      const own = document.createElement('input'); own.placeholder = 'or type/paste any emoji'; own.maxLength = 8; own.className = 'react-own';
      own.onkeydown = (k) => { if (k.key === 'Enter' && own.value.trim()) { const v = own.value.trim(); close(); toggle(row, v); } };
      g.appendChild(own); pop.appendChild(g); own.focus();
    };
    pop.appendChild(plus);
    document.body.appendChild(pop);
    const r = (anchor || row).getBoundingClientRect();
    pop.style.top = Math.max(8, r.top - pop.offsetHeight - 6) + 'px';
    pop.style.left = Math.min(window.innerWidth - pop.offsetWidth - 8, Math.max(8, r.left)) + 'px';
  }
  function attach(row, id, list) {
    if (id) row.dataset.mid = id;
    if (!row._reactWired) {
      row._reactWired = true;
      const btn = document.createElement('button'); btn.type = 'button'; btn.className = 'react-btn'; btn.textContent = '☺'; btn.title = 'React';
      btn.onclick = (e) => { e.stopPropagation(); openPicker(row, btn); };
      row.appendChild(btn);
      let t = null;   // long-press (phone)
      row.addEventListener('touchstart', () => { t = setTimeout(() => openPicker(row), 500); }, { passive: true });
      ['touchend', 'touchmove', 'touchcancel'].forEach((n) => row.addEventListener(n, () => clearTimeout(t), { passive: true }));
      row.addEventListener('contextmenu', (e) => { if (row.dataset.mid) { e.preventDefault(); openPicker(row); } });
    }
    if (list) render(row, list);
  }
  function update(id, list) {
    const row = document.querySelector('.row[data-mid="' + id + '"]'); if (row) render(row, list);
  }
  window.Reactions = { attach, render, update, QUICK };
})();
