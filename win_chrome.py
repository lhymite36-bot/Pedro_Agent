"""Desktop window chrome: frameless dark window like Grok Bot, our own icon in
the taskbar (not Python's), and no console window. Windows only; other
systems get a normal pywebview window."""
from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path
from typing import Any

APP_ID = "PedroAgent.Desktop.App"
TITLE = "Pedro_Agent"
HERE = Path(__file__).resolve().parent


def icon_path() -> Path | None:
    for p in (HERE / "pedro3d.ico", HERE / "installer" / "pedro.ico", HERE / "app_static" / "favicon.ico"):
        if p.is_file():
            return p
    return None


def set_app_id() -> None:
    """Group the window under our own taskbar entry (so it shows our icon)."""
    if os.name != "nt":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:
        pass


_MUTEX = None


def single_instance(name: str = "PedroAgentSingleInstance") -> bool:
    """False if another Pedro_Agent app is already running (Windows named mutex).
    Two copies fight over Telegram, the mic and the tunnel."""
    global _MUTEX
    if os.name != "nt":
        return True
    try:
        import ctypes

        k32 = ctypes.windll.kernel32
        k32.CreateMutexW.restype = ctypes.c_void_p
        _MUTEX = k32.CreateMutexW(None, False, "Local\\" + name)
        return k32.GetLastError() != 183   # ERROR_ALREADY_EXISTS
    except Exception:
        return True


def focus_existing(title: str = TITLE) -> None:
    if os.name != "nt":
        return
    try:
        import ctypes

        u = ctypes.windll.user32
        u.FindWindowW.restype = ctypes.c_void_p
        hwnd = u.FindWindowW(None, title)
        if hwnd:
            u.ShowWindow(ctypes.c_void_p(hwnd), 9)   # SW_RESTORE
            u.SetForegroundWindow(ctypes.c_void_p(hwnd))
    except Exception:
        pass


def apply_icon(title: str = TITLE, tries: int = 40) -> bool:
    """WM_SETICON on our window once it exists (big + small icons)."""
    ico = icon_path()
    if os.name != "nt" or ico is None:
        return False
    import ctypes

    user32 = ctypes.windll.user32
    user32.FindWindowW.restype = ctypes.c_void_p
    user32.LoadImageW.restype = ctypes.c_void_p
    user32.SendMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p]
    for _ in range(tries):
        hwnd = user32.FindWindowW(None, title)
        if hwnd:
            for which, size in ((1, 256), (0, 32)):   # ICON_BIG, ICON_SMALL
                h = user32.LoadImageW(None, str(ico), 1, size, size, 0x10)   # IMAGE_ICON, LR_LOADFROMFILE
                if h:
                    user32.SendMessageW(hwnd, 0x80, which, h)   # WM_SETICON
            return True
        time.sleep(0.25)
    return False


class WindowApi:
    """Called from the page's own title-bar buttons (window.pywebview.api.*)."""

    def __init__(self) -> None:
        self._window: Any = None
        self.maximized = False

    def minimize(self) -> bool:
        if self._window:
            self._window.minimize()
        return True

    def toggle_maximize(self) -> bool:
        if not self._window:
            return False
        if self.maximized:
            self._window.restore()
        else:
            self._window.maximize()
        self.maximized = not self.maximized
        return self.maximized

    def close(self) -> bool:
        if self._window:
            self._window.destroy()
        return True

    def geometry(self) -> dict[str, int]:
        w = self._window
        return {"x": int(w.x), "y": int(w.y), "w": int(w.width), "h": int(w.height)} if w else {}

    def set_geometry(self, x: int, y: int, w: int, h: int) -> bool:
        """Edge-drag resize for the frameless window."""
        if not self._window or self.maximized:
            return False
        w, h = max(int(w), 760), max(int(h), 520)
        self._window.resize(w, h)
        self._window.move(int(x), int(y))
        return True


def open_window(url: str) -> Any:
    import webview  # type: ignore

    set_app_id()
    api = WindowApi()
    frameless = os.name == "nt" and os.environ.get("PEDRO_NATIVE_FRAME") != "1"
    width, height, x, y = 1180, 800, None, None
    try:   # fit small screens (e.g. 1366x768): leave room for the taskbar, centre it
        scr = webview.screens[0]
        width, height = min(width, scr.width - 40), min(height, scr.height - 70)
        x, y = max(0, (scr.width - width) // 2), max(0, (scr.height - 40 - height) // 2)
    except Exception:
        pass
    win = webview.create_window(TITLE, url, width=width, height=height, x=x, y=y, min_size=(760, 520), frameless=frameless,
                                easy_drag=False, js_api=api, background_color="#0b0b0f", text_select=True)
    api._window = win
    threading.Thread(target=apply_icon, daemon=True).start()
    webview.start()
    return win
