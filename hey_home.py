"""Hey Ped hands-free extras: music, volume, lock, apps, timers, optional Home Assistant.

Wake word itself already lives in wake_word.py. This module handles the command
after “Hey Ped”. Phone listener pauses when battery is below 20%.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

_timers: list[dict[str, Any]] = []
_lock = threading.Lock()
run_override = None  # tests: fn(kind, **kw) -> dict


def _ha() -> tuple[str, str]:
    url = os.environ.get("HOME_ASSISTANT_URL", "").strip().rstrip("/")
    token = os.environ.get("HOME_ASSISTANT_TOKEN", "").strip()
    return url, token


def battery_ok(level: int | None) -> bool:
    if level is None:
        return True
    return int(level) >= 20


def _open_url(url: str) -> dict[str, Any]:
    if run_override:
        return run_override("url", url=url)
    import webbrowser
    webbrowser.open(url)
    return {"ok": True, "message": "Opened the link. You press play."}


def music(query: str) -> dict[str, Any]:
    q = urllib.request.quote(query or "lofi")
    # YouTube Music and Spotify links — Pedro starts playback himself
    yt = f"https://music.youtube.com/search?q={q}"
    sp = f"https://open.spotify.com/search/{q}"
    opened = _open_url(yt)
    opened["links"] = {"youtube_music": yt, "spotify": sp}
    opened["message"] = f"Opened YouTube Music for “{query}”. Spotify: {sp}. Ped Bot does not press play for you."
    return opened


def volume(delta: str) -> dict[str, Any]:
    if run_override:
        return run_override("volume", delta=delta)
    if os.name != "nt":
        return {"ok": False, "error": "Volume keys are set up on Windows."}
    mapping = {
        "up": ["powershell", "-NoProfile", "-Command",
               "(New-Object -ComObject WScript.Shell).SendKeys([char]175)"],
        "down": ["powershell", "-NoProfile", "-Command",
                 "(New-Object -ComObject WScript.Shell).SendKeys([char]174)"],
        "mute": ["powershell", "-NoProfile", "-Command",
                 "(New-Object -ComObject WScript.Shell).SendKeys([char]173)"],
    }
    key = "up" if "up" in delta or "loud" in delta else "mute" if "mute" in delta else "down"
    subprocess.run(mapping[key], check=False, timeout=8, capture_output=True)
    return {"ok": True, "message": f"Volume {key}."}


def lock_pc() -> dict[str, Any]:
    if run_override:
        return run_override("lock")
    if os.name != "nt":
        return {"ok": False, "error": "Lock is set up on Windows."}
    subprocess.run(["rundll32.exe", "user32.dll,LockWorkStation"], check=False, timeout=8)
    return {"ok": True, "message": "Locked the PC."}


def open_app(name: str) -> dict[str, Any]:
    if run_override:
        return run_override("app", name=name)
    name = " ".join((name or "").split())[:80]
    if not name:
        return {"ok": False, "error": "Which app?"}
    if os.name == "nt":
        subprocess.Popen(["cmd", "/c", "start", "", name], shell=False)
    else:
        subprocess.Popen(["xdg-open", name])
    return {"ok": True, "message": f"Opening {name}."}


def timer(seconds: int, label: str = "") -> dict[str, Any]:
    seconds = max(5, min(24 * 3600, int(seconds or 0)))
    item = {"id": str(int(time.time() * 1000)), "at": time.time() + seconds, "label": label or "timer", "seconds": seconds}

    def fire() -> None:
        time.sleep(seconds)
        try:
            import checkins
            checkins.post("timer", f"Timer done: {item['label']}", key="timer-" + item["id"])
        except Exception:
            pass
        if os.name == "nt":
            try:
                import winsound
                winsound.MessageBeep(-1)
            except Exception:
                pass

    threading.Thread(target=fire, daemon=True).start()
    with _lock:
        _timers.append(item)
    return {"ok": True, "message": f"Timer set for {seconds} seconds ({item['label']}).", "timer": item}


def lights(command: str) -> dict[str, Any]:
    url, token = _ha()
    if not url or not token:
        return {
            "ok": False,
            "error": "Home Assistant is optional. Put HOME_ASSISTANT_URL and HOME_ASSISTANT_TOKEN in this PC's .env (local only, free).",
        }
    if run_override:
        return run_override("lights", command=command)
    on = not re.search(r"\b(off|dark|kill)\b", command or "", re.I)
    body = json.dumps({"entity_id": "all"}).encode()
    path = "/api/services/light/turn_on" if on else "/api/services/light/turn_off"
    req = urllib.request.Request(
        url + path,
        data=body,
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            resp.read()
        return {"ok": True, "message": "Lights " + ("on" if on else "off") + "."}
    except urllib.error.URLError as exc:
        return {"ok": False, "error": f"Home Assistant did not answer: {exc}"}


def parse_seconds(text: str) -> int:
    m = re.search(r"(\d+)\s*(seconds?|secs?)\b", text, re.I)
    if m:
        return int(m.group(1))
    m = re.search(r"(\d+)\s*(minutes?|mins?)\b", text, re.I)
    if m:
        return int(m.group(1)) * 60
    m = re.search(r"(\d+)\s*(hours?|hrs?)\b", text, re.I)
    if m:
        return int(m.group(1)) * 3600
    m = re.search(r"(\d+)\s*s\b", text, re.I)
    if m:
        return int(m.group(1))
    m = re.search(r"(\d+)\s*m\b", text, re.I)
    if m:
        return int(m.group(1)) * 60
    m = re.search(r"(\d+)\s*h\b", text, re.I)
    if m:
        return int(m.group(1)) * 3600
    return 60


def try_handle(text: str, battery: int | None = None) -> dict[str, Any] | None:
    """Return a result if this is a home command, else None (let chat handle it)."""
    if not battery_ok(battery):
        return {"ok": False, "error": "Battery is below 20%, so the hands-free listener is paused.", "paused": True}
    low = " ".join((text or "").split()).casefold()
    if not low:
        return None
    if re.search(r"\b(play|music|spotify|youtube music)\b", low):
        q = re.sub(r"^(play|put on|listen to)\s+", "", low)
        q = re.sub(r"\s+(on (spotify|youtube( music)?))$", "", q)
        return music(q or "lofi")
    if re.search(r"\b(volume|mute|quieter|louder)\b", low):
        return volume(low)
    if re.search(r"\b(lock( the)? (pc|computer|screen)|lock pc)\b", low):
        return lock_pc()
    if re.search(r"\b(timer|remind me|alarm)\b", low):
        return timer(parse_seconds(low), text)
    if re.search(r"\b(lights?|lamp|home assistant)\b", low):
        return lights(low)
    m = re.search(r"\bopen\s+(.+)$", low)
    if m and len(m.group(1).split()) <= 4:
        return open_app(m.group(1))
    return None


def status() -> dict[str, Any]:
    url, token = _ha()
    with _lock:
        timers = list(_timers[-10:])
    return {
        "ok": True,
        "ha": bool(url and token),
        "ha_url": url,
        "timers": timers,
        "battery_pause_below": 20,
        "commands": ["play lofi on youtube music", "volume up", "lock the pc", "open chrome", "timer 5 minutes", "lights off"],
        "note": "Always-on “Hey Ped” uses the existing wake word. On the phone it pauses under 20% battery. Home Assistant is optional and local.",
    }


def handle(action: str, data: dict[str, Any]) -> dict[str, Any]:
    if action in ("", "status"):
        return status()
    if action in ("do", "command"):
        hit = try_handle(str(data.get("text") or data.get("command") or ""), data.get("battery"))
        return hit or {"ok": False, "error": "Not a home command. Try play, volume, lock, open, timer, or lights."}
    return {"ok": False, "error": "Unknown home action."}
