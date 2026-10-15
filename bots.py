"""Custom bots. Each bot is bots/<id>.json with a name, colour, avatar style,
role (system prompt), allowed tools, optional model, optional per-bot rules
override, and tasks (one-off, scheduled, or woken by a new file). A bot runs
on the same Gemini tool-calling engine (run_agent) and rules.yaml; its tool
list and rules override apply only to its own thread. Its chat thread is
session "bot-<id>".

A bot keeps its own notebook, lessons, and folder. It may hand one task to
another bot; that second bot cannot hand the task on. Scheduled tasks run
unattended, so risky actions wait for your yes (confirm rules still apply).
"""

from __future__ import annotations

import fnmatch
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
AVATARS = ("round", "square", "spark", "robot", "cat", "ghost", "bunny", "fox", "bear", "owl", "alien", "dino", "panda", "frog", "chick", "octopus", "star")
_lock = threading.RLock()
# A bot may call ask_bot once. run_team stays blocked. The callee runs with
# handoff off, so the chain cannot grow.
NO_NESTING = {"run_team"}
SELF_TOOLS = frozenset({
    "bot_remember", "bot_notes", "save_bot_skill", "list_bot_skills", "list_my_files",
    "teach_bot", "stop_demonstration", "replay_skill", "follow_skill",
})
_ctx = threading.local()

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
    watch = None
    raw_watch = raw.get("watch")
    if isinstance(raw_watch, dict):
        path = " ".join(str(raw_watch.get("path") or "").split())[:300]
        pattern = " ".join(str(raw_watch.get("pattern") or "*").split())[:80] or "*"
        if path:
            watch = {"path": path, "pattern": pattern}
    seen: dict[str, int] = {}
    raw_seen = raw.get("watch_seen") if isinstance(raw.get("watch_seen"), dict) else {}
    for key, value in list(raw_seen.items())[:500]:
        try:
            seen[str(key)[:180]] = int(value)
        except (TypeError, ValueError):
            continue
    paths = [str(item)[:300] for item in (raw.get("last_paths") or []) if str(item).strip()][:30]
    return {
        "id": str(raw.get("id") or uuid.uuid4().hex[:8]),
        "text": text,
        "schedule": clean or None,  # None = one-off (run on demand)
        "watch": watch,
        "watch_armed": bool(raw.get("watch_armed")),
        "watch_seen": seen,
        "enabled": bool(raw.get("enabled", True)),
        "last_run": float(raw.get("last_run") or 0),
        "last_result": str(raw.get("last_result") or "")[:2000],
        "last_paths": paths,
    }


def _looks_secret(text: str) -> bool:
    try:
        import agent_core

        return bool(agent_core._memory_is_secret(text or ""))
    except Exception:
        return False


def _clean_notes(raw: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not isinstance(raw, list):
        return out
    for item in raw[:40]:
        if isinstance(item, str):
            text, note_id, at = item, uuid.uuid4().hex[:8], time.time()
        elif isinstance(item, dict):
            text = str(item.get("text") or "")
            note_id = str(item.get("id") or uuid.uuid4().hex[:8])[:12]
            try:
                at = float(item.get("at") or time.time())
            except (TypeError, ValueError):
                at = time.time()
        else:
            continue
        text = " ".join(text.split())[:500]
        if text and not _looks_secret(text):
            out.append({"id": note_id, "text": text, "at": at})
    return out


def _clean_skills(raw: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not isinstance(raw, list):
        return out
    for item in raw[:20]:
        if not isinstance(item, dict):
            continue
        name = " ".join(str(item.get("name") or "").split())[:60]
        text = str(item.get("text") or "")[:4000]
        if not name or not text or _looks_secret(name) or _looks_secret(text):
            continue
        out.append({
            "id": str(item.get("id") or uuid.uuid4().hex[:8])[:12],
            "name": name,
            "text": text,
            "replay": str(item.get("replay") or "")[:60],
            "at": float(item.get("at") or time.time()) if str(item.get("at") or "").strip() else time.time(),
        })
    return out


def normalise(data: dict[str, Any], existing: dict[str, Any] | None = None) -> dict[str, Any]:
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
    prior = existing or {}
    notes_raw = data["notes"] if "notes" in data else prior.get("notes")
    skills_raw = data["skills"] if "skills" in data else prior.get("skills")
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
        "notes": _clean_notes(notes_raw),
        "skills": _clean_skills(skills_raw),
        "created": float(data.get("created") or prior.get("created") or time.time()),
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


def bot_folder(bot: dict[str, Any]) -> Path:
    """This bot's own files: Documents/PedroAgent/bots/<id>."""
    env = os.environ.get("BOT_FILES_DIR", "").strip()
    base = Path(env) if env else Path.home() / "Documents" / "PedroAgent" / "bots"
    folder = base / _slug(bot["id"])
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def save_bot(data: dict[str, Any]) -> dict[str, Any]:
    existing = get_bot(str(data.get("id") or "")) if data.get("id") else None
    bot = normalise(data, existing)
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


def _bind(bot_id: str, handoff: bool) -> tuple[str, bool, list[str]]:
    prev = (
        str(getattr(_ctx, "bot_id", "") or ""),
        bool(getattr(_ctx, "handoff", True)),
        list(getattr(_ctx, "paths", []) or []),
    )
    _ctx.bot_id = bot_id
    _ctx.handoff = handoff
    _ctx.paths = []
    return prev


def _restore(prev: tuple[str, bool, list[str]]) -> None:
    _ctx.bot_id, _ctx.handoff, _ctx.paths = prev


def current_bot() -> dict[str, Any] | None:
    bot_id = str(getattr(_ctx, "bot_id", "") or "")
    return get_bot(bot_id) if bot_id else None


def note_tool_paths(result: dict[str, Any]) -> None:
    """Remember file paths a bot's tool just wrote, for the next run."""
    if not getattr(_ctx, "bot_id", ""):
        return
    found: list[str] = []
    for key in ("path", "file", "output", "saved", "output_path"):
        value = result.get(key)
        if isinstance(value, str) and value.strip():
            found.append(value.strip())
    extra = result.get("paths")
    if isinstance(extra, list):
        found.extend(str(item).strip() for item in extra if str(item).strip())
    bag = getattr(_ctx, "paths", None)
    if bag is None:
        return
    for item in found:
        short = item[:300]
        if short not in bag:
            bag.append(short)


def _prompt(bot: dict[str, Any], text: str) -> str:
    role = bot["role"].strip() or f"You are {bot['name']}, a helpful assistant."
    tools = ", ".join(bot["tools"]) if bot["tools"] else "any allowed tool"
    try:
        folder = str(bot_folder(bot))
    except OSError:
        folder = ""
    lines = [
        f"[You are the bot '{bot['name']}'. Role: {role} Tools you may use: {tools}.",
        "You may react to the user's message by adding one [[react:EMOJI]] tag, e.g. [[react:👍]] to acknowledge or [[react:✅]] when a task is finished.",
    ]
    if folder:
        lines.append(f"Your own folder is {folder}. Save this bot's files there unless the user names another place. list_my_files shows what is already in it.")
    lines.append("Remember a fact the user teaches you with bot_remember. Follow a saved lesson with list_bot_skills when the task matches it.")
    lines.append("You may hand one task to another bot with ask_bot. That bot cannot hand the task on.")
    lines.append("If the user wants to teach you by doing a task on this PC, call teach_bot with a short lesson name, tell them to do it, and wait. When they say stop, call stop_demonstration. replay_skill repeats the recorded clicks. Where the lesson typed and the user gave new words, pass them as inputs, one value per line. When the questions or labels on screen are different, call follow_skill. It reads the screen, types the answer that fits, and fixes a step that did not land. It stops for a password or a graded test, quiz, or exam. Do not store a password.")
    notes = bot.get("notes") or []
    if notes:
        lines.append("Notebook:\n" + "\n".join(f"- {n['text']}" for n in notes[-20:]))
    skills = bot.get("skills") or []
    if skills:
        blocks = []
        for skill in skills[-6:]:
            body = str(skill.get("text") or "")[:1200]
            replay = f" Replay name: {skill['replay']}." if skill.get("replay") else ""
            blocks.append(f"### {skill['name']}{replay}\n{body}")
        lines.append("Lessons you were taught. Follow them when the task matches:\n" + "\n".join(blocks))
    lines.append("]")
    return "\n".join(lines) + f"\n\n{text}"


def _scope_for(bot: dict[str, Any], extra_tools: set[str] | None, handoff: bool) -> set[str]:
    import agent_core

    scope = set(bot["tools"]) if bot["tools"] else set(agent_core.TOOLS)
    if extra_tools:
        scope |= {t for t in extra_tools if t in agent_core.TOOLS}
    scope |= set(SELF_TOOLS)
    if handoff:
        scope.add("ask_bot")
    else:
        scope.discard("ask_bot")
    return scope - NO_NESTING


def run_bot(bot: dict[str, Any], text: str, history: list[Any] | None = None, *,
            model: str = "", unattended: bool = False, extra_tools: set[str] | None = None,
            handoff: bool = True, **kwargs: Any) -> str:
    """One turn for this bot on the normal engine, scoped to its tools/rules."""
    import agent_core

    run = engine or agent_core.run_agent
    chosen = bot.get("model") or model or os.environ.get("GEMINI_MODEL", agent_core.DEFAULT_MODEL)
    rules.set_thread_override(bot.get("rules") or None)
    agent_core.set_tool_scope(_scope_for(bot, extra_tools, handoff))
    agent_core.set_unattended(unattended)
    prev = _bind(bot["id"], handoff)
    try:
        return run(_prompt(bot, text), history if history is not None else [], chosen, **kwargs) or ""
    finally:
        with _lock:
            _recent_paths[bot["id"]] = list(getattr(_ctx, "paths", []) or [])
        _restore(prev)
        rules.set_thread_override(None)
        agent_core.set_tool_scope(None)
        agent_core.set_unattended(False)


_recent_paths: dict[str, list[str]] = {}


def _schedule_due(task: dict[str, Any], now: float) -> bool:
    sched = task.get("schedule")
    if not task.get("enabled") or not sched:
        return False
    if "every_minutes" in sched:
        return now - task["last_run"] >= sched["every_minutes"] * 60
    hour, minute = (int(x) for x in sched["daily"].split(":"))
    local = time.localtime(now)
    target = time.mktime((local.tm_year, local.tm_mon, local.tm_mday, hour, minute, 0, 0, 0, -1))
    return now >= target and task["last_run"] < target


def _due(task: dict[str, Any], now: float) -> bool:
    return _schedule_due(task, now)


def _resolve_watch(path: str, bot: dict[str, Any]) -> Path | None:
    text = (path or "").strip().strip('"')
    key = text.casefold()
    home = Path.home()
    named = {
        "downloads": home / "Downloads",
        "desktop": home / "Desktop",
        "documents": home / "Documents",
        "mine": bot_folder(bot),
        "my folder": bot_folder(bot),
        "my files": bot_folder(bot),
    }
    folder = named.get(key, Path(text).expanduser())
    try:
        resolved = folder.resolve()
        resolved.relative_to(home.resolve())
    except (OSError, ValueError):
        return None
    return resolved


def _watch_map(bot: dict[str, Any], task: dict[str, Any]) -> dict[str, int] | None:
    watch = task.get("watch") or None
    if not watch:
        return None
    folder = _resolve_watch(str(watch.get("path") or ""), bot)
    if folder is None or not folder.is_dir():
        return None
    pattern = str(watch.get("pattern") or "*")
    current: dict[str, int] = {}
    try:
        entries = list(folder.iterdir())
    except OSError:
        return None
    for path in entries:
        if not path.is_file() or not fnmatch.fnmatch(path.name, pattern):
            continue
        try:
            current[path.name] = int(path.stat().st_mtime)
        except OSError:
            continue
    return current


def _scan_watch(bot: dict[str, Any], task: dict[str, Any]) -> tuple[list[str], bool]:
    """Return (new or changed file paths, True when this call only armed the baseline)."""
    if not task.get("watch") or not task.get("enabled", True):
        return [], False
    current = _watch_map(bot, task)
    if current is None:
        return [], False
    if not task.get("watch_armed"):
        task["watch_armed"] = True
        task["watch_seen"] = current
        return [], True
    folder = _resolve_watch(str(task["watch"].get("path") or ""), bot)
    seen = task.get("watch_seen") or {}
    hits: list[str] = []
    for name, stamp in current.items():
        if name not in seen or int(seen[name]) < stamp:
            hits.append(str((folder or Path()) / name))
    return hits, False


def _task_prompt(bot: dict[str, Any], task: dict[str, Any], files: list[str]) -> str:
    lines = [task["text"]]
    if task.get("last_result"):
        lines.append("Last time you ran this, you reported:\n" + str(task["last_result"])[:1500])
    if task.get("last_paths"):
        lines.append("Files from that run:\n" + "\n".join(str(p) for p in task["last_paths"][:20]))
    if files:
        lines.append("New or changed files:\n" + "\n".join(files[:20]))
    if task.get("last_result") or files:
        lines.append("Continue from the last run. Do not redo work that is already done.")
    return "\n\n".join(lines)


def run_task(bot_id: str, task_id: str, *, unattended: bool = True,
             pending_files: list[str] | None = None) -> dict[str, Any]:
    """Run one of a bot's tasks now; the result lands in the bot's thread."""
    bot = get_bot(bot_id)
    if bot is None:
        return {"ok": False, "error": f"No bot '{bot_id}'."}
    task = next((t for t in bot["tasks"] if t["id"] == task_id), None)
    if task is None:
        return {"ok": False, "error": "No such task."}
    session = session_for(bot)
    files = list(pending_files or [])
    _store(session, "user", f"[task] {task['text']}")
    try:
        reply = run_bot(bot, _task_prompt(bot, task, files), [], unattended=unattended)
        ok = True
    except Exception as exc:
        reply, ok = f"Task failed: {exc}", False
    _store(session, "assistant", reply)
    paths = list(_recent_paths.get(bot["id"]) or [])
    with _lock:
        fresh = get_bot(bot["id"]) or bot
        for item in fresh["tasks"]:
            if item["id"] == task_id:
                item["last_run"] = time.time()
                item["last_result"] = reply[:2000]
                item["last_paths"] = paths
                if item.get("watch"):
                    current = _watch_map(fresh, item)
                    if current is not None:
                        item["watch_seen"] = current
                        item["watch_armed"] = True
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
        fresh = get_bot(bot["id"]) or bot
        dirty = False
        pending: list[tuple[str, list[str]]] = []
        for task in fresh["tasks"]:
            hits, armed = _scan_watch(fresh, task)
            if armed:
                dirty = True
            if task.get("enabled", True) and (_schedule_due(task, now) or hits):
                pending.append((task["id"], hits))
        if dirty:
            save_bot(fresh)
        for task_id, hits in pending:
            results.append(run_task(bot["id"], task_id, pending_files=hits))
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

def _target_bot(name: str = "") -> dict[str, Any] | None:
    return get_bot(name) if str(name or "").strip() else current_bot()


def bot_remember(text: str, bot: str = "") -> dict[str, Any]:
    """Save one fact in a bot's own notebook."""
    target = _target_bot(bot)
    if target is None:
        return {"ok": False, "error": "Say which bot should remember this."}
    note = " ".join(str(text or "").split())[:500]
    if not note:
        return {"ok": False, "error": "There is nothing to remember."}
    if _looks_secret(note):
        return {"ok": False, "error": "That looks like a password or a key, so it was not saved."}
    notes = [n for n in (target.get("notes") or []) if n.get("text") != note]
    notes.append({"id": uuid.uuid4().hex[:8], "text": note, "at": time.time()})
    target["notes"] = notes[-40:]
    save_bot(target)
    return {"ok": True, "message": f"{target['name']} remembered that.", "bot": target["name"]}


def bot_notes(bot: str = "") -> dict[str, Any]:
    target = _target_bot(bot)
    if target is None:
        return {"ok": False, "error": "Say which bot's notebook to read."}
    notes = [n["text"] for n in target.get("notes") or []]
    return {"ok": True, "message": f"{len(notes)} note(s).", "notes": notes, "bot": target["name"]}


def save_bot_skill(name: str, steps: str, bot: str = "") -> dict[str, Any]:
    """Save a short procedure this bot should follow next time."""
    target = _target_bot(bot)
    if target is None:
        return {"ok": False, "error": "Say which bot should learn this."}
    title = " ".join(str(name or "").split())[:60]
    body = str(steps or "").strip()[:4000]
    if not title or not body:
        return {"ok": False, "error": "A lesson needs a name and the steps."}
    if _looks_secret(title) or _looks_secret(body):
        return {"ok": False, "error": "That lesson looks like it contains a secret, so it was not saved."}
    return add_taught_skill(target["id"], title, body)


def list_bot_skills(bot: str = "") -> dict[str, Any]:
    target = _target_bot(bot)
    if target is None:
        return {"ok": False, "error": "Say which bot's lessons to list."}
    rows = [{"name": s["name"], "replay": s.get("replay") or "", "text": s["text"][:1500]}
            for s in target.get("skills") or []]
    return {"ok": True, "message": f"{len(rows)} lesson(s).", "skills": rows, "bot": target["name"]}


def add_taught_skill(bot_id: str, name: str, text: str, replay: str = "") -> dict[str, Any]:
    target = get_bot(bot_id)
    if target is None:
        return {"ok": False, "error": "No such bot."}
    title = " ".join(str(name or "").split())[:60]
    body = str(text or "").strip()[:4000]
    if not title or not body:
        return {"ok": False, "error": "A lesson needs a name and the steps."}
    if _looks_secret(title) or _looks_secret(body):
        return {"ok": False, "error": "That lesson looks like it contains a secret, so it was not added."}
    skills = [s for s in (target.get("skills") or []) if _slug(str(s.get("name") or "")) != _slug(title)]
    skills.append({
        "id": uuid.uuid4().hex[:8],
        "name": title,
        "text": body,
        "replay": (replay or title)[:60],
        "at": time.time(),
    })
    target["skills"] = skills[-20:]
    save_bot(target)
    return {"ok": True, "message": f"Taught {target['name']} the lesson '{title}'.", "bot": target["name"], "name": title}


def list_my_files(bot: str = "") -> dict[str, Any]:
    """List files in this bot's own folder."""
    target = _target_bot(bot)
    if target is None:
        return {"ok": False, "error": "Say which bot's folder to list."}
    try:
        folder = bot_folder(target)
    except OSError as exc:
        return {"ok": False, "error": f"Could not open the bot folder: {exc}"}
    rows = []
    try:
        entries = sorted(folder.iterdir(), key=lambda p: p.name.casefold())
    except OSError as exc:
        return {"ok": False, "error": f"Could not read the bot folder: {exc}"}
    for path in entries:
        if path.is_file() and not path.name.startswith("."):
            rows.append(str(path))
        if len(rows) >= 80:
            break
    return {"ok": True, "message": f"{len(rows)} file(s) in {folder}.", "path": str(folder), "files": rows}


def teach_bot(name: str, bot: str = "") -> dict[str, Any]:
    """Watch the user do a task on this PC and save it as this bot's lesson."""
    target = _target_bot(bot)
    if target is None:
        return {"ok": False, "error": "Open a bot, or name the bot you want to teach."}
    import demo_skills

    result = demo_skills.record_demonstration(name, bot=target["id"])
    if result.get("ok"):
        result["bot"] = target["name"]
    return result


def ask_bot(name: str, task: str) -> dict[str, Any]:
    if not bool(getattr(_ctx, "handoff", True)):
        return {"ok": False, "error": "A bot can hand work to one other bot, and that bot cannot hand it on."}
    bot = get_bot(name)
    if bot is None:
        return {"ok": False, "error": f"No bot named '{name}'.", "bots": [b["name"] for b in list_bots()]}
    caller = current_bot()
    if caller is not None and caller["id"] == bot["id"]:
        return {"ok": False, "error": f"{bot['name']} cannot hand a task to itself."}
    session = session_for(bot)
    _store(session, "user", f"[from another bot] {task}" if caller else f"[from main agent] {task}")
    box: dict[str, Any] = {}

    def work() -> None:  # own thread: keeps the caller's turn state intact
        try:
            box["reply"] = run_bot(bot, task, [], handoff=False)
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
     "description": "Hand one task to another custom bot by name. A bot may do this once. The bot that receives the task cannot hand it on.",
     "parameters": {"type": "object", "properties": {"name": {"type": "string"}, "task": {"type": "string"}},
                    "required": ["name", "task"]}},
    {"name": "list_bots", "description": "List the user's custom bots and their roles.",
     "parameters": {"type": "object", "properties": {}}},
    {"name": "bot_remember",
     "description": "Save one fact in a bot's notebook so later runs remember it. Omit bot while that bot is already running.",
     "parameters": {"type": "object", "properties": {
         "text": {"type": "string"},
         "bot": {"type": "string", "description": "Bot name. Optional when that bot is speaking."}},
         "required": ["text"]}},
    {"name": "bot_notes",
     "description": "Read one bot's notebook.",
     "parameters": {"type": "object", "properties": {"bot": {"type": "string"}}}},
    {"name": "save_bot_skill",
     "description": "Save a named procedure (the steps) on a bot so it follows them next time.",
     "parameters": {"type": "object", "properties": {
         "name": {"type": "string"}, "steps": {"type": "string"}, "bot": {"type": "string"}},
         "required": ["name", "steps"]}},
    {"name": "list_bot_skills",
     "description": "List the lessons saved on a bot, including ones taught by recording the screen.",
     "parameters": {"type": "object", "properties": {"bot": {"type": "string"}}}},
    {"name": "list_my_files",
     "description": "List files in a bot's own folder under Documents/PedroAgent/bots.",
     "parameters": {"type": "object", "properties": {"bot": {"type": "string"}}}},
    {"name": "teach_bot",
     "description": "Start watching the user do a task on this PC and save it as a lesson for one bot. Tell the user to do the task, then call stop_demonstration.",
     "parameters": {"type": "object", "properties": {
         "name": {"type": "string", "description": "Short lesson name."},
         "bot": {"type": "string", "description": "Bot name. Optional when that bot is speaking."}},
         "required": ["name"]}},
]
TOOLS = {
    "ask_bot": ask_bot, "list_bots": list_bots_tool,
    "bot_remember": bot_remember, "bot_notes": bot_notes,
    "save_bot_skill": save_bot_skill, "list_bot_skills": list_bot_skills,
    "list_my_files": list_my_files, "teach_bot": teach_bot,
}
