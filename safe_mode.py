"""Safe mode / Pause all: one button (PC or phone) that stops every bot at once.

While paused: running turns are cancelled, every tool call is refused, routines and
idle tasks don't start, and autopilot stops. Chat still works so you can talk.
The pause is saved, so it also holds after a restart until you press Resume.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any

_lock = threading.Lock()
_paused: dict[str, Any] | None = None
_loaded = False
SAFE_TOOLS = {"ask_user", "list_routines", "get_time", "safe_mode_status"}
MESSAGE = "Safe mode is on: everything is paused. Press Resume to let bots act again."


def _file() -> Path:
    try:
        import agent_config

        return agent_config.storage_dir() / "safe_mode.json"
    except Exception:
        return Path(__file__).resolve().parent / "workspace" / "safe_mode.json"


def _load() -> None:
    global _paused, _loaded
    if _loaded:
        return
    _loaded = True
    try:
        data = json.loads(_file().read_text(encoding="utf-8"))
        _paused = data if data.get("paused") else None
    except (OSError, ValueError):
        _paused = None


def _save() -> None:
    try:
        f = _file()
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(_paused or {"paused": False}), encoding="utf-8")
    except OSError:
        pass


def paused() -> bool:
    with _lock:
        _load()
        return _paused is not None


def status() -> dict[str, Any]:
    with _lock:
        _load()
        return {"paused": _paused is not None, "since": (_paused or {}).get("since"),
                "by": (_paused or {}).get("by", "")}


def pause_all(state: Any = None, by: str = "pc") -> dict[str, Any]:
    global _paused
    with _lock:
        _load()
        _paused = {"paused": True, "since": time.time(), "by": by}
        _save()
    stopped = []
    if state is not None and hasattr(state, "any_busy"):
        # 1.4.15: running chats are not cancelled; they freeze at their next safe point
        # (before the next model call or tool) and go on cleanly after Resume. Stop still cancels.
        try:
            if state.any_busy():
                stopped.append("running chats (frozen until Resume)")
        except Exception:
            pass
    for mod, fn in (("idle_tasks", "stop_idle_tasks"),):
        try:
            getattr(__import__(mod), fn)()
            stopped.append("idle tasks")
        except Exception:
            pass
    try:
        import autopilot

        autopilot.instance().stop()
        stopped.append("autopilot")
    except Exception:
        pass
    try:
        import live_sync

        live_sync.notify("paused", by=by)
    except Exception:
        pass
    return {"ok": True, "paused": True, "stopped": stopped, "message": "Paused everything. " + MESSAGE}


def resume_all(state: Any = None, by: str = "pc") -> dict[str, Any]:
    global _paused
    with _lock:
        _load()
        _paused = None
        _save()
    if state is not None and getattr(state, "cancel", None) is not None:
        try:
            state.cancel.clear()
        except Exception:
            pass
    try:
        import live_sync

        live_sync.notify("resumed", by=by)
    except Exception:
        pass
    return {"ok": True, "paused": False, "message": "Resumed. Bots and routines can act again."}


def refuse(tool: str) -> dict[str, Any] | None:
    if tool in SAFE_TOOLS or not paused():
        return None
    return {"ok": False, "error": MESSAGE, "paused": True}


def _reset_for_tests() -> None:
    global _paused, _loaded
    with _lock:
        _paused, _loaded = None, True
