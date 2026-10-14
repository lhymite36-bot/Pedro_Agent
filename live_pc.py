"""Live PC view: JPEG frames of the screen, an MJPEG stream, and a feed of
what the agent is doing (from agent_log events). Remote control is in
remote_access.py and is off unless rules.yaml allows it."""

from __future__ import annotations

import collections
import io
import threading
import time
from typing import Any, Callable

import rules

DEFAULTS = {"max_fps": 5, "default_fps": 3, "max_width": 1280, "jpeg_quality": 55}

# Tests replace: grabber() -> JPEG bytes
grabber: Callable[[], bytes | None] | None = None

_activity: "collections.deque[dict[str, Any]]" = collections.deque(maxlen=200)
_activity_lock = threading.Lock()
_seq = 0
_frame_lock = threading.Lock()
_last_frame: tuple[float, bytes] = (0.0, b"")


def settings() -> dict[str, Any]:
    cfg = rules.section("remote", {})
    out = dict(DEFAULTS)
    out.update({k: cfg[k] for k in DEFAULTS if k in cfg})
    return out


def clamp_fps(value: Any) -> float:
    cfg = settings()
    try:
        fps = float(value)
    except (TypeError, ValueError):
        fps = float(cfg["default_fps"])
    return max(0.5, min(float(cfg["max_fps"]) or 5.0, fps))


def _grab() -> bytes | None:
    if grabber is not None:
        return grabber()
    try:
        import mss
        from PIL import Image

        cfg = settings()
        with mss.mss() as sct:
            shot = sct.grab(sct.monitors[1])
        image = Image.frombytes("RGB", shot.size, shot.rgb)
        width = int(cfg["max_width"])
        if image.width > width:
            image = image.resize((width, int(image.height * width / image.width)))
        out = io.BytesIO()
        image.save(out, "JPEG", quality=int(cfg["jpeg_quality"]))
        return out.getvalue()
    except Exception:
        return None


def frame(max_age: float = 0.15) -> bytes | None:
    """Latest JPEG; viewers share one capture per max_age."""
    global _last_frame
    with _frame_lock:
        stamp, blob = _last_frame
        if blob and time.monotonic() - stamp < max_age:
            return blob
        blob = _grab() or b""
        _last_frame = (time.monotonic(), blob)
        return blob or None


def mjpeg(write: Callable[[bytes], Any], fps: float, stop: threading.Event | None = None,
          max_frames: int = 0, sleep: Callable[[float], None] = time.sleep) -> int:
    """Write multipart MJPEG parts until the client goes away. Returns frames sent."""
    sent = 0
    gap = 1.0 / clamp_fps(fps)
    while not (stop and stop.is_set()):
        blob = frame(gap * 0.8)
        if blob:
            try:
                write(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(len(blob)).encode() + b"\r\n\r\n" + blob + b"\r\n")
            except (BrokenPipeError, ConnectionError, OSError):
                break
            sent += 1
        if max_frames and sent >= max_frames:
            break
        sleep(gap)
    return sent


_SHOWN = {"tool": "Ran", "tool_error": "Failed", "tool_start": "Running", "model_switch": "Switched model",
          "team_plan": "Team planned", "final": "Answered"}


def note(kind: str, **fields: Any) -> None:
    global _seq
    if kind not in _SHOWN and kind not in {"activity"}:
        return
    text = fields.get("text") or " ".join(str(fields.get(k)) for k in ("tool", "model") if fields.get(k)) or ""
    if kind == "tool" and fields.get("ok") is False:
        kind = "tool_error"
    with _activity_lock:
        _seq += 1
        _activity.append({"id": _seq, "t": time.time(), "kind": kind,
                          "label": _SHOWN.get(kind, "Activity"), "text": str(text)[:200]})


def _on_log(record: dict[str, Any]) -> None:
    fields = {k: v for k, v in record.items() if k in {"tool", "ok", "model", "text"}}
    note(str(record.get("event")), **fields)


def attach() -> None:
    import agent_log

    agent_log.add_listener(_on_log)


def activity(after: int = 0) -> list[dict[str, Any]]:
    with _activity_lock:
        return [dict(a) for a in _activity if a["id"] > after]


def busy_text() -> str:
    items = activity()
    return items[-1]["label"] + " " + items[-1]["text"] if items else "Idle"
