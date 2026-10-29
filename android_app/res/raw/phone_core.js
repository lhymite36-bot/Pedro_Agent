// Ped Bot phone-only mode core (1.5.13). Pure functions, no DOM; tested by tests/test_phone_core.js.
(function (root) {
  'use strict';
  // 1.5.13: gemini-2.0-flash is shut down and 2.5 is closed to new keys (ai.google.dev/gemini-api/docs/models, Oct 2026).
  // These are only the fallback; the app asks Google which models the key can use (pickModels).
  // 1.6.0 smart mode: 3.6-flash is the strong free workhorse; 3.8-flash (smartest free, ~20/day) leads hard requests.
  var DEFAULT_MODELS = ['gemini-3.6-flash', 'gemini-3.8-flash', 'gemini-3.5-flash-lite', 'gemini-3.1-flash-lite', 'gemini-flash-latest'];
  var PREFERRED = 'gemini-3.6-flash';
  var TOP = 'gemini-3.8-flash', TOP_BUDGET = 18;
  var HARD = /\b(build|make|create|code|program|script|app|fix|debug|plan|design|analy[sz]e|compare|research|explain why|why does|how (do|can|should)|step[- ]by[- ]step|write (a|an|the)|essay|report|strategy|optimi[sz]e|calculate|solve|prove|figure out|summari[sz]e)\b/i;
  function isHard(text) { var t = String(text || ''); return t.length > 280 || (t.match(/\n/g) || []).length >= 3 || (HARD.test(t) && t.length > 25); }
  // Hard request + TOP budget left -> TOP first; otherwise TOP goes last (saves its small quota).
  function orderFor(list, text, topLeft) {
    var out = (list || []).slice(), i = out.indexOf(TOP);
    if (i < 0) return out;
    out.splice(i, 1);
    if (isHard(text) && topLeft > 0) out.unshift(TOP); else if (topLeft > 0) out.push(TOP);
    return out;
  }
  function thinkingLevel(model, text) { return /gemma/.test(model) ? '' : isHard(text) ? 'high' : /lite/.test(model) ? 'low' : 'medium'; }

  function versionOf(id) { var m = /^gemini-(\d+(?:\.\d+)?)-/.exec(id); return m ? parseFloat(m[1]) : 0; }
  // From a GET /v1beta/models response, the text flash models that support generateContent, best first.
  function pickModels(listBody) {
    var d; try { d = typeof listBody === 'string' ? JSON.parse(listBody) : (listBody || {}); } catch (e) { d = {}; }
    var ids = (d.models || []).filter(function (m) {
      return (m.supportedGenerationMethods || []).indexOf('generateContent') >= 0;
    }).map(function (m) { return String(m.name || '').replace(/^models\//, ''); }).filter(function (id) {
      return /^gemini-[a-z0-9.\-]+$/.test(id) && /flash/.test(id) &&
        !/(tts|live|audio|image|transcribe|translate|embedding|robotics|exp|preview|thinking|\d{3,})/.test(id);
    });
    var latest = ids.filter(function (id) { return /latest$/.test(id); });
    var fixed = ids.filter(function (id) { return !/latest$/.test(id); });
    var full = fixed.filter(function (id) { return !/lite/.test(id); }).sort(function (a, b) { return versionOf(b) - versionOf(a); });
    var lite = fixed.filter(function (id) { return /lite/.test(id); }).sort(function (a, b) { return versionOf(b) - versionOf(a); });
    var out = [];
    if (ids.indexOf(PREFERRED) >= 0) out.push(PREFERRED);
    // newest full flash next (best quality), then lites, then the moving aliases
    full.concat(lite, latest).forEach(function (id) { if (out.indexOf(id) < 0) out.push(id); });
    return out.slice(0, 6);
  }
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
      'Today is ' + new Date().toDateString() + '.',
      'You have NO tools here: you cannot control the PC, read or write files, browse, run commands, or post Shorts.',
      'Never claim you did, opened, sent, posted, filled in or finished anything. If a request needs the PC, say plainly that it needs the PC and offer what you can do now (explain, plan, draft text).',
      'For graded work (assignments, quizzes) guide and explain only; never write final answers to submit.',
      'How you think: understand the real goal; for multi-step requests give a short numbered plan; consider two approaches on hard problems and pick the better one; double-check math, code and facts before answering. If you are not sure of a live fact (news, prices, scores), say so instead of guessing.',
      'Use what you know about Pedro from this chat and your notes. Lead with the answer, keep it short and natural, never repeat yourself.'
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
  function geminiBody(bot, history, max, level) {
    var rows = (history || []).slice(-(max || 80));   // 1.6.0: longer memory (was 30)
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
             generationConfig: level ? { maxOutputTokens: 8192, temperature: 0.6, thinkingConfig: { thinkingLevel: level } }
                                     : { maxOutputTokens: 4096, temperature: 0.6 } };
  }

  var DEAD = /^gemini-(1\.|2\.0|2\.5|3-pro|3\.1-pro)/;   // 1.6.0: 2.5 closed to new keys, pro is paid-only   // shut down; never try them even if a synced bot still names one
  function modelsFor(bot, available) {
    var m = String((bot && bot.model) || '').trim();
    var list = /^gemini-[a-z0-9.\-]{1,40}$/.test(m) && !DEAD.test(m) ? [m] : [];
    var base = available && available.length ? available : DEFAULT_MODELS;
    base.forEach(function (x) { if (list.indexOf(x) < 0) list.push(x); });
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
    if (status === 400 && /thinking/i.test(msg)) return { ok: false, retry: true, noThinking: true, error: msg };
    if (status === 404) return { ok: false, retry: true, gone: true, error: 'That Gemini model is no longer available (' + msg + '). Trying the next one.' };
    if (status >= 500 || status === 0) return { ok: false, retry: true, error: msg };
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
              modelsFor: modelsFor, isHard: isHard, orderFor: orderFor, thinkingLevel: thinkingLevel, TOP: TOP, TOP_BUDGET: TOP_BUDGET, pickModels: pickModels, DEFAULT_MODELS: DEFAULT_MODELS, replyText: replyText, sessionFor: sessionFor, newSessionId: newSessionId,
              clientId: clientId, sessionsFrom: sessionsFrom, stripSpeaker: stripSpeaker };
  if (typeof module !== 'undefined' && module.exports) module.exports = api; else root.PhoneCore = api;
})(this);
