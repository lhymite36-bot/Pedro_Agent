// Pure helpers for the group @mention picker (tested with node: tests/test_mentions.js).
(function (root) {
  // The "@word" being typed right before the caret, or null.
  function mentionQuery(text, caret) {
    const before = String(text || '').slice(0, caret == null ? (text || '').length : caret);
    const m = /(^|\s)@([A-Za-z0-9_\-]*)$/.exec(before);
    return m ? { start: before.length - m[2].length - 1, query: m[2] } : null;
  }
  function filterMembers(members, query) {
    const q = String(query || '').toLowerCase();
    const scored = members.map((m) => {
      const n = m.name.toLowerCase(), id = m.id.toLowerCase();
      const s = !q ? 1 : (n.startsWith(q) || id.startsWith(q)) ? 3 : (n.includes(q) || id.includes(q)) ? 2 : 0;
      return { m, s };
    }).filter((x) => x.s > 0);
    return scored.sort((a, b) => b.s - a.s).map((x) => x.m);
  }
  // Replace the typed "@que" (or insert at caret) with "@id ".
  function applyMention(text, start, caret, id) {
    text = String(text || ''); if (caret == null) caret = text.length; if (start == null || start < 0) start = caret;
    const pre = text.slice(0, start), post = text.slice(caret);
    const lead = pre && !/\s$/.test(pre) ? ' ' : '';
    const ins = lead + '@' + id + ' ';
    return { text: pre + ins + post.replace(/^\s+/, ''), caret: (pre + ins).length };
  }
  function roster(group, bots, main) {
    const out = [{ id: 'all', name: 'Everyone (@all)', color: '#8e8ea0', avatar: 'round', all: true },
      { id: 'pedro', name: (main && main.name) || 'Pedro_Agent', color: (main && main.color) || '#5b6cff', avatar: 'round' }];
    (group.members || []).forEach((id) => { const b = (bots || []).find((x) => x.id === id); if (b) out.push({ id: b.id, name: b.name, color: b.color, avatar: b.avatar }); });
    return out;
  }
  const api = { mentionQuery, filterMembers, applyMention, roster };
  if (typeof module !== 'undefined') module.exports = api; else root.MentionPick = api;
})(this);
