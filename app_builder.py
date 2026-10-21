"""1.5.0 App Builder: spec first, then a multi-file app in Projects\\PedBot-Builds\\<name>, run it, read its errors,
fix them in a loop, screenshot it, let a free vision model critique the screenshots, polish, and ship.

Free models only: Groq (gpt-oss-120b / 20b) writes code, Gemini (free tier) reviews screenshots.
Installs, GitHub pushes and anything outside the project folder go through approval cards (confirm_action).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import zipfile
from pathlib import Path
from typing import Any, Callable

MAX_FIX_ROUNDS = 4
MAX_POLISH_ROUNDS = 2
ask_override: Callable[[str, int], str] | None = None          # tests: fake model
shot_override: Callable[[Path, Path], dict[str, Any]] | None = None   # tests: fake browser
vision_override: Callable[[str, list[bytes]], str] | None = None
_JOBS: dict[str, dict[str, Any]] = {}
_LOCK = threading.Lock()


def builds_root() -> Path:
    root = Path(os.environ.get("PEDBOT_BUILDS") or (Path.home() / "Projects" / "PedBot-Builds"))
    root.mkdir(parents=True, exist_ok=True)
    return root


def slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", str(name or "").casefold()).strip("-")
    return (s or "app")[:40]


# ---------- models ----------
def _groq(prompt: str, max_tokens: int, model: str) -> str:
    import http.client
    key = os.environ.get("GROQ_API_KEY", "").strip()
    if not key:
        raise RuntimeError("no Groq key")
    import model_pool
    body = {"model": model, "messages": [{"role": "user", "content": prompt}], "max_tokens": max_tokens,
            "temperature": 0.3, "reasoning_effort": "medium", "include_reasoning": False}
    data = json.dumps(body).encode("utf-8")
    if not model_pool.acquire(f"groq:{model}", max_wait=20, tokens=len(data) // 4 + max_tokens):
        raise RuntimeError(f"{model} is at its limit")
    conn = http.client.HTTPSConnection("api.groq.com", timeout=120)
    conn.request("POST", "/openai/v1/chat/completions", body=data, headers={
        "Content-Type": "application/json", "Authorization": f"Bearer {key}", "User-Agent": "PedroAgent/1.5.0"})
    resp = conn.getresponse(); raw = resp.read()
    if resp.status == 429:
        model_pool.cooldown(f"groq:{model}", float(resp.getheader("retry-after") or 20))
    if resp.status != 200:
        raise RuntimeError(f"{model} returned {resp.status}")
    return json.loads(raw)["choices"][0]["message"]["content"] or ""


def ask(prompt: str, max_tokens: int = 6000) -> str:
    """Free models in order: Groq gpt-oss-120b, gpt-oss-20b, then Gemini."""
    if ask_override is not None:
        return ask_override(prompt, max_tokens)
    errors = []
    for model in ("openai/gpt-oss-120b", "openai/gpt-oss-20b"):
        for attempt in range(2):
            try:
                out = _groq(prompt, max_tokens, model)
                if out.strip():
                    return out
            except Exception as exc:
                errors.append(f"{model}: {exc}")
                time.sleep(3 + attempt * 6)
    try:
        import llm
        return llm.text(prompt)
    except Exception as exc:
        errors.append(f"gemini: {exc}")
    raise RuntimeError("No free model answered: " + "; ".join(errors[-3:]))


def look(prompt: str, images: list[bytes]) -> str:
    if vision_override is not None:
        return vision_override(prompt, images)
    import llm
    return llm.text(prompt, images)


def _json(text: str) -> Any:
    import llm
    return llm.json_from(text)


# ---------- browser (run + screenshot + console errors) ----------
def _browser() -> str:
    for cand in (shutil.which("msedge"), os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
                 os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
                 os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
                 shutil.which("google-chrome"), shutil.which("chromium"), "/usr/bin/google-chrome"):
        if cand and Path(cand).is_file():
            return cand
    return ""


def run_and_shoot(project: Path, out_png: Path, width: int = 1280, height: int = 800, page: str = "index.html") -> dict[str, Any]:
    """Open the app headless (its own temporary profile, never Pedro's), save a screenshot, collect console errors."""
    if shot_override is not None:
        return shot_override(project, out_png)
    exe = _browser()
    if not exe:
        return {"ok": False, "errors": ["No Edge or Chrome to run the app."]}
    target = (project / page).resolve()
    if not target.is_file():
        return {"ok": False, "errors": [f"{page} is missing."]}
    profile = tempfile.mkdtemp(prefix="pbb-")
    args = [exe, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check", f"--user-data-dir={profile}",
            "--allow-file-access-from-files", "--hide-scrollbars", f"--window-size={width},{height}",
            "--virtual-time-budget=4000", "--enable-logging=stderr", "--v=0", f"--screenshot={out_png}", target.as_uri()]
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=60,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        log = (proc.stderr or "") + (proc.stdout or "")
    except subprocess.TimeoutExpired:
        log = "TIMEOUT"
    finally:
        shutil.rmtree(profile, ignore_errors=True)
    errors = []
    for line in log.splitlines():
        if "CONSOLE" in line and re.search(r"error|uncaught|failed|not defined|cannot read", line, re.I):
            m = re.search(r'"(.*)", source: (\S+) \((\d+)\)', line)
            errors.append(f"{m.group(1)} ({Path(m.group(2)).name}:{m.group(3)})" if m else line[-300:])
    for ref in re.findall(r'(?:src|href)="([^"#?]+)"', (project / page).read_text(encoding="utf-8", errors="replace")):
        if not re.match(r"^(https?:|data:|mailto:|//)", ref) and not (project / ref).exists():
            errors.append(f"{page} links to a missing file: {ref}")
    return {"ok": out_png.is_file(), "errors": sorted(set(errors))[:20], "shot": str(out_png)}


# ---------- the build ----------
SPEC_PROMPT = """You are a senior product designer and front-end engineer. Write the SPEC for this app as JSON only:
{{"name": "...", "tagline": "...", "screens": [{{"id": "...", "title": "...", "purpose": "...", "components": ["..."]}}],
 "features": ["..."], "data": "what is stored (localStorage keys)", "design": {{"palette": {{"bg": "#..", "surface": "#..",
 "text": "#..", "accent": "#.."}}, "font": "system-ui stack", "style": "..."}},
 "files": [{{"path": "index.html", "role": "..."}}, {{"path": "css/styles.css", "role": "..."}}, {{"path": "js/app.js", "role": "..."}}]}}
Rules: a COMPLETE app, not one basic page: 3-5 screens with navigation, real working features, empty states, validation,
responsive layout (phone and desktop), keyboard friendly, no external CDNs or network calls, plain HTML/CSS/JS only, 4-7 files.
App request: {goal}"""

FILE_PROMPT = """Write the complete file `{path}` for this app. Output ONLY the file content, no fences, no commentary.
Spec: {spec}
Other files and their roles: {files}
{context}Requirements: production quality, every feature in the spec works, no placeholder TODOs, no external URLs,
all ids/classes consistent with the other files, accessible labels, smooth but light CSS. Use the exact relative paths above."""

FIX_PROMPT = """The app has problems. Fix them. Return JSON only: {{"files": [{{"path": "...", "content": "FULL new content"}}]}}
with only the files you change.
Problems:
{problems}
Current files:
{snapshot}"""

CRITIQUE_PROMPT = """You are a strict UI reviewer. These are screenshots of an app (desktop {w1}px and phone {w2}px wide).
Spec: {spec}
List the most important visual and usability problems (layout, spacing, contrast, alignment, overflow, missing states,
anything that looks unfinished). Reply JSON only: {{"score": 1-10, "problems": ["..."]}}."""


def _snapshot(project: Path, budget: int = 60000) -> str:
    parts = []
    for f in sorted(project.rglob("*")):
        if f.is_file() and f.suffix in (".html", ".css", ".js", ".json", ".md") and "dist" not in f.parts:
            body = f.read_text(encoding="utf-8", errors="replace")
            parts.append(f"=== {f.relative_to(project).as_posix()} ===\n{body}")
    text = "\n\n".join(parts)
    return text[:budget]


def _safe_write(project: Path, rel: str, content: str) -> Path:
    rel = rel.replace("\\", "/").lstrip("/")
    target = (project / rel).resolve()
    if project.resolve() not in target.parents and target != project.resolve():
        raise ValueError(f"refusing to write outside the project: {rel}")
    target.parent.mkdir(parents=True, exist_ok=True)
    content = re.sub(r"^```[a-zA-Z0-9]*\n|\n```\s*$", "", content.strip()) + "\n"
    target.write_text(content, encoding="utf-8")
    return target


def _log(job: dict[str, Any], text: str) -> None:
    job["log"].append(f"{time.strftime('%H:%M:%S')} {text}")
    job["step"] = text
    try:
        (Path(job["dir"]) / "BUILD_LOG.txt").write_text("\n".join(job["log"]) + "\n", encoding="utf-8")
    except Exception:
        pass


def build(goal: str, name: str = "", job: dict[str, Any] | None = None) -> dict[str, Any]:
    started = time.monotonic()
    project = builds_root() / slug(name or goal[:30])
    project.mkdir(parents=True, exist_ok=True)
    job = job if job is not None else {"log": [], "dir": str(project)}
    job.update(dir=str(project), status="running")
    shots = project / "screenshots"; shots.mkdir(exist_ok=True)
    # 1) spec
    _log(job, "Writing the spec")
    spec = _json(ask(SPEC_PROMPT.format(goal=goal), 3000))
    (project / "SPEC.json").write_text(json.dumps(spec, indent=2), encoding="utf-8")
    files = [f for f in spec.get("files", []) if f.get("path")][:8] or [{"path": "index.html", "role": "app"}]
    roles = json.dumps(files)
    spec_text = json.dumps({k: spec.get(k) for k in ("name", "screens", "features", "data", "design")})[:6000]
    # 2) files (HTML last so it can reference everything; JS sees the HTML ids)
    order = sorted(files, key=lambda f: (f["path"].endswith(".html"), f["path"].endswith(".js")))
    order = [f for f in order if not f["path"].endswith(".html")] + [f for f in order if f["path"].endswith(".html")]
    for f in order:
        _log(job, f"Writing {f['path']}")
        context = ""
        written = _snapshot(project, 24000)
        if written:
            context = f"Files already written (match their ids, classes and functions):\n{written}\n"
        _safe_write(project, f["path"], ask(FILE_PROMPT.format(path=f["path"], spec=spec_text, files=roles, context=context), 8000))
    history: list[dict[str, Any]] = []
    # 3) run -> errors -> fix loop
    for round_no in range(1, MAX_FIX_ROUNDS + 1):
        res = run_and_shoot(project, shots / f"run{round_no}.png")
        history.append({"round": round_no, "errors": res.get("errors", [])})
        _log(job, f"Run {round_no}: {len(res.get('errors', []))} error(s)")
        if not res.get("errors"):
            break
        fix = _json(ask(FIX_PROMPT.format(problems="\n".join(res["errors"]), snapshot=_snapshot(project)), 12000))
        for f in (fix.get("files") or [])[:8]:
            if f.get("path") and f.get("content"):
                _safe_write(project, f["path"], f["content"])
    # 4) screenshots -> vision critique -> polish
    scores = []
    for polish in range(1, MAX_POLISH_ROUNDS + 1):
        desk, phone = shots / f"desktop{polish}.png", shots / f"phone{polish}.png"
        run_and_shoot(project, desk, 1280, 800); run_and_shoot(project, phone, 390, 844)
        imgs = [p.read_bytes() for p in (desk, phone) if p.is_file()]
        if not imgs:
            break
        _log(job, f"Reviewing screenshots (round {polish})")
        try:
            review = _json(look(CRITIQUE_PROMPT.format(w1=1280, w2=390, spec=spec_text[:2000]), imgs))
        except Exception as exc:
            _log(job, f"Vision review unavailable: {type(exc).__name__}")
            break
        scores.append(review.get("score"))
        probs = [str(p) for p in review.get("problems", [])][:10]
        history.append({"review": polish, "score": review.get("score"), "problems": probs})
        if not probs or (isinstance(review.get("score"), (int, float)) and review["score"] >= 9):
            break
        _log(job, f"Polishing: {len(probs)} issue(s), score {review.get('score')}")
        fix = _json(ask(FIX_PROMPT.format(problems="UI review:\n- " + "\n- ".join(probs), snapshot=_snapshot(project)), 12000))
        for f in (fix.get("files") or [])[:8]:
            if f.get("path") and f.get("content"):
                _safe_write(project, f["path"], f["content"])
        res = run_and_shoot(project, shots / f"after_polish{polish}.png")
        if res.get("errors"):
            history.append({"after_polish": polish, "errors": res["errors"]})
    final_d, final_p = shots / "final_desktop.png", shots / "final_phone.png"
    final = run_and_shoot(project, final_d, 1280, 800); run_and_shoot(project, final_p, 390, 844)
    # 5) ship as a website zip (installer / APK / GitHub need approval: ship_app)
    dist = project / "dist"; dist.mkdir(exist_ok=True)
    site = dist / f"{project.name}-website.zip"
    with zipfile.ZipFile(site, "w", zipfile.ZIP_DEFLATED) as z:
        for f in project.rglob("*"):
            if f.is_file() and not ({"dist", "screenshots"} & set(f.relative_to(project).parts)) and f.name != "BUILD_LOG.txt":
                z.write(f, f.relative_to(project).as_posix())
    out = {"ok": True, "project": str(project), "spec": spec.get("name"), "screens": len(spec.get("screens", [])),
           "files": sorted(p.relative_to(project).as_posix() for p in project.rglob("*") if p.is_file()
                           and not ({"dist", "screenshots"} & set(p.relative_to(project).parts))),
           "final_errors": final.get("errors", []), "scores": scores, "history": history,
           "screenshots": [str(final_d), str(final_p)], "website_zip": str(site),
           "seconds": round(time.monotonic() - started, 1)}
    (project / "BUILD_REPORT.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    job.update(status="done", result=out)
    _log(job, f"Done in {out['seconds']} s")
    return out


# ---------- tools ----------
def build_app(goal: str, name: str = "") -> dict[str, Any]:
    """Start a build in the background (never blocks chat). Poll with app_builder_status."""
    key = slug(name or goal[:30])
    with _LOCK:
        if key in _JOBS and _JOBS[key].get("status") == "running":
            return {"ok": True, "message": f"'{key}' is already building: {_JOBS[key].get('step')}", "name": key}
        job = {"log": [], "dir": str(builds_root() / key), "status": "running", "goal": goal}
        _JOBS[key] = job

    def run() -> None:
        try:
            build(goal, key, job)
        except Exception as exc:
            job.update(status="failed", error=f"{type(exc).__name__}: {exc}")
            _log(job, f"Failed: {exc}")
    threading.Thread(target=run, daemon=True, name=f"app-builder-{key}").start()
    return {"ok": True, "name": key, "project": job["dir"],
            "message": f"Started building '{key}' in {job['dir']}: spec, files, run and fix, screenshots, review, polish. "
                       "Ask me for app_builder_status to follow it."}


def app_builder_status(name: str = "") -> dict[str, Any]:
    key = slug(name) if name else (next(reversed(_JOBS)) if _JOBS else "")
    job = _JOBS.get(key)
    if job is None:
        report = builds_root() / key / "BUILD_REPORT.json"
        if key and report.is_file():
            return {"ok": True, "status": "done", "result": json.loads(report.read_text(encoding="utf-8"))}
        return {"ok": False, "error": "No build with that name."}
    res = {k: v for k, v in job.items() if k in ("status", "step", "dir", "error")}
    res["recent"] = job["log"][-6:]
    if job.get("result"):
        r = job["result"]
        res["result"] = {k: r.get(k) for k in ("project", "files", "final_errors", "scores", "screenshots", "website_zip", "seconds")}
    return {"ok": True, **res}


_INSTALLERS = {"pip": ["{py}", "-m", "pip", "install", "--user"], "npm": ["npm", "install", "-g"],
               "winget": ["winget", "install", "--accept-source-agreements", "--accept-package-agreements", "-e", "--id"]}


def builder_install(manager: str, package: str) -> dict[str, Any]:
    """Install one package/tool (pip, npm or winget). Always behind an approval card."""
    mgr = str(manager or "").casefold().strip()
    pkg = str(package or "").strip()
    if mgr not in _INSTALLERS or not re.fullmatch(r"[A-Za-z0-9_.@/+=<>\-]{1,120}", pkg):
        return {"ok": False, "error": "Say pip, npm or winget and one package name."}
    import sys
    cmd = [c.replace("{py}", sys.executable) for c in _INSTALLERS[mgr]] + [pkg]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=900,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except FileNotFoundError:
        return {"ok": False, "error": f"{mgr} is not installed on this PC."}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"Installing {pkg} took over 15 minutes and was stopped."}
    tail = (proc.stdout + proc.stderr)[-800:]
    return {"ok": proc.returncode == 0, "message" if proc.returncode == 0 else "error":
            (f"Installed {pkg} with {mgr}." if proc.returncode == 0 else f"{mgr} failed for {pkg}: {tail}")}


def ship_app(name: str, target: str = "website", repo: str = "") -> dict[str, Any]:
    """website: the zip (already made). github: push the project to a NEW repo (approval card; needs gh signed in)."""
    project = builds_root() / slug(name)
    if not project.is_dir():
        return {"ok": False, "error": "No such project."}
    target = str(target or "website").casefold()
    if target == "website":
        z = project / "dist" / f"{project.name}-website.zip"
        return {"ok": z.is_file(), "message": f"Website package: {z}. Upload the folder to any static host (e.g. GitHub Pages)."}
    if target == "github":
        gh = shutil.which("gh")
        if not gh:
            return {"ok": False, "error": "GitHub CLI (gh) is not installed. Ask me to install it with winget first."}
        repo = re.sub(r"[^A-Za-z0-9._-]", "-", repo or project.name)
        steps = [["git", "init", "-q"], ["git", "add", "-A"], ["git", "commit", "-qm", "First version by Ped Bot App Builder"],
                 [gh, "repo", "create", repo, "--private", "--source", ".", "--push"]]
        for s in steps:
            p = subprocess.run(s, cwd=project, capture_output=True, text=True, timeout=300,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if p.returncode != 0 and s[1] != "commit":
                return {"ok": False, "error": f"{' '.join(s[:3])} failed: {(p.stderr or p.stdout)[-400:]}"}
        return {"ok": True, "message": f"Pushed to a new PRIVATE GitHub repo '{repo}'."}
    return {"ok": False, "error": "Windows installer and APK packaging are not in this version yet; use website or github."}


DECLARATIONS = [
    {"name": "build_app", "description": "App Builder: build a complete multi-screen app (spec first, files, run, fix errors, "
     "screenshots, vision review, polish) in Projects\\PedBot-Builds\\<name>. Runs in the background.",
     "parameters": {"type": "object", "properties": {"goal": {"type": "string"}, "name": {"type": "string"}}, "required": ["goal"]}},
    {"name": "app_builder_status", "description": "Progress and result of an App Builder build.",
     "parameters": {"type": "object", "properties": {"name": {"type": "string"}}}},
    {"name": "builder_install", "description": "Install a package/tool for a build with pip, npm or winget (approval card).",
     "parameters": {"type": "object", "properties": {"manager": {"type": "string"}, "package": {"type": "string"}},
                    "required": ["manager", "package"]}},
    {"name": "ship_app", "description": "Ship a built app: target website (zip) or github (new private repo; approval card).",
     "parameters": {"type": "object", "properties": {"name": {"type": "string"}, "target": {"type": "string"},
                                                     "repo": {"type": "string"}}, "required": ["name"]}},
]
TOOLS = {"build_app": build_app, "app_builder_status": app_builder_status, "builder_install": builder_install, "ship_app": ship_app}
SENSITIVE = {"builder_install"}
