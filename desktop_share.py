"""One pointer, many chats.

Each click, type, or key press finishes before another chat starts one.
A chat that has focused a window is put back on that window first, so the
other chat's typing stays in its own window. The lock is only held for the
action, not while a model is thinking.
"""

from __future__ import annotations

import contextvars
import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Callable

_owner: contextvars.ContextVar[str] = contextvars.ContextVar("pedro_desktop_owner", default="")
_lock = threading.RLock()
_windows_guard = threading.Lock()
_windows: dict[str, int] = {}
focus_hook: Callable[[int], None] | None = None
title_hook: Callable[[int], str] | None = None


def bind(owner: str) -> contextvars.Token[str]:
    return _owner.set(owner or "")


def unbind(token: contextvars.Token[str]) -> None:
    _owner.reset(token)


def owner() -> str:
    return _owner.get() or ""


def remember(hwnd: int, owner_id: str | None = None) -> None:
    key = owner() if owner_id is None else owner_id
    if not key or not hwnd:
        return
    with _windows_guard:
        _windows[key] = int(hwnd)


def clear(owner_id: str | None = None) -> None:
    key = owner() if owner_id is None else owner_id
    if not key:
        return
    with _windows_guard:
        _windows.pop(key, None)


def window_for(owner_id: str | None = None) -> int:
    key = owner() if owner_id is None else owner_id
    if not key:
        return 0
    with _windows_guard:
        return int(_windows.get(key) or 0)


def windows() -> dict[str, int]:
    """Owner id to the window that chat is using."""
    with _windows_guard:
        return dict(_windows)


def window_title(hwnd: int) -> str:
    """Visible title of a window. Empty when this process should stay off the real desktop."""
    if not hwnd:
        return ""
    if title_hook is not None:
        return " ".join(str(title_hook(int(hwnd)) or "").split())[:80]
    if _skip_real_focus() or os.name != "nt":
        return ""
    import ctypes

    user32 = ctypes.windll.user32
    try:
        if not user32.IsWindow(int(hwnd)):
            return ""
        length = int(user32.GetWindowTextLengthW(int(hwnd)))
        if length <= 0:
            return ""
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(int(hwnd), buffer, length + 1)
        return " ".join(buffer.value.split())[:80]
    except Exception:
        return ""


def reset() -> None:
    """Drop remembered windows. Tests use this so later tests see a clean PC share."""
    global focus_hook, title_hook
    with _windows_guard:
        _windows.clear()
    focus_hook = None
    title_hook = None


def _skip_real_focus() -> bool:
    if focus_hook is not None:
        return False
    try:
        import agent_core

        if agent_core.pointer_override is not None or agent_core.window_override is not None:
            return True
    except Exception:
        return True
    try:
        import demo_skills

        if demo_skills.controller_factory is not None:
            return True
    except Exception:
        return True
    return os.name != "nt"


def _foreground() -> int:
    if _skip_real_focus():
        return 0
    import ctypes

    return int(ctypes.windll.user32.GetForegroundWindow() or 0)


def _restore(hwnd: int) -> None:
    if not hwnd:
        return
    if focus_hook is not None:
        focus_hook(int(hwnd))
        return
    if _skip_real_focus():
        return
    import ctypes

    user32 = ctypes.windll.user32
    try:
        if not user32.IsWindow(hwnd):
            clear()
            return
        if int(user32.GetForegroundWindow() or 0) == int(hwnd):
            return
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        user32.SetForegroundWindow(hwnd)
    except Exception:
        return


@contextmanager
def hold(claim: bool = True) -> Iterator[None]:
    """Keep one pointer action whole. Restore this chat's window first."""
    _lock.acquire()
    try:
        if claim:
            hwnd = window_for()
            if hwnd:
                _restore(hwnd)
            else:
                seen = _foreground()
                if seen:
                    remember(seen)
        yield
    finally:
        _lock.release()
