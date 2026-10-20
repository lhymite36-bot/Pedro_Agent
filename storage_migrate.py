"""Bring an older install's chats, bots, groups and routines into this one.

Copies, never moves or deletes: the old folder stays as it was. Runs once
(storage/.migrated_from marks it). The current files that would be replaced are
first copied to storage/pre_migration_backup/.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import time
from pathlib import Path
from typing import Any

MARK = ".migrated_from"
_SKIP = {"pre_migration_backup", "__pycache__", MARK, "remote_token.txt", "telegram_bridge.lock"}
_MAX_FILE = 500 * 1024 * 1024


def _messages(folder: Path) -> int:
    db = folder / "chat_history.db"
    if not db.is_file():
        return 0
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            return int(con.execute("SELECT COUNT(*) FROM messages").fetchone()[0])
        finally:
            con.close()
    except Exception:
        return 0


def candidates() -> list[Path]:
    home = Path(os.path.expanduser("~"))
    local = Path(os.environ.get("LOCALAPPDATA") or (home / "AppData" / "Local"))
    found: list[Path] = []
    extra = os.environ.get("PEDBOT_IMPORT_FROM", "").strip().strip('"')
    if extra:
        found.append(Path(extra))
    found += [
        home / "Projects" / "gta5-mod-agent" / "workspace",
        local / "PedroAgent" / "workspace",
        local / "PedroAgent" / "storage",
    ]
    return found


def migrate(target: Path, sources: list[Path] | None = None) -> dict[str, Any]:
    target = Path(target)
    if (target / MARK).is_file():
        return {"ok": True, "migrated": False, "message": "Already moved over earlier."}
    here = _messages(target)
    best, best_count = None, 0
    for folder in sources if sources is not None else candidates():
        try:
            if folder.resolve() == target.resolve() or not folder.is_dir():
                continue
        except OSError:
            continue
        count = _messages(folder)
        if count > best_count:
            best, best_count = folder, count
    if best is None or best_count <= here:
        return {"ok": True, "migrated": False, "message": "No older chat history with more messages was found."}
    target.mkdir(parents=True, exist_ok=True)
    backup = target / "pre_migration_backup" / time.strftime("%Y%m%d-%H%M%S")
    copied: list[str] = []
    for item in best.iterdir():
        if item.name in _SKIP:
            continue
        dest = target / item.name
        try:
            if dest.exists():
                backup.mkdir(parents=True, exist_ok=True)
                if dest.is_dir():
                    shutil.copytree(dest, backup / item.name, dirs_exist_ok=True)
                else:
                    shutil.copy2(dest, backup / item.name)
            if item.is_dir():
                shutil.copytree(item, dest, dirs_exist_ok=True)
            elif item.stat().st_size <= _MAX_FILE:
                if item.name == "chat_history.db":
                    _copy_sqlite(item, dest)
                else:
                    shutil.copy2(item, dest)
            else:
                continue
            copied.append(item.name)
        except Exception:
            continue
    (target / MARK).write_text(f"{best}\n{best_count} messages\n{time.strftime('%Y-%m-%d %H:%M')}\n", encoding="utf-8")
    return {"ok": True, "migrated": True, "from": str(best), "messages": best_count, "copied": copied,
            "message": f"Brought over {best_count} chat messages and {len(copied)} items from {best}. The old folder was left as it was."}


def _copy_sqlite(source: Path, dest: Path) -> None:
    """A consistent copy even if the old app is still open."""
    src = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    try:
        if dest.exists():
            dest.unlink()
        out = sqlite3.connect(str(dest))
        try:
            src.backup(out)
        finally:
            out.close()
    finally:
        src.close()


def merge_env(target_env: Path, source_env: Path) -> list[str]:
    """Add keys the old install had and this one lacks. Values are copied, never printed."""
    if not source_env.is_file():
        return []
    have: dict[str, str] = {}
    lines: list[str] = []
    if target_env.is_file():
        lines = target_env.read_text(encoding="utf-8", errors="replace").splitlines()
        for line in lines:
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                have[key.strip()] = value.strip()
    added: list[str] = []
    for line in source_env.read_text(encoding="utf-8", errors="replace").splitlines():
        if "=" not in line or line.lstrip().startswith("#"):
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if key and value and not have.get(key):
            lines = [ln for ln in lines if not ln.strip().startswith(key + "=")]
            lines.append(f"{key}={value}")
            added.append(key)
    if added:
        target_env.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return added


def run_at_start(app_dir: Path, storage: Path) -> dict[str, Any]:
    result = migrate(storage)
    if result.get("migrated"):
        source = Path(result["from"])
        result["env_keys"] = merge_env(app_dir / ".env", source.parent / ".env")
    return result
