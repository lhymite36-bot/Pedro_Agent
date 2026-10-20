"""1.4.10: Routines. Bots create scheduled prompts from plain words ("every day at 7 PM check Wingz",
"tomorrow 9 AM remind me ..."). The scheduler runs each one at its time (PC local time = IST) as a normal
chat turn in the routine's chat, so safety rules and Approve/Deny cards still apply.
The 7 PM Wingz check is a built-in routine in the same list.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent / "workspace"
_DEFAULT_ROOT = ROOT
_lock = threading.RLock()
DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
WINGZ_ID = "builtin-wingz"
runner: Callable[[dict[str, Any]], str] | None = None   # set by the chat app: runs one routine turn
now_override: Callable[[], float] | None = None        # tests


def _now() -> float:
    return now_override() if now_override is not None else time.time()


def _path() -> Path:
    base = ROOT
    if ROOT == _DEFAULT_ROOT and os.environ.get("STORAGE_DIR"):
        base = Path(os.environ["STORAGE_DIR"])
    base.mkdir(parents=True, exist_ok=True)
    return base / "routines.json"


def _load() -> dict[str, Any]:
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) and "routines" in data else {"routines": [], "feed": [], "seeded": False}
    except Exception:
        return {"routines": [], "feed": [], "seeded": False}


def _save(data: dict[str, Any]) -> None:
    data["feed"] = data.get("feed", [])[-50:]
    _path().write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")


# ---------- understanding "when" ----------
def _hm(text: str) -> tuple[int, int] | None:
    t = text.lower().replace(".", "")
    if re.search(r"\bnoon\b", t):
        return 12, 0
    if re.search(r"\bmidnight\b", t):
        return 0, 0
    m = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", t)
    if m:
        h, mi = int(m.group(1)) % 12, int(m.group(2) or 0)
        return (h + 12 if m.group(3) == "pm" else h), mi
    m = re.search(r"\b(\d{1,2}):(\d{2})\b", t)
    if m and int(m.group(1)) < 24:
        return int(m.group(1)), int(m.group(2))
    m = re.search(r"\bat (\d{1,2})\b", t)
    if m and int(m.group(1)) < 24:
        return int(m.group(1)), 0
    for word, hm in (("morning", (9, 0)), ("evening", (19, 0)), ("night", (21, 0)), ("afternoon", (14, 0))):
        if word in t:
            return hm
    return None


def parse_when(text: str, now: float | None = None) -> dict[str, Any]:
    """Plain words -> schedule. Raises ValueError when it can't tell."""
    now = _now() if now is None else now
    t = " ".join((text or "").lower().split())
    if not t:
        raise ValueError("Say when, e.g. 'every day at 7 PM' or 'tomorrow 9 AM'.")
    m = re.search(r"\bevery (\d+)\s*(min|minute|minutes|hour|hours|hr|hrs)\b", t) or re.search(r"\bevery (hour|minute)\b", t)
    if m:
        if m.group(1) in {"hour", "minute"}:
            n, unit = 1, m.group(1)
        else:
            n, unit = int(m.group(1)), m.group(2)
        mins = n * (60 if unit.startswith("h") else 1)
        if mins < 5:
            raise ValueError("The shortest repeat is every 5 minutes.")
        return {"kind": "every", "minutes": mins}
    m = re.search(r"\bin (\d+)\s*(min|minute|minutes|hour|hours|hr|hrs)\b", t)
    if m:
        secs = int(m.group(1)) * (3600 if m.group(2).startswith("h") else 60)
        return {"kind": "once", "at": time.strftime("%Y-%m-%d %H:%M", time.localtime(now + secs))}
    hm = _hm(t)
    days: list[int] = []
    if "weekday" in t:
        days = [0, 1, 2, 3, 4]
    elif "weekend" in t:
        days = [5, 6]
    else:
        days = [i for i, d in enumerate(DAYS) if re.search(rf"\b{d}[a-z]*\b", t)]
    repeat = bool(re.search(r"\b(every|each|daily|weekdays?|weekends?|(mon|tues|wednes|thurs|fri|satur|sun)days)\b", t))
    if repeat:
        if hm is None:
            raise ValueError("At what time? e.g. 'every day at 7 PM'.")
        return {"kind": "daily", "time": f"{hm[0]:02d}:{hm[1]:02d}", "days": days or list(range(7))}
    # one time
    base = time.localtime(now)
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", t)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    else:
        y, mo, d = base.tm_year, base.tm_mon, base.tm_mday
        add = 1 if "tomorrow" in t else 0
        if "day after tomorrow" in t:
            add = 2
        wd = next((i for i, dn in enumerate(DAYS) if re.search(rf"\b{dn}[a-z]*\b", t)), None)
        if wd is not None and add == 0:
            add = (wd - base.tm_wday) % 7 or 7
        if add:
            lt = time.localtime(time.mktime((y, mo, d, 12, 0, 0, 0, 0, -1)) + add * 86400)
            y, mo, d = lt.tm_year, lt.tm_mon, lt.tm_mday
    if hm is None:
        raise ValueError("At what time? e.g. 'tomorrow 9 AM'.")
    at = time.mktime((y, mo, d, hm[0], hm[1], 0, 0, 0, -1))
    if at <= now and not m and "tomorrow" not in t and "today" not in t:
        at += 86400   # "at 6 PM" said after 6 PM means tomorrow
    if at <= now:
        raise ValueError("That time has already passed.")
    return {"kind": "once", "at": time.strftime("%Y-%m-%d %H:%M", time.localtime(at))}


def describe(s: dict[str, Any]) -> str:
    if s["kind"] == "once":
        return "once on " + time.strftime("%a %d %b, %I:%M %p", time.strptime(s["at"], "%Y-%m-%d %H:%M")) + " IST"
    if s["kind"] == "every":
        m = s["minutes"]
        return f"every {m // 60} hour(s)" if m % 60 == 0 else f"every {m} minutes"
    days = s.get("days") or list(range(7))
    when = time.strftime("%I:%M %p", time.strptime(s["time"], "%H:%M"))
    d = "every day" if len(days) == 7 else ("weekdays" if days == [0, 1, 2, 3, 4] else ", ".join(DAYS[i].title() for i in days))
    return f"{d} at {when} IST"


def next_run(s: dict[str, Any], after: float, last: float = 0.0) -> float | None:
    if s["kind"] == "once":
        at = time.mktime(time.strptime(s["at"], "%Y-%m-%d %H:%M"))
        return None if last >= at else at
    if s["kind"] == "every":
        return (last or after) + s["minutes"] * 60 if last else after + s["minutes"] * 60
    h, mi = (int(x) for x in s["time"].split(":"))
    lt = time.localtime(after)
    for add in range(0, 8):
        day = time.localtime(time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 12, 0, 0, 0, 0, -1)) + add * 86400)
        cand = time.mktime((day.tm_year, day.tm_mon, day.tm_mday, h, mi, 0, 0, 0, -1))
        if cand > after and day.tm_wday in (s.get("days") or range(7)):
            return cand
    return None


def _fmt(ts: float | None) -> str:
    return time.strftime("%a %d %b %I:%M %p", time.localtime(ts)) if ts else ""


# ---------- store ----------
def _target(bot: str) -> tuple[str, str]:
    """(kind, id) for 'main', a bot name or a group name."""
    b = " ".join((bot or "").split())
    if not b or b.lower() in {"main", "pedro", "pedro_agent", "pedro agent", "me"}:
        return "main", ""
    try:
        import bots
        found = bots.get_bot(b)
        if found:
            return "bot", found["id"]
    except Exception:
        pass
    try:
        import groups
        for g in groups.list_groups():
            if b.lower() in {str(g.get("id", "")).lower(), str(g.get("name", "")).lower()}:
                return "group", g["id"]
    except Exception:
        pass
    raise ValueError(f"No bot or group called '{bot}'.")


def session_for(r: dict[str, Any]) -> str:
    if r.get("target") == "bot":
        return "bot-" + r["target_id"]
    if r.get("target") == "group":
        import groups
        return groups.SESSION_PREFIX + r["target_id"]
    return r.get("session") or ("routine-" + r["id"])


def find(name_or_id: str) -> dict[str, Any] | None:
    key = " ".join((name_or_id or "").lower().split())
    rs = _load()["routines"]
    return next((r for r in rs if r["id"] == name_or_id), None) or \
        next((r for r in rs if r["name"].lower() == key), None) or \
        next((r for r in rs if key and key in r["name"].lower()), None)


def _put(r: dict[str, Any]) -> None:
    with _lock:
        data = _load()
        data["routines"] = [x for x in data["routines"] if x["id"] != r["id"]] + [r]
        _save(data)


def view(r: dict[str, Any]) -> dict[str, Any]:
    out = {k: r.get(k) for k in ("id", "name", "prompt", "paused", "last_status", "builtin", "target", "target_id")}
    out.update({"schedule": describe(r["schedule"]), "next_run": _fmt(r.get("next_run")) if not r.get("paused") else "",
                "last_run": _fmt(r.get("last_run")), "last_result": (r.get("last_result") or "")[:300],
                "session": session_for(r), "done": r.get("next_run") is None and not r.get("paused")})
    return out


def create_routine(name: str, prompt: str, when: str, bot: str = "") -> dict[str, Any]:
    name = " ".join((name or "").split())[:60]
    prompt = (prompt or "").strip()[:2000]
    if not name or not prompt:
        return {"ok": False, "error": "Give the routine a name and what to do."}
    try:
        sched = parse_when(when)
        kind, tid = _target(bot)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    if find(name) and find(name)["name"].lower() == name.lower():
        return {"ok": False, "error": f"A routine called '{name}' already exists. Use update_routine."}
    now = _now()
    r = {"id": uuid.uuid4().hex[:10], "name": name, "prompt": prompt, "when": when, "schedule": sched,
         "target": kind, "target_id": tid, "paused": False, "created": time.strftime("%Y-%m-%d %H:%M"),
         "next_run": next_run(sched, now), "last_run": 0, "last_status": "", "last_result": ""}
    _put(r)
    v = view(r)
    return {"ok": True, "routine": v, "message": f"Routine '{name}' saved: {v['schedule']}. Next run: {v['next_run']}. "
            f"Results will appear in the '{v['session']}' chat. Manage it in Routines."}


def update_routine(routine: str, name: str = "", prompt: str = "", when: str = "", bot: str = "") -> dict[str, Any]:
    r = find(routine)
    if not r:
        return {"ok": False, "error": f"No routine '{routine}'. " + list_routines()["message"]}
    try:
        if when:
            r["schedule"], r["when"] = parse_when(when), when
            r["next_run"] = next_run(r["schedule"], _now())
        if bot:
            r["target"], r["target_id"] = _target(bot)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    if name:
        r["name"] = " ".join(name.split())[:60]
    if prompt and not r.get("builtin"):
        r["prompt"] = prompt.strip()[:2000]
    _put(r)
    return {"ok": True, "routine": view(r), "message": f"Updated '{r['name']}': {describe(r['schedule'])}."}


def pause_routine(routine: str) -> dict[str, Any]:
    r = find(routine)
    if not r:
        return {"ok": False, "error": f"No routine '{routine}'."}
    r["paused"] = True; _put(r)
    return {"ok": True, "message": f"Paused '{r['name']}'."}


def resume_routine(routine: str) -> dict[str, Any]:
    r = find(routine)
    if not r:
        return {"ok": False, "error": f"No routine '{routine}'."}
    r["paused"] = False
    r["next_run"] = next_run(r["schedule"], _now(), 0 if r["schedule"]["kind"] != "once" else r.get("last_run", 0))
    _put(r)
    return {"ok": True, "message": f"Resumed '{r['name']}'. Next run: {_fmt(r['next_run']) or 'none (already ran)'}."}


def delete_routine(routine: str) -> dict[str, Any]:
    """Asks first: only runs after Pedro's Approve / yes."""
    import confirm_action
    r = find(routine)
    if not r:
        return {"ok": False, "error": f"No routine '{routine}'."}
    if not confirm_action.consume_grant("delete_routine", {"routine": r["id"]}):
        confirm_action.remember("delete_routine", {"routine": r["id"]}, f"delete the routine '{r['name']}'")
        return {"ok": False, "needs_confirmation": True,
                "error": f"Waiting for Pedro to approve deleting '{r['name']}'. Stop and tell him."}
    return _remove(r["id"])


def _remove(rid: str) -> dict[str, Any]:
    with _lock:
        data = _load()
        r = next((x for x in data["routines"] if x["id"] == rid), None)
        data["routines"] = [x for x in data["routines"] if x["id"] != rid]
        _save(data)
    return {"ok": bool(r), "message": f"Deleted routine '{r['name']}'." if r else "Already gone."}


def list_routines() -> dict[str, Any]:
    rs = [view(r) for r in _load()["routines"]]
    lines = [f"- {v['name']}: {v['schedule']}" + (" (paused)" if v["paused"] else f", next {v['next_run'] or 'done'}") +
             (f", last {v['last_run']} {v['last_status']}" if v["last_run"] else "") for v in rs]
    return {"ok": True, "routines": rs, "message": "\n".join(lines) or "No routines yet."}


def seed_builtin() -> None:
    """The 7 PM Wingz check + daily report lives in the list (once; deleting it is respected)."""
    with _lock:
        data = _load()
        if data.get("seeded"):
            return
        sched = {"kind": "daily", "time": "19:00", "days": list(range(7))}
        now = _now()
        try:
            import extras148
            done_today = extras148._load("evening_stamp.json", {}).get("day") == time.strftime("%Y-%m-%d", time.localtime(now))
        except Exception:
            done_today = False
        nxt = next_run(sched, now)
        if not done_today and time.strftime("%H:%M", time.localtime(now)) >= "19:00":
            nxt = now   # today's 7 PM check was missed while the app was closed: run it now
        data["routines"].append({"id": WINGZ_ID, "name": "Evening Wingz check", "builtin": True, "action": "evening_check",
                                 "prompt": "Scan the 4 Wingz courses and post the daily report (no filling, list only).",
                                 "when": "every day at 7 PM", "schedule": sched, "target": "main", "target_id": "",
                                 "session": "daily-report", "paused": False, "created": time.strftime("%Y-%m-%d %H:%M"),
                                 "next_run": nxt, "last_run": 0, "last_status": "", "last_result": ""})
        data["seeded"] = True
        _save(data)


# ---------- running ----------
_running: set[str] = set()


def due(now: float | None = None) -> list[dict[str, Any]]:
    now = _now() if now is None else now
    try:
        import safe_mode

        if safe_mode.paused():
            return []
    except Exception:
        pass
    return [r for r in _load()["routines"] if not r.get("paused") and r.get("next_run") and r["next_run"] <= now
            and r["id"] not in _running]


def run_routine(r: dict[str, Any], manual: bool = False) -> dict[str, Any]:
    _running.add(r["id"])
    started = _now()
    status, result = "ok", ""
    try:
        if r.get("action") == "evening_check":
            import extras148
            extras148._save("evening_stamp.json", {"day": time.strftime("%Y-%m-%d")})
            result = str(extras148.evening_check().get("message") or "")
        elif runner is not None:
            result = runner(r) or ""
        else:
            raise RuntimeError("The app is not running the scheduler.")
        if not result.strip():
            status = "no reply"
    except Exception as exc:
        status, result = "failed", str(exc)
    finally:
        _running.discard(r["id"])
    with _lock:
        fresh = find(r["id"]) or r
        fresh["last_run"], fresh["last_status"], fresh["last_result"] = started, status, result[:2000]
        if not manual:
            fresh["next_run"] = next_run(fresh["schedule"], max(_now(), started), started)
        _put(fresh)
        data = _load()
        data.setdefault("feed", []).append({"t": time.time(), "routine": fresh["name"], "status": status,
                                            "session": session_for(fresh), "text": result[:200]})
        data["feed"] = data["feed"][-50:]
        _save(data)
    return {"ok": status == "ok", "status": status, "message": result}


def tick(now: float | None = None) -> list[dict[str, Any]]:
    out = []
    for r in due(now):
        out.append(run_routine(r))
    return out


def feed(since: float = 0) -> list[dict[str, Any]]:
    return [f for f in _load().get("feed", []) if f["t"] > since]


_thread: threading.Thread | None = None


def start(every: float = 20.0) -> None:
    global _thread
    if _thread is not None:
        return
    seed_builtin()

    def loop() -> None:
        while True:
            try:
                for r in due():
                    threading.Thread(target=run_routine, args=(r,), daemon=True, name="routine-" + r["id"]).start()
            except Exception as exc:
                print(f"[routines] {exc}", flush=True)
            time.sleep(every)

    _thread = threading.Thread(target=loop, daemon=True, name="routines")
    _thread.start()


DECLARATIONS = [
    {"name": "create_routine",
     "description": "Create a scheduled routine from Pedro's words: one-time ('tomorrow 9 AM', 'in 10 minutes', 'Friday 6 PM') or repeating ('every day at 7 PM', 'weekdays at 8 AM', 'every 2 hours'). Times are IST. prompt = what to do then, written as an instruction. bot = bot or group name to run it (empty = main assistant). Then confirm the schedule and next run to Pedro.",
     "parameters": {"type": "object", "properties": {
         "name": {"type": "string"}, "prompt": {"type": "string"}, "when": {"type": "string"},
         "bot": {"type": "string"}}, "required": ["name", "prompt", "when"]}},
    {"name": "update_routine", "description": "Change a routine's name, prompt, time (when) or bot.",
     "parameters": {"type": "object", "properties": {"routine": {"type": "string"}, "name": {"type": "string"},
                    "prompt": {"type": "string"}, "when": {"type": "string"}, "bot": {"type": "string"}}, "required": ["routine"]}},
    {"name": "pause_routine", "description": "Pause a routine.",
     "parameters": {"type": "object", "properties": {"routine": {"type": "string"}}, "required": ["routine"]}},
    {"name": "resume_routine", "description": "Resume a paused routine.",
     "parameters": {"type": "object", "properties": {"routine": {"type": "string"}}, "required": ["routine"]}},
    {"name": "delete_routine", "description": "Delete a routine (Pedro must approve first).",
     "parameters": {"type": "object", "properties": {"routine": {"type": "string"}}, "required": ["routine"]}},
    {"name": "list_routines", "description": "List routines with schedule, next run and last result.",
     "parameters": {"type": "object", "properties": {}}},
]
TOOLS = {"create_routine": create_routine, "update_routine": update_routine, "pause_routine": pause_routine,
         "resume_routine": resume_routine, "delete_routine": delete_routine, "list_routines": list_routines}
