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
    try:
        import threading
        threading.Thread(target=register_shortcut_app_id, daemon=True, name="aumid").start()
    except Exception:
        pass


def _start_menu_shortcut() -> Path:
    return Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Ped Bot" / "Ped Bot.lnk"


def register_shortcut_app_id(link: Path | None = None) -> str:
    """1.4.17: stamp our AppUserModelID on the Start Menu shortcut, so Windows notifications say
    'Ped Bot' with its icon instead of 'Python'. Returns 'set', 'ok' (already set) or why it was skipped."""
    if os.name != "nt":
        return "not windows"
    link = link or _start_menu_shortcut()
    if not link.is_file():
        return "no shortcut"
    try:
        import pythoncom  # type: ignore
        from win32com.propsys import propsys, pscon  # type: ignore
        from win32com.shell import shellcon  # type: ignore
    except ImportError:
        return "pywin32 missing"
    try:
        pythoncom.CoInitialize()
        store = propsys.SHGetPropertyStoreFromParsingName(str(link), None, shellcon.GPS_READWRITE, propsys.IID_IPropertyStore)
        current = store.GetValue(pscon.PKEY_AppUserModel_ID).GetValue()
        if current == APP_ID:
            return "ok"
        store.SetValue(pscon.PKEY_AppUserModel_ID, propsys.PROPVARIANTType(APP_ID))
        store.Commit()
        return "set"
    except Exception as exc:
        return f"failed: {type(exc).__name__}"


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


def _process_image(pid: int) -> str:
    """Full path of a running process, or empty."""
    import ctypes
    from ctypes import wintypes

    k32 = ctypes.windll.kernel32
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    handle = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(512)
        size = wintypes.DWORD(512)
        if k32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return buf.value
    except Exception:
        pass
    finally:
        k32.CloseHandle(handle)
    return ""


def _show_hwnd(hwnd: int) -> None:
    import ctypes

    u = ctypes.windll.user32
    SW_SHOW, SW_RESTORE = 5, 9
    u.ShowWindow(ctypes.c_void_p(hwnd), SW_RESTORE)
    u.ShowWindow(ctypes.c_void_p(hwnd), SW_SHOW)
    u.SetForegroundWindow(ctypes.c_void_p(hwnd))


def focus_existing(title: str = TITLE) -> None:
    """Show the running Ped window, including one hidden to the tray.

    FindWindowW(title) can hit Explorer (Start Menu folder / shortcut named Ped Bot).
    """
    if os.name != "nt":
        return
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        matches: list[int] = []
        proto = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        root = str(HERE).casefold()

        def cb(hwnd: Any, _l: Any) -> bool:
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            buf = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(hwnd, buf, 256)
            if buf.value != title:
                return True
            image = _process_image(int(pid.value)).casefold()
            if image.startswith(root) and image.endswith("pythonw.exe"):
                matches.append(int(hwnd))
            return True

        user32.EnumWindows(proto(cb), 0)
        if matches:
            _show_hwnd(matches[0])
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


# 1.4.19/1.5.0: Windows snap for the frameless window. The window gets the resize/maximise styles that snap needs,
# a window procedure that keeps the client area full-size (no visible frame or line), and a native move loop
# (SC_MOVE|HTCAPTION) started from the app's header, so drag-to-edge snapping, Win+arrows and Snap Layouts work.
WM_APP_DRAG = 0x8000 + 7
_SNAP: dict[str, Any] = {}


def enable_snap(title: str = TITLE, tries: int = 40) -> bool:
    if os.name != "nt" or _SNAP.get("hwnd"):
        return bool(_SNAP.get("hwnd"))
    import ctypes
    import time as _t
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    LRESULT = ctypes.c_ssize_t
    WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
    user32.CallWindowProcW.restype = LRESULT
    user32.CallWindowProcW.argtypes = [ctypes.c_void_p, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.SetWindowLongPtrW.restype = ctypes.c_void_p
    user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
    user32.DefWindowProcW.restype = LRESULT
    user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    hwnd = 0
    for _ in range(tries):
        found = _own_windows(title)
        if found:
            hwnd = found[0]
            break
        _t.sleep(0.25)
    if not hwnd:
        return False

    class NCCALCSIZE_PARAMS(ctypes.Structure):
        _fields_ = [("rgrc", wintypes.RECT * 3), ("lppos", ctypes.c_void_p)]

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

    def proc(h: Any, msg: int, wp: int, lp: int) -> int:
        try:
            if msg == 0x0083 and wp:   # WM_NCCALCSIZE: whole window is client area (no frame, no 1px line)
                if user32.IsZoomed(h):   # maximised: keep it inside the work area (not under the taskbar)
                    params = ctypes.cast(lp, ctypes.POINTER(NCCALCSIZE_PARAMS)).contents
                    mon = user32.MonitorFromWindow(h, 2)
                    mi = MONITORINFO(); mi.cbSize = ctypes.sizeof(MONITORINFO)
                    if user32.GetMonitorInfoW(mon, ctypes.byref(mi)):
                        params.rgrc[0] = mi.rcWork
                return 0
            if msg == WM_APP_DRAG:
                user32.ReleaseCapture()
                user32.SendMessageW(h, 0x0112, 0xF012, 0)   # WM_SYSCOMMAND SC_MOVE|HTCAPTION: native move + snap
                return 0
        except Exception:
            pass
        return user32.CallWindowProcW(_SNAP["old"], h, msg, wp, lp)

    cb = WNDPROC(proc)
    _SNAP["cb"] = cb   # keep the callback alive
    _SNAP["old"] = user32.SetWindowLongPtrW(hwnd, -4, ctypes.cast(cb, ctypes.c_void_p))
    style = user32.GetWindowLongW(hwnd, -16)
    style |= 0x00040000 | 0x00020000 | 0x00010000   # THICKFRAME, MINIMIZEBOX, MAXIMIZEBOX (snap)
    style &= ~0x00C00000   # no caption
    style &= ~0x00080000   # no SYSMENU: Windows 11 otherwise paints a native close over our bar
    user32.SetWindowLongW(hwnd, -16, style)
    user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x0027)   # NOSIZE|NOMOVE|NOZORDER|FRAMECHANGED
    try:
        dwm = ctypes.windll.dwmapi
        dark = ctypes.c_int(1)
        dwm.DwmSetWindowAttribute(wintypes.HWND(hwnd), 20, ctypes.byref(dark), ctypes.sizeof(dark))
        caption = ctypes.c_int(0x00110F0E)  # BGR of #0e0f11
        dwm.DwmSetWindowAttribute(wintypes.HWND(hwnd), 35, ctypes.byref(caption), ctypes.sizeof(caption))
        border = ctypes.c_int(0x00110F0E)
        dwm.DwmSetWindowAttribute(wintypes.HWND(hwnd), 34, ctypes.byref(border), ctypes.sizeof(border))
    except Exception:
        pass
    _SNAP["hwnd"] = hwnd
    return True


def start_native_drag() -> bool:
    h = _SNAP.get("hwnd")
    if not h:
        return False
    import ctypes
    ctypes.windll.user32.PostMessageW(h, WM_APP_DRAG, 0, 0)
    return True


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

    def start_drag(self) -> bool:
        """The header was pressed: hand the move to Windows (snap to edges / corners works)."""
        return start_native_drag()

    def snap_ready(self) -> bool:
        return bool(_SNAP.get("hwnd"))

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
                                easy_drag=False, js_api=api, background_color="#0e0f11", text_select=True)
    api._window = win
    _wire_background(win, api)
    threading.Thread(target=apply_icon, daemon=True).start()
    if frameless and os.environ.get("PEDRO_NO_SNAP") != "1":
        def _snap_when_shown() -> None:
            try:
                win.events.shown.wait(20)
            except Exception:
                pass
            try:
                enable_snap()
            except Exception as exc:
                print(f"[window] snap setup failed: {type(exc).__name__}", flush=True)
        threading.Thread(target=_snap_when_shown, daemon=True, name="snap").start()
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
