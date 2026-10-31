// 1.8.4: put the new features into the real menus.
// PC: the account menu under the initials (#pd-menu, built by pc_layout.js) -> after Updates, above Help.
// Phone: the apps grid (#bottomnav .pl-extra, built by phone_layout.js) -> after Updates.
// Menus are built lazily, so a MutationObserver re-checks whenever the page changes.
(function () {
  'use strict';
  const ITEMS = [
    ['m184-avatar', '3D avatar', () => window.pbOpenAvatar && window.pbOpenAvatar()],
    ['m184-translate', 'Live translate', () => window.pb180 && window.pb180.openTranslate()],
    ['m184-tutor', 'Screen tutor', () => window.pb180 && window.pb180.openTutor()],
    ['m184-studio', 'Studio', () => window.pbStudio && window.pbStudio.open()],
    ['m184-lab', 'Lab', () => window.pbLab && window.pbLab.open()],
  ];
  const ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l2.5 5 5.5.8-4 3.9 1 5.5-5-2.7-5 2.7 1-5.5-4-3.9 5.5-.8z"/></svg>';
  const byText = (root, t) => Array.from(root.children).find((b) => b.tagName === 'BUTTON' && b.textContent.trim() === t);
  function pc() {
    const m = document.getElementById('pd-menu'); if (!m || m.querySelector('[data-m184]')) return;
    const old = byText(m, 'Avatar'); if (old) old.textContent = 'Chat face (2D)';
    const help = byText(m, 'Help'); const upd = byText(m, 'Updates');
    ITEMS.forEach(([id, label, fn]) => {
      const b = document.createElement('button'); b.type = 'button'; b.id = id; b.dataset.m184 = '1'; b.textContent = label;
      b.onclick = (e) => { e.stopPropagation(); m.classList.remove('open'); fn(); };
      if (help) m.insertBefore(b, help); else if (upd) upd.after(b); else m.appendChild(b);
    });
  }
  function phone() {
    const nav = document.getElementById('bottomnav'); if (!nav || nav.querySelector('[data-m184]')) return;
    const exAv = nav.querySelector('.pl-extra[data-target="avcbtn"]');
    if (exAv && exAv.lastChild && exAv.lastChild.nodeType === 3) exAv.lastChild.textContent = 'Chat face (2D)';
    let after = nav.querySelector('.pl-extra[data-target="acct-updates"]');
    if (!after) return;   // grid not built yet; the observer calls again
    ITEMS.forEach(([id, label, fn]) => {
      const b = document.createElement('button'); b.type = 'button'; b.className = 'pl-extra'; b.dataset.m184 = '1'; b.dataset.target = id;
      b.innerHTML = ICON; b.appendChild(document.createTextNode(label));
      b.onclick = (e) => { e.stopPropagation(); document.body.classList.remove('pl-grid-open', 'pl-home-on'); fn(); };
      after.after(b); after = b;
    });
  }
  let t = 0;
  const run = () => { clearTimeout(t); t = setTimeout(() => { try { pc(); phone(); } catch (e) {} }, 50); };
  function boot() {
    const st = document.createElement('style'); st.textContent = 'html body.pd #pd-menu button{padding:6px 12px}html body.pd #pd-menu hr{margin:3px 0}'; document.head.appendChild(st);
    run(); new MutationObserver(run).observe(document.body, { childList: true, subtree: true }); document.addEventListener('click', run, true); }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot); else boot();
  window.pbMenu184 = { pc, phone };
})();
