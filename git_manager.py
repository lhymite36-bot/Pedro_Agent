"""Git backups for folders this agent is allowed to touch.

Commands are argument lists. The shell is never used. Tests set
git_runner_override and never start git. Identity, remotes, and
force-push are left to the user.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Any

ACTIONS = {
    "init": "init",
    "initialize": "init",
    "initialise": "init",
    "status": "status",
    "commit": "commit",
    "push": "push",
}
SECRET_NAMES = {".env", "id_rsa", "id_dsa", "known_hosts"}
SECRET_EXTS = {".pem", ".key", ".env"}
KEY_TEXT = re.compile(
    r"(api[_-]?key|access[_-]?token|password|private key|"
    r"AIza[0-9A-Za-z_\-]{20,}|ghp_[A-Za-z0-9]{10,}|github_pat_[A-Za-z0-9_]{10,})",
    re.IGNORECASE,
)
TIMEOUT_SECONDS = 120


def _agent() -> Any:
    return __import__("gta5_agent")


def _resolve_repo(agent: Any, path: str) -> Path:
    text = (path or "").strip().strip('"')
    if not text:
        text = str(agent.APP_DIR)
    drive = agent._resolve_drive_text(text)
    if drive is not None:
        target = drive
    else:
        target = Path(text).expanduser()
        if ".." in target.parts:
            raise ValueError("The path cannot contain '..'.")
    resolved = target.resolve()
    if not agent._path_is_allowed(resolved):
        raise ValueError(
            "Git can only manage a folder in your user profile, the app workspace, or the external drive."
        )
    return resolved


def _secret(path_text: str) -> bool:
    name = Path(path_text.replace("\\", "/")).name.casefold()
    if name in SECRET_NAMES or name.endswith(".env"):
        return True
    return Path(name).suffix.casefold() in SECRET_EXTS


def _porcelain(text: str) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for raw in (text or "").splitlines():
        if len(raw) < 4:
            continue
        path_text = raw[3:].strip()
        if " -> " in path_text:
            path_text = path_text.split(" -> ", 1)[1].strip()
        if len(path_text) >= 2 and path_text[0] == '"' and path_text[-1] == '"':
            path_text = path_text[1:-1]
        if path_text:
            rows.append((raw[0], path_text))
    return rows


def _run(command: list[str], cwd: Path) -> dict[str, Any]:
    agent = _agent()
    if agent.git_runner_override is not None:
        result = agent.git_runner_override(command, cwd)
        if not isinstance(result, dict):
            raise RuntimeError("The git runner returned nothing.")
        return result
    flags: dict[str, Any] = {}
    if os.name == "nt":
        flags["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    process = subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=TIMEOUT_SECONDS,
        shell=False,
        check=False,
        **flags,
    )
    return {
        "returncode": process.returncode,
        "stdout": process.stdout or "",
        "stderr": process.stderr or "",
    }


def _failure(agent: Any, completed: dict[str, Any], fallback: str) -> dict[str, Any] | None:
    if int(completed.get("returncode", 1)) == 0:
        return None
    detail = agent._scrub(str(completed.get("stderr") or completed.get("stdout") or fallback))
    folded = detail.casefold()
    if "user.email" in folded or "user.name" in folded or "tell me who you are" in folded:
        return agent._err(
            "Git has no name or email configured. Set those yourself. "
            "This agent will not change git config."
        )
    return agent._err(detail[-500:] or fallback)


def _message_problem(agent: Any, message: str) -> str | None:
    text = " ".join((message or "").split())
    if not text:
        return "A commit message is required."
    if agent.PIRACY_TERMS.search(text) or KEY_TEXT.search(text):
        return "The commit message cannot contain a crack, a key, or a password."
    live = os.environ.get("GEMINI_API_KEY", "")
    if live and live in message:
        return "The commit message cannot contain a crack, a key, or a password."
    return None


def git_manager(action: str, path: str = "", message: str = "") -> dict[str, Any]:
    """Init, status, commit, or push. Push is exactly `git push`."""
    agent = _agent()
    try:
        folded = " ".join((action or "").replace("_", " ").split()).casefold()
        if "force" in folded or folded in {"-f", "push -f", "push --force"}:
            return agent._err("Force push is not allowed.")
        kind = ACTIONS.get(folded.replace(" ", "_"))
        if kind is None:
            return agent._err("action must be init, status, commit, or push.")
        repo = _resolve_repo(agent, path)
        if not repo.is_dir():
            return agent._err("That folder was not found.")
        if kind == "init":
            completed = _run(["git", "init"], repo)
            failed = _failure(agent, completed, "git init failed.")
            if failed is not None:
                return failed
            return agent._ok("Initialized a git repository.", path=str(repo), action="init")
        if kind == "status":
            completed = _run(["git", "status", "--porcelain"], repo)
            failed = _failure(agent, completed, "git status failed.")
            if failed is not None:
                return failed
            report = agent._scrub(str(completed.get("stdout") or "")).strip()
            return agent._ok(
                "Read the git status.",
                path=str(repo),
                action="status",
                status=report,
            )
        if kind == "push":
            completed = _run(["git", "push"], repo)
            failed = _failure(agent, completed, "git push failed.")
            if failed is not None:
                return failed
            return agent._ok("Pushed the current branch.", path=str(repo), action="push")
        problem = _message_problem(agent, message)
        if problem is not None:
            return agent._err(problem)
        status = _run(["git", "status", "--porcelain"], repo)
        failed = _failure(agent, status, "git status failed.")
        if failed is not None:
            return failed
        rows = _porcelain(str(status.get("stdout") or ""))
        secrets = [name for mark, name in rows if _secret(name) and mark not in {" ", "?"}]
        for secret in secrets:
            reset = _run(["git", "reset", "HEAD", "--", secret], repo)
            failed = _failure(agent, reset, "git could not unstage a secret file.")
            if failed is not None:
                return failed
        keep = [name for _mark, name in rows if not _secret(name)]
        if not keep:
            if secrets or any(_secret(name) for _mark, name in rows):
                return agent._err(
                    "Secret files were left unstaged. Nothing else is ready to commit."
                )
            return agent._err("Nothing is ready to commit.")
        added = _run(["git", "add", "--", *keep], repo)
        failed = _failure(agent, added, "git add failed.")
        if failed is not None:
            return failed
        commit = _run(["git", "commit", "-m", " ".join(message.split())], repo)
        failed = _failure(agent, commit, "git commit failed.")
        if failed is not None:
            return failed
        return agent._ok(
            "Created a commit.",
            path=str(repo),
            action="commit",
            files=keep,
        )
    except AssertionError:
        raise
    except Exception as exc:
        return agent._err(f"git_manager failed: {exc}")
