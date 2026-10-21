"""Online / Offline / Auto model mode (1.5.4).

online  - cloud models as before (Ollama only as the old last-resort fallback)
offline - Ollama only; no cloud model or internet tool is called at all
auto    - default: cloud while the internet answers, Ollama as soon as it doesn't, back when it does

Internet detection is one small HTTPS request (honours the app's proxy settings, so blocking the
app's cloud traffic is detected the same way as a real outage), cached for a few seconds and
re-checked by a light background watcher while in Auto mode.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any

MODES = ("auto", "online", "offline")
PROBE_URL = "https://www.gstatic.com/generate_204"
PROBE_TIMEOUT = 1.5
PROBE_TTL = 8.0
KEEP_ALIVE = "30m"
NUM_CTX = 8192

_lock = threading.Lock()
_state: dict[str, Any] = {"online": None, "at": -1e9, "watch": False, "last_engine": "", "last_model": ""}
online_override: bool | None = None          # tests

OFFLINE_TOOLS = (
    "list_files", "search_local_files", "search_files_by_time", "open_local_file", "write_text_file",
    "create_directory", "delete_path", "launch_application", "launch_any_app", "kill_process", "focus_window",
    "manage_windows_and_processes", "manage_window_layout", "run_terminal_command", "take_screenshot",
    "capture_screenshot_file", "pc_status", "system_diagnostics", "remember_fact", "recall_memory",
    "get_clipboard_text", "press_keys", "type_text", "ui_read", "ui_find", "ui_click", "ui_set_text",
    "make_document", "list_routines", "undo_last_change", "shutdown_computer",
)
_NET_TOOL = re.compile(r"web|search_youtube|youtube|gmail|email|drive_search|connector|whatsapp|browser|download|"
                       r"open_website|navigate|watch_video|bot_send|telegram|remote_update|mcp_router|people_contact|"
                       r"build_app|builder_install|ship_app|gemini|webcam_vision|delegate|code_engineer|self_upgrade|"
                       r"place_order|start_order|wingz", re.I)
_NET_ASK = re.compile(r"\b(search (the )?(web|internet|online)|google (it|for|this)|look (it )?up online|gmail|e-?mail|"
                      r"youtube|website|web ?site|weather|news|download|upload|whatsapp|telegram|browse|online)\b", re.I)


def _file() -> Path:
    import agent_config
    return agent_config.storage_dir() / "model_mode.json"


def _load() -> dict[str, Any]:
    try:
        return json.loads(_file().read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(data: dict[str, Any]) -> None:
    p = _file(); p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=1), encoding="utf-8")


def mode() -> str:
    import sys
    if "unittest" in sys.modules and not os.environ.get("PEDBOT_MODE_TESTS"):
        return "online"   # the old suite expects cloud behaviour and no network probes
    m = str(os.environ.get("PEDBOT_MODEL_MODE") or _load().get("mode") or "auto").casefold()
    return m if m in MODES else "auto"


def set_mode(value: str) -> dict[str, Any]:
    value = str(value or "").casefold()
    if value not in MODES:
        return {"ok": False, "error": f"Mode must be one of {', '.join(MODES)}."}
    data = _load(); data["mode"] = value; _save(data)
    if value != "online":
        threading.Thread(target=prepare_local, daemon=True, name="pb-ollama-warm").start()
    start_watch()
    return {"ok": True, **status(probe=True)}


def chosen_model() -> str:
    return str(_load().get("ollama_model") or "").strip()


def set_model(name: str) -> dict[str, Any]:
    import local_llm
    names = local_llm.installed_models(refresh=True)
    if name not in names:
        return {"ok": False, "error": f"'{name}' is not installed in Ollama. Installed: {', '.join(names) or 'none'}"}
    data = _load(); data["ollama_model"] = name; _save(data)
    threading.Thread(target=prepare_local, daemon=True, name="pb-ollama-warm").start()
    return {"ok": True, **status()}


# ---------- internet ----------
def online(force: bool = False) -> bool:
    if online_override is not None:
        return bool(online_override)
    now = time.monotonic()
    with _lock:
        if not force and _state["online"] is not None and now - _state["at"] < PROBE_TTL:
            return bool(_state["online"])
    ok = False
    try:
        with urllib.request.urlopen(PROBE_URL, timeout=PROBE_TIMEOUT) as r:
            ok = r.status in (200, 204)
    except Exception:
        ok = False
    with _lock:
        changed = _state["online"] is not None and _state["online"] != ok
        _state.update(online=ok, at=time.monotonic())
    if changed:
        _announce(ok)
    return ok


def _announce(ok: bool) -> None:
    try:
        import live_sync
        live_sync.notify("changed", what="model_mode")
    except Exception:
        pass
    if not ok and mode() == "auto":
        threading.Thread(target=prepare_local, daemon=True).start()


def start_watch() -> None:
    with _lock:
        if _state["watch"]:
            return
        _state["watch"] = True

    def loop() -> None:
        while True:
            try:
                if mode() == "auto":
                    online(force=True)
            except Exception:
                pass
            time.sleep(5 if _state.get("online") is False else 10)
    threading.Thread(target=loop, daemon=True, name="pb-net-watch").start()


def use_local() -> bool:
    m = mode()
    if m == "offline":
        return True
    if m == "online":
        return False
    return not online()


def cloud_blocked() -> bool:
    """True when nothing may go to the cloud (Offline mode, or Auto with no internet)."""
    return use_local()


def tool_needs_internet(name: str) -> bool:
    return bool(_NET_TOOL.search(name or "")) and name not in OFFLINE_TOOLS


def needs_internet_reply(user_text: str) -> str:
    if _NET_ASK.search(user_text or ""):
        why = "Offline mode is on" if mode() == "offline" else "there's no internet right now"
        return (f"That needs internet (web search, Gmail, YouTube, websites and cloud models do), and {why}, "
                "so I didn't try it. PC tasks, files and the terminal still work offline.")
    return ""


# ---------- Ollama ----------
def _ollama_exe() -> str:
    for cand in (shutil.which("ollama"), os.path.expandvars(r"%LOCALAPPDATA%\Programs\Ollama\ollama.exe"),
                 os.path.expandvars(r"%ProgramFiles%\Ollama\ollama.exe")):
        if cand and Path(cand).is_file():
            return cand
    return ""


def ensure_ollama(wait: float = 12.0) -> bool:
    """Start `ollama serve` (no window) when it isn't answering."""
    import local_llm
    if local_llm.ollama_reachable():
        return True
    exe = _ollama_exe()
    if not exe:
        return False
    flags = 0x08000000 if os.name == "nt" else 0          # CREATE_NO_WINDOW
    try:
        subprocess.Popen([exe, "serve"], creationflags=flags, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         stdin=subprocess.DEVNULL, close_fds=True)
    except Exception:
        return False
    end = time.monotonic() + wait
    while time.monotonic() < end:
        if local_llm.ollama_reachable():
            return True
        time.sleep(0.4)
    return False


def prepare_local() -> bool:
    """Start Ollama and load the model into memory (kept loaded for KEEP_ALIVE) so the first answer is fast."""
    import local_llm
    if not ensure_ollama():
        return False
    try:
        body = json.dumps({"model": local_llm.model_name(), "prompt": "", "keep_alive": KEEP_ALIVE,
                           "options": {"num_ctx": NUM_CTX}}).encode()
        req = urllib.request.Request("http://127.0.0.1:11434/api/generate", data=body,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=120) as r:
            r.read()
        return True
    except Exception:
        return False


def note_answer(engine: str, model: str) -> None:
    _state.update(last_engine=engine, last_model=model)


def status(probe: bool = False) -> dict[str, Any]:
    import local_llm
    m = mode()
    net = online(force=probe) if m != "offline" else (_state["online"] if _state["online"] is not None else None)
    local = m == "offline" or (m == "auto" and net is False)
    return {"mode": m, "online": net, "engine": "local" if local else "cloud",
            "local_model": local_llm.model_name(), "chosen_model": chosen_model(),
            "installed": local_llm.installed_models(), "ollama_running": local_llm.ollama_reachable(),
            "last_engine": _state["last_engine"], "last_model": _state["last_model"]}
