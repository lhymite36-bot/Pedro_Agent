// Liquid Glass helpers: a pill highlight that slides (spring) between tabs / tab-bar buttons.
(function () {
  'use strict';
  function pillFor(bar, itemSel, activeSel) {
    if (!bar || bar._gpill) return; const pill = document.createElement('i'); pill.className = 'g-pill'; pill.setAttribute('aria-hidden', 'true');
    bar.insertBefore(pill, bar.firstChild); bar._gpill = pill;
    function place() {
      const a = bar.querySelector(activeSel); if (!a || !a.offsetWidth) { pill.style.opacity = '0'; return; }
      pill.style.opacity = '1'; pill.style.width = a.offsetWidth + 'px'; pill.style.transform = 'translateX(' + a.offsetLeft + 'px)';
    }
    new MutationObserver(place).observe(bar, { subtree: true, attributes: true, attributeFilter: ['class'] });
    window.addEventListener('resize', place); setTimeout(place, 50); place();
  }
  function wire() {
    document.querySelectorAll('.tabs').forEach((t) => pillFor(t, '.tab', '.tab.active'));
    pillFor(document.getElementById('bottomnav'), 'button', 'button.active');
    const st = document.getElementById('bottomnav'); if (st && st._gpill) st._gpill.style.top = '6px', st._gpill.style.bottom = '6px';
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', wire); else wire();
  window.addEventListener('load', wire);
})();
