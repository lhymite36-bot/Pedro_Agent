"""Team tasks: planner splits work, workers do parts, checker reviews, max 3 retries.

Live progress is stored so the Pro page can poll a board. The final answer
lists who did what. Existing team_agent + rules.yaml still apply.
"""

from __future__ import annotations

import threading
import time
import uuid
from typing import Any

_jobs: dict[str, dict[str, Any]] = {}
_lock = threading.Lock()
run_override = None  # tests: fn(goal) -> dict


def _job(jid: str) -> dict[str, Any] | None:
    with _lock:
        j = _jobs.get(jid)
        return dict(j) if j else None


def status(jid: str = "") -> dict[str, Any]:
    if jid:
        j = _job(jid)
        return {"ok": bool(j), **(j or {"error": "No such team task."})}
    with _lock:
        items = [{k: v.get(k) for k in ("id", "goal", "status", "started")} for v in _jobs.values()]
    items.sort(key=lambda x: -float(x.get("started") or 0))
    return {"ok": True, "jobs": items[:20]}


def _emit(job: dict[str, Any], event: dict[str, Any]) -> None:
    board = job.setdefault("board", [])
    row = {
        "at": time.time(),
        "who": str(event.get("who") or event.get("role") or event.get("label") or "team"),
        "status": str(event.get("status") or event.get("event") or "update"),
        "text": str(event.get("text") or event.get("task") or event.get("label") or "")[:400],
    }
    board.append(row)
    job["board"] = board[-80:]
    job["log"] = (job.get("log") or []) + [f"{row['who']}: {row['text']}" if row["text"] else row["who"]]
    job["log"] = job["log"][-40:]


def _run(jid: str, goal: str) -> None:
    job = _jobs[jid]
    _emit(job, {"who": "Planner", "status": "working", "text": "Splitting the work…"})
    try:
        if run_override is not None:
            result = run_override(goal)
        else:
            import team_agent
            rounds = 0
            last: dict[str, Any] = {}
            while rounds < 3:
                rounds += 1
                _emit(job, {"who": "Planner", "status": "working", "text": f"Plan round {rounds}"})

                def on_event(ev: dict[str, Any]) -> None:
                    who = str(ev.get("role") or ev.get("label") or ev.get("event") or "worker")
                    _emit(job, {"who": who, "status": ev.get("event") or "working", "text": str(ev.get("task") or ev.get("label") or "")})

                last = team_agent.run_team(goal, on_event=on_event)
                if last.get("ok"):
                    break
                _emit(job, {"who": "Checker", "status": "retry", "text": f"Retry {rounds}/3"})
            result = last
        who = []
        for row in job.get("board") or []:
            if row.get("who") and row["who"] not in who:
                who.append(row["who"])
        parts = result.get("results") or result.get("steps") or []
        credits = []
        if isinstance(parts, list):
            for p in parts:
                if isinstance(p, dict):
                    credits.append(f"{p.get('role') or p.get('who') or 'bot'}: {str(p.get('task') or p.get('result') or '')[:120]}")
        answer = str(result.get("message") or result.get("summary") or result.get("result") or "")
        if credits:
            answer = (answer + "\n\nWho did what:\n- " + "\n- ".join(credits)).strip()
        job.update(status="done" if result.get("ok") else "failed", result=result, answer=answer, who=who)
        _emit(job, {"who": "Checker", "status": job["status"], "text": "Finished."})
    except Exception as exc:
        job.update(status="failed", error=str(exc)[:300])
        _emit(job, {"who": "Checker", "status": "failed", "text": str(exc)[:200]})


def start(goal: str) -> dict[str, Any]:
    goal = " ".join((goal or "").split())[:500]
    if not goal:
        return {"ok": False, "error": "Describe the team task."}
    jid = uuid.uuid4().hex[:8]
    job = {"id": jid, "goal": goal, "status": "working", "started": time.time(), "board": [], "log": []}
    with _lock:
        _jobs[jid] = job
    threading.Thread(target=_run, args=(jid, goal), daemon=True, name="team-" + jid).start()
    return {"ok": True, "job": jid, **status(jid)}


def handle(action: str, data: dict[str, Any]) -> dict[str, Any]:
    if action in ("", "status"):
        return status(str(data.get("job") or data.get("id") or ""))
    if action == "start":
        return start(str(data.get("goal") or data.get("text") or ""))
    return {"ok": False, "error": "Unknown team action."}
