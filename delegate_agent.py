"""Route one task to a specialist worker without a second model call.

Workers may run only the tools on their list. They do not start a shell and
they do not call Gemini. A worker that is still going after a short wait
returns status started.
"""

from __future__ import annotations

import json
import threading
from typing import Any

_JOIN_SECONDS = 0.5
_MAX_JOBS = 3
_WORKERS = {
    "blender": {"run_blender_task", "blender_job_status"},
    "files": {"search_local_files", "search_files_by_time", "file_content_rag_search"},
    "system": {"system_diagnostics", "focus_window", "manage_window_layout"},
}
_ALIASES = {
    "blender": "blender",
    "3d": "blender",
    "files": "files",
    "file": "files",
    "data": "files",
    "system": "system",
    "admin": "system",
}
_lock = threading.Lock()
_inflight = 0


def _agent() -> Any:
    import agent_core

    return agent_core


def _worker_name(value: str) -> str | None:
    key = " ".join((value or "").casefold().replace("-", " ").replace("_", " ").split())
    return _ALIASES.get(key)


def _object_arguments(raw: Any) -> dict[str, Any] | None:
    if raw is None or raw == "":
        return {}
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return {}
        if not text.startswith("{"):
            return None
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return None
        if isinstance(parsed, dict):
            return parsed
    return None


def _infer(worker: str, task: str) -> tuple[str, dict[str, Any]] | None:
    folded = (task or "").casefold()
    if worker == "blender":
        if any(word in folded for word in ("status", "done", "ready", "open")):
            return "blender_job_status", {}
        return None
    if worker == "files":
        if any(word in folded for word in ("yesterday", "last week", "last month", "today", "recent")):
            return "search_files_by_time", {"query": task}
        return "file_content_rag_search", {"query": task}
    if worker == "system":
        if "focus" in folded or "window" in folded:
            return "focus_window", {"window_title": task[:200]}
        if "minimize" in folded:
            return "manage_window_layout", {"action": "minimize", "window_title": ""}
        if "snap" in folded and "right" in folded:
            return "manage_window_layout", {"action": "snap_right", "window_title": ""}
        if "snap" in folded or "maximize" in folded:
            action = "snap_left" if "snap" in folded else "maximize"
            return "manage_window_layout", {"action": action, "window_title": ""}
        return "system_diagnostics", {}
    return None


def delegate_subagent(
    worker: str,
    task: str,
    tool: str = "",
    arguments: Any = None,
) -> dict[str, Any]:
    """Start one allowlisted worker. status started means it is not finished."""
    global _inflight
    agent = _agent()
    try:
        name = _worker_name(worker)
        if name is None:
            return agent._err("worker must be blender, files, or system.")
        requested = " ".join((tool or "").casefold().replace("-", "_").split())
        if requested:
            if requested not in _WORKERS[name]:
                return agent._err(
                    f"{requested} is not a {name} worker tool. "
                    "Workers cannot close programs or run shell commands."
                )
            payload = _object_arguments(arguments)
            if payload is None:
                return agent._err("arguments must be a JSON object.")
            chosen = (requested, payload)
        else:
            chosen = None
        with _lock:
            if _inflight >= _MAX_JOBS:
                return agent._err("Three workers are already running.")
            _inflight += 1
        box: dict[str, Any] = {}

        def _run() -> None:
            global _inflight
            try:
                if agent.delegate_runner_override is not None:
                    box["result"] = agent.delegate_runner_override(name, task)
                    return
                if chosen is None:
                    inferred = _infer(name, task)
                    if inferred is None:
                        box["result"] = agent._err(
                            "The blender worker needs a script in tool arguments."
                        )
                        return
                    tool_name, tool_args = inferred
                else:
                    tool_name, tool_args = chosen
                box["result"] = agent.invoke_tool(tool_name, tool_args)
                box["tool"] = tool_name
            except BaseException as exc:
                box["error"] = exc
            finally:
                with _lock:
                    _inflight = max(0, _inflight - 1)

        worker_thread = threading.Thread(target=_run, name=f"delegate-{name}", daemon=True)
        worker_thread.start()
        worker_thread.join(_JOIN_SECONDS)
        if worker_thread.is_alive():
            return agent._ok(
                f"The {name} worker has started.",
                status="started",
                worker=name,
            )
        if "error" in box:
            if isinstance(box["error"], AssertionError):
                raise box["error"]
            return agent._err(f"delegate_subagent failed: {box['error']}")
        result = box.get("result")
        if not isinstance(result, dict):
            result = agent._ok("The worker finished.")
        else:
            result = dict(result)
        result["status"] = "ready"
        result["worker"] = name
        if box.get("tool"):
            result["tool"] = box["tool"]
        return result
    except AssertionError:
        raise
    except Exception as exc:
        return agent._err(f"delegate_subagent failed: {exc}")


DECLARATIONS = [
    {
        "name": "delegate_subagent",
        "description": (
            "Hand one task to a specialist worker and keep going. worker is "
            "blender, files, or system. tool must be on that worker's list. "
            "Workers do not call the model again and do not run shell commands. "
            "status started means the worker is not finished."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "worker": {"type": "string", "description": "blender, files, or system."},
                "task": {"type": "string", "description": "What the worker should do."},
                "tool": {
                    "type": "string",
                    "description": "Optional tool name on that worker's allowlist.",
                },
                "arguments": {
                    "type": "object",
                    "description": "JSON object of arguments for tool. Not a shell command.",
                },
            },
            "required": ["worker", "task"],
        },
    }
]
