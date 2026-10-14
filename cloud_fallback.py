"""Backup cloud model used only when every Gemini model is busy (503 / high demand).

Default provider is Groq (free tier, OpenAI-compatible, supports tool calls).
It needs the user's own key in GROQ_API_KEY (Settings -> Backup model key).
Nothing is sent anywhere unless that key is set. Tests set transport_override.
"""

from __future__ import annotations

import json
import os
import urllib.request
from typing import Any, Callable

DEFAULT_URL = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_MODEL = "llama-3.3-70b-versatile"
_TIMEOUT = 90
transport_override: Callable[[dict[str, Any]], dict[str, Any]] | None = None

NO_BACKUP_MESSAGE = (
    "All Gemini models are busy right now (Google says 503 / high demand), and no backup "
    "model is set up, so I stopped. Your progress is kept: ask me to continue in a few "
    "minutes. To keep working when Gemini is busy, paste a free Groq API key "
    "(console.groq.com/keys) in Settings -> Backup model key."
)


def _agent() -> Any:
    import agent_core

    return agent_core


def api_key() -> str:
    return os.environ.get("GROQ_API_KEY", "").strip()


def available() -> bool:
    return transport_override is not None or bool(api_key())


def model_name() -> str:
    return os.environ.get("BACKUP_MODEL", "").strip() or DEFAULT_MODEL


def _post(body: dict[str, Any]) -> dict[str, Any]:
    if transport_override is not None:
        return transport_override(body)
    req = urllib.request.Request(
        os.environ.get("BACKUP_MODEL_URL", "").strip() or DEFAULT_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key()}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as exc:  # never echo the key
        raise RuntimeError(f"The backup model could not be reached: {type(exc).__name__}.") from exc


def _tools() -> list[dict[str, Any]]:
    out = []
    for item in _agent().TOOL_DECLARATIONS:
        out.append({"type": "function", "function": {
            "name": item["name"],
            "description": (item.get("description") or "")[:1000],
            "parameters": item.get("parameters") or {"type": "object", "properties": {}},
        }})
    return out


def run(user_text: str, *, on_event: Callable[[dict[str, Any]], None] | None = None,
        max_rounds: int = 40) -> str:
    """Run the tool loop on the backup model. Same tools and safety checks as Gemini."""
    agent = _agent()
    emit = on_event or (lambda e: None)
    emit({"event": "model_switch", "model": f"backup:{model_name()}"})
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": agent._scrub(agent.system_prompt())},
        {"role": "user", "content": agent._scrub(user_text)},
    ]
    tools = _tools()
    for _ in range(max_rounds):
        data = _post({"model": model_name(), "messages": messages, "tools": tools})
        choice = (data.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        calls = msg.get("tool_calls") or []
        if not calls:
            return str(msg.get("content") or "").strip() or "The backup model returned no text."
        messages.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": calls})
        for call in calls:
            fn = call.get("function") or {}
            name = str(fn.get("name") or "")
            raw = fn.get("arguments")
            try:
                args = json.loads(raw) if isinstance(raw, str) and raw.strip() else dict(raw or {})
            except (json.JSONDecodeError, TypeError, ValueError):
                args = {}
            emit({"event": "tool_start", "name": name, "arguments": args})
            result = agent._execute_logged_tool(name, args)
            emit({"event": "tool_end", "name": name, "ok": bool(result.get("ok", True))})
            public = {k: v for k, v in result.items() if not str(k).startswith("_")}
            messages.append({"role": "tool", "tool_call_id": call.get("id") or name,
                             "content": agent._scrub(json.dumps(public, default=str))[:8000]})
    return f"Stopped after {max_rounds} tool rounds on the backup model. Ask me to continue."
