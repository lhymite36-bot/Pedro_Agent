"""1.4.8 part 2: proof screenshots of the right window, checker review, saved skills, setup checklist.

Everything stays on this PC under workspace/. Nothing here sends, deletes or submits anything.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent / "workspace"
_lock = threading.Lock()
windows_override: Any = None   # tests: callable() -> list of (title, (l, t, r, b), is_foreground)
grab_override: Any = None      # tests: callable(path, bbox) -> None
AGENT_TITLES = ("pedro agent", "pedro_agent", "127.0.0.1:8765", "localhost:8765")


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


def _clean(t: str) -> str:
    return (t or "").replace("\u200b", "").strip()


# ---- proof screenshots: shoot the window the step happened in, never the agent's own window ----
def _windows() -> list[tuple[str, tuple[int, int, int, int], bool]]:
    if windows_override is not None:
        return windows_override()
    from pywinauto import Desktop  # type: ignore
    out = []
    fg = None
    try:
        import ctypes
        fg = ctypes.windll.user32.GetForegroundWindow()
    except Exception:
        pass
    for w in Desktop(backend="uia").windows():  # top-level, in z-order (front first)
        try:
            if not w.is_visible() or w.is_minimized():
                continue
            title = _clean(w.window_text())
            r = w.rectangle()
            if not title or r.width() < 120 or r.height() < 80:
                continue
            out.append((title, (r.left, r.top, r.right, r.bottom), w.handle == fg))
        except Exception:
            continue
    return out


def _is_agent(title: str) -> bool:
    t = title.lower()
    return any(a in t for a in AGENT_TITLES)


def pick_window(want: str = "") -> tuple[str, tuple[int, int, int, int]] | None:
    """The window named by `want` (title contains it), else the front-most window that is not this app."""
    wins = _windows()
    if want:
        w = want.lower()
        for title, box, _ in wins:
            if w in title.lower() and not _is_agent(title):
                return title, box
    fg = [x for x in wins if x[2] and not _is_agent(x[0])]
    rest = [x for x in wins if not _is_agent(x[0]) and x[0].lower() not in ("program manager", "taskbar")]
    for title, box, _ in fg + rest:
        return title, box
    return None


def capture_proof(path: str, window: str = "") -> dict[str, Any]:
    """Save a screenshot of the step's window to path. Returns which window was shot."""
    picked = pick_window(window)
    title, box = (picked if picked else ("whole screen", None))
    if box is not None:
        l, t, r, b = box
        box = (max(0, l), max(0, t), r, b)
        if not window or window.lower() in title.lower():
            _focus(title)
    if grab_override is not None:
        grab_override(path, box)
    else:
        from PIL import ImageGrab  # type: ignore
        ImageGrab.grab(bbox=box, all_screens=True).convert("RGB").save(path, quality=70)
    note = "" if (not window or window.lower() in title.lower()) else f"'{window}' not found; shot '{title}' instead"
    return {"window": title, "note": note}


def _focus(title: str) -> None:
    if windows_override is not None:
        return
    try:
        from pywinauto import Desktop  # type: ignore
        for w in Desktop(backend="uia").windows():
            if _clean(w.window_text()) == title:
                w.set_focus()
                time.sleep(0.4)
                return
    except Exception:
        pass


# ---- checker-bot review: a second pass that checks the claims against real evidence ----
def review_work(task: str, claims: list[str] | None = None, files: list[str] | None = None) -> dict[str, Any]:
    """Check a finished task before reporting it: files exist and are not empty, proof was saved,
    and each claim has a proof note behind it. Anything not backed is listed as 'Could not verify'."""
    import extras148
    ok_lines, bad = [], []
    for f in files or []:
        p = Path(os.path.expandvars(os.path.expanduser(f)))
        if p.is_file() and p.stat().st_size > 0:
            ok_lines.append(f"File OK: {p} ({p.stat().st_size} bytes)")
        else:
            bad.append(f"File missing or empty: {p}")
    slug = extras148._slug(task)
    proofs = [e for e in _load("proof_log.json", []) if extras148._slug(e.get("task", "")) == slug]
    shots = [e for e in proofs if e.get("screenshot") and Path(e["screenshot"]).is_file()]
    if proofs:
        ok_lines.append(f"Proof steps saved: {len(proofs)} ({len(shots)} with screenshot)")
    for e in proofs:
        w = (e.get("window") or "").lower()
        if w and _is_agent(w):
            bad.append(f"Step '{e['step']}' screenshot shows this app, not the work")
        elif w and (" - search" in w or "bing.com" in w or "google search" in w):
            bad.append(f"Step '{e['step']}' screenshot shows a web search, not the result")
    wins = [(e.get("window") or "").lower() for e in proofs if e.get("window")]
    for f in files or []:
        name = Path(f).name.lower()
        shown = [w for w in wins if name in w and " - search" not in w]
        if wins and not shown and Path(f).suffix.lower() in OPENABLE:
            bad.append(f"No proof screenshot shows {Path(f).name} open")
    text = " ".join(f"{e.get('step','')} {e.get('check','')} {e.get('window','')}" for e in proofs).lower()
    try:   # what this turn's tools actually reported (opened, typed, pressed, saved...)
        import agent_core
        text += " " + " ".join(agent_core.turn_tool_notes()).lower()
    except Exception:
        pass
    text += " " + " ".join(ok_lines).lower()
    for c in claims or []:
        words = [w for w in "".join(ch if ch.isalnum() else " " for ch in c.lower()).split() if len(w) > 3]
        hit = words and sum(w in text for w in words) >= max(1, len(words) // 2)
        (ok_lines if hit else bad).append(("Backed by proof: " if hit else "Could not verify: ") + c)
    if not proofs and not files:
        bad.append("No proof or files to check. Say what you could not verify.")
    verdict = "pass" if not bad else "needs attention"
    with _lock:
        log = _load("reviews.json", [])
        log.append({"t": time.strftime("%Y-%m-%d %H:%M"), "task": task, "verdict": verdict, "problems": bad})
        _save("reviews.json", log[-300:])
    return {"ok": True, "verdict": verdict, "checked": ok_lines, "problems": bad,
            "message": f"Review: {verdict}." + ("" if not bad else " Tell Pedro: " + "; ".join(bad))}


# ---- open a document (not a program) in its normal app ----
OPENABLE = {".pdf", ".docx", ".doc", ".xlsx", ".xls", ".csv", ".pptx", ".txt", ".md", ".png", ".jpg", ".jpeg"}
open_override: Any = None   # tests


def open_local_file(path: str) -> dict[str, Any]:
    """Open an existing document (PDF, Word, Excel, picture, text) in its usual app. Never runs programs."""
    p = Path(os.path.expandvars(os.path.expanduser(path or "")))
    if p.suffix.lower() not in OPENABLE:
        return {"ok": False, "error": f"Only documents can be opened this way ({', '.join(sorted(OPENABLE))})."}
    if not p.is_file():
        return {"ok": False, "error": f"No file at {p}. Use search_local_files to find it."}
    if open_override is not None:
        open_override(str(p))
    else:
        os.startfile(str(p))  # type: ignore[attr-defined]  # a document, opened by its associated app
        time.sleep(2.5)
    return {"ok": True, "message": f"Opened {p.name}. Check it with take_screenshot, then record_step_proof window='{p.name}'.",
            "path": str(p)}


# ---- saved skills: reusable step lists from finished tasks ----
def _skill_key(name: str) -> str:
    return " ".join("".join(c if c.isalnum() else " " for c in (name or "").lower()).split())[:60]


def save_task_skill(name: str, steps: list[str], when: str = "") -> dict[str, Any]:
    key = _skill_key(name)
    steps = [s.strip() for s in steps or [] if s and s.strip()]
    if not key or not steps:
        return {"ok": False, "error": "Give the skill a name and at least one step."}
    bad = [s for s in steps if any(k in s.lower() for k in ("password", "submit test", "submit exam", "graded"))]
    if bad:
        return {"ok": False, "error": "Skills can't include passwords or graded tests: " + bad[0]}
    with _lock:
        skills = _load("skills.json", {})
        skills[key] = {"name": name, "when": when, "steps": steps[:40], "saved": time.strftime("%Y-%m-%d %H:%M"),
                       "used": skills.get(key, {}).get("used", 0)}
        _save("skills.json", skills)
    return {"ok": True, "message": f"Saved skill '{name}' ({len(steps)} steps)."}


def list_task_skills() -> dict[str, Any]:
    skills = _load("skills.json", {})
    lines = [f"- {s['name']}: {len(s['steps'])} steps" + (f" (use when: {s['when']})" if s.get("when") else "")
             for s in skills.values()]
    return {"ok": True, "message": "\n".join(lines) or "No saved skills yet.", "skills": list(skills)}


def use_task_skill(name: str) -> dict[str, Any]:
    skills = _load("skills.json", {})
    key = _skill_key(name)
    hit = skills.get(key) or next((v for k, v in skills.items() if key and (key in k or k in key)), None)
    if not hit:
        return {"ok": False, "error": f"No skill called '{name}'. " + list_task_skills()["message"]}
    with _lock:
        hit["used"] = hit.get("used", 0) + 1
        skills[_skill_key(hit["name"])] = hit
        _save("skills.json", skills)
    return {"ok": True, "name": hit["name"], "steps": hit["steps"],
            "message": "Follow these steps, still asking before any send/delete:\n" +
                       "\n".join(f"{i}. {s}" for i, s in enumerate(hit["steps"], 1))}


def forget_task_skill(name: str) -> dict[str, Any]:
    with _lock:
        skills = _load("skills.json", {})
        gone = skills.pop(_skill_key(name), None)
        _save("skills.json", skills)
    return {"ok": bool(gone), "message": f"Removed skill '{name}'." if gone else f"No skill called '{name}'."}


# ---- setup checklist ----
def _has_key(name: str) -> bool:
    """True when the key is set (env or the app's .env). Never returns or logs the value."""
    if os.environ.get(name, "").strip():
        return True
    try:
        for line in (Path(__file__).resolve().parent / ".env").read_text(encoding="utf-8").splitlines():
            k, _, v = line.partition("=")
            if k.strip() == name and v.strip().strip('"\''):
                return True
    except Exception:
        pass
    return False


def setup_checklist() -> dict[str, Any]:
    items = []
    def add(ok: bool, what: str, fix: str) -> None:
        items.append({"ok": bool(ok), "item": what, "fix": "" if ok else fix})
    add(_has_key("GEMINI_API_KEY") or _has_key("GOOGLE_API_KEY"), "Gemini key",
        "Settings > paste your Gemini key.")
    add(_has_key("GROQ_API_KEY"), "Backup model key (optional)",
        "Settings > Backup model key, so busy Gemini hours don't stop tasks.")
    wd = Path.home() / "Documents" / "PedroAgent"
    add(wd.is_dir(), f"Work folder {wd}", "It is created on the first task.")
    try:
        import pywinauto  # type: ignore  # noqa: F401
        add(True, "Screen reading (pywinauto)", "")
    except Exception:
        add(False, "Screen reading (pywinauto)", "Reinstall the app; needed for Wingz and proof screenshots.")
    try:
        import remote_access
        phone = bool(remote_access.settings().get("enabled")) and remote_access.token_path().exists()
    except Exception:
        phone = False
    add(phone, "Phone app paired (optional)", "Settings > Connect phone > scan the QR code.")
    done = sum(i["ok"] for i in items)
    lines = [("[x] " if i["ok"] else "[ ] ") + i["item"] + ("" if i["ok"] else " - " + i["fix"]) for i in items]
    return {"ok": True, "message": f"Setup {done}/{len(items)} ready:\n" + "\n".join(lines), "items": items}


DECLARATIONS = [
    {"name": "review_work",
     "description": "Checker step: BEFORE saying a task is done, list your claims and any files you made; this checks them against saved proof and files. Report every 'Could not verify' line honestly.",
     "parameters": {"type": "object", "properties": {
         "task": {"type": "string"},
         "claims": {"type": "array", "items": {"type": "string"}},
         "files": {"type": "array", "items": {"type": "string"}}}, "required": ["task"]}},
    {"name": "save_task_skill",
     "description": "After a task worked, save its steps as a reusable skill (Pedro can say 'do X like last time'). Ask Pedro first if unsure.",
     "parameters": {"type": "object", "properties": {
         "name": {"type": "string"}, "steps": {"type": "array", "items": {"type": "string"}},
         "when": {"type": "string", "description": "When to use it."}}, "required": ["name", "steps"]}},
    {"name": "list_task_skills", "description": "List saved task skills (step lists from finished tasks). Recorded demo skills are list_skills.", "parameters": {"type": "object", "properties": {}}},
    {"name": "use_task_skill", "description": "Get the steps of a saved skill to follow now.",
     "parameters": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}},
    {"name": "forget_task_skill", "description": "Remove a saved skill (only when Pedro asks).",
     "parameters": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}},
    {"name": "open_local_file",
     "description": "Open an existing PDF, Word, Excel, CSV, text or picture file on this PC in its usual app (browsers can't open file:// links). Never runs programs.",
     "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
    {"name": "setup_checklist", "description": "Show what is set up and what is missing (keys, work folder, phone).",
     "parameters": {"type": "object", "properties": {}}},
]
TOOLS = {"review_work": review_work, "save_task_skill": save_task_skill, "list_task_skills": list_task_skills,
         "use_task_skill": use_task_skill, "forget_task_skill": forget_task_skill, "setup_checklist": setup_checklist,
         "open_local_file": open_local_file}
