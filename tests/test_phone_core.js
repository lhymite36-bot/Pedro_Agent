// node tests/test_phone_core.js
const assert = require('assert');
const C = require('../android_app/res/raw/phone_core.js');

assert.ok(C.pcOnlyNote('take a screenshot of my desktop').includes('PC control'));
assert.ok(C.pcOnlyNote('post this to YouTube').includes('Shorts posting'));
assert.ok(C.pcOnlyNote('do my Wingz assignment').includes('needs your PC'));
assert.strictEqual(C.pcOnlyNote('what is a black hole?'), '');

const bot = { id: 'coach', name: 'Coach', role: 'You are a study coach.', model: 'gemini-2.5-flash', notes: [{ text: 'likes short answers' }], skills: [{ name: 'Plan week' }] };
const sp = C.systemPrompt(bot);
assert.ok(sp.includes('Coach') && sp.includes('study coach') && sp.includes('likes short answers') && sp.includes('Plan week'));
assert.ok(/NO tools/.test(sp) && /Never claim/.test(sp));

const body = C.geminiBody(bot, [
  { role: 'assistant', text: 'hi from before' },
  { role: 'user', text: 'a' }, { role: 'user', text: 'b' },
  { role: 'assistant', text: '[[@coach]] reply' }]);
assert.strictEqual(body.contents[0].role, 'user');
assert.strictEqual(body.contents[0].parts[0].text, 'a\n\nb');
assert.strictEqual(body.contents[1].parts[0].text, 'reply');
assert.ok(body.systemInstruction.parts[0].text.includes('Coach'));

assert.deepStrictEqual(C.modelsFor(bot), ['gemini-2.5-flash', 'gemini-2.0-flash']);
assert.deepStrictEqual(C.modelsFor({ model: 'groq:llama' }), ['gemini-2.5-flash', 'gemini-2.0-flash']);

const ok = C.replyText(200, JSON.stringify({ candidates: [{ content: { parts: [{ text: 'Hello' }] } }] }));
assert.ok(ok.ok && ok.text === 'Hello');
assert.ok(C.replyText(429, '{}').retry);
assert.ok(C.replyText(400, JSON.stringify({ error: { message: 'API key not valid' } })).badKey);
assert.ok(!C.replyText(200, '{}').ok);

assert.strictEqual(C.sessionFor(bot), 'bot-coach');
assert.strictEqual(C.sessionFor(C.MAIN), '');
assert.ok(C.clientId().startsWith('phone:'));
const ss = C.sessionsFrom([{ session: 'a', text: 'x', ts: 1 }, { session: 'b', text: 'y', ts: 5 }, { session: 'bot-coach', text: 'z', ts: 9 }]);
assert.deepStrictEqual(ss.map((s) => s.session), ['b', 'a']);

// The HTML must embed the core, show the badge and never mention storing the key in Supabase.
const fs = require('fs');
const html = fs.readFileSync(__dirname + '/../android_app/res/raw/phone_mode.html', 'utf8');
assert.ok(html.includes('/*{{CORE}}*/') && html.includes('Phone mode, PC offline'));
assert.ok(html.includes('PC-only tools are off'));
const java = fs.readFileSync(__dirname + '/../android_app/src/com/pedro/agent/MainActivity.java', 'utf8');
assert.ok(java.includes('pcOnline(url)') && java.includes('showPhoneMode'));
assert.ok(fs.readFileSync(__dirname + '/../android_app/src/com/pedro/agent/SecureStore.java', 'utf8').includes('AndroidKeyStore'));
console.log('phone core ok');
