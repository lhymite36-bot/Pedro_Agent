"""Backup cloud models for when Gemini is busy or out of free requests.

Groq is used when Gemini is busy (503 / high demand), not for a daily quota error.
OpenRouter, Cerebras, and NVIDIA NIM are used, in that order, when their keys are
saved and the current provider cannot answer. Nothing is sent unless that key is set.
Tests set transport_override.
"""

from __future__ import annotations

import json
import re
import os
import urllib.request
from typing import Any, Callable

DEFAULT_URL = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_MODEL = "openai/gpt-oss-120b"   # llama-3.3-70b-versatile was retired on Groq
_TIMEOUT = 15  # 1.4.15: fail over fast instead of hanging 90 s
transport_override: Callable[[dict[str, Any]], dict[str, Any]] | None = None
providers_override: list[dict[str, Any]] | None = None

# quota False: Groq stays off the daily-quota path. The others are tried after Gemini keys.
PROVIDERS: tuple[dict[str, Any], ...] = (
    {"id": "groq", "env": "GROQ_API_KEY", "url": DEFAULT_URL, "model": DEFAULT_MODEL,
     "model_env": "BACKUP_MODEL", "quota": False},
    {"id": "openrouter", "env": "OPENROUTER_API_KEY", "url": "https://openrouter.ai/api/v1/chat/completions",
     "model": "openrouter/free", "model_env": "OPENROUTER_MODEL", "quota": True},
    {"id": "cerebras", "env": "CEREBRAS_API_KEY", "url": "https://api.cerebras.ai/v1/chat/completions",
     "model": "qwen-3.8-27b", "model_env": "CEREBRAS_MODEL", "quota": True},
    # 1.4.18: the PC's own Ollama (free, local) takes work when the cloud models are at their limits.
    {"id": "ollama", "env": "OLLAMA_MODEL", "url": "http://127.0.0.1:11434/v1/chat/completions",
     "model": "qwen2.5:7b", "model_env": "OLLAMA_MODEL", "quota": False, "local": True},
    {"id": "nvidia", "env": "NVIDIA_API_KEY", "url": "https://integrate.api.nvidia.com/v1/chat/completions",
     "model": "openai/gpt-oss-20b", "model_env": "NVIDIA_MODEL", "quota": True},
)

NO_BACKUP_MESSAGE = (
    "All Gemini models are busy right now (Google says 503 / high demand), and no backup "
    "model is set up, so I stopped. Your progress is kept: ask me to continue in a few "
    "minutes. To keep working when Gemini is busy or out of free requests, add another "
    "Gemini key, or a free OpenRouter, Cerebras, NVIDIA NIM, or Groq key, in Settings."
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


def _provider_model(provider: dict[str, Any]) -> str:
    chosen = os.environ.get(str(provider.get("model_env") or ""), "").strip()
    if provider.get("local"):
        try:
            import local_llm
            return local_llm.resolve_model(chosen or str(provider["model"]))
        except Exception:
            pass
    return chosen or str(provider["model"])


def _provider_url(provider: dict[str, Any]) -> str:
    if provider["id"] == "groq":
        return os.environ.get("BACKUP_MODEL_URL", "").strip() or str(provider["url"])
    return str(provider["url"])


def providers_for(kind: str) -> list[dict[str, Any]]:
    """Providers that have a saved key. Daily quota never selects Groq."""
    if providers_override is not None:
        rows = list(providers_override)
    else:
        rows = []
        for item in PROVIDERS:
            if item["id"] == "groq" and transport_override is not None and kind != "quota":
                rows.append(item)
                continue
            if os.environ.get(str(item["env"]), "").strip():
                rows.append(item)
    if kind == "quota":
        return [item for item in rows if item.get("quota")]
    return rows


class _HttpStatus(Exception):
    """A non-2xx answer from the pooled connection (same handling as urllib's HTTPError)."""

    def __init__(self, code: int, body: bytes, retry_after: float = 0.0) -> None:
        super().__init__(f"HTTP {code}")
        self.code = code
        self._body = body
        self.retry_after = retry_after

    def read(self) -> bytes:
        return self._body


# 1.4.17: keep the HTTPS connection to the backup model open between steps (saves the TLS
# handshake, ~0.2-0.5 s a round on a home connection). One idle connection per host, reused.
import http.client
import threading
import urllib.parse

_POOL: dict[str, list[http.client.HTTPSConnection]] = {}
_POOL_LOCK = threading.Lock()
_LAST_RETRY: dict[int, float] = {}


def _pooled_post(url: str, data: bytes, headers: dict[str, str], timeout: float) -> tuple[int, bytes]:
    parts = urllib.parse.urlsplit(url)
    host = parts.netloc
    path = parts.path + (("?" + parts.query) if parts.query else "")
    for attempt in range(2):
        with _POOL_LOCK:
            idle = _POOL.setdefault(host, [])
            conn = idle.pop() if idle else None
        fresh = conn is None
        if conn is None:
            conn = (http.client.HTTPConnection(host, timeout=timeout) if parts.scheme == "http"
                    else http.client.HTTPSConnection(host, timeout=timeout))
        try:
            conn.timeout = timeout
            if conn.sock is not None:
                conn.sock.settimeout(timeout)
            conn.request("POST", path, body=data, headers={**headers, "Connection": "keep-alive"})
            resp = conn.getresponse()
            raw = resp.read()
            try:
                _LAST_RETRY[threading.get_ident()] = float(resp.getheader("retry-after") or 0)
            except ValueError:
                _LAST_RETRY[threading.get_ident()] = 0.0
        except (http.client.HTTPException, ConnectionError, OSError) as exc:
            conn.close()
            if fresh or attempt:   # a fresh connection failing is a real network problem
                raise
            continue   # the kept connection had gone stale: retry once on a new one
        if resp.getheader("connection", "").casefold() == "close" or resp.will_close:
            conn.close()
        else:
            with _POOL_LOCK:
                if len(_POOL.setdefault(host, [])) < 2:
                    _POOL[host].append(conn)
                else:
                    conn.close()
        return resp.status, raw
    raise ConnectionError("unreachable")


def warm(provider: dict[str, Any] | None = None) -> bool:
    """Open the TLS connection to the backup model ahead of time (no request is sent, nothing is used up)."""
    try:
        chosen = provider or (providers_for("busy") or [None])[0]
        if not chosen:
            return False
        host = urllib.parse.urlsplit(_provider_url(chosen)).netloc
        with _POOL_LOCK:
            if _POOL.get(host):
                return True
        conn = http.client.HTTPSConnection(host, timeout=10)
        conn.connect()
        with _POOL_LOCK:
            _POOL.setdefault(host, []).append(conn)
        return True
    except Exception:
        return False


def _post(body: dict[str, Any], provider: dict[str, Any] | None = None) -> dict[str, Any]:
    if transport_override is not None:
        return transport_override(body)
    chosen = provider or PROVIDERS[0]
    try:   # 1.4.18: count the call against this model's per-minute limit (waits a moment when it is full)
        import model_pool
        est = len(json.dumps(body)) // 4 + 600   # rough token estimate for the request and its answer
        if not model_pool.acquire(_pool_key(chosen), max_wait=4.0, tokens=est):
            raise _Switch(f"{chosen['id']} is at its per-minute limit")
    except ImportError:
        pass
    key = os.environ.get(str(chosen["env"]), "").strip()
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {key}",
               "User-Agent": "PedroAgent/1.4.13 (+https://github.com/lhymite36-bot/Pedro_Agent)"}  # Groq's Cloudflare blocks the urllib default (error 1010)
    if chosen["id"] == "openrouter":
        headers["X-Title"] = "Pedro Agent"
    gate = None
    if chosen.get("local"):
        headers.pop("Authorization", None)   # local Ollama needs no key
        try:   # one local answer at a time; when it is busy, use the next model instead of waiting
            import local_llm
            if not local_llm.GATE.acquire(timeout=1.0):
                raise _Switch("the local model is busy")
            gate = local_llm.GATE
        except ImportError:
            pass
    try:
        status, raw = _pooled_post(_provider_url(chosen), json.dumps(body).encode("utf-8"), headers,
                                   60 if chosen.get("local") else _TIMEOUT)
        if status >= 400:
            raise _HttpStatus(status, raw, _LAST_RETRY.get(threading.get_ident(), 0.0))
        return json.loads(raw.decode("utf-8"))
    except Exception as exc:  # never echo the key
        code = getattr(exc, "code", None)
        if code == 413:
            raise _TooLarge("request too large for the backup model") from exc
        if code == 400:
            try:
                detail = exc.read()[:2000]  # type: ignore[attr-defined]
            except Exception:
                detail = b""
            if b"tool_use_failed" in detail:   # the model wrote a bad tool call; asking again usually works
                raise _BadToolCall(f"{chosen['id']} wrote a tool call that did not match its schema") from exc
        if code == 429:   # 1.4.18: rest this model; other tasks move to the next free one
            try:
                import model_pool
                model_pool.cooldown(_pool_key(chosen), float(getattr(exc, "retry_after", 0) or 20))
            except Exception:
                pass
        if isinstance(code, int) and code >= 400:
            raise _Switch(f"{chosen['id']} returned {code}") from exc
        if isinstance(exc, (TimeoutError, OSError)):
            raise _Switch(f"{chosen['id']} unreachable") from exc
        raise RuntimeError(f"The backup model could not be reached: {type(exc).__name__}.") from exc
    finally:
        if gate is not None:
            gate.release()


CORE_TOOLS = ("ask_user", "approval_card", "read_page_text", "navigate_browser", "take_screenshot", "click_screen_target",
              "type_text", "perform_actions", "search_local_files", "open_local_file", "create_routine", "list_routines",
              "web_search", "read_file", "list_files", "pc_status", "get_clipboard_text",
              "start_background_task", "split_big_job", "task_board_status", "share_result", "read_shared")

PC_HINT = ("PC look-ups: use list_files (one call: sort newest/largest, pattern like *.pdf, limit, recursive) to list, "
           "count or find files, and pc_status for free disk space, memory or busy programs. They need no approval. "
           "Do not use run_terminal_command, search_local_files or search_files_by_time for these. Ask for independent "
           "look-ups together in one step. Answer from tool results only.\n\n")


ESSENTIAL_TOOLS = frozenset({"web_search", "list_files", "pc_status", "read_file", "ask_user"})


def _tools(user_text: str = "", limit: int = 24, desc: int = 220) -> list[dict[str, Any]]:
    """Free backup tiers have small request limits, so send only the most relevant tools, briefly described."""
    words = {w for w in re.findall(r"[a-z]{3,}", user_text.lower())}
    decls = list(_agent().TOOL_DECLARATIONS)

    def score(item: dict[str, Any]) -> float:
        text = (item["name"].replace("_", " ") + " " + (item.get("description") or "")[:300]).lower()
        hit = sum(1 for w in words if w in text)
        return hit + (2 if item["name"] in CORE_TOOLS else 0) + (3 if any(w in item["name"] for w in words) else 0)

    ranked = sorted(decls, key=score, reverse=True)
    # 1.4.18: the everyday look-ups are always offered (a long tool list once pushed web_search out)
    must = [d for d in decls if d["name"] in ESSENTIAL_TOOLS]
    picked = must + [d for d in ranked if d["name"] not in ESSENTIAL_TOOLS][: max(0, limit - len(must))]
    return [{"type": "function", "function": {
        "name": item["name"],
        "description": (item.get("description") or "")[:desc],
        "parameters": item.get("parameters") or {"type": "object", "properties": {}},
    }} for item in picked]


class _TooLarge(RuntimeError):
    pass


class _BadToolCall(RuntimeError):
    pass


BAD_CALL_HINT = ("Your last tool call did not match the tool's parameters. Call the tool again with every "
                 "parameter as the right type; use \"\" for an empty text value, never null.")


class _Switch(RuntimeError):
    """This provider cannot take the turn. Try the next saved one."""


def _request_body(provider: dict[str, Any], messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict[str, Any]:
    body: dict[str, Any] = {"model": _provider_model(provider), "messages": messages, "tools": tools}
    if provider["id"] == "cerebras":
        body["reasoning_effort"] = "none"
    return body


def _run_one(provider: dict[str, Any], user_text: str, *, on_event: Callable[[dict[str, Any]], None] | None = None,
             max_rounds: int = 40, history: list[dict[str, str]] | None = None) -> str:
    """Run the tool loop on one backup provider. Same tools and safety checks as Gemini."""
    agent = _agent()
    emit = on_event or (lambda e: None)
    emit({"event": "model_switch", "model": f"backup:{_provider_model(provider)}"})
    prompt = agent._scrub(agent.system_prompt())
    sizes = [(24, 220, 6000), (12, 160, 3000), (6, 120, 1500)]   # shrink until the free tier accepts it
    level = 0
    prompt = PC_HINT + prompt
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": prompt[:sizes[0][2]]},
        *[{"role": m["role"], "content": agent._scrub(m["content"])} for m in (history or [])][-8:],
        {"role": "user", "content": agent._scrub(user_text)},
    ]
    tools = _tools(user_text, *sizes[0][:2])
    import stop_token
    bad_calls = 0
    for _ in range(max_rounds):
        stop_token.checkpoint()   # 1.4.15: Stop / Pause between backup-model steps too
        try:
            import live_steer
            steer = live_steer.take()
        except Exception:
            steer = []
        if steer:   # messages Pedro sent while this task runs
            messages.append({"role": "user", "content": live_steer.STEER_NOTE + "\n".join(f"- {m}" for m in steer)})
            emit({"event": "step", "label": "Got your message - adjusting the task.", "name": "steer"})
        try:
            data = _post(_request_body(provider, messages, tools), provider)
        except _BadToolCall:
            bad_calls += 1
            if bad_calls > 3:
                raise _Switch(f"{provider['id']} kept writing bad tool calls")
            if messages[-1].get("content") != BAD_CALL_HINT:
                messages.append({"role": "user", "content": BAD_CALL_HINT})
            continue
        except _TooLarge:
            if level >= len(sizes) - 1:
                raise _Switch(f"{provider['id']} request too large")
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
            try:
                import live_steer
                if live_steer.pending():
                    messages.append({"role": "assistant", "content": msg.get("content") or ""})
                    continue
            except Exception:
                pass
            return str(msg.get("content") or "").strip() or "The backup model returned no text."
        messages.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": calls})
        parsed = []
        for call in calls:
            fn = call.get("function") or {}
            raw = fn.get("arguments")
            try:
                args = json.loads(raw) if isinstance(raw, str) and raw.strip() else dict(raw or {})
            except (json.JSONDecodeError, TypeError, ValueError):
                args = {}
            parsed.append((str(fn.get("name") or ""), args if isinstance(args, dict) else {}))
        try:   # 1.4.16: read-only look-ups in one step run at the same time
            pre = agent.parallel_results(parsed)
        except Exception:
            pre = {}
        for idx, call in enumerate(calls):
            name, args = parsed[idx]
            emit({"event": "tool_start", "name": name, "arguments": args})
            result = pre[idx] if idx in pre else agent._execute_logged_tool(name, args)
            emit({"event": "tool_end", "name": name, "ok": bool(result.get("ok", True)),
                  "path": agent._undo_path(result) if result.get("ok") else "",
                  "image": agent._result_image(result),
                  "video": agent._result_video(result)})
            public = {k: v for k, v in result.items() if not str(k).startswith("_")}
            messages.append({"role": "tool", "tool_call_id": call.get("id") or name,
                             "content": agent._scrub(json.dumps(public, default=str))[:4000]})
    return f"Stopped after {max_rounds} tool rounds on the backup model. Ask me to continue."


def quick_chat(system: str, messages: list[dict[str, Any]], max_tokens: int = 400) -> str | None:
    """1.4.15: one small no-tools request for simple chat on the first saved backup (Groq is very fast)."""
    for provider in providers_for("busy"):
        body = {"model": _provider_model(provider), "max_tokens": max_tokens, "temperature": 0.4,
                "messages": [{"role": "system", "content": system}, *messages]}
        if provider["id"] == "cerebras":
            body["reasoning_effort"] = "none"
        try:
            data = _post(body, provider)
        except Exception:
            continue
        text = str(((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
        if text:
            return text
    return None


def run(user_text: str, *, on_event: Callable[[dict[str, Any]], None] | None = None,
        max_rounds: int = 40) -> str:
    """Groq tool loop. A provider limit is reported without the key."""
    try:
        return _run_one(PROVIDERS[0], user_text, on_event=on_event, max_rounds=max_rounds)
    except _Switch as exc:
        raise RuntimeError(f"The backup model could not be reached: {type(exc).__name__}.") from exc


def run_chain(user_text: str, *, on_event: Callable[[dict[str, Any]], None] | None = None,
              kind: str = "quota", max_rounds: int = 40, history: list[dict[str, str]] | None = None) -> str | None:
    """Try each saved provider until one answers. None when none are saved or all decline."""
    chosen = providers_for(kind)
    if not chosen:
        return None
    rows: list[dict[str, Any]] = []
    for item in chosen:
        rows.append(item)
        if item["id"] == "groq" and transport_override is None:
            # 1.4.17: Groq limits each model separately; a second free model takes over when the first is
            # rate-limited mid-task. Look-ups it already did come from the result cache, so nothing reruns.
            rows.append({**item, "model": GROQ_SECOND_MODEL, "model_env": "BACKUP_MODEL_2"})
    try:   # 1.4.18: with several tasks running, start on the least-loaded free model
        import model_pool
        keys = [_pool_key(r) for r in rows]
        ranked = model_pool.order(keys)
        rows = [rows[keys.index(k)] for k in ranked]
    except Exception:
        pass
    for item in rows:
        try:
            return _run_one(item, user_text, on_event=on_event, max_rounds=max_rounds, history=history)
        except (_Switch, _TooLarge) as exc:
            print(f"[backup] {item['id']} ({_provider_model(item)}) could not take this turn ({exc}). "
                  "Trying the next one.", flush=True)
    return None


GROQ_SECOND_MODEL = "openai/gpt-oss-20b"


def _pool_key(provider: dict[str, Any]) -> str:
    if provider.get("id") == "groq":
        return f"groq:{_provider_model(provider)}"
    return str(provider.get("id"))


# ---------- 1.4.18: fast spoken replies ----------
VOICE_MODELS = ("openai/gpt-oss-20b", "openai/gpt-oss-120b")   # the free Groq models on this key (llama-3.1-8b is gone)


def stream_text(messages: list[dict[str, str]], on_text: Callable[[str], None], *,
                cancel: Any = None, max_tokens: int = 300) -> str | None:
    """Stream a plain reply (no tools) from Groq, token by token. None when Groq is not usable."""
    key = os.environ.get("GROQ_API_KEY", "").strip()
    if not key:
        return None
    import model_pool
    for model in VOICE_MODELS:
        pool_key = f"groq:{model}"
        if model_pool.at_limit(pool_key):
            continue
        body = {"model": model, "messages": messages, "stream": True, "max_tokens": max_tokens, "temperature": 0.6}
        if model.startswith("openai/gpt-oss"):
            body["reasoning_effort"] = "low"
            body["include_reasoning"] = False
        data = json.dumps(body).encode("utf-8")
        if not model_pool.acquire(pool_key, max_wait=0.5, tokens=len(data) // 4 + max_tokens):
            continue
        host = "api.groq.com"
        with _POOL_LOCK:
            idle = _POOL.setdefault(host, [])
            conn = idle.pop() if idle else None
        if conn is None:
            conn = http.client.HTTPSConnection(host, timeout=12)
        out: list[str] = []
        try:
            conn.request("POST", "/openai/v1/chat/completions", body=data, headers={
                "Content-Type": "application/json", "Authorization": f"Bearer {key}", "Accept": "text/event-stream",
                "User-Agent": "PedroAgent/1.4.18", "Connection": "keep-alive"})
            resp = conn.getresponse()
            if resp.status != 200:
                resp.read()
                if resp.status == 429:
                    model_pool.cooldown(pool_key, float(resp.getheader("retry-after") or 20))
                conn.close()
                continue
            while True:
                if cancel is not None and cancel.is_set():
                    conn.close()
                    return "".join(out)
                line = resp.readline()
                if not line:
                    break
                line = line.strip()
                if not line.startswith(b"data:"):
                    continue
                chunk = line[5:].strip()
                if chunk == b"[DONE]":
                    break
                try:
                    delta = json.loads(chunk)["choices"][0].get("delta", {}).get("content") or ""
                except (ValueError, KeyError, IndexError):
                    continue
                if delta:
                    out.append(delta)
                    on_text(delta)
            resp.read()
            with _POOL_LOCK:
                if len(_POOL.setdefault(host, [])) < 2 and not resp.will_close:
                    _POOL[host].append(conn)
                else:
                    conn.close()
            text = "".join(out).strip()
            if text:
                return text
        except Exception:
            try:
                conn.close()
            except Exception:
                pass
            if out:
                return "".join(out)
    return None
