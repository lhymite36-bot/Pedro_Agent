"""Answer one turn with Ollama when the request stays on this PC.

Gemini remains the default. This module runs only for a privacy phrase,
PRIVACY_MODE or LOCAL_LLM, a network_up_override of False, or after Gemini's
connection fails and Ollama is reachable. Tests set ollama_transport_override
and never open a socket.
"""

from __future__ import annotations

import json
import os
import socket
import threading
import urllib.request
from typing import Any

OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
DEFAULT_OLLAMA_MODEL = "llama3.2"
_PROBE_SECONDS = 0.3
_CHAT_TIMEOUT = 60

_PRIVACY_PHRASES = (
    "keep this private",
    "keep it private",
    "keep this offline",
    "stay offline",
    "offline",
    "local only",
    "local-only",
    "do not send this online",
    "don't send this online",
    "do not send this to gemini",
    "don't send this to gemini",
)


def _agent() -> Any:
    import agent_core

    return agent_core


_INSTALLED: dict[str, Any] = {"at": -1e9, "names": []}
_PREFERRED = ("qwen2.5:7b", "llama3.2", "llama3.1", "qwen2.5", "phi3:mini")


def installed_models(refresh: bool = False) -> list[str]:
    """Models Ollama has pulled (cached a minute; empty when Ollama is not answering)."""
    import time
    now = time.monotonic()
    if not refresh and now - _INSTALLED["at"] < 60:
        return list(_INSTALLED["names"])
    names: list[str] = []
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=1.5) as response:
            names = [str(m.get("name") or "") for m in json.loads(response.read().decode("utf-8")).get("models", [])]
    except Exception:
        names = []
    _INSTALLED.update(at=now, names=[n for n in names if n])
    return list(_INSTALLED["names"])


def resolve_model(configured: str) -> str:
    """1.4.18: OLLAMA_MODEL=llama3.2 was not pulled on Pedro's PC, so every local answer failed (HTTP 404)
    and showed "Ollama is not running". Use the configured model when it is installed, else the best installed one."""
    names = installed_models()
    if not names:
        return configured
    def same(a: str, b: str) -> bool:
        return a == b or a == b + ":latest" or a.split(":")[0] == b
    if any(same(n, configured) for n in names):
        return configured
    for want in _PREFERRED:
        for n in names:
            if same(n, want):
                return n
    usable = [n for n in names if not any(k in n for k in ("moondream", "embed", "coder", "llava"))]
    return (usable or names)[0]


def model_name() -> str:
    try:   # 1.5.4: the model Pedro picked in Settings wins
        import model_mode
        configured = model_mode.chosen_model()
    except Exception:
        configured = ""
    configured = configured or os.environ.get("OLLAMA_MODEL", "").strip() or DEFAULT_OLLAMA_MODEL
    agent = _agent()
    if getattr(agent, "ollama_transport_override", None) is not None:
        return configured
    return resolve_model(configured)


def use_local_first(user_text: str) -> bool:
    """True when this turn must not call Gemini. Does not probe the network."""
    if os.environ.get("PRIVACY_MODE", "").strip() == "1":
        return True
    if os.environ.get("LOCAL_LLM", "").strip() == "1":
        return True
    agent = _agent()
    if agent.network_up_override is False:
        return True
    if getattr(agent, "ollama_transport_override", None) is None:
        try:   # 1.5.4: Offline mode, or Auto with no internet
            import model_mode
            if model_mode.use_local():
                return True
        except Exception:
            pass
    folded = " ".join((user_text or "").casefold().split())
    return any(phrase in folded for phrase in _PRIVACY_PHRASES)


def ollama_reachable() -> bool:
    """True when a test transport is installed, or when localhost:11434 answers."""
    agent = _agent()
    if agent.ollama_transport_override is not None:
        return True
    if agent.ollama_reachable_override is not None:
        return bool(agent.ollama_reachable_override)
    try:
        with socket.create_connection(("127.0.0.1", 11434), _PROBE_SECONDS):
            return True
    except OSError:
        return False


def _scrubbed(payload: dict[str, Any]) -> dict[str, Any]:
    agent = _agent()
    raw = agent._scrub(json.dumps(payload, default=str))
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise RuntimeError("Ollama payload could not be prepared.")
    return parsed


# 1.4.18: the PC runs one local model answer at a time; parallel tasks queue here instead of timing out.
GATE = threading.BoundedSemaphore(1)


def _post(payload: dict[str, Any]) -> dict[str, Any]:
    agent = _agent()
    body = _scrubbed(payload)
    override = agent.ollama_transport_override
    if override is not None:
        result = override(body)
        if not isinstance(result, dict):
            raise RuntimeError("Ollama returned an unexpected response.")
        return result
    data = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        OLLAMA_URL,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    if not GATE.acquire(timeout=_CHAT_TIMEOUT):
        raise RuntimeError("The local model is busy with another task. Answer without it.")
    try:
        with urllib.request.urlopen(request, timeout=_CHAT_TIMEOUT) as response:
            parsed = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        if isinstance(exc, (TimeoutError, socket.timeout)) or "timed out" in str(exc):
            raise RuntimeError("The local model was too slow to answer. Answer without it.") from exc
        raise RuntimeError(
            "Ollama is not running on this PC. Start Ollama, then ask again."
        ) from exc
    finally:
        GATE.release()
    if not isinstance(parsed, dict):
        raise RuntimeError("Ollama returned an unexpected response.")
    return parsed


def _post_stream(payload: dict[str, Any], on_chunk: Any) -> dict[str, Any]:
    """1.5.4: stream tokens; returns the merged message like a non-stream reply."""
    agent = _agent()
    if agent.ollama_transport_override is not None:
        return _post(payload)
    body = _scrubbed({**payload, "stream": True})
    request = urllib.request.Request(OLLAMA_URL, data=json.dumps(body).encode("utf-8"),
                                     headers={"Content-Type": "application/json"}, method="POST")
    if not GATE.acquire(timeout=_CHAT_TIMEOUT):
        raise RuntimeError("The local model is busy with another task. Try again in a moment.")
    content, calls = [], []
    try:
        with urllib.request.urlopen(request, timeout=_CHAT_TIMEOUT * 3) as response:
            for raw in response:
                line = raw.decode("utf-8").strip()
                if not line:
                    continue
                part = json.loads(line)
                if part.get("error"):
                    raise RuntimeError(str(part["error"])[:300])
                msg = part.get("message") or {}
                piece = str(msg.get("content") or "")
                if piece:
                    content.append(piece)
                    if on_chunk is not None:
                        try:
                            on_chunk(piece)
                        except Exception:
                            pass
                calls.extend(msg.get("tool_calls") or [])
                if part.get("done"):
                    break
    except RuntimeError:
        raise
    except Exception as exc:
        if isinstance(exc, (TimeoutError, socket.timeout)) or "timed out" in str(exc):
            raise RuntimeError("The local model was too slow to answer.") from exc
        raise RuntimeError("Ollama is not running on this PC. Start Ollama, then ask again.") from exc
    finally:
        GATE.release()
    return {"message": {"content": "".join(content), "tool_calls": calls}}


LOCAL_PROMPT = """You are Ped Bot, Pedro's assistant on his Windows PC, answering with a local model (no internet).
Be brief and friendly. Use the tools to act on the PC (files, apps, windows, terminal, screenshots) when he asks.
Never claim you did something unless a tool returned ok. Ask before deleting anything.
You have NO internet: if he asks for web search, Gmail/email, YouTube, websites, downloads or anything online,
say plainly that it needs internet and that you're offline, and offer what you can do on the PC instead."""


def _history_messages(history: Any, limit: int = 6) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in list(history or [])[-limit * 3:]:
        role = getattr(item, "role", None) or (item.get("role") if isinstance(item, dict) else None)
        parts = getattr(item, "parts", None) or (item.get("parts") if isinstance(item, dict) else None) or []
        text = " ".join(str(getattr(p, "text", "") or (p.get("text") if isinstance(p, dict) else "") or "") for p in parts).strip()
        if text and role in ("user", "model", "assistant"):
            out.append({"role": "user" if role == "user" else "assistant", "content": text[:1500]})
    return out[-limit:]


def _tool_schema() -> list[dict[str, Any]]:
    agent = _agent()
    tools: list[dict[str, Any]] = []
    try:
        import model_mode
        only = set(model_mode.OFFLINE_TOOLS) if model_mode.use_local() else None
    except Exception:
        only = None
    for item in agent.TOOL_DECLARATIONS:
        if only is not None and item["name"] not in only:
            continue
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": item["name"],
                    "description": item.get("description") or "",
                    "parameters": item.get("parameters") or {"type": "object", "properties": {}},
                },
            }
        )
    return tools


def _arguments(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        if isinstance(parsed, dict):
            return parsed
    return {}


def _public_result(result: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in result.items() if not str(key).startswith("_")}


def _message_text(data: dict[str, Any]) -> tuple[str, list[Any]]:
    if data.get("error") and "message" not in data:
        raise RuntimeError(_agent()._scrub(str(data["error"]))[:300])
    message = data.get("message")
    if not isinstance(message, dict):
        raise RuntimeError("Ollama returned an unexpected response.")
    content = str(message.get("content") or "").strip()
    calls = message.get("tool_calls") or []
    if not isinstance(calls, list):
        calls = []
    return content, calls


def rewrite_with_ollama(source: str, error: str) -> str:
    """Ask the local model for replacement source. No Gemini call."""
    if not ollama_reachable():
        raise RuntimeError("Ollama is not running, so the script was not rewritten.")
    agent = _agent()
    import self_heal

    payload = {
        "model": model_name(),
        "stream": False,
        "messages": [
            {
                "role": "system",
                "content": "Return only the replacement Python source. Do not explain it.",
            },
            {
                "role": "user",
                "content": agent._scrub(
                    f"ERROR:\n{error[:4000]}\n\nSCRIPT:\n{source[:20000]}"
                ),
            },
        ],
    }
    content, _calls = _message_text(_post(payload))
    text = self_heal.strip_code_fence(content)
    if not text.strip():
        raise RuntimeError("The rewriter returned an empty script.")
    return text


def local_llm_fallback(
    user_text: str,
    *,
    voice: bool = False,
    on_sentence: Any = None,
    on_text: Any = None,
    history: Any = None,
) -> str:
    """Run the tool loop on Ollama. Caller must skip Gemini before this."""
    del voice
    agent = _agent()
    agent._turn_is_local = True
    print(f"[local] Answering on this PC with Ollama ({model_name()}).", flush=True)
    compact = False
    try:
        import model_mode
        compact = agent.ollama_transport_override is None and model_mode.use_local()
        if compact:
            refusal = model_mode.needs_internet_reply(user_text)
            if refusal:
                return refusal
            model_mode.ensure_ollama()
            model_mode.note_answer("local", model_name())
    except Exception:
        pass
    if not ollama_reachable():
        return (
            "Ollama is not running on this PC. Start Ollama, then ask again. "
            "This request was not sent online."
        )
    try:
        system = LOCAL_PROMPT if compact else agent.system_prompt()
        messages: list[dict[str, Any]] = [{"role": "system", "content": agent._scrub(system)}]
        if compact:
            messages += [{"role": m["role"], "content": agent._scrub(m["content"])} for m in _history_messages(history)]
        messages.append({"role": "user", "content": agent._scrub(user_text)})
        tools = _tool_schema()
        for _round in range(agent.MAX_TOOL_ROUNDS):
            payload = {"model": model_name(), "stream": False, "messages": messages, "tools": tools,
                       "keep_alive": "30m", "options": {"num_ctx": 8192}}
            if compact:
                content, calls = _message_text(_post_stream(payload, on_text))
            else:
                content, calls = _message_text(_post(payload))
            if not calls:
                text = content or "Ollama returned no text."
                if on_sentence is not None and text:
                    on_sentence(text)
                return text
            messages.append({"role": "assistant", "content": content, "tool_calls": calls})
            for call in calls:
                function = call.get("function") if isinstance(call, dict) else None
                function = function if isinstance(function, dict) else {}
                name = str(function.get("name") or "")
                arguments = _arguments(function.get("arguments"))
                result = agent._execute_logged_tool(name, arguments)
                messages.append(
                    {
                        "role": "tool",
                        "name": name,
                        "content": agent._scrub(
                            json.dumps(_public_result(result), default=str)
                        ),
                    }
                )
        return (
            "Stopped after "
            f"{agent.MAX_TOOL_ROUNDS} tool rounds. Ask for the next step on its own."
        )
    except AssertionError:
        raise
    except Exception as exc:
        return agent._scrub(str(exc))[:500]
