"""1.9.0 Batch 2 dispatcher: Settings › Advanced flags and /api/pro tools.

Risky tools default OFF. Nothing here spends money or sends a message on its own.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

RISKY = frozenset({"phone_control", "pc_autopilot", "self_skills", "live_cam", "hey_home"})
DEFAULTS: dict[str, bool] = {
    "phone_control": False,
    "pc_autopilot": False,
    "memory": True,
    "team": True,
    "voice_clone": False,
    "live_cam": False,
    "self_skills": False,
    "hey_home": False,
    "income": True,
}
LABELS = {
    "phone_control": "Phone control",
    "pc_autopilot": "PC autopilot",
    "memory": "Long-term memory",
    "team": "Team tasks",
    "voice_clone": "My real voice (PC)",
    "live_cam": "Live video avatar",
    "self_skills": "Self-coding skills",
    "hey_home": "Hey Ped + smart home",
    "income": "Income bots",
}

_lock = threading.Lock()


def _path() -> Path:
    import agent_config

    folder = agent_config.storage_dir() / "pro190"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "flags.json"


def _load() -> dict[str, bool]:
    data = dict(DEFAULTS)
    try:
        raw = json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return data
    if isinstance(raw, dict):
        for key in DEFAULTS:
            if key in raw:
                data[key] = bool(raw[key])
    return data


def _save(data: dict[str, bool]) -> None:
    tmp = _path().with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
    tmp.replace(_path())


def flags(patch: dict[str, Any] | None = None) -> dict[str, Any]:
    with _lock:
        data = _load()
        if patch:
            for key, value in patch.items():
                if key in DEFAULTS:
                    data[key] = bool(value)
            _save(data)
    items = []
    for key, on in data.items():
        items.append({
            "id": key,
            "name": LABELS[key],
            "on": on,
            "risky": key in RISKY,
        })
    return {"ok": True, "flags": data, "items": items}


def flag(name: str) -> bool:
    return bool(_load().get(name))


def need(name: str) -> dict[str, Any] | None:
    if flag(name):
        return None
    return {
        "ok": False,
        "error": f"{LABELS.get(name, name)} is off. Turn it on in Settings › Advanced.",
        "flag": name,
    }


def dispatch(data: dict[str, Any]) -> dict[str, Any]:
    """One endpoint for the Pro page. Unknown tools fail closed."""
    tool = str(data.get("tool") or "")
    g = lambda k, d="": data.get(k, d)
    try:
        if tool in ("", "flags"):
            patch = g("flags", None)
            return flags(patch if isinstance(patch, dict) else None)
        if tool == "phone":
            blocked = need("phone_control")
            if blocked:
                return blocked
            import phone_drive
            return phone_drive.handle(str(g("action", "plan")), data)
        if tool == "autopilot":
            blocked = need("pc_autopilot")
            if blocked:
                return blocked
            import see_click
            return see_click.handle(str(g("action", "status")), data)
        if tool == "memory":
            blocked = need("memory")
            if blocked:
                return blocked
            import bot_ltm
            return bot_ltm.handle(str(g("action", "list")), data)
        if tool == "team":
            blocked = need("team")
            if blocked:
                return blocked
            import team_board
            return team_board.handle(str(g("action", "status")), data)
        if tool == "voice":
            blocked = need("voice_clone")
            if blocked:
                return blocked
            import voice_real
            return voice_real.handle(str(g("action", "status")), data)
        if tool == "live":
            blocked = need("live_cam")
            if blocked:
                return blocked
            import live_twin
            return live_twin.handle(str(g("action", "status")), data)
        if tool == "skill":
            blocked = need("self_skills")
            if blocked:
                return blocked
            import skill_forge
            return skill_forge.handle(str(g("action", "list")), data)
        if tool == "home":
            blocked = need("hey_home")
            if blocked:
                return blocked
            import hey_home
            return hey_home.handle(str(g("action", "status")), data)
        if tool == "income":
            blocked = need("income")
            if blocked:
                return blocked
            import income_gigs
            return income_gigs.handle(str(g("action", "search")), data)
        if tool == "bots":
            import bots
            return {"ok": True, "bots": [{"id": b["id"], "name": b["name"]} for b in bots.list_bots()]}
    except Exception as exc:
        return {"ok": False, "error": "That Pro tool hit a problem.", "detail": str(exc)[:220]}
    return {"ok": False, "error": "Unknown Pro tool."}
