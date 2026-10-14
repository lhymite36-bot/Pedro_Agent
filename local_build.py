"""Write an original program on this PC and optionally start it.

The project folder must stay in the user profile, the app workspace, or the
external drive. Tests set program_runner_override so nothing is launched.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import rules

ALLOWED_SUFFIXES = {".py", ".html", ".css", ".js", ".json", ".txt", ".md", ".csv"}
MAX_FILES = 40
MAX_FILE_CHARS = 100_000
MAX_TOTAL_CHARS = 500_000

_INSTALLER = re.compile(
    r"afterfx|setup\.exe|adobe\s*(setup|installer)|crack|keygen|repack",
    re.IGNORECASE,
)


def _agent() -> Any:
    import gta5_agent

    return gta5_agent


def _safe_name(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "-", (name or "").strip()).strip("-_")
    return cleaned[:40]


def _project_dir(output_path: str, name: str) -> Path:
    agent = _agent()
    folder = _safe_name(name)
    if not folder:
        raise ValueError("A project name is required.")
    text = (output_path or "").strip().strip('"')
    if not text:
        target = agent.WORKSPACE / "builds" / folder
    else:
        parsed = None
        import agent_config

        parsed = agent_config.split_drive_prefix(text)
        if parsed is not None:
            _name, relative = parsed
            root = agent._external_drive_root()
            if root is None:
                raise ValueError(agent_config.drive_missing_message())
            if relative and ".." in Path(relative).parts and rules.limit("reject_dotdot_paths"):
                raise ValueError("The path cannot contain '..'.")
            target = root / relative if relative else root / "Apps" / folder
        else:
            target = Path(text).expanduser()
            if ".." in target.parts and rules.limit("reject_dotdot_paths"):
                raise ValueError("The path cannot contain '..'.")
        if target.suffix:
            raise ValueError("output_path must be a folder.")
    resolved = target.resolve()
    if not agent._path_is_allowed(resolved):
        raise ValueError(
            "Save the program in your user folder, the app workspace, or the external drive."
        )
    cursor = resolved
    while rules.limit("keep_builds_out_of_game_folder"):
        if (cursor / "GTA5.exe").is_file():
            raise ValueError("Do not build a program inside the game folder.")
        if cursor == cursor.parent:
            break
        cursor = cursor.parent
    return resolved


def _relative_file(value: str) -> Path:
    text = (value or "").strip().replace("\\", "/").lstrip("/")
    if not text or re.match(r"^[A-Za-z]:", text):
        raise ValueError(f"The file path {value!r} must stay inside the project.")
    path = Path(text)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"The file path {value!r} must stay inside the project.")
    if rules.limit("build_allowed_extensions_only") and path.suffix.casefold() not in ALLOWED_SUFFIXES:
        allowed = ", ".join(sorted(ALLOWED_SUFFIXES))
        raise ValueError(f"Files must use one of these extensions: {allowed}.")
    return path


def _checked_files(raw: Any) -> list[tuple[Path, str]]:
    agent = _agent()
    if isinstance(raw, str):
        try:
            raw = json.loads(raw or "")
        except json.JSONDecodeError as exc:
            raise ValueError(
                'files must be a JSON list, for example '
                '[{"path":"main.py","content":"print(1)"}]. '
                f"Could not parse it: {exc}"
            ) from exc
    if not isinstance(raw, list) or not raw:
        raise ValueError(
            'files must be a JSON list of {"path":"main.py","content":"..."} objects.'
        )
    caps = rules.limit("build_size_caps")
    if caps and len(raw) > MAX_FILES:
        raise ValueError(f"A project can contain at most {MAX_FILES} files.")
    key = os.environ.get("GEMINI_API_KEY", "")
    prepared: list[tuple[Path, str]] = []
    seen: set[str] = set()
    total = 0
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("Each file must be an object with path and content.")
        relative = _relative_file(str(item.get("path") or ""))
        content = item.get("content")
        if not isinstance(content, str) or not content.strip():
            raise ValueError(f"{relative.as_posix()} has no content.")
        if caps and len(content) > MAX_FILE_CHARS:
            raise ValueError(f"{relative.as_posix()} is too long.")
        total += len(content)
        if caps and total > MAX_TOTAL_CHARS:
            raise ValueError("The project is too large.")
        if "\x00" in content:
            raise ValueError(f"{relative.as_posix()} contains a null character.")
        if key and key in content and rules.limit("build_refuse_api_key_in_files"):
            raise ValueError("A project file cannot contain an API key.")
        if agent.PIRACY_TERMS.search(content) or _INSTALLER.search(content):
            raise ValueError(
                "That project asks for a crack, repack, or commercial installer. "
                "Build an original program instead."
            )
        marker = relative.as_posix().casefold()
        if marker in seen:
            raise ValueError(f"{relative.as_posix()} is listed more than once.")
        seen.add(marker)
        prepared.append((relative, content))
    return prepared


def _start(project: Path, entry: Path) -> list[str]:
    agent = _agent()
    if entry.suffix.casefold() == ".py":
        command = [sys.executable, str(project / entry)]
    elif entry.suffix.casefold() == ".html":
        command = ["open", str(project / entry)]
    else:
        raise ValueError("entry must be a .py or .html file that was just written.")
    runner = agent.program_runner_override
    if runner is not None:
        runner(command, project)
        return command
    if command[0] == "open":
        if os.name != "nt":
            raise RuntimeError("Opening the page is supported on Windows.")
        os.startfile(command[1])
        return command
    options: dict[str, Any] = {
        "cwd": str(project),
        "shell": False,
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if os.name == "nt":
        options["creationflags"] = (
            subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        )
    subprocess.Popen(command, **options)
    return command


def build_local_program(
    name: str,
    files: Any,
    output_path: str = "",
    entry: str = "",
    run: bool = False,
) -> dict[str, Any]:
    """Write a small original program and, when asked, start its entry file."""
    agent = _agent()
    try:
        project = _project_dir(output_path, name)
        written = _checked_files(files)
        names = {path.as_posix().casefold(): path for path, _content in written}
        chosen = (entry or "").strip()
        if not chosen and agent._as_bool(run):
            python_files = [path for path, _content in written if path.suffix.casefold() == ".py"]
            if len(python_files) == 1:
                chosen = python_files[0].as_posix()
            else:
                raise ValueError("Pass entry as the .py or .html file to start.")
        entry_path: Path | None = None
        if chosen:
            entry_path = _relative_file(chosen)
            if entry_path.as_posix().casefold() not in names:
                raise ValueError("entry must be one of the files in this project.")
            if entry_path.suffix.casefold() not in {".py", ".html"}:
                raise ValueError("entry must be a .py or .html file.")
        project.mkdir(parents=True, exist_ok=True)
        saved: list[str] = []
        for relative, content in written:
            destination = project / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(content, encoding="utf-8")
            saved.append(relative.as_posix())
        command: list[str] = []
        if entry_path is not None and agent._as_bool(run):
            command = _start(project, entry_path)
        message = f"Saved {len(saved)} file(s) in {project}."
        if command:
            message += " Started the program."
        return agent._ok(
            message,
            path=str(project),
            files=saved,
            entry=entry_path.as_posix() if entry_path is not None else "",
            started=bool(command),
            command=command,
        )
    except AssertionError:
        raise
    except Exception as exc:
        return agent._err(f"build_local_program failed: {exc}")
