"""1.4.15: message Ped Bot while it works (like Grok Bot).

While a task runs, new messages in that chat do not wait and do not restart it. A light
responder replies at once from the task's live state (task, current step, steps done), and
the message is handed to the running task, which reads it before its next step:
add instructions, change the plan, answer its question - or stop it.
"""

from __future__ import annotations

import re
import threading
import time
from typing import Any, Callable

_lock = threading.Lock()
_live: dict[str, dict[str, Any]] = {}
_inbox: dict[str, list[str]] = {}
_local = threading.local()
responder_override: Callable[[str, dict[str, Any]], str] | None = None
STOP_WORDS = re.compile(r"^\s*(stop|cancel|abort|halt|quit|never ?mind|stop (it|that|the task|now)|forget it)\b[\s.!]*$", re.I)
STATUS_WORDS = re.compile(r"\b(status|progress|how('?s| is) it going|where are you|what are you doing|done yet|eta|how long)\b", re.I)


def begin(session: str, text: str) -> None:
    with _lock:
        _live[session] = {"task": text, "started": time.time(), "step": "Starting…", "done": [], "plan": []}
        _inbox.pop(session, None)
    _local.session = session


def end(session: str) -> None:
    with _lock:
        _live.pop(session, None)
        _inbox.pop(session, None)
    if getattr(_local, "session", None) == session:
        _local.session = None


def running(session: str) -> bool:
    with _lock:
        return session in _live


def note(session: str, ev: dict[str, Any]) -> None:
    """Keep the live state from the task's own events."""
    kind = ev.get("event")
    with _lock:
        st = _live.get(session)
        if st is None:
            return
        if kind == "step" and ev.get("label"):
            st["step"] = str(ev["label"])[:200]
        elif kind == "tool_start":
            st["step"] = "Running " + str(ev.get("name") or "a tool").replace("_", " ")
        elif kind == "tool_end":
            st["done"].append(("✓ " if ev.get("ok") else "✗ ") + str(ev.get("name") or "").replace("_", " "))
            del st["done"][:-12]
        elif kind == "plan":
            st["plan"] = [f"{s.get('number')}. {s.get('text')} [{s.get('status')}]" for s in (ev.get("steps") or [])][:12]


def snapshot(session: str) -> dict[str, Any]:
    with _lock:
        st = dict(_live.get(session) or {})
    if st:
        st["elapsed"] = int(time.time() - float(st.get("started") or time.time()))
    return st


def add(session: str, text: str) -> None:
    with _lock:
        _inbox.setdefault(session, []).append(text)


def take(session: str | None = None) -> list[str]:
    """Messages for the running task in this thread's chat (the agent calls this between steps)."""
    sid = session or getattr(_local, "session", None)
    if not sid:
        return []
    with _lock:
        return _inbox.pop(sid, [])


def kind_of(text: str) -> str:
    if STOP_WORDS.match(text or ""):
        return "stop"
    if STATUS_WORDS.search(text or "") and len(text) < 80:
        return "status"
    return "steer"


def _template(text: str, st: dict[str, Any], kind: str) -> str:
    step = st.get("step") or "working"
    mins = int(st.get("elapsed", 0)) // 60
    took = f"{mins} min in" if mins else f"{int(st.get('elapsed', 0))} s in"
    if kind == "stop":
        return "Stopping the task now."
    if kind == "status":
        done = ", ".join(st.get("done", [])[-3:]) or "nothing finished yet"
        return f"Still on it ({took}). Now: {step}. Done so far: {done}."
    return f"Got it - I'll work that in from the next step without starting over. Right now: {step}."


def respond(session: str, text: str, kind: str) -> str:
    """A quick reply from the live state. Uses a small model call with a 6 s cap, else a template."""
    st = snapshot(session)
    if responder_override is not None:
        return responder_override(text, st)
    if kind == "stop":
        return _template(text, st, kind)
    try:
        import agent_core
        from google import genai
        from google.genai import types

        keys = agent_core.gemini_api_keys()
        if not keys:
            return _template(text, st, kind)
        client = agent_core._gemini_client(genai, keys[0])
        state = (f"Task: {st.get('task', '')[:300]}\nRunning for: {st.get('elapsed', 0)} s\nCurrent step: {st.get('step')}\n"
                 f"Finished steps: {'; '.join(st.get('done', [])[-8:]) or 'none yet'}\nPlan: {'; '.join(st.get('plan', [])) or 'none'}")
        system = ("You are Ped Bot, replying to Pedro while you are in the middle of a task on his PC. "
                  "Answer in one or two short sentences using only the live state below. If he adds or changes "
                  "instructions, confirm you will apply them from the next step without restarting. Never claim the "
                  "task is finished. No tools.\n\nLIVE STATE\n" + state)
        cfg = types.GenerateContentConfig(system_instruction=system, temperature=0.3, max_output_tokens=120,
                                          thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.MINIMAL))
        box: dict[str, Any] = {}

        def call() -> None:
            for model in [m for m in agent_core.model_candidates(None) if "lite" in m][:2]:
                try:
                    r = client.models.generate_content(model=model, contents=text, config=cfg)
                    box["text"] = (r.text or "").strip()
                    return
                except Exception:
                    continue

        t = threading.Thread(target=call, daemon=True)
        t.start()
        t.join(6.0)
        if box.get("text"):
            return box["text"]
    except Exception:
        pass
    return _template(text, st, kind)


STEER_NOTE = ("[Pedro sent this while you are working. Apply it from your next step on; do not redo finished "
              "steps or restart. If it changes the plan, update the plan. If it answers your question, use it.]\n")


def pending(session: str | None = None) -> bool:
    sid = session or getattr(_local, "session", None)
    with _lock:
        return bool(sid and _inbox.get(sid))
