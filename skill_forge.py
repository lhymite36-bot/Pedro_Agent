"""Self-coding skills: a bot writes a plugin, tests it in a sandbox, goes live only after Approve.

Skills cannot touch system folders or secrets. Disable and Undo are always available.
"""

from __future__ import annotations

import ast
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

BLOCKED_IMPORTS = frozenset({
    "ctypes", "socket", "http", "urllib", "requests", "subprocess", "shutil",
    "pathlib", "pickle", "multiprocessing", "ctypes", "winreg", "msvcrt",
})
BLOCKED_CALLS = frozenset({"system", "popen", "exec", "eval", "open", "__import__"})
SYSTEM_ROOTS = ("C:\\Windows", "C:\\Program Files", "C:\\Program Files (x86)", "/usr", "/bin", "/etc")
write_override = None  # tests: fn(task) -> dict{name,code,lang}


def _root() -> Path:
    import agent_config
    p = agent_config.storage_dir() / "pro190" / "skills"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _sandbox() -> Path:
    p = _root() / "sandbox"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _store() -> Path:
    return _root() / "live.json"


def _undo() -> Path:
    return _root() / "undo.json"


def _load_live() -> list[dict[str, Any]]:
    try:
        data = json.loads(_store().read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _save_live(rows: list[dict[str, Any]]) -> None:
    tmp = _store().with_suffix(".tmp")
    tmp.write_text(json.dumps(rows, indent=1), encoding="utf-8")
    tmp.replace(_store())


def _is_safe_code(code: str, lang: str) -> str | None:
    if re.search(r"(\.\.\\|/\.\.|C:\\Windows|Program Files|\.env|GEMINI_API_KEY|SERVICE_ROLE)", code, re.I):
        return "The skill tried to touch a system folder or a secret."
    if lang == "python":
        try:
            tree = ast.parse(code)
        except SyntaxError as exc:
            return f"Python syntax error: {exc}"
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for n in node.names:
                    root = n.name.split(".")[0]
                    if root in BLOCKED_IMPORTS:
                        return f"Import '{root}' is not allowed in a skill."
            if isinstance(node, ast.ImportFrom) and node.module:
                root = node.module.split(".")[0]
                if root in BLOCKED_IMPORTS:
                    return f"Import '{root}' is not allowed in a skill."
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in BLOCKED_CALLS:
                return f"Call '{node.func.id}' is not allowed in a skill."
            if isinstance(node, ast.Attribute) and node.attr in {"system", "popen", "remove", "rmdir", "unlink"}:
                return f"Call '{node.attr}' is not allowed in a skill."
    if lang == "js":
        if re.search(r"\b(require|process|child_process|fs|net|http|eval)\b", code):
            return "That JavaScript uses a blocked API (fs/net/process/eval)."
    return None


def _write_plugin(task: str) -> dict[str, Any]:
    if write_override is not None:
        return write_override(task)
    import llm
    prompt = (
        "Write a tiny Ped Bot skill as a single Python 3 function `run(text: str) -> str` "
        "that does this task using only the Python standard library. No network, no files outside "
        "the working directory, no os.system, no secrets. Reply JSON only: "
        '{"name":"slug","title":"Short name","code":"def run(text):\\n    return text","test":"hello"}\n'
        f"TASK: {task}"
    )
    try:
        data = llm.json_from(llm.text(prompt))
    except Exception as exc:
        return {"ok": False, "error": "Needs your free Gemini key to write a skill.", "detail": str(exc)[:160]}
    if not isinstance(data, dict) or not data.get("code"):
        return {"ok": False, "error": "The model did not return skill code."}
    return {
        "ok": True,
        "name": re.sub(r"[^a-z0-9_-]+", "-", str(data.get("name") or "skill").casefold())[:40] or "skill",
        "title": str(data.get("title") or data.get("name") or "Skill")[:80],
        "code": str(data.get("code")),
        "test": str(data.get("test") or "ping"),
        "lang": "python",
    }


def _run_sandbox(code: str, test: str) -> dict[str, Any]:
    folder = _sandbox() / uuid.uuid4().hex[:8]
    folder.mkdir(parents=True, exist_ok=True)
    plugin = folder / "skill.py"
    plugin.write_text(code, encoding="utf-8")
    runner = folder / "runner.py"
    runner.write_text(
        "import json, sys\n"
        "ns = {}\n"
        "exec(open('skill.py', encoding='utf-8').read(), ns, ns)\n"
        "text = sys.argv[1] if len(sys.argv) > 1 else ''\n"
        "print(json.dumps({'ok': True, 'result': str(ns['run'](text))[:2000]}))\n",
        encoding="utf-8",
    )
    env = {k: v for k, v in os.environ.items() if k not in {
        "GEMINI_API_KEY", "GEMINI_API_KEYS", "SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_ANON_KEY",
        "OPENROUTER_API_KEY", "GROQ_API_KEY", "ELEVENLABS_API_KEY",
    }}
    try:
        proc = subprocess.run(
            [sys.executable, str(runner), test],
            cwd=str(folder),
            capture_output=True,
            text=True,
            timeout=8,
            env=env,
            check=False,
        )
        out = (proc.stdout or "").strip()
        try:
            data = json.loads(out.splitlines()[-1]) if out else {}
        except Exception:
            data = {}
        if proc.returncode != 0 or not data.get("ok"):
            return {"ok": False, "error": (proc.stderr or out or "Skill test failed.")[:400], "code": code}
        return {"ok": True, "result": data.get("result"), "code": code}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "Skill test timed out (8s).", "code": code}
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def draft(task: str) -> dict[str, Any]:
    task = " ".join((task or "").split())[:400]
    if not task:
        return {"ok": False, "error": "Describe the skill you want."}
    plugin = _write_plugin(task)
    if not plugin.get("ok"):
        return plugin
    reason = _is_safe_code(str(plugin["code"]), plugin.get("lang") or "python")
    if reason:
        return {"ok": False, "error": reason, "code": plugin["code"]}
    test = _run_sandbox(plugin["code"], plugin.get("test") or "ping")
    draft_id = uuid.uuid4().hex[:8]
    row = {
        "id": draft_id,
        "name": plugin["name"],
        "title": plugin["title"],
        "code": plugin["code"],
        "lang": plugin.get("lang") or "python",
        "task": task,
        "test_ok": bool(test.get("ok")),
        "test_result": test.get("result") or test.get("error") or "",
        "live": False,
        "enabled": False,
        "at": time.time(),
    }
    path = _root() / f"draft-{draft_id}.json"
    path.write_text(json.dumps(row, indent=1), encoding="utf-8")
    return {"ok": True, "draft": row, "message": "Nothing is live until you tap Approve."}


def _draft(did: str) -> dict[str, Any] | None:
    path = _root() / f"draft-{did}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def approve(did: str) -> dict[str, Any]:
    row = _draft(did)
    if not row:
        return {"ok": False, "error": "That draft is gone."}
    if not row.get("test_ok"):
        return {"ok": False, "error": "The sandbox test failed, so this skill cannot go live."}
    live = _load_live()
    _undo().write_text(json.dumps(live, indent=1), encoding="utf-8")
    row = dict(row)
    row.update(live=True, enabled=True, approved_at=time.time())
    live = [s for s in live if s.get("id") != row["id"] and s.get("name") != row["name"]]
    live.append(row)
    _save_live(live)
    return {"ok": True, "skill": {k: row[k] for k in ("id", "name", "title", "enabled", "live")}, "message": "Skill is live."}


def listing() -> dict[str, Any]:
    live = _load_live()
    drafts = []
    for p in _root().glob("draft-*.json"):
        try:
            drafts.append(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            pass
    slim = lambda rows: [{k: r.get(k) for k in ("id", "name", "title", "enabled", "live", "test_ok", "test_result", "task", "code")} for r in rows]
    return {"ok": True, "live": slim(live), "drafts": slim(drafts)}


def disable(sid: str, enabled: bool = False) -> dict[str, Any]:
    live = _load_live()
    found = False
    for row in live:
        if row.get("id") == sid or row.get("name") == sid:
            row["enabled"] = bool(enabled)
            found = True
    if not found:
        return {"ok": False, "error": "No such skill."}
    _save_live(live)
    return {"ok": True, "live": listing()["live"]}


def undo() -> dict[str, Any]:
    try:
        prev = json.loads(_undo().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"ok": False, "error": "Nothing to undo."}
    current = _load_live()
    _undo().write_text(json.dumps(current, indent=1), encoding="utf-8")
    _save_live(prev if isinstance(prev, list) else [])
    return {"ok": True, "message": "Reverted the last Approve.", "live": listing()["live"]}


def handle(action: str, data: dict[str, Any]) -> dict[str, Any]:
    if action in ("", "list"):
        return listing()
    if action == "draft":
        return draft(str(data.get("task") or data.get("text") or ""))
    if action == "approve":
        return approve(str(data.get("id") or data.get("draft") or ""))
    if action == "disable":
        return disable(str(data.get("id") or ""), False)
    if action == "enable":
        return disable(str(data.get("id") or ""), True)
    if action == "undo":
        return undo()
    return {"ok": False, "error": "Unknown skill action."}
