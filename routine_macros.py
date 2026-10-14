"""Save and replay a short list of tool steps.

Playback goes through invoke_tool, so a sensitive step still waits for a yes.
The agent does not invent or auto-run a destructive routine.
"""

from __future__ import annotations

import json
import re
from collections import deque
from typing import Any

_MAX_STEPS = 8
_LOG_CAP = 50
_recent: deque[str] = deque(maxlen=_LOG_CAP)
_SHELL = re.compile(r"[&|;`<>]")


def _agent() -> Any:
    import agent_core

    return agent_core


def reset() -> None:
    _recent.clear()


def note_tool(name: str) -> None:
    if name:
        _recent.append(name)


def _path() -> Any:
    agent = _agent()
    agent.WORKSPACE.mkdir(parents=True, exist_ok=True)
    return agent.WORKSPACE / "routines.json"


BUILTIN: dict[str, list[dict[str, Any]]] = {
    "Wingz assignments": [
        {"tool": "open_website", "arguments": {"url": "https://wingz.itvedant.com/"}},
        {"tool": "verify_screen", "arguments": {"expectation": (
            "The Itvedant Wingz portal is open and signed in (a dashboard or course list, not the Login page). "
            "If the Login page shows, say LOGIN and whether a 'Login with Google' button is visible; "
            "if a password box shows, say PASSWORD WALL.")}},
    ],
}


def _load() -> dict[str, Any]:
    path = _path()
    raw: Any = {}
    if path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raw = {}
    raw = raw if isinstance(raw, dict) else {}
    for name, steps in BUILTIN.items():
        raw.setdefault(name, steps)
    return raw


def _save_file(data: dict[str, Any]) -> None:
    _path().write_text(json.dumps(data, indent=2), encoding="utf-8")


def _steps(raw: Any) -> list[dict[str, Any]] | str:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return "steps must be a list of {tool, arguments} objects."
    if not isinstance(raw, list) or not raw:
        return "steps must be a list of {tool, arguments} objects."
    if len(raw) > _MAX_STEPS:
        return f"A routine can have at most {_MAX_STEPS} steps."
    agent = _agent()
    steps: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            return "Each routine step must be an object."
        tool = str(item.get("tool") or "").strip()
        arguments = item.get("arguments") or {}
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                return "Step arguments must be a JSON object."
        if not isinstance(arguments, dict):
            return "Step arguments must be a JSON object."
        if tool not in agent.TOOLS or tool == "routine_macro_engine":
            return f"{tool or 'That step'} cannot be saved in a routine."
        blob = json.dumps(arguments)
        if agent.PIRACY_TERMS.search(blob) or agent._memory_is_secret(blob) or _SHELL.search(blob):
            return "That routine step looks like a secret, a crack, or a shell command."
        steps.append({"tool": tool, "arguments": arguments})
    return steps


def routine_macro_engine(
    action: str,
    name: str = "",
    steps: Any = None,
) -> dict[str, Any]:
    """save, run, list, or recent. run plays a saved name such as 3D-Export."""
    agent = _agent()
    try:
        key = " ".join((action or "").casefold().replace("-", " ").split())
        title = " ".join((name or "").split())[:80]
        if key in {"recent", "log"}:
            names = list(_recent)
            return agent._ok(
                f"{len(names)} recent tool call(s).",
                tools=names,
            )
        if key in {"list", "show"}:
            saved = _load()
            return agent._ok(
                f"{len(saved)} saved routine(s).",
                routines=sorted(saved),
            )
        if key in {"save", "remember"}:
            if not title:
                return agent._err("A routine needs a name.")
            parsed = _steps(steps)
            if isinstance(parsed, str):
                return agent._err(parsed)
            saved = _load()
            saved[title] = parsed
            _save_file(saved)
            return agent._ok(
                f"Saved routine {title} with {len(parsed)} step(s).",
                name=title,
                steps=len(parsed),
            )
        if key in {"run", "execute", "play"}:
            if not title:
                return agent._err("Say which routine to run.")
            saved = _load()
            chosen = saved.get(title)
            if not isinstance(chosen, list):
                return agent._err(f"No routine is named {title}.")
            completed: list[str] = []
            for index, step in enumerate(chosen, 1):
                result = agent.invoke_tool(step["tool"], step.get("arguments") or {})
                if not result.get("ok"):
                    detail = result.get("error") or result.get("message") or "The step failed."
                    failed = agent._err(
                        f"Stopped on step {index} of {title}. {detail}",
                        completed=completed,
                        needs_confirmation=result.get("needs_confirmation", False),
                    )
                    return failed
                completed.append(step["tool"])
            return agent._ok(
                f"Ran routine {title}.",
                name=title,
                completed=completed,
            )
        return agent._err("action must be save, run, list, or recent.")
    except AssertionError:
        raise
    except Exception as exc:
        return agent._err(f"routine_macro_engine failed: {exc}")


DECLARATIONS = [
    {
        "name": "routine_macro_engine",
        "description": (
            "Save up to 8 tool steps as a named voice shortcut, or run one "
            "that was saved, such as 3D-Export. Playback uses the normal tools, "
            "so closing a program still waits for a yes. It does not run shell "
            "commands or learn destructive steps on its own."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "save, run, list, or recent.",
                },
                "name": {"type": "string", "description": "Routine name, such as 3D-Export."},
                "steps": {
                    "type": "array",
                    "description": "For save: objects with tool and arguments.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "tool": {
                                "type": "string",
                                "description": "Name of an existing tool.",
                            },
                            "arguments": {
                                "type": "object",
                                "description": "Arguments for that tool.",
                            },
                        },
                        "required": ["tool"],
                    },
                },
            },
            "required": ["action"],
        },
    }
]
