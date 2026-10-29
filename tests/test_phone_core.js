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

assert.deepStrictEqual(C.modelsFor(bot), C.DEFAULT_MODELS);   // 1.6.0: 2.5 is closed to new keys, skipped
assert.deepStrictEqual(C.modelsFor({ model: 'groq:llama' }), C.DEFAULT_MODELS);
assert.deepStrictEqual(C.modelsFor({ model: 'gemini-2.0-flash' }), C.DEFAULT_MODELS);   // shut down, skipped
assert.ok(C.DEFAULT_MODELS.every((m) => !/^gemini-(1\.|2\.)/.test(m)));
const listed = { models: ['gemini-3.8-flash', 'gemini-3.5-flash-lite', 'gemini-3.8-flash-tts', 'gemini-3.1-flash-lite', 'gemini-3.8-live', 'gemini-flash-latest', 'gemini-embedding-001']
  .map((n) => ({ name: 'models/' + n, supportedGenerationMethods: /embedding/.test(n) ? ['embedContent'] : ['generateContent'] })) };
assert.deepStrictEqual(C.pickModels(JSON.stringify(listed)), ['gemini-3.8-flash', 'gemini-3.5-flash-lite', 'gemini-3.1-flash-lite', 'gemini-flash-latest']);
assert.deepStrictEqual(C.orderFor(C.modelsFor({}, C.pickModels(listed)), 'hi', 5)[0], 'gemini-3.5-flash-lite');
assert.ok(C.replyText(404, '{"error":{"message":"not found"}}').retry);

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

// 1.5.13: phone mode runs the PC web UI with a shim that answers /api on the phone.
const fs = require('fs');
const shim = fs.readFileSync(__dirname + '/../android_app/phone_web/phone_shim.js', 'utf8');
assert.ok(shim.includes("'/api/chat'") && shim.includes("'/api/bots'") && shim.includes('geminiModels') && shim.includes('Phone mode, PC offline'));
assert.ok(!/AIza[0-9A-Za-z_-]{20,}/.test(shim));
assert.ok(fs.readFileSync(__dirname + '/../android_app/build.sh', 'utf8').includes('app_static'));
const java = fs.readFileSync(__dirname + '/../android_app/src/com/pedro/agent/MainActivity.java', 'utf8');
assert.ok(java.includes('pcOnline(url)') && java.includes('showPhoneMode') && java.includes('phoneAsset'));
assert.ok(fs.readFileSync(__dirname + '/../android_app/src/com/pedro/agent/SecureStore.java', 'utf8').includes('AndroidKeyStore'));
console.log('phone core ok');

// 1.6.0 smart mode
assert.strictEqual(C.DEFAULT_MODELS[0], 'gemini-3.6-flash');
assert.ok(C.isHard('build me a study planner app with reminders') && !C.isHard('hi'));
assert.strictEqual(C.orderFor(C.DEFAULT_MODELS, 'plan my week of exam study step by step', 5)[0], 'gemini-3.8-flash');
assert.strictEqual(C.orderFor(C.DEFAULT_MODELS, 'hi', 5)[0], 'gemini-3.6-flash');
assert.ok(C.orderFor(C.DEFAULT_MODELS, 'plan my week of exam study step by step', 0).indexOf('gemini-3.8-flash') < 0);
const tb = C.geminiBody(bot, [{ role: 'user', text: 'x' }], 80, 'high');
assert.strictEqual(tb.generationConfig.thinkingConfig.thinkingLevel, 'high');
assert.ok(!C.geminiBody(bot, [{ role: 'user', text: 'x' }]).generationConfig.thinkingConfig);
assert.ok(C.replyText(400, JSON.stringify({ error: { message: 'Thinking level is not supported for this model.' } })).noThinking);
console.log('phone smart ok');
