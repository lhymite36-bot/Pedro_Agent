"""Local crash reports. Saved on this PC only; nothing is ever sent anywhere.

Settings shows the latest reports with "Copy report" (to paste wherever you like)
and "Open folder". Keys, tokens and passwords are masked before saving.
"""

from __future__ import annotations

import os
import platform
import re
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Any

VERSION = "1.7.1"
KEEP = 30
_SECRET = re.compile(
    r"(AIza[0-9A-Za-z_\-]{20,}|gsk_[0-9A-Za-z]{20,}|sk-[0-9A-Za-z_\-]{20,}|ghp_[0-9A-Za-z]{20,}|github_pat_[0-9A-Za-z_]{20,}"
    r"|ya29\.[0-9A-Za-z_\-]+|xox[abpr]-[0-9A-Za-z\-]+|\b\d{8,10}:[0-9A-Za-z_\-]{30,})")
_KV = re.compile(r"(?i)\b(api[_-]?key|token|secret|password|passwd|pin|cvv|authorization)\b(\s*[=:]\s*)(\S+)")


def folder() -> Path:
    try:
        import agent_config

        return agent_config.storage_dir() / "crash_reports"
    except Exception:
        return Path(__file__).resolve().parent / "workspace" / "crash_reports"


def redact(text: str) -> str:
    text = _SECRET.sub("[hidden]", text)
    return _KV.sub(lambda m: m.group(1) + m.group(2) + "[hidden]", text)


def record(exc: BaseException | None = None, where: str = "", tb: Any = None) -> Path | None:
    try:
        if exc is not None and tb is None:
            tb = exc.__traceback__
        body = "".join(traceback.format_exception(type(exc), exc, tb)) if exc is not None else traceback.format_exc()
        lines = [f"Ped Bot {VERSION} crash report", time.strftime("Time: %Y-%m-%d %H:%M:%S %z"),
                 f"Where: {where or 'app'}", f"Windows/OS: {platform.platform()}", f"Python: {sys.version.split()[0]}",
                 "", body]
        d = folder()
        d.mkdir(parents=True, exist_ok=True)
        path = d / time.strftime("crash-%Y%m%d-%H%M%S.txt")
        n = 1
        while path.exists():
            path = d / time.strftime(f"crash-%Y%m%d-%H%M%S-{n}.txt")
            n += 1
        path.write_text(redact("\n".join(lines)), encoding="utf-8")
        for old in sorted(d.glob("crash-*.txt"))[:-KEEP]:
            old.unlink(missing_ok=True)
        return path
    except Exception:
        return None


def listing(limit: int = 10) -> list[dict[str, Any]]:
    d = folder()
    if not d.is_dir():
        return []
    out = []
    for p in sorted(d.glob("crash-*.txt"), reverse=True)[:limit]:
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            continue
        first = next((l for l in reversed(text.strip().splitlines()) if l.strip()), "")
        out.append({"name": p.name, "when": p.stat().st_mtime, "summary": first[:200]})
    return out


def read(name: str) -> str:
    if not re.fullmatch(r"crash-[0-9\-]+\.txt", name or ""):
        return ""
    p = folder() / name
    return p.read_text(encoding="utf-8") if p.is_file() else ""


def open_folder() -> dict[str, Any]:
    d = folder()
    d.mkdir(parents=True, exist_ok=True)
    try:
        if os.name == "nt":
            os.startfile(str(d))  # noqa: S606 - opens Explorer on the user's own folder
        return {"ok": True, "path": str(d)}
    except OSError as exc:
        return {"ok": False, "error": str(exc), "path": str(d)}


def install() -> None:
    old = sys.excepthook

    def hook(t, e, tb):
        record(e, "main thread", tb)
        old(t, e, tb)

    def thook(args):
        if args.exc_type is not SystemExit:
            record(args.exc_value, f"thread {getattr(args.thread, 'name', '')}", args.exc_traceback)

    sys.excepthook = hook
    threading.excepthook = thook
