"""Custom bots. Each bot is bots/<id>.json with a name, colour, avatar style,
role (system prompt), allowed tools, optional model, optional per-bot rules
override, and tasks (one-off or scheduled). A bot runs on the same Gemini
tool-calling engine (run_agent) and rules.yaml; its tool list and rules
override apply only to its own thread. Its chat thread is session "bot-<id>".
The main agent delegates with ask_bot; scheduled tasks run unattended, so
risky actions wait for your yes (confirm rules still apply).
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable

import rules

SESSION_PREFIX = "bot-"
COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
AVATARS = ("round", "square", "spark", "robot", "cat", "ghost", "bunny")
_lock = threading.RLock()
NO_NESTING = {"ask_bot", "run_team"}  # a bot cannot start other bots/teams

# Tests replace: engine(prompt, history, model, **kwargs) -> str
engine: Callable[..., str] | None = None


def bots_dir() -> Path:
    env = os.environ.get("BOTS_DIR", "").strip()
    if env:
        return Path(env)
    import agent_config

    return agent_config.storage_dir() / "bots"


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (value or "").casefold()).strip("-")[:40]


def _clean_task(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    text = " ".join(str(raw.get("text") or "").split())[:2000]
    if not text:
        return None
    schedule = raw.get("schedule") or {}
    clean: dict[str, Any] = {}
    if isinstance(schedule, dict):
        if schedule.get("every_minutes"):
            clean["every_minutes"] = max(1, int(schedule["every_minutes"]))
        elif re.fullmatch(r"\d{1,2}:\d{2}", str(schedule.get("daily") or "")):
            clean["daily"] = str(schedule["daily"])
    return {
        "id": str(raw.get("id") or uuid.uuid4().hex[:8]),
        "text": text,
        "schedule": clean or None,  # None = one-off (run on demand)
        "enabled": bool(raw.get("enabled", True)),
        "last_run": float(raw.get("last_run") or 0),
        "last_result": str(raw.get("last_result") or "")[:2000],
    }


def normalise(data: dict[str, Any]) -> dict[str, Any]:
    name = " ".join(str(data.get("name") or "").split())[:60]
    if not name:
        raise ValueError("A bot needs a name.")
    bot_id = _slug(str(data.get("id") or "")) or _slug(name) or uuid.uuid4().hex[:8]
    color = str(data.get("color") or "#7c5cff")
    override = data.get("rules") or {}
    if isinstance(override, str):
        override = rules.parse_text(override, ".yaml") if override.strip() else {}
    if not isinstance(override, dict):
        raise ValueError("The bot's rules override must be a mapping.")
    tools = data.get("tools") or []
    if isinstance(tools, str):
        tools = [t for t in re.split(r"[\s,]+", tools) if t]
    return {
        "id": bot_id,
        "name": name,
        "color": color if COLOR.match(color) else "#7c5cff",
        "avatar": data.get("avatar") if data.get("avatar") in AVATARS else "round",
        "role": str(data.get("role") or "")[:8000],
        "model": str(data.get("model") or "")[:80],
        "tools": sorted({str(t) for t in tools}),
        "rules": override,
        "tasks": [t for t in (_clean_task(x) for x in data.get("tasks") or []) if t],
        "created": float(data.get("created") or time.time()),
    }


def _path(bot_id: str) -> Path:
    slug = _slug(bot_id)
    if not slug:
        raise ValueError("Bad bot id.")
    return bots_dir() / f"{slug}.json"


def list_bots() -> list[dict[str, Any]]:
    folder = bots_dir()
    out = []
    for path in sorted(folder.glob("*.json")) if folder.is_dir() else []:
        try:
            out.append(normalise(json.loads(path.read_text(encoding="utf-8"))))
        except Exception:
            continue
    return sorted(out, key=lambda b: b["created"])


def get_bot(name_or_id: str) -> dict[str, Any] | None:
    key = _slug(name_or_id)
    for bot in list_bots():
        if bot["id"] == key or _slug(bot["name"]) == key:
            return bot
    return None


def save_bot(data: dict[str, Any]) -> dict[str, Any]:
    bot = normalise(data)
    with _lock:
        folder = bots_dir()
        folder.mkdir(parents=True, exist_ok=True)
        if not data.get("id"):  # new bot: avoid clobbering a namesake
            base, n = bot["id"], 2
            while _path(bot["id"]).exists():
                bot["id"], n = f"{base}-{n}", n + 1
        tmp = _path(bot["id"]).with_suffix(".tmp")
        tmp.write_text(json.dumps(bot, indent=2), encoding="utf-8")
        os.replace(tmp, _path(bot["id"]))
    return bot


def delete_bot(bot_id: str) -> bool:
    with _lock:
        path = _path(bot_id)
        if not path.is_file():
            return False
        path.unlink()
    try:
        import chat_store

        chat_store.delete_session(SESSION_PREFIX + _slug(bot_id))
    except Exception:
        pass
    return True


def session_for(bot: dict[str, Any]) -> str:
    return SESSION_PREFIX + bot["id"]


def bot_for_session(session: str) -> dict[str, Any] | None:
    if not str(session or "").startswith(SESSION_PREFIX):
        return None
    return get_bot(session[len(SESSION_PREFIX):])


def _prompt(bot: dict[str, Any], text: str) -> str:
    role = bot["role"].strip() or f"You are {bot['name']}, a helpful assistant."
    tools = ", ".join(bot["tools"]) if bot["tools"] else "any allowed tool"
    return f"[You are the bot '{bot['name']}'. Role: {role} Tools you may use: {tools}.]\n\n{text}"


def run_bot(bot: dict[str, Any], text: str, history: list[Any] | None = None, *,
            model: str = "", unattended: bool = False, **kwargs: Any) -> str:
    """One turn for this bot on the normal engine, scoped to its tools/rules."""
    import gta5_agent

    run = engine or gta5_agent.run_agent
    chosen = bot.get("model") or model or os.environ.get("GEMINI_MODEL", gta5_agent.DEFAULT_MODEL)
    rules.set_thread_override(bot.get("rules") or None)
    scope = set(bot["tools"]) if bot["tools"] else set(gta5_agent.TOOLS)
    gta5_agent.set_tool_scope(scope - NO_NESTING)
    gta5_agent.set_unattended(unattended)
    try:
        return run(_prompt(bot, text), history if history is not None else [], chosen, **kwargs) or ""
    finally:
        rules.set_thread_override(None)
        gta5_agent.set_tool_scope(None)
        gta5_agent.set_unattended(False)


def _due(task: dict[str, Any], now: float) -> bool:
    sched = task.get("schedule")
    if not task.get("enabled") or not sched:
        return False
    if "every_minutes" in sched:
        return now - task["last_run"] >= sched["every_minutes"] * 60
    hour, minute = (int(x) for x in sched["daily"].split(":"))
    local = time.localtime(now)
    target = time.mktime((local.tm_year, local.tm_mon, local.tm_mday, hour, minute, 0, 0, 0, -1))
    return now >= target and task["last_run"] < target


def run_task(bot_id: str, task_id: str, *, unattended: bool = True) -> dict[str, Any]:
    """Run one of a bot's tasks now; the result lands in the bot's thread."""
    bot = get_bot(bot_id)
    if bot is None:
        return {"ok": False, "error": f"No bot '{bot_id}'."}
    task = next((t for t in bot["tasks"] if t["id"] == task_id), None)
    if task is None:
        return {"ok": False, "error": "No such task."}
    session = session_for(bot)
    _store(session, "user", f"[task] {task['text']}")
    try:
        reply = run_bot(bot, task["text"], [], unattended=unattended)
        ok = True
    except Exception as exc:
        reply, ok = f"Task failed: {exc}", False
    _store(session, "assistant", reply)
    with _lock:
        fresh = get_bot(bot["id"]) or bot
        for item in fresh["tasks"]:
            if item["id"] == task_id:
                item["last_run"], item["last_result"] = time.time(), reply[:2000]
        save_bot(fresh)
    return {"ok": ok, "message": reply, "bot": bot["id"], "session": session}


def _store(session: str, role: str, text: str) -> None:
    try:
        import chat_store

        chat_store.add(session, role, text)
    except Exception:
        pass


def run_due_tasks(now: float | None = None) -> list[dict[str, Any]]:
    now = time.time() if now is None else now
    results = []
    for bot in list_bots():
        for task in bot["tasks"]:
            if _due(task, now):
                results.append(run_task(bot["id"], task["id"]))
    return results


class Scheduler:
    """Background tick that runs due bot tasks (started by the chat app)."""

    def __init__(self, every: float = 30.0) -> None:
        self.every = every
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._loop, name="bot-scheduler", daemon=True)

    def start(self) -> "Scheduler":
        self.thread.start()
        return self

    def _loop(self) -> None:
        while not self.stop.wait(self.every):
            try:
                run_due_tasks()
            except Exception:
                pass


# ---- tools for the main agent ----

def ask_bot(name: str, task: str) -> dict[str, Any]:
    bot = get_bot(name)
    if bot is None:
        return {"ok": False, "error": f"No bot named '{name}'.", "bots": [b["name"] for b in list_bots()]}
    session = session_for(bot)
    _store(session, "user", f"[from main agent] {task}")
    box: dict[str, Any] = {}

    def work() -> None:  # own thread: keeps the caller's turn state intact
        try:
            box["reply"] = run_bot(bot, task, [])
        except Exception as exc:
            box["error"] = str(exc)

    worker = threading.Thread(target=work, name=f"bot-{bot['id']}", daemon=True)
    worker.start()
    worker.join()
    if "error" in box:
        return {"ok": False, "error": f"{bot['name']} failed: {box['error']}"}
    reply = box.get("reply", "")
    _store(session, "assistant", reply)
    return {"ok": True, "message": reply, "bot": bot["name"]}


def list_bots_tool() -> dict[str, Any]:
    rows = [{"name": b["name"], "role": b["role"][:200], "tools": b["tools"],
             "tasks": len(b["tasks"])} for b in list_bots()]
    return {"ok": True, "message": f"{len(rows)} bots.", "bots": rows}


DECLARATIONS = [
    {"name": "ask_bot",
     "description": "Delegate a task to one of the user's custom bots (by name). It works with its own role and tools and its reply comes back.",
     "parameters": {"type": "object", "properties": {"name": {"type": "string"}, "task": {"type": "string"}},
                    "required": ["name", "task"]}},
    {"name": "list_bots", "description": "List the user's custom bots and their roles.",
     "parameters": {"type": "object", "properties": {}}},
]
TOOLS = {"ask_bot": ask_bot, "list_bots": list_bots_tool}
