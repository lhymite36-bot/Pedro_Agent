"""24/7 worker: Ped Bot keeps working when its window is closed.

- Closing the window hides it to the tray (Open / Pause all / Quit). Bots, routines,
  the phone link and queued tasks keep running. Quit (tray) really exits.
- Optional "Start with Windows" (off by default; you turn it on in Settings) starts it
  hidden in the tray at sign-in, via your own HKCU Run entry (no admin, no PowerShell).
- Every chat task is written to a small queue file when it starts and cleared when it
  ends. After a restart or crash, unfinished tasks are resumed and say so in their chat.
- notify() shows a Windows notification from the tray icon.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "PedBot"
_lock = threading.Lock()
_tray: Any = None
notifier: Callable[[str, str], Any] | None = None     # tests replace this
sent_notes: list[tuple[str, str]] = []


# ---------- settings ----------
def _settings_file() -> Path:
    import agent_config

    return agent_config.storage_dir() / "background.json"


def settings() -> dict[str, Any]:
    try:
        data = json.loads(_settings_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    return {"keep_running": bool(data.get("keep_running", True)), "notifications": bool(data.get("notifications", True)),
            "start_with_windows": autostart_enabled()}


def save_settings(**changes: Any) -> dict[str, Any]:
    cur = settings()
    if "start_with_windows" in changes:
        set_autostart(bool(changes.pop("start_with_windows")))
    cur.update({k: bool(v) for k, v in changes.items() if k in {"keep_running", "notifications"}})
    f = _settings_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({"keep_running": cur["keep_running"], "notifications": cur["notifications"]}), encoding="utf-8")
    return settings()


# ---------- start with Windows (HKCU Run, only when the user turns it on) ----------
def _launch_command() -> str:
    here = Path(__file__).resolve().parent
    py = here / ".venv" / "Scripts" / "pythonw.exe"
    exe = py if py.is_file() else Path(sys.executable).with_name("pythonw.exe")
    return f'"{exe}" "{here / "main.py"}" --app --background'


def autostart_enabled() -> bool:
    if os.name != "nt":
        return False
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, RUN_NAME)
            return True
    except OSError:
        return False


def set_autostart(on: bool) -> bool:
    if os.name != "nt":
        return False
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if on:
            winreg.SetValueEx(k, RUN_NAME, 0, winreg.REG_SZ, _launch_command())
        else:
            try:
                winreg.DeleteValue(k, RUN_NAME)
            except FileNotFoundError:
                pass
    return on


# ---------- persisted task queue ----------
def _queue_file() -> Path:
    import agent_config

    return agent_config.storage_dir() / "task_queue.json"


def _load_queue() -> list[dict[str, Any]]:
    try:
        data = json.loads(_queue_file().read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _save_queue(items: list[dict[str, Any]]) -> None:
    f = _queue_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(items[-200:]), encoding="utf-8")
    os.replace(tmp, f)


def task_started(session: str, text: str, files: list[str] | None = None) -> str:
    tid = uuid.uuid4().hex[:10]
    with _lock:
        q = _load_queue()
        q.append({"id": tid, "session": session, "text": text, "files": files or [], "started": time.time(),
                  "status": "running", "tries": 0})
        _save_queue(q)
    return tid


def task_finished(tid: str, status: str = "done") -> None:
    with _lock:
        q = [t for t in _load_queue() if t.get("id") != tid]
        _save_queue(q)


def unfinished() -> list[dict[str, Any]]:
    with _lock:
        return [t for t in _load_queue() if t.get("status") in {"running", "queued"}]


def resume_unfinished(run: Callable[[dict[str, Any]], Any], max_age_hours: float = 24.0) -> list[str]:
    """Called once at start: re-run tasks a restart or crash cut off (each at most twice)."""
    resumed = []
    with _lock:
        q = _load_queue()
        keep = []
        for t in q:
            if t.get("status") not in {"running", "queued"}:
                continue
            if time.time() - float(t.get("started") or 0) > max_age_hours * 3600 or int(t.get("tries") or 0) >= 2:
                continue
            t["tries"] = int(t.get("tries") or 0) + 1
            keep.append(t)
        _save_queue([])
    try:
        import safe_mode

        if safe_mode.paused():
            with _lock:
                _save_queue(keep)
            return []
    except Exception:
        pass
    for t in keep:
        resumed.append(t["id"])
        threading.Thread(target=run, args=(t,), daemon=True, name="resume-" + t["id"]).start()
    return resumed


# ---------- notifications + tray ----------
def notify(title: str, message: str) -> None:
    if not settings()["notifications"]:
        return
    sent_notes.append((title, message))
    del sent_notes[:-50]
    try:
        if notifier is not None:
            notifier(title, message)
        elif not _toast(title, message) and _tray is not None:
            _tray.notify(message[:250], title[:60])   # older Windows / toast package missing: tray balloon
    except Exception:
        pass


_toaster: Any = None


_AUMID_DONE = {"v": False}


def _register_aumid() -> None:
    """1.4.19: name the app ID in the registry too, so the toast header says Ped Bot even before the
    Start Menu shortcut is indexed (HKCU\\Software\\Classes\\AppUserModelId\\<id>: DisplayName, IconUri)."""
    if _AUMID_DONE["v"] or os.name != "nt":
        return
    _AUMID_DONE["v"] = True
    try:
        import winreg
        import win_chrome
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, "Software\\Classes\\AppUserModelId\\" + win_chrome.APP_ID) as key:
            winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, "Ped Bot")
            icon = win_chrome.icon_path()
            if icon:
                winreg.SetValueEx(key, "IconUri", 0, winreg.REG_SZ, str(icon))
    except Exception:
        pass


def _toast(title: str, message: str) -> bool:
    """1.4.18: a real Windows toast sent as Ped Bot's app ID (the Start Menu shortcut carries it),
    so Windows shows 'Ped Bot' and its icon instead of 'Python'."""
    global _toaster
    if os.name != "nt":
        return False
    try:
        from windows_toasts import InteractableWindowsToaster, Toast  # type: ignore
        import win_chrome
    except Exception:
        return False
    try:   # 1.4.19: WinRT needs COM on the calling thread; app threads had none (OSError -> "Python" tray balloon)
        import pythoncom  # type: ignore
        pythoncom.CoInitialize()
    except Exception:
        pass
    _register_aumid()
    try:
        if _toaster is None:
            if win_chrome.register_shortcut_app_id() not in ("set", "ok"):
                return False
            _toaster = InteractableWindowsToaster("Ped Bot", notifierAUMID=win_chrome.APP_ID)
        toast = Toast([title[:60], message[:250]])
        _toaster.show_toast(toast)
        return True
    except Exception as exc:
        print(f"[notify] toast failed, using the tray: {type(exc).__name__}: {str(exc)[:160]}", flush=True)
        return False


def start_tray(show: Callable[[], Any], quit_app: Callable[[], Any], pause: Callable[[], Any]) -> bool:
    global _tray
    try:
        import pystray  # type: ignore
        from PIL import Image
    except ImportError:
        return False
    here = Path(__file__).resolve().parent
    img_path = next((p for p in (here / "app_static" / "icon-192.png", here / "docs" / "icon.png") if p.is_file()), None)
    image = Image.open(img_path) if img_path else Image.new("RGBA", (64, 64), (91, 108, 255, 255))
    menu = pystray.Menu(pystray.MenuItem("Open Ped Bot", lambda *_: show(), default=True),
                        pystray.MenuItem("Pause all / Resume", lambda *_: pause()),
                        pystray.MenuItem("Quit Ped Bot", lambda *_: quit_app()))
    _tray = pystray.Icon("PedBot", image, "Ped Bot - working in the background", menu)
    _tray.run_detached()
    return True


def stop_tray() -> None:
    global _tray
    if _tray is not None:
        try:
            _tray.stop()
        except Exception:
            pass
        _tray = None
