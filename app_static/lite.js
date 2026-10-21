// 1.4.18 Lite mode: on by default on phones (and when the device asks for reduced motion or data).
// Turns off the glass blur and moving background, makes avatars animate only on interaction, renders
// only the newest messages of a long chat and pauses polling while the app is hidden.
// Settings > "Lite mode" overrides it (auto / on / off), stored on this device only.
(function () {
  let pref = 'auto';
  try { pref = localStorage.liteMode || 'auto'; } catch (e) {}
  const phone = matchMedia('(max-width: 760px)').matches || matchMedia('(pointer: coarse)').matches;
  const ask = matchMedia('(prefers-reduced-motion: reduce)').matches || !!(navigator.connection && navigator.connection.saveData);
  const on = pref === 'on' || (pref === 'auto' && (phone || ask));
  document.documentElement.classList.toggle('lite', on);
  window.LITE = { on: on, pref: pref, historyLimit: 40,
    set: function (v) { try { localStorage.liteMode = v; } catch (e) {} location.reload(); } };
  function avatars() { if (window.PedBot && window.PedBot.lite) window.PedBot.lite.on = on; }
  avatars(); document.addEventListener('DOMContentLoaded', avatars);
})();
document.addEventListener('DOMContentLoaded', function () {
  const sel = document.getElementById('lite-mode'); if (!sel) return;
  sel.value = window.LITE.pref; sel.onchange = function () { window.LITE.set(sel.value); };
});
