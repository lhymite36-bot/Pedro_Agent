"""Run one terminal command (PowerShell or cmd) on this PC after Pedro approves it.

Every command needs its own yes (confirm_action treats this tool as always sensitive),
the approval card shows the exact command, and the output streams into the chat.
Commands run in a normal console process: no hidden window flag, no encoded commands.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

MAX_OUTPUT = 12000
_BLOCKED = [
    (re.compile(r"(^|\s)-(e|ec|enc|encodedcommand|encodedcomm\w*)\s", re.I), "encoded PowerShell commands are not allowed"),
    (re.compile(r"frombase64string|\bbase64\b|certutil\s+-decode", re.I), "base64 decoding is not allowed"),
    (re.compile(r"-w(indowstyle)?\s+hidden", re.I), "hidden windows are not allowed"),
    (re.compile(r"\b(format(-volume)?\s+[a-z]:|diskpart|bcdedit|vssadmin\s+delete|cipher\s+/w)", re.I), "disk-wiping and boot commands are blocked"),
    (re.compile(r"\b(rm|del|remove-item|rd|rmdir)\b[^|;&]*\s(c:\\?\s*$|c:\\windows|\$env:windir|/\s*$)", re.I), "deleting system folders is blocked"),
]

listener: Callable[[dict[str, Any]], None] | None = None   # set per turn by agent_core


def _emit(ev: dict[str, Any]) -> None:
    try:
        import agent_core
        fn = agent_core._active_listener()
    except Exception:
        fn = listener
    if fn is not None:
        try:
            fn(ev)
        except Exception:
            pass


def check(command: str) -> str | None:
    text = " " + " ".join(str(command or "").split()) + " "
    if not text.strip():
        return "No command given."
    for rx, why in _BLOCKED:
        if rx.search(text):
            return f"Refused: {why}."
    return None


def argv_for(command: str, shell: str) -> list[str]:
    shell = (shell or "powershell").casefold()
    if os.name != "nt":
        return ["/bin/sh", "-c", command]
    if shell in {"cmd", "cmd.exe", "command prompt"}:
        return [os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "cmd.exe"), "/d", "/c", command]
    if shell in {"pwsh", "powershell 7"}:
        return ["pwsh", "-NoProfile", "-NonInteractive", "-Command", command]
    return ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command]


def run_terminal_command(command: str, shell: str = "powershell", cwd: str = "", timeout_seconds: int = 600) -> dict[str, Any]:
    why = check(command)
    if why:
        return {"ok": False, "error": why, "blocked_by_rules": True}
    folder = Path(os.path.expandvars(os.path.expanduser(cwd))) if cwd else Path.home()
    if not folder.is_dir():
        return {"ok": False, "error": f"Folder not found: {folder}"}
    limit = max(5, min(int(timeout_seconds or 600), 3600))
    argv = argv_for(command, shell)
    _emit({"event": "terminal", "kind": "start", "shell": shell, "command": command, "cwd": str(folder)})
    started = time.monotonic()
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    try:
        proc = subprocess.Popen(argv, cwd=str(folder), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, env=env, bufsize=1, text=True,
                                encoding="utf-8", errors="replace")
    except OSError as exc:
        return {"ok": False, "error": f"Could not start {argv[0]}: {exc}"}
    out: list[str] = []
    size = 0
    timed_out = False
    assert proc.stdout is not None
    for line in proc.stdout:
        line = line.rstrip("\r\n")
        if size < MAX_OUTPUT:
            out.append(line)
            size += len(line) + 1
        _emit({"event": "terminal", "kind": "line", "line": line[:2000]})
        if time.monotonic() - started > limit:
            timed_out = True
            proc.kill()
            break
    try:
        code = proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        code = -1
    secs = round(time.monotonic() - started, 1)
    _emit({"event": "terminal", "kind": "end", "code": code, "seconds": secs})
    text = "\n".join(out)[-MAX_OUTPUT:]
    msg = (f"Ran in {shell} ({secs} s), exit code {code}." + (" Stopped: time limit reached." if timed_out else ""))
    return {"ok": code == 0 and not timed_out, "message": msg, "exit_code": code, "output": text, "seconds": secs,
            "error": "" if code == 0 and not timed_out else msg + (" Last output: " + text[-400:] if text else "")}


DECLARATIONS = [{
    "name": "run_terminal_command",
    "description": ("Run ONE PowerShell or cmd command on Pedro's PC. Each command shows an approval card with the exact "
                    "command and runs only after his yes; its output streams into the chat. Use for things only a terminal "
                    "can do (git, pip, winget, dir listings, builds). One command per call; never chain unrelated steps. "
                    "Never type passwords/OTPs, never use encoded or hidden commands."),
    "parameters": {"type": "object", "properties": {
        "command": {"type": "string", "description": "The exact command line."},
        "shell": {"type": "string", "enum": ["powershell", "cmd", "pwsh"], "description": "Default powershell."},
        "cwd": {"type": "string", "description": "Working folder (default: his home folder)."},
        "timeout_seconds": {"type": "integer", "description": "Stop after this many seconds (default 600)."}},
        "required": ["command"]},
}]
TOOLS = {"run_terminal_command": run_terminal_command}
