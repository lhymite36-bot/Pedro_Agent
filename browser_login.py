"""1.4.19: "log in to <site>" - open the site in Pedro's real Chrome profile, let Chrome fill his SAVED login,
and press Sign in. Ped Bot never reads, stores or types a password. One-time codes are asked for in chat.

Graded tests and marked submissions: guide and check only; never press the final Submit (see the prompt rule).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

SITES = {
    "itvedant": "https://wingz.itvedant.com/site/login",
    "wingz": "https://wingz.itvedant.com/site/login",
    "gmail": "https://mail.google.com/",
    "youtube": "https://accounts.google.com/ServiceLogin?service=youtube",
    "github": "https://github.com/login",
    "linkedin": "https://www.linkedin.com/login",
}
_SIGN_IN = re.compile(r"^(sign ?in|log ?in|login|continue|next|submit login|sign in with google|login with google|"
                      r"continue with google)$", re.I)
_OTP = re.compile(r"\b(otp|one[- ]time|verification code|enter (?:the )?code|2-step|two[- ]step|authenticator)\b", re.I)
_LOGIN_PAGE = re.compile(r"\b(password|sign ?in|log ?in)\b", re.I)
open_override: Any = None     # tests: replace the real Chrome / UI automation
page_override: Any = None


def site_url(site: str) -> str:
    raw = " ".join(str(site or "").split())
    key = raw.casefold().replace("www.", "").split(".")[0] if raw else ""
    if key in SITES:
        return SITES[key]
    if re.match(r"^https?://", raw, re.I):
        return raw
    if "." in raw and " " not in raw:
        return "https://" + raw
    return ""


def _chrome() -> str:
    for cand in (shutil.which("chrome"), os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
                 os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
                 os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe")):
        if cand and Path(cand).is_file():
            return cand
    return ""


def _chrome_window(host: str) -> Any:
    from pywinauto import Desktop  # type: ignore
    wins = [w for w in Desktop(backend="uia").windows(visible_only=True) if "Google Chrome" in (w.window_text() or "")]
    wins.sort(key=lambda w: 0 if host.split(".")[-2:][0] in (w.window_text() or "").casefold() else 1)
    return wins[0] if wins else None


def _page(win: Any) -> tuple[list[str], list[Any]]:
    """Visible text lines and the clickable sign-in controls (names only; field values are never read)."""
    lines: list[str] = []
    buttons: list[Any] = []
    docs = win.descendants(control_type="Document")
    root = docs[0] if docs else win
    for i, el in enumerate(root.descendants()):
        if i > 3000:
            break
        try:
            kind = el.element_info.control_type
            if kind == "Edit":
                continue   # never touch input values (that is where a password lives)
            name = " ".join((el.window_text() or "").split())
        except Exception:
            continue
        if not name:
            continue
        lines.append(name)
        if kind in ("Button", "Hyperlink") and _SIGN_IN.match(name):
            buttons.append(el)
    return lines, buttons


def login(site: str = "") -> dict[str, Any]:
    url = site_url(site)
    if not url:
        return {"ok": False, "error": f"I don't know which website '{site}' is. Tell me its address, e.g. example.com."}
    host = urlparse(url).netloc.casefold()
    if open_override is not None:
        return open_override(url)
    chrome = _chrome()
    if not chrome:
        return {"ok": False, "error": "Google Chrome is not installed, so I can't use your saved Chrome logins."}
    # his everyday Chrome profile: saved passwords, Google account and cookies stay in Chrome
    subprocess.Popen([chrome, "--profile-directory=Default", url], close_fds=True)
    steps = [f"Opened {url} in your Chrome."]
    win = None
    for _ in range(20):
        time.sleep(0.75)
        try:
            win = _chrome_window(host)
        except Exception:
            win = None
        if win is not None:
            break
    if win is None:
        return {"ok": False, "error": "Chrome opened but I could not find its window to press Sign in. "
                                      "Please press Sign in yourself.", "steps": steps}
    time.sleep(2.5)   # give Chrome a moment to autofill the saved login
    try:
        lines, buttons = _page(win)
    except Exception as exc:
        return {"ok": False, "error": f"I could not read the page ({type(exc).__name__}). Please sign in yourself."}
    text = " ".join(lines)
    if not _LOGIN_PAGE.search(text):
        return {"ok": True, "message": f"{host} is open and you already look signed in. " + " ".join(steps),
                "signed_in": True}
    if not buttons:
        return {"ok": False, "error": f"{host} is open, but I can't find its Sign in button. Please sign in yourself."}
    google = [b for b in buttons if "google" in (b.window_text() or "").casefold()]
    target = (google or buttons)[0]
    label = " ".join((target.window_text() or "Sign in").split())
    try:
        target.invoke()
    except Exception:
        try:
            target.click_input()
        except Exception as exc:
            return {"ok": False, "error": f"Pressing '{label}' failed ({type(exc).__name__}). Please sign in yourself."}
    steps.append(f"Pressed '{label}' (Chrome filled your saved login; I never saw or typed a password).")
    time.sleep(5)
    try:
        lines, buttons = _page(_chrome_window(host) or win)
        text = " ".join(lines)
    except Exception:
        text = ""
    if _OTP.search(text):
        return {"ok": True, "needs_code": True, "steps": steps,
                "message": " ".join(steps) + " The site now asks for a one-time code. Ask Pedro for the code in chat "
                           "with ask_user, then type only that code."}
    if buttons and re.search(r"\bpassword\b", text, re.I):
        return {"ok": False, "steps": steps, "error": " ".join(steps) + " The sign-in page is still showing, so Chrome "
                "probably has no saved login for this site. Save the login in Chrome (or sign in once yourself), then "
                "ask me again."}
    return {"ok": True, "signed_in": True, "steps": steps, "message": " ".join(steps) + f" You are signed in to {host}."}


DECLARATION = {
    "name": "browser_login",
    "description": ("Log in to a website (e.g. Itvedant/Wingz, GitHub) in Pedro's own Chrome: opens it, lets Chrome "
                    "autofill his SAVED login and presses Sign in. Never reads or types passwords. Use for 'log in to X'."),
    "parameters": {"type": "object", "properties": {"site": {"type": "string", "description": "Site name or address."}},
                   "required": ["site"]},
}
TOOLS = {"browser_login": login}
PROMPT = """Logging in:
- "Log in to <site>" calls browser_login once (it shows an approval card). Never ask for, read, store or type a password. If it says there is no saved login, tell Pedro to save one in Chrome or sign in himself. If it needs a one-time code, ask him in chat with ask_user and type only that code.
- After sign-in you may do practice or ungraded work for his review. For graded tests, exams or marked submissions only guide him and check his answers; never press the final Submit, Finish or Turn in button yourself.
- Never go silent: always reply with what you are doing, what happened, or why you can't.
"""
