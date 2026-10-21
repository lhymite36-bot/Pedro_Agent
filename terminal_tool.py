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


def argv_for(command: str, shell: str) -> "list[str] | str":
    shell = (shell or "powershell").casefold()
    if os.name != "nt":
        return ["/bin/sh", "-c", command]
    if shell in {"cmd", "cmd.exe", "command prompt"}:
        # A plain string with /s keeps the user's quotes intact (a list would turn "" into \"\").
        exe = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "cmd.exe")
        return f'"{exe}" /d /s /c "{command}"'
    if shell in {"pwsh", "powershell 7"}:
        return ["pwsh", "-NoProfile", "-NonInteractive", "-Command", command]
    return ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command]


# 1.4.16: a warm PowerShell. Starting powershell.exe costs 1-3 s on a busy PC, so one console is started
# while the approval card is on screen (or kept after a command) and the approved command is fed to it.
# Same visible console as before (no hidden flag, nothing encoded). It closes after WARM_IDLE_SECONDS.
# Only plain cmdlet pipelines use it (they cannot read stdin); anything else starts a fresh console as before.
import threading
import uuid

WARM_IDLE_SECONDS = 90
_CMDLET = re.compile(r"^\s*(\(|\$\w|[A-Za-z]+-[A-Za-z]+\b|(dir|ls|gci|gi|cat|type|echo|write|sort|select|where|measure|"
                     r"foreach|ft|fl|fw|gps|gsv|gdr|pwd|cd|sl|hostname|whoami)\b)", re.I)
_STDIN_READERS = re.compile(r"read-host|\bpause\b|-confirm\b|get-credential|\bexit\b|out-gridview|start-process|"
                            r"\binvoke-|\bpython|\bnode|\bgit\b|\bnpm|\bpip|\bwinget|\bcmd\b|\.exe\b", re.I)
_warm_lock = threading.Lock()
_warm: dict[str, Any] = {"proc": None, "timer": None}


def warm_ok(command: str, shell: str = "powershell") -> bool:
    if os.name != "nt" or (shell or "powershell").casefold() not in {"powershell", "powershell.exe", ""}:
        return False
    text = str(command or "")
    if "\n" in text or "\r" in text or "`" in text or len(text) > 2000 or _STDIN_READERS.search(text):
        return False
    parts = [p for p in re.split(r"[|;]", text) if p.strip()]
    return bool(parts) and all(_CMDLET.match(p) for p in parts)


def _close_warm() -> None:
    with _warm_lock:
        proc, _warm["proc"] = _warm["proc"], None
    if proc is not None and proc.poll() is None:
        try:
            proc.stdin.close()
            proc.wait(timeout=3)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass


def _arm_idle() -> None:
    with _warm_lock:
        if _warm["timer"] is not None:
            _warm["timer"].cancel()
        timer = threading.Timer(WARM_IDLE_SECONDS, _close_warm)
        timer.daemon = True
        _warm["timer"] = timer
        timer.start()


def prewarm() -> None:
    """Start the warm console now (called when a terminal approval card appears). Cheap if one is ready."""
    if os.name != "nt":
        return
    with _warm_lock:
        if _warm["proc"] is not None and _warm["proc"].poll() is None:
            ready = True
        else:
            ready = False
            try:
                _warm["proc"] = subprocess.Popen(
                    ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", "-"], cwd=str(Path.home()),
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    env=dict(os.environ, PYTHONIOENCODING="utf-8"), bufsize=1, text=True, encoding="utf-8", errors="replace")
            except OSError:
                _warm["proc"] = None
                return
    _arm_idle()
    _ = ready


def _take_warm() -> Any:
    with _warm_lock:
        proc, _warm["proc"] = _warm["proc"], None
    if proc is None or proc.poll() is not None:
        return None
    return proc


def _ps_quote(text: str) -> str:
    return "'" + str(text).replace("'", "''") + "'"


def _run_warm(proc: Any, command: str, folder: Path, limit: int, started: float) -> tuple[list[str], int, bool]:
    marker = "__PB_END_" + uuid.uuid4().hex[:12] + "__"
    line = (f"Set-Location -LiteralPath {_ps_quote(folder)}; $global:LASTEXITCODE = 0; $pbok = $true; "
            f"try {{ {command} }} catch {{ $pbok = $false; \"$_\" }}; if (-not $?) {{ $pbok = $false }}; "
            f"Write-Output ('{marker} ' + [int](-not $pbok) + ' ' + $LASTEXITCODE)")
    proc.stdin.write(line + "\n")
    proc.stdin.flush()
    out: list[str] = []
    size = 0
    code = -1
    timed_out = False
    assert proc.stdout is not None
    for raw in proc.stdout:
        text = raw.rstrip("\r\n")
        if text.startswith(marker):
            bits = text.split()
            failed = bits[1] if len(bits) > 1 else "1"
            last = bits[2] if len(bits) > 2 else "0"
            code = int(last) if last.lstrip("-").isdigit() and last != "0" else (1 if failed == "1" else 0)
            break
        if size < MAX_OUTPUT:
            out.append(text)
            size += len(text) + 1
        _emit({"event": "terminal", "kind": "line", "line": text[:2000]})
        if time.monotonic() - started > limit:
            timed_out = True
            proc.kill()
            break
    return out, code, timed_out


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
    import stop_token
    warm = _take_warm() if warm_ok(command, shell) else None
    if warm is not None:
        stop_token.track(warm)   # Stop kills the warm console too
        try:
            out, code, timed_out = _run_warm(warm, command, folder, limit, started)
        except (OSError, ValueError):
            out, code, timed_out = [], -1, False
        stop_token.untrack(warm)
        if stop_token.stopped() or warm.poll() is not None:
            if stop_token.stopped():
                _emit({"event": "terminal", "kind": "end", "code": code, "seconds": round(time.monotonic() - started, 1)})
                return {"ok": False, "stopped": True, "error": "Stopped by the user.", "exit_code": code}
        else:
            with _warm_lock:   # keep it for the next approved command
                if _warm["proc"] is None:
                    _warm["proc"] = warm
                else:
                    warm.kill()
            _arm_idle()
        if code != -1 or out:
            return _finish(command, shell, out, code, timed_out, started, warm=True)
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    try:
        proc = subprocess.Popen(argv, cwd=str(folder), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, env=env, bufsize=1, text=True,
                                encoding="utf-8", errors="replace")
    except OSError as exc:
        return {"ok": False, "error": f"Could not start {shell}: {exc}"}
    stop_token.track(proc)   # 1.4.15: Stop kills the whole process tree at once
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
    stop_token.untrack(proc)
    if stop_token.stopped():
        _emit({"event": "terminal", "kind": "end", "code": code, "seconds": round(time.monotonic() - started, 1)})
        return {"ok": False, "stopped": True, "error": "Stopped by the user.", "exit_code": code}
    return _finish(command, shell, out, code, timed_out, started)


def _finish(command: str, shell: str, out: list[str], code: int, timed_out: bool, started: float,
            warm: bool = False) -> dict[str, Any]:
    secs = round(time.monotonic() - started, 1)
    _emit({"event": "terminal", "kind": "end", "code": code, "seconds": secs})
    text = "\n".join(out)[-MAX_OUTPUT:]
    msg = (f"Ran in {shell} ({secs} s), exit code {code}." + (" Stopped: time limit reached." if timed_out else ""))
    tail = "\n".join(out[-20:]).strip("\n")
    if tail:   # keep the output in the chat history too (the live box only exists while it streams)
        fence = "`" * 3
        msg += "\n\n" + fence + "\n> " + command[:300] + "\n" + tail[-1500:].replace(fence, "'" * 3) + "\n" + fence
    return {"ok": code == 0 and not timed_out, "message": msg, "exit_code": code, "output": text, "seconds": secs, "warm": warm,
            "error": "" if code == 0 and not timed_out else msg + (" Last output: " + text[-400:] if text else "")}


DECLARATIONS = [{
    "name": "run_terminal_command",
    "description": ("Run ONE PowerShell or cmd command on Pedro's PC. Each command shows an approval card with the exact "
                    "command and runs only after his yes; its output streams into the chat. Use for things only a terminal "
                    "can do (git, pip, winget, builds). For listing, counting or finding files use list_files, and for disk space, memory or busy programs use pc_status: they need no approval and are much faster. One command per call; never chain unrelated steps. "
                    "Never type passwords/OTPs, never use encoded or hidden commands."),
    "parameters": {"type": "object", "properties": {
        "command": {"type": "string", "description": "The exact command line."},
        "shell": {"type": "string", "enum": ["powershell", "cmd", "pwsh"], "description": "Default powershell."},
        "cwd": {"type": "string", "description": "Working folder (default: his home folder)."},
        "timeout_seconds": {"type": "integer", "description": "Stop after this many seconds (default 600)."}},
        "required": ["command"]},
}]
TOOLS = {"run_terminal_command": run_terminal_command}
