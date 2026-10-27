// Settings > Connect phone (PC only).
(function () {
  const $ = (s) => document.querySelector(s);
  const local = /^(127\.0\.0\.1|localhost)$/.test(location.hostname);
  if (!$('#phone-sec')) return;
  if (!local) { $('#phone-sec').hidden = true; return; }
  const post = async (u, b) => (await fetch(u, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b || {}) })).json();
  let timer = null;
  function show(st) {
    $('#phone-on').checked = !!st.enabled; $('#phone-body').hidden = !st.enabled;
    const a = $('#phone-apk'); a.innerHTML = ''; const l = document.createElement('a'); l.href = st.apk; l.target = '_blank'; l.rel = 'noopener'; l.textContent = 'download the APK'; a.appendChild(l);
    $('#phone-url').textContent = st.url || '(starting…)';
  }
  async function pair() {
    const r = await post('/api/phone/pair');
    if (!r.ok) { $('#phone-msg').textContent = r.error; clearTimeout(timer); timer = setTimeout(pair, 3000); return; }
    $('#phone-msg').textContent = 'Ready. Scan with the Ped Bot app.';
    const box = $('#phone-qr'); box.textContent = '';
      if (r.qr_svg) {
        const img = document.createElement('img');
        img.alt = 'Pairing QR';
        img.width = 180; img.height = 180;
        img.src = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(r.qr_svg);
        box.appendChild(img);
      }
      $('#phone-code').textContent = r.code; show(r);
  }
  async function refresh() { const st = await (await fetch('/api/phone')).json(); show(st); if (st.enabled) pair(); }
  $('#phone-on').onchange = async (e) => {
    if (e.target.checked) {
      $('#phone-msg').textContent = 'Starting phone access…';
      const r = await post('/api/phone/enable', {});
      if (r.needs_consent) { $('#phone-consent').hidden = false; e.target.checked = false; return; }
      if (!r.ok && r.error) { $('#phone-msg').textContent = r.error; }
      show(r); pair();
    } else { if (!confirm('Turn off phone access? Your phone will disconnect until you turn it back on.')) { e.target.checked = true; return; } show(await post('/api/phone/disable')); $('#phone-qr').textContent = ''; }
  };
  $('#phone-allow').onclick = async () => {
    $('#phone-consent').hidden = true; $('#phone-msg').textContent = 'Downloading cloudflared…'; $('#phone-body').hidden = false;
    const r = await post('/api/phone/enable', { consent: true }); if (!r.ok && r.error) $('#phone-msg').textContent = r.error; show(r); if (r.ok) pair();
  };
  $('#phone-newqr').onclick = pair;
  $('#phone-unpair').onclick = async () => {
    if (!confirm('Unpair ALL phones? They will be signed out and need a new QR code.')) return;
    const r = await post('/api/phone/unpair', { confirm: true }); $('#phone-msg').textContent = r.message || r.error || ''; pair();
  };
  const sb = $('#setbtn'); if (sb) sb.addEventListener('click', refresh);
})();
