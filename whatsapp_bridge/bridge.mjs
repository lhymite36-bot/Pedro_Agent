// Ped Bot WhatsApp bridge (1.6.1). Baileys (WhatsApp Web protocol, no Chromium).
// Talks JSON lines with Ped Bot over stdin/stdout: {"id","cmd","args"} -> {"id","ok","result"|"error"}.
// Events: {"event":"qr"|"status"|"message", ...}. Logs go to stderr. Session lives in --auth <dir> (never in git).
import fs from 'node:fs';
import path from 'node:path';
import readline from 'node:readline';
import pino from 'pino';
import makeWASocket, {
  useMultiFileAuthState, DisconnectReason, Browsers, downloadMediaMessage, jidNormalizedUser, isJidGroup, fetchLatestBaileysVersion,
} from 'baileys';

const args = process.argv.slice(2);
const opt = (k, d) => { const i = args.indexOf(k); return i >= 0 ? args[i + 1] : d; };
const AUTH = path.resolve(opt('--auth', './wa_session'));
const MEDIA = path.resolve(opt('--media', path.join(AUTH, '..', 'wa_media')));
const STORE = path.join(AUTH, 'store.json');
fs.mkdirSync(AUTH, { recursive: true }); fs.mkdirSync(MEDIA, { recursive: true });
const log = pino({ level: 'warn' }, pino.destination(2));

const out = (o) => process.stdout.write(JSON.stringify(o) + '\n');
let sock = null, state = 'starting', me = null, stopping = false, retry = 0;
const sentIds = new Set();
// small local store: chats, contacts, last messages per chat
let store = { chats: {}, contacts: {}, msgs: {} };
try { store = { ...store, ...JSON.parse(fs.readFileSync(STORE, 'utf8')) }; } catch {}
let dirty = false;
setInterval(() => { if (dirty) { dirty = false; try { fs.writeFileSync(STORE, JSON.stringify(store)); } catch {} } }, 5000).unref();

const MAX_PER_CHAT = 200;
function textOf(m) {
  const x = m.message || {};
  const inner = x.ephemeralMessage?.message || x.viewOnceMessage?.message || x;
  return inner.conversation || inner.extendedTextMessage?.text || inner.imageMessage?.caption || inner.videoMessage?.caption
    || inner.documentMessage?.caption || inner.documentMessage?.fileName || (inner.reactionMessage ? `[reacted ${inner.reactionMessage.text}]` : '') || '';
}
function kindOf(m) {
  const x = m.message || {};
  const inner = x.ephemeralMessage?.message || x.viewOnceMessage?.message || x;
  if (inner.audioMessage) return inner.audioMessage.ptt ? 'voice' : 'audio';
  for (const k of ['image', 'video', 'document', 'sticker', 'location', 'contact', 'reaction']) if (inner[k + 'Message']) return k;
  return 'text';
}
function remember(m) {
  const chat = jidNormalizedUser(m.key.remoteJid || '');
  if (!chat || chat === 'status@broadcast') return null;
  const row = { id: m.key.id, chat, from_me: !!m.key.fromMe, sender: m.key.participant || (m.key.fromMe ? 'me' : chat),
    name: m.pushName || '', text: textOf(m), kind: kindOf(m), ts: Number(m.messageTimestamp || Date.now() / 1000) };
  const list = store.msgs[chat] || (store.msgs[chat] = []);
  if (!list.some((r) => r.id === row.id)) { list.push(row); if (list.length > MAX_PER_CHAT) list.splice(0, list.length - MAX_PER_CHAT); }
  const c = store.chats[chat] || (store.chats[chat] = { id: chat, name: '' });
  c.last = Math.max(c.last || 0, row.ts); c.preview = row.text.slice(0, 80);
  if (!row.from_me && m.pushName && !isJidGroup(chat) && !c.name) c.name = m.pushName;
  if (!row.from_me && m.pushName) { const s = jidNormalizedUser(row.sender); store.contacts[s] = { ...(store.contacts[s] || { id: s }), notify: m.pushName }; }
  dirty = true; return row;
}
const rawMsgs = new Map();   // id -> raw message (for react/reply/download), recent only
function keepRaw(m) { rawMsgs.set(m.key.id, m); if (rawMsgs.size > 3000) rawMsgs.delete(rawMsgs.keys().next().value); }

const selfJids = () => [me?.id, me?.lid].filter(Boolean).map(jidNormalizedUser);
function nameOf(jid) {
  const c = store.contacts[jid] || {}; const ch = store.chats[jid] || {};
  return c.name || ch.name || c.notify || c.verifiedName || jid.split('@')[0];
}

async function start() {
  const { state: auth, saveCreds } = await useMultiFileAuthState(AUTH);
  let version; try { version = (await fetchLatestBaileysVersion()).version; } catch {}
  sock = makeWASocket({ auth, logger: log, browser: Browsers.windows('Ped Bot'), markOnlineOnConnect: false,
    syncFullHistory: false, ...(version ? { version } : {}) });
  sock.ev.on('creds.update', saveCreds);
  sock.ev.on('connection.update', (u) => {
    if (u.qr) { state = 'qr'; out({ event: 'qr', qr: u.qr }); }
    if (u.connection === 'open') {
      state = 'connected'; retry = 0; me = sock.user;
      out({ event: 'status', state, me: { id: me?.id, name: me?.name || '' } });
    }
    if (u.connection === 'close') {
      const code = u.lastDisconnect?.error?.output?.statusCode;
      const loggedOut = code === DisconnectReason.loggedOut;
      state = loggedOut ? 'logged_out' : 'reconnecting';
      out({ event: 'status', state, code });
      if (loggedOut) { try { fs.rmSync(AUTH, { recursive: true, force: true }); fs.mkdirSync(AUTH, { recursive: true }); } catch {} }
      if (!stopping) { const wait = Math.min(60000, 2000 * 2 ** Math.min(retry++, 5)); setTimeout(() => start().catch(fail), loggedOut ? 1500 : wait); }
    }
  });
  sock.ev.on('messaging-history.set', ({ chats, contacts, messages }) => {
    for (const c of chats || []) { const id = jidNormalizedUser(c.id); store.chats[id] = { ...(store.chats[id] || {}), id, name: c.name || store.chats[id]?.name || '' }; }
    for (const c of contacts || []) { const id = jidNormalizedUser(c.id); store.contacts[id] = { ...(store.contacts[id] || {}), ...c, id }; }
    for (const m of messages || []) { remember(m); keepRaw(m); }
    dirty = true;
  });
  sock.ev.on('contacts.upsert', (cs) => { for (const c of cs) { const id = jidNormalizedUser(c.id); store.contacts[id] = { ...(store.contacts[id] || {}), ...c, id }; } dirty = true; });
  sock.ev.on('contacts.update', (cs) => { for (const c of cs) { const id = jidNormalizedUser(c.id); store.contacts[id] = { ...(store.contacts[id] || { id }), ...c, id }; } dirty = true; });
  sock.ev.on('chats.upsert', (cs) => { for (const c of cs) { const id = jidNormalizedUser(c.id); store.chats[id] = { ...(store.chats[id] || {}), id, name: c.name || '' }; } dirty = true; });
  sock.ev.on('groups.upsert', (gs) => { for (const g of gs) { const id = jidNormalizedUser(g.id); store.chats[id] = { ...(store.chats[id] || {}), id, name: g.subject || '' }; } dirty = true; });
  sock.ev.on('messages.upsert', async ({ messages, type }) => {
    for (const m of messages) {
      keepRaw(m); const row = remember(m);
      if (!row || type !== 'notify') continue;
      if (sentIds.has(m.key.id)) continue;   // our own reply: never answer ourselves
      const self = selfJids().includes(row.chat);
      const ev = { event: 'message', ...row, self_chat: self, chat_name: nameOf(row.chat), sender_name: row.name || nameOf(jidNormalizedUser(row.sender)) };
      if (row.kind === 'voice' || row.kind === 'audio') {
        try { const buf = await downloadMediaMessage(m, 'buffer', {}); const f = path.join(MEDIA, `${m.key.id}.ogg`); fs.writeFileSync(f, buf); ev.media_path = f; } catch (e) { ev.media_error = String(e.message || e); }
      }
      out(ev);
    }
  });
}
function fail(e) { log.error(e); out({ event: 'status', state: 'error', error: String(e?.message || e) }); }

// ---- commands ----
function digits(s) { return String(s || '').replace(/[^0-9]/g, ''); }
function resolve(to) {
  const t = String(to || '').trim();
  if (!t) throw new Error('No recipient given.');
  if (/^(me|myself|self|message yourself)$/i.test(t)) { const s = selfJids()[0]; if (!s) throw new Error('Not connected.'); return s; }
  if (t.includes('@')) return jidNormalizedUser(t);
  const d = digits(t);
  if (d.length >= 8 && d.length === t.replace(/[\s+()-]/g, '').length) return `${d}@s.whatsapp.net`;
  const hits = search(t, 8);
  const exact = hits.filter((h) => h.name.toLowerCase() === t.toLowerCase());
  if (exact.length === 1) return exact[0].id;
  if (hits.length === 1) return hits[0].id;
  if (!hits.length) throw new Error(`No WhatsApp contact or group matches "${t}". Give the number with country code.`);
  throw new Error(`"${t}" matches several chats: ${hits.map((h) => `${h.name} (${h.id})`).join('; ')}. Say which one.`);
}
function search(q, limit = 20) {
  const s = String(q || '').toLowerCase().trim(); const seen = new Map();
  const add = (id, name) => { if (!id || id === 'status@broadcast' || seen.has(id)) return; seen.set(id, { id, name: name || id.split('@')[0], group: isJidGroup(id) }); };
  for (const c of Object.values(store.contacts)) { const n = c.name || c.notify || c.verifiedName || ''; if (!s || n.toLowerCase().includes(s) || c.id.includes(digits(s) || '\u0000')) add(c.id, n); }
  for (const c of Object.values(store.chats)) { const n = c.name || nameOf(c.id); if (!s || n.toLowerCase().includes(s) || c.id.includes(digits(s) || '\u0000')) add(c.id, n); }
  return [...seen.values()].slice(0, limit);
}
function need() { if (!sock || state !== 'connected') throw new Error('WhatsApp is not connected. Open Settings > Connections > Connect WhatsApp.'); }
async function sent(p) { const r = await p; if (r?.key?.id) sentIds.add(r.key.id); if (r) { remember(r); keepRaw(r); } return { id: r?.key?.id, chat: r?.key?.remoteJid }; }
function quoted(chat, id) { if (!id) return undefined; const m = rawMsgs.get(id); if (!m) throw new Error('That message is not in recent memory, so I cannot reply to it.'); return m; }

const MIME = { '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png', '.webp': 'image/webp', '.gif': 'image/gif', '.mp4': 'video/mp4',
  '.mov': 'video/quicktime', '.mp3': 'audio/mpeg', '.ogg': 'audio/ogg; codecs=opus', '.opus': 'audio/ogg; codecs=opus', '.m4a': 'audio/mp4', '.wav': 'audio/wav',
  '.pdf': 'application/pdf', '.txt': 'text/plain', '.zip': 'application/zip', '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', '.pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation' };

const handlers = {
  status: async () => ({ state, me: me ? { id: me.id, name: me.name || '' } : null, chats: Object.keys(store.chats).length }),
  logout: async () => { stopping = true; try { await sock?.logout(); } catch {} try { fs.rmSync(AUTH, { recursive: true, force: true }); } catch {} state = 'logged_out'; out({ event: 'status', state }); setTimeout(() => process.exit(0), 300); return { ok: true }; },
  resolve: async (a) => { const id = resolve(a.to); return { id, name: nameOf(id), group: !!isJidGroup(id) }; },
  send_text: async (a) => { need(); const to = resolve(a.to); return sent(sock.sendMessage(to, { text: String(a.text || '') }, { quoted: quoted(to, a.reply_to) })); },
  send_file: async (a) => {
    need(); const to = resolve(a.to); const f = path.resolve(String(a.path || ''));
    if (!fs.existsSync(f)) throw new Error(`File not found: ${f}`);
    const ext = path.extname(f).toLowerCase(); const mimetype = MIME[ext] || 'application/octet-stream';
    let kind = a.kind || 'auto';
    if (kind === 'auto') kind = /^image\//.test(mimetype) && ext !== '.gif' ? 'image' : /^video\//.test(mimetype) ? 'video' : /^audio\//.test(mimetype) ? 'audio' : 'document';
    const buf = fs.readFileSync(f); const caption = a.caption ? String(a.caption) : undefined;
    const content = kind === 'image' ? { image: buf, caption } : kind === 'video' ? { video: buf, caption }
      : kind === 'voice' ? { audio: buf, mimetype: 'audio/ogg; codecs=opus', ptt: true } : kind === 'audio' ? { audio: buf, mimetype }
      : { document: buf, mimetype, fileName: path.basename(f), caption };
    return sent(sock.sendMessage(to, content, { quoted: quoted(to, a.reply_to) }));
  },
  react: async (a) => { need(); const chat = resolve(a.chat); const m = rawMsgs.get(a.msg_id); if (!m) throw new Error('Message not found in recent memory.');
    return sent(sock.sendMessage(chat, { react: { text: String(a.emoji ?? '👍'), key: m.key } })); },
  mark_read: async (a) => { need(); const chat = resolve(a.chat); const rows = (store.msgs[chat] || []).filter((r) => !r.from_me).slice(-(a.limit || 20));
    const keys = rows.map((r) => rawMsgs.get(r.id)?.key).filter(Boolean); if (keys.length) await sock.readMessages(keys); return { marked: keys.length }; },
  list_chats: async (a) => ({ chats: Object.values(store.chats).filter((c) => c.id !== 'status@broadcast').sort((x, y) => (y.last || 0) - (x.last || 0)).slice(0, a.limit || 20)
    .map((c) => ({ id: c.id, name: nameOf(c.id), group: !!isJidGroup(c.id), last: c.last || 0, preview: c.preview || '' })) }),
  read_chat: async (a) => { const chat = resolve(a.chat); const rows = (store.msgs[chat] || []).slice(-(a.limit || 30));
    return { chat, name: nameOf(chat), messages: rows.map((r) => ({ ...r, sender_name: r.from_me ? 'me' : (r.name || nameOf(jidNormalizedUser(r.sender))) })) }; },
  search_contacts: async (a) => ({ results: search(a.query, a.limit || 20) }),
  create_group: async (a) => { need(); const ps = (a.participants || []).map(resolve); const g = await sock.groupCreate(String(a.name || 'New group'), ps);
    store.chats[g.id] = { id: g.id, name: g.subject }; dirty = true; return { id: g.id, name: g.subject, participants: ps.length }; },
  group_info: async (a) => { need(); const chat = resolve(a.chat); const g = await sock.groupMetadata(chat);
    return { id: g.id, name: g.subject, description: g.desc || '', participants: g.participants.map((p) => ({ id: p.id, admin: p.admin || null, name: nameOf(jidNormalizedUser(p.id)) })) }; },
  download_media: async (a) => { need(); const m = rawMsgs.get(a.msg_id); if (!m) throw new Error('Message not found in recent memory.');
    const buf = await downloadMediaMessage(m, 'buffer', {}); const k = kindOf(m);
    const ext = { image: '.jpg', video: '.mp4', voice: '.ogg', audio: '.ogg', sticker: '.webp' }[k] || '.bin';
    const f = path.join(MEDIA, `${a.msg_id}${ext}`); fs.writeFileSync(f, buf); return { path: f, kind: k }; },
};

readline.createInterface({ input: process.stdin }).on('line', async (line) => {
  let req; try { req = JSON.parse(line); } catch { return; }
  const h = handlers[req.cmd];
  if (!h) return out({ id: req.id, ok: false, error: `unknown command ${req.cmd}` });
  try { out({ id: req.id, ok: true, result: await h(req.args || {}) }); }
  catch (e) { out({ id: req.id, ok: false, error: String(e?.message || e) }); }
}).on('close', () => { stopping = true; try { fs.writeFileSync(STORE, JSON.stringify(store)); } catch {} process.exit(0); });

if (process.env.PEDBOT_WA_NO_CONNECT !== '1') start().catch(fail); else { state = 'offline-test'; out({ event: 'status', state }); }
export { resolve, search, store, handlers };
