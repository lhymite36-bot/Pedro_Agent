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


_CHAT_WORDS = re.compile(r"^(hi+|hey+|hello+|yo|sup|hola|good (morning|afternoon|evening|night)|thanks?( you)?|thank u|ty|ok(ay)?|cool|nice|great|lol|bye|see you|how are (you|u)( all| guys)?|what'?s up|wassup|gm|gn)\b", re.I)
_TASK_WORDS = re.compile(r"\b(make|create|build|write|draft|research|find|search|send|open|install|fix|plan|design|code|analy[sz]e|summari[sz]e|translate|compare|list|save|download|edit|generate|prepare|schedule|check|calculate|report|pdf|docx?|excel|presentation|email|whatsapp)\b", re.I)


def is_chitchat(text: str) -> bool:
    """Greetings / small talk get a quick natural reply, not the project loop."""
    t = re.sub(r"@[A-Za-z0-9_\-]+", "", text or "").strip(" !.?,")
    if not t:
        return True
    if _TASK_WORDS.search(t):
        return False
    return bool(_CHAT_WORDS.match(t)) and len(t.split()) <= 8


def for_display(text: str, group: dict[str, Any] | None = None) -> tuple[str, list[dict[str, str]]]:
    """Strip protocol markers (ASSIGN/DONE/BLOCKED/PROJECT DONE/ASK USER) from what people see.
    Returns (natural text, chips)."""
    chips: list[dict[str, str]] = []
    out: list[str] = []
    for line in str(text or "").splitlines():
        raw = line.strip().strip("*").strip()
        m = re.match(r"(?i)^ASSIGN\s+@?([A-Za-z0-9_\-]+)\s*\**\s*[:\-]\s*(.+)$", raw)
        if m:
            who = display(_slug(m.group(1)))["name"] if group is None or _slug(m.group(1)) in (group.get("members") or []) + [MAIN] else m.group(1)
            task = m.group(2).strip().rstrip(".")
            chips.append({"kind": "assign", "text": f"→ assigned to {who}"})
            out.append(f"{who}, could you {task[0].lower() + task[1:] if task else 'take this'}?")
            continue
        m = re.match(r"(?i)^PROJECT\s+(?:DONE|COMPLETE)\s*[:\-]?\s*(.*)$", raw)
        if m:
            chips.append({"kind": "done", "text": "✓ project complete"})
            if m.group(1):
                out.append(m.group(1))
            continue
        m = re.match(r"(?i)^(DONE|BLOCKED)\s*[:\-]\s*(.*)$", raw)
        if m:
            chips.append({"kind": "done" if m.group(1).upper() == "DONE" else "blocked",
                          "text": "✓ done" if m.group(1).upper() == "DONE" else "⚠ blocked"})
            if m.group(2):
                out.append(m.group(2))
            continue
        m = re.match(r"(?i)^ASK\s+USER\s*[:\-]\s*(.+)$", raw)
        if m:
            out.append(m.group(1))
            continue
        m = re.search(r"\b(DONE|BLOCKED)\s*:\s*", line)   # inline "… DONE: result"
        if m and not re.search(r"(?i)project\s*$", line[:m.start()]):
            ok = m.group(1) == "DONE"
            chips.append({"kind": "done" if ok else "blocked", "text": "✓ done" if ok else "⚠ blocked"})
            line = (line[:m.start()].rstrip(" .…") + (". " if line[:m.start()].strip() else "") + line[m.end():]).strip()
        out.append(line)
    clean = re.sub(r"\[\[@[^\]]*\]\]\s*", "", "\n".join(out)).strip()
    return re.sub(r"\n{3,}", "\n\n", clean), chips


def clean_row(row: dict[str, Any]) -> dict[str, Any]:
    """History row for the UI: speaker tag kept, protocol markers -> chips (old rows too)."""
    if row.get("role") != "assistant":
        return row
    text = str(row.get("text") or "")
    m = TAG.match(text)
    body = text[m.end():] if m else text
    chips = [{"kind": "done" if "✓" in c else "assign" if "→" in c else "blocked", "text": c}
             for c in re.findall(r"\[\[chip:([^\]]+)\]\]", body)]
    body = re.sub(r"\s*\[\[chip:[^\]]+\]\]", "", body)
    shown, more = for_display(body)
    return {**row, "text": (m.group(0) if m else "") + shown, "chips": chips + more}


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


DEFAULT_LIMITS = {"max_turns": 40, "max_minutes": 30}
ASSIGN = re.compile(r"^\s*\**\s*ASSIGN\s+@?([A-Za-z0-9_\-]+)\s*\**\s*[:\-]\s*(.+)$", re.I | re.M)
DONE_RE = re.compile(r"^\s*\**\s*PROJECT\s+(DONE|COMPLETE)\b", re.I | re.M)
ASK_RE = re.compile(r"^\s*\**\s*ASK\s+USER\s*[:\-]\s*(.+)$", re.I | re.M)


def limits() -> dict[str, Any]:
    try:
        import rules

        return rules.section("groups", DEFAULT_LIMITS)
    except Exception:
        return dict(DEFAULT_LIMITS)


def _roster(group: dict[str, Any]) -> str:
    return ", ".join(["@pedro (Pedro_Agent)"] + [f"@{m} ({display(m)['name']})" for m in group["members"]])


def _tail(transcript: list[str], n: int = 14, cap: int = 1500) -> str:
    return "\n".join(t if len(t) <= cap else t[:cap] + " …" for t in transcript[-n:])


def _room_prompt(group: dict[str, Any], speaker: str, transcript: list[str], coordinating: bool) -> str:
    lines = [f"[Group room '{group['name']}'. Purpose: {group['purpose'] or 'general'}. Members: {_roster(group)}.",
             f"You are {display(speaker)['name']}. Reply only as yourself, briefly."]
    lines.append("]\n\nConversation so far this turn:\n" + _tail(transcript))
    return "\n".join(lines)


def _leader_prompt(group: dict[str, Any], leader: str, transcript: list[str]) -> str:
    return (f"[Group project room '{group['name']}'. Purpose: {group['purpose'] or 'general'}. Members: {_roster(group)}.\n"
            f"You are {display(leader)['name']}, the LEADER. Run the project to the end without asking the user unless you must.\n"
            "Each reply: briefly review the latest result (check it is real and correct), then give EXACTLY ONE directive line:\n"
            "  ASSIGN @member: <one concrete subtask with everything they need>   (you may assign @pedro or yourself too)\n"
            "  PROJECT DONE: <final summary for the user, with the full path of every file made>\n"
            "  ASK USER: <question>   (only if truly blocked, e.g. missing info or a needed yes)\n"
            "As leader you plan, delegate and review: do NOT do the members' work yourself in this turn. Give each subtask to "
            "the member whose purpose fits it best, in order (e.g. research before writing). Only report results that appear in the "
            "project log; never claim a member did something they haven't. "
            "Only declare PROJECT DONE after the work is finished and verified (files exist, content right). "
            "Never send, delete or buy anything unless the user asked.]\n\nProject log:\n" + _tail(transcript))


def _worker_prompt(group: dict[str, Any], worker: str, task: str, transcript: list[str]) -> str:
    return (f"[Group project room '{group['name']}'. You are {display(worker)['name']}, a team MEMBER (not the leader: "
            "never write ASSIGN, never review others). The leader assigned you this subtask:\n"
            f"{task}\nDo it for real with your tools (start_task, create_task_plan, verify_screen, make_document, files…). "
            "Save files where the task says, else on the Desktop, and give full paths. "
            "End with a line starting 'DONE:' and the result, or 'BLOCKED:' and why. Never write 'PROJECT DONE' (only the leader does).]\n\nRecent project log:\n"
            + _tail(transcript, 8))


def _direct_prompt(group: dict[str, Any], who: str, text: str, transcript: list[str]) -> str:
    return (f"[Group room '{group['name']}'. The user addressed YOU ({display(who)['name']}) directly with @mention. "
            "Answer or do it yourself with your tools; don't hand it to anyone else. "
            "Save files where asked, else on the Desktop, and give full paths.]\n\nUser: " + text +
            "\n\nRecent room log:\n" + _tail(transcript[:-1] or [], 6))


def _run_one(speaker: str, prompt: str, history: list[Any], model: str, kw: dict[str, Any]) -> str:
    import agent_core

    if speaker == MAIN:
        run = main_engine or agent_core.run_agent
        return run(prompt, history, model, **kw) or ""
    bot = bots.get_bot(speaker)
    if bot is None:
        return f"(@{speaker} isn't a bot any more)"
    # members work from the prompt (task + recent log), not the whole room history, so they don't act as leader
    return bots.run_bot(bot, prompt, [], model=model, extra_tools=GROUP_TOOLS, **kw)


GROUP_TOOLS = {"start_task", "create_task_plan", "complete_plan_step", "revise_task_plan", "verify_screen",
               "capture_screenshot_file", "make_document", "launch_any_app", "take_screenshot", "write_text_file",
               "open_website", "list_task_routines", "get_task_routine"}


def _pending_confirmation() -> str:
    try:
        import confirm_action

        p = confirm_action.pending()
        return p.get("label", "") if p else ""
    except Exception:
        return ""


def run_group(group: dict[str, Any], text: str, history: list[Any], emit: Callable[[dict], Any], *,
              model: str = "", store: Callable[[str, str, str], Any] | None = None,
              cancel_event: Any = None, now: Callable[[], float] = time.time, **kw: Any) -> list[tuple[str, str]]:
    """@mentions -> those members answer once. Otherwise the leader runs the project:
    plan -> ASSIGN -> member works -> leader reviews -> ... -> PROJECT DONE (+ summary)."""
    session = SESSION_PREFIX + group["id"]
    done: list[tuple[str, str]] = []
    transcript = [f"User: {text}"]
    kw = dict(kw)
    if cancel_event is not None:
        kw["cancel_event"] = cancel_event
    on_event = kw.get("on_event")

    def say(speaker: str, prompt: str, status: str) -> str:
        emit({"event": "speaker", **display(speaker)})
        emit({"event": "step", "label": status, "name": ""})
        emit({"event": "group_status", "who": display(speaker)["name"], "doing": status})
        call_kw = dict(kw)
        call_kw["on_text"] = lambda chunk: emit({"event": "token", "text": chunk})
        try:
            reply = _run_one(speaker, prompt, history, model, call_kw)
        except Exception as exc:
            reply = f"(couldn't answer: {exc})"
        done.append((speaker, reply))
        transcript.append(f"{display(speaker)['name']}: {reply}")
        shown, chips = for_display(reply, group)
        emit({"event": "done", "text": shown, "speaker": speaker, "chips": chips})
        if store and reply:
            store(session, "assistant", f"[[@{speaker}]] {shown}" + "".join(f" [[chip:{c['text']}]]" for c in chips))
        return reply

    def stopped() -> bool:
        return bool(cancel_event is not None and cancel_event.is_set())

    direct = mentions(text, group)
    if direct:
        everyone = bool(re.search(r"@(all|everyone)\b", text, re.I))
        for speaker in direct[:MAX_SPEAKERS]:
            if stopped():
                break
            if everyone:
                prompt = _room_prompt(group, speaker, transcript, False)
            else:   # the user picked this member: it handles the message itself, with its tools
                prompt = _direct_prompt(group, speaker, text, transcript)
            say(speaker, prompt, f"{display(speaker)['name']} is working on your message")
            if _pending_confirmation():
                _notice(emit, store, session, f"Waiting for your yes to {_pending_confirmation()}. Reply 'yes' to continue.")
                break
        return done

    if is_chitchat(text):   # small talk: the leader just answers, naturally and briefly
        say(group["coordinator"], _room_prompt(group, group["coordinator"], transcript, False)
            + "\n(This is small talk. Reply in one or two friendly sentences, no directives, don't assign anyone.)",
            f"{display(group['coordinator'])['name']} is replying")
        return done

    lim = limits()
    max_turns, deadline = int(lim.get("max_turns") or 40), now() + float(lim.get("max_minutes") or 30) * 60
    leader = group["coordinator"]
    turns = 0
    while True:
        if stopped():
            _notice(emit, store, session, "Stopped. Say 'continue' to pick up where we left off.")
            break
        if turns >= max_turns or now() > deadline:
            _notice(emit, store, session, f"Paused after {turns} turns (safety limit in rules.yaml › groups). "
                                          "Say 'continue' to keep going.")
            break
        lead = say(leader, _leader_prompt(group, leader, transcript), f"{display(leader)['name']} is reviewing and planning")
        turns += 1
        if DONE_RE.search(lead):
            emit({"event": "group_status", "who": display(leader)["name"], "doing": "Project complete"})
            break
        ask = ASK_RE.search(lead)
        waiting = _pending_confirmation()
        if ask or waiting or stopped():
            if waiting:
                _notice(emit, store, session, f"Waiting for your yes to {waiting}. Reply 'yes' to continue.")
            break
        m = ASSIGN.search(lead)
        if m:
            who = _names(group).get(_slug(m.group(1))) or _names(group).get(_slug(m.group(1)).replace("-", ""))
            task = m.group(2).strip()
        else:
            named = [x for x in mentions(lead, group) if x != leader]
            if not named:   # a plain answer (no directive, nobody handed work): the turn is over
                break
            who, task = named[0], lead.strip()
        if not who:
            transcript.append(f"System: @{m.group(1)} is not in this group. Members: {_roster(group)}.")
            continue
        say(who, _worker_prompt(group, who, task, transcript), f"{display(who)['name']} is working on: {task[:80]}")
        turns += 1
        waiting = _pending_confirmation()
        if waiting:
            _notice(emit, store, session, f"Waiting for your yes to {waiting}. Reply 'yes' to continue.")
            break
    return done


def _notice(emit: Callable[[dict], Any], store: Any, session: str, text: str) -> None:
    emit({"event": "group_status", "who": "", "doing": text})
    emit({"event": "speaker", **display(MAIN), "name": "Room"})
    emit({"event": "done", "text": text, "speaker": MAIN})
    if store:
        store(session, "assistant", f"[[@{MAIN}]] _{text}_")

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
