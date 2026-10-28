// Ped Bot 1.5.13 phone-only mode: the PC's own web UI (same sidebar, bots, avatars) runs inside the app,
// and this shim answers its /api/* calls on the phone: chats and bots from Supabase, replies from Gemini
// with the user's own key (kept encrypted by the app). Loaded before auth.js so every fetch goes through here.
(function () {
  'use strict';
  var N = window.PedroNative, C = window.PhoneCore, CFG = window.__PB_PHONE || {};
  var SB = CFG.url || '', ANON = CFG.anon || '';
  var realFetch = window.fetch.bind(window);
  var pending = {}, seq = 0, models = null, bots = [], titles = {};
  try { titles = JSON.parse(localStorage.pbPhoneTitles || '{}'); } catch (e) {}
  var settings = { speak_mode: 'never', model: '', wake: false };
  window.__PB_PHONE_MODE = true;

  function json(o, status) { return new Response(JSON.stringify(o), { status: status || 200, headers: { 'Content-Type': 'application/json' } }); }
  function auth() { var s = {}; try { s = JSON.parse(N.phoneSession() || '{}'); } catch (e) {} return s; }
  function rest(method, path, body) {
    var s = auth(); if (!s.access_token) return Promise.reject(new Error('Please sign in again.'));
    return realFetch(SB + '/rest/v1/' + path, { method: method, headers: { apikey: ANON, Authorization: 'Bearer ' + s.access_token,
      'Content-Type': 'application/json', Prefer: 'return=minimal' }, body: body ? JSON.stringify(body) : undefined })
      .then(function (r) { if (!r.ok) throw new Error('Sync error ' + r.status + (r.status === 404 ? ': run supabase/phone_sync.sql' : ''));
        return method === 'GET' ? r.json() : null; });
  }
  function loadBots() {
    return rest('GET', 'pb_bots?select=bot_id,data&order=updated_at.desc')
      .then(function (r) { bots = r.map(function (x) { return x.data; }).filter(Boolean); return bots; })
      .catch(function () { return bots; });
  }
  function botFor(session) {
    if (String(session).indexOf('bot-') !== 0) return C.MAIN;
    return bots.filter(function (b) { return 'bot-' + b.id === session; })[0] || C.MAIN;
  }

  // ---- Gemini (through the app, the key never reaches JS) ----
  window.__pbGemini = function (id, status, body) { var p = pending[id]; delete pending[id]; if (p) p(status, body); };
  function native(fn, a, b) {
    return new Promise(function (resolve) { var id = 'g' + (++seq); pending[id] = function (st, body) { resolve({ status: st, body: body }); };
      if (fn === 'list') N.geminiModels(id); else N.gemini(a, b, id); });
  }
  function availableModels() {
    if (models) return Promise.resolve(models);
    try { var c = JSON.parse(localStorage.pbModels || 'null'); if (c && Date.now() - c.at < 864e5 && c.list.length) { models = c.list; return Promise.resolve(models); } } catch (e) {}
    if (!N.geminiModels) return Promise.resolve(C.DEFAULT_MODELS);
    return native('list').then(function (r) {
      var list = r.status === 200 ? C.pickModels(r.body) : [];
      if (list.length) { models = list; localStorage.pbModels = JSON.stringify({ at: Date.now(), list: list }); }
      return list.length ? list : C.DEFAULT_MODELS;
    });
  }
  function ask(bot, history, list, notes) {
    return native('gen', list[0], JSON.stringify(C.geminiBody(bot, history))).then(function (r) {
      var out = C.replyText(r.status, r.body); out.model = list[0];
      if (!out.ok && out.gone) { notes.push(list[0] + ' is no longer available'); localStorage.removeItem('pbModels'); models = null; }
      if (!out.ok && out.retry && list.length > 1) return ask(bot, history, list.slice(1), notes);
      return out;
    });
  }

  function chat(body) {
    var text = String(body.text || '').trim(), session = body.session || C.newSessionId(), bot = botFor(session);
    var enc = new TextEncoder();
    var stream = new ReadableStream({ start: function (ctl) {
      function ev(o) { ctl.enqueue(enc.encode('data: ' + JSON.stringify(o) + '\n\n')); }
      ev({ event: 'session', session: session });
      if (!N.hasGeminiKey()) { ev({ event: 'error', text: 'Add your free Gemini key first: open the menu and tap "Phone settings".' }); ev({ event: 'done', text: '' }); ctl.close(); openSheet(); return; }
      var row = { user_id: auth().user_id, client_id: C.clientId(), session: session, role: 'user', text: text, origin: 'phone', ts: Date.now() / 1000 };
      ev({ event: 'step', label: 'Thinking on your phone…' });
      rest('GET', 'pb_messages?select=role,text,ts&session=eq.' + encodeURIComponent(session) + '&order=ts.asc&limit=200').catch(function () { return []; })
        .then(function (hist) {
          rest('POST', 'pb_messages', row).catch(function (e) { ev({ event: 'error', text: 'Not synced: ' + e.message }); });
          hist.push(row);
          var note = C.pcOnlyNote(text); if (note) ev({ event: 'token', raw: true, text: '_' + note + '_\n\n' });
          return availableModels().then(function (list) { var notes = []; return ask(bot, hist, C.modelsFor(bot, list), notes).then(function (r) { r.notes = notes; return r; }); });
        })
        .then(function (r) {
          if (r.notes && r.notes.length && r.ok) ev({ event: 'model_switch', model: r.model });
          if (r.ok) {
            ev({ event: 'token', raw: true, text: r.text });
            var a = { user_id: row.user_id, client_id: C.clientId(), session: session, role: 'assistant', text: r.text, origin: 'phone', ts: Date.now() / 1000 };
            rest('POST', 'pb_messages', a).catch(function () {});
            ev({ event: 'done' });
          } else { ev({ event: 'error', text: r.error }); ev({ event: 'done' }); if (r.badKey) openSheet(); }
          ctl.close();
        }).catch(function (e) { ev({ event: 'error', text: String(e && e.message || e) }); ev({ event: 'done' }); ctl.close(); });
    } });
    return new Response(stream, { headers: { 'Content-Type': 'text/event-stream' } });
  }

  function sessions() {
    return rest('GET', 'pb_messages?select=session,role,text,ts&order=ts.desc&limit=800').then(function (rows) {
      var by = {};
      rows.forEach(function (r) {
        var s = by[r.session] || (by[r.session] = { session: r.session, last: 0, n: 0, title: '', preview: '' });
        s.n++; if (r.ts > s.last) { s.last = r.ts; s.preview = C.stripSpeaker(r.text).slice(0, 80); }
        if (r.role === 'user') s.title = C.stripSpeaker(r.text).slice(0, 60);   // rows are newest first, so this ends on the first
      });
      return Object.keys(by).map(function (k) { var s = by[k]; if (titles[k]) s.title = titles[k]; return s; })
        .sort(function (a, b) { return b.last - a.last; });
    }).catch(function () { return []; });
  }
  function history(session) {
    return rest('GET', 'pb_messages?select=id,role,text,ts&session=eq.' + encodeURIComponent(session) + '&order=ts.asc&limit=300').catch(function () { return []; });
  }

  var PC_ONLY = 'This needs your PC. Phone mode can chat with your bots, but this works once your PC is on.';
  function route(path, q, body, method) {
    switch (path) {
      case '/api/auth/config': return json({ configured: true, url: SB, anonKey: ANON });
      case '/api/auth/me': return json({ ok: true, user: { email: CFG.email || '', is_admin: false } });
      case '/api/status': return json({ busy: false, telegram: false, model: 'Gemini on phone', active_model: (models && models[0]) || C.DEFAULT_MODELS[0], paused: false, phone_mode: true });
      case '/api/sessions': return sessions().then(json);
      case '/api/history': return history(q.get('session') || '').then(json);
      case '/api/bots': if (method === 'POST') return json({ ok: false, error: PC_ONLY }); return loadBots().then(function (b) { return json({ bots: b, tools: [] }); });
      case '/api/chat': return chat(body || {});
      case '/api/chat_side': return json({ ok: false, error: PC_ONLY });
      case '/api/rename': titles[body.session] = body.title; localStorage.pbPhoneTitles = JSON.stringify(titles); return json({ ok: true });
      case '/api/settings': if (body) Object.assign(settings, body); return json(settings);
      case '/api/sidebar': return json({ sections: [], unassigned: [] });
      case '/api/groups': return json({ groups: [] });
      case '/api/setup': return json({ needs_setup: false });
      case '/api/level': return json({ level: 0 });
      case '/api/pending': return json([]);
      case '/api/chats_count': return sessions().then(function (s) { return json({ count: s.length }); });
      case '/api/stop': case '/api/react': case '/api/pin': return json({ ok: true });
      case '/api/theme': return json(body || {});
      case '/api/phone': return json({ enabled: false, phone_mode: true });
    }
    if (method === 'POST') return json({ ok: false, error: PC_ONLY });
    return json({});
  }

  window.fetch = function (u, o) {
    var url; try { url = new URL(String((u && u.url) || u), location.href); } catch (e) { return realFetch(u, o); }
    if (url.origin !== location.origin || !(url.pathname.indexOf('/api/') === 0 || url.pathname.indexOf('/live/') === 0)) return realFetch(u, o);
    var method = ((o && o.method) || 'GET').toUpperCase(), body = null;
    if (o && typeof o.body === 'string') { try { body = JSON.parse(o.body); } catch (e) { body = null; } }
    try { return Promise.resolve(route(url.pathname, url.searchParams, body, method)); } catch (e) { return Promise.resolve(json({ ok: false, error: String(e) }, 500)); }
  };
  // No live feed on the phone: a quiet EventSource that never fires.
  var RealES = window.EventSource;
  window.EventSource = function (u) {
    if (String(u).indexOf('/api/live') === 0) { this.readyState = 1; this.close = function () {}; this.addEventListener = function () {}; return; }
    return new RealES(u);
  };

  // The app serves the UI itself; no service worker on the phone origin.
  try { if (navigator.serviceWorker) navigator.serviceWorker.register = function () { return Promise.resolve({}); }; } catch (e) {}

  // ---- Phone settings sheet (Gemini key, always-phone, try PC) ----
  function openSheet() {
    var el = document.getElementById('pb-sheet');
    if (!el) {
      el = document.createElement('div'); el.id = 'pb-sheet';
      el.innerHTML = '<div class="pb-card"><h3>Phone settings</h3>' +
        '<p>Your own free Gemini key from <a href="https://aistudio.google.com/apikey">aistudio.google.com/apikey</a>. It is stored encrypted on this phone only.</p>' +
        '<input id="pb-key" type="password" placeholder="Paste Gemini API key" autocomplete="off"><p id="pb-keystate"></p><p id="pb-models"></p>' +
        '<label><input type="checkbox" id="pb-always"> Always use phone mode (don\'t look for the PC)</label>' +
        '<div class="pb-row"><button id="pb-save" class="pb-pri">Save key</button><button id="pb-clear">Remove key</button></div>' +
        '<div class="pb-row"><button id="pb-trypc">Try the PC now</button><button id="pb-close">Close</button></div></div>';
      document.body.appendChild(el);
      var $ = function (s) { return document.getElementById(s); };
      $('pb-save').onclick = function () { var ok = N.setGeminiKey($('pb-key').value); $('pb-key').value = ''; localStorage.removeItem('pbModels'); models = null;
        $('pb-keystate').textContent = ok ? 'Saved (encrypted on this phone).' : 'That does not look like a Gemini key.'; if (ok) showModels(); };
      $('pb-clear').onclick = function () { N.clearGeminiKey(); $('pb-keystate').textContent = 'Key removed.'; };
      $('pb-always').onchange = function () { N.setPhoneOnly($('pb-always').checked); };
      $('pb-trypc').onclick = function () { N.tryPc(); };
      $('pb-close').onclick = function () { el.style.display = 'none'; };
    }
    document.getElementById('pb-keystate').textContent = N.hasGeminiKey() ? 'A key is saved on this phone.' : 'No key yet.';
    document.getElementById('pb-always').checked = N.phoneOnly();
    el.style.display = 'flex'; if (N.hasGeminiKey()) showModels();
  }
  function showModels() { availableModels().then(function (l) { var m = document.getElementById('pb-models'); if (m) m.textContent = 'Models: ' + l.slice(0, 4).join(', '); }); }
  window.PedPhone = { openSheet: openSheet };

  var css = '#pb-banner{position:fixed;top:max(6px,env(safe-area-inset-top));left:50%;transform:translateX(-50%);z-index:9998;background:#3a2a00;color:#ffcc4d;border:1px solid #6b5000;border-radius:999px;padding:4px 12px;font:600 12px system-ui;cursor:pointer;white-space:nowrap}' +
    '#pb-sheet{position:fixed;inset:0;background:#000a;display:none;align-items:flex-end;z-index:9999}#pb-sheet .pb-card{background:#16181c;color:#e7e9ea;width:100%;border-radius:16px 16px 0 0;padding:18px;font:14px system-ui}' +
    '#pb-sheet p{color:#8b9096;font-size:13px}#pb-sheet a{color:#1d9bf0}#pb-sheet input[type=password]{width:100%;box-sizing:border-box;background:#0e0f11;color:#e7e9ea;border:1px solid #26292e;border-radius:10px;padding:10px}' +
    '.pb-row{display:flex;gap:8px;margin-top:10px}.pb-row button{flex:1;background:none;color:#e7e9ea;border:1px solid #26292e;border-radius:999px;padding:9px}.pb-row .pb-pri{background:#1d9bf0;border:0;color:#fff;font-weight:700}';
  document.addEventListener('DOMContentLoaded', function () {
    var st = document.createElement('style'); st.textContent = css; document.head.appendChild(st);
    var b = document.createElement('div'); b.id = 'pb-banner'; b.textContent = CFG.reason === 'Phone mode' ? 'Phone mode ⚙' : 'Phone mode, PC offline ⚙';
    b.title = 'Phone settings'; b.onclick = openSheet; document.body.appendChild(b);
    if (!N.hasGeminiKey()) setTimeout(openSheet, 800);
  });
})();
