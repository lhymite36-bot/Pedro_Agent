"""Live video avatar → OBS Virtual Camera + optional VB-Cable mic.

The twin only talks when Pedro presses Speak for me, or in Q&A mode after
each approved answer. Frames always carry a small “AI assistant” label.
"""

from __future__ import annotations

import threading
import time
from typing import Any

_lock = threading.Lock()
_stop = threading.Event()
_thread: threading.Thread | None = None
_state: dict[str, Any] = {
    "running": False,
    "mode": "push",  # push = Speak for me; qa = approve each answer
    "label": "AI assistant",
    "last_said": "",
    "pending_answer": "",
    "engine": "",
    "error": "",
}
send_fn = None  # tests: fn(frame) -> None


def _detect() -> dict[str, Any]:
    cam = False
    try:
        import pyvirtualcam  # noqa: F401
        cam = True
    except Exception:
        cam = False
    cable = False
    try:
        import pygame
        pygame.mixer.init()
        names = []
        try:
            import pygame._sdl2.audio as sdl_audio
            names = list(sdl_audio.get_audio_device_names(False) or [])
        except Exception:
            names = []
        cable = any("cable" in str(n).casefold() for n in names)
    except Exception:
        cable = False
    return {
        "virtual_cam": cam,
        "vb_cable": cable,
        "note": (
            "Install free OBS Studio (and enable its Virtual Camera) plus optional VB-Audio Cable. "
            "In Zoom/Meet pick “OBS Virtual Camera” and “CABLE Output”."
        ),
    }


def status() -> dict[str, Any]:
    det = _detect()
    with _lock:
        snap = dict(_state)
    snap.update(ok=True, detect=det)
    return snap


def _label_frame(frame: Any) -> Any:
    """Draw a small AI assistant badge on a numpy RGB frame."""
    try:
        import cv2
        import numpy as np
        if frame is None:
            frame = np.zeros((720, 1280, 3), dtype=np.uint8)
            frame[:] = (14, 15, 17)
        img = frame.copy()
        h, w = img.shape[:2]
        cv2.rectangle(img, (16, 16), (220, 58), (20, 20, 20), -1)
        cv2.putText(img, "AI assistant", (28, 46), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2, cv2.LINE_AA)
        return img
    except Exception:
        return frame


def _blank() -> Any:
    try:
        import numpy as np
        import cv2
        img = np.zeros((720, 1280, 3), dtype=np.uint8)
        img[:] = (14, 15, 17)
        cv2.putText(img, "Ped Bot", (520, 360), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (230, 230, 230), 3, cv2.LINE_AA)
        return _label_frame(img)
    except Exception:
        return None


def _loop() -> None:
    cam = None
    try:
        if send_fn is None:
            import pyvirtualcam
            import numpy as np
            frame = _blank()
            if frame is None:
                with _lock:
                    _state["running"] = False
                    _state["error"] = "Need OBS Virtual Camera (free) plus pyvirtualcam."
                return
            cam = pyvirtualcam.Camera(width=frame.shape[1], height=frame.shape[0], fps=8, fmt=pyvirtualcam.PixelFormat.RGB)
            with _lock:
                _state["engine"] = "pyvirtualcam"
        while not _stop.is_set():
            frame = _blank()
            frame = _label_frame(frame)
            if send_fn is not None:
                send_fn(frame)
            elif cam is not None:
                cam.send(frame)
                cam.sleep_until_next_frame()
            else:
                time.sleep(0.12)
    except Exception as exc:
        with _lock:
            _state["error"] = str(exc)[:200]
            _state["running"] = False
    finally:
        try:
            if cam is not None:
                cam.close()
        except Exception:
            pass
        with _lock:
            _state["running"] = False


def start(mode: str = "push") -> dict[str, Any]:
    mode = "qa" if str(mode).casefold() in {"qa", "q&a", "approve"} else "push"
    det = _detect()
    if send_fn is None and not det["virtual_cam"]:
        return {"ok": False, "error": "Install free OBS Studio and enable Virtual Camera, then pip install pyvirtualcam (free)."}
    global _thread
    with _lock:
        if _state.get("running"):
            _state["mode"] = mode
            return status()
        _stop.clear()
        _state.update(running=True, mode=mode, error="", pending_answer="")
    _thread = threading.Thread(target=_loop, daemon=True, name="live-twin")
    _thread.start()
    return status()


def stop() -> dict[str, Any]:
    _stop.set()
    with _lock:
        _state["running"] = False
        _state["pending_answer"] = ""
    return status()


def speak_for_me(text: str, approve: bool = True) -> dict[str, Any]:
    text = " ".join((text or "").split())[:500]
    if not text:
        return {"ok": False, "error": "Nothing to say."}
    with _lock:
        mode = _state.get("mode") or "push"
        if mode == "qa" and not approve:
            _state["pending_answer"] = text
            return {"ok": True, "needs_approve": True, "preview": text, "message": "Approve this answer before the twin speaks."}
        _state["last_said"] = text
        _state["pending_answer"] = ""
    try:
        import voice_real
        spoken = voice_real.speak(text)
    except Exception:
        spoken = {"ok": True, "fallback": True, "text": text}
    spoken["label"] = "AI assistant"
    return spoken


def handle(action: str, data: dict[str, Any]) -> dict[str, Any]:
    if action in ("", "status"):
        return status()
    if action == "start":
        return start(str(data.get("mode") or "push"))
    if action == "stop":
        return stop()
    if action == "speak":
        return speak_for_me(str(data.get("text") or ""), bool(data.get("approve", True)))
    if action == "approve":
        with _lock:
            text = str(_state.get("pending_answer") or data.get("text") or "")
        return speak_for_me(text, approve=True)
    return {"ok": False, "error": "Unknown live-avatar action."}
