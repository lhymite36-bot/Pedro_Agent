// Tiny, safe markdown renderer (no dependencies, no CDN). Escapes all HTML
// first, then adds: fenced code, inline code, bold, italic, headings, lists,
// blockquotes, links (http/https only) and paragraphs.
(function (root) {
  function esc(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }
  function inline(s) {
    const codes = [];
    s = s.replace(/`([^`\n]+)`/g, (_, c) => { codes.push(c); return '\u0000' + (codes.length - 1) + '\u0000'; });
    s = esc(s);
    s = s.replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>')
      .replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<em>$2</em>')
      .replace(/(^|[^_])_([^_\n]+)_(?=$|[^_])/g, '$1<em>$2</em>')
      .replace(/\[([^\]\n]+)\]\((https?:\/\/[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>')
      .replace(/(^|[\s(])(https?:\/\/[^\s<)]+)/g, '$1<a href="$2" target="_blank" rel="noopener">$2</a>');
    return s.replace(/\u0000(\d+)\u0000/g, (_, i) => '<code>' + esc(codes[+i]) + '</code>');
  }
  function render(src) {
    const lines = String(src || '').replace(/\r\n/g, '\n').split('\n');
    const out = []; let i = 0;
    while (i < lines.length) {
      const line = lines[i];
      const fence = line.match(/^```\s*([\w+-]*)\s*$/);
      if (fence) {
        const body = []; i++;
        while (i < lines.length && !/^```\s*$/.test(lines[i])) body.push(lines[i++]);
        i++;
        out.push('<div class="code"><div class="code-head"><span>' + esc(fence[1] || 'code') +
          '</span><button class="copy" type="button">Copy</button></div><pre><code>' + esc(body.join('\n')) + '</code></pre></div>');
        continue;
      }
      const h = line.match(/^(#{1,4})\s+(.*)$/);
      if (h) { out.push('<h' + (h[1].length + 2) + '>' + inline(h[2]) + '</h' + (h[1].length + 2) + '>'); i++; continue; }
      if (/^\s*([-*+]|\d+\.)\s+/.test(line)) {
        const ordered = /^\s*\d+\./.test(line); const items = [];
        while (i < lines.length && /^\s*([-*+]|\d+\.)\s+/.test(lines[i])) items.push('<li>' + inline(lines[i++].replace(/^\s*([-*+]|\d+\.)\s+/, '')) + '</li>');
        out.push((ordered ? '<ol>' : '<ul>') + items.join('') + (ordered ? '</ol>' : '</ul>'));
        continue;
      }
      if (/^>\s?/.test(line)) {
        const q = [];
        while (i < lines.length && /^>\s?/.test(lines[i])) q.push(inline(lines[i++].replace(/^>\s?/, '')));
        out.push('<blockquote>' + q.join('<br>') + '</blockquote>');
        continue;
      }
      if (!line.trim()) { i++; continue; }
      const para = [];
      while (i < lines.length && lines[i].trim() && !/^```|^#{1,4}\s|^\s*([-*+]|\d+\.)\s|^>/.test(lines[i])) para.push(inline(lines[i++]));
      out.push('<p>' + para.join('<br>') + '</p>');
    }
    return out.join('');
  }
  const api = { render, escape: esc };
  if (typeof module !== 'undefined' && module.exports) module.exports = api; else root.Markdown = api;
})(this);
