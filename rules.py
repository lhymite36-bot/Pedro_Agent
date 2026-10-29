"""User-editable rules for Pedro_Agent.

The agent used to carry hardcoded limits (writes only in a few folders, no
.exe writes, no Windows/Program Files paths). Those limits now live in
rules.yaml (or rules.json) next to this file, so the owner decides what is
allowed. Edit the file by hand or in the chat app's Settings page.

Lookup order: RULES_FILE env var, then rules.yaml, then rules.json in the
app folder. When no file exists the built-in DEFAULT_RULES apply, which
match the old behaviour plus a confirm step for risky actions.

Path patterns:
  "~"              the user home folder
  "{workspace}"    the agent workspace folder
  "{external}"     the external drive (EXTERNAL_DRIVE_PATH / label)
  "*"              everywhere
  anything else    a folder; it and everything under it match.
  Patterns may use * and ? wildcards (fnmatch, case-insensitive).
"""

from __future__ import annotations

import copy
import fnmatch
import json
import os
import threading
from pathlib import Path
from typing import Any

APP_DIR = Path(__file__).resolve().parent

DEFAULT_RULES: dict[str, Any] = {
    "version": 1,
    # Extra owner lines injected into the system prompt. Add/remove in Settings → Rules.
    "instructions": [],
    "paths": {
        # Where file-writing tools may write.
        "allowed": ["*"],
        # Always refused, even inside an allowed folder. Blocked wins.
        "blocked": [],
    },
    "files": {
        # false keeps the old "never write or replace an .exe" rule.
        "allow_exe_writes": True,
        # File types that may never be written (empty = none).
        "blocked_extensions": [],
    },
    "tools": {
        # Empty list = every tool is allowed. Otherwise only these run.
        "allowed": [],
        # These tools never run.
        "blocked": [],
    },
    "confirm": {
        # Master switch. false = never ask, just do it.
        "enabled": True,
        # Categories that need a "yes" first. Remove any to stop asking.
        "categories": ["delete", "payment", "send_message", "power", "kill_process", "network",
                       "self_upgrade", "remote_control"],
        # Extra tool names that always need a "yes".
        "extra_tools": [],
    },
    "agent": {
        # Gemini models tried in order when one runs out of free quota.
        "models": [
            "gemini-3.6-flash",
            "gemini-3.5-flash-lite",
            "gemini-3.1-flash-lite",
        ],
        "smart_mode": True,
        "top_model_daily_budget": 18,
        "max_tool_rounds": 30,
        "tool_timeout_seconds": 300,
    },
    "voice": {
        # Seconds of silence that end your sentence. Lower = faster turns.
        "pause_threshold": 1.2,
        # Chat app: speak replies aloud by default.
        "auto_speak": False,
    },
    # Hardcoded limits that used to live in the code. Every switch is OFF
    # (permissive) by default. Turn one on to get the old behaviour back.
    # Numbers: 0 = unlimited.
    "limits": {
        "scheduler_allowlist_only": False,       # only built-in jobs; no scheduled scripts/programs
        "scheduler_max_jobs": 0,                 # was 20
        "refuse_secret_text": False,             # refuse to remember/type/schedule text that looks like a password/key
        "build_allowed_extensions_only": False,  # build_local_program: only .py .html .css .js .json .txt .md .csv
        "build_size_caps": False,                # build_local_program: file count / size caps
        "build_refuse_api_key_in_files": False,  # refuse project files containing GEMINI_API_KEY
        "keep_builds_out_of_game_folder": False, # no builds/script repair inside the GTA folder
        "mod_writes_in_game_folder_only": False, # mod copy tools may only write inside the GTA folder
        "archive_size_caps": False,              # 4 GiB download, 20,000 entries, 8 GiB unpacked
        "public_urls_only": False,               # refuse downloads from LAN/localhost addresses
        "reject_dotdot_paths": False,            # refuse paths containing ".."
        "excel_block_risky_formulas": False,     # refuse DDE/CMD/WEBSERVICE-style formulas
        "sql_safe_mode": False,                  # refuse xp_cmdshell, OPENROWSET, ATTACH, etc.
        "sql_local_servers_only": False,         # SQL Server only on localhost
        "require_plan_for_multistep": False,     # force create_task_plan before acting on multi-part requests
        "max_plan_steps": 0,                     # was 8
        "max_action_batch": 0,                   # perform_actions batch size, was 12
        "type_text_max_chars": 0,                # was 500
        "browser_action_caps": False,            # browser_download_tool: 8 actions, 1 download, Enter/Tab/Escape only
        "browser_env_prefix_only": False,        # browser fills may only read BROWSER_* env vars
        "blender_script_checks": False,          # refuse Blender scripts with file paths/exports/shell calls
        "downloads_leave_programs_in_place": False,  # organize_downloads skips .exe/.bat/... files
    },
    # Accident protection. ON by default; switch off only if you are sure.
    "protect": {
        "never_delete_drive_root": True,
        "never_delete_home_folder": True,
        "never_delete_agent_folder": True,
        "archive_path_safety": True,             # stop zip entries escaping their folder (zip-slip) or linking out
        "git_unstage_secrets": True,             # keep .env/.pem/.key out of commits
        "skill_typing_stays_local": True,        # demo skills: typed text not sent to Gemini / SKILL.md
    },
    "speed": {
        # Wait after focusing a window or clicking before checking the screen.
        "settle_seconds": 0.12,
        # Wait between retries when an element was not found.
        "retry_wait_seconds": 0.2,
        # Extra attempts for click_screen_target.
        "retries": 1,
        # Screenshots sent to vision are shrunk and JPEG-compressed.
        "vision_max_width": 1024,
        "vision_jpeg_quality": 60,
        # Fastest free model for finding things on screen.
        "vision_model": "gemini-3.5-flash-lite",
        # Look up controls by name with Windows UI Automation before vision.
        "use_ui_automation": True,
        "ui_automation_timeout_seconds": 1.5,
        # Window lookups are cached this long.
        "window_cache_seconds": 30,
        # Fraction of pixels that must change to count as "the click did something".
        "pixel_diff_threshold": 0.002,
    },
}

# Which tools belong to each confirm category.
CATEGORY_TOOLS: dict[str, set[str]] = {
    "delete": {"delete_path", "delete_task_routine", "delete_app_item"},
    "payment": set(),  # no payment tools ship; listed so custom tools can join
    "send_message": {"gmail_send_message", "send_remote_update", "whatsapp_send_now", "youtube_upload"},
    "power": {"shutdown_computer"},
    "kill_process": {"kill_process"},
    "network": set(),  # decided by action in category_for
    "self_upgrade": set(),  # self_upgrade apply/rollback, decided in category_for
    "remote_control": {"remote_control_action"},  # phone -> PC input from the Live PC page
}
_PAYMENT_WORDS = ("pay ", "payment", "checkout", "buy now", "place order", "purchase")
_NETWORK = {"wifi_connect", "wifi_disconnect", "vpn_connect", "vpn_disconnect", "connect", "disconnect"}

_lock = threading.Lock()
_cache: tuple[Path | None, float, dict[str, Any]] | None = None


def _merge(base: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for key, value in (extra or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def rules_path() -> Path | None:
    env = os.environ.get("RULES_FILE", "").strip().strip('"')
    if env:
        return Path(env).expanduser()
    for name in ("rules.yaml", "rules.yml", "rules.json"):
        candidate = APP_DIR / name
        if candidate.is_file():
            return candidate
    return None


def parse_text(text: str, suffix: str) -> dict[str, Any]:
    if suffix.casefold() == ".json":
        data = json.loads(text or "{}")
    else:
        try:
            import yaml  # type: ignore
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("Install PyYAML for rules.yaml, or use rules.json.") from exc
        data = yaml.safe_load(text or "") or {}
    if not isinstance(data, dict):
        raise ValueError("The rules file must be a mapping at the top level.")
    return data


_thread = threading.local()


def set_thread_override(extra: dict[str, Any] | None) -> None:
    """Per-bot rules: merged over rules.yaml for this thread only."""
    _thread.override = dict(extra) if isinstance(extra, dict) and extra else None


def load(force: bool = False) -> dict[str, Any]:
    """Rules merged over the defaults (plus this thread's bot override)."""
    base = _load_file(force)
    extra = getattr(_thread, "override", None)
    return _merge(base, extra) if extra else base


def _load_file(force: bool = False) -> dict[str, Any]:
    global _cache
    path = rules_path()
    mtime = path.stat().st_mtime if path is not None and path.is_file() else 0.0
    with _lock:
        if not force and _cache is not None and _cache[0] == path and _cache[1] == mtime:
            return _cache[2]
        data: dict[str, Any] = {}
        if path is not None and path.is_file():
            data = parse_text(path.read_text(encoding="utf-8"), path.suffix)
        merged = _merge(DEFAULT_RULES, data)
        _cache = (path, mtime, merged)
        return merged


def save_text(text: str) -> Path:
    """Validate and save rules text from the settings page."""
    path = rules_path() or (APP_DIR / "rules.yaml")
    parse_text(text, path.suffix)  # raises on bad input
    path.write_text(text, encoding="utf-8")
    load(force=True)
    return path


def _raw_file() -> dict[str, Any]:
    path = rules_path()
    if path is None or not path.is_file():
        return {}
    return parse_text(path.read_text(encoding="utf-8"), path.suffix)


def dump_text(data: dict[str, Any], suffix: str) -> str:
    if suffix.casefold() == ".json":
        return json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    try:
        import yaml  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Install PyYAML for rules.yaml, or use rules.json.") from exc

    class Dumper(yaml.SafeDumper):
        pass

    def _str(dumper: Any, value: str) -> Any:
        style = "|" if "\n" in value else None
        return dumper.represent_scalar("tag:yaml.org,2002:str", value, style=style)

    def _bool(dumper: Any, value: bool) -> Any:
        return dumper.represent_scalar("tag:yaml.org,2002:bool", "true" if value else "false")

    Dumper.add_representer(str, _str)
    Dumper.add_representer(bool, _bool)
    body = yaml.dump(data, Dumper=Dumper, sort_keys=False, allow_unicode=True)
    return (
        "# Ped Bot rules. Edit in Settings → Rules. Changes apply on the next action.\n"
        + body
    )


def _patch_merge(base: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base) if isinstance(base, dict) else {}
    for key, value in (extra or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _patch_merge(out[key], value)
        else:
            out[key] = value
    return out


def apply_patch(patch: dict[str, Any]) -> Path:
    """Update selected keys in the rules file. Other sections stay as they are."""
    if not isinstance(patch, dict):
        raise ValueError("Rules patch must be an object.")
    path = rules_path() or (APP_DIR / "rules.yaml")
    current = _raw_file()
    updated = _patch_merge(current, patch)
    text = dump_text(updated, path.suffix)
    parse_text(text, path.suffix)
    path.write_text(text, encoding="utf-8")
    load(force=True)
    return path


def editor_payload() -> dict[str, Any]:
    path = rules_path() or (APP_DIR / "rules.yaml")
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    data: dict[str, Any] = {}
    if text.strip():
        data = parse_text(text, path.suffix)
    return {
        "path": str(path),
        "text": text,
        "data": data,
        "defaults": {
            "confirm": copy.deepcopy(DEFAULT_RULES["confirm"]),
            "protect": copy.deepcopy(DEFAULT_RULES["protect"]),
            "files": copy.deepcopy(DEFAULT_RULES["files"]),
            "paths": copy.deepcopy(DEFAULT_RULES["paths"]),
        },
        "confirm_categories": [
            {"id": "delete", "label": "Deleting files"},
            {"id": "payment", "label": "Payments and checkout"},
            {"id": "send_message", "label": "Sending email or messages"},
            {"id": "power", "label": "Shut down the PC"},
            {"id": "kill_process", "label": "Force-close programs"},
            {"id": "network", "label": "Wi-Fi and VPN"},
            {"id": "self_upgrade", "label": "Installing Ped Bot updates"},
            {"id": "remote_control", "label": "Phone control of this PC"},
        ],
    }


def instructions() -> list[str]:
    """Standing owner rules from Settings. Applied on the next model call."""
    raw = load().get("instructions") or []
    if isinstance(raw, str):
        raw = [raw]
    out: list[str] = []
    if not isinstance(raw, list):
        return out
    for item in raw:
        text = " ".join(str(item).split())
        if not text:
            continue
        out.append(text[:500])
        if len(out) >= 40:
            break
    return out


def reset_cache() -> None:
    global _cache
    with _lock:
        _cache = None


# ---- paths -------------------------------------------------------------

def _long_path(text: str) -> str:
    """Expand Windows 8.3 short names (C:/Users/JOHNSM~1 -> C:/Users/JohnSmith)."""
    if os.name != "nt" or "~" not in text:
        return text
    try:
        import ctypes

        get_long = ctypes.windll.kernel32.GetLongPathNameW  # type: ignore[attr-defined]
        buffer = ctypes.create_unicode_buffer(32768)
        # Expand the longest existing prefix; keep the not-yet-created tail.
        head, tail = text, ""
        while head:
            if get_long(head, buffer, 32768):
                return os.path.join(buffer.value, tail) if tail else buffer.value
            parent, name = os.path.split(head)
            if parent == head:
                break
            tail = os.path.join(name, tail) if tail else name
            head = parent
    except Exception:
        pass
    return text


def _real(text: str) -> str:
    if not os.path.isabs(text):
        return text  # never resolve against the current folder
    try:
        text = os.path.realpath(text)
    except (OSError, ValueError):
        pass
    return _long_path(text)


def _norm(path: Path | str) -> str:
    text = str(path)
    if "*" not in text and "?" not in text and text.strip():
        text = _real(text)
    return text.replace("\\", "/").rstrip("/").casefold()


def _expand(pattern: str, workspace: Path | None, external: Path | None) -> str | None:
    text = str(pattern or "").strip()
    if not text:
        return None
    if text == "*":
        return "*"
    if text.startswith("{workspace}"):
        if workspace is None:
            return None
        text = str(workspace) + text[len("{workspace}"):]
    elif text.startswith("{external}"):
        if external is None:
            return None
        text = str(external) + text[len("{external}"):]
    elif text.startswith("~"):
        text = str(Path.home()) + text[1:]
    return _norm(text)


def _matches(path: Path, pattern: str | None) -> bool:
    if pattern is None:
        return False
    if pattern == "*":
        return True
    target = _norm(path)
    if fnmatch.fnmatchcase(target, pattern) or target == pattern:
        return True
    # folder pattern: everything under it
    if target.startswith(pattern + "/"):
        return True
    prefix_parts = pattern.count("/") + 1
    head = "/".join(target.split("/")[:prefix_parts])
    return fnmatch.fnmatchcase(head, pattern)


def path_blocked(path: Path, workspace: Path | None = None, external: Path | None = None) -> bool:
    rules = load()
    return any(_matches(path, _expand(p, workspace, external)) for p in rules["paths"].get("blocked") or [])


def path_allowed(path: Path, workspace: Path | None = None, external: Path | None = None) -> bool:
    if path_blocked(path, workspace, external):
        return False
    rules = load()
    return any(_matches(path, _expand(p, workspace, external)) for p in rules["paths"].get("allowed") or [])


def allowed_path_message() -> str:
    path = rules_path()
    where = str(path) if path else "rules.yaml"
    return f"That path is not allowed by your rules. Edit paths.allowed / paths.blocked in {where}."


def file_write_reason(path: Path) -> str | None:
    """Why a file must not be written, or None."""
    rules = load()
    files = rules.get("files") or {}
    suffix = path.suffix.casefold()
    blocked = {str(e).casefold() if str(e).startswith(".") else "." + str(e).casefold() for e in files.get("blocked_extensions") or []}
    if suffix in blocked:
        return f"Your rules block writing {suffix} files: {path.name}"
    if not files.get("allow_exe_writes") and (suffix == ".exe" or path.name.casefold() == "gta5.exe"):
        return f"Refusing to write an executable: {path.name} (set files.allow_exe_writes: true in your rules to allow)"
    return None


# ---- tools and confirmation -----------------------------------------------

def tool_block_reason(name: str) -> str | None:
    tools = load().get("tools") or {}
    blocked = {str(t) for t in tools.get("blocked") or []}
    allowed = {str(t) for t in tools.get("allowed") or []}
    if name in blocked:
        return f"Your rules block the tool {name}."
    if allowed and name not in allowed:
        return f"The tool {name} is not in your rules' tools.allowed list."
    return None


def _fold(value: Any) -> str:
    return " ".join(str(value or "").casefold().replace("-", " ").replace("_", " ").split())


def category_for(name: str, arguments: dict[str, Any]) -> str | None:
    for category, names in CATEGORY_TOOLS.items():
        if name in names:
            return category
    if name == "manage_windows_and_processes" and _fold(arguments.get("action")) in {"kill", "kill process"}:
        return "kill_process"
    if name == "self_upgrade" and _fold(arguments.get("action")) in {"apply", "rollback"}:
        return "self_upgrade"
    if name == "confirm_before":
        kind = _fold(arguments.get("kind"))
        return {"delete": "delete", "purchase": "payment", "buy": "payment", "pay": "payment"}.get(kind, "send_message")
    if name == "network_manager":
        action = str(arguments.get("action") or "").strip().casefold().replace("-", "_").replace(" ", "_")
        if action in _NETWORK:
            return "network"
    if name == "ui_click":
        label = " " + _fold(arguments.get("name")) + " "
        if any(w in label for w in (" delete ", " remove ", " erase ", " uninstall ", " empty recycle bin ")):
            return "delete"
        if any(w.strip() in label for w in _PAYMENT_WORDS) or any(w in label for w in (" buy ", " pay ", " checkout ")):
            return "payment"
        if any(w in label for w in (" send ", " post ", " publish ", " submit ", " share ")):
            return "send_message"
        return None
    if name in {"perform_actions", "browser_download_tool", "desktop_ui_automation", "click_screen_target"}:
        blob = json.dumps(arguments, default=str).casefold()
        if any(word in blob for word in _PAYMENT_WORDS):
            return "payment"
    return None


def needs_confirmation(name: str, arguments: dict[str, Any]) -> bool:
    confirm = load().get("confirm") or {}
    if not confirm.get("enabled", True):
        return False
    if name in {str(t) for t in confirm.get("extra_tools") or []}:
        return True
    if name == "create_routine" and confirm.get("ask_before_routines", True):
        return True   # a bot never adds a scheduled job without an Approve
    category = category_for(name, arguments)
    return category is not None and category in {str(c) for c in confirm.get("categories") or []}


def agent_setting(key: str, default: Any) -> Any:
    return (load().get("agent") or {}).get(key, default)


def limit(key: str) -> Any:
    """A `limits:` switch or number. Missing keys use DEFAULT_RULES."""
    value = (load().get("limits") or {}).get(key)
    if value is None:
        value = DEFAULT_RULES["limits"].get(key)
    return value


def cap(key: str, legacy: int) -> int | None:
    """Numeric limit: None = unlimited. `true` means the old built-in number."""
    value = limit(key)
    if value is True:
        return legacy
    try:
        number = int(value or 0)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def protect(key: str) -> bool:
    value = (load().get("protect") or {}).get(key)
    if value is None:
        value = DEFAULT_RULES["protect"].get(key, True)
    return bool(value)


def section(name: str, defaults: dict[str, Any]) -> dict[str, Any]:
    """A rules.yaml section merged over the module's defaults."""
    found = load().get(name)
    merged = dict(defaults)
    if isinstance(found, dict):
        merged.update(found)
    return merged


def speed_setting(key: str, default: Any = None) -> Any:
    value = (load().get("speed") or {}).get(key)
    if value is None:
        value = DEFAULT_RULES["speed"].get(key, default)
    return value


def voice_setting(key: str, default: Any) -> Any:
    return (load().get("voice") or {}).get(key, default)
