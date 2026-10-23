"""Low-priority work while nobody is using the PC.

Idle time comes from GetLastInputInfo. pywin32 is not required. The work
pauses as soon as the keyboard or mouse is used again. Tests set
idle_seconds_override and idle_runner_override.
"""

from __future__ import annotations

import os
import threading
from typing import Any

TASKS = ("reindex_files", "organize_downloads", "health_check")
_stop = threading.Event()
_thread: threading.Thread | None = None


def _agent() -> Any:
    import agent_core

    return agent_core


def idle_seconds() -> float:
    agent = _agent()
    if agent.idle_seconds_override is not None:
        return float(agent.idle_seconds_override)
    import voice_checkin

    return voice_checkin._last_input_idle()


def threshold_seconds() -> float:
    agent = _agent()
    if agent.idle_task_seconds_override is not None:
        return max(1.0, float(agent.idle_task_seconds_override))
    raw = os.environ.get("IDLE_TASK_SECONDS", "").strip()
    try:
        value = float(raw) if raw else 300.0
    except ValueError:
        value = 300.0
    return value if value >= 1 else 300.0


def _dispatch(task: str) -> dict[str, Any]:
    agent = _agent()
    if task == "reindex_files":
        import local_search

        return local_search.index_local_files()
    if task == "organize_downloads":
        import task_schedule

        return task_schedule.organize_downloads_folder()
    if task == "health_check":
        import diagnostics

        return diagnostics.system_diagnostics()
    return agent._err(f"Unknown idle task: {task}")


def run_idle_pass() -> dict[str, Any]:
    """Run the allowlisted tasks until the PC is no longer idle."""
    agent = _agent()
    try:
        import safe_mode

        if safe_mode.paused():
            return agent._ok("Safe mode is on, so idle tasks are paused.", paused=True)
    except Exception:
        pass
    try:
        limit = threshold_seconds()
        if idle_seconds() < limit:
            return agent._ok(
                "The PC is in use, so idle tasks are paused.",
                status="paused",
                ran=[],
            )
        ran: list[str] = []
        for task in TASKS:
            if idle_seconds() < limit:
                return agent._ok(
                    "Paused idle tasks because input resumed.",
                    status="paused",
                    ran=ran,
                )
            if agent.idle_runner_override is not None:
                agent.idle_runner_override(task)
            else:
                outcome = _dispatch(task)
                if not outcome.get("ok"):
                    return outcome
            ran.append(task)
            print(f"[idle] {task}", flush=True)
        return agent._ok(
            "Finished the idle tasks.",
            status="done",
            ran=ran,
        )
    except AssertionError:
        raise
    except Exception as exc:
        return _agent()._err(f"idle_task_scheduler failed: {exc}")


def idle_task_scheduler(action: str = "status") -> dict[str, Any]:
    """Report idle time, or run one pass when action is run."""
    agent = _agent()
    key = " ".join((action or "status").casefold().split())
    if key in {"", "status"}:
        idle = idle_seconds()
        limit = threshold_seconds()
        state = "idle" if idle >= limit else "active"
        return agent._ok(
            f"Idle for {int(idle)} seconds. Threshold is {int(limit)} seconds.",
            status=state,
            idle_seconds=idle,
            threshold=limit,
        )
    if key in {"run", "start"}:
        return run_idle_pass()
    return agent._err("action must be status or run.")


DECLARATIONS = [
    {
        "name": "idle_task_scheduler",
        "description": (
            "Report how long this PC has been idle, or run one pass of "
            "low-priority indexing, download organizing, and a health check. "
            "The pass pauses when keyboard or mouse input resumes. It does not "
            "run scripts."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "status or run. Default status.",
                }
            },
        },
    }
]


def _loop() -> None:
    while not _stop.is_set():
        agent = _agent()
        if agent.background_services_enabled:
            try:
                run_idle_pass()
            except Exception as exc:
                print(f"[idle] {exc}", flush=True)
        if _stop.wait(5.0):
            return


def start_idle_tasks() -> None:
    global _thread
    agent = _agent()
    if not agent.background_services_enabled:
        return
    if _thread is not None and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="idle-tasks", daemon=True)
    _thread.start()


def stop_idle_tasks() -> None:
    _stop.set()
