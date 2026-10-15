"""General multi-step tasks: plan -> act -> verify, with real screenshots,
documents, Store-app launching and WhatsApp Web sending.

The agent's own tool loop does the planning (create_task_plan / complete_plan_step,
shown live in the UI). This module adds the missing building blocks:

  capture_screenshot_file   real screenshot (optional crop) saved for documents
  verify_screen             screenshot + Gemini vision yes/no check, with retries
  launch_any_app            normal apps, Store apps (shell:AppsFolder) or a URL
  make_document             PDF (reportlab) or Word (python-docx) from steps + screenshots
  whatsapp_prepare          open WhatsApp Web in a logged-in browser, open the chat,
                            CHECK the contact name, attach file, type caption (no send)
  whatsapp_send_now         press Send (needs your yes: confirm category send_message)
  confirm_before            pause for a yes before any send/delete/purchase/form submit
  start_task / save_task_routine / list_task_routines / get_task_routine
                            reusable routines learned from finished tasks

Graded tests/exams/quizzes are refused (start_task + get_task_routine).
"""

from __future__ import annotations

import difflib
import io
import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any, Callable

GRADED = re.compile(r"\b(graded|exam|midterm|final test|quiz|proctored|online test|assessment test|mcq test|"
                    r"timed test|certification test|answer (the|my) (test|exam|quiz))\b", re.I)
SELF_LEARN_OK = re.compile(r"\b(self[- ]?learn|practice|assignment|homework|project)\b", re.I)

# ---- test seams (tests replace these) ----
grab_png: Callable[[], bytes] | None = None
vision: Callable[[str, bytes], str] | None = None
keys: Callable[..., None] | None = None
paste_text: Callable[[str], None] | None = None
set_clipboard_file: Callable[[str], None] | None = None
open_url: Callable[[str, str], None] | None = None
sleep: Callable[[float], None] = time.sleep


def _ok(msg: str, **kw: Any) -> dict[str, Any]:
    return {"ok": True, "message": msg, **kw}


def _err(msg: str, **kw: Any) -> dict[str, Any]:
    return {"ok": False, "error": msg, **kw}


def _storage() -> Path:
    import agent_config

    return agent_config.storage_dir()


def desktop() -> Path:
    if os.name == "nt":
        try:
            out = subprocess.run(["powershell", "-NoProfile", "-Command", "[Environment]::GetFolderPath('Desktop')"],
                                 capture_output=True, text=True, timeout=10, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if out.stdout.strip():
                return Path(out.stdout.strip())
        except Exception:
            pass
    return Path.home() / "Desktop"


def is_graded_test(text: str) -> bool:
    t = text or ""
    return bool(GRADED.search(t)) and not re.search(r"\bnot (a )?graded\b|\bungraded\b", t, re.I)


# ---------------- screen ----------------
def _grab() -> bytes:
    if grab_png is not None:
        return grab_png()
    import mss
    import mss.tools

    with mss.mss() as sct:
        shot = sct.grab(sct.monitors[1])
        return mss.tools.to_png(shot.rgb, shot.size)


def _shots_dir() -> Path:
    d = _storage() / "task_shots"
    d.mkdir(parents=True, exist_ok=True)
    return d


def capture_screenshot_file(name: str = "", crop: Any = None) -> dict[str, Any]:
    """crop = [left, top, right, bottom] in 0-1000 grid (like click_element)."""
    from PIL import Image

    img = Image.open(io.BytesIO(_grab())).convert("RGB")
    if crop:
        try:
            l, t, r, b = [max(0.0, min(1000.0, float(v))) for v in list(crop)[:4]]
            if r - l < 10 or b - t < 10:
                return _err("crop box is too small.")
            w, h = img.size
            img = img.crop((int(l * w / 1000), int(t * h / 1000), int(r * w / 1000), int(b * h / 1000)))
        except Exception:
            return _err("crop must be [left, top, right, bottom] on a 0-1000 grid.")
    stem = re.sub(r"[^A-Za-z0-9_-]+", "_", name or "")[:40] or time.strftime("shot_%H%M%S")
    path = _shots_dir() / f"{stem}.png"
    import undo_store
    undo_store.remember(path)
    img.save(path)
    undo_store.seal(path)
    return _ok(f"Saved screenshot {path.name} ({img.size[0]}x{img.size[1]}).", path=str(path),
               width=img.size[0], height=img.size[1])


def _ask_vision(question: str, png: bytes) -> str:
    if vision is not None:
        return vision(question, png)
    from google import genai
    from google.genai import types

    import rules

    models = (rules.load().get("agent") or {}).get("models") or [os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")]
    client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY", ""))
    last = None
    for model in models:
        try:
            r = client.models.generate_content(model=model, contents=[
                types.Part.from_bytes(data=png, mime_type="image/png"), question])
            return (r.text or "").strip()
        except Exception as exc:  # quota -> next model
            last = exc
    raise RuntimeError(f"vision check failed: {last}")


def verify_screen(expectation: str, retries: int = 2, wait_seconds: float = 2.0) -> dict[str, Any]:
    """Screenshot + vision: does the screen show `expectation`? Retries while waiting."""
    if not (expectation or "").strip():
        return _err("Say what the screen should show.")
    q = ("Look at this screenshot. Question: does it show the following? " + expectation.strip() +
         "\nAnswer on the first line with exactly YES or NO, then one short reason.")
    reason = ""
    for attempt in range(max(1, int(retries) + 1)):
        try:
            ans = _ask_vision(q, _grab())
        except Exception as exc:
            return _err(str(exc))
        first = ans.strip().splitlines()[0].strip().upper() if ans.strip() else ""
        reason = ans.strip()[:300]
        if first.startswith("YES"):
            return _ok("Verified: " + expectation, verified=True, attempts=attempt + 1, reason=reason)
        if attempt < retries:
            sleep(float(wait_seconds))
    return _ok("Not verified yet: " + expectation, verified=False, attempts=retries + 1, reason=reason)


# ---------------- apps ----------------
def _ps(cmd: str, timeout: int = 20) -> str:
    out = subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True, text=True,
                         timeout=timeout, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return out.stdout


def store_app_id(name: str, apps: list[dict[str, str]] | None = None) -> str:
    """Best AppID for a Start-menu app name (Get-StartApps)."""
    if apps is None:
        raw = _ps("Get-StartApps | Select-Object Name,AppID | ConvertTo-Json -Compress")
        apps = json.loads(raw or "[]")
        apps = apps if isinstance(apps, list) else [apps]
    want = (name or "").casefold().strip()
    names = {a["Name"].casefold(): a["AppID"] for a in apps if a.get("Name") and a.get("AppID")}
    if want in names:
        return names[want]
    starts = [n for n in names if n.startswith(want) or want in n]
    if starts:
        return names[sorted(starts, key=len)[0]]
    close = difflib.get_close_matches(want, list(names), n=1, cutoff=0.6)
    return names[close[0]] if close else ""


def launch_any_app(name: str) -> dict[str, Any]:
    """Open an app by name: normal programs first, then Store apps via shell:AppsFolder."""
    if not (name or "").strip():
        return _err("Which app?")
    if re.match(r"https?://", name.strip()):
        import webbrowser

        webbrowser.open(name.strip())
        return _ok(f"Opened {name.strip()}.")
    try:
        import agent_core

        r = agent_core.launch_application(name)
        if r.get("ok"):
            return r
    except Exception:
        pass
    if os.name != "nt":
        return _err(f"Couldn't find {name}.")
    app_id = store_app_id(name)
    if not app_id:
        return _err(f"Couldn't find an app called {name} in the Start menu.")
    subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{app_id}"])
    return _ok(f"Opened {name} (Start menu app).", app_id=app_id)


# ---------------- documents ----------------
def _safe_name(title: str, ext: str) -> str:
    base = re.sub(r"[^A-Za-z0-9 _-]+", "", title or "").strip().replace(" ", "_")[:80] or "Document"
    return base + ext


def _steps(steps: Any) -> list[dict[str, str]]:
    out = []
    for s in steps or []:
        if isinstance(s, str):
            s = {"text": s}
        if isinstance(s, dict) and (s.get("text") or s.get("image")):
            out.append({"text": str(s.get("text") or ""), "image": str(s.get("image") or "")})
    return out


def _out_folder(folder: str) -> tuple[Path | None, str]:
    """Where to save: Desktop by default; a user-named folder if rules.yaml allows it.
    A folder on a drive that isn't plugged in falls back to the local PedroAgent folder (never required)."""
    if not folder:
        return desktop(), ""
    raw = str(folder).strip()
    named = {"desktop": desktop(), "documents": Path.home() / "Documents", "downloads": Path.home() / "Downloads"}
    out = named.get(raw.casefold().strip("\\/")) or Path(os.path.expandvars(raw)).expanduser()
    if not out.is_absolute():
        out = Path.home() / out
    note = ""
    if os.name == "nt" and out.drive and not Path(out.drive + "\\").exists():
        import agent_config

        fallback = agent_config.default_output_dir()
        note = f" Drive {out.drive} isn't connected, so I saved it locally instead."
        out = fallback
    try:
        import rules

        if not rules.path_allowed(out):
            return None, (f"rules.yaml doesn't allow saving in {out}. Pick a folder in your user profile "
                          f"(for example {desktop()}) or allow it in paths.allowed.")
    except Exception:
        pass
    return out, note


def make_document(title: str, steps: Any, format: str = "pdf", folder: str = "", headings: bool = False,
                  overwrite: bool = False) -> dict[str, Any]:
    """steps: [{text, image}] -> numbered steps with screenshots. Saved to the Desktop by default.
    headings=False: no title/intro/conclusion (straight to the steps)."""
    items = _steps(steps)
    if not items:
        return _err("Give at least one step (text and/or image path).")
    for it in items:
        if it["image"] and not Path(it["image"]).is_file():
            return _err(f"Image not found: {it['image']}")
    fmt = (format or "pdf").casefold().lstrip(".")
    if fmt not in {"pdf", "docx"}:
        return _err("format must be pdf or docx.")
    out_dir, note = _out_folder(folder)
    if out_dir is None:
        return _err(note)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / _safe_name(title, "." + fmt)
    if path.exists() and not overwrite:
        n = 2
        while (out_dir / _safe_name(f"{title} {n}", "." + fmt)).exists():
            n += 1
        path = out_dir / _safe_name(f"{title} {n}", "." + fmt)
    import undo_store
    undo_store.remember(path)
    (_pdf if fmt == "pdf" else _docx)(path, title, items, headings)
    undo_store.seal(path)
    return _ok(f"Saved {path.name} with {len(items)} steps at {path}.{note}", path=str(path), steps=len(items))


def _pdf(path: Path, title: str, items: list[dict[str, str]], headings: bool) -> None:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import Image as RLImage, KeepTogether, Paragraph, SimpleDocTemplate, Spacer
    from PIL import Image

    ss = getSampleStyleSheet(); doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm,
                                                        topMargin=2 * cm, bottomMargin=2 * cm)
    flow: list[Any] = []
    if headings and title:
        flow += [Paragraph(title, ss["Title"]), Spacer(1, 10)]
    maxw, maxh = doc.width, doc.height * 0.62
    for i, it in enumerate(items, 1):
        block: list[Any] = [Paragraph(f"<b>Step {i}.</b> " + _esc(it["text"]), ss["BodyText"]), Spacer(1, 6)]
        if it["image"]:
            w, h = Image.open(it["image"]).size
            k = min(maxw / w, maxh / h, 1.0 if w < maxw else 99)
            block.append(RLImage(it["image"], width=w * k, height=h * k))
        block.append(Spacer(1, 16))
        flow.append(KeepTogether(block))
    doc.build(flow)


def _esc(t: str) -> str:
    return (t or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _docx(path: Path, title: str, items: list[dict[str, str]], headings: bool) -> None:
    from docx import Document
    from docx.shared import Inches

    d = Document()
    if headings and title:
        d.add_heading(title, 0)
    for i, it in enumerate(items, 1):
        p = d.add_paragraph(); p.add_run(f"Step {i}. ").bold = True; p.add_run(it["text"])
        if it["image"]:
            d.add_picture(it["image"], width=Inches(6))
    d.save(str(path))


# ---------------- WhatsApp Web ----------------
_wa: dict[str, Any] = {}


def _keys(*k: str) -> None:
    if keys is not None:
        return keys(*k)
    import pyautogui

    pyautogui.hotkey(*k) if len(k) > 1 else pyautogui.press(k[0])


def _paste(text: str) -> None:
    if paste_text is not None:
        return paste_text(text)
    import pyperclip

    pyperclip.copy(text); _keys("ctrl", "v")


def _clip_file(path: str) -> None:
    if set_clipboard_file is not None:
        return set_clipboard_file(path)
    _ps(f"Set-Clipboard -Path '{path.replace(chr(39), chr(39) * 2)}'")


def _open(browser: str, url: str) -> None:
    if open_url is not None:
        return open_url(browser, url)
    exe = {"edge": "msedge", "chrome": "chrome", "firefox": "firefox", "brave": "brave"}.get(browser.casefold(), "")
    if exe and os.name == "nt":
        subprocess.Popen(["cmd", "/c", "start", "", exe, url], creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    else:
        import webbrowser

        webbrowser.open(url)


def _names_match(seen: str, want: str) -> bool:
    a = re.sub(r"[^a-z0-9 ]", "", (seen or "").casefold()).strip()
    b = re.sub(r"[^a-z0-9 ]", "", (want or "").casefold()).strip()
    return bool(a and b) and (a == b or a.startswith(b) or difflib.SequenceMatcher(None, a, b).ratio() >= 0.85)


def whatsapp_prepare(contact: str, file_path: str = "", caption: str = "", browser: str = "") -> dict[str, Any]:
    """Open the chat and stage the message WITHOUT sending. Then ask the user and call whatsapp_send_now."""
    if not (contact or "").strip():
        return _err("Who should get it?")
    if file_path and not Path(file_path).is_file():
        return _err(f"File not found: {file_path}")
    if not file_path and not caption:
        return _err("Nothing to send.")
    tried = [browser] if browser else ["edge", "chrome", "firefox", "brave"]
    logged = False
    for b in tried:
        _open(b, "https://web.whatsapp.com/"); sleep(6)
        v = verify_screen("WhatsApp Web is open and logged in, showing the chat list (not a QR code)", retries=3, wait_seconds=3)
        if v.get("verified"):
            logged, browser = True, b
            break
    if not logged:
        return _err("WhatsApp Web isn't logged in in any browser I tried. Open it and scan the QR code first.", browsers=tried)
    _keys("ctrl", "alt", "/"); sleep(1); _paste(contact.strip()); sleep(2); _keys("enter"); sleep(2)
    seen = _ask_vision("This is WhatsApp Web. Reply with ONLY the exact name shown at the top of the open chat "
                       "(the header above the messages). If no chat is open, reply NONE.", _grab()).strip().splitlines()[0:1]
    seen_name = seen[0].strip().strip('"') if seen else ""
    if not _names_match(seen_name, contact):
        _keys("escape")
        return _err(f"The open chat is '{seen_name or 'none'}', not '{contact}'. Nothing was staged or sent.",
                    seen=seen_name)
    if file_path:
        _clip_file(str(Path(file_path).resolve())); sleep(0.5); _keys("ctrl", "v"); sleep(3)
    if caption:
        _paste(caption); sleep(0.5)
    shot = capture_screenshot_file("whatsapp_preview")
    _wa.clear(); _wa.update(contact=seen_name, file=file_path, caption=caption, browser=browser, at=time.time())
    return _ok(f"Ready to send to {seen_name} in {browser}. Ask the user, then call whatsapp_send_now.",
               contact=seen_name, browser=browser, preview=shot.get("path"), needs_send=True)


def whatsapp_send_now(contact: str) -> dict[str, Any]:
    """Press Send on the staged WhatsApp message (needs a yes)."""
    if not _wa or time.time() - _wa.get("at", 0) > 600:
        return _err("Nothing is staged. Call whatsapp_prepare first.")
    if not _names_match(_wa["contact"], contact):
        return _err(f"The staged message is for {_wa['contact']}, not {contact}.")
    _keys("enter"); sleep(3)
    v = verify_screen("the last message in the open chat was just sent (a single or double tick or clock icon)",
                      retries=2, wait_seconds=3)
    staged = dict(_wa); _wa.clear()
    return _ok(f"Sent to {staged['contact']}." if v.get("verified") else
               f"Pressed Send for {staged['contact']}, but I couldn't confirm it on screen.",
               verified=bool(v.get("verified")), contact=staged["contact"])


def confirm_before(kind: str, description: str) -> dict[str, Any]:
    """Call right before a send / delete / purchase / form submit done by clicking.
    rules.yaml confirm categories decide whether it asks."""
    return _ok(f"Approved: {description}", approved=True, kind=kind)


# ---------------- routines (skills from finished tasks) ----------------
BUILTIN = {
    "assignment-to-pdf-whatsapp": {
        "name": "assignment-to-pdf-whatsapp",
        "description": "Read a self-learn assignment in the browser, do it in the right app, take real screenshots, "
                       "make a step-by-step PDF on the Desktop, then send it on WhatsApp Web after a yes.",
        "inputs": ["contact (optional)", "caption (optional)"],
        "steps": [
            "Take a screenshot and read the assignment text in the browser (verify_screen that it is a self-learn assignment, not a graded test).",
            "Plan the work with create_task_plan (one step per thing the task asks for).",
            "Open the needed app with launch_any_app (Store apps work too) and load any files the task gives.",
            "Do each part; after each one call verify_screen for the expected result, retry or fix on NO.",
            "After each finished part call capture_screenshot_file (crop away notifications if needed).",
            "Call make_document(title, steps=[{text, image}], format='pdf') - no title/intro/conclusion unless asked; it saves to the Desktop.",
            "If a contact was given: whatsapp_prepare(contact, file_path, caption), show the user, and only after a yes call whatsapp_send_now.",
        ],
        "builtin": True,
    },
    "webpage-to-pdf": {
        "name": "webpage-to-pdf",
        "description": "Open a web page, capture it as real screenshots and save a short PDF on the Desktop.",
        "inputs": ["url", "title"],
        "steps": [
            "open_website(url) and verify_screen that the page has loaded.",
            "capture_screenshot_file for the top of the page; scroll and capture again if the user wants more.",
            "make_document(title, steps with a one-line description per screenshot, format='pdf').",
            "Tell the user the saved path. Do not send it anywhere unless asked.",
        ],
        "builtin": True,
    },
}


def _routines_dir() -> Path:
    d = _storage() / "task_routines"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _rslug(v: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (v or "").casefold()).strip("-")[:50]


_STOP = {"the", "and", "for", "with", "then", "make", "send", "into", "from", "this", "that", "my", "your", "page"}


def start_task(goal: str) -> dict[str, Any]:
    """Call first for a multi-step task: refuses graded tests and suggests a saved routine."""
    if is_graded_test(goal):
        return _err("I won't take graded tests, exams or quizzes. I can help you study or practise instead.",
                    refused=True)
    words = lambda t: {w for w in re.findall(r"[a-z]{3,}", t.casefold()) if w not in _STOP}
    g = words(goal)
    best, score = None, 0.0
    for r in list_task_routines()["routines"]:
        rw = words(r["name"].replace("-", " ") + " " + r["description"])
        s = len(g & rw) / max(1, len(g))
        if s > score:
            best, score = r, s
    hint = {"suggested_routine": best["name"]} if best and score >= 0.3 else {}
    return _ok("Plan it with create_task_plan, act, verify each step with verify_screen, and save a routine at the end "
               "with save_task_routine if it worked.", **hint)


def save_task_routine(name: str, description: str = "", steps: Any = None) -> dict[str, Any]:
    """Save the finished task as a reusable routine. steps defaults to the current plan."""
    slug = _rslug(name)
    if not slug:
        return _err("Give the routine a name.")
    if slug in BUILTIN:
        return _err("That name is a built-in routine; pick another.")
    if not steps:
        try:
            import agent_core

            steps = [s["text"] for s in agent_core._public_steps()]
        except Exception:
            steps = []
    clean = [" ".join(str(s.get("text") if isinstance(s, dict) else s).split())[:500] for s in steps or []]
    clean = [s for s in clean if s]
    if len(clean) < 2:
        return _err("A routine needs at least 2 steps.")
    r = {"name": slug, "description": " ".join((description or "").split())[:300], "steps": clean,
         "builtin": False, "saved": time.time()}
    (_routines_dir() / f"{slug}.json").write_text(json.dumps(r, indent=2), encoding="utf-8")
    return _ok(f"Saved routine {slug} with {len(clean)} steps.", routine=r)


def list_task_routines() -> dict[str, Any]:
    out = [dict(v) for v in BUILTIN.values()]
    for p in sorted(_routines_dir().glob("*.json")):
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            continue
    return _ok(f"{len(out)} routines.", routines=[{"name": r["name"], "description": r.get("description", ""),
                                                   "builtin": r.get("builtin", False)} for r in out])


def get_task_routine(name: str) -> dict[str, Any]:
    slug = _rslug(name)
    r = BUILTIN.get(slug)
    p = _routines_dir() / f"{slug}.json"
    if r is None and p.is_file():
        r = json.loads(p.read_text(encoding="utf-8"))
    if r is None:
        return _err(f"No routine called {name}.")
    return _ok("Follow these steps (plan them with create_task_plan first).", routine=r)


def delete_task_routine(name: str) -> dict[str, Any]:
    slug = _rslug(name)
    p = _routines_dir() / f"{slug}.json"
    if slug in BUILTIN or not p.is_file():
        return _err("Only saved (non built-in) routines can be deleted.")
    p.unlink()
    return _ok(f"Deleted routine {slug}.")


def _decl(name: str, desc: str, props: dict[str, Any], req: list[str]) -> dict[str, Any]:
    return {"name": name, "description": desc, "parameters": {"type": "object", "properties": props, "required": req}}


S = {"type": "string"}
DECLARATIONS = [
    _decl("start_task", "Call FIRST for any multi-step job (read a task, work in apps, make a document, send it). "
          "Refuses graded tests and suggests a saved routine.", {"goal": S}, ["goal"]),
    _decl("capture_screenshot_file", "Save a real screenshot to a file for a document. crop=[left,top,right,bottom] on the 0-1000 grid.",
          {"name": S, "crop": {"type": "array", "items": {"type": "number"}}}, []),
    _decl("verify_screen", "Check the screen with vision: does it show <expectation>? Retries. Use after every important step.",
          {"expectation": S, "retries": {"type": "integer"}, "wait_seconds": {"type": "number"}}, ["expectation"]),
    _decl("launch_any_app", "Open an app by name, including Microsoft Store apps (via shell:AppsFolder), or a URL.",
          {"name": S}, ["name"]),
    _decl("make_document", "Make a PDF or Word document of numbered steps with screenshots; saves to the Desktop. "
          "headings=false means no title/intro/conclusion.",
          {"title": S, "steps": {"type": "array", "items": {"type": "object", "properties": {"text": S, "image": S}}},
           "format": S, "folder": S, "headings": {"type": "boolean"}, "overwrite": {"type": "boolean"}}, ["title", "steps"]),
    _decl("whatsapp_prepare", "Open WhatsApp Web in a logged-in browser, open the contact's chat, CHECK the name, attach the file "
          "and type the caption WITHOUT sending. Then show the user and ask before whatsapp_send_now.",
          {"contact": S, "file_path": S, "caption": S, "browser": S}, ["contact"]),
    _decl("whatsapp_send_now", "Press Send on the message staged by whatsapp_prepare. Only after the user said yes.",
          {"contact": S}, ["contact"]),
    _decl("confirm_before", "Call right before clicking anything that sends, deletes, buys or submits a form. kind = send|delete|purchase|submit.",
          {"kind": S, "description": S}, ["kind", "description"]),
    _decl("save_task_routine", "Save a finished task as a reusable routine (steps default to the current plan).",
          {"name": S, "description": S, "steps": {"type": "array", "items": S}}, ["name"]),
    _decl("list_task_routines", "List saved and built-in task routines.", {}, []),
    _decl("get_task_routine", "Get the steps of a saved routine to follow.", {"name": S}, ["name"]),
    _decl("delete_task_routine", "Delete a saved routine (asks first).", {"name": S}, ["name"]),
]
TOOLS = {"start_task": start_task, "capture_screenshot_file": capture_screenshot_file, "verify_screen": verify_screen,
         "launch_any_app": launch_any_app, "make_document": make_document, "whatsapp_prepare": whatsapp_prepare,
         "whatsapp_send_now": whatsapp_send_now, "confirm_before": confirm_before, "save_task_routine": save_task_routine,
         "list_task_routines": list_task_routines, "get_task_routine": get_task_routine,
         "delete_task_routine": delete_task_routine}
