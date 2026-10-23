"""1.4.15 proactive check-ins: Ped Bot messages Pedro on its own, briefly and rarely.

- Morning summary at about 9 AM: what ran overnight, results, and anything that needs him.
- Heads-up when an action waits for his approval or a task/routine fails (urgent).
- End-of-task report for long tasks (over 2 minutes).
- An occasional nudge, e.g. a routine that keeps failing.

Messages go to the "Check-ins" chat (PC and phone see it through the shared history) and as a
notification. At most `per_day` non-urgent messages a day (Settings: Low 2, Normal 4, High 6).
Quiet hours 23:00-08:00 (PC local time, IST): only urgent items. Nothing here sends anything
outside the app.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, Callable

SESSION = "checkins"
FREQ = {"low": 2, "normal": 4, "high": 6}
DEFAULTS = {"enabled": True, "frequency": "normal", "morning_hour": 9, "quiet_start": 23, "quiet_end": 8}
LONG_TASK_SECONDS = 120
_lock = threading.Lock()
now_override: Callable[[], float] | None = None
poster: Callable[[str, str], Any] | None = None   # tests


def _now() -> float:
    return now_override() if now_override is not None else time.time()


def _file(name: str) -> Path:
    import agent_config
    folder = agent_config.storage_dir()
    folder.mkdir(parents=True, exist_ok=True)
    return folder / name


def settings() -> dict[str, Any]:
    try:
        data = json.loads(_file("checkins.json").read_text(encoding="utf-8"))
    except Exception:
        data = {}
    out = {**DEFAULTS, **{k: v for k, v in data.items() if k in DEFAULTS}}
    if out["frequency"] not in FREQ:
        out["frequency"] = "normal"
    out["per_day"] = FREQ[out["frequency"]]
    return out


def save_settings(**changes: Any) -> dict[str, Any]:
    cur = settings()
    if "enabled" in changes:
        cur["enabled"] = bool(changes["enabled"])
    if str(changes.get("frequency") or "") in FREQ:
        cur["frequency"] = str(changes["frequency"])
    _file("checkins.json").write_text(json.dumps({k: cur[k] for k in DEFAULTS}), encoding="utf-8")
    return settings()


def _state() -> dict[str, Any]:
    try:
        return json.loads(_file("checkins_state.json").read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_state(st: dict[str, Any]) -> None:
    _file("checkins_state.json").write_text(json.dumps(st), encoding="utf-8")


def quiet(ts: float | None = None) -> bool:
    s = settings()
    h = time.localtime(ts if ts is not None else _now()).tm_hour
    a, b = int(s["quiet_start"]), int(s["quiet_end"])
    return (h >= a or h < b) if a > b else (a <= h < b)


def _day(ts: float) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(ts))


def post(kind: str, text: str, *, urgent: bool = False, key: str = "") -> bool:
    """Send one check-in if the rules allow it. Returns True when it went out."""
    s = settings()
    if not s["enabled"]:
        return False
    now = _now()
    with _lock:
        st = _state()
        today = _day(now)
        if st.get("day") != today:
            st = {"day": today, "count": 0, "keys": [], "morning": st.get("morning", "")}
        if key and key in st.get("keys", []):
            return False
        if not urgent:
            if quiet(now) or int(st.get("count", 0)) >= int(s["per_day"]):
                return False
            st["count"] = int(st.get("count", 0)) + 1
        if key:
            st.setdefault("keys", []).append(key)
            st["keys"] = st["keys"][-200:]
        _save_state(st)
    msg = text.strip()
    if poster is not None:
        poster(kind, msg)
        return True
    try:
        import chat_store
        chat_store.add(SESSION, "assistant", msg)
        try:
            chat_store.rename_session(SESSION, "Check-ins")
        except Exception:
            pass
        import live_sync
        live_sync.notify("changed", what="checkins")
    except Exception:
        pass
    try:
        import background
        background.notify("Ped Bot", msg.splitlines()[0][:200])
    except Exception:
        pass
    return True


# ---- sources ------------------------------------------------------------------------------
def morning_summary(since: float) -> str:
    lines: list[str] = []
    try:
        import routines
        feed = routines.feed(since)
    except Exception:
        feed = []
    ok = [f for f in feed if f.get("status") == "ok"]
    bad = [f for f in feed if f.get("status") not in ("ok",)]
    if feed:
        lines.append(f"Overnight: {len(feed)} routine run(s), {len(ok)} OK" + (f", {len(bad)} with problems." if bad else "."))
        for f in bad[:3]:
            lines.append(f"- {f.get('routine')}: {f.get('status')}. {str(f.get('text') or '')[:120]}")
    else:
        lines.append("Nothing ran overnight.")
    try:
        import background
        left = background.unfinished()
        if left:
            lines.append(f"{len(left)} task(s) were not finished: " + "; ".join(str(t.get('text') or '')[:60] for t in left[:3]))
    except Exception:
        pass
    waiting = _waiting()
    if waiting:
        lines.append("Waiting for your OK: " + "; ".join(sorted(waiting)[:3]))
    return "Good morning, Pedro. " + "\n".join(lines)


def _waiting() -> set[str]:
    try:
        import confirm_action
        return {w for w in confirm_action.waiting_labels() if w}
    except Exception:
        return set()


def task_finished(session: str, text: str, reply: str, seconds: float, failed: bool = False) -> None:
    """Called by the chat app when a turn ends. Long tasks get a short report; failures a heads-up."""
    if session == SESSION:
        return
    first = " ".join(str(reply or "").split())[:180]
    task = " ".join(str(text or "").split())[:80]
    if failed:
        post("failed", f"Heads-up: a task failed: \"{task}\". {first}", urgent=True, key=f"fail:{session}:{int(_now())//600}")
    elif seconds >= LONG_TASK_SECONDS:
        post("done", f"Done ({int(seconds // 60)} min): \"{task}\". {first}", key=f"done:{session}:{int(_now())//60}")


def tick() -> list[str]:
    """One pass of the scheduler (every minute)."""
    out: list[str] = []
    s = settings()
    if not s["enabled"]:
        return out
    now = _now()
    lt = time.localtime(now)
    st = _state()
    today = _day(now)
    if lt.tm_hour >= int(s["morning_hour"]) and lt.tm_hour < 12 and st.get("morning") != today:
        since = float(st.get("morning_ts") or (now - 14 * 3600))
        if post("morning", morning_summary(since), key=f"morning:{today}"):
            st = _state()
            st["morning"], st["morning_ts"] = today, now
            _save_state(st)
            out.append("morning")
    seen = _seen_waiting(now)
    for label in sorted(l for l, first in seen.items() if now - first >= 120):   # unanswered for 2+ minutes
        if post("approval", f"Heads-up: waiting for your OK to {label}. Open the chat to Approve or Deny.",
                urgent=True, key=f"approve:{label}"):
            out.append("approval")
    try:
        import routines
        feed = routines.feed(now - 24 * 3600)
    except Exception:
        feed = []
    for f in feed:
        if f.get("status") == "failed" and post("failed", f"Heads-up: routine '{f.get('routine')}' failed. {str(f.get('text') or '')[:140]}",
                                                urgent=True, key=f"rfail:{f.get('routine')}:{int(f.get('t') or 0)}"):
            out.append("routine_failed")
    names: dict[str, int] = {}
    for f in feed:
        if f.get("status") != "ok":
            names[str(f.get("routine"))] = names.get(str(f.get("routine")), 0) + 1
    for name, n in names.items():
        if n >= 2 and post("nudge", f"Routine '{name}' had problems {n} times today. Want me to look at it or pause it?",
                           key=f"nudge:{name}:{today}"):
            out.append("nudge")
    return out


_first_seen: dict[str, float] = {}


def _seen_waiting(now: float) -> dict[str, float]:
    cur = _waiting()
    for gone in [k for k in _first_seen if k not in cur]:
        _first_seen.pop(gone, None)
    for label in cur:
        _first_seen.setdefault(label, now)
    return dict(_first_seen)


_thread: threading.Thread | None = None


def start(every: float = 60.0) -> None:
    global _thread
    if _thread is not None:
        return

    def loop() -> None:
        while True:
            try:
                tick()
            except Exception:
                pass
            time.sleep(every)

    _thread = threading.Thread(target=loop, name="checkins", daemon=True)
    _thread.start()
