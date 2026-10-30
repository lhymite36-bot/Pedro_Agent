// 1.8.2 Studio: WhatsApp drafts, trend radar, video edit, shortcuts, call-me, app factory, meeting notes, price watch, photo-to-app, mood.
(function () {
  'use strict';
  const $ = (s, r) => (r || document).querySelector(s);
  const api = (b) => fetch('/api/studio', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) }).then((r) => r.json()).catch(() => ({ ok: false, error: 'Ped Bot is not reachable.' }));
  const esc = (t) => String(t == null ? '' : t).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const b64 = (file) => new Promise((ok) => { const r = new FileReader(); r.onload = () => ok(String(r.result).split(',')[1] || ''); r.readAsDataURL(file); });
  const TOOLS = [
    ['wa', 'WhatsApp drafts'], ['trends', 'Trend radar'], ['video', 'Video edit'], ['shortcuts', 'Shortcuts'], ['calls', 'Call me'],
    ['factory', 'App factory'], ['notes', 'Meeting notes'], ['prices', 'Price watch'], ['photo', 'Photo → app'], ['mood', 'Mood journal']];

  function open(tab) {
    const old = $('#st182'); if (old) old.remove();
    const p = document.createElement('div'); p.id = 'st182'; p.className = 'b180-page st182';
    p.innerHTML = '<div class="b180-head"><button type="button" class="b180-x" aria-label="Close"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M18 6 6 18M6 6l12 12"/></svg></button><b>Studio</b><span class="b180-pill">10 tools</span></div>' +
      '<div class="st-tabs">' + TOOLS.map(([k, l]) => '<button type="button" data-k="' + k + '">' + l + '</button>').join('') + '</div><div class="b180-body st-body"></div>';
    document.body.appendChild(p);
    $('.b180-x', p).onclick = () => p.remove();
    p.querySelectorAll('.st-tabs button').forEach((b) => (b.onclick = () => show(b.dataset.k)));
    function show(k) {
      p.querySelectorAll('.st-tabs button').forEach((b) => b.classList.toggle('on', b.dataset.k === k));
      const t = p.querySelector('.st-tabs'), b = t.querySelector('.on'); if (b) t.scrollLeft = b.offsetLeft - 16;
      const body = $('.st-body', p); body.innerHTML = ''; (VIEWS[k] || VIEWS.wa)(body); localStorage.pbStudioTab = k;
    }
    show(tab || localStorage.pbStudioTab || 'wa');
  }
  const out = (body, html) => { let o = $('.st-out', body); if (!o) { o = document.createElement('div'); o.className = 'st-out'; body.appendChild(o); } o.innerHTML = html; return o; };
  const err = (r) => '<div class="st-err">' + esc(r.error || 'Something went wrong.') + '</div>';
  const busy = (btn, on) => { btn.disabled = on; btn.classList.toggle('busy', on); };

  const VIEWS = {
    wa(body) {
      body.innerHTML = '<div class="b180-sec">Texting-style drafts. Nothing is ever sent for you.</div>' +
        '<input id="wa-to" placeholder="To (name or number, optional)"><textarea id="wa-in" rows="3" placeholder="What do you want to say? e.g. tell Kofi I\'m running 10 min late but bringing food"></textarea>' +
        '<div class="b180-bar"><select id="wa-tone"><option>casual</option><option>funny</option><option>sweet</option><option>polite</option><option>formal</option></select><button type="button" class="b180-btn acc" id="wa-go">Write drafts</button></div>';
      $('#wa-go', body).onclick = async (e) => {
        busy(e.target, true); const r = await api({ tool: 'wa', to: $('#wa-to', body).value, intent: $('#wa-in', body).value, tone: $('#wa-tone', body).value }); busy(e.target, false);
        if (!r.ok) return out(body, err(r));
        out(body, r.drafts.map((d, i) => '<div class="b180-item st-wa"><div class="st-bubble">' + esc(d) + '</div><a class="b180-btn" target="_blank" rel="noopener" href="' + esc(r.links[i]) + '">Approve → open WhatsApp</a></div>').join('') + '<small class="st-note">' + esc(r.note) + '</small>');
      };
    },
    trends(body) {
      body.innerHTML = '<div class="b180-sec">Today\'s trends turned into psychology Short ideas</div><div class="b180-bar"><select id="tr-geo"><option value="IN">India</option><option value="GH">Ghana</option><option value="US">USA</option><option value="GB">UK</option></select><button type="button" class="b180-btn acc" id="tr-go">Scan trends</button></div>';
      $('#tr-go', body).onclick = async (e) => {
        busy(e.target, true); const r = await api({ tool: 'trends', geo: $('#tr-geo', body).value }); busy(e.target, false);
        if (!r.ok) return out(body, err(r));
        const o = out(body, (r.ideas || []).map((i) => '<div class="b180-item"><small>' + esc(i.trend) + ' · ' + esc(i.angle) + '</small><div><b>' + esc(i.title) + '</b><br>' + esc(i.hook) + '</div><button type="button" class="b180-btn st-use" data-t="' + esc(i.title) + '">Use for next Short</button></div>').join('') +
          (r.error ? err(r) : '') + '<small class="st-note">Trending: ' + esc((r.trends || []).slice(0, 12).join(' · ')) + '</small>');
        o.querySelectorAll('.st-use').forEach((b) => (b.onclick = async () => { await api({ tool: 'trend_use', title: b.dataset.t }); b.textContent = 'Saved ✓'; }));
      };
    },
    video(body) {
      body.innerHTML = '<div class="b180-sec">Edit a video on this PC by saying what you want</div><input id="ve-path" placeholder="Video path, e.g. C:\\Users\\Pedro\\Videos\\clip.mp4"><textarea id="ve-in" rows="2" placeholder="e.g. trim 0:05 to 0:25, make it vertical for Shorts, add caption \'wait for it\'"></textarea><button type="button" class="b180-btn acc" id="ve-go">Edit with ffmpeg</button>';
      $('#ve-go', body).onclick = async (e) => {
        busy(e.target, true); out(body, '<div class="b180-item">Editing… (big videos take a while)</div>');
        const r = await api({ tool: 'video', path: $('#ve-path', body).value, instruction: $('#ve-in', body).value }); busy(e.target, false);
        out(body, r.ok ? '<div class="b180-item"><small>Saved</small><div>' + esc(r.output) + '</div></div>' : err(r) + (r.detail ? '<small class="st-note">' + esc(r.detail) + '</small>' : ''));
      };
    },
    shortcuts(body) {
      body.innerHTML = '<div class="b180-sec">One-tap commands for your PC (from the phone too)</div><input id="sc-l" placeholder="Name, e.g. Gaming mode"><input id="sc-c" placeholder="Command, e.g. close Chrome and open Steam"><div class="b180-bar"><input id="sc-t" placeholder="Remind me at (optional, 21:00)"><button type="button" class="b180-btn acc" id="sc-add">Add</button></div><div class="st-list"></div>';
      const list = $('.st-list', body);
      const draw = (r) => { list.innerHTML = r.ok ? (r.items || []).map((i) => '<div class="b180-item st-row"><div><b>' + esc(i.label) + '</b><small>' + esc(i.command) + (i.at ? ' · ' + esc(i.at) : '') + '</small></div><button type="button" class="b180-btn acc" data-run="' + esc(i.command) + '">Run</button><button type="button" class="b180-btn" data-del="' + i.id + '">✕</button></div>').join('') || '<small class="st-note">No shortcuts yet.</small>' : err(r);
        list.querySelectorAll('[data-del]').forEach((b) => (b.onclick = async () => draw(await api({ tool: 'shortcuts', action: 'delete', id: b.dataset.del }))));
        list.querySelectorAll('[data-run]').forEach((b) => (b.onclick = () => { const i = document.querySelector('#input, #msg, textarea'); $('#st182').remove(); if (i) { i.value = b.dataset.run; i.dispatchEvent(new Event('input')); const s = document.querySelector('#send, .send'); if (s) s.click(); } })); };
      $('#sc-add', body).onclick = async () => draw(await api({ tool: 'shortcuts', action: 'add', label: $('#sc-l', body).value, command: $('#sc-c', body).value, at: $('#sc-t', body).value }));
      api({ tool: 'shortcuts' }).then(draw);
    },
    calls(body) {
      body.innerHTML = '<div class="b180-sec">Ped Bot rings you like an alarm and talks</div><div class="b180-bar"><input id="cl-t" type="time" value="07:30"><input id="cl-a" placeholder="About, e.g. wake up, gym, upload Short"></div><label class="b180-row"><input type="checkbox" id="cl-r"> Every day</label><button type="button" class="b180-btn acc" id="cl-add">Schedule call</button><div class="st-list"></div>';
      const list = $('.st-list', body);
      const draw = (r) => { list.innerHTML = (r.items || []).map((i) => '<div class="b180-item st-row"><div><b>' + esc(i.at) + '</b><small>' + esc(i.about) + (i.repeat ? ' · daily' : '') + '</small></div><button type="button" class="b180-btn" data-del="' + i.id + '">✕</button></div>').join('') || (r.ok ? '<small class="st-note">No calls scheduled.</small>' : err(r));
        list.querySelectorAll('[data-del]').forEach((b) => (b.onclick = async () => draw(await api({ tool: 'calls', action: 'delete', id: b.dataset.del })))); };
      $('#cl-add', body).onclick = async () => draw(await api({ tool: 'calls', action: 'add', at: $('#cl-t', body).value, about: $('#cl-a', body).value, repeat: $('#cl-r', body).checked }));
      api({ tool: 'calls' }).then(draw);
    },
    factory(body) {
      body.innerHTML = '<div class="b180-sec">Describe an app - the coding bot builds, tests and fixes it</div><textarea id="af-in" rows="4" placeholder="e.g. a habit tracker with streaks and a dark theme"></textarea><button type="button" class="b180-btn acc" id="af-go">Build app</button>';
      $('#af-go', body).onclick = async (e) => {
        busy(e.target, true); const r = await api({ tool: 'factory', goal: $('#af-in', body).value });
        if (!r.ok) { busy(e.target, false); return out(body, err(r)); }
        out(body, '<div class="b180-item">Building… you can close this; you\'ll get a check-in when it\'s done.</div>');
        const poll = setInterval(async () => { const j = await api({ tool: 'factory_job', job: r.job }); if (j.status !== 'building') { clearInterval(poll); busy(e.target, false); out(body, '<div class="b180-item"><small>' + esc(j.status) + '</small><div>' + esc(j.message || '') + '</div></div>'); } }, 4000);
      };
    },
    notes(body) {
      body.innerHTML = '<div class="b180-sec">Record a meeting, get notes + action items</div><input id="mn-t" placeholder="Meeting name (optional)"><button type="button" class="b180-btn acc" id="mn-rec">● Start recording</button><small class="st-note">Notes are saved in Documents\\Ped Bot Notes. Up to ~15 min per recording on the free tier.</small>';
      let rec = null, chunks = [];
      $('#mn-rec', body).onclick = async (e) => {
        const b = e.target;
        if (rec) { rec.stop(); return; }
        try { const s = await navigator.mediaDevices.getUserMedia({ audio: true }); chunks = []; rec = new MediaRecorder(s);
          rec.ondataavailable = (d) => chunks.push(d.data);
          rec.onstop = async () => { s.getTracks().forEach((t) => t.stop()); rec = null; b.textContent = '● Start recording'; busy(b, true); out(body, '<div class="b180-item">Writing notes…</div>');
            const blob = new Blob(chunks, { type: chunks[0] && chunks[0].type || 'audio/webm' });
            const r = await api({ tool: 'notes', audio: await b64(blob), mime: blob.type, title: $('#mn-t', body).value }); busy(b, false);
            out(body, r.ok ? '<div class="b180-item"><small>' + esc(r.file) + '</small><div><b>' + esc(r.title) + '</b><br>' + esc(r.summary) + '</div></div>' + (r.action_items || []).map((a) => '<div class="b180-item">☐ ' + esc(a.what) + ' <small>' + esc(a.who) + ' ' + esc(a.when) + '</small></div>').join('') : err(r)); };
          rec.start(1000); b.textContent = '■ Stop & make notes'; } catch (x) { out(body, err({ error: 'Microphone not available here.' })); }
      };
    },
    prices(body) {
      body.innerHTML = '<div class="b180-sec">Get a check-in when a price drops</div><input id="pw-u" placeholder="Product link (Amazon, Flipkart, any shop)"><div class="b180-bar"><input id="pw-t" inputmode="decimal" placeholder="Alert below this price (e.g. 1499)"><button type="button" class="b180-btn acc" id="pw-add">Watch</button></div><button type="button" class="b180-btn" id="pw-chk">Check all now</button><div class="st-list"></div>';
      const list = $('.st-list', body);
      const draw = (r) => { list.innerHTML = r.ok ? (r.items || []).map((i) => '<div class="b180-item st-row"><div><b>' + esc(i.name || i.url) + '</b><small>Now: ' + (i.price != null ? esc(i.price.toLocaleString()) : (i.error ? 'could not read' : '…')) + ' · target ' + esc(i.target) + '</small></div><button type="button" class="b180-btn" data-del="' + i.id + '">✕</button></div>').join('') || '<small class="st-note">Nothing watched yet. Checked every 6 hours.</small>' : err(r);
        list.querySelectorAll('[data-del]').forEach((b) => (b.onclick = async () => draw(await api({ tool: 'prices', action: 'delete', id: b.dataset.del })))); };
      $('#pw-add', body).onclick = async (e) => { busy(e.target, true); draw(await api({ tool: 'prices', action: 'add', url: $('#pw-u', body).value, target: $('#pw-t', body).value })); busy(e.target, false); };
      $('#pw-chk', body).onclick = async (e) => { busy(e.target, true); draw(await api({ tool: 'prices', action: 'check' })); busy(e.target, false); };
      api({ tool: 'prices' }).then(draw);
    },
    photo(body) {
      body.innerHTML = '<div class="b180-sec">Snap a sketch or screenshot → working app</div><input type="file" id="pa-f" accept="image/*" capture="environment"><input id="pa-n" placeholder="Extra wishes (optional)"><button type="button" class="b180-btn acc" id="pa-go">Make app</button>';
      $('#pa-go', body).onclick = async (e) => {
        const f = $('#pa-f', body).files[0]; if (!f) return out(body, err({ error: 'Pick a photo first.' }));
        busy(e.target, true); out(body, '<div class="b180-item">Building from the photo…</div>');
        const r = await api({ tool: 'photo_app', image: await b64(f), notes: $('#pa-n', body).value }); busy(e.target, false);
        out(body, r.ok ? '<div class="b180-item"><small>' + esc(r.folder) + '</small><a class="b180-btn acc" target="_blank" href="' + esc(r.preview) + '">Open app</a></div><iframe class="st-prev" src="' + esc(r.preview) + '"></iframe>' : err(r));
      };
    },
    mood(body) {
      body.innerHTML = '<div class="b180-sec">How was today? One line is enough.</div><textarea id="md-in" rows="3" placeholder="e.g. tired but the Short hit 2k views"></textarea><button type="button" class="b180-btn acc" id="md-go">Save</button><div class="st-chart"></div><div class="st-list"></div>';
      const draw = (r) => { const it = r.items || [];
        $('.st-chart', body).innerHTML = it.slice(-30).map((i) => '<i title="' + esc(i.day + ' ' + i.feeling) + '" style="height:' + i.score * 10 + '%"></i>').join('');
        $('.st-list', body).innerHTML = it.slice().reverse().slice(0, 10).map((i) => '<div class="b180-item"><small>' + esc(i.day) + ' · ' + i.score + '/10 · ' + esc(i.feeling) + '</small><div>' + esc(i.text) + '</div><small class="st-refl">' + esc(i.reflection) + '</small></div>').join(''); };
      $('#md-go', body).onclick = async (e) => { busy(e.target, true); draw(await api({ tool: 'mood', action: 'add', text: $('#md-in', body).value })); $('#md-in', body).value = ''; busy(e.target, false); };
      api({ tool: 'mood' }).then(draw);
    },
  };

  // Incoming "call": ring screen with answer / decline. Polls every 20 s.
  let ring = null;
  async function checkCall() {
    if (ring) return; const r = await api({ tool: 'pending_call' }); if (!r.ok || !r.call) return;
    ring = document.createElement('div'); ring.id = 'st-call';
    ring.innerHTML = '<div class="st-call-in"><div class="st-ava">P</div><b>Ped Bot</b><small>calling about ' + esc(r.call.about) + '</small><div class="st-call-b"><button type="button" class="st-dec">Decline</button><button type="button" class="st-acc">Answer</button></div></div>';
    document.body.appendChild(ring);
    let tone = null; try { const C = new (window.AudioContext || window.webkitAudioContext)(); const o = C.createOscillator(), g = C.createGain(); o.frequency.value = 620; o.connect(g); g.connect(C.destination); o.start(); let on = 0; tone = setInterval(() => { g.gain.value = (on = 1 - on) * 0.15; }, 500); ring._c = C; } catch (e) {}
    const end = () => { clearInterval(tone); try { ring._c.close(); } catch (e) {} ring.remove(); ring = null; };
    $('.st-dec', ring).onclick = end;
    $('.st-acc', ring).onclick = async () => { clearInterval(tone); try { ring._c.close(); } catch (e) {} $('small', ring).textContent = r.call.say;
      try { const s = await fetch('/api/speak_text', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text: r.call.say }) }).then((x) => x.json()); if (s.url) { const a = new Audio(s.url); a.onended = end; a.play(); } else setTimeout(end, 6000); } catch (e) { setTimeout(end, 6000); } };
  }

  function addMenu() {
    const menu = $('#pl-menu');
    if (menu && !menu.querySelector('[data-st182]')) { const b = document.createElement('button'); b.type = 'button'; b.dataset.st182 = '1'; b.textContent = 'Studio (10 tools)'; b.onclick = (e) => { e.stopPropagation(); document.body.classList.remove('pl-menu-open'); open(); }; menu.appendChild(b); }
    const box = $('#b180-side');
    if (box && !box.querySelector('[data-st182]')) { const b = document.createElement('button'); b.type = 'button'; b.className = 'side-btn'; b.dataset.st182 = '1'; b.textContent = 'Studio'; b.onclick = () => open(); box.appendChild(b); }
  }
  function boot() { addMenu(); setTimeout(addMenu, 1700); setInterval(checkCall, 20000); setTimeout(checkCall, 3000); }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot); else boot();
  window.pbStudio = { open, checkCall };
})();
