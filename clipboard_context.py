"""Read the clipboard and propose a next step. Nothing is executed.

Tests set clipboard_override and clipboard_image_override. The real clipboard
is not opened while those are set.
"""

from __future__ import annotations

import io
import re
import threading
from typing import Any

_TRACE = re.compile(
    r"traceback \(most recent call last\)|^\s*File \".+\", line \d+",
    re.IGNORECASE | re.MULTILINE,
)
_URL = re.compile(r"https?://\S+", re.IGNORECASE)
_CODE = re.compile(
    r"^\s*(def |class |import |from |#include |function |const |let |var )",
    re.MULTILINE,
)
_stop = threading.Event()
_thread: threading.Thread | None = None
_last_proposal = ""


def _agent() -> Any:
    import agent_core

    return agent_core


def _clipboard_text() -> str:
    agent = _agent()
    if agent.clipboard_override is not None:
        raw = agent.clipboard_override()
    else:
        import pyperclip

        raw = pyperclip.paste()
    if not isinstance(raw, str):
        raw = "" if raw is None else str(raw)
    return agent._scrub(raw.replace("\x00", "").strip())


def _clipboard_image() -> bytes | None:
    agent = _agent()
    if agent.clipboard_image_override is not None:
        raw = agent.clipboard_image_override()
    else:
        from PIL import ImageGrab

        grabbed = ImageGrab.grabclipboard()
        if grabbed is None or isinstance(grabbed, list):
            return None
        buffer = io.BytesIO()
        grabbed.convert("RGB").save(buffer, format="JPEG", quality=80)
        raw = buffer.getvalue()
    if not isinstance(raw, (bytes, bytearray)) or not raw:
        return None
    data = bytes(raw)
    if len(data) > 2_000_000:
        raise ValueError("The clipboard image is too large.")
    return data


def _mime(data: bytes) -> str:
    if data.startswith(b"\xff\xd8"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG"):
        return "image/png"
    return "image/jpeg"


def _looks_csv(text: str) -> bool:
    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) < 2:
        return False
    counts = [line.count(",") for line in lines[:6]]
    return counts[0] >= 1 and len(set(counts)) == 1


def classify(text: str, has_image: bool) -> tuple[str, str]:
    stripped = (text or "").strip()
    if _TRACE.search(stripped):
        return "traceback", "I can explain this Python traceback."
    if _URL.fullmatch(stripped):
        return "url", "I can open this link."
    if _looks_csv(stripped):
        return "csv", "I can turn this into a spreadsheet."
    if _CODE.search(stripped):
        return "code", "I can save this in the workspace."
    if has_image:
        return "image", "I can describe the image on the clipboard."
    if stripped:
        return "text", "I can read this clipboard text."
    return "empty", "The clipboard is empty."


def _read_pair() -> tuple[str, bytes | None]:
    text = _clipboard_text()
    if len(text) > _agent().CLIPBOARD_TEXT_LIMIT:
        text = text[: _agent().CLIPBOARD_TEXT_LIMIT]
    image = _clipboard_image()
    return text, image


def read_clipboard_context() -> dict[str, Any]:
    """Pull clipboard text or an image into this turn. Does not act on it."""
    agent = _agent()
    try:
        text, image = _read_pair()
        if not text and not image:
            return agent._err("The clipboard is empty.")
        kind, proposal = classify(text, image is not None)
        message = f"Read the clipboard ({kind}). {proposal}"
        payload = agent._ok(
            message,
            kind=kind,
            proposal=proposal,
            text=text,
            has_image=image is not None,
        )
        if image is not None:
            payload["_screenshot_bytes"] = image
            payload["_screenshot_mime"] = _mime(image)
        return payload
    except AssertionError:
        raise
    except Exception as exc:
        return agent._err(f"read_clipboard_context failed: {exc}")


def clipboard_action_dispatcher() -> dict[str, Any]:
    """Propose one action for the current clipboard. Do not run it here."""
    global _last_proposal
    agent = _agent()
    try:
        text, image = _read_pair()
        kind, proposal = classify(text, image is not None)
        if kind == "empty":
            return agent._err("The clipboard is empty.")
        _last_proposal = proposal
        preview = text[:240]
        return agent._ok(
            proposal,
            kind=kind,
            proposal=proposal,
            preview=preview,
            has_image=image is not None,
            executed=False,
        )
    except AssertionError:
        raise
    except Exception as exc:
        return agent._err(f"clipboard_action_dispatcher failed: {exc}")


DECLARATIONS = [
    {
        "name": "read_clipboard_context",
        "description": (
            "Read clipboard text or an image for this turn. Use it for "
            "'Analyze what's on my clipboard'. It does not open, save, or run "
            "what it finds, and it does not store the text in memory."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "clipboard_action_dispatcher",
        "description": (
            "Look at the clipboard and propose one next step, such as explaining "
            "a traceback, opening a link, making a spreadsheet, or saving code. "
            "It never performs that step."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
]


def _loop() -> None:
    global _last_proposal
    while not _stop.is_set():
        agent = _agent()
        if agent.background_services_enabled:
            try:
                text, image = _read_pair()
                _kind, proposal = classify(text, image is not None)
                if proposal and proposal != _last_proposal and _kind != "empty":
                    _last_proposal = proposal
            except Exception:
                pass
        if _stop.wait(2.0):
            return


def start_clipboard_watcher() -> None:
    global _thread
    if not _agent().background_services_enabled:
        return
    if _thread is not None and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="clipboard-watch", daemon=True)
    _thread.start()


def stop_clipboard_watcher() -> None:
    _stop.set()
