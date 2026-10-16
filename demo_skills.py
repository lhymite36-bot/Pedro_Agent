"""Learn by demonstration.

record_demonstration(name) watches the mouse, keys and screen until
stop_demonstration (or skills.max_record_seconds). Gemini vision turns the
frames and event log into skills/<name>/SKILL.md; the raw events go to
skills/<name>/actions.json. replay_skill(name) plays the clicks back (Esc aborts).

A run of typed keys is an input. Replay asks for new text and types that,
one value per line. The recorded words stay in actions.json on this PC and
are not typed again. With protect.skill_typing_stays_local (on by default)
they are not sent to Gemini or written into SKILL.md.

follow_skill reads the live screen and carries out the same steps. When a
question or label is different, it writes the answer that fits, then looks
again and fixes a step that did not land. It stops for a password or a
graded test, quiz, or exam.
"""

from __future__ import annotations

import hashlib
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
        self.bot_id = ""

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


def record_demonstration(name: str, bot: str = "") -> dict[str, Any]:
    global _current
    slug = skill_name(name)
    if not slug:
        return _err("Give the skill a name, like 'export-invoice'.")
    bot_id = ""
    bot_name = ""
    if str(bot or "").strip():
        import bots

        found = bots.get_bot(bot)
        if found is None:
            return _err(f"No bot named '{bot}'.")
        bot_id = found["id"]
        bot_name = found["name"]
    with _current_lock:
        if _current is not None:
            return _err(f"Already recording '{_current.name}'. Say stop first.")
        recorder = Recorder(slug)
        recorder.bot_id = bot_id
        try:
            recorder.start_listeners()
        except Exception as exc:
            return _err(f"Could not watch the mouse and keyboard: {exc}")
        recorder._frame(True)
        _current = recorder
    limit = settings()["max_record_seconds"]
    who = f" for {bot_name}" if bot_name else ""
    return _ok(f"Recording '{slug}'{who}. Do the task on this PC now, then say 'stop recording'. "
               f"It stops by itself after {limit} seconds.", name=slug, bot=bot_name)


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


_SHIFT_KEYS = {"Key.shift", "Key.shift_r", "Key.shift_l"}
_SHORTCUT_KEYS = {
    "Key.ctrl", "Key.ctrl_l", "Key.ctrl_r",
    "Key.alt", "Key.alt_l", "Key.alt_r", "Key.alt_gr",
    "Key.cmd", "Key.cmd_l", "Key.cmd_r",
}
_MODIFIER_KEYS = _SHIFT_KEYS | _SHORTCUT_KEYS


def _is_char_event(event: dict[str, Any]) -> bool:
    return event.get("type") == "key" and len(str(event.get("key") or "")) == 1


def _key_text(event: dict[str, Any]) -> str:
    return str(event.get("key") or "")


def input_slots(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Typed runs that take new text on the next replay.

    Printable keys, and Shift used to type them, are one input. Ctrl, Alt,
    and the Windows key mark a shortcut, which is replayed as recorded.
    The recorded characters are not copied onto the slot.
    """
    slots: list[dict[str, Any]] = []
    index = 0
    total = len(events)
    while index < total:
        event = events[index]
        if not (_is_char_event(event) and event.get("down")):
            index += 1
            continue
        start = index
        lead = start
        while lead > 0 and _key_text(events[lead - 1]) in _MODIFIER_KEYS:
            lead -= 1
        end = start + 1
        chars = 1
        cursor = start + 1
        while cursor < total:
            current = events[cursor]
            if _is_char_event(current):
                if current.get("down"):
                    chars += 1
                end = cursor + 1
                cursor += 1
                continue
            if _key_text(current) in _MODIFIER_KEYS:
                look = cursor + 1
                while look < total and _key_text(events[look]) in _MODIFIER_KEYS:
                    look += 1
                if look < total and _is_char_event(events[look]):
                    cursor += 1
                    continue
                break
            break
        while end < total and _key_text(events[end]) in _MODIFIER_KEYS:
            end += 1
        if any(_key_text(events[pos]) in _SHORTCUT_KEYS for pos in range(lead, end)):
            index = start + 1
            continue
        number = len(slots) + 1
        slots.append({
            "id": f"input_{number}",
            "label": f"Input {number}",
            "chars": chars,
            "start": lead,
            "end": end,
        })
        index = end
    return slots


def _parse_inputs(raw: Any) -> list[str] | None:
    if raw is None:
        return None
    if isinstance(raw, (list, tuple)):
        return [str(item) for item in raw]
    text = str(raw).strip()
    if not text:
        return None
    if text.startswith("["):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, list):
            return [str(item) for item in parsed]
    return [line.strip() for line in text.splitlines()]


def _inputs_note(slots: list[dict[str, Any]]) -> str:
    if not slots:
        return ""
    lines = ["", "## Inputs"]
    for slot in slots:
        lines.append(
            f"- {slot['label']}: new text every time ({slot['chars']} characters were typed while recording)."
        )
    lines.append("Ask for these before replaying. Pass them to replay_skill as inputs, one value per line.")
    return "\n".join(lines) + "\n"


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
        "text that is hidden in the log. Each '[N characters typed]' item is one input "
        "that changes every time. Call those Input 1, Input 2, in order, in the steps.\n\n"
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
    slots = input_slots(recorder.events)
    stored = [{"id": slot["id"], "label": slot["label"], "chars": slot["chars"]} for slot in slots]
    actions = {"name": recorder.name, "screen": list(recorder.screen), "recorded": time.strftime("%Y-%m-%d %H:%M"),
               "inputs": stored, "events": recorder.events}
    (folder / "actions.json").write_text(json.dumps(actions, indent=1), encoding="utf-8")
    body = summarise(recorder.name, recorder.events, recorder.frames).rstrip() + _inputs_note(slots)
    (folder / "SKILL.md").write_text(body, encoding="utf-8")
    taught = ""
    bot_id = str(getattr(recorder, "bot_id", "") or "")
    if bot_id:
        import bots

        lesson = (folder / "SKILL.md").read_text(encoding="utf-8")
        saved = bots.add_taught_skill(bot_id, recorder.name, lesson, replay=recorder.name)
        taught = str(saved.get("bot") or "")
        if not saved.get("ok"):
            return _err(str(saved.get("error") or "Could not add the lesson to the bot."),
                        name=recorder.name, path=str(folder / "SKILL.md"))
    message = f"Saved the skill '{recorder.name}' ({len(recorder.events)} actions)."
    if taught:
        message = f"Taught {taught} the lesson '{recorder.name}' ({len(recorder.events)} actions)."
    if slots:
        message += f" {len(slots)} typed step(s) ask for new text next time."
    return _ok(message, name=recorder.name, path=str(folder / "SKILL.md"), bot=taught)


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


def _type_text(keys_c: Any, text: str) -> int:
    done = 0
    for char in str(text):
        keys_c.press(char)
        keys_c.release(char)
        done += 2
    return done


def replay_skill(name: str, speed: float = 0.0, cancel_event: threading.Event | None = None,
                 sleep: Callable[[float], None] = time.sleep, inputs: Any = None) -> dict[str, Any]:
    slug = skill_name(name)
    path = skills_dir() / slug / "actions.json"
    if not path.is_file():
        return _err(f"No replayable skill named '{slug}'.", available=[s["name"] for s in list_skills()["skills"]])
    data = json.loads(path.read_text(encoding="utf-8"))
    events = data.get("events") or []
    slots = input_slots(events)
    values = _parse_inputs(inputs)
    if slots and (values is None or len(values) != len(slots)):
        return _err(
            f"'{slug}' has {len(slots)} typed step(s). The words change each time. "
            "Ask the user for the new text, then replay with inputs, one value per line.",
            needs_input=[{"label": slot["label"], "chars": slot["chars"]} for slot in slots],
        )
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
    slot_at = {slot["start"]: values[pos] for pos, slot in enumerate(slots)} if values else {}
    covered: set[int] = set()
    for slot in slots:
        covered.update(range(int(slot["start"]), int(slot["end"])))
    try:
        from pynput.mouse import Button  # noqa: F401
    except Exception:
        Button = None  # type: ignore[assignment]
    try:
        for index, event in enumerate(events):
            if stop.is_set():
                break
            if index in covered and index not in slot_at:
                last_t = float(event.get("t", 0))
                continue
            gap = max(0.0, float(event.get("t", 0)) - last_t) / speed
            last_t = float(event.get("t", 0))
            if gap:
                sleep(min(gap, 5.0))
            import desktop_share
            with desktop_share.hold():
                if index in slot_at:
                    done += _type_text(keys_c, slot_at[index])
                    continue
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
    note = f" with {len(values)} new input(s)" if slots and values else ""
    return _ok(f"Replayed '{slug}' ({done} actions){note}.", done=done)


def _tool_replay(name: str, speed: float = 0.0, inputs: Any = None) -> dict[str, Any]:
    return replay_skill(name, speed, inputs=inputs)


_SECRET = re.compile(
    r"(api[_ -]?key|password|passwd|secret|token|credential)\s*[:=]|bearer\s+[a-z0-9]",
    re.I,
)
_FOLLOW_KEYS = {
    "enter": "Key.enter", "tab": "Key.tab", "escape": "Key.esc", "esc": "Key.esc",
    "backspace": "Key.backspace", "space": "Key.space",
}
FOLLOW_LIMIT = 12


def _is_secret(text: str) -> bool:
    body = str(text or "")
    return "GEMINI_API_KEY" in body or bool(_SECRET.search(body))


def _follow_image() -> tuple[bytes, float, float] | None:
    """JPEG bytes and the scale from image pixels to screen pixels."""
    if screen_grab is not None:
        blob = screen_grab()
        if not blob:
            return None
        return blob, 1.0, 1.0
    try:
        import mss
        from PIL import Image

        with mss.mss() as sct:
            shot = sct.grab(sct.monitors[1])
        image = Image.frombytes("RGB", shot.size, shot.rgb)
        screen_w, screen_h = image.size
        image.thumbnail((1280, 1280))
        image_w, image_h = image.size
        out = io.BytesIO()
        image.save(out, "JPEG", quality=60)
        scale_x = screen_w / image_w if image_w else 1.0
        scale_y = screen_h / image_h if image_h else 1.0
        return out.getvalue(), scale_x, scale_y
    except Exception:
        return None


def _follow_prompt(lesson: str, supplied: str, previous: str) -> str:
    given = supplied.strip() or "None. Read the question or label on the screen and write the answer that fits."
    return (
        "Follow this recorded Windows task on the current screenshot. The steps stay the same. "
        "A question, label, or typed answer may be different from the recording. "
        "Read what the screen asks and produce the output that fits. "
        "If the previous action missed, click the right control or type a corrected answer. "
        "If you cannot see the whole question, scroll. "
        "If the question is not on the screen, scroll or stop. Do not invent the question or the answer. "
        "Stop for a password prompt, a graded test, a quiz, or an exam. Do not answer those.\n"
        "Return one JSON object only, with action set to click, type, key, scroll, done, or stop.\n"
        'click needs x and y in image pixels. type needs text. key is enter, tab, escape, or backspace. '
        "scroll needs dy (negative moves down). done means the task on screen is finished. "
        "stop means you cannot do this step. reason is a short note and must not repeat typed text.\n\n"
        f"LESSON:\n{lesson[:6000]}\n\n"
        f"TEXT THE USER ALREADY SUPPLIED:\n{given}\n\n"
        f"PREVIOUS ACTION: {previous}"
    )


def _decision(raw: str) -> dict[str, Any]:
    try:
        data = llm.json_from(raw)
    except (ValueError, TypeError):
        return {"action": "invalid"}
    if not isinstance(data, dict):
        return {"action": "invalid"}
    data["action"] = str(data.get("action") or "").strip().casefold()
    return data


def _action_signature(decision: dict[str, Any]) -> tuple[Any, ...] | None:
    action = decision.get("action")
    try:
        if action == "type":
            text = " ".join(str(decision.get("text") or "").split())
            if not text:
                return None
            return ("type", hashlib.sha256(text.encode()).hexdigest()[:12])
        if action == "click":
            return ("click", int(float(decision["x"])), int(float(decision["y"])))
        if action == "key":
            name = str(decision.get("key") or "").strip().casefold()
            if name not in _FOLLOW_KEYS:
                return None
            return ("key", name)
        if action == "scroll":
            return ("scroll", int(float(decision.get("dy") or 0)))
    except (KeyError, TypeError, ValueError):
        return None
    return None


def _perform_follow(decision: dict[str, Any], mouse_c: Any, keys_c: Any, scale_x: float, scale_y: float) -> dict[str, Any]:
    action = decision.get("action")
    if action == "type":
        text = " ".join(str(decision.get("text") or "").split())[:2000]
        if not text:
            return {"ok": False, "note": "The type action had no text."}
        if _is_secret(text):
            return {"ok": False, "blocked": True, "note": "Stopped because that step asked for a secret."}
        import bot_mind

        owner = bot_mind.bot_id()
        if owner:
            drafted = bot_mind.keep_draft(bot_mind.screen_text() or "The question on screen.", text, owner)
            if not drafted.get("ok"):
                return {"ok": False, "blocked": True, "note": str(drafted.get("error") or "The answer was not saved.")}
        _type_text(keys_c, text)
        return {"ok": True, "kind": "type", "note": f"typed {len(text)} characters"}
    if action == "click":
        x = int(float(decision["x"]) * scale_x)
        y = int(float(decision["y"]) * scale_y)
        mouse_c.position = (x, y)
        try:
            from pynput.mouse import Button
            button: Any = Button.left
        except Exception:
            button = "left"
        mouse_c.press(button)
        mouse_c.release(button)
        return {"ok": True, "kind": "click", "note": "clicked"}
    if action == "key":
        key = _resolve_key(_FOLLOW_KEYS[str(decision.get("key") or "").strip().casefold()])
        if key is None:
            return {"ok": False, "note": "That key is not available."}
        keys_c.press(key)
        keys_c.release(key)
        return {"ok": True, "kind": "key", "note": "pressed a key"}
    if action == "scroll":
        mouse_c.scroll(0, int(float(decision.get("dy") or 0)))
        return {"ok": True, "kind": "scroll", "note": "scrolled"}
    return {"ok": False, "note": "That action is not one of the steps."}


def follow_skill(name: str, inputs: Any = None, cancel_event: threading.Event | None = None,
                 sleep: Callable[[float], None] = time.sleep, limit: int = FOLLOW_LIMIT) -> dict[str, Any]:
    """Carry out a recorded lesson on the current screen, reading new questions."""
    slug = skill_name(name)
    path = skills_dir() / slug / "SKILL.md"
    if not path.is_file():
        return _err(f"No lesson named '{slug}'.", available=[s["name"] for s in list_skills()["skills"]])
    lesson = path.read_text(encoding="utf-8", errors="replace")
    values = _parse_inputs(inputs)
    supplied = "\n".join(values) if values else ""
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
    previous = "none yet"
    seen: list[tuple[Any, ...]] = []
    performed: list[str] = []
    invalid = 0
    import bot_mind

    frames: list[dict[str, Any]] = bot_mind.load_frames(slug)
    rewound = False
    try:
        for _ in range(max(1, int(limit))):
            if stop.is_set():
                break
            import desktop_share
            with desktop_share.hold():
                frame = _follow_image()
            if frame is None:
                return _err("Could not see the screen.")
            blob, scale_x, scale_y = frame
            seen_words = bot_mind.words(bot_mind.screen_text())
            decision = _decision(llm.text(_follow_prompt(lesson, supplied, previous), [blob]))
            action = decision.get("action")
            if action == "done":
                return _ok(f"Followed '{slug}' ({len(performed)} actions).", done=len(performed), actions=performed)
            if action == "stop":
                reason = " ".join(str(decision.get("reason") or "").split())[:180]
                if not reason or _is_secret(reason):
                    reason = "Stopped. That step needs you."
                return _err(reason, stopped=True, done=len(performed), actions=performed)
            signature = _action_signature(decision)
            if action == "invalid" or signature is None:
                invalid += 1
                previous = "The last reply was not a usable action. Return one JSON object."
                if invalid >= 3:
                    return _err("Could not decide the next step.", done=len(performed), actions=performed)
                continue
            if seen.count(signature) >= 2:
                back = bot_mind.matching_frame(frames, " ".join(seen_words))
                if back is not None and not rewound:
                    rewound = True
                    previous = bot_mind.rewind_note(back)
                    continue
                return _err(f"Could not fix '{slug}'. The same step kept failing.",
                            done=len(performed), actions=performed)
            seen.append(signature)
            with desktop_share.hold():
                outcome = _perform_follow(decision, mouse_c, keys_c, scale_x, scale_y)
            if outcome.get("blocked"):
                return _err(str(outcome.get("note") or "Stopped."), done=len(performed), actions=performed)
            if not outcome.get("ok"):
                previous = str(outcome.get("note") or "That action failed.")
                invalid += 1
                if invalid >= 3:
                    return _err("Could not decide the next step.", done=len(performed), actions=performed)
                continue
            performed.append(str(outcome["kind"]))
            previous = str(outcome["note"])
            frames.append({"words": seen_words, "note": previous})
            bot_mind.remember_frame(slug, seen_words, previous)
            if outcome.get("kind") == "click" and bot_mind.bot_id():
                reason = " ".join(str(decision.get("reason") or "that control").split())[:80]
                bot_mind.remember_place(reason, screen=" ".join(seen_words))
            sleep(0.4)
    finally:
        if escape is not None:
            escape.stop()
    if stop.is_set():
        return _err(f"Follow of '{slug}' stopped after {len(performed)} actions.",
                    stopped=True, done=len(performed), actions=performed)
    return _err(f"Stopped '{slug}' after {len(performed)} actions. The screen still needs a fix.",
                done=len(performed), actions=performed)


def _tool_follow(name: str, inputs: Any = None) -> dict[str, Any]:
    return follow_skill(name, inputs=inputs)


DECLARATIONS = [
    {"name": "record_demonstration",
     "description": "Start learning a skill by watching the user do it on this PC (mouse, keys, screen). Pass bot to save the lesson on that bot. Stop with stop_demonstration.",
     "parameters": {"type": "object", "properties": {
         "name": {"type": "string", "description": "Short skill name."},
         "bot": {"type": "string", "description": "Optional bot name. The lesson is saved on that bot."}},
         "required": ["name"]}},
    {"name": "stop_demonstration",
     "description": "Stop recording and save skills/<name>/SKILL.md (Gemini vision summary) plus actions.json.",
     "parameters": {"type": "object", "properties": {}}},
    {"name": "list_skills", "description": "List learned skills.", "parameters": {"type": "object", "properties": {}}},
    {"name": "replay_skill",
     "description": "Replay a learned skill's clicks and shortcut keys. Typed steps need new text in inputs, one value per line, in order. Leave inputs empty to learn how many values to ask the user for. Do not reuse words from the recording. Esc stops the replay. If the questions on screen are different, use follow_skill instead.",
     "parameters": {"type": "object", "properties": {
         "name": {"type": "string"},
         "speed": {"type": "number", "description": "1 = recorded speed, 2 = twice as fast."},
         "inputs": {"type": "string", "description": "New text for each typed step, one value per line, in order."}},
         "required": ["name"]}},
    {"name": "follow_skill",
     "description": "Follow a recorded lesson on the current screen. The steps stay the same. Read a different question or label and type the answer that fits. If a step misses, look again and fix it. Stop for a password, graded test, quiz, or exam. Esc stops it.",
     "parameters": {"type": "object", "properties": {
         "name": {"type": "string"},
         "inputs": {"type": "string", "description": "Optional text the user already supplied, one value per line. Otherwise read the screen."}},
         "required": ["name"]}},
]
TOOLS = {"record_demonstration": record_demonstration, "stop_demonstration": stop_demonstration,
         "list_skills": list_skills, "replay_skill": _tool_replay, "follow_skill": _tool_follow}
