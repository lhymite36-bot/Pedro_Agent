"""Chromium helper for pages the user asked to operate.

Tests set browser_runner_override or playwright_launcher and never launch
Chromium. Passwords stay in environment variables. The tool does not solve
a check, skip a countdown, or take a file from a download gate.
"""

from __future__ import annotations

import os
import re
import time
import uuid
from pathlib import Path
from typing import Any

import rules
from urllib.parse import urlparse

CHECK_WAIT_SECONDS = 90
GOTO_TIMEOUT_MS = 30_000
DOWNLOAD_TIMEOUT_MS = 60_000
MAX_ACTIONS = 8
MAX_FILE_BYTES = 200 * 1024 * 1024
MIN_FILE_BYTES = 16
MAX_COOKIE_BYTES = 1_000_000

_ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]{1,40}$")
_BLOCKED_ENV = {
    "GEMINI_API_KEY",
    "GEMINI_MODEL",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
    "DISCORD_WEBHOOK_URL",
}
_CHECK_HOSTS = (
    "recaptcha",
    "hcaptcha",
    "challenges.cloudflare.com",
    "turnstile",
)
_BLOCKED_SUFFIXES = {
    ".exe",
    ".msi",
    ".bat",
    ".cmd",
    ".ps1",
    ".scr",
    ".com",
    ".dll",
    ".js",
    ".vbs",
    ".hta",
    ".jar",
    ".apk",
    ".iso",
}
_KEYS = {"Enter", "Tab", "Escape"}
# None uses the installed Playwright. Tests pass a callable context manager.
playwright_launcher: Any = None


def _agent() -> Any:
    return __import__("agent_core")


def _safe_text(text: str) -> str:
    agent = _agent()
    safe = agent._scrub(text or "")
    for name in ("BROWSER_PASSWORD", "BROWSER_USERNAME", *sorted(_BLOCKED_ENV)):
        value = os.environ.get(name, "")
        if value:
            safe = safe.replace(value, "[redacted]")
    return safe


def _fail(text: str) -> dict[str, Any]:
    return _agent()._err(_safe_text(text))


def _check_url(url: str) -> str:
    text = (url or "").strip()
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("The address must be http or https.")
    if parsed.username or parsed.password or "@" in (parsed.netloc or ""):
        raise ValueError("Put the login in environment variables, not in the address.")
    host = parsed.hostname.casefold().rstrip(".")
    if host == "gta5-mods.com" or host.endswith(".gta5-mods.com"):
        raise ValueError(
            "That site does not offer a direct file this tool can take. "
            "Download the archive yourself into Downloads, then ask to install it."
        )
    agent = _agent()
    if agent.PIRACY_TERMS.search(text):
        raise ValueError("That address is refused.")
    return text


def _env_name(name: str) -> str:
    cleaned = (name or "").strip()
    if not rules.limit("browser_env_prefix_only"):
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", cleaned):
            raise ValueError("env must be an environment variable name.")
        return cleaned
    if not _ENV_NAME.fullmatch(cleaned) or cleaned in _BLOCKED_ENV:
        raise ValueError("env must name a BROWSER_ variable, not an API key or token.")
    if cleaned.startswith(("GEMINI", "TELEGRAM", "DISCORD")):
        raise ValueError("env must name a BROWSER_ variable, not an API key or token.")
    return cleaned


def _selector(value: str) -> str:
    text = (value or "").strip()
    if not text or len(text) > 180:
        raise ValueError("A selector is required and must be at most 180 characters.")
    lowered = text.casefold()
    if any(token in lowered for token in ("javascript:", "data:", "file:", "<script")):
        raise ValueError("That selector is not allowed.")
    if any(ord(char) < 32 for char in text):
        raise ValueError("That selector is not allowed.")
    return text


def _fill_is_secret(text: str) -> bool:
    agent = _agent()
    if agent._SECRET_FACT.search(text):
        return True
    stripped = text.strip()
    if re.fullmatch(r"\d{6,}:[A-Za-z0-9_-]{20,}", stripped):
        return True
    for name in ("BROWSER_PASSWORD", "GEMINI_API_KEY", "TELEGRAM_BOT_TOKEN", "DISCORD_WEBHOOK_URL"):
        value = os.environ.get(name, "")
        if value and value == stripped:
            return True
    return False


def _actions(raw: Any) -> list[dict[str, Any]]:
    if raw is None:
        raw = []
    if not isinstance(raw, list):
        raise ValueError("actions must be a list.")
    caps = rules.limit("browser_action_caps")
    if caps and len(raw) > MAX_ACTIONS:
        raise ValueError("At most 8 browser actions are allowed.")
    steps: list[dict[str, Any]] = []
    downloads = 0
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("Each browser action must be an object.")
        action = str(item.get("action") or "").strip().casefold()
        if action not in {"fill", "click", "press"}:
            raise ValueError("A browser action must be fill, click, or press.")
        step: dict[str, Any] = {"action": action}
        if action in {"fill", "click"}:
            step["selector"] = _selector(str(item.get("selector") or ""))
        if action == "fill":
            env_name = str(item.get("env") or "").strip()
            text = item.get("text")
            if env_name and text not in (None, ""):
                raise ValueError("A fill uses either text or env, not both.")
            if env_name:
                step["env"] = _env_name(env_name)
            elif isinstance(text, str) and text:
                if caps and len(text) > 500:
                    raise ValueError("Fill text is longer than 500 characters.")
                if rules.limit("refuse_secret_text") and _fill_is_secret(text):
                    raise ValueError(
                        "Put a password in an environment variable and pass its name in env."
                    )
                step["text"] = text
            else:
                raise ValueError("A fill needs text or env.")
        if action == "press":
            key = str(item.get("key") or "")
            if caps and key not in _KEYS:
                raise ValueError("press key must be Enter, Tab, or Escape.")
            if not key.strip():
                raise ValueError("press needs a key name.")
            step["key"] = key
        if action == "click" and item.get("download") is True:
            step["download"] = True
            downloads += 1
        steps.append(step)
    if caps and downloads > 1:
        raise ValueError("Only one download click is allowed.")
    return steps


def _visible(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, bool):
        return value
    raise ValueError("visible must be true or false.")


def _destination(agent: Any, destination: str) -> Path:
    name = " ".join((destination or "downloads").split()).casefold()
    if name in {"downloads", "download", "my downloads"}:
        folder = agent._downloads_folder()
    elif name in {"desktop", "my desktop", "the desktop"}:
        if agent.desktop_override is not None:
            folder = agent.desktop_override
        else:
            folder = Path.home() / "Desktop"
    else:
        text = (destination or "").strip().strip('"')
        drive = agent._resolve_drive_text(text)
        if drive is not None:
            folder = drive
        else:
            folder = Path(text).expanduser()
            if ".." in folder.parts:
                raise ValueError("The path cannot contain '..'.")
        resolved = folder.resolve()
        if not agent._path_is_allowed(resolved):
            raise ValueError(
                "Save the file in Downloads, on the Desktop, in your user folder, "
                "the app workspace, or on the external drive."
            )
        folder = resolved
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _cookie_file(agent: Any, cookie_file: str) -> str:
    text = (cookie_file or "").strip().strip('"')
    if not text:
        return ""
    path = Path(text).expanduser()
    if ".." in path.parts:
        raise ValueError("The cookie path cannot contain '..'.")
    resolved = path.resolve()
    if not agent._path_is_allowed(resolved):
        raise ValueError(
            "The cookie file must be in your user folder, the workspace, or the external drive."
        )
    if resolved.suffix.casefold() != ".json":
        raise ValueError("The cookie file must be a .json file.")
    if not resolved.is_file():
        raise ValueError("The cookie file was not found.")
    if resolved.stat().st_size > MAX_COOKIE_BYTES:
        raise ValueError("The cookie file is too large.")
    return str(resolved)


def _needs_person(page: Any) -> bool:
    frames = getattr(page, "frames", None) or []
    for frame in frames:
        url = str(getattr(frame, "url", "") or "").casefold()
        if any(token in url for token in _CHECK_HOSTS):
            return True
    return False


def _wait_for_person(page: Any) -> bool:
    deadline = time.monotonic() + max(0, CHECK_WAIT_SECONDS)
    while True:
        if not _needs_person(page):
            return True
        if time.monotonic() >= deadline:
            return False
        page.wait_for_timeout(500)


def _safe_filename(name: str) -> str:
    base = Path(str(name or "")).name
    if not base or base in {".", ".."}:
        raise ValueError("The download name is not valid.")
    if any(char in base for char in '<>:"|?*'):
        raise ValueError("The download name is not valid.")
    return base


def _unique_target(folder: Path, name: str) -> Path:
    target = folder / name
    if not target.exists():
        return target
    return folder / f"{target.stem}-{uuid.uuid4().hex[:8]}{target.suffix}"


def _accept_file(path: Path, folder: Path) -> dict[str, Any]:
    resolved = path.resolve()
    root = folder.resolve()
    if resolved != root and root not in resolved.parents:
        raise RuntimeError("The download was saved outside the chosen folder.")
    if not resolved.is_file():
        raise RuntimeError("The download did not finish.")
    size = resolved.stat().st_size
    if size < MIN_FILE_BYTES:
        resolved.unlink(missing_ok=True)
        raise RuntimeError("The download was empty.")
    if size > MAX_FILE_BYTES:
        resolved.unlink(missing_ok=True)
        raise RuntimeError("The download is larger than 200 MB.")
    if resolved.suffix.casefold() in _BLOCKED_SUFFIXES:
        resolved.unlink(missing_ok=True)
        raise RuntimeError("That file type is refused. The download was deleted.")
    with resolved.open("rb") as handle:
        head = handle.read(2)
    if head.startswith(b"MZ"):
        resolved.unlink(missing_ok=True)
        raise RuntimeError("That file type is refused. The download was deleted.")
    return {"path": str(resolved), "name": resolved.name, "bytes": size}


def _snapshot(page: Any) -> list[dict[str, str]]:
    try:
        raw = page.eval_on_selector_all(
            "a, button, input, textarea, select",
            """els => els.slice(0, 20).map(el => ({
                tag: (el.tagName || '').toLowerCase(),
                text: ((el.innerText || el.getAttribute('aria-label')
                    || el.getAttribute('placeholder') || el.getAttribute('name') || '') + '')
                    .trim().slice(0, 80),
                id: el.id || '',
                name: el.getAttribute('name') || ''
            }))""",
        )
    except Exception:
        return []
    items: list[dict[str, str]] = []
    if not isinstance(raw, list):
        return items
    for entry in raw[:20]:
        if not isinstance(entry, dict):
            continue
        tag = str(entry.get("tag") or "")[:20]
        text = " ".join(str(entry.get("text") or "").split())[:80]
        ident = str(entry.get("id") or "")[:80]
        name = str(entry.get("name") or "")[:80]
        if ident:
            selector = f"#{ident}"
        elif name:
            selector = f'{tag}[name="{name}"]' if tag else f'[name="{name}"]'
        else:
            selector = tag
        if not text and not selector:
            continue
        items.append({"tag": tag, "text": text, "selector": selector})
    return items


def _store_download(download: Any, folder: Path) -> Path:
    name = _safe_filename(getattr(download, "suggested_filename", "") or "download")
    target = _unique_target(folder, name)
    download.save_as(str(target))
    return target


def _run_playwright(plan: dict[str, Any], folder: Path) -> dict[str, Any]:
    launcher = playwright_launcher
    if launcher is None:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError(
                "playwright is not installed. From the project folder run: "
                ".\\.venv\\Scripts\\python.exe -m pip install playwright "
                "and then .\\.venv\\Scripts\\python.exe -m playwright install chromium"
            ) from exc
        launcher = sync_playwright
    with launcher() as playwright:
        browser = playwright.chromium.launch(headless=not plan["visible"])
        context = None
        context_args: dict[str, Any] = {"accept_downloads": True}
        if plan.get("cookie_file"):
            context_args["storage_state"] = plan["cookie_file"]
        try:
            try:
                context = browser.new_context(**context_args)
            except Exception as exc:
                if plan.get("cookie_file"):
                    raise RuntimeError("The cookie file could not be loaded.") from exc
                raise
            page = context.new_page()
            page.goto(plan["url"], wait_until="domcontentloaded", timeout=GOTO_TIMEOUT_MS)
            if _needs_person(page) and not _wait_for_person(page):
                raise RuntimeError(
                    "A check is on the page. Finish it in the browser window, then ask again."
                )
            saved: Path | None = None
            for step in plan["actions"]:
                if _needs_person(page) and not _wait_for_person(page):
                    raise RuntimeError(
                        "A check is on the page. Finish it in the browser window, then ask again."
                    )
                if step["action"] == "fill":
                    if "env" in step:
                        value = os.environ.get(step["env"], "")
                        if not value:
                            raise RuntimeError(f'{step["env"]} is not set.')
                    else:
                        value = step["text"]
                    page.fill(step["selector"], value)
                elif step["action"] == "press":
                    page.keyboard.press(step["key"])
                elif step.get("download"):
                    with page.expect_download(timeout=DOWNLOAD_TIMEOUT_MS) as pending:
                        page.click(step["selector"])
                    saved = _store_download(pending.value, folder)
                else:
                    page.click(step["selector"])
            title = str(page.title() or "")[:180]
            elements = [] if saved is not None else _snapshot(page)
            return {"title": title, "saved": saved, "elements": elements}
        finally:
            if context is not None:
                context.close()
            browser.close()


def browser_download_tool(
    url: str,
    actions: list[dict[str, Any]] | None = None,
    destination: str = "downloads",
    visible: bool | None = None,
    cookie_file: str = "",
) -> dict[str, Any]:
    """Open one page, run a short action list, and save one download."""
    agent = _agent()
    try:
        target = _check_url(url)
        steps = _actions(actions)
        show = _visible(visible)
        folder = _destination(agent, destination)
        cookies = _cookie_file(agent, cookie_file)
        plan = {
            "url": target,
            "actions": steps,
            "visible": show,
            "cookie_file": cookies,
        }
        runner = agent.browser_runner_override
        if runner is not None:
            outcome = runner(plan, folder)
        else:
            outcome = _run_playwright(plan, folder)
        if not isinstance(outcome, dict):
            return _fail("The browser returned nothing.")
        saved = outcome.get("saved")
        title = str(outcome.get("title") or "")[:180]
        if saved:
            accepted = _accept_file(Path(saved), folder)
            return agent._ok(
                f"Saved {accepted['name']} ({accepted['bytes']} bytes) to {accepted['path']}.",
                path=accepted["path"],
                bytes=accepted["bytes"],
                title=title,
            )
        elements = outcome.get("elements") if isinstance(outcome.get("elements"), list) else []
        public = []
        for item in elements[:20]:
            if isinstance(item, dict):
                public.append(
                    {
                        "tag": str(item.get("tag") or "")[:20],
                        "text": str(item.get("text") or "")[:80],
                        "selector": str(item.get("selector") or "")[:180],
                    }
                )
        return agent._ok(
            "Opened the page. No file was downloaded.",
            title=title,
            url=target,
            elements=public,
        )
    except AssertionError:
        raise
    except Exception as exc:
        return _fail(str(exc))
