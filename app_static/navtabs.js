// 1.4.19: the phone bottom bar is true tab switching. Tapping a tab closes every other screen first, so screens
// never stack; the Android back button returns to Chats (one step), not through a stack of panels.
(function () {
  const nav = document.getElementById('bottomnav'); if (!nav) return;
  const PANELS = ['routines', 'tasks', 'connectors'];
  function closeAll(except) {
    PANELS.forEach((id) => { if (id !== except) { const p = document.getElementById(id); if (p && !p.hidden) p.hidden = true; } });
    if (except !== 'live' && window.pbCloseLive) window.pbCloseLive();
    if (except !== 'settings') { const s = document.getElementById('settings'); if (s && s.classList.contains('open')) { s.classList.remove('open'); const o = document.getElementById('overlay'); if (o) o.classList.remove('open'); } }
    if (except !== 'chats' && except !== 'bots' && window.closeMobileSide) window.closeMobileSide();
  }
  function anyOpen() {
    return PANELS.some((id) => { const p = document.getElementById(id); return p && !p.hidden; }) ||
      document.body.classList.contains('live-open') || (document.getElementById('settings') || { classList: { contains: () => false } }).classList.contains('open');
  }
  function setActive(name) { nav.querySelectorAll('button').forEach((b) => b.classList.toggle('active', b.dataset.nav === name)); }
  let marked = false;
  nav.addEventListener('click', (e) => {
    const b = e.target.closest('button'); if (!b) return;
    const name = b.dataset.nav;
    // a tap on the tab that is already showing does nothing (no toggle-off, no reopen flicker)
    if (name !== 'chats' && b.classList.contains('active') && anyOpen()) { e.stopImmediatePropagation(); return; }
    closeAll(name);
    if (name === 'chats') { setActive('chats'); return; }
    if (!marked) { try { history.pushState({ pbTab: 1 }, ''); marked = true; } catch (err) {} }
    setTimeout(() => setActive(name), 0);   // after the screen's own handler (some reset the highlight)
  }, true);   // capture: runs before each screen's own open handler
  window.addEventListener('popstate', () => {
    if (!marked) return; marked = false;
    if (anyOpen()) { closeAll('chats'); setActive('chats'); }
  });
  window.pbTabs = { closeAll, anyOpen };
})();
