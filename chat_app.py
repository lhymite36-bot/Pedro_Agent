"""Pedro_Agent desktop chat app.

    python main.py --app            (opens a window / browser tab)

A small local web server (127.0.0.1 only, standard library) serves a chat
window with streaming replies, live tool activity, saved history, a Stop
button that also cuts off speech, optional spoken replies, and a Settings
page that edits rules.yaml. If pywebview is installed the chat opens in its
own desktop window; otherwise it opens in the default browser.
"""

from __future__ import annotations

import os
import sys
import json
import time
import tempfile
import re
import queue
import threading
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import bots
import groups
import chat_store
import rules

STATIC = Path(__file__).resolve().parent / "app_static"
STATIC_FILES = {
    "app.css": "text/css; charset=utf-8",
    "app.js": "application/javascript; charset=utf-8",
    "routines_ui.js": "application/javascript; charset=utf-8",
    "avatars/round.png": "image/png",
    "avatars/robot.png": "image/png",
    "avatars/cat.png": "image/png",
    "avatars/ghost.png": "image/png",
    "avatars/square.png": "image/png",
    "avatars/bunny.png": "image/png",
    "avatars/spark.png": "image/png",
    "avatars/fox.png": "image/png",
    "avatars/bear.png": "image/png",
    "avatars/owl.png": "image/png",
    "avatars/alien.png": "image/png",
    "avatars/dino.png": "image/png",
    "avatars/panda.png": "image/png",
    "avatars/frog.png": "image/png",
    "avatars/chick.png": "image/png",
    "avatars/octopus.png": "image/png",
    "avatars/star.png": "image/png",
    "reactions.js": "application/javascript; charset=utf-8",
    "markdown.js": "application/javascript; charset=utf-8",
    "avatar.js": "application/javascript; charset=utf-8",
    "avatars.css": "text/css; charset=utf-8",
    "newbot_ui.js": "application/javascript; charset=utf-8",
    "glass.css": "text/css; charset=utf-8",
    "pedbot-avatars.js": "application/javascript; charset=utf-8",
    "glass.js": "application/javascript; charset=utf-8",
    "themes.js": "application/javascript; charset=utf-8",
    "avatar_mode.js": "application/javascript; charset=utf-8",
    "handsfree.js": "application/javascript; charset=utf-8",
    "bots_ui.js": "application/javascript; charset=utf-8",
    "groups_ui.js": "application/javascript; charset=utf-8",
    "mention_pick.js": "application/javascript; charset=utf-8",
    "titlebar.js": "application/javascript; charset=utf-8",
    "phone_ui.js": "application/javascript; charset=utf-8",
    "favicon.ico": "image/x-icon",
    "live_ui.js": "application/javascript; charset=utf-8",
    "connectors_ui.js": "application/javascript; charset=utf-8",
    "maintenance_ui.js": "application/javascript; charset=utf-8",
    "sw.js": "application/javascript; charset=utf-8",
    "manifest.webmanifest": "application/manifest+json",
    "icon-192.png": "image/png",
    "icon-512.png": "image/png",
}
LOCAL_HOSTS = {"127.0.0.1", "localhost", "[::1]"}
_IMAGE_EXTS = {".png", ".jpg", ".jpeg"}
_MEDIA_EXTS = {".png", ".jpg", ".jpeg", ".mp4", ".webm"}
_MEDIA_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
}


def _stored_file(raw: str, suffixes: set[str]) -> Path | None:
    """A file under the agent workspace or storage folder, or None."""
    import agent_config

    try:
        target = Path(raw).expanduser().resolve()
    except (OSError, ValueError):
        return None
    if target.suffix.casefold() not in suffixes or not target.is_file():
        return None
    roots = [(Path(__file__).resolve().parent / "workspace").resolve(), agent_config.storage_dir().resolve()]
    if any(root == target.parent or root in target.parents for root in roots):
        return target
    return None


def safe_image_path(raw: str) -> Path | None:
    """Only images inside the agent workspace / storage folder are served."""
    return _stored_file(raw, _IMAGE_EXTS)


def safe_media_path(raw: str) -> Path | None:
    """Images and camera videos inside the workspace or storage folder."""
    return _stored_file(raw, _MEDIA_EXTS)


def remote_control_allowed() -> bool:
    return bool(rules.section("remote", {"allow_control": False}).get("allow_control"))


def level_payload() -> dict[str, Any]:
    try:
        import speech_level

        return {"level": speech_level.current(), "mic": speech_level.mic()}
    except Exception:
        return {"level": None, "mic": None}


def status_payload(state: "AppState") -> dict[str, Any]:
    agent = _agent()
    try:
        import remote_bridge

        telegram = remote_bridge.bridge_running()
    except Exception:
        telegram = False
    try:
        import speech_level

        level = speech_level.current()
        mic_level = speech_level.mic()
    except Exception:
        level = None
        mic_level = None
    try:
        import safe_mode

        _paused = safe_mode.paused()
    except Exception:
        _paused = False
    return {
        "paused": _paused,
        "busy": state.any_busy(),
        "listening": state.mic_lock.locked(),
        "speaking": state.is_speaking(),
        "speech_level": level if isinstance(level, (int, float)) else None,
        "mic_level": mic_level if isinstance(mic_level, (int, float)) else None,
        "telegram": telegram,
        "model": state.model,
        "active_model": str(getattr(state, "active_model", "") or ""),
        "quota_note": _quota_note(state.model),
        "speak": state.speak,
        "speak_mode": state.speak_mode,
    }


def _quota_note(selected: str) -> str:
    try:
        import extras148

        return extras148.quota_line(selected)
    except Exception:
        return ""


SPEAK_MODES = ("voice", "always", "never")
TTS_DIR = Path(tempfile.gettempdir()) / "pedro-agent-tts"
_TTS_ID = re.compile(r"^[0-9a-f]{32}$")


def default_speak_mode() -> str:
    mode = str(rules.voice_setting("speak_replies", "") or "").strip().casefold()
    if mode in SPEAK_MODES:
        return mode
    return "always" if rules.voice_setting("auto_speak", False) else "voice"


def should_speak(mode: str, from_voice: bool) -> bool:
    """voice = speak only replies to spoken messages; always; never."""
    if mode == "always":
        return True
    if mode == "never":
        return False
    return bool(from_voice)


def synth_client_audio(text: str) -> str:
    """Write the reply as an mp3 for the browser/phone. Returns the clip id."""
    agent = _agent()
    TTS_DIR.mkdir(parents=True, exist_ok=True)
    for old in TTS_DIR.glob("*.mp3"):  # keep the folder small
        try:
            if time.time() - old.stat().st_mtime > 900:
                old.unlink()
        except OSError:
            pass
    clip = uuid.uuid4().hex
    agent._synthesize_reply(text, TTS_DIR / f"{clip}.mp3", agent._neural_voice())
    return clip


def tts_file(clip: str) -> Path | None:
    if not _TTS_ID.match(clip or ""):
        return None
    path = TTS_DIR / f"{clip}.mp3"
    return path if path.is_file() else None




SETUP_KEYS = ("GEMINI_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "GROQ_API_KEY",
              "OPENROUTER_API_KEY", "CEREBRAS_API_KEY", "NVIDIA_API_KEY")


def _env_path() -> Path:
    return Path(__file__).resolve().parent / ".env"


def setup_status() -> dict:
    seen: list[str] = []
    primary = os.environ.get("GEMINI_API_KEY", "").strip()
    if primary:
        seen.append(primary)
    for part in os.environ.get("GEMINI_API_KEYS", "").split(","):
        part = part.strip()
        if part and part not in seen:
            seen.append(part)
    return {"needs_setup": not primary,
            "telegram": bool(os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()),
            "backup_model": bool(os.environ.get("GROQ_API_KEY", "").strip()),
            "gemini_keys": len(seen),
            "openrouter": bool(os.environ.get("OPENROUTER_API_KEY", "").strip()),
            "cerebras": bool(os.environ.get("CEREBRAS_API_KEY", "").strip()),
            "nvidia": bool(os.environ.get("NVIDIA_API_KEY", "").strip())}


def save_setup(data: dict) -> dict:
    """First-run setup: write the user's own keys into .env (never sent anywhere)."""
    import re as _re

    values = {k: str(data.get(k.lower()) or "").strip() for k in SETUP_KEYS}
    raw_list = str(data.get("gemini_api_keys") or "").strip()
    if raw_list:
        extra: list[str] = []
        for piece in _re.split(r"[\s,;]+", raw_list):
            piece = piece.strip()
            if not piece:
                continue
            if len(piece) > 200 or _re.search(r"[=\s\"']", piece):
                return {"ok": False, "error": "A Gemini key doesn't look right."}
            if piece not in extra:
                extra.append(piece)
        if len(extra) > 8:
            return {"ok": False, "error": "Save up to 8 extra Gemini keys."}
        values["GEMINI_API_KEYS"] = ",".join(extra)
    if not values["GEMINI_API_KEY"] and setup_status()["needs_setup"]:
        return {"ok": False, "error": "Paste your Gemini API key (free at aistudio.google.com/apikey)."}
    for k, v in values.items():
        if k == "GEMINI_API_KEYS":
            continue
        if v and (len(v) > 300 or _re.search(r"[\s\r\n=\"']", v)):
            return {"ok": False, "error": f"{k} doesn't look right."}
    path = _env_path()
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    for k, v in values.items():
        if not v:
            continue
        os.environ[k] = v
        for n, line in enumerate(lines):
            if line.split("=", 1)[0].strip() == k:
                lines[n] = f"{k}={v}"
                break
        else:
            lines.append(f"{k}={v}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"ok": True, **setup_status()}


def clear_chats(state) -> int:
    """Delete every normal chat. Bot and group rooms (and the bots/groups) stay."""
    n = 0
    for row in chat_store.sessions():
        sid = str(row.get("session") or "")
        if sid and not sid.startswith((bots.SESSION_PREFIX, groups.SESSION_PREFIX)):
            chat_store.delete_session(sid)
            state.histories.pop(sid, None)
            n += 1
    return n

def _ui_settings_path():
    import agent_config

    return agent_config.storage_dir() / "ui_settings.json"


def _saved_model() -> str:
    try:
        return str(json.loads(_ui_settings_path().read_text(encoding="utf-8")).get("model") or "")
    except Exception:
        return ""


VOICE_STYLES = {
    "andrew": "en-US-AndrewNeural",
    "brian": "en-US-BrianNeural",
    "guy": "en-US-GuyNeural",
    "jenny": "en-US-JennyNeural",
    "aria": "en-US-AriaNeural",
}


def _ui_load() -> dict:
    try:
        data = json.loads(_ui_settings_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _ui_save(data: dict) -> None:
    try:
        path = _ui_settings_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")
    except Exception:
        pass


def _save_model(model: str) -> None:
    data = _ui_load()
    data["model"] = model
    _ui_save(data)


def current_voice_style() -> str:
    saved = str(_ui_load().get("voice_style") or "").strip().casefold()
    if saved in VOICE_STYLES:
        return saved
    env = os.environ.get("EDGE_TTS_VOICE", "").strip()
    for key, name in VOICE_STYLES.items():
        if name == env:
            return key
    return "andrew"


def apply_voice_style(key: str) -> str:
    """Save one allowlisted neural voice. An unknown name changes nothing."""
    name = str(key or "").strip().casefold()
    if name not in VOICE_STYLES:
        return ""
    os.environ["EDGE_TTS_VOICE"] = VOICE_STYLES[name]
    data = _ui_load()
    data["voice_style"] = name
    _ui_save(data)
    return name


def apply_saved_voice() -> None:
    saved = str(_ui_load().get("voice_style") or "").strip().casefold()
    if saved in VOICE_STYLES:
        os.environ["EDGE_TTS_VOICE"] = VOICE_STYLES[saved]

class AppState:
    @property
    def speak(self) -> bool:
        return self.speak_mode == "always"

    @speak.setter
    def speak(self, value: bool) -> None:
        self.speak_mode = "always" if value else "voice"

    def __init__(self, model: str) -> None:
        self.model = _saved_model() or model
        self.histories: dict[str, list[Any]] = {}
        self.cancel = threading.Event()
        self.busy = threading.Lock()
        self._session_guard = threading.Lock()
        self._session_locks: dict[str, threading.Lock] = {}
        self._session_cancels: dict[str, threading.Event] = {}
        self._session_pipes: dict[str, Any] = {}
        self.speak_mode = default_speak_mode()
        self.pipeline: Any = None
        self.pipeline_factory: Any = None  # tests inject a fake speech pipeline
        self.mic_lock = threading.Lock()
        self.wake_on = False

    def history_for(self, session: str) -> list[Any]:
        if session not in self.histories:
            self.histories[session] = _rebuild_history(session)
        return self.histories[session]

    def session_lock(self, session: str) -> threading.Lock:
        with self._session_guard:
            lock = self._session_locks.get(session)
            if lock is None:
                lock = threading.Lock()
                self._session_locks[session] = lock
            return lock

    def session_cancel(self, session: str) -> threading.Event:
        with self._session_guard:
            ev = self._session_cancels.get(session)
            if ev is None:
                ev = threading.Event()
                self._session_cancels[session] = ev
            return ev

    def any_busy(self) -> bool:
        with self._session_guard:
            return any(lock.locked() for lock in self._session_locks.values())

    def is_speaking(self) -> bool:
        with self._session_guard:
            for sess, pipe in self._session_pipes.items():
                lock = self._session_locks.get(sess)
                if pipe is not None and (lock is None or not lock.locked()):
                    return True
        return False

    def remember_pipe(self, session: str, pipe: Any) -> None:
        with self._session_guard:
            if pipe is None:
                self._session_pipes.pop(session, None)
            else:
                self._session_pipes[session] = pipe

    def cancel_session(self, session: str) -> None:
        self.session_cancel(session).set()
        with self._session_guard:
            pipe = self._session_pipes.get(session)
        if pipe is not None:
            try:
                pipe.abort()
            except Exception:
                pass

    def cancel_all(self) -> None:
        self.cancel.set()
        with self._session_guard:
            events = list(self._session_cancels.values())
            pipes = list(self._session_pipes.values())
        for ev in events:
            ev.set()
        for pipe in pipes:
            try:
                pipe.abort()
            except Exception:
                pass


def _clip_saved_line(text: str) -> str:
    flat = " ".join(str(text or "").split())
    if not flat:
        return ""
    try:
        import agent_core

        if agent_core._memory_is_secret(flat):
            return "[hidden]"
    except Exception:
        pass
    return flat[:160]


def _rebuild_history(session: str) -> list[Any]:
    """Restore the model context from saved text after a restart.

    A bot chat keeps the last 80 turns, plus up to 30 older lines in one note.
    Other chats stay at the last 40 turns.
    """
    try:
        from google.genai import types
    except ImportError:
        return []
    bot_chat = str(session or "").startswith("bot-")
    rows = chat_store.history(session, limit=110 if bot_chat else 40)
    earlier: list[dict[str, Any]] = []
    recent = rows
    if bot_chat and len(rows) > 80:
        earlier, recent = rows[:-80][-30:], rows[-80:]
    out: list[Any] = []
    if earlier:
        lines = []
        for row in earlier:
            who = "User" if row.get("role") == "user" else "You"
            shown = _clip_saved_line(str(row.get("text") or ""))
            if shown:
                lines.append(f"{who}: {shown}")
        if lines:
            note = "Earlier turns you still remember:\n" + "\n".join(lines)
            out.append(types.Content(role="user", parts=[types.Part.from_text(text=note)]))
    for row in recent:
        role = "user" if row["role"] == "user" else "model"
        out.append(types.Content(role=role, parts=[types.Part.from_text(text=row["text"])]))
    return out


def _agent() -> Any:
    import agent_core

    return agent_core


def _new_pipeline(state: AppState) -> Any:
    factory = state.pipeline_factory or _agent()._SpeechPipeline
    return factory()


SPEECH_FINISH_TIMEOUT = 120.0  # no playback progress for this long means the device is stuck
SPEECH_MAX_SECONDS = 20 * 60  # a reply that keeps playing is not cut before this


def speech_deadline(now: float, deadline: float, cursor: int, last: int | None) -> tuple[float, int]:
    """Extend the deadline while the voice is still moving forward."""
    if last is None or cursor != last:
        return now + SPEECH_FINISH_TIMEOUT, cursor
    return deadline, last if last is not None else cursor


def _wait_for_speech(worker: threading.Thread, pipeline: Any) -> str:
    """Wait until playback ends. A moving voice is not stopped for being long."""
    import speech_level

    started = time.monotonic()
    deadline = started + SPEECH_FINISH_TIMEOUT
    last: int | None = speech_level.cursor()
    while worker.is_alive():
        now = time.monotonic()
        if now - started > SPEECH_MAX_SECONDS or now >= deadline:
            try:
                pipeline.abort()
            except Exception:
                pass
            return "timeout"
        worker.join(min(0.2, max(0.01, deadline - now)))
        if not worker.is_alive():
            return "done"
        deadline, last = speech_deadline(time.monotonic(), deadline, speech_level.cursor(), last)
    return "done"


def _finish_speech(state: AppState, pipeline: Any, reply: str, spoke_any: bool, emit: Any) -> None:
    """Play what is left, then ALWAYS emit speech_end (ok, error, skipped, stuck)."""
    status, detail = "ok", ""
    try:
        if state.cancel.is_set():
            status = "stopped"
            pipeline.abort()
            return
        if reply and not spoke_any:
            pipeline.submit(reply)  # non-streamed answer: speak it whole
        box: dict[str, Any] = {}

        def run() -> None:
            try:
                box["result"] = pipeline.finish() or {}
            except BaseException as exc:  # noqa: BLE001
                box["error"] = exc

        worker = threading.Thread(target=run, name="speech-finish", daemon=True)
        worker.start()
        if _wait_for_speech(worker, pipeline) == "timeout":
            status, detail = "timeout", "Speech playback did not finish; stopped it."
            return
        if "error" in box:
            status, detail = "error", f"Voice: {box['error']}"
            return
        result = box.get("result") or {}
        if result.get("interrupted") and result.get("transcript"):
            status = "barge"
            emit({"event": "barge", "text": str(result["transcript"])})
        elif not result.get("ok", True):
            status, detail = "error", "Voice: " + str(result.get("error"))
    except Exception as exc:
        status, detail = "error", f"Voice: {exc}"
    finally:
        if detail:
            emit({"event": "error", "text": detail})
        emit({"event": "speech_end", "status": status})


def state_hidden() -> bool:
    """True while the window is closed to the tray (updates also go to notifications)."""
    try:
        import win_chrome

        return bool(getattr(win_chrome, "HIDDEN", False))
    except Exception:
        return False


def stream_turn(state: AppState, session: str, text: str, emit: Any, speak: bool | None = None,
                from_voice: bool = False, client_audio: bool = False, files: list[str] | None = None,
                origin: str = "") -> str:
    """Run one turn and push events through emit(dict). Returns the reply.

    With speech on, each streamed sentence is synthesized and played while
    the rest is still arriving (the console voice pipeline). Talking over it
    (barge-in) or Stop cuts it off; a barge-in transcript is sent back as a
    "barge" event so the window can submit it as the next message.
    Every turn ends with a "speech_end" event, even when speech is off or
    failed, so hands-free mode always knows when to listen again.
    """
    agent = _agent()
    import step_labels, team_agent
    wrote: list[str] = []
    raw_emit = emit

    import progress_notes
    import background as _bg

    def _post_update(kind: str, note: str) -> None:
        try:
            mid = chat_store.add(session, "assistant", note)
        except Exception:
            mid = 0
        ev = {"event": "update", "kind": kind, "text": note, "id": mid}
        try:
            import live_sync

            live_sync.publish(session, ev)       # every window and the phone, not just this one
        except Exception:
            pass
        raw_emit(ev)
        if kind in {"opening", "blocker", "final"} or state_hidden():
            _bg.notify("Ped Bot", note)

    narrator = progress_notes.Narrator(text, _post_update)
    task_id = _bg.task_started(session, text, files) if not text.startswith("[Resumed") else ""

    def watch(ev: dict) -> None:
        try:
            narrator.feed(ev)
        except Exception:
            pass
        if ev.get("event") == "model_switch":
            shown = str(ev.get("model") or "")
            state.active_model = shown.split(":", 1)[-1] if shown.startswith("backup:") else shown
        if ev.get("event") == "tool_end" and ev.get("ok") and ev.get("path"):
            wrote.append(str(ev["path"]))
        try:
            import live_sync

            live_sync.publish(session, ev, origin=origin)
        except Exception:
            pass
        raw_emit(ev)

    emit = step_labels.wrap_emit(watch)
    import confirm_action as _confirm
    chat_token = _confirm.bind_chat(session)
    import desktop_share
    desk_token = desktop_share.bind(session)
    team_agent.bind_live_emit(emit)
    agent.bind_turn_view(emit, [])
    emit({"event": "step", "label": "Thinking…", "name": ""})
    import bot_mind
    bot_mind.hear(text)
    say_token = bot_mind.bind_announce(lambda label: emit({"event": "step", "label": label[:180], "name": "mind"}))
    cancel = state.session_cancel(session)
    cancel.clear()
    state.cancel = cancel
    pipeline = None
    reply = ""
    spoke = {"any": False}
    try:
        import polls
        import confirm_action as _ca
        polls.begin_turn()
        waiting_before = (_ca.pending() or {}).get("label")
        import attachments
        files = [f for f in (files or []) if attachments.get(f)][:10]
        user_id = chat_store.add(session, "user", attachments.message_with_marker(text, files))
        emit({"event": "saved", "role": "user", "id": user_id, "ts": chat_store.message_time(user_id)})
        turn_parts: list = []
        if files:   # pictures/PDFs go to the model as parts; other files as their text
            text, turn_parts = attachments.build_turn(text, files)
            emit({"event": "step", "label": f"Reading {len(files)} attachment(s)", "name": ""})

        def save_reply(sess: str, role: str, said: str) -> int:   # store + tell the window the id and reactions
            if role == "assistant" and "[[card:" not in said:
                import reply_clean

                guarded = reply_clean.guard_loop(sess, said)
                if guarded != said:
                    emit({"event": "step", "label": "Stopped a repeating answer.", "name": "reason"})
                    said = guarded
            mid = chat_store.add(sess, role, said)
            if wrote:
                chat_store.remember_writes(mid, wrote)
                emit({"event": "writes", "id": mid, "paths": list(wrote)})
                wrote.clear()
            emit({"event": "saved", "role": role, "id": mid, "ts": chat_store.message_time(mid)})
            emit({"event": "reactions", "id": user_id,
                  "reactions": chat_store.reactions_for([user_id]).get(user_id, [])})
            return mid

        history = state.history_for(session)
        want = should_speak(state.speak_mode, from_voice) if speak is None else bool(speak)
        # PC window: play on the PC speakers. Phone/remote: send an mp3 to the client.
        pipeline = _new_pipeline(state) if (want and not client_audio) else None
        state.pipeline = pipeline
        state.remember_pipe(session, pipeline)

        def on_text(chunk: str) -> None:
            emit({"event": "token", "text": chunk})
            if pipeline is not None and not cancel.is_set():
                spoke["any"] = True
                try:
                    pipeline.submit(chunk)
                except Exception as exc:
                    emit({"event": "error", "text": f"Voice: {exc}"})

        if pipeline is not None:
            _pause_wake()
        with state.session_lock(session):
            try:
                agent.bind_turn_view(emit, turn_parts)
            except Exception:
                pass
            try:
                bot = bots.bot_for_session(session)
                group = groups.group_for_session(session)
                import confirm_action
                waiting = confirm_action.pending()
                quick = confirm_action.answer_pending(text, agent.invoke_tool)   # one yes runs it once
                if quick is not None and waiting and waiting.get("name") == "place_order" and quick.startswith("Cancelled"):
                    import order_flow
                    order_flow.deny_order(str((waiting.get("arguments") or {}).get("order_id") or ""))
                    quick = "Order cancelled. Nothing was placed (the cart is left as it is)."

                if quick is not None:
                    reply = quick
                    if group is not None:
                        emit({"event": "speaker", **groups.display(groups.MAIN)})
                        emit({"event": "done", "text": reply, "speaker": groups.MAIN})
                        save_reply(session, "assistant", f"[[@{groups.MAIN}]] {reply}")
                elif group is not None:
                    def group_emit(e: dict) -> None:   # speak each member's finished reply in turn
                        emit(e)
                        if pipeline is not None and e.get("event") == "done" and e.get("text") and not cancel.is_set():
                            spoke["any"] = True
                            try:
                                pipeline.submit(str(e["text"]))
                            except Exception as exc:
                                emit({"event": "error", "text": f"Voice: {exc}"})

                    with confirm_action.user_turn(text):
                        said = groups.run_group(group, text, history, group_emit, model=state.model,
                                                store=save_reply, react=lambda sess, e, who: (
                                                    chat_store.react_last_user(sess, e, who),
                                                    emit({"event": "reactions", "id": user_id,
                                                          "reactions": chat_store.reactions_for([user_id]).get(user_id, [])})),
                                                cancel_event=cancel, on_event=group_emit)
                    reply = said[-1][1] if said else ""
                elif bot is not None:
                    with confirm_action.user_turn(text):
                        reply = bots.run_bot(
                            bot, text, history, model=state.model,
                            cancel_event=cancel, on_text=on_text, on_event=emit,
                        )
                else:
                    reply = agent.run_agent(
                        text, history, state.model,
                        cancel_event=cancel, on_text=on_text, on_event=emit,
                    ) or ""
            except Exception as exc:  # RuntimeError for quota, key, network
                print(f"[turn] {type(exc).__name__}: {agent._scrub(str(exc))[:300]}", flush=True)
                if not isinstance(exc, RuntimeError):
                    try:
                        import crash_reports
                        crash_reports.record(exc, where="chat turn")
                    except Exception:
                        pass
                emit({"event": "error", "text": agent.friendly_model_error(agent._scrub(str(exc)))})
                reply = ""
        if reply and not session.startswith(groups.SESSION_PREFIX):
            save_reply(session, "assistant", reply)
            reply = chat_store.extract_reactions(reply)[0]
        _post_cards(session, emit, waiting_before)
        emit({"event": "group_done"} if session.startswith(groups.SESSION_PREFIX) else {"event": "done", "text": reply})
        try:
            narrator.finish(reply, cancelled=cancel.is_set())
        except Exception:
            pass
        if task_id:
            _bg.task_finished(task_id)
        if pipeline is not None:
            _finish_speech(state, pipeline, reply, spoke["any"], emit)
        elif want and client_audio and reply and not cancel.is_set():
            try:
                emit({"event": "step", "label": "Getting my voice ready…", "name": ""})
                clip = synth_client_audio(reply)
                emit({"event": "audio", "url": f"/api/tts?id={clip}"})
                emit({"event": "speech_end", "status": "client"})
            except Exception as exc:
                emit({"event": "error", "text": f"Voice: {agent._scrub(str(exc))}"})
                emit({"event": "speech_end", "status": "error"})
        else:
            emit({"event": "speech_end", "status": "skipped"})
        return reply
    except Exception as exc:
        try:
            if task_id:
                import background as _bg2
                _bg2.task_finished(task_id)
        except Exception:
            pass
        try:
            import crash_reports
            crash_reports.record(exc, "chat turn")
        except Exception:
            pass
        emit({"event": "error", "text": f"Turn failed: {exc}"})
        emit({"event": "speech_end", "status": "error"})
        return reply
    finally:
        try:
            import team_agent
            team_agent.clear_live_emit()
            agent.clear_turn_view()
            _confirm.unbind_chat(chat_token)
            desktop_share.unbind(desk_token)
            bot_mind.unbind_announce(say_token)
        except Exception:
            pass
        state.remember_pipe(session, None)
        if state.pipeline is pipeline:
            state.pipeline = None
        if pipeline is not None:
            _resume_wake()


def _post_cards(session: str, emit: Any, waiting_before: str | None) -> None:
    """1.4.10: question cards from ask_user, and an Approve/Deny card for a new waiting action."""
    try:
        import confirm_action
        import polls
        cards = polls.take_turn_cards()
        p = confirm_action.pending()
        if p is None:
            polls.expire_open_approvals()
        elif p.get("label") != waiting_before:
            order = None
            if p.get("name") == "place_order":
                import order_flow
                order = order_flow.pending_card()
            cards.append(polls.approval_card(str(p.get("label") or p.get("name")), str(p.get("name")), order))
        for c in cards:
            mid = chat_store.add(session, "assistant", f"[[card:{c['id']}]]")
            emit({"event": "card", "id": mid, "card": polls.view(c["id"], confirm_action.pending())})
    except Exception as exc:
        emit({"event": "error", "text": f"Card: {exc}"})


def _pause_wake() -> None:
    try:
        import wake_word

        wake_word.pause_wake_listener()
    except Exception:
        pass


def _resume_wake() -> None:
    try:
        import wake_word

        wake_word.resume_wake_listener()
    except Exception:
        pass


_SILENCE_MARKERS = ("no speech", "timed out")


def listen_once(state: AppState, timeout: float = 8.0) -> dict[str, Any]:
    """Record one phrase with the same local recogniser as console voice mode.

    Returns {"ok", "text", "error", "kind"}. kind is "speech", "silence"
    (nothing heard: hands-free just listens again) or "error" (shown in the
    window). The mic lock and the wake-listener pause are released on every
    path.
    """
    agent = _agent()
    if not state.mic_lock.acquire(timeout=3):
        return {"ok": False, "text": "", "error": "The microphone is busy.", "kind": "busy"}
    heard: Any = None
    try:
        _pause_wake()
        try:
            heard = agent.listen_to_microphone(timeout=timeout, phrase_time_limit=None, announce=False)
        except Exception as exc:
            heard = {"ok": False, "error": f"Microphone error: {exc}"}
    finally:
        _resume_wake()
        state.mic_lock.release()
    if not isinstance(heard, dict):
        return {"ok": False, "text": "", "error": "", "kind": "silence"}
    text = str(heard.get("text") or "").strip()
    if heard.get("ok") and text:
        return {"ok": True, "text": text, "error": "", "kind": "speech"}
    error = str(heard.get("error") or "")
    if not error or any(m in error.casefold() for m in _SILENCE_MARKERS):
        return {"ok": False, "text": "", "error": error, "kind": "silence"}
    return {"ok": False, "text": "", "error": error, "kind": "error"}


def make_handler(state: AppState) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args: Any) -> None:  # quiet console
            return

        def _send(self, code: int, body: bytes, kind: str = "application/json") -> None:
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _send_saved(self, body: bytes, kind: str, name: str, download: bool) -> None:
            self.send_response(200)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "private, max-age=3600")
            if download:
                from urllib.parse import quote
                self.send_header("Content-Disposition", "attachment; filename*=UTF-8''" + quote(name))
            self.end_headers()
            self.wfile.write(body)

        def _json(self, data: Any, code: int = 200) -> None:
            self._send(code, json.dumps(data, default=str).encode("utf-8"))

        def _body(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            try:
                return json.loads(raw.decode("utf-8") or "{}")
            except json.JSONDecodeError:
                return {}

        def _same_origin(self) -> bool:
            origin = self.headers.get("Origin")
            host = self.headers.get("Host", "")
            return origin is None or urlparse(origin).netloc == host

        remote = False

        def _gate(self) -> bool:
            """Local app: only for this PC. Blocks other Host names (DNS
            rebinding, or a tunnel pointed at this port by mistake)."""
            host = self.headers.get("Host", "").rsplit(":", 1)[0].casefold()
            if host in LOCAL_HOSTS:
                return True
            self._send(403, b'{"error":"local only - use the remote port"}')
            return False

        def _live_get(self, url: Any, query: dict[str, list[str]]) -> bool:
            import live_pc

            if url.path == "/live/frame.jpg":
                blob = live_pc.frame()
                if blob:
                    self._send(200, blob, "image/jpeg")
                else:
                    self._send(503, b'{"error":"no screen capture"}')
            elif url.path == "/live/stream.mjpg":
                self.send_response(200)
                self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                live_pc.mjpeg(lambda b: (self.wfile.write(b), self.wfile.flush()),
                              query.get("fps", [""])[0] or live_pc.settings()["default_fps"])
            elif url.path == "/live/activity":
                try:
                    after = int(query.get("after", ["0"])[0])
                except ValueError:
                    after = 0
                self._json({"items": live_pc.activity(after), "busy": state.any_busy(),
                            "now": live_pc.busy_text(), "remote": self.remote,
                            "local": not self.remote,
                            "control": remote_control_allowed()})
            else:
                return False
            return True

        def do_GET(self) -> None:
            if not self._gate():
                return
            url = urlparse(self.path)
            query = parse_qs(url.query)
            if url.path.startswith("/live/") and self._live_get(url, query):
                return
            if url.path == "/api/live":
                self._live_feed(query)
                return
            if url.path in {"/", "/index.html"}:
                self._send(200, (STATIC / "index.html").read_bytes(), "text/html; charset=utf-8")
            elif url.path.lstrip("/") in STATIC_FILES:
                name = url.path.lstrip("/")
                self._send(200, (STATIC / name).read_bytes(), STATIC_FILES[name])
            elif url.path == "/api/level":
                self._json(level_payload())
            elif url.path == "/api/setup":
                self._json(setup_status())
            elif url.path == "/api/phone":
                import remote_access
                self._json(remote_access.phone_status() if not self.remote else {"error": "PC only"}, 200 if not self.remote else 403)
            elif url.path == "/api/groups":
                self._json({"groups": groups.list_groups(), "main": groups.display(groups.MAIN)})
            elif url.path == "/api/pending":  # phone/PC Approve-Deny bar for a waiting send/delete
                import confirm_action
                p = confirm_action.pending()
                card = None
                if p and p.get("name") == "place_order":
                    import order_flow
                    card = order_flow.pending_card()
                self._json({"pending": {"label": str((p or {}).get("label") or ""), "order": card} if p else None})
            elif url.path == "/api/checklist":
                import extras149
                self._json(extras149.setup_checklist())
            elif url.path == "/api/background":
                import background
                self._json(background.settings())
            elif url.path == "/api/shorts":
                import quiet_brain_shorts
                self._json(quiet_brain_shorts.settings())
            elif url.path == "/api/theme":
                import themes
                self._json(themes.get())
            elif url.path == "/api/update":
                import updater
                self._json(updater.last() or {"current": updater.VERSION, "update_available": False})
            elif url.path == "/api/connections":
                import google_connections
                self._json(google_connections.status())
            elif url.path == "/api/crashes":
                import crash_reports
                name = query.get("name", [""])[0]
                self._json({"text": crash_reports.read(name)} if name else {"reports": crash_reports.listing(),
                                                                             "folder": str(crash_reports.folder())})
            elif url.path == "/api/status":
                self._json(status_payload(state))
            elif url.path == "/api/image":
                found = safe_image_path(query.get("path", [""])[0])
                if found is None:
                    self._send(404, b"{}")
                else:
                    kind = "image/png" if found.suffix.casefold() == ".png" else "image/jpeg"
                    self._send_saved(found.read_bytes(), kind, found.name, query.get("download", ["0"])[0] == "1")
            elif url.path == "/api/media":
                found = safe_media_path(query.get("path", [""])[0])
                if found is None:
                    self._send(404, b"{}")
                else:
                    kind = _MEDIA_TYPES.get(found.suffix.casefold(), "application/octet-stream")
                    self._send_saved(found.read_bytes(), kind, found.name, query.get("download", ["0"])[0] == "1")
            elif url.path == "/api/bots":
                self._json({"bots": bots.list_bots(), "tools": sorted(_agent().TOOLS)})
            elif url.path == "/api/sessions":
                import attachments
                rows = chat_store.sessions()
                for r in rows:
                    t, ids = attachments.split_marker(str(r.get("title") or ""))
                    if ids:
                        r["title"] = (t if t and t != "(sent attachments)" else "\U0001F4CE " + ", ".join(
                            f["name"] for f in attachments.info(ids)) or "Attachment")
                self._json(rows)
            elif url.path == "/api/history":
                sid = query.get("session", [""])[0]
                rows = chat_store.history(sid)
                if sid.startswith(groups.SESSION_PREFIX):
                    rows = [groups.clean_row(r) for r in rows]
                import reply_clean

                rows = [reply_clean.clean_row(r) for r in rows]
                import attachments
                import confirm_action
                import polls
                waiting = confirm_action.pending()
                for r in rows:
                    m = polls.MARK.match(str(r.get("text") or ""))
                    if m:
                        r["card"] = polls.view(m.group(1), waiting)
                    if r.get("role") == "user" and "[[files:" in str(r.get("text") or ""):
                        r["text"], ids = attachments.split_marker(str(r["text"]))
                        r["files"] = attachments.info(ids)
                self._json(rows)
            elif url.path == "/api/routines":
                import routines
                self._json(routines.list_routines())
            elif url.path == "/api/routines/feed":
                import routines
                try:
                    since = float(query.get("since", ["0"])[0])
                except ValueError:
                    since = 0.0
                self._json({"feed": routines.feed(since)})
            elif url.path == "/api/card":
                import confirm_action
                import polls
                card = polls.view(query.get("id", [""])[0], confirm_action.pending())
                self._json({"card": card} if card else {"error": "not found"}, 200 if card else 404)
            elif url.path == "/api/upload":
                import attachments
                item = attachments.get(query.get("id", [""])[0])
                if item is None:
                    self._send(404, b"{}")
                else:
                    blob = Path(item["path"]).read_bytes()
                    kind = attachments.mime_for(item["name"])
                    self.send_response(200)
                    self.send_header("Content-Type", kind if item["kind"] == "image" else "application/octet-stream")
                    self.send_header("Content-Length", str(len(blob)))
                    self.send_header("X-Content-Type-Options", "nosniff")
                    self.send_header("Content-Security-Policy", "sandbox")
                    self.send_header("Cache-Control", "private, max-age=86400")
                    if item["kind"] != "image":
                        from urllib.parse import quote
                        self.send_header("Content-Disposition", "attachment; filename*=UTF-8''" + quote(item["name"]))
                    self.end_headers()
                    self.wfile.write(blob)
            elif url.path == "/api/rules":
                path = rules.rules_path() or (rules.APP_DIR / "rules.yaml")
                text = path.read_text(encoding="utf-8") if path.is_file() else ""
                self._json({"path": str(path), "text": text})
            elif url.path == "/api/wake":
                import wake_word

                item = wake_word.poll_wake_command() if state.wake_on else None
                self._json({"text": str(item.get("text")) if item else ""})
            elif url.path == "/api/tts":
                found = tts_file(query.get("id", [""])[0])
                if found is None:
                    self._send(404, b"{}")
                else:
                    self._send(200, found.read_bytes(), "audio/mpeg")
            elif url.path == "/api/connectors":
                import connectors
                self._json({"connectors": connectors.catalog()})
            elif url.path == "/api/settings":
                self._json({"model": state.model, "speak": state.speak, "speak_mode": state.speak_mode,
                            "wake": state.wake_on,
                            "wake_phrase": _wake_phrase(),
                            "models": _agent().model_candidates(state.model),
                            "voice_style": current_voice_style(),
                            "voice_styles": list(VOICE_STYLES)})
            else:
                self._send(404, b"{}")

        _SYNC_PATHS = {"/api/card/answer", "/api/react", "/api/rename", "/api/delete_session", "/api/clear_chats",
                       "/api/pin", "/api/routines/update", "/api/bots", "/api/bots/delete", "/api/groups",
                       "/api/groups/delete", "/api/undo", "/api/stop", "/api/pause_all", "/api/resume_all"}

        def do_POST(self) -> None:
            path = urlparse(self.path).path
            try:
                self._do_post()
            finally:
                if path in self._SYNC_PATHS:
                    try:
                        import live_sync

                        live_sync.notify("changed", what=path.rsplit("/", 1)[-1])
                    except Exception:
                        pass

        def _do_post(self) -> None:
            if not self._gate():
                return
            if not self._same_origin():
                self._send(403, b'{"error":"cross-origin"}')
                return
            url = urlparse(self.path)
            if url.path == "/api/upload":   # raw file bytes; name in X-File-Name (URL-encoded)
                import attachments
                from urllib.parse import unquote
                self._body_read = True
                try:
                    size = int(self.headers.get("Content-Length") or 0)
                except ValueError:
                    size = 0
                if size <= 0 or size > attachments.MAX_BYTES:
                    self.close_connection = True
                    self._json({"ok": False, "error": "Files can be up to 15 MB."}, 413)
                    return
                blob = self.rfile.read(size)
                self._json(attachments.save_upload(unquote(self.headers.get("X-File-Name") or "file"), blob))
                return
            data = self._body()
            if url.path.startswith("/api/phone/"):
                import remote_access
                if self.remote:
                    self._json({"ok": False, "error": "Pairing is only available on the PC."}, 403)
                else:
                    act = url.path.rsplit("/", 1)[-1]
                    if act == "enable":
                        self._json(remote_access.phone_enable(state, bool(data.get("consent"))))
                    elif act == "disable":
                        self._json(remote_access.phone_disable())
                    elif act == "pair":
                        self._json(remote_access.phone_pair())
                    elif act == "unpair" and data.get("confirm"):
                        self._json(remote_access.unpair_all())
                    else:
                        self._json({"ok": False, "error": "Unknown or unconfirmed action."}, 400)
            elif url.path == "/api/setup":
                if self.remote:
                    self._json({"ok": False, "error": "Run setup on the PC itself."}, 403)
                else:
                    self._json(save_setup(data))
            elif url.path == "/live/control":
                if self.remote:
                    self._json({"ok": False, "error": "Phone control stays behind Allow control."}, 403)
                else:
                    import live_pc
                    self._json(live_pc.local_control(data))
            elif url.path == "/api/pin":
                try:
                    on = chat_store.set_pin(str(data.get("session") or ""), bool(data.get("on")))
                    self._json({"ok": True, "pinned": on})
                except (ValueError, KeyError) as exc:
                    self._json({"ok": False, "error": str(exc)}, 400)
            elif url.path == "/api/undo":
                if self.remote:
                    self._json({"ok": False, "error": "Undo is only available on the PC."}, 403)
                else:
                    import undo_store
                    paths = data.get("paths") if isinstance(data.get("paths"), list) else []
                    if paths:
                        self._json(undo_store.undo_paths([str(p) for p in paths[:40]]))
                    else:
                        self._json(undo_store.undo_last_change())
            elif url.path == "/api/chat":
                self._chat(data)
            elif url.path == "/api/routines/update":   # Routines page buttons
                self._json(routine_action(data))
            elif url.path == "/api/card/answer":   # tap on a question / approval card; the page then sends r.text
                import polls
                choices = data.get("choices") if isinstance(data.get("choices"), list) else []
                self._json(polls.answer(str(data.get("id") or ""), [str(c) for c in choices],
                                        str(data.get("other") or ""), str(data.get("decision") or "")))
            elif url.path == "/api/listen":
                self._json(listen_once(state, float(data.get("timeout") or 8)))
            elif url.path == "/api/wake":
                import wake_word

                state.wake_on = bool(data.get("on"))
                if state.wake_on:
                    wake_word.drain_commands()
                    wake_word.start_wake_word_listener()
                else:
                    wake_word.stop_wake_word_listener()
                self._json({"ok": True, "wake": state.wake_on, "phrase": _wake_phrase()})
            elif url.path in {"/api/update/check", "/api/update/download", "/api/update/install"}:
                import updater
                if self.remote and url.path != "/api/update/check":
                    self._json({"ok": False, "error": "Update from the PC."}, 403)
                elif url.path.endswith("check"):
                    self._json(updater.check())
                elif url.path.endswith("download"):
                    self._json(updater.download())
                else:
                    result = updater.install(str(data.get("confirm") or ""))
                    self._json(result)
                    if result.get("ok"):
                        threading.Timer(2.0, lambda: os._exit(0)).start()
            elif url.path == "/api/connections/connect":
                import google_connections
                if self.remote:
                    self._json({"ok": False, "error": "Sign in on the PC; the Google page opens there."}, 403)
                else:
                    self._json(google_connections.connect(str(data.get("service") or "")))
            elif url.path == "/api/connections/disconnect":
                import google_connections
                self._json(google_connections.disconnect(str(data.get("service") or "")))
            elif url.path == "/api/crashes/open":
                import crash_reports
                if self.remote:
                    self._json({"ok": False, "error": "Open the folder on the PC."}, 403)
                else:
                    self._json(crash_reports.open_folder())
            elif url.path == "/api/theme":   # the phone may change it too: it is only colours
                import themes
                self._json(themes.save(data))
            elif url.path in {"/api/shorts", "/api/shorts/token", "/api/shorts/dry_run"}:
                import quiet_brain_shorts as qbs
                if self.remote and url.path != "/api/shorts/dry_run":
                    self._json({"ok": False, "error": "Change this on the PC."}, 403)
                elif url.path.endswith("token"):
                    self._json(qbs.set_token(str(data.get("token") or "")))
                elif url.path.endswith("dry_run"):
                    try:
                        self._json(qbs.run_day(dry_run=True))
                    except Exception as exc:
                        self._json({"ok": False, "error": str(exc)})
                else:
                    keys = {"enabled", "per_day", "vts_dir"}
                    self._json(qbs.save_settings(**{k: v for k, v in data.items() if k in keys}))
            elif url.path == "/api/background":
                import background
                if self.remote:
                    self._json({"ok": False, "error": "Change this on the PC."}, 403)
                else:
                    keys = {"keep_running", "notifications", "start_with_windows"}
                    self._json(background.save_settings(**{k: v for k, v in data.items() if k in keys}))
            elif url.path == "/api/pause_all":
                import safe_mode
                self._json(safe_mode.pause_all(state, by="phone" if self.remote else "pc"))
            elif url.path == "/api/resume_all":
                import safe_mode
                self._json(safe_mode.resume_all(state, by="phone" if self.remote else "pc"))
            elif url.path == "/api/stop":
                stopped = str(data.get("session") or "")
                if stopped:
                    state.cancel_session(stopped)
                else:
                    state.cancel_all()
                try:
                    _agent().stop_agent_speech()
                except Exception:
                    pass
                self._json({"ok": True})
            elif url.path == "/api/rules":
                try:
                    path = rules.save_text(str(data.get("text") or ""))
                    self._json({"ok": True, "path": str(path)})
                except Exception as exc:
                    self._json({"ok": False, "error": str(exc)}, 400)
            elif url.path == "/api/connectors":
                import connectors
                action = str(data.get("action") or "")
                if action in {"connect", "disconnect"} and self.remote:
                    self._json({"ok": False, "error": "Connect on the PC."}, 403)
                elif action == "connect":
                    self._json(connectors.connect(str(data.get("id") or ""), data))
                elif action == "disconnect":
                    self._json(connectors.disconnect(str(data.get("id") or "")))
                else:
                    self._json({"ok": False, "error": "Unknown connector action."}, 400)
            elif url.path == "/api/settings":
                if "voice_style" in data and not apply_voice_style(str(data.get("voice_style") or "")):
                    self._json({"ok": False, "error": "Pick one of the saved voice styles."}, 400)
                    return
                if data.get("model"):
                    state.model = str(data["model"]).strip()
                    _save_model(state.model)
                if "speak" in data:
                    state.speak = bool(data["speak"])
                if str(data.get("speak_mode") or "") in SPEAK_MODES:
                    state.speak_mode = str(data["speak_mode"])
                self._json({"ok": True, "model": state.model, "speak": state.speak,
                            "speak_mode": state.speak_mode,
                            "voice_style": current_voice_style()})
            elif url.path == "/api/bots":
                try:
                    bot = bots.save_bot(data)
                    self._json({"ok": True, "bot": bot, "session": bots.session_for(bot)})
                except Exception as exc:
                    self._json({"ok": False, "error": str(exc)}, 400)
            elif url.path == "/api/groups":
                try:
                    g = groups.save_group(data)
                    self._json({"ok": True, "group": g, "session": groups.SESSION_PREFIX + g["id"]})
                except Exception as exc:
                    self._json({"ok": False, "error": str(exc)}, 400)
            elif url.path == "/api/groups/delete":
                gid = str(data.get("id") or "")
                if not data.get("confirm"):
                    self._json({"ok": False, "error": "Confirm the delete."}, 400)
                else:
                    state.histories.pop(groups.SESSION_PREFIX + gid, None)
                    self._json({"ok": groups.delete_group(gid)})
            elif url.path == "/api/bots/delete":
                bot_id = str(data.get("id") or "")
                if not data.get("confirm"):
                    self._json({"ok": False, "error": "Confirm the delete."}, 400)
                else:
                    state.histories.pop(bots.SESSION_PREFIX + bot_id, None)
                    ok = bots.delete_bot(bot_id)
                    self._json({"ok": ok, "groups_updated": groups.remove_bot(bot_id) if ok else 0})
            elif url.path == "/api/bots/run_task":
                bot_id, task_id = str(data.get("id") or ""), str(data.get("task") or "")
                threading.Thread(target=bots.run_task, args=(bot_id, task_id),
                                 kwargs={"unattended": False}, daemon=True).start()
                self._json({"ok": True, "started": True})
            elif url.path == "/api/bots/teach":
                import demo_skills
                found = bots.get_bot(str(data.get("id") or ""))
                if found is None:
                    self._json({"ok": False, "error": "Save the bot first."}, 400)
                else:
                    self._json(demo_skills.record_demonstration(str(data.get("name") or "lesson"), bot=found["id"]))
            elif url.path == "/api/bots/teach_stop":
                import demo_skills
                result = demo_skills.stop_demonstration()
                saved = bots.get_bot(str(result.get("bot") or "")) if result.get("ok") else None
                self._json({**result, "saved": saved})
            elif url.path == "/api/react":   # tap an emoji on a message; tapping yours again removes it
                try:
                    found = chat_store.toggle_reaction(int(data.get("id") or 0), str(data.get("emoji") or ""), "you")
                    self._json({"ok": True, "id": int(data.get("id") or 0), "reactions": found})
                except (ValueError, KeyError) as exc:
                    self._json({"ok": False, "error": str(exc)}, 400)
            elif url.path == "/api/rename":
                try:
                    title = chat_store.rename_session(str(data.get("session") or ""), str(data.get("title") or ""))
                    self._json({"ok": True, "title": title})
                except (ValueError, KeyError) as exc:
                    self._json({"ok": False, "error": str(exc)}, 400)
            elif url.path == "/api/delete_session":
                if not data.get("confirm"):
                    self._json({"ok": False, "error": "Confirm the delete."}, 400)
                else:
                    chat_store.delete_session(str(data.get("session") or ""))
                    state.histories.pop(str(data.get("session") or ""), None)
                    self._json({"ok": True})
            elif url.path == "/api/clear_chats":
                if data.get("confirm") != "clear":
                    self._json({"ok": False, "error": "Confirm clearing all chats."}, 400)
                else:
                    self._json({"ok": True, "deleted": clear_chats(state)})
            else:
                self._send(404, b"{}")

        def _chat(self, data: dict[str, Any]) -> None:
            text = " ".join(str(data.get("text") or "").split())
            files = [str(f) for f in (data.get("files") or []) if isinstance(f, str)][:10]
            if not text and files:
                text = "(sent attachments)"
            session = str(data.get("session") or uuid.uuid4().hex[:12])
            from_voice = bool(data.get("voice"))
            force_speak = True if data.get("speak") is True else None
            # Remote (phone) always plays on the client; the PC window may ask for it too.
            client_audio = bool(self.remote or data.get("play_here"))
            if not text:
                self._json({"error": "empty"}, 400)
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            events: queue.Queue = queue.Queue()
            worker = threading.Thread(
                target=lambda: (stream_turn(state, session, text, events.put, speak=force_speak,
                                           from_voice=from_voice, client_audio=client_audio, files=files,
                                           origin=str(data.get("client") or "")), events.put(None)),
                daemon=True,
            )
            worker.start()
            self._write({"event": "session", "session": session})
            while True:
                item = events.get()
                if item is None:
                    break
                if not self._write(item):
                    state.cancel_session(session)
                    break

        def _live_feed(self, query: dict[str, list[str]]) -> None:
            """Server push for every window (PC and phone): same chats, live, with catch-up."""
            import live_sync

            raw = (query.get("since", [""])[0] or self.headers.get("Last-Event-ID") or "").strip()
            try:
                seq = int(raw) if raw else live_sync.current()
            except ValueError:
                seq = live_sync.current()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
            if not self._write({"event": "hello", "seq": live_sync.current()}):
                return
            started = time.monotonic()
            while time.monotonic() - started < 600:   # the client reconnects with ?since=
                items, gap = live_sync.wait(seq, timeout=15)
                if gap:
                    if not self._write({"event": "resync", "seq": live_sync.current()}):
                        return
                    items = items[-200:]
                if not items:
                    try:   # comment line keeps the tunnel and proxies from closing an idle stream
                        self.wfile.write(b": ping\n\n")
                        self.wfile.flush()
                    except OSError:
                        return
                    continue
                for item in items:
                    try:
                        self.wfile.write(f"id: {item['seq']}\n".encode())
                    except OSError:
                        return
                    if not self._write(item):
                        return
                    seq = item["seq"]

        def _write(self, item: dict[str, Any]) -> bool:
            try:
                self.wfile.write(f"data: {json.dumps(item, default=str)}\n\n".encode("utf-8"))
                self.wfile.flush()
                return True
            except (BrokenPipeError, ConnectionResetError, OSError):
                return False

    return Handler


TELEGRAM_SESSION = "telegram"


def telegram_turn(state: AppState, text: str) -> str:
    """Answer a Telegram message with the app's agent, history and rules.

    It is saved in the "telegram" chat so it shows in the window, and it is
    never spoken aloud on the PC.
    """
    events: list[dict[str, Any]] = []
    reply = stream_turn(state, TELEGRAM_SESSION, text, events.append, speak=False)
    if not reply:
        errors = [e.get("text", "") for e in events if e.get("event") == "error"]
        reply = errors[-1] if errors else "Done."
    return reply


def attach_telegram(state: AppState) -> bool:
    """Route Telegram through this app and start polling. False if not set up
    or another Pedro_Agent window already polls."""
    import remote_bridge

    remote_bridge.answer_handler = lambda text: telegram_turn(state, text)

    def log(role: str, text: str) -> None:
        chat_store.add(TELEGRAM_SESSION, role, text)
        history = state.histories.get(TELEGRAM_SESSION)
        if history is not None:
            try:
                from google.genai import types

                history.append(types.Content(role="user" if role == "user" else "model",
                                             parts=[types.Part.from_text(text=text)]))
            except Exception:
                pass

    remote_bridge.history_hook = log
    remote_bridge.start_remote_bridge()
    return remote_bridge.bridge_running()


def detach_telegram() -> None:
    import remote_bridge

    remote_bridge.stop_remote_bridge()
    remote_bridge.answer_handler = None
    remote_bridge.history_hook = None


def _wake_phrase() -> str:
    try:
        import wake_word

        return wake_word.wake_phrase()
    except Exception:
        return "hey agent"


def routine_action(data: dict) -> dict:
    import routines
    r = routines.find(str(data.get("id") or ""))
    if not r:
        return {"ok": False, "error": "No such routine."}
    a = str(data.get("action") or "")
    if a == "pause":
        return routines.pause_routine(r["id"])
    if a == "resume":
        return routines.resume_routine(r["id"])
    if a == "edit":
        return routines.update_routine(r["id"], name=str(data.get("name") or ""), prompt=str(data.get("prompt") or ""),
                                       when=str(data.get("when") or ""))
    if a == "delete":   # the page asks "Delete ...?" first and only then sends confirm: true
        if data.get("confirm") is not True:
            return {"ok": False, "error": "Confirm first."}
        return routines._remove(r["id"])
    if a == "run":
        threading.Thread(target=routines.run_routine, args=(r, True), daemon=True).start()
        return {"ok": True, "message": f"Running '{r['name']}' now; the result will appear in its chat."}
    return {"ok": False, "error": "Unknown action."}


def start_routines(state: "AppState") -> None:
    import routines

    def run(r: dict) -> str:
        out: list[str] = []

        def emit(ev: dict) -> None:
            if ev.get("type") in ("done", "final") and ev.get("text"):
                out.append(str(ev["text"]))

        reply = stream_turn(state, routines.session_for(r), f"[Routine: {r['name']}] {r['prompt']}", emit, speak=False)
        if isinstance(reply, str) and reply:
            return reply
        return out[-1] if out else ""

    routines.runner = run
    routines.start()
    try:
        import quiet_brain_shorts

        quiet_brain_shorts.start_routine()   # does nothing until switched on in Settings
    except Exception as exc:
        print(f"[quiet-brain] not started: {exc}", flush=True)
    try:
        import background

        def _resume(t: dict) -> None:
            events: list = []
            chat_store.add(t["session"], "assistant", "Picking this back up after a restart: " + str(t["text"])[:200])
            stream_turn(state, t["session"], "[Resumed after a restart] " + str(t["text"]), events.append, speak=False,
                        files=list(t.get("files") or []))

        got = background.resume_unfinished(_resume)
        if got:
            print(f"[background] resumed {len(got)} unfinished task(s)", flush=True)
    except Exception as exc:
        print(f"[background] resume failed: {exc}", flush=True)
    try:
        import updater

        if os.environ.get("PEDBOT_NO_UPDATE_CHECK") != "1":
            updater.start_background_check()
    except Exception:
        pass


def serve(model: str, port: int = 8765) -> tuple[ThreadingHTTPServer, AppState]:
    apply_saved_voice()
    state = AppState(model)
    import bot_mind
    bot_mind.live_read = True
    bot_mind.busy_hook = state.any_busy
    bot_mind.freeze_hook = state.cancel_all
    bots.lock_for = state.session_lock
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(state))
    server.daemon_threads = True
    return server, state


def shutdown(server: Any) -> None:
    """Stop everything the app started (also used by tests)."""
    bots.lock_for = None
    try:
        import remote_access

        remote_access.stop()
    except Exception:
        pass
    for step in (server.shutdown, server.server_close, detach_telegram, chat_store.close):
        try:
            step()
        except Exception:
            pass
    try:
        import wake_word

        wake_word.stop_wake_word_listener()
    except Exception:
        pass


def run(model: str, port: int = 8765) -> int:
    try:
        import win_chrome

        if not win_chrome.single_instance():
            win_chrome.focus_existing()
            print("Ped Bot is already running; switched to its window.", flush=True)
            return 0
    except Exception:
        pass
    if sys.stdout is None or sys.stderr is None:   # started with pythonw (no console): log to a file
        log = open(Path(__file__).resolve().parent / "app_out.log", "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stdout or log
        sys.stderr = sys.stderr or log
    server, state = serve(model, port)
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"Ped Bot chat app: {url}  (Ctrl+C to quit)", flush=True)
    bots.Scheduler().start()  # scheduled bot tasks
    start_routines(state)  # Routines scheduler (includes the 7 PM Wingz scan + report in the "daily-report" chat)
    try:
        import live_pc
        import remote_access

        live_pc.attach()
        if remote_access.settings()["enabled"]:
            info = remote_access.start(state)
            print(info.get("message") or info.get("error"), flush=True)
    except Exception as exc:
        print(f"Remote access did not start: {exc}", flush=True)
    try:
        import autopilot

        if autopilot.load_config()["enabled"]:
            autopilot.instance().start()
            print("Autopilot: watching (see autopilot.yaml).", flush=True)
    except Exception as exc:
        print(f"Autopilot did not start: {exc}", flush=True)
    try:
        try:
            if attach_telegram(state):
                print("Telegram: messages to your bot are answered here and saved in the 'telegram' chat.", flush=True)
        except Exception as exc:
            print(f"Telegram bridge did not start: {exc}", flush=True)
        try:
            import webview  # type: ignore  # pywebview, optional  # noqa: F401
            import win_chrome

            win_chrome.open_window(url)  # frameless dark window, our icon; returns when closed
            return 0
        except ImportError:
            webbrowser.open(url)
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            pass
        return 0
    finally:
        shutdown(server)
