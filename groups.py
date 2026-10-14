"""Bot groups (group rooms). groups/<id>.json holds a name, purpose, member bot
ids and a coordinator ("pedro" = Pedro_Agent, or a member bot id). The group
chat is session "group-<id>". Your message goes to the room:
  - @mentioned members answer in the order mentioned (@all = every member);
  - otherwise the coordinator answers first and may hand parts of the task to
    members by @mentioning them; those members then answer in turn.
Each reply is stored as "[[@speaker]] text" so the UI shows its name/avatar.
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

import bots

SESSION_PREFIX = "group-"
MAIN = "pedro"                 # Pedro_Agent itself
MAX_SPEAKERS = 6               # replies per message, so a room can't loop forever
TAG = re.compile(r"^\[\[@([a-z0-9-]+)\]\]\s?")
_lock = threading.RLock()
PICTURE = re.compile(r"data:image/(png|jpeg|webp);base64,[A-Za-z0-9+/=]+")
MAX_PICTURE = 280_000          # chars of data URL (~200 KB image)

# Tests replace: main_engine(prompt, history, model, **kw) -> str
main_engine: Callable[..., str] | None = None


def groups_dir() -> Path:
    env = os.environ.get("GROUPS_DIR", "").strip()
    if env:
        return Path(env)
    import agent_config

    return agent_config.storage_dir() / "groups"


def _slug(v: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (v or "").casefold()).strip("-")[:40]


def normalise(data: dict[str, Any]) -> dict[str, Any]:
    name = " ".join(str(data.get("name") or "").split())[:60]
    if not name:
        raise ValueError("Give the group a name.")
    known = {b["id"] for b in bots.list_bots()}
    members = []
    for m in data.get("members") or []:
        m = _slug(str(m))
        if m in known and m not in members:
            members.append(m)
    coord = _slug(str(data.get("coordinator") or MAIN))
    if coord != MAIN and coord not in members:
        coord = MAIN
    pic = str(data.get("picture") or "")
    if pic and not (PICTURE.fullmatch(pic) and len(pic) <= MAX_PICTURE):
        raise ValueError("That picture can't be used (PNG/JPEG/WebP up to ~200 KB).")
    color = str(data.get("color") or "#5b9dff")
    return {"id": _slug(str(data.get("id") or "")) or _slug(name) or uuid.uuid4().hex[:8], "name": name,
            "picture": pic, "color": color if bots.COLOR.fullmatch(color) else "#5b9dff",
            "avatar": str(data.get("avatar")) if data.get("avatar") in bots.AVATARS else "round",
            "purpose": str(data.get("purpose") or "").strip()[:1000], "members": members,
            "coordinator": coord, "created": float(data.get("created") or time.time())}


def _path(gid: str) -> Path:
    s = _slug(gid)
    if not s:
        raise ValueError("Bad group id.")
    return groups_dir() / f"{s}.json"


def list_groups() -> list[dict[str, Any]]:
    folder = groups_dir(); out = []
    for p in sorted(folder.glob("*.json")) if folder.is_dir() else []:
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            continue
    return sorted(out, key=lambda g: g.get("created", 0))


def get_group(gid: str) -> dict[str, Any] | None:
    p = _path(gid)
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None


def save_group(data: dict[str, Any]) -> dict[str, Any]:
    g = normalise(data)
    with _lock:
        groups_dir().mkdir(parents=True, exist_ok=True)
        if not data.get("id"):
            base, n = g["id"], 2
            while _path(g["id"]).exists():
                g["id"], n = f"{base}-{n}", n + 1
        else:
            old = get_group(g["id"])
            if old:
                g["created"] = old.get("created", g["created"])
        tmp = _path(g["id"]).with_suffix(".tmp")
        tmp.write_text(json.dumps(g, indent=2), encoding="utf-8")
        os.replace(tmp, _path(g["id"]))
    return g


def delete_group(gid: str) -> bool:
    with _lock:
        p = _path(gid)
        if not p.is_file():
            return False
        p.unlink()
    try:
        import chat_store

        chat_store.delete_session(SESSION_PREFIX + _slug(gid))
    except Exception:
        pass
    return True


def group_for_session(session: str) -> dict[str, Any] | None:
    s = str(session or "")
    return get_group(s[len(SESSION_PREFIX):]) if s.startswith(SESSION_PREFIX) else None


def _names(group: dict[str, Any]) -> dict[str, str]:
    """slugged name/id -> member id (plus Pedro_Agent)."""
    out = {"pedro": MAIN, "pedro-agent": MAIN, "pedro_agent": MAIN}
    for m in group["members"]:
        b = bots.get_bot(m)
        if b:
            out[b["id"]] = b["id"]; out[_slug(b["name"])] = b["id"]
            out[_slug(b["name"]).replace("-", "")] = b["id"]
    return out


def mentions(text: str, group: dict[str, Any]) -> list[str]:
    names = _names(group); found: list[str] = []
    for raw in re.findall(r"@([A-Za-z0-9_\-]+)", text or ""):
        key = _slug(raw)
        if key in {"all", "everyone"}:
            for m in [MAIN] + group["members"]:
                if m not in found:
                    found.append(m)
            continue
        mid = names.get(key) or names.get(key.replace("-", ""))
        if mid and mid not in found:
            found.append(mid)
    return found


def display(speaker: str) -> dict[str, Any]:
    if speaker == MAIN:
        return {"id": MAIN, "name": "Pedro_Agent", "color": "#5b6cff", "avatar": "round"}
    b = bots.get_bot(speaker) or {"id": speaker, "name": speaker, "color": "#5b6cff", "avatar": "round"}
    return {"id": b["id"], "name": b["name"], "color": b.get("color"), "avatar": b.get("avatar")}


def _room_prompt(group: dict[str, Any], speaker: str, transcript: list[str], coordinating: bool) -> str:
    roster = ", ".join(["@pedro (Pedro_Agent)"] + [f"@{m} ({display(m)['name']})" for m in group["members"]])
    lines = [f"[Group room '{group['name']}'. Purpose: {group['purpose'] or 'general'}. Members: {roster}.",
             f"You are {display(speaker)['name']}. Reply only as yourself, briefly."]
    if coordinating:
        lines.append("You coordinate this room: do your part, and if other members should handle parts, "
                     "@mention each one with their part. Don't @mention anyone otherwise.")
    lines.append("]\n\nConversation so far this turn:\n" + "\n".join(transcript))
    return "\n".join(lines)


def run_group(group: dict[str, Any], text: str, history: list[Any], emit: Callable[[dict], Any], *,
              model: str = "", store: Callable[[str, str, str], Any] | None = None, **kw: Any) -> list[tuple[str, str]]:
    """One room turn. Returns [(speaker, reply)]. emit gets 'speaker' events
    before each reply; store(session, role, text) saves tagged replies."""
    import gta5_agent

    session = SESSION_PREFIX + group["id"]
    queue = mentions(text, group)
    coordinating = not queue
    if coordinating:
        queue = [group["coordinator"]]
    transcript = [f"Pedro: {text}"]; done: list[tuple[str, str]] = []
    while queue and len(done) < MAX_SPEAKERS:
        speaker = queue.pop(0)
        emit({"event": "speaker", **display(speaker)})
        prompt = _room_prompt(group, speaker, transcript, coordinating and speaker == group["coordinator"] and not done)
        try:
            if speaker == MAIN:
                run = main_engine or gta5_agent.run_agent
                reply = run(prompt, history, model, **kw) or ""
            else:
                reply = bots.run_bot(bots.get_bot(speaker), prompt, history, model=model, **kw)
        except Exception as exc:
            reply = f"(couldn't answer: {exc})"
        done.append((speaker, reply))
        transcript.append(f"{display(speaker)['name']}: {reply}")
        emit({"event": "done", "text": reply, "speaker": speaker})
        if store and reply:
            store(session, "assistant", f"[[@{speaker}]] {reply}")
        if coordinating and len(done) == 1:   # coordinator hands work out by @mention
            for m in mentions(reply, group):
                if m != speaker and m not in queue and m not in [d[0] for d in done]:
                    queue.append(m)
    return done


def remove_bot(bot_id: str) -> int:
    """A deleted bot leaves every group; a coordinator falls back to Pedro_Agent."""
    gone, changed = _slug(bot_id), 0
    with _lock:
        for g in list_groups():
            if gone in g.get("members", []):
                g["members"] = [m for m in g["members"] if m != gone]
                if g.get("coordinator") == gone:
                    g["coordinator"] = MAIN
                tmp = _path(g["id"]).with_suffix(".tmp")
                tmp.write_text(json.dumps(g, indent=2), encoding="utf-8")
                os.replace(tmp, _path(g["id"]))
                changed += 1
    return changed
