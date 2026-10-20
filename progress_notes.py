"""Natural progress updates for long tasks (1.4.14), the way a person reports back.

Short tasks stay quiet: just the answer. Once a task proves long (several tool steps
or about 15 seconds), the bot posts:
  1. one opening line restating the goal,
  2. short plain-language updates only at real milestones - a result (a file saved, a
     checked click, a model built, a message sent), a blocker (a step failed), or a
     changed plan - never one per command, and at most one every 30 s unless blocked,
  3. a closing line with proof (files written, what was verified) after the answer.
Each update is saved in the chat (so the phone mirror and history show it) and sent
as a Windows notification while the window is hidden.
"""

from __future__ import annotations

import re
import time
from typing import Any, Callable

LONG_STEPS = 3
LONG_SECONDS = 15.0
GAP_SECONDS = 30.0
RESULT_TOOLS = {"ui_click", "ui_set_text", "write_file", "create_file", "save_file", "run_blender_task",
                "send_email", "gmail_send", "youtube_upload", "download_file", "browser_download", "run_python",
                "create_routine", "save_task_routine", "export_file", "follow_demonstration"}
QUIET_TOOLS = {"ui_read", "ui_find", "read_page_text", "screenshot", "take_screenshot", "list_files", "ask_user",
               "blender_docs_search", "blender_guide", "verify_screen", "get_time"}


def _short(text: str, n: int = 110) -> str:
    t = " ".join(str(text or "").split())
    t = re.sub(r"^\[[^\]]+\]\s*", "", t)          # "[Routine: x]" prefix
    return t if len(t) <= n else t[: n - 1].rsplit(" ", 1)[0] + "…"


def _plain(name: str) -> str:
    return str(name or "").replace("_", " ")


class Narrator:
    def __init__(self, goal: str, post: Callable[[str, str], Any], clock: Callable[[], float] = time.monotonic):
        self.goal = _short(goal)
        self.post = post            # post(kind, text) kind: opening | milestone | blocker | final
        self.clock = clock
        self.started = clock()
        self.steps = 0
        self.since_update = 0
        self.last_update = 0.0
        self.opened = False
        self.results: list[str] = []
        self.files: list[str] = []
        self.failed: list[str] = []
        self.last_label = ""
        self.posted: list[tuple[str, str]] = []

    def _say(self, kind: str, text: str) -> None:
        self.posted.append((kind, text))
        self.last_update = self.clock()
        self.since_update = 0
        try:
            self.post(kind, text)
        except Exception:
            pass

    def _maybe_open(self) -> None:
        if self.opened:
            return
        if self.steps >= LONG_STEPS or self.clock() - self.started >= LONG_SECONDS:
            self.opened = True
            self._say("opening", f"On it: {self.goal}. This takes a few steps, so I'll update you as it goes.")

    def feed(self, ev: dict[str, Any]) -> None:
        kind = ev.get("event")
        if kind == "step" and ev.get("label") and ev.get("name") not in {"", "mind"}:
            self.last_label = _short(ev["label"], 90)
        if kind == "plan_changed" or (kind == "step" and ev.get("name") == "replan"):
            self._maybe_open()
            if self.opened:
                self._say("milestone", "Change of plan: " + _short(ev.get("label") or ev.get("text") or "trying another way", 140))
            return
        if kind != "tool_end":
            return
        name = str(ev.get("name") or "")
        self.steps += 1
        self.since_update += 1
        if ev.get("path"):
            self.files.append(str(ev["path"]))
        ok = bool(ev.get("ok"))
        detail = _short(ev.get("detail") or "", 140).rstrip(" .")
        self.last_ok = bool(ev.get("ok"))
        self._maybe_open()
        if not ok and name not in QUIET_TOOLS:
            self.failed.append(f"{_plain(name)}: {detail}")
            if self.opened and "waiting for a yes" in detail.casefold():
                self._say("blocker", f"Waiting for your yes: {detail}.")
            elif self.opened:
                self._say("blocker", f"Hit a snag with {_plain(name)}: {detail or 'it did not work'}. Trying another way.")
            return
        if ok and (name in RESULT_TOOLS or ev.get("path")):
            self.results.append(detail or _plain(name))
            if self.opened and self.clock() - self.last_update >= GAP_SECONDS:
                done = f"{self.steps} steps in" if self.steps > 1 else "First step"
                self._say("milestone", f"{done}: {detail or _plain(name) + ' worked'}.")

    def finish(self, reply: str, cancelled: bool = False) -> str:
        """Closing line with proof, only for tasks that were narrated."""
        if not self.opened:
            return ""
        secs = int(self.clock() - self.started)
        if cancelled:
            text = f"Stopped after {self.steps} steps ({secs} s)."
        elif (self.failed and not self.results) or str(reply or "").lstrip().casefold().startswith(("not done", "not finished")) \
                or not getattr(self, "last_ok", True):
            text = f"Not finished yet ({self.steps} steps, {secs} s): {self.failed[-1] if self.failed else _short(reply, 140)}"
        else:
            proof = []
            if self.files:
                uniq = list(dict.fromkeys(self.files))
                proof.append("saved " + ", ".join(uniq[-3:]))
            if self.results:
                proof.append("checked: " + "; ".join(r for r in self.results[-2:] if r))
            text = f"Finished in {self.steps} steps ({secs} s)." + (" Proof - " + " | ".join(proof) if proof else "")
        self._say("final", text)
        return text
