"""1.4.18: a small shared notebook for bots and tasks.

A task (or bot) writes a result under a short key; any other bot or task can read it. The task board
also files every finished task's answer here as "task:<id>" so a later step can pick it up.
Stored locally in storage/shared_memory.json. Never used for passwords or keys.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any

MAX_ITEMS = 200
MAX_TEXT = 6000
_lock = threading.Lock()
_SECRETISH = re.compile(r"(password|app[_ ]?password|api[_ ]?key|token|secret|otp|cvv|pin)\s*[:=]", re.I)


def _path() -> Path:
    import agent_config

    base = agent_config.storage_dir()
    base.mkdir(parents=True, exist_ok=True)
    return base / "shared_memory.json"


def _load() -> dict[str, Any]:
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(data: dict[str, Any]) -> None:
    tmp = _path().with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(_path())


def _key(key: str) -> str:
    return " ".join(str(key or "").split())[:80]


def put(key: str, text: str, by: str = "") -> dict[str, Any]:
    key = _key(key)
    text = str(text or "")
    if not key or not text.strip():
        return {"ok": False, "error": "A key and some text are required."}
    if _SECRETISH.search(text):
        return {"ok": False, "error": "That looks like a password or key, so it was not shared."}
    with _lock:
        data = _load()
        data[key] = {"text": text[:MAX_TEXT], "by": str(by or "")[:60], "at": time.time()}
        if len(data) > MAX_ITEMS:
            for old in sorted(data, key=lambda k: data[k].get("at", 0))[: len(data) - MAX_ITEMS]:
                data.pop(old, None)
        _save(data)
    return {"ok": True, "message": f"Shared as '{key}'.", "key": key}


def get(key: str) -> dict[str, Any]:
    key = _key(key)
    with _lock:
        item = _load().get(key)
    if not item:
        return {"ok": False, "error": f"Nothing shared as '{key}' yet.", "keys": keys()[:20]}
    return {"ok": True, "message": item["text"], "key": key, "by": item.get("by", ""), "at": item.get("at", 0)}


def keys() -> list[str]:
    with _lock:
        data = _load()
    return sorted(data, key=lambda k: -data[k].get("at", 0))


def share_result(key: str, text: str) -> dict[str, Any]:
    try:
        import bots
        who = str((bots.current_bot() or {}).get("name") or "") if hasattr(bots, "current_bot") else ""
    except Exception:
        who = ""
    return put(key, text, by=who or "Ped Bot")


def read_shared(key: str = "") -> dict[str, Any]:
    if not str(key or "").strip():
        listing = keys()[:30]
        return {"ok": True, "message": ("Shared items: " + ", ".join(listing)) if listing else "Nothing shared yet.",
                "keys": listing}
    return get(key)


DECLARATIONS = [
    {"name": "share_result",
     "description": "Save a result in the shared notebook so other bots and tasks can use it (never passwords or keys).",
     "parameters": {"type": "object", "properties": {
         "key": {"type": "string", "description": "Short name, e.g. 'downloads-summary'."},
         "text": {"type": "string", "description": "The result to share."}}, "required": ["key", "text"]}},
    {"name": "read_shared",
     "description": "Read a result another bot or task shared (task results are under 'task:<id>'). No key lists what is there.",
     "parameters": {"type": "object", "properties": {"key": {"type": "string"}}}},
]
TOOLS = {"share_result": share_result, "read_shared": read_shared}
READ_ONLY = {"read_shared"}
