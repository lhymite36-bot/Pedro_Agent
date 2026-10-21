"""Automatic progress posts for long background jobs (1.5.2).

A background job (App Builder, board tasks, ...) gets a Reporter tied to the chat it was
started from. It posts short plain-word milestones into that chat, at most one every
GAP seconds (a newer milestone replaces a waiting one and is flushed when the gap is up),
then always posts a final message (result, optional screenshot, how to open it). The final
result and failures also raise a Windows toast and a phone notification; milestones don't.
Milestones start with PROGRESS_MARK so the phone app knows not to buzz for them.
"""

from __future__ import annotations

import contextvars
import threading
import time
from typing import Any, Callable

GAP = 60.0
PROGRESS_MARK = "\u23f3 "          # hourglass: quiet update
DONE_MARK = "\u2705 "
FAIL_MARK = "\u274c "

# set by chat_app: poster(session, text, kind, image_path) ; kind: progress | final | failed
poster: Callable[[str, str, str, str], Any] | None = None
SESSION: contextvars.ContextVar[str] = contextvars.ContextVar("pb_session", default="")


def current_session() -> str:
    return SESSION.get()


class Reporter:
    def __init__(self, session: str, title: str, gap: float = GAP, clock: Callable[[], float] = time.monotonic):
        self.session, self.title, self.gap, self.clock = session or "", title, gap, clock
        self.last = -1e9
        self.pending = ""
        self.timer: threading.Timer | None = None
        self.closed = False
        self.sent: list[tuple[str, str]] = []
        self.lock = threading.Lock()

    def _post(self, text: str, kind: str, image: str = "") -> None:
        self.sent.append((kind, text))
        if poster is None or not self.session:
            return
        try:
            poster(self.session, text, kind, image)
        except Exception:
            pass

    def milestone(self, text: str) -> None:
        with self.lock:
            if self.closed:
                return
            now = self.clock()
            if now - self.last >= self.gap:
                self.last, self.pending = now, ""
                self._post(PROGRESS_MARK + f"{self.title}: {text}", "progress")
                return
            self.pending = text
            if self.timer is None:
                self.timer = threading.Timer(max(1.0, self.gap - (now - self.last)), self._flush)
                self.timer.daemon = True
                self.timer.start()

    def _flush(self) -> None:
        with self.lock:
            self.timer = None
            if self.closed or not self.pending:
                return
            text, self.pending, self.last = self.pending, "", self.clock()
            self._post(PROGRESS_MARK + f"{self.title}: {text}", "progress")

    def final(self, text: str, ok: bool = True, image: str = "") -> None:
        with self.lock:
            self.closed = True
            if self.timer is not None:
                self.timer.cancel()
                self.timer = None
            self._post((DONE_MARK if ok else FAIL_MARK) + f"{self.title}: {text}", "final" if ok else "failed", image)
