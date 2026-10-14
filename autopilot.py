"""Autopilot watchers. autopilot.yaml lists watchers (gmail, telegram, folder,
url); when one fires, its prompt runs on the agent (or a named bot) in the
background. These runs are unattended: anything in rules.yaml confirm
categories is NOT done - it waits for your yes (reply yes in Telegram or the
chat app). Results are sent to your phone when notify is true.

The first check of each watcher only records a baseline, so old mail and
existing files do not fire.
"""

from __future__ import annotations

import email
import email.header
import fnmatch
import hashlib
import imaplib
import json
import os
import re
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any, Callable

TYPES = ("gmail", "telegram", "folder", "url")
EXAMPLE = """# Autopilot: things the agent watches and what it does when they change.
# Runs while the chat app is open (or say "start autopilot" in any mode).
# Risky actions (rules.yaml confirm categories) wait for your yes.
enabled: false
check_every_seconds: 60
notify: true                  # send the result to Telegram/Discord when set up
watchers:
  - name: new-downloads
    type: folder
    path: ~/Downloads
    pattern: "*.pdf"
    prompt: "A new PDF arrived: {path}. If it is an invoice, move it to ~/Documents/Invoices."
  # - name: boss-mail
  #   type: gmail               # uses GMAIL_ADDRESS + GMAIL_APP_PASSWORD (IMAP, read-only peek)
  #   from: boss@example.com
  #   subject: ""
  #   prompt: "New email from {from}: {subject}\\n{snippet}\\nSummarise it for me."
  # - name: phone-commands
  #   type: telegram
  #   match: "^run backup"
  #   prompt: "Run my backup routine. Message was: {text}"
  # - name: price-watch
  #   type: url
  #   url: https://example.com/product
  #   contains: "In stock"      # optional: fire only when this text appears
  #   prompt: "{url} changed and now says In stock. Tell me."
  #   bot: Shopper              # optional: let one of your bots handle it
"""

# Tests replace these.
runner: Callable[[dict[str, Any], str], str] | None = None
fetcher: Callable[[str], str] | None = None
mail_reader: Callable[[dict[str, Any]], list[dict[str, str]]] | None = None
notifier: Callable[[str], Any] | None = None


def config_path() -> Path:
    env = os.environ.get("AUTOPILOT_FILE", "").strip()
    if env:
        return Path(env)
    import agent_config

    return agent_config.APP_DIR / "autopilot.yaml"


def _state_path() -> Path:
    import agent_config

    return agent_config.storage_dir() / "autopilot_state.json"


def load_config() -> dict[str, Any]:
    path = config_path()
    if not path.is_file():
        return {"enabled": False, "watchers": []}
    import rules

    data = rules.parse_text(path.read_text(encoding="utf-8"), path.suffix or ".yaml") or {}
    watchers = []
    for i, raw in enumerate(data.get("watchers") or []):
        if isinstance(raw, dict) and raw.get("type") in TYPES and str(raw.get("prompt") or "").strip():
            watchers.append({**raw, "name": str(raw.get("name") or f"{raw['type']}-{i}")})
    return {"enabled": bool(data.get("enabled")), "check_every_seconds": max(10, int(data.get("check_every_seconds") or 60)),
            "notify": bool(data.get("notify", True)), "watchers": watchers}


def _fmt(template: str, fields: dict[str, Any]) -> str:
    return re.sub(r"\{(\w+)\}", lambda m: str(fields.get(m.group(1), m.group(0))), template)


# ---- watcher checks: each returns (events, new_state) ----

def check_folder(w: dict[str, Any], state: dict[str, Any] | None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    root = Path(os.path.expanduser(str(w.get("path") or ""))).resolve()
    pattern = str(w.get("pattern") or "*")
    seen = {}
    if root.is_dir():
        for p in root.iterdir():
            if p.is_file() and fnmatch.fnmatch(p.name.casefold(), pattern.casefold()):
                seen[str(p)] = p.stat().st_mtime
    if state is None:
        return [], {"files": seen}
    old = state.get("files", {})
    events = [{"path": path, "name": Path(path).name} for path, mtime in sorted(seen.items())
              if path not in old or mtime > old[path] + 1]
    return events, {"files": seen}


def _fetch(url: str) -> str:
    if fetcher is not None:
        return fetcher(url)
    if not re.match(r"^https?://", url, re.I):
        raise ValueError("Only http(s) URLs can be watched.")
    req = urllib.request.Request(url, headers={"User-Agent": "Pedro_Agent autopilot"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read(2_000_000).decode("utf-8", "replace")


def check_url(w: dict[str, Any], state: dict[str, Any] | None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    url = str(w.get("url") or "")
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", _fetch(url)))
    wanted = str(w.get("contains") or "")
    present = wanted.casefold() in text.casefold() if wanted else None
    digest = hashlib.sha256(text.encode()).hexdigest()
    new = {"hash": digest, "present": present}
    if state is None:
        return [], new
    if wanted:
        fired = bool(present) and not state.get("present")
    else:
        fired = digest != state.get("hash")
    return ([{"url": url, "snippet": text[:500]}] if fired else []), new


def _decode(value: str) -> str:
    out = []
    for part, enc in email.header.decode_header(value or ""):
        out.append(part.decode(enc or "utf-8", "replace") if isinstance(part, bytes) else part)
    return "".join(out)


def _imap_unseen(w: dict[str, Any]) -> list[dict[str, str]]:
    if mail_reader is not None:
        return mail_reader(w)
    user = os.environ.get("GMAIL_ADDRESS", "").strip()
    password = os.environ.get("GMAIL_APP_PASSWORD", "").strip()
    if not user or not password:
        raise RuntimeError("Set GMAIL_ADDRESS and GMAIL_APP_PASSWORD for the Gmail watcher.")
    rows = []
    with imaplib.IMAP4_SSL("imap.gmail.com") as imap:
        imap.login(user, password)
        imap.select("INBOX", readonly=True)
        _typ, data = imap.uid("search", None, "UNSEEN")
        for uid in (data[0] or b"").split()[-30:]:
            _typ, msg_data = imap.uid("fetch", uid, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT)] BODY.PEEK[TEXT]<0.800>)")
            header = msg_data[0][1] if msg_data and msg_data[0] else b""
            body = msg_data[1][1] if len(msg_data) > 1 and isinstance(msg_data[1], tuple) else b""
            msg = email.message_from_bytes(header)
            rows.append({"uid": uid.decode(), "from": _decode(msg.get("From", "")),
                         "subject": _decode(msg.get("Subject", "")),
                         "snippet": body.decode("utf-8", "replace")[:500]})
    return rows


def check_gmail(w: dict[str, Any], state: dict[str, Any] | None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows = _imap_unseen(w)
    want_from = str(w.get("from") or "").casefold()
    want_subject = str(w.get("subject") or "").casefold()
    matching = [r for r in rows if want_from in r["from"].casefold() and want_subject in r["subject"].casefold()]
    uids = sorted({r["uid"] for r in rows} | set((state or {}).get("uids", [])))[-500:]
    if state is None:
        return [], {"uids": uids}
    old = set(state.get("uids", []))
    return [r for r in matching if r["uid"] not in old], {"uids": uids}


CHECKS = {"folder": check_folder, "url": check_url, "gmail": check_gmail}


class Autopilot:
    def __init__(self) -> None:
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.state: dict[str, Any] = self._load_state()
        self.log: list[dict[str, Any]] = []
        self.config = load_config()
        self._lock = threading.Lock()

    def _load_state(self) -> dict[str, Any]:
        try:
            return json.loads(_state_path().read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save_state(self) -> None:
        try:
            path = _state_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(self.state), encoding="utf-8")
        except Exception:
            pass

    # Telegram watchers are pushed by remote_bridge, not polled.
    def on_telegram(self, text: str) -> list[str]:
        fired = []
        for w in self.config["watchers"]:
            if w["type"] == "telegram" and re.search(str(w.get("match") or "."), text or "", re.I):
                fired.append(self.fire(w, {"text": text}))
        return fired

    def check_once(self) -> list[str]:
        self.config = load_config()
        fired = []
        for w in self.config["watchers"]:
            check = CHECKS.get(w["type"])
            if check is None:
                continue
            key = f"{w['type']}:{w['name']}"
            try:
                events, new_state = check(w, self.state.get(key))
            except Exception as exc:
                self.log.append({"t": time.time(), "watcher": w["name"], "error": str(exc)[:300]})
                continue
            self.state[key] = new_state
            for event in events[:10]:
                fired.append(self.fire(w, event))
        self._save_state()
        return fired

    def fire(self, w: dict[str, Any], fields: dict[str, Any]) -> str:
        prompt = "[Autopilot trigger: " + w["name"] + "] " + _fmt(str(w["prompt"]), fields)
        try:
            reply = (runner or _default_runner)(w, prompt)
        except Exception as exc:
            reply = f"Autopilot '{w['name']}' failed: {exc}"
        self.log.append({"t": time.time(), "watcher": w["name"], "reply": str(reply)[:500]})
        del self.log[:-100]
        if self.config.get("notify"):
            _notify(f"🤖 {w['name']}: {reply}")
        return reply

    def _loop(self) -> None:
        while not self.stop_event.is_set():
            if self.config.get("enabled"):
                self.check_once()
            self.stop_event.wait(self.config.get("check_every_seconds", 60))
            self.config = load_config()

    def start(self) -> "Autopilot":
        if self.thread is None or not self.thread.is_alive():
            self.stop_event.clear()
            self.thread = threading.Thread(target=self._loop, name="autopilot", daemon=True)
            self.thread.start()
            _register_telegram(self)
        return self

    def stop(self) -> None:
        self.stop_event.set()
        _register_telegram(None)


def _default_runner(w: dict[str, Any], prompt: str) -> str:
    import gta5_agent

    if w.get("bot"):
        import bots

        bot = bots.get_bot(str(w["bot"]))
        if bot is None:
            return f"No bot named {w['bot']}."
        return bots.run_bot(bot, prompt, [], unattended=True)
    gta5_agent.set_unattended(True)
    try:
        reply = gta5_agent.run_agent(prompt, [], os.environ.get("GEMINI_MODEL", gta5_agent.DEFAULT_MODEL))
    finally:
        gta5_agent.set_unattended(False)
    import confirm_action

    waiting = confirm_action.pending()
    if waiting is not None:
        reply = f"{reply}\n\nWaiting for your yes to {waiting.get('label') or waiting['name']}."
    return reply


def _notify(text: str) -> None:
    try:
        if notifier is not None:
            notifier(text)
            return
        import remote_bridge

        if remote_bridge.alerts_configured():
            remote_bridge.notify(text)
    except Exception:
        pass


def _register_telegram(pilot: Autopilot | None) -> None:
    try:
        import remote_bridge

        remote_bridge.message_listeners[:] = [cb for cb in remote_bridge.message_listeners
                                              if getattr(cb, "_autopilot", False) is False]
        if pilot is not None:
            def listener(text: str) -> None:
                matched = [w for w in pilot.config["watchers"] if w["type"] == "telegram"
                           and re.search(str(w.get("match") or "."), text or "", re.I)]
                if matched:
                    threading.Thread(target=pilot.on_telegram, args=(text,), daemon=True).start()

            listener._autopilot = True  # type: ignore[attr-defined]
            remote_bridge.message_listeners.append(listener)
    except Exception:
        pass


_pilot: Autopilot | None = None


def instance() -> Autopilot:
    global _pilot
    if _pilot is None:
        _pilot = Autopilot()
    return _pilot


def ensure_config() -> Path:
    path = config_path()
    if not path.exists():
        path.write_text(EXAMPLE, encoding="utf-8")
    return path


def autopilot_control(action: str = "status") -> dict[str, Any]:
    pilot = instance()
    action = (action or "status").strip().casefold()
    if action == "start":
        ensure_config()
        pilot.config = load_config()
        if not pilot.config["enabled"]:
            return {"ok": False, "error": f"Set enabled: true in {config_path()} first."}
        pilot.start()
    elif action == "stop":
        pilot.stop()
    elif action == "check":
        pilot.check_once()
    running = bool(pilot.thread and pilot.thread.is_alive() and not pilot.stop_event.is_set())
    return {"ok": True, "message": f"Autopilot is {'running' if running else 'stopped'}.", "running": running,
            "file": str(config_path()), "watchers": [w["name"] for w in load_config()["watchers"]],
            "recent": pilot.log[-5:]}


DECLARATIONS = [{
    "name": "autopilot_control",
    "description": "Start, stop, check now, or show the status of autopilot watchers (Gmail, Telegram, folder, URL) defined in autopilot.yaml.",
    "parameters": {"type": "object", "properties": {
        "action": {"type": "string", "enum": ["start", "stop", "check", "status"]}}},
}]
TOOLS = {"autopilot_control": autopilot_control}
