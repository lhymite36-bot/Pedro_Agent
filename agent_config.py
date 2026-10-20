"""Paths and settings for a checkout that can run on any computer.

Secrets stay in the environment. Drive letters and account names are not
stored in this file. `.env` is loaded only when the program starts.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent

_LABEL_ENV = "EXTERNAL_DRIVE_LABEL"
_PATH_ENV = "EXTERNAL_DRIVE_PATH"
_STORAGE_ENV = "STORAGE_DIR"


def load_env_file(path: Path) -> None:
    """Load KEY=VALUE lines. Variables already set in the environment win."""
    if not path.is_file():
        return
    try:
        from dotenv import load_dotenv
    except ImportError:
        _load_env_lines(path)
        return
    load_dotenv(path, override=False)


def _load_env_lines(path: Path) -> None:
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def storage_dir() -> Path:
    """Folder for indexes, memory, and downloads. Unset keeps `workspace/`."""
    raw = os.environ.get(_STORAGE_ENV, "").strip().strip('"')
    if not raw:
        return APP_DIR / "workspace"
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = APP_DIR / path
    return path


def volume_label() -> str:
    """Volume name to search for. Empty until EXTERNAL_DRIVE_LABEL is set."""
    return os.environ.get(_LABEL_ENV, "").strip().strip('"')


def configured_drive_path() -> Path | None:
    """A drive folder chosen in EXTERNAL_DRIVE_PATH, or None."""
    raw = os.environ.get(_PATH_ENV, "").strip().strip('"')
    if not raw:
        return None
    return Path(raw).expanduser()


def drive_names() -> list[str]:
    """Path prefixes that mean the external drive. Longer names are safer."""
    names = ["external", "drive"]
    label = volume_label()
    if not label:
        return names
    names.append(label)
    compact = re.sub(r"[\s_-]+", "", label)
    if compact and compact.casefold() not in {item.casefold() for item in names}:
        names.append(compact)
    return names


def split_drive_prefix(text: str) -> tuple[str, str] | None:
    """Return (name, relative) when text points at the external drive."""
    raw = (text or "").strip().strip('"').strip("'")
    if not raw:
        return None
    for name in sorted(drive_names(), key=len, reverse=True):
        if raw.casefold() == name.casefold():
            return name, ""
        match = re.match(rf"(?i)^{re.escape(name)}[:\\/]+(.*)$", raw)
        if match:
            return name, match.group(1).lstrip("\\/")
    return None


def match_volume(volumes: list[tuple[str, str]]) -> Path | None:
    """The mounted folder whose label matches EXTERNAL_DRIVE_LABEL."""
    label = volume_label()
    if not label:
        return None
    for root, found in volumes:
        if found.strip().casefold() == label.casefold():
            return Path(root)
    return None


def default_output_dir() -> Path:
    """Local folder for agent-made files when the user names no place.
    PEDRO_OUTPUT_DIR overrides; otherwise %USERPROFILE%\\Documents\\PedroAgent. Never an external drive."""
    raw = os.environ.get("PEDRO_OUTPUT_DIR", "").strip().strip('"')
    path = Path(raw).expanduser() if raw else Path.home() / "Documents" / "PedroAgent"
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return path


def drive_missing_message() -> str:
    label = volume_label() or "external"
    return (f'The drive labeled "{label}" is not connected, so it was skipped. '
            f"Files can go in {default_output_dir()} or any folder you name instead.")


def allowed_path_message() -> str:
    return ("That folder isn't allowed by rules.yaml (paths.allowed / paths.blocked). "
            f"Your user folder works, for example {default_output_dir()} or the Desktop.")


def missing_settings() -> list[str]:
    """Names that must be set before an online chat. Local mode does not need a key."""
    private = os.environ.get("PRIVACY_MODE", "").strip() == "1"
    local = os.environ.get("LOCAL_LLM", "").strip() == "1"
    if private or local:
        return []
    if os.environ.get("GEMINI_API_KEY", "").strip():
        return []
    return ["GEMINI_API_KEY"]


def prepare_checkout(root: Path | None = None) -> dict[str, list[str]]:
    """Create the folders a fresh clone needs. Existing files are left in place."""
    base = root or APP_DIR
    folders: list[str] = []
    for name in ("logs", "data", "temp"):
        folder = base / name
        folder.mkdir(parents=True, exist_ok=True)
        marker = folder / ".gitkeep"
        if not marker.exists():
            marker.write_text("", encoding="utf-8")
        folders.append(str(folder))
    store = storage_dir() if root is None else base / "storage"
    store.mkdir(parents=True, exist_ok=True)
    folders.append(str(store))
    example = APP_DIR / "mcp_servers.example.json"
    mcp_target = base / "workspace" / "mcp_servers.json"
    if example.is_file() and not mcp_target.is_file():
        mcp_target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(example, mcp_target)
    return {"folders": folders}


def ffmpeg_status() -> str:
    configured = os.environ.get("FFMPEG_EXECUTABLE", "").strip().strip('"')
    if configured and Path(configured).is_file():
        return configured
    found = shutil.which("ffmpeg")
    if found:
        return found
    return ""


