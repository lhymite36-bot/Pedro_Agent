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
    "reactions.js": "application/javascript; charset=utf-8",
    "markdown.js": "application/javascript; charset=utf-8",
    "avatar.js": "application/javascript; charset=utf-8",
    "handsfree.js": "application/javascript; charset=utf-8",
    "bots_ui.js": "application/javascript; charset=utf-8",
    "groups_ui.js": "application/javascript; charset=utf-8",
    "mention_pick.js": "application/javascript; charset=utf-8",
    "titlebar.js": "application/javascript; charset=utf-8",
    "phone_ui.js": "application/javascript; charset=utf-8",
    "favicon.ico": "image/x-icon",
    "live_ui.js": "application/javascript; charset=utf-8",
    "sw.js": "application/javascript; charset=utf-8",
    "manifest.webmanifest": "application/manifest+json",
    "icon-192.png": "image/png",
    "icon-512.png": "image/png",
}
LOCAL_HOSTS = {"127.0.0.1", "localhost", "[::1]"}
_IMAGE_EXTS = {".png", ".jpg", ".jpeg"}


def safe_image_path(raw: str) -> Path | None:
    """Only images inside the agent workspace / storage folder are served."""
    import agent_config

    try:
        target = Path(raw).expanduser().resolve()
    except (OSError, ValueError):
        return None
    if target.suffix.casefold() not in _IMAGE_EXTS or not target.is_file():
        return None
    roots = [(Path(__file__).resolve().parent / "workspace").resolve(), agent_config.storage_dir().resolve()]
    if any(root == target.parent or root in target.parents for root in roots):
        return target
    return None


def remote_control_allowed() -> bool:
    return bool(rules.section("remote", {"allow_control": False}).get("allow_control"))


def level_payload() -> dict[str, Any]:
    try:
        import speech_level

        return {"level": speech_level.current()}
    except Exception:
        return {"level": None}


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
    except Exception:
        level = None
    return {
        "busy": state.busy.locked(),
        "listening": state.mic_lock.locked(),
        "speaking": state.pipeline is not None and not state.busy.locked(),
        "speech_level": level if isinstance(level, (int, float)) else None,
        "telegram": telegram,
        "model": state.model,
        "speak": state.speak,
        "speak_mode": state.speak_mode,
    }


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




SETUP_KEYS = ("GEMINI_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")


def _env_path() -> Path:
    return Path(__file__).resolve().parent / ".env"


def setup_status() -> dict:
    return {"needs_setup": not os.environ.get("GEMINI_API_KEY", "").strip(),
            "telegram": bool(os.environ.get("TELEGRAM_BOT_TOKEN", "").strip())}


def save_setup(data: dict) -> dict:
    """First-run setup: write the user's own keys into .env (never sent anywhere)."""
    import re as _re

    values = {k: str(data.get(k.lower()) or "").strip() for k in SETUP_KEYS}
    if not values["GEMINI_API_KEY"] and setup_status()["needs_setup"]:
        return {"ok": False, "error": "Paste your Gemini API key (free at aistudio.google.com/apikey)."}
    for k, v in values.items():
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


def _save_model(model: str) -> None:
    try:
        path = _ui_settings_path()
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        data["model"] = model
        path.write_text(json.dumps(data), encoding="utf-8")
    except Exception:
        pass

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
        self.speak_mode = default_speak_mode()
        self.pipeline: Any = None
        self.pipeline_factory: Any = None  # tests inject a fake speech pipeline
        self.mic_lock = threading.Lock()
        self.wake_on = False

    def history_for(self, session: str) -> list[Any]:
        if session not in self.histories:
            self.histories[session] = _rebuild_history(session)
        return self.histories[session]


def _rebuild_history(session: str) -> list[Any]:
    """Restore the model context from saved text after a restart."""
    try:
        from google.genai import types
    except ImportError:
        return []
    out: list[Any] = []
    for row in chat_store.history(session, limit=40):
        role = "user" if row["role"] == "user" else "model"
        out.append(types.Content(role=role, parts=[types.Part.from_text(text=row["text"])]))
    return out


def _agent() -> Any:
    import agent_core

    return agent_core


def _new_pipeline(state: AppState) -> Any:
    factory = state.pipeline_factory or _agent()._SpeechPipeline
    return factory()


SPEECH_FINISH_TIMEOUT = 120.0  # seconds; a stuck audio device cannot hang the turn


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
        worker.join(SPEECH_FINISH_TIMEOUT)
        if worker.is_alive():
            status, detail = "timeout", "Speech playback did not finish; stopped it."
            try:
                pipeline.abort()
            except Exception:
                pass
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


def stream_turn(state: AppState, session: str, text: str, emit: Any, speak: bool | None = None,
                from_voice: bool = False, client_audio: bool = False) -> str:
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
    emit = step_labels.wrap_emit(emit)
    team_agent.LIVE_EMIT = emit
    emit({"event": "step", "label": "Thinking…", "name": ""})
    state.cancel.clear()
    pipeline = None
    reply = ""
    spoke = {"any": False}
    try:
        user_id = chat_store.add(session, "user", text)
        emit({"event": "saved", "role": "user", "id": user_id})

        def save_reply(sess: str, role: str, said: str) -> int:   # store + tell the window the id and reactions
            mid = chat_store.add(sess, role, said)
            emit({"event": "saved", "role": role, "id": mid})
            emit({"event": "reactions", "id": user_id,
                  "reactions": chat_store.reactions_for([user_id]).get(user_id, [])})
            return mid

        history = state.history_for(session)
        want = should_speak(state.speak_mode, from_voice) if speak is None else bool(speak)
        # PC window: play on the PC speakers. Phone/remote: send an mp3 to the client.
        pipeline = _new_pipeline(state) if (want and not client_audio) else None
        state.pipeline = pipeline

        def on_text(chunk: str) -> None:
            emit({"event": "token", "text": chunk})
            if pipeline is not None and not state.cancel.is_set():
                spoke["any"] = True
                try:
                    pipeline.submit(chunk)
                except Exception as exc:
                    emit({"event": "error", "text": f"Voice: {exc}"})

        if pipeline is not None:
            _pause_wake()
        with state.busy:
            try:
                try:
                    agent.plan_listener = emit
                except Exception:
                    pass
                bot = bots.bot_for_session(session)
                group = groups.group_for_session(session)
                import confirm_action
                quick = confirm_action.answer_pending(text, agent.invoke_tool)   # one yes runs it once
                if quick is not None:
                    reply = quick
                    if group is not None:
                        emit({"event": "speaker", **groups.display(groups.MAIN)})
                        emit({"event": "done", "text": reply, "speaker": groups.MAIN})
                        save_reply(session, "assistant", f"[[@{groups.MAIN}]] {reply}")
                elif group is not None:
                    def group_emit(e: dict) -> None:   # speak each member's finished reply in turn
                        emit(e)
                        if pipeline is not None and e.get("event") == "done" and e.get("text") and not state.cancel.is_set():
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
                                                cancel_event=state.cancel, on_event=group_emit)
                    reply = said[-1][1] if said else ""
                elif bot is not None:
                    with confirm_action.user_turn(text):
                        reply = bots.run_bot(
                            bot, text, history, model=state.model,
                            cancel_event=state.cancel, on_text=on_text, on_event=emit,
                        )
                else:
                    reply = agent.run_agent(
                        text, history, state.model,
                        cancel_event=state.cancel, on_text=on_text, on_event=emit,
                    ) or ""
            except Exception as exc:  # RuntimeError for quota, key, network
                emit({"event": "error", "text": agent._scrub(str(exc))})
                reply = ""
        if reply and not session.startswith(groups.SESSION_PREFIX):
            save_reply(session, "assistant", reply)
            reply = chat_store.extract_reactions(reply)[0]
        emit({"event": "group_done"} if session.startswith(groups.SESSION_PREFIX) else {"event": "done", "text": reply})
        if pipeline is not None:
            _finish_speech(state, pipeline, reply, spoke["any"], emit)
        elif want and client_audio and reply and not state.cancel.is_set():
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
        emit({"event": "error", "text": f"Turn failed: {exc}"})
        emit({"event": "speech_end", "status": "error"})
        return reply
    finally:
        try:
            import team_agent
            team_agent.LIVE_EMIT = None
            agent.plan_listener = None
        except Exception:
            pass
        state.pipeline = None
        if pipeline is not None:
            _resume_wake()


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
                self._json({"items": live_pc.activity(after), "busy": state.busy.locked(),
                            "now": live_pc.busy_text(), "remote": self.remote,
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
            elif url.path == "/api/status":
                self._json(status_payload(state))
            elif url.path == "/api/image":
                found = safe_image_path(query.get("path", [""])[0])
                if found is None:
                    self._send(404, b"{}")
                else:
                    kind = "image/png" if found.suffix.casefold() == ".png" else "image/jpeg"
                    self._send(200, found.read_bytes(), kind)
            elif url.path == "/api/bots":
                self._json({"bots": bots.list_bots(), "tools": sorted(_agent().TOOLS)})
            elif url.path == "/api/sessions":
                self._json(chat_store.sessions())
            elif url.path == "/api/history":
                sid = query.get("session", [""])[0]
                rows = chat_store.history(sid)
                if sid.startswith(groups.SESSION_PREFIX):
                    rows = [groups.clean_row(r) for r in rows]
                self._json(rows)
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
            elif url.path == "/api/settings":
                self._json({"model": state.model, "speak": state.speak, "speak_mode": state.speak_mode,
                            "wake": state.wake_on,
                            "wake_phrase": _wake_phrase(),
                            "models": _agent().model_candidates(state.model)})
            else:
                self._send(404, b"{}")

        def do_POST(self) -> None:
            if not self._gate():
                return
            if not self._same_origin():
                self._send(403, b'{"error":"cross-origin"}')
                return
            url = urlparse(self.path)
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
            elif url.path == "/api/chat":
                self._chat(data)
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
            elif url.path == "/api/stop":
                state.cancel.set()
                if state.pipeline is not None:
                    try:
                        state.pipeline.abort()
                    except Exception:
                        pass
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
            elif url.path == "/api/settings":
                if data.get("model"):
                    state.model = str(data["model"]).strip()
                    _save_model(state.model)
                if "speak" in data:
                    state.speak = bool(data["speak"])
                if str(data.get("speak_mode") or "") in SPEAK_MODES:
                    state.speak_mode = str(data["speak_mode"])
                self._json({"ok": True, "model": state.model, "speak": state.speak,
                            "speak_mode": state.speak_mode})
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
            elif url.path == "/api/react":   # tap an emoji on a message; tapping yours again removes it
                try:
                    found = chat_store.toggle_reaction(int(data.get("id") or 0), str(data.get("emoji") or ""), "you")
                    self._json({"ok": True, "id": int(data.get("id") or 0), "reactions": found})
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
            session = str(data.get("session") or uuid.uuid4().hex[:12])
            from_voice = bool(data.get("voice"))
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
                target=lambda: (stream_turn(state, session, text, events.put, from_voice=from_voice,
                                           client_audio=client_audio), events.put(None)),
                daemon=True,
            )
            worker.start()
            self._write({"event": "session", "session": session})
            while True:
                item = events.get()
                if item is None:
                    break
                if not self._write(item):
                    state.cancel.set()
                    break

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


def serve(model: str, port: int = 8765) -> tuple[ThreadingHTTPServer, AppState]:
    state = AppState(model)
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(state))
    server.daemon_threads = True
    return server, state


def shutdown(server: Any) -> None:
    """Stop everything the app started (also used by tests)."""
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
            print("Pedro_Agent is already running; switched to its window.", flush=True)
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
    print(f"Pedro_Agent chat app: {url}  (Ctrl+C to quit)", flush=True)
    bots.Scheduler().start()  # scheduled bot tasks
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
