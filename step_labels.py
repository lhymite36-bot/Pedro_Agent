"""Human-readable live activity labels for tool calls (shown like
"Opening Chrome" or "Checking Gmail"). Only whitelisted, non-secret
argument keys are ever shown, and values are shortened."""
from __future__ import annotations

import re
from typing import Any

_SECRET = re.compile(r"pass|token|secret|key|cookie|auth|pin|otp|credential", re.I)
_TEMPLATES: dict[str, tuple[str, tuple[str, ...]]] = {
    "launch_application": ("Opening {}", ("name", "app", "application", "path")),
    "open_website": ("Opening {}", ("url", "site")),
    "navigate_browser": ("Browsing {}", ("url", "query", "action")),
    "search_youtube": ("Searching YouTube for {}", ("query",)),
    "search_and_find_mod_download": ("Searching the web for {}", ("query", "mod_name", "name")),
    "download_mod_from_web": ("Downloading {}", ("url", "name")),
    "browser_download_tool": ("Downloading {}", ("url", "name")),
    "download_and_extract_zip": ("Downloading and extracting {}", ("url",)),
    "gmail_send_message": ("Drafting an email to {}", ("to",)),
    "take_screenshot": ("Looking at your screen", ()),
    "find_on_screen": ("Looking for {} on screen", ("target", "text", "query")),
    "click_element": ("Clicking {}", ("name", "target", "text")),
    "click_screen_target": ("Clicking {}", ("target", "text", "name")),
    "type_text": ("Typing", ()),
    "press_keys": ("Pressing {}", ("keys", "key")),
    "scroll": ("Scrolling", ()),
    "focus_window": ("Switching to {}", ("title", "name")),
    "search_local_files": ("Searching your files for {}", ("query", "pattern", "name")),
    "search_files_by_time": ("Finding recent files", ()),
    "file_content_rag_search": ("Reading files about {}", ("query",)),
    "write_text_file": ("Writing {}", ("path",)),
    "create_directory": ("Creating folder {}", ("path",)),
    "delete_path": ("Deleting {}", ("path",)),
    "copy_mod_files": ("Copying mod files", ()),
    "locate_gta5_directory": ("Finding the GTA V folder", ()),
    "code_engineer": ("Working on code: {}", ("task", "goal")),
    "build_local_program": ("Building {}", ("path", "project")),
    "git_manager": ("Running git {}", ("action", "command")),
    "self_heal_execution": ("Running and fixing {}", ("command", "path")),
    "system_diagnostics": ("Checking your PC's health", ()),
    "run_team": ("Team is working on {}", ("goal",)),
    "ask_bot": ("Asking {}", ("name",)),
    "delegate_subagent": ("Delegating: {}", ("task",)),
    "remember_fact": ("Saving to memory", ()),
    "recall_memory": ("Checking memory", ()),
    "capture_webcam_image": ("Looking through the webcam", ()),
    "webcam_vision_tool": ("Looking through the webcam", ()),
    "run_blender_task": ("Running Blender", ()),
    "process_media": ("Processing media", ()),
    "kill_process": ("Closing {}", ("name", "process")),
    "create_task_plan": ("Planning the steps", ()),
    "start_task": ("Getting ready for the task", ()),
    "verify_screen": ("Checking: {}", ("expectation",)),
    "capture_screenshot_file": ("Taking a screenshot", ()),
    "launch_any_app": ("Opening {}", ("name",)),
    "make_document": ("Making the document", ()),
    "whatsapp_prepare": ("Opening WhatsApp chat with {}", ("contact",)),
    "whatsapp_send_now": ("Sending to {}", ("contact",)),
    "save_task_routine": ("Saving routine {}", ("name",)),
    "self_upgrade": ("Upgrading myself", ()),
    "record_demonstration": ("Watching you to learn a skill", ()),
    "replay_skill": ("Replaying skill {}", ("name",)),
    "follow_skill": ("Following {}", ("name",)),
    "system_tests": ("Running tests", ()),
}


def _short(value: Any, n: int = 48) -> str:
    s = " ".join(str(value).split())
    return s if len(s) <= n else s[: n - 1] + "…"


def label_for(name: str, arguments: dict[str, Any] | None = None) -> str:
    args = arguments or {}
    tpl, keys = _TEMPLATES.get(name, ("", ()))
    val = ""
    for k in keys:
        if k in args and args[k] not in (None, "", [], {}) and not _SECRET.search(k):
            val = _short(args[k]); break
    if tpl:
        if "{}" in tpl:
            return tpl.format(val) if val else tpl.replace(" {}", "").replace(": {}", "").replace("{}", "").strip()
        return tpl
    if "gmail" in name:
        return "Checking Gmail"
    if "test" in name:
        return "Running tests"
    return name.replace("_", " ").capitalize()


def wrap_emit(emit: Any) -> Any:
    """Add a 'step' event with a label before every tool_start."""
    def out(ev: dict[str, Any]) -> None:
        if ev.get("event") == "tool_start":
            ev = {**ev, "label": label_for(str(ev.get("name") or ""), ev.get("arguments") or {})}
            emit({"event": "step", "label": ev["label"], "name": ev.get("name")})
        emit(ev)
    return out
