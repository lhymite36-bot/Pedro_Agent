"""1.4.8 extras: proof of work, daily report, Gemini usage tracker, change log, deadlines.

All data stays on this PC under workspace/. Nothing here sends, deletes or submits anything.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent / "workspace"
_lock = threading.Lock()
shot_override: Any = None   # tests: callable(path) -> None


def _p(name: str) -> Path:
    ROOT.mkdir(parents=True, exist_ok=True)
    return ROOT / name


def _load(name: str, default: Any) -> Any:
    try:
        return json.loads(_p(name).read_text(encoding="utf-8"))
    except Exception:
        return default


def _save(name: str, data: Any) -> None:
    _p(name).write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")


def _slug(s: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in (s or "task").lower()).strip("-")[:40] or "task"


# ---- Phase 2: proof of work ----
def record_step_proof(task: str, step: str, check: str = "", window: str = "") -> dict[str, Any]:
    """Screenshot + note for one finished step; saved under workspace/proof/<task>/."""
    folder = _p("proof") / _slug(task)
    folder.mkdir(parents=True, exist_ok=True)
    n = len(list(folder.glob("*.jpg"))) + 1
    shot = folder / f"{n:02d}.jpg"
    shot_window = ""
    try:
        if shot_override is not None:
            shot_override(str(shot))
        else:
            import extras149  # shoots the step's window, never this app's own window
            got = extras149.capture_proof(str(shot), window)
            shot_window = got["window"]
            if got["note"]:
                check = f"{check} ({got['note']})".strip()
    except Exception as exc:
        shot = None
        check = f"{check} (no screenshot: {exc})".strip()
    with _lock:
        log = _load("proof_log.json", [])
        log.append({"t": time.strftime("%Y-%m-%d %H:%M"), "task": task, "step": step,
                    "check": check, "window": shot_window, "screenshot": str(shot) if shot else ""})
        _save("proof_log.json", log[-500:])
    import task_memory
    task_memory.save_task_progress(task, done=step, note=check)
    return {"ok": True, "message": f"Proof saved for step {n}" + (f" (window: {shot_window})." if shot_window else "."),
            "screenshot": str(shot) if shot else "", "window": shot_window}


# ---- Phase 6: Gemini usage, change log, deadlines ----
def note_model_call(model: str, ok: bool, error: str = "") -> None:
    day = time.strftime("%Y-%m-%d")
    with _lock:
        data = _load("gemini_usage.json", {})
        row = data.setdefault(day, {}).setdefault(model, {"calls": 0, "errors": 0, "busy": 0})
        row["calls"] += 1
        if not ok:
            row["errors"] += 1
            if any(k in error.lower() for k in ("503", "high demand", "overloaded", "429", "quota")):
                row["busy"] += 1
        for old in sorted(data)[:-14]:
            data.pop(old, None)
        _save("gemini_usage.json", data)


def exhausted_models() -> set[str]:
    """Gemini models that already hit a busy or quota error today. Tomorrow's file is a new day."""
    day = time.strftime("%Y-%m-%d")
    usage = _load("gemini_usage.json", {}).get(day) or {}
    if not isinstance(usage, dict):
        return set()
    return {str(model) for model, row in usage.items()
            if isinstance(row, dict) and int(row.get("busy") or 0) > 0}


def quota_line(selected: str = "") -> str:
    """A short line when a Gemini model already hit its free-tier limit today."""
    exhausted = sorted(exhausted_models())
    if not exhausted:
        return ""
    name = selected if selected in exhausted else exhausted[0]
    return f"{name} is out for today"


def gemini_usage(days: int = 1) -> dict[str, Any]:
    data = _load("gemini_usage.json", {})
    keep = {d: data[d] for d in sorted(data)[-max(1, int(days)):]}
    lines = [f"{d} {m}: {r['calls']} calls, {r['errors']} errors ({r['busy']} busy/quota)"
             for d, models in keep.items() for m, r in models.items()]
    return {"ok": True, "message": "\n".join(lines) or "No Gemini calls recorded yet.", "usage": keep}


def note_change(tool: str, path: str, action: str = "created") -> None:
    if not path:
        return
    with _lock:
        log = _load("change_log.json", [])
        log.append({"t": time.strftime("%Y-%m-%d %H:%M"), "tool": tool, "action": action, "path": path})
        _save("change_log.json", log[-1000:])


def show_change_log(limit: int = 20) -> dict[str, Any]:
    log = _load("change_log.json", [])[-max(1, int(limit)):]
    lines = [f"{e['t']} {e['action']} {e['path']} ({e['tool']})" for e in log]
    return {"ok": True, "message": "\n".join(lines) or "No changes recorded yet.", "entries": log,
            "note": "Say undo to put the last file back. undo_last_change restores the previous copy, or removes a file just created."}


def add_deadline(title: str, due: str, note: str = "") -> dict[str, Any]:
    try:
        time.strptime(due, "%Y-%m-%d")
    except ValueError:
        return {"ok": False, "error": "Give the due date as YYYY-MM-DD."}
    with _lock:
        items = _load("deadlines.json", [])
        items.append({"title": title, "due": due, "note": note})
        _save("deadlines.json", items)
    return {"ok": True, "message": f"Deadline saved: {title} on {due}."}


def upcoming_deadlines(days: int = 7) -> list[dict[str, Any]]:
    today = time.strftime("%Y-%m-%d")
    end = time.strftime("%Y-%m-%d", time.localtime(time.time() + 86400 * max(0, int(days))))
    return sorted([d for d in _load("deadlines.json", []) if today <= d["due"] <= end], key=lambda d: d["due"])


# ---- Phase 3: daily report ----
def daily_report() -> dict[str, Any]:
    import task_memory
    parts = []
    wz = task_memory.get_task_progress("wingz").get("log", [])
    if wz:
        parts.append("Wingz (last scan " + wz[-1]["t"] + "):\n" + (wz[-1].get("left") or wz[-1].get("done") or ""))
    dl = upcoming_deadlines(7)
    if dl:
        parts.append("Deadlines this week:\n" + "\n".join(f"- {d['due']}: {d['title']}" for d in dl))
    proofs = [p for p in _load("proof_log.json", []) if p["t"].startswith(time.strftime("%Y-%m-%d"))]
    if proofs:
        parts.append(f"Steps finished today with proof: {len(proofs)}")
    parts.append("Gemini today:\n" + gemini_usage(1)["message"])
    text = "\n\n".join(parts)
    _p("daily_report.txt").write_text(text, encoding="utf-8")
    return {"ok": True, "message": text, "path": str(_p("daily_report.txt")),
            "note": "Shown in the app. Ask before sending it anywhere."}


DECLARATIONS = [
    {"name": "record_step_proof",
     "description": "After finishing a step of a task, save proof: a screenshot plus what you checked. Also saves progress for resume.",
     "parameters": {"type": "object", "properties": {
         "task": {"type": "string"}, "step": {"type": "string"},
         "check": {"type": "string", "description": "What you verified, e.g. 'Saved banner shown'."},
         "window": {"type": "string", "description": "Part of the title of the window that shows the result, e.g. 'Power_BI_Tips.pdf' or 'Wingz'. Never this app."}},
         "required": ["task", "step"]}},
    {"name": "gemini_usage", "description": "Show today's Gemini calls, errors and busy/quota hits per model.",
     "parameters": {"type": "object", "properties": {"days": {"type": "integer"}}}},
    {"name": "show_change_log", "description": "List files the agent created or changed recently (for undo).",
     "parameters": {"type": "object", "properties": {"limit": {"type": "integer"}}}},
    {"name": "add_deadline", "description": "Save a deadline (YYYY-MM-DD) so it shows in the daily report.",
     "parameters": {"type": "object", "properties": {"title": {"type": "string"}, "due": {"type": "string"},
                    "note": {"type": "string"}}, "required": ["title", "due"]}},
    {"name": "daily_report",
     "description": "Build the morning report: Wingz list, deadlines this week, proofs today, Gemini usage. Use for 'morning report' or scheduled daily checks.",
     "parameters": {"type": "object", "properties": {}}},
]
TOOLS = {"record_step_proof": record_step_proof, "gemini_usage": gemini_usage,
         "show_change_log": show_change_log, "add_deadline": add_deadline, "daily_report": daily_report}


# ---- Phase 3: evening Wingz check, shown inside the app (chat "Daily report") ----
REPORT_SESSION = "daily-report"
EVENING_AT = "19:00"
_evening_thread: threading.Thread | None = None
scan_override: Any = None   # tests


def evening_check() -> dict[str, Any]:
    """Run wingz_scan + daily_report and post the report in the app's own chat list."""
    try:
        if scan_override is not None:
            scan_override()
        else:
            import wingz_scan
            wingz_scan.wingz_scan()
    except Exception as exc:
        print(f"[evening] wingz_scan failed: {exc}", flush=True)
    rep = daily_report()
    try:
        import chat_store
        chat_store.add(REPORT_SESSION, "assistant", "Evening report " + time.strftime("%d %b %H:%M") + "\n\n" + rep["message"])
    except Exception as exc:
        print(f"[evening] could not post the report: {exc}", flush=True)
    return rep


def _due(now: time.struct_time, last_day: str, at: str = EVENING_AT) -> bool:
    return time.strftime("%Y-%m-%d", now) != last_day and time.strftime("%H:%M", now) >= at


def start_evening_job(at: str = EVENING_AT) -> None:
    """Daemon: once a day after `at` (PC local time), run evening_check. Survives restarts via a stamp."""
    global _evening_thread
    if _evening_thread is not None:
        return

    def loop():
        while True:
            try:
                last = _load("evening_stamp.json", {}).get("day", "")
                if _due(time.localtime(), last, at):
                    _save("evening_stamp.json", {"day": time.strftime("%Y-%m-%d")})
                    evening_check()
            except Exception as exc:
                print(f"[evening] {exc}", flush=True)
            time.sleep(60)

    _evening_thread = threading.Thread(target=loop, daemon=True, name="evening-wingz")
    _evening_thread.start()
    print(f"[evening] Wingz check + report scheduled daily at {at}.", flush=True)
