"""1.4.18: the task board. Every task runs in its own worker, so a slow job never blocks chat or other bots.

- Up to MAX_RUNNING tasks (default 5, 1-6) run at the same time, each in its own chat session
  ("task-<id>") with its own lock, history and Stop button. Waiting tasks start in board order.
- Pause holds a task at its next step; Stop ends it; Up/Down reorder waiting tasks.
- A manager job (`split`) asks the planner to cut a big goal into independent parts, runs the parts
  as separate tasks in parallel, then merges their answers into one reply.
- Finished answers go to the shared notebook as "task:<id>" and back to the chat that asked.
- Approvals are unchanged: a task that needs a yes waits on the board with Approve / Decline, and
  only one approval card is open at a time (confirm_action queues the others).
"""

from __future__ import annotations

import threading
import time
import uuid
from typing import Any, Callable

MAX_RUNNING = 5
SESSION_PREFIX = "task-"
KEEP_FINISHED = 40

# chat_app sets this: runner(session, text, emit) -> reply. Tests replace it.
runner: Callable[[str, str, Callable[[dict[str, Any]], None]], str] | None = None
# chat_app sets this: stop(session) cancels a running turn in that session.
stopper: Callable[[str], None] | None = None
# chat_app sets this: post(session, text) adds an assistant message to a chat and tells the windows.
poster: Callable[[str, str], None] | None = None

_lock = threading.RLock()
_tasks: dict[str, dict[str, Any]] = {}
_order: list[str] = []
_pause: dict[str, threading.Event] = {}     # set = may run
_changed = threading.Condition(_lock)
_version = 0


def _now() -> float:
    return time.time()


def _bump() -> None:
    global _version
    _version += 1
    _changed.notify_all()
    try:
        import live_sync
        live_sync.notify("tasks", version=_version)
    except Exception:
        pass


def _public(t: dict[str, Any]) -> dict[str, Any]:
    keep = ("id", "title", "goal", "status", "bot", "steps", "tools", "progress", "created", "started", "finished",
            "result", "parent", "children", "origin", "needs", "model", "error")
    out = {k: t.get(k) for k in keep}
    out["seconds"] = round((t.get("finished") or _now()) - t["started"], 1) if t.get("started") else 0
    return out


def snapshot() -> dict[str, Any]:
    with _lock:
        rows = [_public(_tasks[i]) for i in _order if i in _tasks]
        running = sum(1 for t in _tasks.values() if t["status"] in ("running", "paused", "approval"))
        return {"tasks": rows, "running": running, "max_running": MAX_RUNNING, "version": _version}


def get(task_id: str) -> dict[str, Any] | None:
    with _lock:
        t = _tasks.get(task_id)
        return _public(t) if t else None


def _title(goal: str) -> str:
    words = " ".join(str(goal or "").split())
    return words if len(words) <= 70 else words[:67].rstrip() + "…"


def add(goal: str, *, bot: str = "", origin: str = "", parent: str = "", title: str = "", start: bool = True) -> dict[str, Any]:
    goal = " ".join(str(goal or "").split())
    if not goal:
        return {"ok": False, "error": "Say what the task should do."}
    tid = uuid.uuid4().hex[:8]
    with _lock:
        _tasks[tid] = {"id": tid, "title": title or _title(goal), "goal": goal, "status": "waiting", "bot": bot,
                       "steps": [], "tools": 0, "progress": 0, "created": _now(), "started": 0.0, "finished": 0.0,
                       "result": "", "parent": parent, "children": [], "origin": origin, "needs": "", "model": "",
                       "error": "", "session": _session_for(tid, bot)}
        _order.append(tid)
        ev = threading.Event()
        ev.set()
        _pause[tid] = ev
        _trim()
        _bump()
    if start:
        _dispatch()
    return {"ok": True, "message": f"Task added to the board: {_title(goal)}", "id": tid}


def _trim() -> None:
    done = [i for i in _order if _tasks.get(i, {}).get("status") in ("done", "failed", "stopped")]
    for old in done[: max(0, len(done) - KEEP_FINISHED)]:
        _order.remove(old)
        _tasks.pop(old, None)
        _pause.pop(old, None)


def _session_for(tid: str, bot: str) -> str:
    """A task's own chat session. A bot's task runs as that bot, but not in its main chat (so it never waits on it)."""
    if bot:
        try:
            import bots
            found = bots.get_bot(bot)
            if found:
                return f"{bots.SESSION_PREFIX}{found['id']}#{SESSION_PREFIX}{tid}"
        except Exception:
            pass
    return SESSION_PREFIX + tid


def _running_count() -> int:   # the manager only waits, so it does not take a worker slot
    return sum(1 for t in _tasks.values() if t["status"] in ("running", "paused", "approval") and t.get("kind") != "manager")


def _dispatch() -> None:
    to_start = []
    with _lock:
        free = max(1, min(6, int(MAX_RUNNING))) - _running_count()
        for tid in _order:
            if free <= 0:
                break
            t = _tasks.get(tid)
            if t and t["status"] == "waiting" and _pause[tid].is_set() and t.get("kind") != "manager":
                t["status"] = "running"
                t["started"] = _now()
                to_start.append(tid)
                free -= 1
        if to_start:
            _bump()
    for tid in to_start:
        threading.Thread(target=_work, args=(tid,), daemon=True, name=f"task-{tid}").start()


def _emit_for(tid: str) -> Callable[[dict[str, Any]], None]:
    def emit(ev: dict[str, Any]) -> None:
        kind = ev.get("event")
        gate = _pause.get(tid)
        if gate is not None and not gate.is_set() and kind in ("tool_start", "step", "model_switch"):
            with _lock:
                if tid in _tasks and _tasks[tid]["status"] == "running":
                    _tasks[tid]["status"] = "paused"
                    _bump()
            while not gate.wait(0.25):     # paused: hold here until Resume or Stop
                if _tasks.get(tid, {}).get("status") == "stopped":
                    break
            with _lock:
                if _tasks.get(tid, {}).get("status") == "paused":
                    _tasks[tid]["status"] = "running"
                    _bump()
        with _lock:
            t = _tasks.get(tid)
            if t is None:
                return
            label = ""
            if kind == "step" and ev.get("label"):
                label = str(ev["label"])
            elif kind == "tool_start":
                t["tools"] += 1
                label = str(ev.get("label") or ev.get("name") or ev.get("tool") or "Working")
            elif kind == "model_switch":
                t["model"] = str(ev.get("model") or "")[:60]
            if label:
                t["steps"] = (t["steps"] + [label[:120]])[-6:]
                # Progress is an estimate: it grows with each step and never claims 100 before the end.
                t["progress"] = min(90, 8 + t["tools"] * 12)
                _bump()
    return emit


def _work(tid: str) -> None:
    with _lock:
        t = _tasks[tid]
        session, goal = t["session"], t["goal"]
    text = goal
    try:
        reply = (runner or _no_runner)(session, text, _emit_for(tid)) or ""
        _finish(tid, reply)
    except Exception as exc:
        with _lock:
            t["status"], t["error"], t["finished"] = "failed", str(exc)[:300], _now()
            _bump()
    finally:
        _dispatch()


def _no_runner(session: str, text: str, emit: Callable[[dict[str, Any]], None]) -> str:
    raise RuntimeError("The task board is not connected to the app yet.")


def _pending_for(session: str) -> dict[str, Any] | None:
    try:
        import confirm_action
        token = confirm_action.bind_chat(session)
        try:
            return confirm_action.pending()
        finally:
            confirm_action.unbind_chat(token)
    except Exception:
        return None


def _finish(tid: str, reply: str) -> None:
    with _lock:
        t = _tasks[tid]
        if t["status"] == "stopped":
            t["finished"] = t["finished"] or _now()
            _bump()
            return
        waiting = _pending_for(t["session"])
        t["result"] = reply[:6000]
        if waiting:
            t["status"], t["needs"] = "approval", str(waiting.get("label") or "approve the next step")
            _bump()
            _say(t, f"Task \"{t['title']}\" needs your OK: {t['needs']}. Approve or decline it on the task board.")
            return
        t["status"], t["progress"], t["finished"], t["needs"] = "done", 100, _now(), ""
        _bump()
    try:
        import shared_memory
        shared_memory.put(f"task:{tid}", reply or "(no answer)", by=t.get("bot") or "Ped Bot")
    except Exception:
        pass
    if not t.get("parent"):
        _say(t, f"Task done: {t['title']}\n\n{reply}".strip())


def _say(t: dict[str, Any], text: str) -> None:
    if t.get("origin") and poster is not None:
        try:
            poster(t["origin"], text)
        except Exception:
            pass
    try:
        import background
        background.notify("Ped Bot", text.split("\n", 1)[0][:200])
    except Exception:
        pass


def _drop_card(session: str) -> None:
    try:
        import confirm_action
        confirm_action.drop_pending(session)
    except Exception:
        pass


def control(task_id: str, action: str) -> dict[str, Any]:
    action = str(action or "").strip().casefold()
    with _lock:
        t = _tasks.get(task_id)
        if t is None:
            return {"ok": False, "error": "That task is no longer on the board."}
        status = t["status"]
        if action == "pause":
            if status in ("done", "failed", "stopped"):
                return {"ok": False, "error": "That task has already finished."}
            _pause[task_id].clear()
            if status == "waiting":
                t["status"] = "held"
            _bump()
            return {"ok": True, "message": "Paused. It holds at its next step."}
        if action == "resume":
            _pause[task_id].set()
            if status == "held":
                t["status"] = "waiting"
            _bump()
        elif action == "stop":
            if status in ("done", "failed", "stopped"):
                return {"ok": False, "error": "That task has already finished."}
            t["status"], t["finished"] = "stopped", _now()
            _pause[task_id].set()
            _drop_card(t["session"])
            for child in t.get("children") or []:
                if _tasks.get(child, {}).get("status") not in ("done", "failed", "stopped", None):
                    _tasks[child]["status"], _tasks[child]["finished"] = "stopped", _now()
                    _pause[child].set()
                    if stopper is not None:
                        threading.Thread(target=stopper, args=(_tasks[child]["session"],), daemon=True).start()
            _bump()
            if stopper is not None and status in ("running", "paused", "approval"):
                threading.Thread(target=stopper, args=(t["session"],), daemon=True).start()
        elif action in ("up", "down", "top"):
            i = _order.index(task_id)
            j = 0 if action == "top" else max(0, min(len(_order) - 1, i + (-1 if action == "up" else 1)))
            _order.insert(j, _order.pop(i))
            _bump()
        elif action in ("approve", "decline"):
            if status != "approval":
                return {"ok": False, "error": "That task is not waiting for an OK."}
            t["status"], t["needs"] = "running", ""
            _bump()
            threading.Thread(target=_answer, args=(task_id, "yes" if action == "approve" else "no"),
                             daemon=True, name=f"task-{task_id}-answer").start()
            return {"ok": True, "message": "Approved." if action == "approve" else "Declined. Nothing was done."}
        elif action == "remove":
            if status in ("running", "paused", "approval"):
                return {"ok": False, "error": "Stop it first."}
            _order.remove(task_id)
            _tasks.pop(task_id, None)
            _pause.pop(task_id, None)
            _bump()
            return {"ok": True, "message": "Removed from the board."}
        else:
            return {"ok": False, "error": f"Unknown action: {action}"}
    _dispatch()
    return {"ok": True, "message": "Done."}


def _answer(tid: str, text: str) -> None:
    session = _tasks[tid]["session"]
    try:
        reply = (runner or _no_runner)(session, text, _emit_for(tid)) or ""
        _finish(tid, reply)
    except Exception as exc:
        with _lock:
            _tasks[tid]["status"], _tasks[tid]["error"], _tasks[tid]["finished"] = "failed", str(exc)[:300], _now()
            _bump()
    finally:
        _dispatch()


# ---------- the manager: split a big job, run the parts in parallel, merge ----------
planner: Callable[[str], list[dict[str, str]]] | None = None   # tests replace these
merger: Callable[[str, list[dict[str, Any]]], str] | None = None


def _plan(goal: str) -> list[dict[str, str]]:
    if planner is not None:
        return planner(goal)
    import team_agent
    return team_agent.plan(goal)


def _merge(goal: str, parts: list[dict[str, Any]]) -> str:
    if merger is not None:
        return merger(goal, parts)
    import team_agent
    rows = [{"role": p.get("role", ""), "task": p["task"], "result": p.get("result") or p.get("status", ""),
             "ok": p.get("status") == "done"} for p in parts]
    return str(team_agent.review(goal, rows).get("summary") or "")


def split(goal: str, *, origin: str = "", wait: bool = False) -> dict[str, Any]:
    goal = " ".join(str(goal or "").split())
    if not goal:
        return {"ok": False, "error": "Say what the job is."}
    made = add(goal, origin=origin, title="Manager: " + _title(goal), start=False)
    mid = made["id"]
    with _lock:
        _tasks[mid].update(kind="manager", status="running", started=_now(), steps=["Splitting the job into parts"])
        _bump()
    th = threading.Thread(target=_manage, args=(mid,), daemon=True, name=f"task-{mid}-manager")
    th.start()
    if wait:
        th.join()
    return {"ok": True, "message": f"Manager started: {_title(goal)}. Its parts run in parallel on the task board.",
            "id": mid}


def _manage(mid: str) -> None:
    t = _tasks[mid]
    try:
        parts = _plan(t["goal"]) or [{"role": "research", "task": t["goal"]}]
        kids = []
        for p in parts[:6]:
            brief = (f"{p['task']}\n\n(This is one part of a bigger job: \"{t['goal']}\". Do only this part, "
                     "read-only unless the part clearly needs a change, and report the result briefly.)")
            kid = add(brief, parent=mid, title=_title(p["task"]), start=False)["id"]
            with _lock:
                _tasks[kid]["role"] = p.get("role", "")
            kids.append(kid)
        with _lock:
            t["children"] = kids
            t["steps"] = (t["steps"] + [f"Running {len(kids)} parts in parallel"])[-6:]
            t["progress"] = 10
            _bump()
        _dispatch()
        while True:
            with _lock:
                if t["status"] == "stopped":
                    return
                states = [_tasks.get(k, {}).get("status") for k in kids]
                done = sum(1 for s in states if s in ("done", "failed", "stopped", None))
                t["progress"] = 10 + int(75 * done / max(1, len(kids)))
                if done == len(kids):
                    break
                waiting_ok = any(s == "approval" for s in states)
                t["needs"] = "a part is waiting for your OK" if waiting_ok else ""
                _changed.wait(1.0)
        with _lock:
            t["steps"] = (t["steps"] + ["Merging the results"])[-6:]
            rows = [{"task": _tasks[k]["title"], "role": _tasks[k].get("role", ""), "status": _tasks[k]["status"],
                     "result": _tasks[k]["result"] or _tasks[k]["error"]} for k in kids if k in _tasks]
            _bump()
        summary = _merge(t["goal"], rows) or "\n\n".join(f"{r['task']}: {r['result']}" for r in rows)
        _finish(mid, summary)
    except Exception as exc:
        with _lock:
            t["status"], t["error"], t["finished"] = "failed", str(exc)[:300], _now()
            _bump()


# ---------- tools the chat model can use ----------
def _origin() -> str:
    try:
        import confirm_action
        return confirm_action._bucket()
    except Exception:
        return ""


def _inside_task(origin: str) -> bool:
    return origin.startswith(SESSION_PREFIX) or f"#{SESSION_PREFIX}" in origin


def start_background_task(goal: str, bot: str = "") -> dict[str, Any]:
    origin = _origin()
    if _inside_task(origin):
        return {"ok": False, "error": "This already runs on the task board. Do the work here."}
    return add(goal, bot=bot, origin=origin)


def split_big_job(goal: str) -> dict[str, Any]:
    origin = _origin()
    if _inside_task(origin):
        return {"ok": False, "error": "This already runs on the task board. Do the work here."}
    return split(goal, origin=origin)


def task_board_status() -> dict[str, Any]:
    snap = snapshot()
    lines = [f"{t['title']} - {t['status']}" + (f" ({t['progress']}%)" if t["status"] == "running" else "")
             for t in snap["tasks"][-12:]]
    return {"ok": True, "message": "\n".join(lines) or "The task board is empty.", "running": snap["running"]}


DECLARATIONS = [
    {"name": "start_background_task",
     "description": ("Run a slow or long job on the task board in its own worker, so this chat stays free. "
                     "Use when Pedro asks for something that will take a while, or says 'in the background'. "
                     "The answer comes back to this chat when it is done."),
     "parameters": {"type": "object", "properties": {
         "goal": {"type": "string", "description": "The whole job, in Pedro's words."},
         "bot": {"type": "string", "description": "Optional bot name to do it."}}, "required": ["goal"]}},
    {"name": "split_big_job",
     "description": ("Manager mode: split a big job with several independent parts (e.g. research three topics, "
                     "check several folders) into parts that run in parallel on the task board, then merge the "
                     "answers into one reply."),
     "parameters": {"type": "object", "properties": {"goal": {"type": "string"}}, "required": ["goal"]}},
    {"name": "task_board_status",
     "description": "List the tasks on the task board and how far each one is.",
     "parameters": {"type": "object", "properties": {}}},
]
TOOLS = {"start_background_task": start_background_task, "split_big_job": split_big_job,
         "task_board_status": task_board_status}
READ_ONLY = {"task_board_status"}


def reset() -> None:
    with _lock:
        _tasks.clear()
        _order.clear()
        _pause.clear()
