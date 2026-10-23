"""1.4.15: one cancel token per turn, so Stop takes effect within about half a second.

The chat turn binds its cancel Event here. Everything a turn runs (model requests,
tools, terminal commands, replays) asks this module instead of sleeping or blocking:

- wait(seconds) is a sleep that ends the moment Stop is pressed.
- run(fn) runs a blocking call in a worker and returns at once on Stop (the worker
  is abandoned; model requests also carry an 8 s HTTP timeout so it ends soon).
- track(proc) registers a subprocess; Stop kills its whole process tree.
- held keys and mouse buttons are released on Stop.
- checkpoint() raises Stopped on Stop and freezes while Pause all is on.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from typing import Any, Callable

_local = threading.local()
_lock = threading.Lock()
_procs: dict[int, tuple[Any, threading.Event | None]] = {}
_held: dict[tuple[str, str], tuple[Any, Any, threading.Event | None]] = {}
POLL = 0.05


class Stopped(Exception):
    """The user pressed Stop."""


def bind(event: threading.Event | None) -> None:
    _local.event = event


def current() -> threading.Event | None:
    return getattr(_local, "event", None)


def stopped(event: threading.Event | None = None) -> bool:
    ev = event or current()
    return bool(ev is not None and ev.is_set())


def wait(seconds: float, event: threading.Event | None = None) -> bool:
    """Sleep up to `seconds`; True when Stop ended it early."""
    ev = event or current()
    if ev is None:
        time.sleep(max(0.0, seconds))
        return False
    return ev.wait(max(0.0, seconds))


def _paused() -> bool:
    try:
        import safe_mode
        return safe_mode.paused()
    except Exception:
        return False


def checkpoint(event: threading.Event | None = None, on_pause: Callable[[], None] | None = None,
               on_resume: Callable[[], None] | None = None) -> None:
    """A safe point: raise Stopped on Stop; while Pause all is on, freeze here until Resume."""
    ev = event or current()
    if ev is not None and ev.is_set():
        raise Stopped("Stopped.")
    if not _paused():
        return
    if on_pause is not None:
        on_pause()
    while _paused():
        if ev is not None and ev.wait(0.2):
            raise Stopped("Stopped.")
        if ev is None:
            time.sleep(0.2)
    if on_resume is not None:
        on_resume()


def run(fn: Callable[[], Any], event: threading.Event | None = None, name: str = "pb-call") -> Any:
    """Run fn in a worker; return its result, or raise Stopped the moment Stop is pressed."""
    ev = event or current()
    if ev is None:
        return fn()
    box: dict[str, Any] = {}
    parent = dict(_local.__dict__)

    def runner() -> None:
        _local.__dict__.update(parent)
        try:
            box["result"] = fn()
        except BaseException as exc:
            box["error"] = exc

    worker = threading.Thread(target=runner, name=name, daemon=True)
    worker.start()
    while worker.is_alive():
        worker.join(POLL)
        if ev.is_set() and worker.is_alive():
            raise Stopped("Stopped.")
    if "error" in box:
        raise box["error"]
    return box.get("result")


def track(proc: Any, event: threading.Event | None = None) -> None:
    with _lock:
        _procs[proc.pid] = (proc, event or current())


def untrack(proc: Any) -> None:
    with _lock:
        _procs.pop(getattr(proc, "pid", -1), None)


def kill_tree(proc: Any) -> None:
    pid = getattr(proc, "pid", None)
    if not pid:
        return
    if sys.platform == "win32":
        try:
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)], capture_output=True, timeout=5,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except Exception:
            pass
    else:
        try:
            import signal
            os.killpg(os.getpgid(pid), signal.SIGKILL)
        except Exception:
            pass
    try:
        proc.kill()
    except Exception:
        pass


def hold(kind: str, key: Any, controller: Any) -> None:
    """Remember a pressed key or mouse button so Stop can let it go."""
    with _lock:
        _held[(kind, repr(key))] = (controller, key, current())


def unhold(kind: str, key: Any) -> None:
    with _lock:
        _held.pop((kind, repr(key)), None)


def release_inputs(event: threading.Event | None = None) -> int:
    """Release held keys and buttons (all of them, or those of one turn)."""
    with _lock:
        items = [(k, v) for k, v in _held.items() if event is None or v[2] is None or v[2] is event]
        for k, _v in items:
            _held.pop(k, None)
    n = 0
    for _k, (controller, key, _ev) in items:
        try:
            controller.release(key)
            n += 1
        except Exception:
            pass
    return n


def fire(event: threading.Event | None = None) -> dict[str, int]:
    """Called by Stop: kill tracked process trees and release inputs right away."""
    with _lock:
        procs = [p for p, ev in _procs.values() if event is None or ev is None or ev is event]
    for p in procs:
        kill_tree(p)
    with _lock:
        for p in procs:
            _procs.pop(p.pid, None)
    return {"killed": len(procs), "released": release_inputs(event)}


def fire_async(event: threading.Event | None = None) -> None:
    threading.Thread(target=fire, args=(event,), name="pb-stop", daemon=True).start()
