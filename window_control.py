"""Focus, move, and close ordinary application windows on this PC.

System processes are refused. Tests pass process_override and window_override
so this module does not inspect or close real programs.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

PROTECTED = {
    "system",
    "registry",
    "smss",
    "csrss",
    "wininit",
    "winlogon",
    "services",
    "lsass",
    "svchost",
    "fontdrvhost",
    "dwm",
    "memory compression",
    "secure system",
    "idle",
    "audiodg",
    "sihost",
    "taskhostw",
    "explorer",
}
LAYOUTS = {
    "maximize": "maximize",
    "max": "maximize",
    "minimize": "minimize",
    "min": "minimize",
    "restore": "restore",
    "snap left": "snap_left",
    "left": "snap_left",
    "snap right": "snap_right",
    "right": "snap_right",
}


def _agent() -> Any:
    import agent_core

    return agent_core


def _program_name(value: str) -> str | None:
    text = " ".join((value or "").split())
    if not text or len(text) > 80:
        return None
    if re.search(r"[\\/|&;<>`$*%?]", text):
        return None
    return Path(text).stem.casefold()


def _layout_name(action: str) -> str | None:
    key = " ".join((action or "").casefold().replace("-", " ").replace("_", " ").split())
    return LAYOUTS.get(key)


def _layout_rect(action: str, width: int, height: int) -> tuple[int, int, int, int] | None:
    if action == "snap_left":
        return (0, 0, max(1, width // 2), height)
    if action == "snap_right":
        half = max(1, width // 2)
        return (half, 0, max(1, width - half), height)
    return None


def _screen() -> tuple[int, int]:
    agent = _agent()
    if agent.screen_size_override is not None:
        width, height = agent.screen_size_override
        return int(width), int(height)
    if os.name == "nt":
        import ctypes

        user32 = ctypes.windll.user32
        return int(user32.GetSystemMetrics(0)), int(user32.GetSystemMetrics(1))
    return 1920, 1080


def _list_processes() -> list[dict[str, Any]]:
    agent = _agent()
    if agent.process_override is not None:
        rows = agent.process_override("list")
        return list(rows or [])
    import psutil

    found: list[dict[str, Any]] = []
    for proc in psutil.process_iter(["pid", "name"]):
        info = proc.info or {}
        name = str(info.get("name") or "")
        if not name:
            continue
        found.append({"pid": int(info["pid"]), "name": name})
    return found


def _kill_pid(pid: int, name: str) -> None:
    agent = _agent()
    if agent.process_override is not None:
        agent.process_override("kill", {"pid": pid, "name": name})
        return
    import psutil

    psutil.Process(pid).kill()


def kill_process(process_name: str) -> dict[str, Any]:
    """Close programs whose file name matches process_name."""
    agent = _agent()
    try:
        target = _program_name(process_name)
        if target is None:
            return agent._err("process_name must be a program name, such as notepad.")
        if target in PROTECTED:
            return agent._err(
                f"{target} is a Windows system process, so it was left running."
            )
        victims = []
        for row in _list_processes():
            name = str(row.get("name") or "")
            if Path(name).stem.casefold() != target:
                continue
            pid = int(row.get("pid") or 0)
            if pid <= 0 or pid == os.getpid():
                continue
            victims.append({"pid": pid, "name": name})
        if not victims:
            return agent._err(f"No running program is named {target}.")
        if len(victims) > 8:
            return agent._err(
                f"{target} matched too many processes. Close one window instead."
            )
        for row in victims:
            _kill_pid(int(row["pid"]), str(row["name"]))
        return agent._ok(
            f"Closed {len(victims)} {target} process(es).",
            closed=victims,
        )
    except AssertionError:
        raise
    except Exception as exc:
        return agent._err(f"kill_process failed: {exc}")


def _matching_windows(title: str) -> list[tuple[int, str]]:
    import ctypes

    user32 = ctypes.windll.user32
    found: list[tuple[int, str]] = []
    wanted = title.casefold()

    enum_proc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def callback(hwnd: int, _lparam: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        length = int(user32.GetWindowTextLengthW(hwnd))
        if length <= 0:
            return True
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        text = buffer.value.strip()
        if text and wanted in text.casefold():
            found.append((int(hwnd), text))
        return True

    user32.EnumWindows(enum_proc(callback), 0)
    return found


def _focus_hwnd(hwnd: int) -> None:
    import ctypes

    user32 = ctypes.windll.user32
    user32.ShowWindow(hwnd, 9)
    user32.SetForegroundWindow(hwnd)


def focus_window(window_title: str) -> dict[str, Any]:
    """Bring the first visible window whose title contains window_title forward."""
    agent = _agent()
    try:
        title = " ".join((window_title or "").split())
        if not title:
            return agent._err("window_title is required.")
        if len(title) > 200:
            title = title[:200]
        if agent.window_override is not None:
            agent.window_override("focus", {"title": title})
            return agent._ok(f"Brought {title} to the front.", title=title)
        if os.name != "nt":
            return agent._err("Window control is only available on Windows.")
        try:
            import pygetwindow as gw
        except ImportError:
            gw = None
        if gw is not None:
            matches = [
                window
                for window in gw.getAllWindows()
                if title.casefold() in (window.title or "").casefold()
                and (window.title or "").strip()
            ]
            if not matches:
                return agent._err(f"No window title contains {title}.")
            chosen = matches[0]
            if getattr(chosen, "isMinimized", False):
                chosen.restore()
            chosen.activate()
            return agent._ok(
                f"Brought {chosen.title} to the front.",
                title=str(chosen.title),
            )
        matches = _matching_windows(title)
        if not matches:
            return agent._err(f"No window title contains {title}.")
        hwnd, shown = matches[0]
        _focus_hwnd(hwnd)
        return agent._ok(f"Brought {shown} to the front.", title=shown)
    except AssertionError:
        raise
    except Exception as exc:
        return agent._err(f"focus_window failed: {exc}")


def _apply_layout(action: str, title: str, rect: tuple[int, int, int, int] | None) -> None:
    import ctypes

    user32 = ctypes.windll.user32
    commands = {"maximize": 3, "minimize": 6, "restore": 9}
    if title:
        matches = _matching_windows(title)
        if not matches:
            raise RuntimeError(f"No window title contains {title}.")
        hwnd = matches[0][0]
    else:
        hwnd = int(user32.GetForegroundWindow() or 0)
        if not hwnd:
            raise RuntimeError("There is no active window to move.")
    if action in commands:
        user32.ShowWindow(hwnd, commands[action])
        return
    if rect is None:
        raise RuntimeError(f"Unknown layout {action}.")
    user32.ShowWindow(hwnd, 9)
    flags = 0x0040
    user32.SetWindowPos(hwnd, 0, rect[0], rect[1], rect[2], rect[3], flags)


def manage_window_layout(action: str, window_title: str = "") -> dict[str, Any]:
    """Maximize, minimize, restore, or snap a window to the left or right half."""
    agent = _agent()
    try:
        layout = _layout_name(action)
        if layout is None:
            return agent._err(
                "action must be maximize, minimize, restore, snap_left, or snap_right."
            )
        title = " ".join((window_title or "").split())[:200]
        width, height = _screen()
        rect = _layout_rect(layout, width, height)
        if agent.window_override is not None:
            agent.window_override(
                "layout",
                {"action": layout, "title": title, "rect": rect},
            )
            where = title or "the active window"
            return agent._ok(f"Set {where} to {layout}.", action=layout, rect=rect)
        if os.name != "nt":
            return agent._err("Window control is only available on Windows.")
        _apply_layout(layout, title, rect)
        where = title or "the active window"
        return agent._ok(f"Set {where} to {layout}.", action=layout, rect=rect)
    except AssertionError:
        raise
    except Exception as exc:
        return agent._err(f"manage_window_layout failed: {exc}")


def manage_windows_and_processes(action: str, target: str = "") -> dict[str, Any]:
    """Run one window or process action. target is a program name or a title."""
    key = " ".join((action or "").casefold().replace("-", " ").replace("_", " ").split())
    if key in {"kill", "kill process"}:
        return kill_process(target)
    if key in {"focus", "focus window"}:
        return focus_window(target)
    if _layout_name(key) is not None:
        return manage_window_layout(key, target)
    return _agent()._err(
        "action must be kill, focus, maximize, minimize, restore, snap_left, or snap_right."
    )
