"""PC autopilot: screenshot → Gemini vision → click/type, with Allow on every step.

Default is step mode. Advanced users can tap “Allow this task” once. Moving the
mouse to a corner or pressing Ctrl+Shift+Esc+P stops it. Every action is logged
to Documents\\Ped Bot Logs.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable

screenshot_fn: Callable[[], bytes] | None = None
vision_fn: Callable[[bytes, str], dict[str, Any]] | None = None
act_fn: Callable[[dict[str, Any]], dict[str, Any]] | None = None
locate_fn: Callable[[bytes, str], dict[str, Any]] | None = None

_lock = threading.Lock()
_stop = threading.Event()
_hotkey_thread: threading.Thread | None = None
_state: dict[str, Any] = {
    "running": False,
    "mode": "step",
    "goal": "",
    "pending": None,
    "history": [],
    "log": [],
    "error": "",
}


def logs_dir() -> Path:
    folder = Path.home() / "Documents" / "Ped Bot Logs"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _log(line: str) -> None:
    stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    text = f"{stamp}  {line}"
    with _lock:
        _state["log"] = (_state.get("log") or [])[-80:] + [text]
    try:
        path = logs_dir() / f"autopilot-{dt.date.today().isoformat()}.log"
        with path.open("a", encoding="utf-8") as fh:
            fh.write(text + "\n")
    except OSError:
        pass


def stop(reason: str = "Stopped.") -> dict[str, Any]:
    _stop.set()
    with _lock:
        _state["running"] = False
        _state["pending"] = None
        _state["error"] = reason
    _log(reason)
    return status()


def status() -> dict[str, Any]:
    with _lock:
        snap = dict(_state)
        snap["pending"] = dict(snap["pending"]) if isinstance(snap.get("pending"), dict) else None
        snap["history"] = list(snap.get("history") or [])[-20:]
        snap["log"] = list(snap.get("log") or [])[-20:]
    snap["ok"] = True
    snap["stop_hint"] = "Move the mouse to a corner, or press Ctrl+Shift+Esc then P, to stop at once."
    return snap


def _shot() -> bytes:
    if screenshot_fn is not None:
        return screenshot_fn()
    try:
        import mss
        import mss.tools
        with mss.mss() as sct:
            mon = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
            raw = sct.grab(mon)
            return mss.tools.to_png(raw.rgb, raw.size)
    except Exception:
        from io import BytesIO
        from PIL import ImageGrab
        buf = BytesIO()
        ImageGrab.grab().save(buf, format="PNG")
        return buf.getvalue()


def _ask(image: bytes, goal: str, history: list[str]) -> dict[str, Any]:
    if vision_fn is not None:
        return vision_fn(image, goal)
    import llm
    done = "\n".join(history[-8:]) or "(nothing yet)"
    prompt = (
        "You drive a Windows PC one step at a time from a screenshot. "
        f"GOAL: {goal}\nALREADY DONE:\n{done}\n"
        "Reply JSON only: {\"done\": false, \"action\": \"click|type|hotkey|wait|fail\", "
        "\"target\": \"visible name of the control\", \"text\": \"\", "
        "\"preview\": \"I'm about to click Save\"}. "
        "action=fail if the goal cannot be done. Never type passwords. "
        "If the goal is already done, {\"done\": true, \"preview\": \"Done.\"}."
    )
    try:
        data = llm.json_from(llm.text(prompt, [image]))
    except Exception as exc:
        return {"done": False, "action": "fail", "preview": f"Could not see the screen: {exc}"[:180]}
    if not isinstance(data, dict):
        return {"done": False, "action": "fail", "preview": "The model did not return a step."}
    return data


def _do(step: dict[str, Any], image: bytes) -> dict[str, Any]:
    if act_fn is not None:
        return act_fn(step)
    action = str(step.get("action") or "").casefold()
    if action == "wait":
        time.sleep(min(5.0, float(step.get("seconds") or 1)))
        return {"ok": True, "did": "wait"}
    if action == "hotkey":
        import pyautogui
        keys = [k.strip() for k in str(step.get("text") or step.get("key") or "enter").split("+") if k.strip()]
        pyautogui.hotkey(*keys[:4])
        return {"ok": True, "did": "hotkey " + "+".join(keys)}
    if action == "type":
        import pyautogui
        pyautogui.typewrite(str(step.get("text") or "")[:400], interval=0.02)
        return {"ok": True, "did": "type"}
    if action == "click":
        target = str(step.get("target") or "").strip()
        box = None
        if locate_fn is not None:
            box = locate_fn(image, target)
        else:
            try:
                import screen_vision
                box = screen_vision.find_on_screen(target) if hasattr(screen_vision, "find_on_screen") else None
            except Exception:
                box = None
        if not box or not box.get("found"):
            # fallback: click by vision 0-1000 coords if present
            if step.get("x") is not None and step.get("y") is not None:
                import mouse_controller
                import pyautogui
                x, y = mouse_controller.norm_to_pixel(float(step["x"]), float(step["y"]), *pyautogui.size())
                pyautogui.click(x, y)
                return {"ok": True, "did": f"click {x},{y}"}
            return {"ok": False, "error": f"Could not find “{target}” on screen."}
        import pyautogui
        x, y = int(box.get("px") or box.get("x") or 0), int(box.get("py") or box.get("y") or 0)
        if box.get("x") is not None and box.get("px") is None and x <= 1000:
            import mouse_controller
            x, y = mouse_controller.norm_to_pixel(float(box["x"]), float(box["y"]), *pyautogui.size())
        pyautogui.click(x, y)
        return {"ok": True, "did": f"click {target}"}
    return {"ok": False, "error": f"Unknown action {action}."}


def _listen_hotkey() -> None:
    """Ctrl+Shift+Esc then P, or the pyautogui corner failsafe, stops the run."""
    try:
        from pynput import keyboard
    except Exception:
        return
    held: set[str] = set()

    def name(key: Any) -> str:
        try:
            if key in (keyboard.Key.ctrl_l, keyboard.Key.ctrl_r, keyboard.Key.ctrl):
                return "ctrl"
            if key in (keyboard.Key.shift_l, keyboard.Key.shift_r, keyboard.Key.shift):
                return "shift"
            if key == keyboard.Key.esc:
                return "esc"
            return getattr(key, "char", "") or ""
        except Exception:
            return ""

    def on_press(key: Any) -> None:
        n = name(key).casefold()
        if n:
            held.add(n)
        if {"ctrl", "shift", "esc"}.issubset(held) and n == "p":
            stop("Hotkey Ctrl+Shift+Esc+P — stopped.")
        if {"ctrl", "shift"}.issubset(held) and n == "p" and "esc" in held:
            stop("Hotkey — stopped.")

    def on_release(key: Any) -> None:
        n = name(key).casefold()
        if n:
            held.discard(n)

    with keyboard.Listener(on_press=on_press, on_release=on_release) as listener:
        while not _stop.is_set() and _state.get("running"):
            listener.join(0.2)
            if not listener.running:
                break


def _arm_failsafe() -> None:
    try:
        import pyautogui
        import mouse_controller
        mouse_controller.configure_desktop(pyautogui)
    except Exception:
        pass


def _run(goal: str, mode: str) -> None:
    history: list[str] = []
    try:
        for _ in range(40):
            if _stop.is_set():
                return
            try:
                image = _shot()
            except Exception as exc:
                stop(f"Could not take a screenshot: {exc}"[:180])
                return
            step = _ask(image, goal, history)
            if step.get("done"):
                _log("Done: " + str(step.get("preview") or "goal reached"))
                with _lock:
                    _state["running"] = False
                    _state["pending"] = None
                    _state["history"] = history + ["done"]
                return
            if str(step.get("action") or "").casefold() == "fail":
                stop(str(step.get("preview") or "Could not continue."))
                return
            preview = str(step.get("preview") or f"I'm about to {step.get('action')} {step.get('target') or step.get('text') or ''}".strip())
            pending = {"preview": preview, "step": step, "image_bytes": len(image)}
            with _lock:
                _state["pending"] = pending
            _log("Pending: " + preview)
            if mode != "task":
                # wait until allow() clears pending or stop
                while not _stop.is_set():
                    with _lock:
                        if _state.get("pending") is None:
                            break
                    time.sleep(0.15)
                if _stop.is_set():
                    return
            else:
                # one-task allow already granted; still log
                with _lock:
                    _state["pending"] = None
            if _stop.is_set():
                return
            _arm_failsafe()
            try:
                result = _do(step, image)
            except Exception as exc:
                # pyautogui FailSafeException when mouse in corner
                stop(f"Stopped ({exc})."[:180])
                return
            line = result.get("did") or result.get("error") or json.dumps(result)
            history.append(preview + " → " + str(line))
            _log(str(line))
            with _lock:
                _state["history"] = list(history)
            if not result.get("ok"):
                stop(str(result.get("error") or "Step failed."))
                return
            time.sleep(0.35)
    finally:
        with _lock:
            _state["running"] = False
            if _state.get("pending") and _stop.is_set():
                _state["pending"] = None


def start(goal: str, mode: str = "step") -> dict[str, Any]:
    goal = " ".join((goal or "").split())[:400]
    if not goal:
        return {"ok": False, "error": "Tell autopilot what to do, e.g. open Notepad and type hello."}
    if not os.environ.get("GEMINI_API_KEY", "").strip() and vision_fn is None:
        return {"ok": False, "error": "PC autopilot needs your free Gemini key (Settings) so it can see the screen."}
    mode = "task" if str(mode).casefold() in {"task", "allow_task", "one_task"} else "step"
    with _lock:
        if _state.get("running"):
            return {"ok": False, "error": "Autopilot is already running. Stop it first."}
        _stop.clear()
        _state.update(running=True, mode=mode, goal=goal, pending=None, history=[], error="")
    _log(f"Start ({mode}): {goal}")
    threading.Thread(target=_run, args=(goal, mode), daemon=True, name="see-click").start()
    global _hotkey_thread
    if os.environ.get("PEDBOT_TEST") != "1":
        if _hotkey_thread is None or not _hotkey_thread.is_alive():
            _hotkey_thread = threading.Thread(target=_listen_hotkey, daemon=True, name="see-click-hotkey")
            _hotkey_thread.start()
    return status()


def allow(whole_task: bool = False) -> dict[str, Any]:
    with _lock:
        if not _state.get("running"):
            return {"ok": False, "error": "Nothing is waiting."}
        if whole_task:
            _state["mode"] = "task"
        _state["pending"] = None
    _log("Allowed" + (" this task" if whole_task else " this step"))
    return status()


def handle(action: str, data: dict[str, Any]) -> dict[str, Any]:
    if action in ("", "status"):
        return status()
    if action == "start":
        return start(str(data.get("goal") or data.get("command") or ""), str(data.get("mode") or "step"))
    if action == "allow":
        return allow(bool(data.get("task") or data.get("whole")))
    if action == "stop":
        return stop("Stopped by you.")
    return {"ok": False, "error": "Unknown autopilot action."}
