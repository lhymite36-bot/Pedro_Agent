"""Blender expert knowledge: the official Manual + Python API reference, searchable offline.

On first use (not bundled in the release) it downloads the HTML docs from
docs.blender.org that match the installed Blender version, indexes the text with
SQLite FTS5, and deletes the zip. blender_docs_search then answers in milliseconds.
Expert workflow guides (data/blender_guides/*.md) are indexed with them.
"""

from __future__ import annotations

import html
import re
import sqlite3
import subprocess
import threading
import time
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Callable

MANUAL = "https://docs.blender.org/manual/en/{v}/blender_manual_html.zip"
API = "https://docs.blender.org/api/{v}/blender_python_reference_{u}.zip"
GUIDES = Path(__file__).resolve().parent / "blender_guides"
DEFAULT_VERSION = "4.2"
fetch: Callable[[str, Path], None] | None = None    # tests replace this
version_override: str | None = None
_lock = threading.Lock()


def folder() -> Path:
    import agent_config

    return agent_config.storage_dir() / "blender_docs"


def installed_version() -> str:
    if version_override:
        return version_override
    try:
        import blender_task

        exe = blender_task.find_blender()
    except Exception:
        exe = None
    if exe:
        m = re.search(r"Blender\s+(\d+\.\d+)", str(exe))
        if m:
            return m.group(1)
        try:
            out = subprocess.run([str(exe), "--version"], capture_output=True, text=True, timeout=30,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
            m = re.search(r"Blender\s+(\d+\.\d+)", out)
            if m:
                return m.group(1)
        except (OSError, subprocess.SubprocessError):
            pass
    return DEFAULT_VERSION


def db_path(version: str) -> Path:
    return folder() / f"blender_{version}.sqlite"


def _download(url: str, dest: Path) -> None:
    if fetch is not None:
        fetch(url, dest)
        return
    req = urllib.request.Request(url, headers={"User-Agent": "PedBot-docs"})
    with urllib.request.urlopen(req, timeout=120) as r, open(dest, "wb") as f:
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)


_TAG = re.compile(r"<(script|style|nav|header|footer)[^>]*>.*?</\1>", re.S | re.I)
_ANY = re.compile(r"<[^>]+>")


def page_text(raw: str) -> tuple[str, str]:
    title = re.search(r"<title>(.*?)</title>", raw, re.S | re.I)
    main = re.search(r'<div[^>]+(?:role="main"|itemprop="articleBody")[^>]*>(.*)', raw, re.S | re.I)
    body = main.group(1) if main else raw
    body = _TAG.sub(" ", body)
    body = re.sub(r"</(p|div|h\d|li|tr|pre|dt|dd)>", "\n", body, flags=re.I)
    text = html.unescape(_ANY.sub(" ", body))
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text).strip()
    t = html.unescape(_ANY.sub("", title.group(1))).strip() if title else ""
    return re.sub(r"\s+[—-]\s+Blender.*$", "", t), text


def _open(version: str) -> sqlite3.Connection:
    p = db_path(version)
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(p))
    con.execute("CREATE VIRTUAL TABLE IF NOT EXISTS docs USING fts5(source, title, path, body, tokenize='porter')")
    con.execute("CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT)")
    return con


def _index_zip(con: sqlite3.Connection, zpath: Path, source: str) -> int:
    n = 0
    with zipfile.ZipFile(zpath) as z:
        for name in z.namelist():
            if not name.endswith(".html") or "/_static/" in name or name.endswith(("genindex.html", "search.html")):
                continue
            raw = z.read(name).decode("utf-8", "replace")
            title, body = page_text(raw)
            if len(body) < 40:
                continue
            con.execute("INSERT INTO docs VALUES (?,?,?,?)", (source, title, name.split("/", 1)[-1], body[:200000]))
            n += 1
    return n


def _index_guides(con: sqlite3.Connection) -> int:
    con.execute("DELETE FROM docs WHERE source='guide'")
    n = 0
    for p in sorted(GUIDES.glob("*.md")):
        text = p.read_text(encoding="utf-8")
        title = text.splitlines()[0].lstrip("# ").strip() if text else p.stem
        con.execute("INSERT INTO docs VALUES ('guide',?,?,?)", (title, p.name, text))
        n += 1
    return n


def ensure(version: str | None = None, progress: Callable[[str], Any] | None = None) -> dict[str, Any]:
    version = version or installed_version()
    say = progress or (lambda m: None)
    with _lock:
        con = _open(version)
        try:
            have = dict(con.execute("SELECT k, v FROM meta").fetchall())
            if have.get("ready") != "1":
                started = time.time()
                for source, url in (("manual", MANUAL.format(v=version)),
                                    ("api", API.format(v=version, u=version.replace(".", "_")))):
                    if have.get(source) == "1":
                        continue
                    zpath = folder() / f"{source}_{version}.zip"
                    say(f"Downloading the Blender {version} {source} docs (one time)…")
                    _download(url, zpath)
                    say(f"Indexing the {source} docs…")
                    con.execute("DELETE FROM docs WHERE source=?", (source,))
                    count = _index_zip(con, zpath, source)
                    con.execute("INSERT OR REPLACE INTO meta VALUES (?, '1')", (source,))
                    con.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (source + "_pages", str(count)))
                    con.commit()
                    zpath.unlink(missing_ok=True)
                con.execute("INSERT OR REPLACE INTO meta VALUES ('ready','1')")
                con.execute("INSERT OR REPLACE INTO meta VALUES ('seconds', ?)", (f"{time.time() - started:.0f}",))
            _index_guides(con)
            con.commit()
            meta = dict(con.execute("SELECT k, v FROM meta").fetchall())
        finally:
            con.close()
    return {"ok": True, "version": version, "manual_pages": int(meta.get("manual_pages", 0)),
            "api_pages": int(meta.get("api_pages", 0))}


def _fts_query(q: str) -> str:
    words = re.findall(r"[A-Za-z0-9_.]{2,}", q)
    return " OR ".join('"' + w.replace('"', "") + '"' for w in words[:12])


def blender_docs_search(query: str, source: str = "", limit: int = 5) -> dict[str, Any]:
    """Search the official Blender Manual, Python API and expert guides for this Blender version."""
    if not str(query or "").strip():
        return {"ok": False, "error": "Say what to look up, e.g. 'bpy.ops.object.modifier_add bevel' or 'UV unwrap smart project'."}
    try:
        info = ensure()
    except Exception as exc:
        return {"ok": False, "error": f"Could not get the Blender docs: {exc}"}
    con = sqlite3.connect(str(db_path(info["version"])))
    try:
        sql = ("SELECT source, title, path, snippet(docs, 3, '[', ']', ' … ', 40), bm25(docs, 0, 5.0, 2.0, 1.0) AS r "
               "FROM docs WHERE docs MATCH ?")
        args: list[Any] = [_fts_query(query)]
        if source in {"manual", "api", "guide"}:
            sql += " AND source = ?"
            args.append(source)
        sql += " ORDER BY r LIMIT ?"
        args.append(max(1, min(20, int(limit))))
        rows = con.execute(sql, args).fetchall() if args[0] else []
    finally:
        con.close()
    hits = []
    for src, title, path, snip, _r in rows:
        base = (f"https://docs.blender.org/manual/en/{info['version']}/" if src == "manual"
                else f"https://docs.blender.org/api/{info['version']}/" if src == "api" else "guide:")
        hits.append({"source": src, "title": title, "url": base + path, "excerpt": snip})
    return {"ok": True, "version": info["version"], "results": hits,
            "message": f"{len(hits)} match(es) in the Blender {info['version']} docs."}


def blender_guide(topic: str) -> dict[str, Any]:
    """Return the full expert workflow guide for a topic (modelling, uv, rigging, …)."""
    t = re.sub(r"[^a-z]", "", str(topic or "").lower())
    for p in sorted(GUIDES.glob("*.md")):
        if t and (t in p.stem.replace("_", "") or p.stem.replace("_", "") in t):
            return {"ok": True, "topic": p.stem, "guide": p.read_text(encoding="utf-8")}
    return {"ok": False, "error": "No guide by that name.", "topics": [p.stem for p in sorted(GUIDES.glob("*.md"))]}


DECLARATIONS = [
    {"name": "blender_docs_search",
     "description": ("Search the official Blender Manual and Python API reference (matching the installed Blender) "
                     "plus expert workflow guides. Use before writing bpy code you are unsure of; cite what you used."),
     "parameters": {"type": "object", "properties": {
         "query": {"type": "string"}, "source": {"type": "string", "enum": ["", "manual", "api", "guide"]},
         "limit": {"type": "integer"}}, "required": ["query"]}},
    {"name": "blender_guide",
     "description": "Get the expert step-by-step workflow for a Blender topic (e.g. modelling, uv, rigging, geometry_nodes).",
     "parameters": {"type": "object", "properties": {"topic": {"type": "string"}}, "required": ["topic"]}},
]
TOOLS = {"blender_docs_search": blender_docs_search, "blender_guide": blender_guide}
