"""General file tools governed by rules.yaml: write_text_file, delete_path.

delete_path is in the "delete" confirm category, so by default the agent
asks before it runs. Files go to the Recycle Bin when send2trash is
installed; otherwise they are removed permanently.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import rules


def _agent() -> Any:
    import agent_core

    return agent_core


def _target(path_text: str) -> Path:
    agent = _agent()
    text = (path_text or "").strip().strip('"')
    if not text:
        raise ValueError("A path is required.")
    drive = agent._resolve_drive_text(text)
    target = drive if drive is not None else Path(text).expanduser()
    target = target.resolve()
    if not agent._path_is_allowed(target):
        raise ValueError(rules.allowed_path_message())
    return target


def _is_agent_code(target: Path, agent_dir: Path) -> bool:
    """The agent folder, a folder above it, or its code (workspace/ files are fine)."""
    if target == agent_dir or target in agent_dir.parents:
        return True
    if agent_dir not in target.parents:
        return False
    import agent_config

    data_roots = [agent_dir / "workspace", agent_config.storage_dir().resolve()]
    return not any(root == target or root in target.parents for root in data_roots)


def _protected_delete(target: Path) -> str | None:
    """Accident protection from the `protect:` section of rules.yaml."""
    agent_dir = Path(__file__).resolve().parent
    if rules.protect("never_delete_drive_root") and target.parent == target:
        return f"Refusing to delete a drive root: {target} (protect.never_delete_drive_root)"
    if rules.protect("never_delete_home_folder") and target == Path.home().resolve():
        return f"Refusing to delete your home folder: {target} (protect.never_delete_home_folder)"
    if rules.protect("never_delete_agent_folder") and _is_agent_code(target, agent_dir):
        return f"Refusing to delete the agent's own files: {target} (protect.never_delete_agent_folder)"
    return None


def write_text_file(path: str, content: str, overwrite: bool = False) -> dict[str, Any]:
    agent = _agent()
    try:
        target = _target(path)
        reason = rules.file_write_reason(target)
        if reason:
            return agent._err(reason)
        if target.exists() and not overwrite:
            return agent._err(f"Already exists: {target}. Pass overwrite true to replace it.")
        import undo_store

        undo_store.remember(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(str(content or ""), encoding="utf-8")
        undo_store.seal(target)
        return agent._ok(f"Saved {target}.", path=str(target), bytes=target.stat().st_size)
    except Exception as exc:
        return agent._err(f"write_text_file failed: {exc}")


def delete_path(path: str, recursive: bool = False) -> dict[str, Any]:
    agent = _agent()
    try:
        target = _target(path)
        if not target.exists():
            return agent._err(f"Nothing at {target}.")
        reason = _protected_delete(target)
        if reason:
            return agent._err(reason)
        try:
            from send2trash import send2trash  # type: ignore

            send2trash(str(target))
            return agent._ok(f"Moved {target} to the Recycle Bin.", path=str(target), recycled=True)
        except ImportError:
            pass
        if target.is_dir():
            if not recursive:
                return agent._err("That is a folder. Pass recursive true to delete it and its contents.")
            shutil.rmtree(target)
        else:
            target.unlink()
        return agent._ok(f"Deleted {target}.", path=str(target), recycled=False)
    except Exception as exc:
        return agent._err(f"delete_path failed: {exc}")
