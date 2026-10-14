"""Code engineer loop: ask Gemini for file edits, write them, run the tests,
feed failures back, and repeat up to code.max_iterations. A passing round is
committed with git (secrets stay unstaged by git_manager). Writes go through
rules.file_write_reason and stay inside the project folder.
"""

from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path
from typing import Any, Callable

import llm
import rules

DEFAULTS = {"max_iterations": 5, "test_timeout_seconds": 300, "max_file_chars": 200_000,
            "default_test_command": "python -m pytest -q", "git_commit": True}
SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache", "dist", "build"}

# Tests replace: test_runner(command_list, cwd, timeout) -> (returncode, output)
test_runner: Callable[[list[str], Path, int], tuple[int, str]] | None = None


def settings() -> dict[str, Any]:
    return rules.section("code", DEFAULTS)


def _ok(message: str, **extra: Any) -> dict[str, Any]:
    return {"ok": True, "message": message, **extra}


def _err(message: str, **extra: Any) -> dict[str, Any]:
    return {"ok": False, "error": message, **extra}


def _listing(root: Path, limit: int = 200) -> list[str]:
    out = []
    for path in sorted(root.rglob("*")):
        if any(part in SKIP_DIRS for part in path.relative_to(root).parts):
            continue
        if path.is_file():
            out.append(path.relative_to(root).as_posix())
            if len(out) >= limit:
                break
    return out


def _snapshot(root: Path, names: list[str], budget: int = 60_000) -> str:
    parts, used = [], 0
    for name in names:
        path = root / name
        if path.suffix.casefold() not in {".py", ".js", ".ts", ".html", ".css", ".json", ".md", ".txt", ".toml", ".yaml", ".yml", ".cfg", ".ini"}:
            continue
        try:
            body = path.read_text(encoding="utf-8")
        except Exception:
            continue
        if used + len(body) > budget:
            break
        used += len(body)
        parts.append(f"--- {name}\n{body}")
    return "\n".join(parts)


def _target(root: Path, name: str) -> Path:
    rel = Path(str(name).replace("\\", "/"))
    if rel.is_absolute() or ".." in rel.parts or not rel.parts:
        raise ValueError(f"{name}: files must stay inside the project.")
    target = (root / rel).resolve()
    if root.resolve() not in target.parents:
        raise ValueError(f"{name}: files must stay inside the project.")
    if rel.parts[0] in SKIP_DIRS:
        raise ValueError(f"{name}: not editable.")
    return target


def _run_tests(command: list[str], cwd: Path, timeout: int) -> tuple[int, str]:
    if test_runner is not None:
        return test_runner(command, cwd, timeout)
    flags: dict[str, Any] = {}
    if os.name == "nt":
        flags["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        done = subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=timeout,
                              shell=False, check=False, **flags)
    except FileNotFoundError as exc:
        return 127, f"Test command not found: {exc}"
    except subprocess.TimeoutExpired:
        return 124, f"Tests timed out after {timeout}s."
    return done.returncode, (done.stdout or "") + (done.stderr or "")


def _commit(root: Path, message: str) -> str:
    if not settings().get("git_commit", True) or not (root / ".git").is_dir():
        return "not committed (no git repo or code.git_commit is off)"
    import git_manager

    result = git_manager.git_manager("commit", str(root), message[:200])
    return "committed" if result.get("ok") else f"commit skipped: {result.get('error')}"


def code_engineer(goal: str, project_dir: str, test_command: str = "", max_iterations: int = 0) -> dict[str, Any]:
    goal = " ".join((goal or "").split())
    if not goal:
        return _err("Say what to build or fix.")
    root = Path(os.path.expanduser(project_dir or "")).resolve()
    root.mkdir(parents=True, exist_ok=True) if not root.exists() and root.parent.is_dir() else None
    if not root.is_dir():
        return _err("The project folder was not found.")
    cfg = settings()
    cap = max(1, min(int(max_iterations or cfg["max_iterations"] or 5), 20))
    command = shlex.split(test_command or cfg["default_test_command"], posix=(os.name != "nt"))
    if not command:
        return _err("A test command is required.")
    feedback, log = "", []
    for round_no in range(1, cap + 1):
        names = _listing(root)
        prompt = (
            "You are a careful software engineer working in a local project. Make the "
            "smallest edits that achieve the goal and make the tests pass. Add or update "
            "tests when needed. Reply with JSON only: {\"files\": {\"relative/path\": \"full new "
            "content\"}, \"delete\": [], \"message\": \"short commit message\"}.\n\n"
            f"GOAL: {goal}\nTEST COMMAND: {' '.join(command)}\nFILES: {names}\n\n"
            f"CURRENT CONTENT:\n{_snapshot(root, names)}\n\n"
            + (f"LAST TEST OUTPUT (round {round_no - 1}):\n{feedback[-6000:]}" if feedback else "")
        )
        try:
            plan = llm.json_from(llm.text(prompt))
        except Exception as exc:
            log.append({"round": round_no, "error": f"no usable edit: {exc}"})
            feedback = f"Your last reply was not valid JSON ({exc})."
            continue
        files = plan.get("files") if isinstance(plan, dict) else None
        written, refused = [], []
        for name, content in (files or {}).items():
            try:
                target = _target(root, name)
                text = str(content)
                if len(text) > int(cfg["max_file_chars"]):
                    raise ValueError(f"{name}: too large.")
                reason = rules.file_write_reason(target)
                if reason:
                    raise ValueError(f"{name}: {reason}")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(text, encoding="utf-8")
                written.append(name)
            except ValueError as exc:
                refused.append(str(exc))
        code, output = _run_tests(command, root, int(cfg["test_timeout_seconds"]))
        entry = {"round": round_no, "written": written, "refused": refused, "tests_passed": code == 0,
                 "output_tail": output[-1500:]}
        log.append(entry)
        if code == 0:
            message = str((plan or {}).get("message") or goal)[:120]
            entry["git"] = _commit(root, message)
            return _ok(f"Tests pass after {round_no} round(s). {entry['git']}.", rounds=round_no, log=log,
                       project=str(root))
        feedback = output + ("\nREFUSED WRITES: " + "; ".join(refused) if refused else "")
    return _err(f"Tests still fail after {cap} rounds. Last output is in the log.", rounds=cap, log=log,
                project=str(root))


DECLARATIONS = [{
    "name": "code_engineer",
    "description": ("Build or fix code in a local project folder: writes files, runs the tests, reads failures, "
                    "fixes, and loops until tests pass (capped), then makes a git commit."),
    "parameters": {"type": "object", "properties": {
        "goal": {"type": "string"},
        "project_dir": {"type": "string", "description": "Project folder (created if its parent exists)."},
        "test_command": {"type": "string", "description": "e.g. 'python -m pytest -q' or 'npm test'."},
        "max_iterations": {"type": "integer"}},
        "required": ["goal", "project_dir"]},
}]
TOOLS = {"code_engineer": code_engineer}
