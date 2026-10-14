"""Persistent task progress so a long job can resume across runs and restarts."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

PATH = Path(__file__).resolve().parent / "workspace" / "task_memory.json"
_lock = threading.Lock()


def _load() -> dict[str, Any]:
    try:
        return json.loads(PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _key(task: str) -> str:
    return " ".join((task or "").casefold().split())[:80] or "general"


def save_task_progress(task: str, done: str = "", left: str = "", note: str = "") -> dict[str, Any]:
    with _lock:
        data = _load()
        row = data.get(_key(task), {"task": task, "log": []})
        entry = {"t": time.strftime("%Y-%m-%d %H:%M"), "done": done, "left": left, "note": note}
        row["log"] = (row.get("log", []) + [entry])[-50:]
        row["updated"] = entry["t"]
        data[_key(task)] = row
        PATH.parent.mkdir(parents=True, exist_ok=True)
        PATH.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    return {"ok": True, "message": f"Saved progress for '{task}'."}


def get_task_progress(task: str) -> dict[str, Any]:
    row = _load().get(_key(task))
    if not row:
        return {"ok": True, "message": "No saved progress for that task yet.", "log": []}
    return {"ok": True, "message": f"Last update {row.get('updated')}.", "log": row.get("log", [])[-10:]}


DECLARATIONS = [
    {"name": "save_task_progress",
     "description": "Save what is finished and what is left for a long task (e.g. 'wingz'), so a later run can resume. Call after each finished item.",
     "parameters": {"type": "object", "properties": {
         "task": {"type": "string"}, "done": {"type": "string"},
         "left": {"type": "string"}, "note": {"type": "string"}}, "required": ["task"]}},
    {"name": "get_task_progress",
     "description": "Read saved progress for a long task before starting or resuming it. Saved notes are hints; re-check the screen.",
     "parameters": {"type": "object", "properties": {"task": {"type": "string"}}, "required": ["task"]}},
]
