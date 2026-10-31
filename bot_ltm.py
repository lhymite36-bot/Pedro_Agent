"""Per-bot long-term memory: local JSON + hashed embeddings (no paid APIs).

When a Gemini key is present, facts are also embedded with the free
text-embedding-004 model. Otherwise a local bag-of-ngrams vector is used.
Top 5 facts are prepended to each reply. Secrets are refused.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any

DIM = 128
MAX_FACTS = 400
_SECRET = re.compile(r"(password|api[_ ]?key|token|secret|otp|cvv|pin)\s*[:=]", re.I)
_lock = threading.Lock()
embed_override = None  # tests: fn(text) -> list[float]


def _dir() -> Path:
    import agent_config
    p = agent_config.storage_dir() / "pro190" / "memory"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _bot_id(raw: str) -> str:
    text = re.sub(r"[^a-z0-9_-]+", "-", str(raw or "default").casefold())[:60].strip("-")
    return text or "default"


def _file(bot: str) -> Path:
    return _dir() / f"{_bot_id(bot)}.json"


def _load(bot: str) -> list[dict[str, Any]]:
    try:
        data = json.loads(_file(bot).read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _save(bot: str, rows: list[dict[str, Any]]) -> None:
    path = _file(bot)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def local_embed(text: str) -> list[float]:
    vec = [0.0] * DIM
    toks = re.findall(r"[a-z0-9']+", (text or "").casefold())
    grams = toks + ["".join(toks[i:i + 2]) for i in range(len(toks) - 1)]
    for g in grams:
        h = int(hashlib.sha256(g.encode()).hexdigest(), 16)
        vec[h % DIM] += 1.0
        vec[(h >> 8) % DIM] += 0.5
    n = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / n for v in vec]


def embed(text: str) -> list[float]:
    if embed_override is not None:
        return list(embed_override(text))
    key = __import__("os").environ.get("GEMINI_API_KEY", "").strip()
    if key:
        try:
            from google import genai
            client = genai.Client(api_key=key)
            res = client.models.embed_content(model="text-embedding-004", contents=text[:2000])
            values = getattr(getattr(res, "embeddings", [None])[0], "values", None) or getattr(res, "embedding", None)
            if values:
                return [float(v) for v in values]
        except Exception:
            pass
    return local_embed(text)


def _cos(a: list[float], b: list[float]) -> float:
    n = min(len(a), len(b))
    if n <= 0:
        return 0.0
    return sum(a[i] * b[i] for i in range(n))


def add(bot: str, text: str, source: str = "user") -> dict[str, Any]:
    text = " ".join((text or "").split())
    if not text:
        return {"ok": False, "error": "A fact is required."}
    if _SECRET.search(text):
        return {"ok": False, "error": "That looks like a password or key, so it was not saved."}
    text = text[:500]
    row = {
        "id": uuid.uuid4().hex[:10],
        "text": text,
        "source": str(source or "user")[:40],
        "at": time.time(),
        "vec": embed(text),
    }
    with _lock:
        rows = _load(bot)
        for old in rows:
            if old.get("text") == text:
                return {"ok": True, "item": old, "message": "Already saved."}
        rows.append(row)
        if len(rows) > MAX_FACTS:
            rows = rows[-MAX_FACTS:]
        _save(bot, rows)
    return {"ok": True, "item": {k: row[k] for k in ("id", "text", "source", "at")}, "message": "Saved."}


def search(bot: str, query: str, k: int = 5) -> dict[str, Any]:
    qv = embed(query or "") if (query or "").strip() else None
    with _lock:
        rows = _load(bot)
    scored = []
    for row in rows:
        if qv is None:
            score = float(row.get("at") or 0)
        else:
            score = _cos(qv, list(row.get("vec") or []))
        scored.append((score, row))
    scored.sort(key=lambda p: p[0], reverse=True)
    facts = [{"id": r["id"], "text": r["text"], "source": r.get("source", ""), "at": r.get("at", 0), "score": round(s, 4)}
             for s, r in scored[: max(1, min(20, k))]]
    return {"ok": True, "facts": facts, "bot": _bot_id(bot)}


def listing(bot: str) -> dict[str, Any]:
    with _lock:
        rows = _load(bot)
    items = [{"id": r["id"], "text": r["text"], "source": r.get("source", ""), "at": r.get("at", 0)} for r in rows]
    items.sort(key=lambda r: -float(r.get("at") or 0))
    return {"ok": True, "items": items, "bot": _bot_id(bot), "count": len(items)}


def edit(bot: str, item_id: str, text: str) -> dict[str, Any]:
    text = " ".join((text or "").split())[:500]
    if not text:
        return {"ok": False, "error": "New text is required."}
    if _SECRET.search(text):
        return {"ok": False, "error": "That looks like a password or key, so it was not saved."}
    with _lock:
        rows = _load(bot)
        found = None
        for row in rows:
            if row.get("id") == item_id:
                row["text"] = text
                row["vec"] = embed(text)
                row["at"] = time.time()
                found = row
                break
        if not found:
            return {"ok": False, "error": "That memory is gone."}
        _save(bot, rows)
    return {"ok": True, "item": {"id": found["id"], "text": found["text"]}}


def delete(bot: str, item_id: str, confirm: bool = False) -> dict[str, Any]:
    if not confirm:
        return {"ok": False, "error": "Tap delete again to confirm."}
    with _lock:
        rows = _load(bot)
        keep = [r for r in rows if r.get("id") != item_id]
        if len(keep) == len(rows):
            return {"ok": False, "error": "That memory is gone."}
        _save(bot, keep)
    return {"ok": True, "deleted": item_id}


def export(bot: str) -> dict[str, Any]:
    data = listing(bot)
    text = "\n".join(f"- {i['text']}" for i in data["items"]) or "(empty)"
    path = _dir() / f"{_bot_id(bot)}-export.txt"
    path.write_text(text, encoding="utf-8")
    return {"ok": True, "file": str(path), "count": data["count"], "text": text}


def prompt_facts(bot: str = "", query: str = "") -> str:
    try:
        import pro190
        if not pro190.flag("memory"):
            return ""
    except Exception:
        return ""
    if not bot:
        try:
            import bots
            cur = bots.current_bot() or {}
            bot = str(cur.get("id") or cur.get("name") or "default")
        except Exception:
            bot = "default"
    r = search(bot, query or "preferences identity paths instructions", k=5)
    facts = r.get("facts") or []
    if not facts:
        return ""
    lines = ["Long-term memory for this bot (top matches):"]
    for f in facts:
        lines.append(f"- {f['text']}")
    return "\n".join(lines)


def ingest(bot: str, text: str) -> None:
    """Pull lasting facts out of a user line without a model when possible."""
    t = " ".join((text or "").split())
    if len(t) < 8 or len(t) > 240:
        return
    if not re.search(r"\b(my name is|i am|i'm|i prefer|i live|always|never call me|remember that)\b", t, re.I):
        return
    try:
        add(bot, t, source="chat")
    except Exception:
        pass


def handle(action: str, data: dict[str, Any]) -> dict[str, Any]:
    bot = str(data.get("bot") or data.get("bot_id") or "default")
    if action in ("", "list"):
        return listing(bot)
    if action == "add":
        return add(bot, str(data.get("text") or data.get("fact") or ""))
    if action == "search":
        return search(bot, str(data.get("query") or data.get("text") or ""), int(data.get("k") or 5))
    if action == "edit":
        return edit(bot, str(data.get("id") or ""), str(data.get("text") or ""))
    if action == "delete":
        return delete(bot, str(data.get("id") or ""), bool(data.get("confirm")))
    if action == "export":
        return export(bot)
    return {"ok": False, "error": "Unknown memory action."}
