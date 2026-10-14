"""Learn by demonstration.

record_demonstration(name) watches the mouse, keys and screen until
stop_demonstration (or skills.max_record_seconds). Gemini vision turns the
frames and event log into skills/<name>/SKILL.md; the raw events go to
skills/<name>/actions.json. replay_skill(name) plays them back (Esc aborts).

Typed text stays in actions.json on this PC. With protect.skill_typing_stays_local
(on by default) it is not sent to Gemini or written into SKILL.md.
"""

from __future__ import annotations

import io
import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Callable

import llm
import rules

DEFAULTS = {"max_record_seconds": 300, "frame_every_seconds": 2.0, "max_frames": 8, "replay_speed": 1.0}
NAME = re.compile(r"[^a-z0-9_-]+")

# Tests can swap these.
screen_grab: Callable[[], bytes | None] | None = None
controller_factory: Callable[[], tuple[Any, Any]] | None = None


def settings() -> dict[str, Any]:
    return rules.section("skills", DEFAULTS)


def skills_dir() -> Path:
    env = os.environ.get("SKILLS_DIR", "").strip()
    if env:
        return Path(env)
    import agent_config

    return agent_config.APP_DIR / "skills"


def skill_name(value: str) -> str:
    return NAME.sub("-", (value or "").strip().casefold()).strip("-")[:60]


def _ok(message: str, **extra: Any) -> dict[str, Any]:
    return {"ok": True, "message": message, **extra}


def _err(message: str, **extra: Any) -> dict[str, Any]:
    return {"ok": False, "error": message, **extra}


def _default_grab() -> bytes | None:
    try:
        import mss
        from PIL import Image

        with mss.mss() as sct:
            shot = sct.grab(sct.monitors[1])
        image = Image.frombytes("RGB", shot.size, shot.rgb)
        image.thumbnail((1024, 1024))
        out = io.BytesIO()
        image.save(out, "JPEG", quality=60)
        return out.getvalue()
    except Exception:
        return None


def _screen_size() -> tuple[int, int]:
    try:
        import pyautogui

        width, height = pyautogui.size()
        return int(width), int(height)
    except Exception:
        return (0, 0)


def _key_name(key: Any) -> str:
    char = getattr(key, "char", None)
    if char:
        return str(char)
    name = getattr(key, "name", None) or str(key)
    return "Key." + str(name).replace("Key.", "")


class Recorder:
    """Collects events. Listener callbacks call the on_* methods."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.started = time.monotonic()
        self.events: list[dict[str, Any]] = []
        self.frames: list[tuple[float, bytes]] = []
        self.stop_event = threading.Event()
        self.screen = _screen_size()
        self._listeners: list[Any] = []
        self._last_frame = -999.0
        self._lock = threading.Lock()
        self.async_frames = True

    def _t(self) -> float:
        return round(time.monotonic() - self.started, 3)

    def _frame(self, force: bool = False) -> None:
        cfg = settings()
        now = self._t()
        if not force and now - self._last_frame < float(cfg["frame_every_seconds"]):
            return
        if len(self.frames) >= int(cfg["max_frames"]) * 4:
            return
        blob = (screen_grab or _default_grab)()
        if blob:
            self._last_frame = now
            self.frames.append((now, blob))

    def add(self, event: dict[str, Any]) -> None:
        with self._lock:
            self.events.append({"t": self._t(), **event})

    def on_click(self, x: int, y: int, button: Any, pressed: bool) -> None:
        self.add({"type": "click", "x": int(x), "y": int(y), "button": getattr(button, "name", str(button)), "down": bool(pressed)})
        if pressed and self.async_frames:
            threading.Thread(target=self._frame, args=(True,), daemon=True).start()
        elif pressed:
            self._frame(True)

    def on_scroll(self, x: int, y: int, dx: int, dy: int) -> None:
        self.add({"type": "scroll", "x": int(x), "y": int(y), "dx": int(dx), "dy": int(dy)})

    def on_press(self, key: Any) -> None:
        self.add({"type": "key", "key": _key_name(key), "down": True})

    def on_release(self, key: Any) -> None:
        self.add({"type": "key", "key": _key_name(key), "down": False})

    def start_listeners(self) -> None:
        from pynput import keyboard, mouse

        self._listeners = [
            mouse.Listener(on_click=self.on_click, on_scroll=self.on_scroll),
            keyboard.Listener(on_press=self.on_press, on_release=self.on_release),
        ]
        for listener in self._listeners:
            listener.start()

        def ticker() -> None:
            limit = float(settings()["max_record_seconds"]) or 300.0
            while not self.stop_event.wait(0.5):
                self._frame()
                if self._t() >= limit:
                    self.stop_event.set()

        threading.Thread(target=ticker, name="demo-ticker", daemon=True).start()

    def stop_listeners(self) -> None:
        self.stop_event.set()
        for listener in self._listeners:
            try:
                listener.stop()
            except Exception:
                pass


_current: Recorder | None = None
_current_lock = threading.Lock()


def record_demonstration(name: str) -> dict[str, Any]:
    global _current
    slug = skill_name(name)
    if not slug:
        return _err("Give the skill a name, like 'export-invoice'.")
    with _current_lock:
        if _current is not None:
            return _err(f"Already recording '{_current.name}'. Say stop first.")
        recorder = Recorder(slug)
        try:
            recorder.start_listeners()
        except Exception as exc:
            return _err(f"Could not watch the mouse and keyboard: {exc}")
        recorder._frame(True)
        _current = recorder
    limit = settings()["max_record_seconds"]
    return _ok(f"Recording '{slug}'. Do the task now, then say 'stop recording'. "
               f"It stops by itself after {limit} seconds.", name=slug)


def _typed_runs(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Condense key-downs into typed text runs for the summary."""
    out: list[dict[str, Any]] = []
    for e in events:
        if e["type"] == "key" and e.get("down") and len(str(e["key"])) == 1:
            if out and out[-1]["type"] == "type":
                out[-1]["text"] += e["key"]
                continue
            out.append({"t": e["t"], "type": "type", "text": e["key"]})
        elif e["type"] == "key" and e.get("down"):
            out.append({"t": e["t"], "type": "press", "key": e["key"]})
        elif e["type"] == "click" and e.get("down"):
            out.append({"t": e["t"], "type": "click", "x": e["x"], "y": e["y"], "button": e["button"]})
        elif e["type"] == "scroll":
            out.append({"t": e["t"], "type": "scroll", "dy": e["dy"]})
    return out


def _summary_log(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    runs = _typed_runs(events)
    if rules.protect("skill_typing_stays_local"):
        for run in runs:
            if run["type"] == "type":
                run["text"] = f"[{len(run['text'])} characters typed]"
    return runs


def _pick_frames(frames: list[tuple[float, bytes]], count: int) -> list[bytes]:
    if len(frames) <= count:
        return [blob for _t, blob in frames]
    step = (len(frames) - 1) / max(1, count - 1)
    return [frames[round(i * step)][1] for i in range(count)]


def summarise(name: str, events: list[dict[str, Any]], frames: list[tuple[float, bytes]]) -> str:
    log = _summary_log(events)
    prompt = (
        "These screenshots and this input log show a person doing a task on Windows. "
        "Write a reusable skill file in Markdown for an AI agent with: a '# <title>' line, "
        "'## When to use', '## Steps' (numbered, naming the buttons/fields seen in the "
        "screenshots), and '## Notes' (what could differ next time). Do not invent typed "
        "text that is hidden in the log.\n\n"
        f"SKILL NAME: {name}\nINPUT LOG (t = seconds):\n{json.dumps(log)[:12000]}"
    )
    try:
        body = llm.strip_fence(llm.text(prompt, _pick_frames(frames, int(settings()["max_frames"]))))
    except Exception as exc:
        body = f"# {name}\n\n(No vision summary: {exc})\n\n## Steps\n" + "\n".join(
            f"{i + 1}. {json.dumps(step)}" for i, step in enumerate(log[:60]))
    if not body.lstrip().startswith("#"):
        body = f"# {name}\n\n{body}"
    return body.rstrip() + f"\n\nReplay: say \"replay skill {name}\" (Esc stops the replay).\n"


def save_skill(recorder: Recorder) -> dict[str, Any]:
    folder = skills_dir() / recorder.name
    folder.mkdir(parents=True, exist_ok=True)
    actions = {"name": recorder.name, "screen": list(recorder.screen), "recorded": time.strftime("%Y-%m-%d %H:%M"),
               "events": recorder.events}
    (folder / "actions.json").write_text(json.dumps(actions, indent=1), encoding="utf-8")
    (folder / "SKILL.md").write_text(summarise(recorder.name, recorder.events, recorder.frames), encoding="utf-8")
    return _ok(f"Saved the skill '{recorder.name}' ({len(recorder.events)} actions).",
               name=recorder.name, path=str(folder / "SKILL.md"))


def stop_demonstration() -> dict[str, Any]:
    global _current
    with _current_lock:
        recorder, _current = _current, None
    if recorder is None:
        return _err("Nothing is being recorded.")
    recorder.stop_listeners()
    events = recorder.events
    # Drop the keys/clicks used to say or type "stop" at the very end.
    while events and events[-1]["type"] == "key" and events[-1]["t"] > recorder._t() - 0.05:
        events.pop()
    return save_skill(recorder)


def list_skills() -> dict[str, Any]:
    root = skills_dir()
    rows = []
    for folder in sorted(root.glob("*/SKILL.md")) if root.is_dir() else []:
        first = folder.read_text(encoding="utf-8", errors="replace").splitlines()[:1]
        rows.append({"name": folder.parent.name, "title": (first[0].lstrip("# ") if first else ""),
                     "replayable": (folder.parent / "actions.json").is_file()})
    return _ok(f"{len(rows)} skills.", skills=rows)


def _controllers() -> tuple[Any, Any]:
    if controller_factory is not None:
        return controller_factory()
    from pynput import keyboard, mouse

    return mouse.Controller(), keyboard.Controller()


def _resolve_key(text: str) -> Any:
    if not text.startswith("Key."):
        return text
    from pynput import keyboard

    return getattr(keyboard.Key, text[4:], None)


def replay_skill(name: str, speed: float = 0.0, cancel_event: threading.Event | None = None,
                 sleep: Callable[[float], None] = time.sleep) -> dict[str, Any]:
    slug = skill_name(name)
    path = skills_dir() / slug / "actions.json"
    if not path.is_file():
        return _err(f"No replayable skill named '{slug}'.", available=[s["name"] for s in list_skills()["skills"]])
    data = json.loads(path.read_text(encoding="utf-8"))
    events = data.get("events") or []
    speed = float(speed or settings()["replay_speed"] or 1.0)
    speed = min(10.0, max(0.1, speed))
    width, height = _screen_size()
    rec_w, rec_h = (list(data.get("screen") or [0, 0]) + [0, 0])[:2]
    sx = width / rec_w if rec_w and width else 1.0
    sy = height / rec_h if rec_h and height else 1.0
    stop = cancel_event or threading.Event()
    escape = None
    if controller_factory is None:
        try:
            from pynput import keyboard

            def on_press(key: Any) -> None:
                if key == keyboard.Key.esc:
                    stop.set()

            escape = keyboard.Listener(on_press=on_press)
            escape.start()
        except Exception:
            escape = None
    mouse_c, keys_c = _controllers()
    done = 0
    last_t = 0.0
    try:
        from pynput.mouse import Button  # noqa: F401
    except Exception:
        Button = None  # type: ignore[assignment]
    try:
        for event in events:
            if stop.is_set():
                break
            gap = max(0.0, float(event.get("t", 0)) - last_t) / speed
            last_t = float(event.get("t", 0))
            if gap:
                sleep(min(gap, 5.0))
            kind = event.get("type")
            if kind == "click":
                mouse_c.position = (int(event["x"] * sx), int(event["y"] * sy))
                button = getattr(Button, str(event.get("button", "left")), None) if Button else event.get("button")
                (mouse_c.press if event.get("down") else mouse_c.release)(button)
            elif kind == "scroll":
                mouse_c.position = (int(event["x"] * sx), int(event["y"] * sy))
                mouse_c.scroll(int(event.get("dx", 0)), int(event.get("dy", 0)))
            elif kind == "key":
                key = _resolve_key(str(event.get("key", "")))
                if key is None:
                    continue
                (keys_c.press if event.get("down") else keys_c.release)(key)
            done += 1
    finally:
        if escape is not None:
            escape.stop()
    if stop.is_set():
        return _err(f"Replay of '{slug}' stopped after {done} of {len(events)} actions.", stopped=True, done=done)
    return _ok(f"Replayed '{slug}' ({done} actions).", done=done)


def _tool_replay(name: str, speed: float = 0.0) -> dict[str, Any]:
    return replay_skill(name, speed)


DECLARATIONS = [
    {"name": "record_demonstration",
     "description": "Start learning a skill by watching the user do it (mouse, keys, screen). Stop with stop_demonstration.",
     "parameters": {"type": "object", "properties": {"name": {"type": "string", "description": "Short skill name."}},
                    "required": ["name"]}},
    {"name": "stop_demonstration",
     "description": "Stop recording and save skills/<name>/SKILL.md (Gemini vision summary) plus actions.json.",
     "parameters": {"type": "object", "properties": {}}},
    {"name": "list_skills", "description": "List learned skills.", "parameters": {"type": "object", "properties": {}}},
    {"name": "replay_skill",
     "description": "Replay a learned skill's recorded mouse and keyboard actions by name. Esc stops it.",
     "parameters": {"type": "object", "properties": {
         "name": {"type": "string"},
         "speed": {"type": "number", "description": "1 = recorded speed, 2 = twice as fast."}},
         "required": ["name"]}},
]
TOOLS = {"record_demonstration": record_demonstration, "stop_demonstration": stop_demonstration,
         "list_skills": list_skills, "replay_skill": _tool_replay}
