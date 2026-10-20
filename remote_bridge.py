"""Phone bridge. Telegram can ask the agent a question. Discord can receive alerts.

Nothing is contacted unless TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are set,
or DISCORD_WEBHOOK_URL is set. Tests pass remote_transport_override and never
open a socket. Tokens and webhook URLs are not printed.

A Telegram voice note (the Bot API voice field, the same messages a
filters.VOICE handler selects) is downloaded, transcribed, and run through
the agent. The text answer is sent back to that chat. No voice message is
sent. A reaction is added only when TELEGRAM_VOICE_REACTION is 👍 or 🤖.
"""

from __future__ import annotations

import io
import json
import os
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any

_stop = threading.Event()
_thread: threading.Thread | None = None
_offset = 0
_lock = threading.Lock()
# Set by the chat app so Telegram turns share its agent state and history:
# answer_handler(text) -> reply; history_hook(role, text) logs side replies.
answer_handler: Any = None
history_hook: Any = None
# Callbacks given every incoming Telegram text (autopilot telegram watchers).
message_listeners: list[Any] = []
_console_history: list[Any] = []
_instance_lock_handle: Any = None
_conflict_logged = False
NEGATIVE = {"no", "nope", "cancel", "stop", "don't", "dont", "n"}
_SCREENSHOT_REQUEST = re.compile(
    r"""
    \A\s*
    (?:please\s+)?
    (?:(?:can|could|will)\s+you\s+)?
    (?:please\s+)?
    (?:
        /screenshot(?:@\w+)?
        | (?:send|take|snap|capture)(?:\s+me)?(?:\s+a)?\s+screenshot
        | send(?:\s+me)?(?:\s+a)?\s+(?:picture|photo|image)\s+of\s+my\s+screen
        | show(?:\s+me)?\s+my\s+screen
        | what(?:'s|’s|s|\s+is)\s+on\s+my\s+screen
        | screenshot
    )
    \s*(?:please\s*)?[.!?]*\s*
    \Z
    """,
    re.IGNORECASE | re.VERBOSE,
)
_PC_CAMERA_REQUEST = re.compile(
    r"""
    \A\s*
    (?:please\s+)?
    (?:(?:can|could|will)\s+you\s+)?
    (?:please\s+)?
    (?:
        /pc_camera(?:@\w+)?
        | show(?:\s+me)?\s+what\s+your\s+computer\s+camera\s+sees
        | send(?:\s+me)?(?:\s+the)?\s+live\s+pc\s+camera\s+feed
        | what\s+is\s+your\s+computer\s+seeing
    )
    \s*(?:please\s*)?[.!?]*\s*
    \Z
    """,
    re.IGNORECASE | re.VERBOSE,
)
_PHONE_CAMERA_REQUEST = re.compile(
    r"""
    \A\s*
    (?:please\s+)?
    (?:(?:can|could|will)\s+you\s+)?
    (?:please\s+)?
    (?:
        /phone_camera(?:@\w+)?
        | look\s+at\s+me\s+through\s+my\s+phone
        | start(?:\s+the)?\s+phone\s+video\s+feed
        | look\s+at\s+me\s+live
    )
    \s*(?:please\s*)?[.!?]*\s*
    \Z
    """,
    re.IGNORECASE | re.VERBOSE,
)
_STOP_CAMERA_REQUEST = re.compile(
    r"""
    \A\s*
    (?:please\s+)?
    (?:(?:can|could|will)\s+you\s+)?
    (?:please\s+)?
    (?:
        /stop_camera(?:@\w+)?
        | stop(?:\s+the)?\s+live\s+(?:camera|video|stream)
        | stop(?:\s+the)?\s+(?:pc|phone)\s+camera
        | stop(?:\s+the)?\s+camera(?:\s+feed)?
    )
    \s*(?:please\s*)?[.!?]*\s*
    \Z
    """,
    re.IGNORECASE | re.VERBOSE,
)
_MAX_VOICE_BYTES = 8 * 1024 * 1024
_MAX_VOICE_SECONDS = 600
_MAX_VOICE_TEXT = 8000
_VOICE_FILE_ID = re.compile(r"^[A-Za-z0-9_-]{8,512}$")
_VOICE_PATH = re.compile(r"^(?:voice|audio)/[A-Za-z0-9._-]{1,180}\.(?:ogg|oga|opus)$")
_VOICE_MIME = {"audio/ogg", "audio/opus", "application/ogg"}
_VOICE_REACTIONS = {"👍", "🤖"}


class _RefuseRedirect(urllib.request.HTTPRedirectHandler):
    """Voice downloads must stay on the Telegram file host."""

    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        raise RuntimeError("The voice download was redirected.")


def _agent() -> Any:
    import agent_core

    return agent_core


def _token() -> str:
    return os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()


def _chat_id() -> str:
    return os.environ.get("TELEGRAM_CHAT_ID", "").strip()


def _webhook() -> str:
    return os.environ.get("DISCORD_WEBHOOK_URL", "").strip()


def paired() -> bool:
    return bool(_token() and _chat_id())


def alerts_configured() -> bool:
    return paired() or bool(_webhook())


def _scrubbed(text: str) -> str:
    agent = _agent()
    safe = agent._scrub(text or "")
    token = _token()
    hook = _webhook()
    if token:
        safe = safe.replace(token, "[redacted]")
    if hook:
        safe = safe.replace(hook, "[redacted]")
    return safe


def _http(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    agent = _agent()
    if agent.remote_transport_override is not None:
        result = agent.remote_transport_override(kind, payload)
        if not isinstance(result, dict):
            raise RuntimeError("The remote bridge returned nothing.")
        return result
    if kind in {"telegram_photo", "discord_photo"}:
        return _post_photo(kind, payload)
    if kind == "telegram_updates":
        query = urllib.parse.urlencode(
            {"offset": payload.get("offset", 0), "timeout": 0}
        )
        url = f"https://api.telegram.org/bot{_token()}/getUpdates?{query}"
        with urllib.request.urlopen(url, timeout=15) as response:
            return json.loads(response.read().decode("utf-8"))
    body = json.dumps(payload.get("body") or {}).encode("utf-8")
    if kind == "telegram_send":
        url = f"https://api.telegram.org/bot{_token()}/sendMessage"
    elif kind == "telegram_reaction":
        url = f"https://api.telegram.org/bot{_token()}/setMessageReaction"
    elif kind == "telegram_file":
        url = f"https://api.telegram.org/bot{_token()}/getFile"
    elif kind == "discord":
        url = _webhook()
    else:
        raise RuntimeError("Unknown remote bridge call.")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        raw = response.read().decode("utf-8")
    if not raw:
        return {"ok": True}
    return json.loads(raw)


def wants_screenshot(text: str) -> bool:
    """True for /screenshot and the short screen requests from the phone."""
    return _SCREENSHOT_REQUEST.match(text or "") is not None


def wants_pc_camera(text: str) -> bool:
    """True only for a full message that asks for the PC webcam feed."""
    return _PC_CAMERA_REQUEST.match(text or "") is not None


def wants_phone_camera(text: str) -> bool:
    """True only for a full message that asks for the phone camera page."""
    return _PHONE_CAMERA_REQUEST.match(text or "") is not None


def wants_stop_camera(text: str) -> bool:
    """True only for a full message that stops a live camera feed."""
    return _STOP_CAMERA_REQUEST.match(text or "") is not None


def _photo_body(
    fields: dict[str, str],
    file_field: str,
    filename: str,
    mime: str,
    image: bytes,
) -> tuple[bytes, str]:
    boundary = "phone" + uuid.uuid4().hex
    chunks: list[bytes] = []
    for key, value in fields.items():
        chunks.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode(
                "utf-8"
            )
        )
    chunks.append(
        (
            f'--{boundary}\r\nContent-Disposition: form-data; name="{file_field}"; '
            f'filename="{filename}"\r\nContent-Type: {mime}\r\n\r\n'
        ).encode("utf-8")
        + image
        + b"\r\n"
    )
    chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def _telegram_jpeg(image: bytes) -> bytes:
    """Baseline 4:2:0 JPEG. A 4:4:4 screenshot is accepted and then not shown."""
    try:
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError(
            "pillow is not installed. From the project folder run: "
            ".\\.venv\\Scripts\\python.exe -m pip install pillow"
        ) from exc
    try:
        picture = Image.open(io.BytesIO(image))
        picture.load()
    except Exception as exc:
        raise RuntimeError("The screenshot could not be prepared for the phone.") from exc
    if picture.mode != "RGB":
        picture = picture.convert("RGB")
    width, height = picture.size
    if width < 1 or height < 1:
        raise RuntimeError("The screenshot was empty.")
    if width % 2 or height % 2:
        picture = picture.resize((max(2, width - (width % 2)), max(2, height - (height % 2))))
    buffer = io.BytesIO()
    picture.save(buffer, format="JPEG", quality=80, subsampling=2, optimize=True)
    data = buffer.getvalue()
    if len(data) < 16 or not data.startswith(b"\xff\xd8"):
        raise RuntimeError("The screenshot could not be prepared for the phone.")
    return data


def _telegram_failure(exc: urllib.error.HTTPError) -> str:
    """Telegram's description, without the request URL."""
    raw = ""
    try:
        try:
            raw = exc.read().decode("utf-8", errors="replace")
        except Exception:
            raw = ""
    finally:
        try:
            exc.close()
        except Exception:
            pass
    if raw:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict) and parsed.get("description"):
            return str(parsed["description"])[:300]
        if raw.strip():
            return raw.strip()[:300]
    return f"Telegram rejected the screenshot ({exc.code})."


def _post_photo(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    image = payload.get("image")
    if not isinstance(image, (bytes, bytearray)) or not image:
        raise RuntimeError("The screenshot was empty.")
    image = _telegram_jpeg(bytes(image))
    filename = "screen.jpg"
    mime = "image/jpeg"
    caption = str(payload.get("caption") or "Here is the screen.")
    if kind == "telegram_photo":
        url = f"https://api.telegram.org/bot{_token()}/sendPhoto"
        body, content_type = _photo_body(
            {"chat_id": str(payload.get("chat_id") or _chat_id()), "caption": caption},
            "photo",
            filename,
            mime,
            image,
        )
    elif kind == "discord_photo":
        url = _webhook()
        body, content_type = _photo_body(
            {"payload_json": json.dumps({"content": caption})},
            "files[0]",
            filename,
            mime,
            image,
        )
    else:
        raise RuntimeError("Unknown remote bridge call.")
    request = urllib.request.Request(url, data=body, method="POST")
    request.add_header("Content-Type", content_type)
    request.add_header("Content-Length", str(len(body)))
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        raise RuntimeError(_telegram_failure(exc)) from None
    if kind == "discord_photo":
        if not raw:
            return {"ok": True}
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {"ok": True}
        return parsed if isinstance(parsed, dict) else {"ok": True}
    if not raw:
        raise RuntimeError("Telegram returned an empty response.")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Telegram returned an unreadable response.") from exc
    result = parsed.get("result") if isinstance(parsed, dict) else None
    photo = result.get("photo") if isinstance(result, dict) else None
    if not isinstance(parsed, dict) or not parsed.get("ok") or not photo:
        description = "Telegram did not return a picture."
        if isinstance(parsed, dict) and parsed.get("description"):
            description = str(parsed["description"])
        raise RuntimeError(description)
    return parsed


def _text_back(chat_id: str, text: str) -> None:
    if not (_chat_id() or chat_id):
        return
    _http(
        "telegram_send",
        {"body": {"chat_id": chat_id, "text": _scrubbed(text)[:1800] or "The screenshot failed."}},
    )


def _capture_phone_photo() -> tuple[Path, bytes, str]:
    agent = _agent()
    shot = agent.take_screenshot()
    if not isinstance(shot, dict) or not shot.get("ok"):
        detail = "The screen capture failed."
        if isinstance(shot, dict) and shot.get("error"):
            detail = str(shot.get("error"))
        raise RuntimeError(detail)
    data = shot.get("_screenshot_bytes")
    if not isinstance(data, (bytes, bytearray)) or not data:
        raise RuntimeError("The screen capture returned no image.")
    mime = str(shot.get("_screenshot_mime") or "image/jpeg")
    suffix = ".jpg" if "jpeg" in mime or "jpg" in mime else ".png"
    folder = agent.WORKSPACE / "screenshots"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"phone-{uuid.uuid4().hex}{suffix}"
    path.write_bytes(bytes(data))
    return path, bytes(data), mime


def _deliver_screenshot() -> dict[str, Any]:
    """Capture the primary screen and upload it. The temp file is removed."""
    agent = _agent()
    chat_id = _chat_id()
    path: Path | None = None
    try:
        path, image, mime = _capture_phone_photo()
        caption = "Here is the screen."
        filename = path.name
        sent: list[str] = []
        if paired() or chat_id:
            _http(
                "telegram_photo",
                {
                    "chat_id": chat_id,
                    "caption": caption,
                    "filename": filename,
                    "mime": mime,
                    "image": image,
                },
            )
            sent.append("telegram")
        if _webhook():
            try:
                _http(
                    "discord_photo",
                    {
                        "caption": caption,
                        "filename": filename,
                        "mime": mime,
                        "image": image,
                    },
                )
                sent.append("discord")
            except AssertionError:
                raise
            except Exception as exc:
                print(f"[phone] {_scrubbed(str(exc))}", flush=True)
        if not sent:
            return agent._err("The phone bridge is not set up.")
        print("[phone] Sent a screenshot.", flush=True)
        return agent._ok("Sent the screenshot to your phone.", channels=sent)
    except AssertionError:
        raise
    except Exception as exc:
        detail = _scrubbed(str(exc)) or "The screenshot failed."
        print(f"[phone] {detail}", flush=True)
        try:
            if chat_id:
                _text_back(chat_id, detail)
        except Exception:
            pass
        return agent._err(detail)
    finally:
        if path is not None:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass


def _run_live(kind: str) -> dict[str, Any]:
    import live_video

    if kind == "pc":
        return live_video.stream_pc_camera()
    if kind == "phone":
        return live_video.stream_phone_camera()
    return live_video.stop_live_feeds()


def _schedule_live(kind: str) -> dict[str, Any]:
    """Start or stop a feed off the poller. Tests with a fake transport run inline."""
    agent = _agent()
    if agent.remote_transport_override is not None:
        return _run_live(kind)

    def _worker() -> None:
        try:
            _run_live(kind)
        except Exception as exc:
            print(f"[phone] {_scrubbed(str(exc))}", flush=True)

    worker = threading.Thread(target=_worker, name="phone-live", daemon=True)
    worker.start()
    return agent._ok("The live video request is starting.", status="started")


def _schedule_screenshot() -> dict[str, Any]:
    """Upload off the caller. Tests with a fake transport run inline."""
    agent = _agent()
    if agent.remote_transport_override is not None:
        return _deliver_screenshot()

    def _worker() -> None:
        try:
            _deliver_screenshot()
        except Exception as exc:
            print(f"[phone] {_scrubbed(str(exc))}", flush=True)

    worker = threading.Thread(target=_worker, name="phone-photo", daemon=True)
    worker.start()
    return agent._ok("The screenshot is being sent.", status="started")


def _log(role: str, text: str) -> None:
    if history_hook is not None:
        try:
            history_hook(role, text)
        except Exception:
            pass


def _confirm_reply(text: str) -> str | None:
    """A yes/no answer to a waiting confirm-before action, or None.

    "yes" runs the waiting action right away (no second model call);
    "no" cancels it. Any other text cancels it and is handled normally.
    """
    import confirm_action

    waiting = confirm_action.pending()
    if waiting is None:
        return None
    folded = " ".join((text or "").casefold().split()).strip(" .!?")
    agent = _agent()
    if folded in confirm_action.POSITIVE:
        _log("user", text)
        agent.begin_task_turn(text)  # grants the waiting action
        result = agent.invoke_tool(waiting["name"], waiting["arguments"])
        detail = str(result.get("message") or result.get("error") or "")
        reply = ("Done: " if result.get("ok") else "That failed: ") + detail
        _log("assistant", reply)
        return reply
    if folded in NEGATIVE:
        _log("user", text)
        confirm_action.note_user_text(text)  # cancels it
        reply = f"Cancelled: {waiting.get('label') or waiting['name']}."
        _log("assistant", reply)
        return reply
    return None


def _with_confirm_hint(reply: str) -> str:
    import confirm_action

    waiting = confirm_action.pending()
    if waiting is not None and "reply yes" not in reply.casefold():
        reply = f"{reply}\n\nReply yes to {waiting.get('label') or 'go ahead'}, or no to cancel."
    return reply


def _answer(text: str) -> str:
    agent = _agent()
    for listener in list(message_listeners):
        try:
            listener(text)
        except Exception:
            pass
    confirmed = _confirm_reply(text)
    if confirmed is not None:
        return _scrubbed(confirmed)[:3500]
    if agent.remote_reply_override is not None:
        reply = agent.remote_reply_override(text)
        return _scrubbed(_with_confirm_hint(str(reply or "")))[:3500]
    if answer_handler is not None:
        reply = answer_handler(text)
        return _scrubbed(_with_confirm_hint(str(reply or "")))[:3500]
    import agent_core

    # One running conversation per process, so "yes" follow-ups have context.
    answer = agent_core.run_agent(text, _console_history, os.environ.get("GEMINI_MODEL", agent_core.DEFAULT_MODEL))
    del _console_history[:-40]
    return _scrubbed(_with_confirm_hint(str(answer or "")))[:3500]


def notify(text: str) -> dict[str, Any]:
    """Send a status line to Discord and Telegram when either is configured."""
    agent = _agent()
    message = _scrubbed(text)[:1800]
    if not message:
        return agent._err("A message is required.")
    if not alerts_configured() and agent.remote_transport_override is None:
        return agent._err(
            "The phone bridge is not set up. Set TELEGRAM_BOT_TOKEN and "
            "TELEGRAM_CHAT_ID, or DISCORD_WEBHOOK_URL, in the environment."
        )
    sent: list[str] = []
    try:
        if _webhook():
            _http("discord", {"body": {"content": message}})
            sent.append("discord")
        if paired():
            _http(
                "telegram_send",
                {"body": {"chat_id": _chat_id(), "text": message}},
            )
            sent.append("telegram")
    except Exception as exc:
        return agent._err(f"The phone bridge could not send that. {_scrubbed(str(exc))}")
    if not sent:
        return agent._err("The phone bridge is not set up.")
    return agent._ok("Sent the update to your phone.", channels=sent)


def send_remote_update(message: str) -> dict[str, Any]:
    """Tool entry. The message is a status line, not a shell command."""
    return notify(message)


def _voice_reaction() -> str:
    """👍 or 🤖 when asked. Empty means the chat stays quiet."""
    value = os.environ.get("TELEGRAM_VOICE_REACTION", "").strip()
    if value in _VOICE_REACTIONS:
        return value
    return ""


def _safe_voice_path(file_path: str) -> str:
    text = (file_path or "").strip().replace("\\", "/")
    if _VOICE_PATH.fullmatch(text) is None:
        raise RuntimeError("The voice file path was rejected.")
    return text


def _checked_ogg(data: Any) -> bytes:
    if not isinstance(data, (bytes, bytearray)):
        raise RuntimeError("The voice note could not be downloaded.")
    raw = bytes(data)
    if len(raw) < 16 or len(raw) > _MAX_VOICE_BYTES:
        raise RuntimeError("The voice note was empty or too large.")
    if not raw.startswith(b"OggS"):
        raise RuntimeError("The voice note was not an ogg file.")
    return raw


def _read_telegram_file(file_path: str) -> bytes:
    """Download one voice file. The bot token stays in the URL and out of logs."""
    safe = _safe_voice_path(file_path)
    token = _token()
    quoted = urllib.parse.quote(safe, safe="/")
    url = f"https://api.telegram.org/file/bot{token}/{quoted}"
    request = urllib.request.Request(url, method="GET")
    opener = urllib.request.build_opener(_RefuseRedirect)
    try:
        with opener.open(request, timeout=20) as response:
            final = response.geturl() if hasattr(response, "geturl") else url
            host = urllib.parse.urlparse(str(final)).hostname or ""
            if host != "api.telegram.org":
                raise RuntimeError("The voice download left Telegram.")
            raw = response.read(_MAX_VOICE_BYTES + 1)
    except AssertionError:
        raise
    except Exception as exc:
        raise RuntimeError(
            f"The voice note could not be downloaded. {_scrubbed(str(exc))}"
        ) from exc
    return _checked_ogg(raw)


def _download_voice_file(file_path: str) -> bytes:
    safe = _safe_voice_path(file_path)
    agent = _agent()
    if agent.remote_transport_override is not None:
        result = agent.remote_transport_override("telegram_download", {"file_path": safe})
        if not isinstance(result, dict):
            raise RuntimeError("The voice note could not be downloaded.")
        return _checked_ogg(result.get("data"))
    return _read_telegram_file(safe)


def _fetch_voice_bytes(voice: dict[str, Any]) -> bytes:
    """getFile plus the ogg bytes for one Telegram voice note."""
    file_id = str(voice.get("file_id") or "")
    if _VOICE_FILE_ID.fullmatch(file_id) is None:
        raise RuntimeError("The voice note id was rejected.")
    mime = str(voice.get("mime_type") or "").split(";", 1)[0].strip().casefold()
    if mime and mime not in _VOICE_MIME:
        raise RuntimeError("That message is not a voice note.")
    duration = voice.get("duration")
    if type(duration) is int and (duration < 0 or duration > _MAX_VOICE_SECONDS):
        raise RuntimeError("The voice note is too long.")
    size = voice.get("file_size")
    if type(size) is int and (size < 16 or size > _MAX_VOICE_BYTES):
        raise RuntimeError("The voice note was empty or too large.")
    info = _http("telegram_file", {"body": {"file_id": file_id}})
    result = info.get("result") if isinstance(info, dict) else None
    if not isinstance(info, dict) or not info.get("ok") or not isinstance(result, dict):
        raise RuntimeError("Telegram did not return the voice file.")
    remote_size = result.get("file_size")
    if type(remote_size) is int and (remote_size < 16 or remote_size > _MAX_VOICE_BYTES):
        raise RuntimeError("The voice note was empty or too large.")
    return _download_voice_file(str(result.get("file_path") or ""))


def _write_voice_file(data: bytes) -> Path:
    agent = _agent()
    folder = agent.WORKSPACE / "scribe"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"telegram-voice-{uuid.uuid4().hex[:8]}.ogg"
    path.write_bytes(data)
    return path


def _whisper_file(path: Path) -> str | None:
    """Local whisper text, or None when neither package is installed."""
    try:
        import whisper
    except ImportError:
        whisper = None
    if whisper is not None:
        model = whisper.load_model("base")
        result = model.transcribe(str(path))
        if isinstance(result, dict):
            return str(result.get("text") or "")
        return str(result or "")
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        return None
    model = WhisperModel("base", device="cpu", compute_type="int8")
    segments, _info = model.transcribe(str(path))
    return " ".join(segment.text.strip() for segment in segments)


def _local_whisper_text(data: bytes) -> str | None:
    """Transcribe on this PC. None means whisper is not installed."""
    path: Path | None = None
    try:
        probe = _whisper_file_available()
        if not probe:
            return None
        path = _write_voice_file(data)
        heard = _whisper_file(path)
        if heard is None:
            return None
        return heard
    finally:
        if path is not None:
            try:
                path.unlink()
            except OSError:
                pass


def _whisper_file_available() -> bool:
    try:
        import whisper  # noqa: F401
    except ImportError:
        whisper = None
    if whisper is not None:
        return True
    try:
        from faster_whisper import WhisperModel  # noqa: F401
    except ImportError:
        return False
    return True


def _gemini_transcription_allowed() -> bool:
    if os.environ.get("PRIVACY_MODE", "").strip() == "1":
        return False
    if os.environ.get("LOCAL_LLM", "").strip() == "1":
        return False
    agent = _agent()
    if agent.network_up_override is False:
        return False
    return True


def _transcribe_with_gemini(data: bytes) -> str:
    """One transcription call. Tests pass genai_client_override and do not go online."""
    agent = _agent()
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if agent.genai_client_override is None and not api_key:
        raise RuntimeError(
            "A voice note could not be transcribed. A local whisper package is "
            "not installed, and GEMINI_API_KEY is not set."
        )
    from google import genai
    from google.genai import types

    if agent.genai_client_override is not None:
        client = agent.genai_client_override(api_key or "test")
    else:
        client = genai.Client(api_key=api_key)
    model = os.environ.get("GEMINI_MODEL", agent.DEFAULT_MODEL)
    response = client.models.generate_content(
        model=model,
        contents=[
            types.Part.from_bytes(data=data, mime_type="audio/ogg"),
            "Transcribe this voice note. Return only the spoken words.",
        ],
    )
    return agent._text_from(response)


def _transcribe_voice(data: bytes) -> str:
    agent = _agent()
    if agent.telegram_voice_transcriber_override is not None:
        text = agent.telegram_voice_transcriber_override(data)
        return "" if text is None else str(text).strip()
    local = _local_whisper_text(data)
    if local is not None:
        return local.strip()
    if not _gemini_transcription_allowed():
        raise RuntimeError(
            "This voice note stays on this PC, and a local transcription model is not installed."
        )
    return _transcribe_with_gemini(data).strip()


def _maybe_react(chat_id: str, message_id: int) -> None:
    """Acknowledge with a reaction only. A failure does not send a chat message."""
    emoji = _voice_reaction()
    if not emoji or message_id <= 0:
        return
    try:
        _http(
            "telegram_reaction",
            {
                "body": {
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "reaction": [{"type": "emoji", "emoji": emoji}],
                }
            },
        )
    except AssertionError:
        raise
    except Exception as exc:
        print(f"[phone] {_scrubbed(str(exc))}", flush=True)


def _send_chat_text(chat_id: str, text: str) -> None:
    """Post one text answer. Voice notes never go back out as audio."""
    message = _scrubbed(text).strip()[:3500] or "Done."
    _http("telegram_send", {"body": {"chat_id": chat_id, "text": message}})


def _voice_worker(text: str, chat_id: str) -> None:
    try:
        _send_chat_text(chat_id, _answer(text))
    except Exception as exc:
        print(f"[phone] {_scrubbed(str(exc))}", flush=True)
        try:
            _send_chat_text(chat_id, "I could not run that voice note.")
        except Exception as send_exc:
            print(f"[phone] {_scrubbed(str(send_exc))}", flush=True)


def _dispatch_voice_command(text: str, chat_id: str) -> None:
    """Run the transcript and send the text answer to the same chat."""
    agent = _agent()
    if agent.remote_transport_override is not None:
        _send_chat_text(chat_id, _answer(text))
        return
    worker = threading.Thread(
        target=_voice_worker,
        args=(text, chat_id),
        name="phone-voice",
        daemon=True,
    )
    worker.start()


def _handle_voice_note(message: dict[str, Any], chat_id: str) -> bool:
    """Download, transcribe, run, and answer one voice note in text."""
    try:
        data = _fetch_voice_bytes(message.get("voice") or {})
        text = _transcribe_voice(data).replace("\x00", "").strip()
        if not text or re.search(r"[A-Za-z0-9]", text) is None:
            print("[phone] Voice note had no speech.", flush=True)
            return False
        if len(text) > _MAX_VOICE_TEXT:
            print("[phone] Voice note was too long to run.", flush=True)
            return False
        message_id = int(message.get("message_id") or 0)
        _maybe_react(chat_id, message_id)
        _dispatch_voice_command(text, chat_id)
        print("[phone] Ran a voice note.", flush=True)
        return True
    except AssertionError:
        raise
    except Exception as exc:
        print(f"[phone] {_scrubbed(str(exc))}", flush=True)
        return False


def poll_once() -> dict[str, Any]:
    """Read one Telegram batch. Messages from other chats are ignored."""
    global _offset
    agent = _agent()
    if not paired() and agent.remote_transport_override is None:
        return agent._err("Telegram is not paired. Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID.")
    if not _chat_id():
        return agent._err("Set TELEGRAM_CHAT_ID to the chat that is allowed to give commands.")
    try:
        with _lock:
            offset = _offset
        payload = _http("telegram_updates", {"offset": offset})
    except Exception as exc:
        global _conflict_logged
        if "409" in str(exc):
            if not _conflict_logged:
                _conflict_logged = True
                print("[phone] Another copy of the bot is polling Telegram (409). "
                      "Close the other Ped Bot window.", flush=True)
            return agent._err("Telegram conflict (409): another bridge is polling.", conflict=True)
        return agent._err(f"Telegram could not be reached. {_scrubbed(str(exc))}")
    updates = payload.get("result") if isinstance(payload, dict) else None
    if not isinstance(updates, list):
        return agent._err("Telegram returned an unexpected update list.")
    replied = 0
    voice_ran = 0
    allowed = _chat_id()
    for update in updates:
        if not isinstance(update, dict):
            continue
        update_id = int(update.get("update_id") or 0)
        with _lock:
            _offset = max(_offset, update_id + 1)
        message = update.get("message") if isinstance(update.get("message"), dict) else {}
        chat = message.get("chat") if isinstance(message.get("chat"), dict) else {}
        if str(chat.get("id", "")) != allowed:
            continue
        voice = message.get("voice") if isinstance(message.get("voice"), dict) else None
        if voice:
            if _handle_voice_note(message, allowed):
                voice_ran += 1
            continue
        text = str(message.get("text") or "").strip()
        if not text:
            continue
        if wants_screenshot(text):
            _log("user", text)
            _log("assistant", "[sent a screenshot to Telegram]")
            _schedule_screenshot()
            replied += 1
            print("[phone] Answered a screenshot request.", flush=True)
            continue
        if wants_stop_camera(text):
            _schedule_live("stop")
            replied += 1
            print("[phone] Stopped the live camera.", flush=True)
            continue
        if wants_pc_camera(text):
            _schedule_live("pc")
            replied += 1
            print("[phone] Answered a PC camera request.", flush=True)
            continue
        if wants_phone_camera(text):
            _schedule_live("phone")
            replied += 1
            print("[phone] Answered a phone camera request.", flush=True)
            continue
        reply = _answer(text)
        try:
            _http("telegram_send", {"body": {"chat_id": allowed, "text": reply or "Done."}})
        except Exception as exc:
            return agent._err(f"Telegram could not deliver the reply. {_scrubbed(str(exc))}")
        replied += 1
        print(f"[phone] Answered a Telegram message.", flush=True)
    return agent._ok(
        f"Checked Telegram. Replied to {replied} message(s).",
        replied=replied,
        voice=voice_ran,
    )


def _loop() -> None:
    while not _stop.is_set():
        wait = 2
        try:
            result = poll_once()
            if isinstance(result, dict) and result.get("conflict"):
                wait = 30
        except Exception as exc:
            print(f"[phone] {_scrubbed(str(exc))}", flush=True)
        _stop.wait(wait)


def _lock_path() -> Path:
    import agent_config

    folder = agent_config.storage_dir()
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "telegram_bridge.lock"


def _acquire_instance_lock() -> bool:
    """One poller per PC: an OS file lock, released automatically if the process dies."""
    global _instance_lock_handle
    if _instance_lock_handle is not None:
        return True
    handle = open(_lock_path(), "a+")
    try:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return False
    _instance_lock_handle = handle
    return True


def _release_instance_lock() -> None:
    global _instance_lock_handle
    handle = _instance_lock_handle
    _instance_lock_handle = None
    if handle is None:
        return
    try:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass
    handle.close()


def bridge_running() -> bool:
    return _thread is not None and _thread.is_alive()


def start_remote_bridge() -> None:
    """Start the Telegram listener when a chat is paired. Alerts need no thread."""
    global _thread
    if not paired():
        return
    if _thread is not None and _thread.is_alive():
        return
    if not _acquire_instance_lock():
        print("[phone] Telegram bridge is already running in another Ped Bot "
              "window; this one will not poll.", flush=True)
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="phone-bridge", daemon=True)
    _thread.start()
    print("[phone] Telegram bridge is listening.", flush=True)


def stop_remote_bridge() -> None:
    global _thread
    _stop.set()
    thread = _thread
    if thread is not None and thread.is_alive() and thread is not threading.current_thread():
        thread.join(timeout=2)
    _thread = None
    _release_instance_lock()


def reset_remote_bridge() -> None:
    """Stop the listener and forget the update offset. Used by tests."""
    global _offset
    stop_remote_bridge()
    with _lock:
        _offset = 0
