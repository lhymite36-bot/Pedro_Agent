const assert = require('assert');
const M = require('../app_static/mention_pick.js');
assert.deepStrictEqual(M.mentionQuery('hi @wri', 7), { start: 3, query: 'wri' });
assert.deepStrictEqual(M.mentionQuery('@', 1), { start: 0, query: '' });
assert.strictEqual(M.mentionQuery('mail a@b', 8), null);          // emails are not mentions
assert.strictEqual(M.mentionQuery('hi @wri there', 13), null);
const r = M.roster({ members: ['writer', 'gone'] }, [{ id: 'writer', name: 'Writer', color: '#f00', avatar: 'cat' }], null);
assert.deepStrictEqual(r.map((x) => x.id), ['all', 'pedro', 'writer']);
assert.deepStrictEqual(M.filterMembers(r, 'wr').map((x) => x.id), ['writer']);
assert.deepStrictEqual(M.filterMembers(r, 'ped').map((x) => x.id), ['pedro']);
assert.strictEqual(M.filterMembers(r, '').length, 3);
assert.strictEqual(M.filterMembers(r, 'zzz').length, 0);
let a = M.applyMention('hi @wri now', 3, 7, 'writer');
assert.deepStrictEqual(a, { text: 'hi @writer now', caret: 11 });
a = M.applyMention('please do', null, 9, 'writer');                 // "+" button: insert at caret
assert.deepStrictEqual(a, { text: 'please do @writer ', caret: 18 });
assert.strictEqual(M.quoteReply('Bunny', 'The sky is blue', 'Why?'), 'Replying to Bunny: "The sky is blue"\n\nWhy?');
assert.strictEqual(M.quoteReply('Bunny', '', 'Why?'), 'Why?');
const chats = M.replyChats('bot-bunny', 'bunny', [{ id: 'bunny', name: 'bunny' }, { id: 'fay', name: 'fay' }], [{ id: 'g1', name: 'Study' }], [{ session: 'bot-fay', title: 'ignore' }, { session: 'c1', title: 'Wingz notes' }]);
assert.deepStrictEqual(chats.map((c) => c.id), ['bot-bunny', 'bot-fay', 'group-g1', 'c1']);
assert.strictEqual(chats[0].name, 'bunny');
assert.strictEqual(chats[3].name, 'Wingz notes');
console.log('mention picker: all tests passed');
