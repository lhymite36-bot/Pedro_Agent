// Ped Bot phone-only mode core (1.5.12). Pure functions, no DOM; tested by tests/test_phone_core.js.
(function (root) {
  'use strict';
  var DEFAULT_MODELS = ['gemini-2.5-flash', 'gemini-2.0-flash'];
  var MAIN = { id: 'pedro', name: 'Ped Bot', color: '#1d9bf0', role: '' };

  // Requests that need the PC (tools the phone cannot run). The phone never pretends to do these.
  var PC_ONLY = [
    { re: /\b(screenshot|screen ?shot|click|mouse|keyboard|type (it|this) in|open (the )?(app|program|chrome|browser|folder|file explorer)|my pc|my computer|desktop)\b/i, what: 'PC control' },
    { re: /\b(file|files|folder|download(s)?|documents|drive [a-z]:|c:\\|save (it|this) to)\b/i, what: 'files on your PC' },
    { re: /\b(shorts?|post (it |this )?(to|on) (youtube|tiktok)|buffer|upload (a |the )?video)\b/i, what: 'Shorts posting' },
    { re: /\b(terminal|powershell|command prompt|run (the |a )?(command|script)|install)\b/i, what: 'running commands' },
    { re: /\b(wingz|assignment|quiz|submit)\b/i, what: 'browser tasks on your PC' }
  ];

  function pcOnlyNote(text) {
    var hits = [];
    PC_ONLY.forEach(function (r) { if (r.re.test(String(text || '')) && hits.indexOf(r.what) < 0) hits.push(r.what); });
    if (!hits.length) return '';
    return 'That needs your PC (' + hits.join(', ') + '). Phone mode can talk, plan and draft, but it cannot do that until your PC is on.';
  }

  function systemPrompt(bot) {
    var b = bot || MAIN;
    var lines = [
      'You are ' + (b.name || 'Ped Bot') + ', Pedro\'s assistant, running in PHONE MODE because his PC is offline.',
      'You have NO tools here: you cannot control the PC, read or write files, browse, run commands, or post Shorts.',
      'Never claim you did, opened, sent, posted, filled in or finished anything. If a request needs the PC, say plainly that it needs the PC and offer what you can do now (explain, plan, draft text).',
      'For graded work (assignments, quizzes) guide and explain only; never write final answers to submit.',
      'Be brief and friendly.'
    ];
    if (b.role) lines.push('', 'Your role and persona:', String(b.role).slice(0, 8000));
    var notes = b.notes;
    if (Array.isArray(notes) && notes.length) {
      lines.push('', 'Notes you keep:');
      notes.slice(0, 30).forEach(function (n) { lines.push('- ' + String((n && (n.text || n.note)) || n).slice(0, 400)); });
    }
    var skills = b.skills;
    if (Array.isArray(skills) && skills.length) {
      lines.push('', 'Skills you know (steps need the PC to actually run):');
      skills.slice(0, 20).forEach(function (s) { lines.push('- ' + String((s && (s.name || s.title)) || s).slice(0, 120)); });
    }
    return lines.join('\n');
  }

  function stripSpeaker(text) { return String(text || '').replace(/^\[\[@[a-z0-9-]+\]\]\s?/, ''); }

  // Build a Gemini generateContent body from chat history (oldest first). Keeps the last `max` turns.
  function geminiBody(bot, history, max) {
    var rows = (history || []).slice(-(max || 30));
    var contents = [];
    rows.forEach(function (m) {
      var role = m.role === 'user' ? 'user' : 'model';
      var text = stripSpeaker(m.text).trim(); if (!text) return;
      var last = contents[contents.length - 1];
      if (last && last.role === role) last.parts[0].text += '\n\n' + text;   // Gemini wants alternating roles
      else contents.push({ role: role, parts: [{ text: text }] });
    });
    while (contents.length && contents[0].role !== 'user') contents.shift();
    return { systemInstruction: { parts: [{ text: systemPrompt(bot) }] }, contents: contents,
             generationConfig: { maxOutputTokens: 2048, temperature: 0.7 } };
  }

  function modelsFor(bot) {
    var m = String((bot && bot.model) || '').trim();
    var list = /^gemini-[a-z0-9.\-]{1,40}$/.test(m) ? [m] : [];
    DEFAULT_MODELS.forEach(function (x) { if (list.indexOf(x) < 0) list.push(x); });
    return list;
  }

  function replyText(status, body) {
    var d; try { d = JSON.parse(body || '{}'); } catch (e) { d = {}; }
    if (status >= 200 && status < 300) {
      var c = d.candidates && d.candidates[0];
      var parts = (c && c.content && c.content.parts) || [];
      var text = parts.map(function (p) { return p.text || ''; }).join('').trim();
      if (text) return { ok: true, text: text };
      return { ok: false, retry: false, error: 'Gemini returned no text' + (c && c.finishReason ? ' (' + c.finishReason + ')' : '') + '.' };
    }
    var msg = (d.error && d.error.message) || ('HTTP ' + status);
    if (status === 400 && /api key/i.test(msg)) return { ok: false, retry: false, badKey: true, error: 'Your Gemini key was rejected. Check it in Phone settings.' };
    if (status === 429) return { ok: false, retry: true, error: 'Free Gemini limit reached for now. Try again in a minute.' };
    if (status === 404 || status >= 500 || status === 0) return { ok: false, retry: true, error: msg };
    return { ok: false, retry: false, error: msg };
  }

  function sessionFor(bot) { return bot && bot.id && bot.id !== 'pedro' ? 'bot-' + bot.id : ''; }
  function newSessionId(now) { return 'phone-' + (now || Date.now()).toString(36); }
  function clientId(rand) { return 'phone:' + (rand || (Date.now().toString(36) + Math.random().toString(36).slice(2, 10))); }

  // Group recent message rows into chat sessions, newest first. Bot sessions stay under their bot.
  function sessionsFrom(rows) {
    var by = {};
    (rows || []).forEach(function (r) {
      var s = by[r.session] || (by[r.session] = { session: r.session, ts: 0, preview: '' });
      if (r.ts >= s.ts) { s.ts = r.ts; s.preview = stripSpeaker(r.text).slice(0, 60); }
    });
    return Object.keys(by).map(function (k) { return by[k]; })
      .filter(function (s) { return s.session.indexOf('bot-') !== 0 && s.session.indexOf('group-') !== 0; })
      .sort(function (a, b) { return b.ts - a.ts; });
  }

  var api = { MAIN: MAIN, PC_ONLY: PC_ONLY, pcOnlyNote: pcOnlyNote, systemPrompt: systemPrompt, geminiBody: geminiBody,
              modelsFor: modelsFor, replyText: replyText, sessionFor: sessionFor, newSessionId: newSessionId,
              clientId: clientId, sessionsFrom: sessionsFrom, stripSpeaker: stripSpeaker };
  if (typeof module !== 'undefined' && module.exports) module.exports = api; else root.PhoneCore = api;
})(this);
