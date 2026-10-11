"""Delayed and repeating routines that stay inside the agent's own tools.

The scheduler does not launch scripts or programs. organize_downloads sorts
files already in Downloads, reindex_files rebuilds the external-drive index, and
remind prints a message when it is due.
"""

from __future__ import annotations

import shutil
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

ALLOWED = {"organize_downloads", "reindex_files", "remind"}
SCRIPT_MARKERS = (".py", ".bat", ".exe", ".ps1", ".cmd", ".com", "script", "powershell")
GROUPS = {
    ".txt": "Documents",
    ".md": "Documents",
    ".pdf": "Documents",
    ".doc": "Documents",
    ".docx": "Documents",
    ".rtf": "Documents",
    ".csv": "Spreadsheets",
    ".xlsx": "Spreadsheets",
    ".xls": "Spreadsheets",
    ".zip": "Archives",
    ".7z": "Archives",
    ".rar": "Archives",
    ".png": "Pictures",
    ".jpg": "Pictures",
    ".jpeg": "Pictures",
    ".gif": "Pictures",
    ".webp": "Pictures",
}
LEAVE_IN_PLACE = {".exe", ".dll", ".msi", ".bat", ".cmd", ".ps1", ".com", ".scr"}
_lock = threading.Lock()
_jobs: list[dict[str, Any]] = []
_next_id = 1
_stop = threading.Event()
_thread: threading.Thread | None = None


def _agent() -> Any:
    import gta5_agent

    return gta5_agent


def clear_jobs() -> None:
    global _next_id
    with _lock:
        _jobs.clear()
        _next_id = 1


def _now() -> float:
    agent = _agent()
    if agent.scheduler_clock is not None:
        return float(agent.scheduler_clock())
    return time.time()


def _minutes(value: Any, name: str) -> float | dict[str, Any]:
    agent = _agent()
    if value is None or value == "":
        return 0.0
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return agent._err(f"{name} must be a number of minutes.")
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return 0.0
        try:
            value = float(text)
        except ValueError:
            return agent._err(f"{name} must be a number of minutes.")
    number = float(value)
    if number < 0:
        return agent._err(f"{name} cannot be negative.")
    if 0 < number < 1:
        return agent._err("The shortest schedule is 1 minute.")
    return number


def _rule_text(minutes: int, repeat: bool) -> str:
    agent = _agent()
    fallback = (
        f"every {minutes} minutes" if repeat else f"once after {minutes} minutes"
    )
    try:
        if agent.schedule_module_override is not None:
            lib = agent.schedule_module_override
        else:
            import schedule as lib
        preview = lib.Scheduler()
        job = preview.every(minutes).minutes.do(lambda: None)
        interval = getattr(job, "interval", minutes)
        unit = getattr(job, "unit", "minutes")
        clear = getattr(preview, "clear", None)
        if clear is not None:
            clear()
        if repeat:
            return f"every {interval} {unit}"
        unit_name = "minute" if int(minutes) == 1 else "minutes"
        return f"once after {int(minutes)} {unit_name}"
    except Exception:
        return fallback


def _unique_destination(folder: Path, name: str) -> Path:
    candidate = folder / name
    if not candidate.exists():
        return candidate
    stem = Path(name).stem
    suffix = Path(name).suffix
    for number in range(2, 100):
        candidate = folder / f"{stem}-{number}{suffix}"
        if not candidate.exists():
            return candidate
    return folder / f"{stem}-copy{suffix}"


def organize_downloads_folder() -> dict[str, Any]:
    """Move loose downloads into folders. Programs are left where they are."""
    agent = _agent()
    folder = agent._downloads_folder()
    if not folder.is_dir():
        return agent._err(f"The Downloads folder does not exist: {folder}")
    moved: list[str] = []
    skipped: list[str] = []
    for path in folder.iterdir():
        if not path.is_file() or path.is_symlink():
            continue
        suffix = path.suffix.casefold()
        if suffix in LEAVE_IN_PLACE:
            skipped.append(path.name)
            continue
        group = GROUPS.get(suffix, "Other")
        destination_dir = folder / group
        destination_dir.mkdir(exist_ok=True)
        destination = _unique_destination(destination_dir, path.name)
        shutil.move(str(path), str(destination))
        moved.append(path.name)
    return agent._ok(
        f"Organized {len(moved)} file(s) in Downloads. Left {len(skipped)} program(s) in place.",
        moved=moved,
        skipped=skipped,
        folder=str(folder),
    )


def _run_job(job: dict[str, Any]) -> dict[str, Any]:
    agent = _agent()
    task = job["task"]
    if task == "organize_downloads":
        return organize_downloads_folder()
    if task == "reindex_files":
        import local_search

        return local_search.index_local_files()
    if task == "remind":
        message = job.get("message") or "Reminder."
        print(f"[schedule] reminder: {message}", flush=True)
        return agent._ok(f"Reminder: {message}")
    if task == "health_check":
        import diagnostics

        return diagnostics.system_diagnostics()
    if task == "screenshot_to_phone":
        import remote_bridge

        return remote_bridge._deliver_screenshot()
    if task == "backup_notes":
        return backup_notes()
    return agent._err(f"Unknown scheduled task: {task}")


def run_due_tasks() -> list[dict[str, Any]]:
    """Run jobs whose time has arrived. One-shot jobs are then removed."""
    now = _now()
    due: list[dict[str, Any]] = []
    with _lock:
        kept: list[dict[str, Any]] = []
        for job in _jobs:
            if float(job["next_run"]) <= now:
                due.append(job)
            else:
                kept.append(job)
        _jobs[:] = kept
    results: list[dict[str, Any]] = []
    for job in due:
        try:
            result = _run_job(job)
        except Exception as exc:
            result = _agent()._err(f"{job['task']} failed: {exc}")
        status = result.get("message") or result.get("error") or ""
        print(f"[schedule] {job['task']}: {status}", flush=True)
        results.append(result)
        if job.get("daily_at"):
            job["next_run"] = _next_daily(str(job["daily_at"]), now + 60)
            job["interval"] = 86400.0
            with _lock:
                _jobs.append(job)
        elif float(job["interval"]) > 0:
            job["next_run"] = now + float(job["interval"])
            with _lock:
                _jobs.append(job)
    return results


def _next_daily(hhmm: str, after: float) -> float:
    hour, minute = (int(part) for part in hhmm.split(":", 1))
    moment = datetime.fromtimestamp(after)
    target = moment.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target.timestamp() <= after:
        target += timedelta(days=1)
    return target.timestamp()


def _daily_at(value: str) -> tuple[str, float] | dict[str, Any]:
    agent = _agent()
    text = " ".join((value or "").split())
    if not text:
        return "", 0.0
    parts = text.split(":")
    if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():
        return agent._err("daily_at must look like 02:00.")
    hour = int(parts[0])
    minute = int(parts[1])
    if hour > 23 or minute > 59 or len(parts[1]) != 2:
        return agent._err("daily_at must look like 02:00.")
    stamp = f"{hour:02d}:{minute:02d}"
    delay = _next_daily(stamp, _now()) - _now()
    if delay < 60:
        delay = _next_daily(stamp, _now() + 86400) - _now()
    return stamp, delay


_NOTE_EXTS = {".txt", ".md"}
_SECRET_NAMES = {".env", "id_rsa", "id_dsa", "known_hosts"}
_SECRET_EXTS = {".pem", ".key", ".env"}


def backup_notes() -> dict[str, Any]:
    """Copy up to 50 text notes. Programs, secrets, and the game are skipped."""
    agent = _agent()
    import local_search

    roots, problem = local_search._search_roots("")
    if problem:
        return agent._err(problem)
    destination = agent.WORKSPACE / "backups" / "notes"
    if agent.search_root_override is None:
        external = agent._external_drive_root()
        if external is not None:
            destination = external / "Backups" / "notes"
    destination.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    for root in roots:
        for path in local_search._iter_files([root]):
            if len(copied) >= 50:
                break
            suffix = path.suffix.casefold()
            if suffix not in _NOTE_EXTS:
                continue
            if path.name.casefold() in _SECRET_NAMES or suffix in _SECRET_EXTS:
                continue
            if suffix in LEAVE_IN_PLACE:
                continue
            try:
                relative = path.resolve().relative_to(root.resolve())
            except (OSError, ValueError):
                continue
            if any(part == ".." for part in relative.parts):
                continue
            target = destination / relative
            try:
                if target.exists() and target.stat().st_mtime >= path.stat().st_mtime:
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)
            except OSError:
                continue
            copied.append(path.name)
    return agent._ok(
        f"Copied {len(copied)} note file(s). Programs and secrets were left alone.",
        copied=copied,
        folder=str(destination),
    )


_JOB_ALIASES = {
    "organize_downloads": "organize_downloads",
    "organize": "organize_downloads",
    "downloads": "organize_downloads",
    "reindex_files": "reindex_files",
    "reindex": "reindex_files",
    "index": "reindex_files",
    "remind": "remind",
    "reminder": "remind",
    "health_check": "health_check",
    "health": "health_check",
    "screenshot_to_phone": "screenshot_to_phone",
    "screenshot": "screenshot_to_phone",
    "backup_notes": "backup_notes",
    "backup": "backup_notes",
    "notes_backup": "backup_notes",
}
_FULL_COPY = ("full disk", "full backup", "game backup", "copy the game", "entire game")


def job_scheduler(
    task: str,
    delay_minutes: Any = 0,
    interval_minutes: Any = 0,
    message: str = "",
    daily_at: str = "",
) -> dict[str, Any]:
    """Queue a safe routine, including a daily clock time. Scripts are refused."""
    global _next_id
    agent = _agent()
    try:
        folded = (task or "").casefold()
        if any(phrase in folded for phrase in _FULL_COPY):
            return agent._err(
                "A full disk or game copy is not a scheduled task. "
                "I can back up text notes only."
            )
        if any(marker in folded for marker in SCRIPT_MARKERS):
            return agent._err(
                "Scheduled tasks cannot run scripts or programs. "
                "Use organize_downloads, reindex_files, remind, health_check, "
                "screenshot_to_phone, or backup_notes."
            )
        name = " ".join(folded.replace("-", " ").split()).replace(" ", "_")
        canonical = _JOB_ALIASES.get(name)
        if canonical is None:
            return agent._err(
                "task must be organize_downloads, reindex_files, remind, "
                "health_check, screenshot_to_phone, or backup_notes."
            )
        daily = _daily_at(str(daily_at or ""))
        if isinstance(daily, dict):
            return daily
        stamp, daily_delay = daily
        delay = _minutes(delay_minutes, "delay_minutes")
        if isinstance(delay, dict):
            return delay
        interval = _minutes(interval_minutes, "interval_minutes")
        if isinstance(interval, dict):
            return interval
        if stamp:
            delay = daily_delay / 60.0
            interval = 1440.0
        elif delay == 0 and interval == 0:
            return agent._err("Say when to run it, in minutes or as a daily time.")
        note = agent._scrub(" ".join((message or "").split())[:300])
        if canonical == "remind" and not note:
            return agent._err("A reminder needs a message.")
        if note and agent._memory_is_secret(note):
            return agent._err("That reminder looks like a password or API key.")
        repeat = interval > 0
        first = delay if delay > 0 else interval
        if stamp:
            rule = f"every day at {stamp}"
        else:
            rule = _rule_text(int(first if not repeat else (interval or first)), repeat)
        job = {
            "id": _next_id,
            "task": canonical,
            "message": note,
            "next_run": _now() + (first * 60),
            "interval": (interval * 60) if repeat else 0,
            "rule": rule,
            "daily_at": stamp,
        }
        with _lock:
            if len(_jobs) >= 20:
                return agent._err("There are already 20 scheduled tasks.")
            _next_id += 1
            _jobs.append(job)
        print(f"[schedule] {rule}: {canonical}", flush=True)
        return agent._ok(
            f"Scheduled {canonical}. {rule}.",
            task=canonical,
            rule=rule,
            id=job["id"],
        )
    except AssertionError:
        raise
    except Exception as exc:
        return agent._err(f"job_scheduler failed: {exc}")


JOB_DECLARATIONS = [
    {
        "name": "job_scheduler",
        "description": (
            "Schedule organize_downloads, reindex_files, remind, health_check, "
            "screenshot_to_phone, or backup_notes. daily_at is a 24-hour time "
            "such as 02:00. backup_notes copies text notes only. It does not "
            "copy the game or run a script."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "task": {"type": "string", "description": "Allowlisted task name."},
                "delay_minutes": {"type": "number", "description": "Minutes from now. Minimum 1."},
                "interval_minutes": {
                    "type": "number",
                    "description": "Repeat interval in minutes. Minimum 1.",
                },
                "daily_at": {"type": "string", "description": "Daily time, such as 02:00."},
                "message": {"type": "string", "description": "Reminder text, when task is remind."},
            },
            "required": ["task"],
        },
    }
]


def schedule_background_task(
    task: str,
    delay_minutes: Any = 0,
    interval_minutes: Any = 0,
    message: str = "",
) -> dict[str, Any]:
    """Queue an allowlisted routine. Scripts and programs are refused."""
    global _next_id
    agent = _agent()
    try:
        name = " ".join((task or "").casefold().replace("-", " ").split()).replace(" ", "_")
        folded = (task or "").casefold()
        if any(marker in folded for marker in SCRIPT_MARKERS):
            return agent._err(
                "Scheduled tasks cannot run scripts or programs. "
                "Use organize_downloads, reindex_files, or remind."
            )
        aliases = {
            "organize_downloads": "organize_downloads",
            "organize": "organize_downloads",
            "downloads": "organize_downloads",
            "reindex_files": "reindex_files",
            "reindex": "reindex_files",
            "index": "reindex_files",
            "remind": "remind",
            "reminder": "remind",
        }
        canonical = aliases.get(name)
        if canonical not in ALLOWED:
            return agent._err(
                "task must be organize_downloads, reindex_files, or remind."
            )
        delay = _minutes(delay_minutes, "delay_minutes")
        if isinstance(delay, dict):
            return delay
        interval = _minutes(interval_minutes, "interval_minutes")
        if isinstance(interval, dict):
            return interval
        if delay == 0 and interval == 0:
            return agent._err("Say when to run it, in minutes.")
        note = agent._scrub(" ".join((message or "").split())[:300])
        if canonical == "remind" and not note:
            return agent._err("A reminder needs a message.")
        if note and agent._memory_is_secret(note):
            return agent._err("That reminder looks like a password or API key.")
        repeat = interval > 0
        first = delay if delay > 0 else interval
        rule = _rule_text(int(first if not repeat else (interval or first)), repeat)
        job = {
            "id": _next_id,
            "task": canonical,
            "message": note,
            "next_run": _now() + (first * 60),
            "interval": (interval * 60) if repeat else 0,
            "rule": rule,
        }
        with _lock:
            if len(_jobs) >= 20:
                return agent._err("There are already 20 scheduled tasks.")
            _next_id += 1
            _jobs.append(job)
        print(f"[schedule] {rule}: {canonical}", flush=True)
        return agent._ok(
            f"Scheduled {canonical}. {rule}.",
            task=canonical,
            rule=rule,
            id=job["id"],
        )
    except AssertionError:
        raise
    except Exception as exc:
        return agent._err(f"schedule_background_task failed: {exc}")


def _loop() -> None:
    while not _stop.wait(1.0):
        try:
            run_due_tasks()
        except Exception as exc:
            print(f"[schedule] {exc}", flush=True)


def start_background_scheduler() -> None:
    global _thread
    if _thread is not None and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="agent-schedule", daemon=True)
    _thread.start()


def stop_background_scheduler() -> None:
    _stop.set()
