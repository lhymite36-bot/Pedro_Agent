"""Backup cloud model used only when every Gemini model is busy (503 / high demand).

Default provider is Groq (free tier, OpenAI-compatible, supports tool calls).
It needs the user's own key in GROQ_API_KEY (Settings -> Backup model key).
Nothing is sent anywhere unless that key is set. Tests set transport_override.
"""

from __future__ import annotations

import json
import re
import os
import urllib.request
from typing import Any, Callable

DEFAULT_URL = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_MODEL = "openai/gpt-oss-120b"   # llama-3.3-70b-versatile was retired on Groq
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
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key()}",
                 "User-Agent": "PedroAgent/1.4.12 (+https://github.com/lhymite36-bot/Pedro_Agent)"},  # Groq's Cloudflare blocks the urllib default (error 1010)
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as exc:  # never echo the key
        if getattr(exc, "code", None) == 413:
            raise _TooLarge("request too large for the backup model") from exc
        raise RuntimeError(f"The backup model could not be reached: {type(exc).__name__}.") from exc


CORE_TOOLS = ("ask_user", "approval_card", "read_page_text", "navigate_browser", "take_screenshot", "click_screen_target",
              "type_text", "perform_actions", "search_local_files", "open_local_file", "create_routine", "list_routines",
              "web_search", "read_file", "list_files", "get_clipboard_text")


def _tools(user_text: str = "", limit: int = 24, desc: int = 220) -> list[dict[str, Any]]:
    """Free backup tiers have small request limits, so send only the most relevant tools, briefly described."""
    words = {w for w in re.findall(r"[a-z]{3,}", user_text.lower())}
    decls = list(_agent().TOOL_DECLARATIONS)

    def score(item: dict[str, Any]) -> float:
        text = (item["name"].replace("_", " ") + " " + (item.get("description") or "")[:300]).lower()
        hit = sum(1 for w in words if w in text)
        return hit + (2 if item["name"] in CORE_TOOLS else 0) + (3 if any(w in item["name"] for w in words) else 0)

    picked = sorted(decls, key=score, reverse=True)[:limit]
    return [{"type": "function", "function": {
        "name": item["name"],
        "description": (item.get("description") or "")[:desc],
        "parameters": item.get("parameters") or {"type": "object", "properties": {}},
    }} for item in picked]


class _TooLarge(RuntimeError):
    pass


def run(user_text: str, *, on_event: Callable[[dict[str, Any]], None] | None = None,
        max_rounds: int = 40) -> str:
    """Run the tool loop on the backup model. Same tools and safety checks as Gemini."""
    agent = _agent()
    emit = on_event or (lambda e: None)
    emit({"event": "model_switch", "model": f"backup:{model_name()}"})
    prompt = agent._scrub(agent.system_prompt())
    sizes = [(24, 220, 6000), (12, 160, 3000), (6, 120, 1500)]   # shrink until the free tier accepts it
    level = 0
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": prompt[:sizes[0][2]]},
        {"role": "user", "content": agent._scrub(user_text)},
    ]
    tools = _tools(user_text, *sizes[0][:2])
    for _ in range(max_rounds):
        try:
            data = _post({"model": model_name(), "messages": messages, "tools": tools})
        except _TooLarge:
            if level >= len(sizes) - 1:
                raise RuntimeError("The backup model could not take this request (too large for its free tier).")
            level += 1
            tools = _tools(user_text, *sizes[level][:2])
            messages[0]["content"] = prompt[:sizes[level][2]]
            for m in messages:
                if m.get("role") == "tool":
                    m["content"] = m["content"][:2000]
            continue
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
            emit({"event": "tool_end", "name": name, "ok": bool(result.get("ok", True)),
                  "path": agent._undo_path(result) if result.get("ok") else ""})
            public = {k: v for k, v in result.items() if not str(k).startswith("_")}
            messages.append({"role": "tool", "tool_call_id": call.get("id") or name,
                             "content": agent._scrub(json.dumps(public, default=str))[:4000]})
    return f"Stopped after {max_rounds} tool rounds on the backup model. Ask me to continue."
