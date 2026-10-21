"""Auto-update from GitHub releases (lhymite36-bot/Pedro_Agent, tags v*-windows).

check()    - finds the newest v*-windows release; "Update available" when newer.
download() - fetches PedBot-Setup-<v>.exe and checks its SHA-256 against the hash
             written in the release notes. A mismatch deletes the file.
install()  - only after you press Install (confirm="yes"): starts the verified
             installer, which keeps your chats, settings and keys, and closes the app.
Nothing is downloaded or installed without you.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any, Callable

VERSION = "1.5.0"
REPO = "lhymite36-bot/Pedro_Agent"
API = f"https://api.github.com/repos/{REPO}/releases?per_page=15"
TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)-windows$")
ASSET = re.compile(r"^PedBot-Setup-(\d+\.\d+\.\d+)\.exe$")

fetch_json: Callable[[str], Any] | None = None       # tests replace these
fetch_file: Callable[[str, Path], None] | None = None
_last: dict[str, Any] = {}
_lock = threading.Lock()


def _vt(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3])


def _get_json(url: str) -> Any:
    if fetch_json is not None:
        return fetch_json(url)
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "PedBot-updater"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def _get_file(url: str, dest: Path) -> None:
    if fetch_file is not None:
        fetch_file(url, dest)
        return
    req = urllib.request.Request(url, headers={"User-Agent": "PedBot-updater"})
    with urllib.request.urlopen(req, timeout=120) as r, open(dest, "wb") as f:
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)


def folder() -> Path:
    import agent_config

    return agent_config.storage_dir() / "updates"


def sha_from_notes(notes: str, name: str) -> str:
    for line in (notes or "").splitlines():
        if name in line:
            m = re.search(r"\b([0-9a-fA-F]{64})\b", line)
            if m:
                return m.group(1).lower()
    return ""


def check(current: str = VERSION) -> dict[str, Any]:
    try:
        releases = _get_json(API)
    except Exception as exc:
        return {"ok": False, "error": f"Could not reach GitHub: {exc}", "update_available": False}
    best = None
    for rel in releases if isinstance(releases, list) else []:
        if rel.get("draft") or rel.get("prerelease"):
            continue
        m = TAG.match(str(rel.get("tag_name") or ""))
        if not m:
            continue
        v = ".".join(m.groups())
        if best is None or _vt(v) > _vt(best[0]):
            best = (v, rel)
    if best is None:
        out = {"ok": True, "update_available": False, "current": current, "message": "No Windows release found."}
    else:
        v, rel = best
        asset = next((a for a in rel.get("assets") or [] if ASSET.match(str(a.get("name") or ""))), None)
        newer = _vt(v) > _vt(current)
        out = {"ok": True, "current": current, "latest": v, "update_available": bool(newer and asset),
               "notes_url": rel.get("html_url", ""),
               "message": (f"Update available: Ped Bot {v}" if newer and asset else f"Ped Bot {current} is up to date.")}
        if asset:
            out.update(asset=asset["name"], url=asset.get("browser_download_url", ""),
                       sha256=sha_from_notes(str(rel.get("body") or ""), asset["name"]))
    with _lock:
        _last.clear()
        _last.update(out, checked=time.time())
    return out


def last() -> dict[str, Any]:
    with _lock:
        return dict(_last)


def download() -> dict[str, Any]:
    info = last() if last().get("update_available") else check()
    if not info.get("update_available"):
        return {"ok": False, "error": info.get("message") or "No update available."}
    if not info.get("sha256"):
        return {"ok": False, "error": "The release notes have no SHA-256 for the installer, so it was not downloaded."}
    d = folder()
    d.mkdir(parents=True, exist_ok=True)
    dest = d / info["asset"]
    part = dest.with_suffix(".part")
    try:
        _get_file(info["url"], part)
    except Exception as exc:
        part.unlink(missing_ok=True)
        return {"ok": False, "error": f"Download failed: {exc}"}
    h = hashlib.sha256()
    with open(part, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    if h.hexdigest() != info["sha256"]:
        part.unlink(missing_ok=True)
        return {"ok": False, "error": "The download did not match the SHA-256 in the release notes, so it was deleted."}
    os.replace(part, dest)
    with _lock:
        _last["downloaded"] = str(dest)
    return {"ok": True, "path": str(dest), "version": info["latest"], "sha256": info["sha256"],
            "message": f"Ped Bot {info['latest']} downloaded and verified. Press Install to update (your data stays)."}


def install(confirm: str = "", launcher: Callable[[list[str]], Any] | None = None) -> dict[str, Any]:
    if str(confirm).strip().lower() != "yes":
        return {"ok": False, "error": "Installing needs your OK: press Install."}
    path = last().get("downloaded")
    if not path or not Path(path).is_file():
        return {"ok": False, "error": "Download the update first."}
    info = last()
    h = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    if info.get("sha256") and h != info["sha256"]:
        return {"ok": False, "error": "The installer changed since it was verified; not running it."}
    (launcher or (lambda cmd: subprocess.Popen(cmd, close_fds=True)))([path])
    return {"ok": True, "message": "The installer is open. Ped Bot closes so it can update; your chats and settings stay."}


def start_background_check(delay: float = 30.0) -> None:
    def run() -> None:
        time.sleep(delay)
        try:
            check()
        except Exception:
            pass

    threading.Thread(target=run, daemon=True, name="update-check").start()
