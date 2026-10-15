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

DEFAULTS = {"max_fps": 30, "default_fps": 10, "max_width": 1280, "jpeg_quality": 55}
FPS_CHOICES = (1, 5, 10, 15, 30)

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
    return max(0.5, min(float(cfg["max_fps"]) or 30.0, fps))


_tls = threading.local()


def _raw() -> Any:
    """Screen as a PIL image, scaled to max_width. One mss handle per thread (fast)."""
    from PIL import Image

    sct = getattr(_tls, "sct", None)
    if sct is None:
        import mss

        sct = _tls.sct = mss.mss()
    shot = sct.grab(sct.monitors[1])
    image = Image.frombuffer("RGB", shot.size, shot.bgra, "raw", "BGRX", 0, 1)
    width = int(settings()["max_width"])
    if image.width > width:
        image = image.resize((width, int(image.height * width / image.width)), Image.BILINEAR)
    return image


def _encode(image: Any, quality: int, scale: float = 1.0) -> bytes:
    from PIL import Image

    if scale < 0.99:
        image = image.resize((max(320, int(image.width * scale)), max(180, int(image.height * scale))), Image.BILINEAR)
    out = io.BytesIO()
    image.save(out, "JPEG", quality=int(quality), optimize=False)
    return out.getvalue()


def _grab(quality: int | None = None, scale: float = 1.0) -> bytes | None:
    if grabber is not None:
        return grabber()
    try:
        return _encode(_raw(), quality or int(settings()["jpeg_quality"]), scale)
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


class Adaptive:
    """Per-viewer quality: if sending a frame takes longer than the frame gap
    (slow tunnel), drop JPEG quality and size; when it's fast again, step back up."""

    def __init__(self, base_quality: int, gap: float) -> None:
        self.q, self.scale, self.gap, self.good = int(base_quality), 1.0, gap, 0
        self.top = int(base_quality)
        self.max_scale = 1.0

    def update(self, send_seconds: float) -> None:
        if send_seconds > self.gap * 0.9:
            self.good = 0
            self.q = max(25, self.q - 8)
            if self.q <= 35:
                self.scale = max(0.5, self.scale * 0.85)
        else:
            self.good += 1
            if self.good >= 20:
                self.good = 0
                if self.scale < self.max_scale:
                    self.scale = min(self.max_scale, self.scale / 0.85)
                elif self.q < self.top:
                    self.q = min(self.top, self.q + 5)


def mjpeg(write: Callable[[bytes], Any], fps: float, stop: threading.Event | None = None,
          max_frames: int = 0, sleep: Callable[[float], None] = time.sleep,
          stats: dict[str, Any] | None = None) -> int:
    """Write multipart MJPEG parts on one persistent connection until the client
    goes away, pacing to fps with adaptive quality. Returns frames sent."""
    sent = 0
    gap = 1.0 / clamp_fps(fps)
    adapt = Adaptive(int(settings()["jpeg_quality"]), gap)
    if 1.0 / gap >= 24:   # 30 fps: smaller frames so capture+encode fits in 33 ms
        adapt.q, adapt.top, adapt.scale = min(adapt.q, 45), min(adapt.top, 45), 0.75
        adapt.max_scale = 0.75
    t0 = time.monotonic()
    # Pipeline: one thread grabs the screen while this one encodes + sends the
    # previous grab (both release the GIL), so capture and JPEG overlap.
    latest: dict[str, Any] = {}
    halt = threading.Event()
    have = threading.Event()

    def capture() -> None:
        while not halt.is_set():
            try:
                img = _raw()
                latest["img"], latest["n"] = img, latest.get("n", 0) + 1
                have.set()
            except Exception:
                time.sleep(0.05)
            time.sleep(0.001)

    seen = 0
    if grabber is None:
        threading.Thread(target=capture, name="live-capture", daemon=True).start()
    try:
      while not (stop and stop.is_set()):
        start = time.monotonic()
        if grabber is not None:
            blob = grabber()
        else:
            have.wait(1.0)
            while latest.get("n", 0) == seen and not (stop and stop.is_set()) and time.monotonic() - start < 1.0:
                time.sleep(0.003)   # wait for a fresh grab (never resend the same frame)
            seen = latest.get("n", 0)
            img = latest.get("img")
            try:
                blob = _encode(img, adapt.q, adapt.scale) if img is not None else None
            except Exception:
                blob = None
        if blob:
            w0 = time.monotonic()
            try:
                write(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(len(blob)).encode() + b"\r\n\r\n" + blob + b"\r\n")
            except (BrokenPipeError, ConnectionError, OSError):
                break
            adapt.update(time.monotonic() - w0)
            sent += 1
        if stats is not None:
            stats.update(frames=sent, fps=round(sent / max(1e-6, time.monotonic() - t0), 1), quality=adapt.q, scale=round(adapt.scale, 2))
        if max_frames and sent >= max_frames:
            break
        sleep(max(0.0, gap - (time.monotonic() - start)))
    finally:
        halt.set()
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


# Tests set this to record local pointer actions without moving the real mouse.
mouse_override: Callable[[str, dict[str, Any]], None] | None = None
_CONTROL_KINDS = {"click", "move", "down", "up", "scroll", "type", "drag"}


def _unit(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = 0.0
    return max(0.0, min(1.0, number))


def _ascii_type(text: str) -> str:
    return "".join(ch for ch in str(text or "")[:500] if 32 <= ord(ch) < 127)


def _scroll_steps(delta: Any) -> int:
    """Browser wheel deltaY is positive downward. pyautogui.scroll is positive upward."""
    try:
        amount = float(delta or 0)
    except (TypeError, ValueError):
        amount = 0.0
    steps = int(round(-amount / 40))
    if steps == 0 and amount:
        steps = -1 if amount > 0 else 1
    return max(-8, min(8, steps))


def _apply_mouse(kind: str, fields: dict[str, Any]) -> None:
    if mouse_override is not None:
        mouse_override(kind, fields)
        return
    import pyautogui

    pyautogui.FAILSAFE = True
    width, height = pyautogui.size()

    def px(x_norm: float, y_norm: float) -> tuple[int, int]:
        return (
            int(_unit(x_norm) * max(1, width - 1)),
            int(_unit(y_norm) * max(1, height - 1)),
        )

    if kind == "type":
        pyautogui.write(str(fields.get("text") or ""), interval=0.01)
        return
    if kind == "scroll":
        x, y = px(fields["x"], fields["y"])
        pyautogui.scroll(int(fields.get("steps") or 0), x=x, y=y)
        return
    x, y = px(fields["x"], fields["y"])
    button = fields.get("button") or "left"
    if kind == "click":
        pyautogui.click(x, y, button=button)
    elif kind == "move":
        pyautogui.moveTo(x, y)
    elif kind == "down":
        pyautogui.moveTo(x, y)
        pyautogui.mouseDown(button=button)
    elif kind == "up":
        pyautogui.moveTo(x, y)
        pyautogui.mouseUp(button=button)
    elif kind == "drag":
        x2, y2 = px(fields.get("x2", fields["x"]), fields.get("y2", fields["y"]))
        pyautogui.moveTo(x, y)
        pyautogui.dragTo(x2, y2, duration=0.12, button=button)


def local_control(data: dict[str, Any] | None) -> dict[str, Any]:
    """Clicks, drags, scrolls, and typing from Live PC on this PC or a signed-in phone."""
    data = data if isinstance(data, dict) else {}
    kind = str(data.get("type") or "").casefold()
    if kind not in _CONTROL_KINDS:
        return {"ok": False, "error": "Unknown control."}
    try:
        if kind == "type":
            value = _ascii_type(str(data.get("text") or ""))
            _apply_mouse("type", {"text": value})
            return {"ok": True, "message": f"Typed {len(value)} characters."}
        x, y = _unit(data.get("x")), _unit(data.get("y"))
        if kind == "scroll":
            steps = _scroll_steps(data.get("delta"))
            _apply_mouse("scroll", {"x": x, "y": y, "steps": steps})
            return {"ok": True, "message": f"Scrolled {steps}."}
        button = "right" if str(data.get("button") or "").casefold() == "right" else "left"
        fields: dict[str, Any] = {"x": x, "y": y, "button": button}
        if kind == "drag":
            fields["x2"] = _unit(data.get("x2") if data.get("x2") is not None else x)
            fields["y2"] = _unit(data.get("y2") if data.get("y2") is not None else y)
        _apply_mouse(kind, fields)
        return {"ok": True, "message": kind}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
