"""How a bot thinks before it touches the PC.

A second opinion can refuse a click. Two plans are shown and the one whose
words are on the screen is kept. A click that worked becomes a named place.
A failed lesson step rewinds to the last screen that still matched. A quiet
moment turns the last mistake into a plan and does not move the mouse.
An answer is written in the bot's folder before it is typed on the page.
A timer, a grade, or a submit that cannot be undone stops every bot until
you say yes. If you pull the pointer off a bot's click, that spot is saved.
"""

from __future__ import annotations

import contextvars
import json
import os
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable

IDLE_S = 45.0
HAND_SLACK = 70
_lock = threading.RLock()
_activity = time.monotonic()
_trap_waiting = False
_trap_open = False
live_read = False
ask_hook: Callable[[str, str], str] | None = None
screen_text_hook: Callable[[], str] | None = None
cursor_hook: Callable[[], tuple[int, int] | None] | None = None
busy_hook: Callable[[], bool] | None = None
freeze_hook: Callable[[], None] | None = None

_target: contextvars.ContextVar[tuple[str, bool]] = contextvars.ContextVar(
    "pedro_mind_target", default=("", False)
)
_announce: contextvars.ContextVar[Callable[[str], None] | None] = contextvars.ContextVar(
    "pedro_mind_say", default=None
)
_YES = {"yes"}   # only a clear "yes" (any capitals) or the card's Approve tap lets a bot pass a trap
_STOP_WORDS = frozenset(
    "the a an on in of to and or for page this that with from are was were click button text".split()
)


def mind_dir() -> Path:
    env = os.environ.get("BOT_MIND_DIR", "").strip()
    if env:
        return Path(env)
    import agent_config

    return agent_config.storage_dir() / "bot_mind"


def bind_target(phrase: str, trusted: bool = False) -> contextvars.Token:
    return _target.set((" ".join(str(phrase or "").split())[:160], bool(trusted)))


def unbind_target(token: contextvars.Token) -> None:
    _target.reset(token)


def bind_announce(fn: Callable[[str], None] | None) -> contextvars.Token:
    return _announce.set(fn)


def unbind_announce(token: contextvars.Token) -> None:
    _announce.reset(token)


def bot_id() -> str:
    try:
        import desktop_share

        owner = desktop_share.owner() or ""
        if owner.startswith("bot-"):
            return owner[4:]
    except Exception:
        pass
    try:
        import bots

        bot = bots.current_bot()
        if bot:
            return str(bot.get("id") or "")
    except Exception:
        pass
    return ""


def words(text: str) -> list[str]:
    found = re.findall(r"[a-z0-9]{3,}", str(text or "").casefold())
    return [item for item in found if item not in _STOP_WORDS]


def trap_reason(screen: str) -> str:
    """A practice page is left alone. A timer, a grade, or a final submit is not."""
    text = " ".join(str(screen or "").casefold().split())
    if not text:
        return ""
    if re.search(r"cannot be undone|can't be undone|cannot undo|final submit", text):
        return "This page has a submit that cannot be undone."
    if re.search(r"time remaining|time left|\btimer\b", text):
        return "This page has a timer."
    if "practice" in text:
        return ""
    if re.search(r"\bgraded\b|\bexam\b|\bquiz\b", text):
        return "This page looks graded."
    return ""


def note_activity() -> None:
    global _activity
    _activity = time.monotonic()


def hear(text: str) -> None:
    """A user message. Yes lifts a trap. Any words count as someone at the chat."""
    global _trap_open, _trap_waiting
    note_activity()
    folded = " ".join(str(text or "").casefold().split()).strip(" .!?")
    if folded in _YES and _trap_waiting:
        _trap_open = True
        _trap_waiting = False


def allow_trap(reason: str = "") -> dict[str, Any]:
    global _trap_open, _trap_waiting
    _trap_open = True
    _trap_waiting = False
    return {"ok": True, "message": "Continuing. The next click is allowed."}


def screen_text() -> str:
    if screen_text_hook is not None:
        try:
            return str(screen_text_hook() or "")
        except Exception:
            return ""
    try:
        import page_text

        if page_text.reader_override is None and not (live_read and bot_id()):
            return ""
        found = page_text.read_page_text("")
        if found.get("ok"):
            return str(found.get("text") or "")
    except Exception:
        return ""
    return ""


def _load() -> dict[str, Any]:
    path = mind_dir() / "mind.json"
    if not path.is_file():
        return {"places": [], "frames": {}, "mistakes": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"places": [], "frames": {}, "mistakes": []}
    if not isinstance(data, dict):
        return {"places": [], "frames": {}, "mistakes": []}
    data.setdefault("places", [])
    data.setdefault("frames", {})
    data.setdefault("mistakes", [])
    return data


def _save(data: dict[str, Any]) -> None:
    folder = mind_dir()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "mind.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _score(plan: str, screen: str) -> float:
    keys = words(plan)
    if not keys:
        return 0.0
    hay = " ".join(words(screen))
    if not hay:
        return 0.0
    return sum(1 for item in keys if item in hay.split()) / len(keys)


def choose_plan(plan_a: str, plan_b: str, screen: str) -> str:
    """Return 'first' or 'second'. A tie keeps the bot's own plan."""
    if not str(plan_b or "").strip():
        return "first"
    if _score(plan_b, screen) > _score(plan_a, screen):
        return "second"
    return "first"


def lookup(phrase: str) -> dict[str, Any] | None:
    keys = words(phrase)
    if not keys:
        return None
    with _lock:
        places = list(_load().get("places") or [])
    places.sort(key=lambda item: float(item.get("at") or 0), reverse=True)
    for place in places:
        hay = set(words(str(place.get("name") or "") + " " + str(place.get("phrase") or "")))
        if keys and set(keys) <= hay:
            return dict(place)
    return None


def remember_place(
    phrase: str,
    grid_x: int | None = None,
    grid_y: int | None = None,
    pixel: tuple[int, int] | None = None,
    source: str = "worked",
    screen: str = "",
) -> dict[str, Any] | None:
    label = " ".join(str(phrase or "").split())[:80]
    if not label:
        return None
    if _secret(label):
        return None
    name = label
    blob = f"{screen} {label}".casefold()
    if "practice" in blob and "practice page" not in label.casefold():
        name = f"{label} on the practice page"
    px = int(pixel[0]) if pixel else None
    py = int(pixel[1]) if pixel else None
    if grid_x is None and px is not None and py is not None:
        grid_x, grid_y = _pixels_to_grid(px, py)
    place = {
        "id": uuid.uuid4().hex[:8],
        "name": name[:120],
        "phrase": label,
        "grid_x": None if grid_x is None else int(grid_x),
        "grid_y": None if grid_y is None else int(grid_y),
        "pixel_x": px,
        "pixel_y": py,
        "source": "hand" if source == "hand" else "worked",
        "bot": bot_id(),
        "at": time.time(),
    }
    with _lock:
        data = _load()
        kept = [
            item for item in data["places"]
            if words(str(item.get("phrase") or "")) != words(label)
        ]
        kept.append(place)
        data["places"] = kept[-80:]
        _save(data)
    return place


def remember_frame(lesson: str, frame_words: list[str], note: str) -> None:
    if len(frame_words) < 2:
        return
    if not os.environ.get("BOT_MIND_DIR") and not live_read:
        return
    slug = re.sub(r"[^a-z0-9]+", "-", str(lesson or "").casefold()).strip("-")[:40] or "lesson"
    with _lock:
        data = _load()
        frames = data["frames"].get(slug) or []
        frames.append({"words": frame_words[:40], "note": str(note or "")[:160], "at": time.time()})
        data["frames"][slug] = frames[-8:]
        _save(data)


def load_frames(lesson: str) -> list[dict[str, Any]]:
    if not os.environ.get("BOT_MIND_DIR") and not live_read:
        return []
    slug = re.sub(r"[^a-z0-9]+", "-", str(lesson or "").casefold()).strip("-")[:40] or "lesson"
    with _lock:
        frames = _load().get("frames", {}).get(slug) or []
    return [dict(item) for item in frames if isinstance(item, dict)]


def matching_frame(frames: list[dict[str, Any]], current: str) -> dict[str, Any] | None:
    cur = set(words(current))
    if len(cur) < 2:
        return None
    best = None
    for frame in frames:
        other = set(frame.get("words") or [])
        if len(other) < 2:
            continue
        shared = cur & other
        if len(shared) >= 2 and len(shared) / min(len(cur), len(other)) >= 0.5:
            best = frame
    return dict(best) if best else None


def rewind_note(frame: dict[str, Any]) -> str:
    note = " ".join(str(frame.get("note") or "an earlier step").split())[:120]
    return (
        f"Rewind. The screen still matches an earlier step ({note}). "
        "Continue from there. Do not repeat the click that just failed."
    )


def note_mistake(bot: str, note: str) -> None:
    text = " ".join(str(note or "").split())[:300]
    if not text or _secret(text):
        return
    with _lock:
        data = _load()
        if any(item.get("note") == text and not item.get("plan") for item in data["mistakes"]):
            return
        data["mistakes"].append({
            "id": uuid.uuid4().hex[:8],
            "bot": str(bot or "")[:40],
            "note": text,
            "plan": "",
            "at": time.time(),
        })
        data["mistakes"] = data["mistakes"][-40:]
        _save(data)


def latest_plan(bot: str) -> str:
    key = str(bot or "")
    with _lock:
        mistakes = list(_load().get("mistakes") or [])
    for item in reversed(mistakes):
        plan = " ".join(str(item.get("plan") or "").split())
        if plan and (not key or item.get("bot") in {key, ""}):
            return plan[:500]
    return ""


def study_if_idle(now: float | None = None, busy: bool | None = None) -> dict[str, Any] | None:
    """Rewrite the last mistake as a plan. This never moves the mouse."""
    moment = time.monotonic() if now is None else float(now)
    if busy is None and busy_hook is not None:
        try:
            busy = bool(busy_hook())
        except Exception:
            busy = False
    if busy:
        return None
    if moment - _activity < IDLE_S:
        return None
    with _lock:
        data = _load()
        pick = next((item for item in reversed(data["mistakes"]) if not item.get("plan")), None)
    if pick is None:
        return None
    prompt = (
        "You are studying a mistake. Do not use the mouse or name a click coordinate. "
        "Write a short plan for the next run. No passwords.\nMISTAKE:\n" + str(pick.get("note") or "")
    )
    try:
        plan = " ".join(_ask("study", prompt).split())[:500]
    except Exception:
        return None
    if not plan or _secret(plan):
        return None
    with _lock:
        data = _load()
        for item in data["mistakes"]:
            if item.get("id") == pick.get("id"):
                item["plan"] = plan
        _save(data)
    _remember_plan(str(pick.get("bot") or ""), plan)
    return {"ok": True, "plan": plan, "bot": pick.get("bot") or ""}


def keep_draft(question: str, answer: str, bot: str = "") -> dict[str, Any]:
    """Write the question and the full answer, then allow typing."""
    body = " ".join(str(answer or "").split())
    if not body:
        return {"ok": False, "error": "There is no answer to save."}
    if _secret(body) or _secret(question):
        return {"ok": False, "error": "Stopped because that step asked for a secret."}
    folder = _draft_folder(bot)
    folder.mkdir(parents=True, exist_ok=True)
    asked = " ".join(str(question or "").split())[:1000] or "The question on screen."
    path = folder / f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}.txt"
    path.write_text(f"Question:\n{asked}\n\nAnswer:\n{body}\n", encoding="utf-8")
    written = path.read_text(encoding="utf-8")
    if body not in written:
        return {"ok": False, "error": "The answer was not saved, so it was not typed."}
    return {"ok": True, "path": str(path), "message": "Saved the answer before typing it."}


def notice_hand(pixel_x: int, pixel_y: int, cursor_x: int, cursor_y: int, phrase: str) -> dict[str, Any] | None:
    if abs(int(cursor_x) - int(pixel_x)) + abs(int(cursor_y) - int(pixel_y)) <= HAND_SLACK:
        return None
    place = remember_place(phrase or "that spot", pixel=(int(cursor_x), int(cursor_y)), source="hand")
    if place is None:
        return None
    return {"ok": True, "name": place["name"], "grid_x": place.get("grid_x"), "grid_y": place.get("grid_y")}


def before_click(pixel_x: int, pixel_y: int) -> dict[str, Any] | None:
    """None when this click is not a bot's. Otherwise allow, move, or refuse it."""
    if not bot_id():
        return None
    try:
        import agent_core

        if agent_core.pointer_override is not None:
            return None
    except Exception:
        pass
    phrase, trusted = _target.get()
    screen = screen_text()
    reason = trap_reason(screen)
    global _trap_open, _trap_waiting
    if reason:
        if _trap_open:
            _trap_open = False
        else:
            _trap_waiting = True
            _ask_user(reason)
            if freeze_hook is not None:
                try:
                    freeze_hook()
                except Exception:
                    pass
            note_mistake(bot_id(), reason)
            return {"ok": False, "error": f"Stopped. {reason} Reply yes to let the bots continue.", "frozen": True}
    if trusted:
        place = lookup(phrase)
        if place and place.get("pixel_x") is not None and place.get("pixel_y") is not None:
            return {
                "ok": True,
                "pixel_x": int(place["pixel_x"]),
                "pixel_y": int(place["pixel_y"]),
                "say": f"Used the saved place {place.get('name')}.",
            }
        return {"ok": True, "say": f"Used the saved place {phrase}." if phrase else ""}
    plan_a = phrase or f"click at {int(pixel_x)},{int(pixel_y)}"
    plan_b, judge, why = _consult(screen, plan_a)
    which = choose_plan(plan_a, plan_b, screen)
    shown = plan_b or "none"
    say = f"Plans: {plan_a} | {shown}. Chose the {'second' if which == 'second' else 'first'} plan."
    _say(say)
    if which == "second":
        note_mistake(bot_id(), f"Dropped {plan_a}. The screen matched {plan_b}.")
        return {"ok": False, "error": f"The screen matches the other plan, so this click was dropped. {say}", "say": say}
    if judge == "no":
        note_mistake(bot_id(), why or f"The judge refused {plan_a}.")
        return {"ok": False, "error": f"The judge said no. {why} {say}".strip(), "say": say}
    return {"ok": True, "say": say}


def after_click(pixel_x: int, pixel_y: int) -> None:
    if not bot_id():
        return
    try:
        import agent_core

        if agent_core.pointer_override is not None:
            return
    except Exception:
        pass
    phrase, _trusted = _target.get()
    owner = bot_id()

    def watch() -> None:
        time.sleep(0.9)
        pos = _cursor()
        if pos is None:
            return
        notice_hand(pixel_x, pixel_y, pos[0], pos[1], phrase or "that spot")

    threading.Thread(target=watch, name=f"mind-hand-{owner}", daemon=True).start()


def _consult(screen: str, plan_a: str) -> tuple[str, str, str]:
    other = _other_name()
    prompt = (
        f"You are {other}, a different bot. You see only the screen text and the proposed click. "
        "You cannot click. Reply with one JSON object: "
        '{"plan_b": "a short other target or empty", "judge": "yes or no", "reason": "short"}. '
        "Say no for a password, a graded test, a timer, or a submit that cannot be undone. "
        "Say yes for an ordinary practice page.\n"
        f"SCREEN:\n{screen[:4000]}\nPROPOSAL:\n{plan_a[:300]}"
    )
    try:
        raw = _ask("judge", prompt)
    except Exception:
        return "", "yes", ""
    data = _json_object(raw)
    plan_b = " ".join(str(data.get("plan_b") or "").split())[:120]
    judge = "no" if str(data.get("judge") or "").strip().casefold().startswith("n") else "yes"
    why = " ".join(str(data.get("reason") or "").split())[:180]
    return plan_b, judge, why


def _other_name() -> str:
    me = bot_id()
    try:
        import bots

        for other in bots.list_bots():
            if str(other.get("id") or "") != me and other.get("name"):
                return str(other["name"])
    except Exception:
        pass
    return "the judge"


def _ask(kind: str, prompt: str) -> str:
    if ask_hook is not None:
        return str(ask_hook(kind, prompt) or "")
    import llm

    return llm.text(prompt)


def _json_object(raw: str) -> dict[str, Any]:
    try:
        import llm

        data = llm.json_from(raw)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _say(text: str) -> None:
    fn = _announce.get()
    if fn is None or not text:
        return
    try:
        fn(text)
    except Exception:
        pass


def _ask_user(reason: str) -> None:
    try:
        import confirm_action

        confirm_action.remember("allow_bot_trap", {"reason": reason[:80]}, reason)
    except Exception:
        pass


def _secret(text: str) -> bool:
    try:
        import agent_core

        return bool(agent_core._memory_is_secret(text or ""))
    except Exception:
        return False


def _pixels_to_grid(px: int, py: int) -> tuple[int, int]:
    width, height = 1920, 1080
    try:
        import agent_core

        width, height = agent_core._screen_size()
    except Exception:
        pass
    width = max(int(width or 1), 1)
    height = max(int(height or 1), 1)
    return (
        max(0, min(1000, round(int(px) * 1000 / width))),
        max(0, min(1000, round(int(py) * 1000 / height))),
    )


def _cursor() -> tuple[int, int] | None:
    if cursor_hook is not None:
        try:
            pos = cursor_hook()
        except Exception:
            return None
        if pos is None:
            return None
        return int(pos[0]), int(pos[1])
    if os.name != "nt":
        return None
    try:
        import ctypes

        class POINT(ctypes.Structure):
            _fields_ = (("x", ctypes.c_long), ("y", ctypes.c_long))

        point = POINT()
        if not ctypes.windll.user32.GetCursorPos(ctypes.byref(point)):
            return None
        return int(point.x), int(point.y)
    except Exception:
        return None


def _draft_folder(bot: str) -> Path:
    if bot:
        try:
            import bots

            found = bots.get_bot(bot)
            if found is not None:
                return bots.bot_folder(found) / "drafts"
        except Exception:
            pass
    return mind_dir() / "drafts"


def _remember_plan(bot: str, plan: str) -> None:
    if not bot:
        return
    try:
        import bots

        bots.bot_remember(plan, bot)
    except Exception:
        pass
