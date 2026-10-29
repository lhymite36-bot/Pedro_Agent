"""1.6.1 WhatsApp for Ped Bot, linked like WhatsApp Web (QR code), through the Baileys bridge in whatsapp_bridge/.

Safety rules (Pedro's):
- Ped Bot only takes COMMANDS from Pedro: the app, Telegram, his WhatsApp "Message yourself" chat, or numbers he
  put on the allowlist. It never answers other people's messages on its own.
- Sending to anyone else shows a confirm card (recipient + text) while "Ask before sending" is on (default on).
- Rate limits (gap + jitter, per minute, per day) lower the ban risk. WhatsApp can still ban unofficial clients.
- The login session is stored in storage/whatsapp/session (never in git).
"""

from __future__ import annotations

import json
import os
import random
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable

import rules

DEFAULTS: dict[str, Any] = {
    "enabled": False,               # turned on by "Connect WhatsApp"
    "ask_before_sending": True,     # confirm card before messaging anyone but yourself
    "allowlist": [],                # extra numbers (digits) whose messages count as Pedro's commands
    "min_gap_seconds": 4,           # at least this long between sends (+1-3 s random)
    "per_minute": 10,
    "per_day": 250,
    "reply_prefix": "🤖 ",          # marks Ped Bot's replies in your self-chat
}
BAN_NOTICE = ("WhatsApp doesn't officially allow automated accounts: heavy or bulk sending can get your number banned. "
              "Ped Bot rate-limits sends, but use it gently.")
SEND_TOOLS = {"whatsapp_send_message", "whatsapp_send_file", "whatsapp_react", "whatsapp_create_group"}

bridge_factory: Callable[[], Any] | None = None   # tests swap the Node process for a fake
answer_handler: Callable[[str], str] | None = None
history_hook: Callable[[str, str], None] | None = None


def settings() -> dict[str, Any]:
    cfg = dict(DEFAULTS)
    cfg.update(rules.section("whatsapp", DEFAULTS) or {})
    try:
        cfg.update(json.loads(_overlay().read_text(encoding="utf-8")))
    except Exception:
        pass
    return cfg


def save_settings(**values: Any) -> dict[str, Any]:
    try:
        data = json.loads(_overlay().read_text(encoding="utf-8"))
    except Exception:
        data = {}
    if "allowlist" in values:
        values["allowlist"] = [d for d in (re.sub(r"\D", "", str(x)) for x in values["allowlist"] or []) if len(d) >= 8]
    for k in ("ask_before_sending", "enabled"):
        if k in values:
            values[k] = bool(values[k])
    data.update({k: v for k, v in values.items() if k in DEFAULTS})
    _overlay().parent.mkdir(parents=True, exist_ok=True)
    _overlay().write_text(json.dumps(data, indent=2), encoding="utf-8")
    return settings()


def _dir() -> Path:
    import agent_config
    return Path(agent_config.storage_dir()) / "whatsapp"


def _overlay() -> Path:
    return _dir() / "settings.json"


def _node() -> str:
    import agent_config
    for p in (Path(agent_config.APP_DIR) / "node" / "node.exe", Path(agent_config.APP_DIR) / "node" / "bin" / "node"):
        if p.is_file():
            return str(p)
    return shutil.which("node") or ""


def _script() -> Path:
    import agent_config
    return Path(agent_config.APP_DIR) / "whatsapp_bridge" / "bridge.mjs"


# ---------------------------------------------------------------- rate limit
class RateLimiter:
    def __init__(self, clock: Callable[[], float] = time.time, sleep: Callable[[float], None] = time.sleep):
        self.clock, self.sleep = clock, sleep
        self.sent: list[float] = []
        self.lock = threading.Lock()

    def wait_turn(self) -> str:
        """Blocks for the gap; returns an error text when the minute/day cap is hit."""
        cfg = settings()
        with self.lock:
            now = self.clock()
            self.sent = [t for t in self.sent if now - t < 86400]
            if len(self.sent) >= int(cfg["per_day"]):
                return f"Daily WhatsApp limit reached ({cfg['per_day']} sends) to protect your number. Try tomorrow."
            if len([t for t in self.sent if now - t < 60]) >= int(cfg["per_minute"]):
                return f"Slow down: {cfg['per_minute']} WhatsApp sends a minute is the limit. Try again in a minute."
            gap = float(cfg["min_gap_seconds"]) + random.uniform(1, 3)
            if self.sent and now - self.sent[-1] < gap:
                self.sleep(gap - (now - self.sent[-1]))
            self.sent.append(self.clock())
        return ""


limiter = RateLimiter()


# ---------------------------------------------------------------- bridge process
class NodeBridge:
    def __init__(self, on_event: Callable[[dict[str, Any]], None]):
        self.on_event = on_event
        self.proc: subprocess.Popen | None = None
        self.waiting: dict[int, tuple[threading.Event, dict[str, Any]]] = {}
        self.seq = 0
        self.lock = threading.Lock()

    def start(self) -> None:
        node, script = _node(), _script()
        if not node:
            raise RuntimeError("Node.js was not found (the installer ships it in the node folder).")
        if not script.is_file():
            raise RuntimeError("whatsapp_bridge/bridge.mjs is missing. Reinstall Ped Bot.")
        flags: dict[str, Any] = {}
        if os.name == "nt":
            flags["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self.proc = subprocess.Popen([node, str(script), "--auth", str(_dir() / "session"), "--media", str(_dir() / "media")],
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                     text=True, encoding="utf-8", errors="replace", bufsize=1, cwd=str(script.parent), **flags)
        self.errors: list[str] = []
        threading.Thread(target=self._read, daemon=True, name="wa-read").start()
        threading.Thread(target=self._read_err, daemon=True, name="wa-err").start()

    def _read_err(self) -> None:
        """1.6.2: keep the bridge's error output so Settings can show why it stopped."""
        proc = self.proc
        for line in proc.stderr:   # type: ignore[union-attr]
            line = line.rstrip()
            if line:
                self.errors.append(line[:400])
                del self.errors[:-40]

    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def _read(self) -> None:
        proc = self.proc
        for line in proc.stdout:   # type: ignore[union-attr]
            try:
                msg = json.loads(line)
            except Exception:
                continue
            if "id" in msg and msg["id"] in self.waiting:
                ev, box = self.waiting.pop(msg["id"])
                box.update(msg)
                ev.set()
            elif "event" in msg:
                self.on_event(msg)
        try:
            proc.wait(timeout=3)   # type: ignore[union-attr]
        except Exception:
            pass
        time.sleep(0.2)   # let the stderr reader catch up
        self.on_event({"event": "status", "state": "stopped", "code": getattr(proc, "returncode", None),
                       "stderr": "\n".join(getattr(self, "errors", [])[-12:])})

    def request(self, cmd: str, args: dict[str, Any] | None = None, timeout: float = 60) -> dict[str, Any]:
        if not self.alive():
            raise RuntimeError("WhatsApp is not running. Open Settings > Connections > Connect WhatsApp.")
        with self.lock:
            self.seq += 1
            rid = self.seq
            ev, box = threading.Event(), {}
            self.waiting[rid] = (ev, box)
            self.proc.stdin.write(json.dumps({"id": rid, "cmd": cmd, "args": args or {}}) + "\n")   # type: ignore[union-attr]
            self.proc.stdin.flush()   # type: ignore[union-attr]
        if not ev.wait(timeout):
            self.waiting.pop(rid, None)
            raise RuntimeError(f"WhatsApp did not answer ({cmd}).")
        if not box.get("ok"):
            raise RuntimeError(str(box.get("error") or "WhatsApp error"))
        return box.get("result") or {}

    def stop(self) -> None:
        p = self.proc
        self.proc = None
        if p is not None:
            try:
                p.stdin.close()   # type: ignore[union-attr]
                p.wait(timeout=5)
            except Exception:
                try:
                    p.kill()
                except Exception:
                    pass


# ---------------------------------------------------------------- state
_bridge: Any = None
_status: dict[str, Any] = {"state": "off", "qr": "", "me": None, "error": ""}
_watch: threading.Thread | None = None
_stop = threading.Event()


def status() -> dict[str, Any]:
    s = dict(_status)
    cfg = settings()
    s.update(enabled=bool(cfg["enabled"]), ask_before_sending=bool(cfg["ask_before_sending"]),
             allowlist=list(cfg["allowlist"]), notice=BAN_NOTICE, node=bool(_node()) or bridge_factory is not None)
    if s.get("qr"):
        try:
            import remote_access
            s["qr_svg"] = remote_access.qr_svg(s["qr"])
        except Exception:
            s["qr_svg"] = ""
    return s


def _on_event(ev: dict[str, Any]) -> None:
    kind = ev.get("event")
    if kind == "qr":
        _status.update(state="qr", qr=str(ev.get("qr") or ""), error="")
    elif kind == "status":
        st = str(ev.get("state") or "")
        err = str(ev.get("error") or "")
        if st == "stopped" and _bridge is not None and getattr(_bridge, "proc", 1) is not None:
            # 1.6.2: the bridge crashed (not a Disconnect): show why, and repair missing packages once
            tail = str(ev.get("stderr") or "")
            err = explain_crash(tail, ev.get("code"))
            st = "error"
            if broken_modules(tail):
                threading.Thread(target=repair_and_restart, daemon=True, name="wa-repair").start()
                err += " Repairing the WhatsApp packages now (npm ci)…"
        _status.update(state=st, error=err)
        if st == "connected":
            _status.update(qr="", me=ev.get("me"))
    elif kind == "message":
        threading.Thread(target=handle_incoming, args=(ev,), daemon=True, name="wa-msg").start()


def broken_modules(stderr: str) -> bool:
    return bool(re.search(r"ERR_MODULE_NOT_FOUND|Cannot find (module|package)|MODULE_NOT_FOUND", stderr or ""))


def explain_crash(stderr: str, code: Any = None) -> str:
    lines = [l for l in (stderr or "").splitlines() if l.strip()]
    key = next((l for l in lines if re.search(r"^\s*\w*Error\b|Cannot find", l)), "") or \
        next((l for l in lines if re.search(r"Error|error:|ERR_", l)), lines[-1] if lines else "")
    head = "The WhatsApp bridge stopped" + (f" (exit code {code})" if code not in (None, 0) else "") + "."
    return f"{head} {key.strip()[:300]}" if key else head + " No error text was printed."


_repairing = threading.Lock()
_repaired_once = {"done": False}


def npm_cmd() -> list[str]:
    """Bundled npm (node/node_modules/npm) or the system one."""
    node = _node()
    if node:
        cli = Path(node).parent / "node_modules" / "npm" / "bin" / "npm-cli.js"
        if cli.is_file():
            return [node, str(cli)]
    npm = shutil.which("npm") or shutil.which("npm.cmd")
    return [npm] if npm else []


def repair_modules(runner: Callable[..., Any] = subprocess.run) -> tuple[bool, str]:
    cmd = npm_cmd()
    if not cmd:
        return False, "npm was not found, so the WhatsApp packages can't be repaired. Reinstall Ped Bot."
    flags: dict[str, Any] = {}
    if os.name == "nt":
        flags["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        r = runner([*cmd, "ci", "--omit=dev", "--no-audit", "--no-fund"], cwd=str(_script().parent),
                   capture_output=True, text=True, timeout=600, **flags)
    except Exception as exc:
        return False, f"npm ci failed: {exc}"
    if getattr(r, "returncode", 1) != 0:
        tail = (str(getattr(r, "stderr", "")) or str(getattr(r, "stdout", ""))).strip().splitlines()[-3:]
        return False, "npm ci failed: " + " ".join(tail)[:300]
    return True, "WhatsApp packages repaired."


def repair_and_restart() -> None:
    if _repaired_once["done"] or not _repairing.acquire(blocking=False):
        return
    try:
        _repaired_once["done"] = True
        _status.update(state="repairing", error="Repairing the WhatsApp packages (npm ci)… this needs internet and can take a minute.")
        ok, msg = repair_modules()
        if not ok:
            _status.update(state="error", error=msg)
            return
        global _bridge
        _bridge = None
        connect()
    finally:
        _repairing.release()


def connect() -> dict[str, Any]:
    """Start (or restart) the bridge. A new device shows a QR in Settings."""
    global _bridge, _watch
    save_settings(enabled=True)
    if _bridge is None or not _bridge.alive():
        _bridge = (bridge_factory or (lambda: NodeBridge(_on_event)))()
        if bridge_factory is not None and hasattr(_bridge, "on_event"):
            _bridge.on_event = _on_event
        try:
            _bridge.start()
        except Exception as exc:
            _status.update(state="error", error=str(exc))
            return {"ok": False, "error": str(exc), **status()}
        _status.update(state="starting", error="")
        for _ in range(0 if bridge_factory else 15):   # 1.6.2: an instant crash is reported by this click, not silently
            time.sleep(0.1)
            if _status.get("state") != "starting":
                break
    if _watch is None or not _watch.is_alive():
        _stop.clear()
        _watch = threading.Thread(target=_watchdog, daemon=True, name="wa-watchdog")
        _watch.start()
    return {"ok": True, **status()}


def _watchdog() -> None:
    """Auto-reconnect: Baileys reconnects itself; this restarts the Node process if it dies."""
    wait = 5
    while not _stop.wait(wait):
        if not settings()["enabled"]:
            return
        if _status.get("state") == "repairing":
            continue
        if _bridge is None or not _bridge.alive():
            print("WhatsApp: bridge stopped, starting it again.", flush=True)
            connect()
            wait = min(wait * 2, 120)
        else:
            wait = 5


def disconnect(logout: bool = False) -> dict[str, Any]:
    """Stop the bridge. logout=True also unlinks this PC from WhatsApp and deletes the local session."""
    global _bridge
    save_settings(enabled=False)
    _stop.set()
    b = _bridge
    if b is not None and b.alive():
        if logout:
            try:
                b.request("logout", timeout=15)
            except Exception:
                pass
        b.stop()
    _bridge = None
    if logout:
        shutil.rmtree(_dir() / "session", ignore_errors=True)
    _status.update(state="off", qr="", me=None if logout else _status.get("me"))
    return {"ok": True, **status()}


def autostart() -> None:
    if settings()["enabled"] and (_dir() / "session" / "creds.json").is_file():
        connect()


def call(cmd: str, args: dict[str, Any] | None = None, timeout: float = 60) -> dict[str, Any]:
    if _bridge is None or not _bridge.alive():
        raise RuntimeError("WhatsApp is not connected. Open Settings > Connections > Connect WhatsApp and scan the QR code.")
    return _bridge.request(cmd, args, timeout)


# ---------------------------------------------------------------- incoming (commands from Pedro only)
FILE_LINE = re.compile(r"^\s*SEND_FILE:\s*(.+?)\s*$", re.M)


def is_command_source(ev: dict[str, Any]) -> bool:
    """Only Pedro's own 'Message yourself' chat or allowlisted numbers. Never other contacts, never groups."""
    chat = str(ev.get("chat") or "")
    if ev.get("self_chat") and ev.get("from_me"):
        return True
    if chat.endswith("@g.us") or ev.get("from_me"):
        return False
    digits = re.sub(r"\D", "", chat.split("@")[0])
    return bool(digits) and digits in set(settings()["allowlist"])


def handle_incoming(ev: dict[str, Any]) -> None:
    if not is_command_source(ev):
        return   # other people's messages are only stored for reading; never answered
    text = str(ev.get("text") or "").strip()
    if ev.get("kind") in ("voice", "audio") and ev.get("media_path"):
        try:
            import remote_bridge
            text = remote_bridge._transcribe_voice(Path(ev["media_path"]).read_bytes())
            text = f"[voice note] {text}"
        except Exception as exc:
            _reply(ev["chat"], f"I couldn't understand that voice note ({exc}).")
            return
    if not text or text.startswith(settings()["reply_prefix"].strip() or "\u0000"):
        return
    if history_hook:
        history_hook("user", text)
    try:
        reply = answer_handler(text) if answer_handler else _default_answer(text)
    except Exception as exc:
        reply = f"That failed: {exc}"
    if history_hook:
        history_hook("assistant", reply)
    _reply(ev["chat"], str(reply or ""))


def _default_answer(text: str) -> str:
    import remote_bridge
    return remote_bridge._answer(text)


def _reply(chat: str, reply: str) -> None:
    files = [p.strip().strip('"') for p in FILE_LINE.findall(reply)]
    body = FILE_LINE.sub("", reply).strip()
    try:
        if body:
            call("send_text", {"to": chat, "text": settings()["reply_prefix"] + body[:4000]})
        for f in files[:5]:
            if Path(f).is_file():
                call("send_file", {"to": chat, "path": f}, timeout=180)
    except Exception as exc:
        print(f"WhatsApp: reply failed: {exc}", flush=True)


# ---------------------------------------------------------------- tools
def _ok(message: str, **extra: Any) -> dict[str, Any]:
    return {"ok": True, "message": message, **extra}


def _err(message: str) -> dict[str, Any]:
    return {"ok": False, "error": message}


def _guard(fn: Callable[..., dict[str, Any]]) -> Callable[..., dict[str, Any]]:
    def run(**kw: Any) -> dict[str, Any]:
        try:
            return fn(**kw)
        except Exception as exc:
            return _err(str(exc))
    run.__name__ = fn.__name__
    run.__doc__ = fn.__doc__
    return run


def _limited(cmd: str, args: dict[str, Any], timeout: float = 60) -> dict[str, Any]:
    stop = limiter.wait_turn()
    if stop:
        raise RuntimeError(stop)
    return call(cmd, args, timeout)


@_guard
def whatsapp_status() -> dict[str, Any]:
    s = status()
    s.pop("qr_svg", None); s.pop("qr", None)
    return _ok(f"WhatsApp is {s['state']}.", **s)


@_guard
def whatsapp_list_chats(limit: int = 20) -> dict[str, Any]:
    r = call("list_chats", {"limit": max(1, min(100, int(limit or 20)))})
    lines = [f"- {c['name']}{' (group)' if c['group'] else ''}: {c['preview']}" for c in r["chats"]]
    return _ok("\n".join(lines) or "No chats synced yet.", chats=r["chats"])


@_guard
def whatsapp_read_chat(chat: str, limit: int = 30) -> dict[str, Any]:
    r = call("read_chat", {"chat": chat, "limit": max(1, min(200, int(limit or 30)))})
    lines = [f"[{time.strftime('%d %b %H:%M', time.localtime(m['ts']))}] {m['sender_name']}: "
             f"{m['text'] or '[' + m['kind'] + ']'} (id {m['id']})" for m in r["messages"]]
    return _ok(f"{r['name']} - last {len(lines)} messages:\n" + "\n".join(lines) if lines else
               f"No messages from {r['name']} are stored yet (only messages since linking, plus recent sync).",
               chat=r["chat"], messages=r["messages"])


@_guard
def whatsapp_search_contacts(query: str) -> dict[str, Any]:
    r = call("search_contacts", {"query": query})
    lines = [f"- {x['name']} ({x['id']}){' group' if x['group'] else ''}" for x in r["results"]]
    return _ok("\n".join(lines) or f"No contact matches {query!r}.", results=r["results"])


@_guard
def whatsapp_send_message(to: str, text: str, reply_to: str = "") -> dict[str, Any]:
    if not str(text or "").strip():
        return _err("Say what to send.")
    r = _limited("send_text", {"to": to, "text": text, "reply_to": reply_to or None})
    return _ok(f"Sent on WhatsApp to {to} (message id {r.get('id')}).", **r)


@_guard
def whatsapp_send_file(to: str, path: str, caption: str = "", kind: str = "auto", reply_to: str = "") -> dict[str, Any]:
    if not Path(str(path)).is_file():
        return _err(f"File not found: {path}")
    r = _limited("send_file", {"to": to, "path": str(path), "caption": caption, "kind": kind or "auto", "reply_to": reply_to or None}, 300)
    return _ok(f"Sent {Path(path).name} on WhatsApp to {to}.", **r)


@_guard
def whatsapp_react(chat: str, message_id: str, emoji: str = "👍") -> dict[str, Any]:
    r = _limited("react", {"chat": chat, "msg_id": message_id, "emoji": emoji})
    return _ok(f"Reacted {emoji} in {chat}.", **r)


@_guard
def whatsapp_mark_read(chat: str) -> dict[str, Any]:
    r = call("mark_read", {"chat": chat})
    return _ok(f"Marked {r.get('marked', 0)} messages as read in {chat}.", **r)


@_guard
def whatsapp_create_group(name: str, participants: list[str]) -> dict[str, Any]:
    if not participants:
        return _err("Say who to add.")
    r = _limited("create_group", {"name": name, "participants": list(participants)})
    return _ok(f"Created the WhatsApp group {r.get('name')} with {r.get('participants')} people.", **r)


@_guard
def whatsapp_group_info(chat: str) -> dict[str, Any]:
    r = call("group_info", {"chat": chat})
    return _ok(f"{r['name']}: {len(r['participants'])} members.", **r)


@_guard
def whatsapp_download_media(chat: str, message_id: str) -> dict[str, Any]:
    r = call("download_media", {"chat": chat, "msg_id": message_id}, 180)
    return _ok(f"Saved to {r['path']}.", **r)


_S = {"type": "string"}
DECLARATIONS = [
    {"name": "whatsapp_status", "description": "Is WhatsApp (linked by QR) connected? Read-only.",
     "parameters": {"type": "object", "properties": {}}},
    {"name": "whatsapp_list_chats", "description": "Recent WhatsApp chats and groups with a preview. Read-only.",
     "parameters": {"type": "object", "properties": {"limit": {"type": "integer"}}}},
    {"name": "whatsapp_read_chat", "description": "Read recent messages of a WhatsApp chat (name, number, 'me' or chat id) to answer or summarize. Read-only. Message ids are shown for replies/reactions.",
     "parameters": {"type": "object", "properties": {"chat": _S, "limit": {"type": "integer"}}, "required": ["chat"]}},
    {"name": "whatsapp_search_contacts", "description": "Find WhatsApp contacts or groups by name or number. Read-only.",
     "parameters": {"type": "object", "properties": {"query": _S}, "required": ["query"]}},
    {"name": "whatsapp_send_message", "description": "Send a WhatsApp text to a contact, group, number (with country code) or 'me'. reply_to = a message id to quote. Pedro confirms first.",
     "parameters": {"type": "object", "properties": {"to": _S, "text": _S, "reply_to": _S}, "required": ["to", "text"]}},
    {"name": "whatsapp_send_file", "description": "Send a file, photo, video, audio or voice note (kind: auto|image|video|document|audio|voice; voice wants .ogg opus) on WhatsApp. Pedro confirms first.",
     "parameters": {"type": "object", "properties": {"to": _S, "path": _S, "caption": _S, "kind": _S, "reply_to": _S}, "required": ["to", "path"]}},
    {"name": "whatsapp_react", "description": "React to a WhatsApp message with an emoji (empty emoji removes it).",
     "parameters": {"type": "object", "properties": {"chat": _S, "message_id": _S, "emoji": _S}, "required": ["chat", "message_id"]}},
    {"name": "whatsapp_mark_read", "description": "Mark a WhatsApp chat's recent messages as read.",
     "parameters": {"type": "object", "properties": {"chat": _S}, "required": ["chat"]}},
    {"name": "whatsapp_create_group", "description": "Create a WhatsApp group with these people (names or numbers). Pedro confirms first.",
     "parameters": {"type": "object", "properties": {"name": _S, "participants": {"type": "array", "items": _S}}, "required": ["name", "participants"]}},
    {"name": "whatsapp_group_info", "description": "Members and description of a WhatsApp group. Read-only.",
     "parameters": {"type": "object", "properties": {"chat": _S}, "required": ["chat"]}},
    {"name": "whatsapp_download_media", "description": "Save a photo/video/voice/document from a WhatsApp message to the PC and return its path.",
     "parameters": {"type": "object", "properties": {"chat": _S, "message_id": _S}, "required": ["chat", "message_id"]}},
]
TOOLS = {d["name"]: globals()[d["name"]] for d in DECLARATIONS}


def _is_self(to: Any) -> bool:
    t = str(to or "").strip().casefold()
    if t in {"me", "myself", "self", "message yourself"}:
        return True
    mine = re.sub(r"\D", "", str((_status.get("me") or {}).get("id") or "").split(":")[0].split("@")[0])
    return bool(mine) and re.sub(r"\D", "", t.split("@")[0]) == mine


def needs_confirm(name: str, arguments: dict[str, Any]) -> bool:
    """Sending tools ask first unless 'Ask before sending' is off or it only goes to Pedro's own chat."""
    if name not in SEND_TOOLS:
        return False
    if not settings()["ask_before_sending"]:
        return False
    target = arguments.get("to") or arguments.get("chat")
    return not (name != "whatsapp_create_group" and _is_self(target))


def label(name: str, a: dict[str, Any]) -> str:
    to = a.get("to") or a.get("chat") or "that chat"
    if name == "whatsapp_send_message":
        return f"send on WhatsApp to {to}: \"{' '.join(str(a.get('text') or '').split())[:300]}\""
    if name == "whatsapp_send_file":
        cap = f" with caption \"{str(a.get('caption'))[:120]}\"" if a.get("caption") else ""
        return f"send {Path(str(a.get('path') or 'a file')).name} on WhatsApp to {to}{cap}"
    if name == "whatsapp_react":
        return f"react {a.get('emoji') or '👍'} on WhatsApp in {to}"
    return f"create the WhatsApp group '{a.get('name')}' with {', '.join(map(str, a.get('participants') or []))}"
