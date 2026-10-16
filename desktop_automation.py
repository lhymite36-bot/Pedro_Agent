"""Drive a desktop app with the existing click, type, and focus tools.

pywinauto is not installed. Steps stay on the 0-1000 grid and the key list
the other desktop tools already allow. At most 8 steps run in one call.
"""

from __future__ import annotations

import json
from typing import Any

_MAX_STEPS = 8


def _agent() -> Any:
    import agent_core

    return agent_core


def _steps(raw: Any) -> list[dict[str, Any]] | str:
    if raw is None or raw == "":
        return []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return "steps must be a list of action objects."
    if not isinstance(raw, list):
        return "steps must be a list of action objects."
    if len(raw) > _MAX_STEPS:
        return f"At most {_MAX_STEPS} desktop steps can run in one call."
    steps: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, dict):
            steps.append(dict(item))
        else:
            return "Each desktop step must be an object."
    return steps


def desktop_ui_automation(
    app: str = "",
    window_title: str = "",
    steps: Any = None,
) -> dict[str, Any]:
    """Focus a known app or window, then run a short action list."""
    agent = _agent()
    try:
        parsed = _steps(steps)
        if isinstance(parsed, str):
            return agent._err(parsed)
        app_name = " ".join((app or "").split())
        title = " ".join((window_title or "").split())
        if not app_name and not title and not parsed:
            return agent._err("Say which app, window, or steps to run.")
        notes: list[str] = []
        import desktop_share

        with desktop_share.hold(claim=False):
            return _run_desktop(agent, app_name, title, parsed, notes)
    except AssertionError:
        raise
    except Exception as exc:
        return agent._err(f"desktop_ui_automation failed: {exc}")


def _run_desktop(agent: Any, app_name: str, title: str, parsed: list[dict[str, Any]], notes: list[str]) -> dict[str, Any]:
    if app_name:
        opened = agent.launch_application(app_name)
        if not opened.get("ok"):
            return opened
        notes.append(str(opened.get("message") or f"Opened {app_name}."))
    if title:
        import window_control

        focused = window_control.focus_window(title)
        if not focused.get("ok"):
            return focused
        notes.append(str(focused.get("message") or f"Focused {title}."))
    image = None
    mime = None
    if parsed:
        ran = agent.perform_actions(parsed)
        if not ran.get("ok"):
            return ran
        notes.append(str(ran.get("message") or "Ran the steps."))
        image = ran.get("_screenshot_bytes")
        mime = ran.get("_screenshot_mime")
    payload = agent._ok(" ".join(notes), app=app_name, window_title=title, steps=len(parsed))
    if isinstance(image, (bytes, bytearray)) and image:
        payload["_screenshot_bytes"] = bytes(image)
        payload["_screenshot_mime"] = mime or "image/jpeg"
    return payload


DECLARATIONS = [
    {
        "name": "desktop_ui_automation",
        "description": (
            "Open a known app such as Excel, Power BI, SSMS, or Chrome, focus "
            "a window, and run up to 8 click, type, or key steps. Coordinates "
            "are the 0-1000 screen grid. Do not pass a shell command."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "app": {"type": "string", "description": "Known app name, such as excel."},
                "window_title": {"type": "string", "description": "Window title to focus."},
                "steps": {
                    "type": "array",
                    "description": "Up to 8 click, type, press, scroll, navigate, or screenshot steps.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "action": {"type": "string"},
                            "x": {"type": "integer"},
                            "y": {"type": "integer"},
                            "text": {"type": "string"},
                            "key": {"type": "string"},
                            "button": {"type": "string"},
                            "clicks": {"type": "integer"},
                            "direction": {"type": "string"},
                            "amount": {"type": "integer"},
                            "url": {"type": "string"},
                        },
                        "required": ["action"],
                    },
                },
            },
        },
    }
]
