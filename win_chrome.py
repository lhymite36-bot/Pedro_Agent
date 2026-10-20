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
TITLE = "Ped Bot"
HERE = Path(__file__).resolve().parent


def icon_path() -> Path | None:
    for p in (HERE / "pedbot.ico", HERE / "pedro3d.ico", HERE / "installer" / "pedro.ico", HERE / "app_static" / "favicon.ico"):
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


def _own_windows(title: str) -> list[int]:
    """Top-level windows of THIS process with our title (FindWindow could pick another app's window)."""
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    found: list[int] = []
    pid = os.getpid()
    proto = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def cb(hwnd: Any, _l: Any) -> bool:
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid:
            buf = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(hwnd, buf, 256)
            if buf.value == title:
                found.append(int(hwnd))
        return True

    user32.EnumWindows(proto(cb), 0)
    return found


def apply_icon(title: str = TITLE, tries: int = 60) -> bool:
    """WM_SETICON (big + small) on our own window, re-applied for ~15 s because the
    window toolkit can set Python's icon after we do (the taskbar then shows Python)."""
    ico = icon_path()
    if os.name != "nt" or ico is None:
        return False
    import ctypes

    user32 = ctypes.windll.user32
    user32.LoadImageW.restype = ctypes.c_void_p
    user32.SendMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p]
    icons = [(which, user32.LoadImageW(None, str(ico), 1, size, size, 0x10)) for which, size in ((1, 256), (0, 32))]
    done = False
    for _ in range(tries):
        try:
            for hwnd in _own_windows(title):
                for which, h in icons:
                    if h:
                        user32.SendMessageW(hwnd, 0x80, which, h)   # WM_SETICON
                done = True
        except Exception:
            pass
        time.sleep(0.25)
    return done


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
        # The title-bar X: goes through the same closing handler (hide to tray when on).
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
    width, height, x, y = 1440, 900, None, None
    try:   # use most of the screen (Live PC needs room); leave the taskbar free, centre it
        scr = webview.screens[0]
        width, height = max(760, min(width, scr.width - 16)), max(520, min(height, scr.height - 56))
        x, y = max(0, (scr.width - width) // 2), max(0, (scr.height - 40 - height) // 2)
    except Exception:
        pass
    win = webview.create_window(TITLE, url, width=width, height=height, x=x, y=y, min_size=(760, 520), frameless=frameless,
                                easy_drag=False, js_api=api, background_color="#0b0b0f", text_select=True)
    api._window = win
    _wire_background(win, api)
    threading.Thread(target=apply_icon, daemon=True).start()
    webview.start()
    return win


QUITTING = threading.Event()
HIDDEN = False


def _wire_background(win: Any, api: "WindowApi") -> None:
    """Close = hide to tray (bots keep working); tray Quit really exits. 1.4.14."""
    try:
        import background
    except Exception:
        return

    def show() -> None:
        global HIDDEN
        HIDDEN = False
        try:
            win.show()
            win.restore()
        except Exception:
            pass
        threading.Thread(target=apply_icon, kwargs={"tries": 12}, daemon=True).start()

    def quit_app() -> None:
        QUITTING.set()
        background.stop_tray()
        try:
            win.destroy()
        except Exception:
            os._exit(0)

    def pause() -> None:
        try:
            import json
            import urllib.request
            import safe_mode

            path = "/api/resume_all" if safe_mode.paused() else "/api/pause_all"
            port = os.environ.get("PEDBOT_PORT", "8765")
            req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=b"{}", method="POST",
                                         headers={"Content-Type": "application/json", "Origin": f"http://127.0.0.1:{port}"})
            urllib.request.urlopen(req, timeout=10).read()
        except Exception:
            pass

    tray = background.start_tray(show, quit_app, pause)

    def on_closing() -> bool:
        if QUITTING.is_set() or not tray or not background.settings()["keep_running"]:
            return True
        try:
            win.hide()
            global HIDDEN
            HIDDEN = True
        except Exception:
            return True
        background.notify("Ped Bot is still working", "Closed to the tray. Bots, routines and the phone keep running. "
                          "Right-click the tray icon to open or quit.")
        return False

    try:
        win.events.closing += on_closing
    except Exception:
        pass
    if os.environ.get("PEDBOT_START_HIDDEN") == "1" and tray:
        def hide_soon() -> None:
            try:
                win.events.shown.wait(15)
                win.hide()
            except Exception:
                pass
        threading.Thread(target=hide_soon, daemon=True).start()
