"""Facts a turn actually checked. A reply may use these, and nothing invented."""

from __future__ import annotations

import json
import re
import threading
from typing import Any

# Screen and keyboard actions. A third identical call is refused.
# Reads such as take_screenshot stay repeatable.
ACTION_TOOLS = frozenset({
    "click_element",
    "click_screen_target",
    "type_text",
    "perform_actions",
    "press_keys",
    "scroll",
})

_PATH = re.compile(r"[A-Za-z]:\\[^\s\"'`<>|*?\n]+")
_URL = re.compile(r"https?://[^\s\"'<>\n]+")
_DONE = re.compile(
    r"\b(saved|sent|clicked|opened|downloaded|uploaded|submitted|finished|completed|installed)\b"
    r"|\b(all done|it is done|it's done|task is complete|successfully)\b",
    re.I,
)
_NEG = ("not ", "n't ", "never ", "unable", "failed", "could not", "cannot", "can't", "did not", "didn't")
_LAUNCH_TOOLS = frozenset({"launch_application", "launch_any_app", "open_website", "watch_video"})
_LINK = re.compile(
    r"https?://[^\s\"'<>]+"
    r"|(?:[A-Za-z0-9-]+\.)+(?:youtube|youtu|vimeo|tiktok|twitch|dailymotion|instagram)\.[A-Za-z]{2,}[^\s\"'<>]*",
    re.I,
)
_OPEN_VERB = re.compile(
    r"\b(open|opening|opened|watch|watching|playing|play|launching|launch)\b",
    re.I,
)
_QUOTE = re.compile(r"\b(replied|said|says|wrote|answered)\s*:", re.I)
_CLAIM_APP = re.compile(
    r"\b(?:i am |i'm |i will |i'll |let me )?"
    r"(launching|opening|starting|launched|opened|started)\s+"
    r"((?:the\s+)?[A-Za-z][A-Za-z0-9+]*(?:\s+[A-Za-z][A-Za-z0-9+]*){0,4})",
    re.I,
)
_BARE_ACTION = re.compile(
    r"\b(?:i am |i'm |i )?(clicking|clicked|typing|typed|scrolling|scrolled|sending)\b",
    re.I,
)
_NAME_TAIL = frozenset({
    "for", "you", "now", "the", "app", "application", "please", "a", "an", "to", "it",
    "browser", "window", "program", "up",
})

# A tool call written into the reply as text, e.g. [[replay_skill(name='lesson')]].
# Writing it does nothing; the agent loop asks the model to make a real call, then drops it.
TEXT_CALL = re.compile(r"\[\[\s*([A-Za-z_][A-Za-z0-9_]{2,60})\s*\((?:[^\[\]]|\[[^\[\]]*\])*\)\s*\]\]")
_STRONG_DONE = re.compile(
    r"\b(completed|finished|all done|it is done|it's done|task is complete|have done it|recorded|"
    r"submitted|uploaded|saved|sent|placed the order|deleted)\b",
    re.I,
)


def text_calls(reply: str) -> list[str]:
    """Tool names written as text instead of called."""
    return [m.group(1) for m in TEXT_CALL.finditer(reply or "")]


def strip_text_calls(reply: str) -> str:
    out = TEXT_CALL.sub("", reply or "")
    return re.sub(r"[ \t]{2,}", " ", out).strip()


def _strong_claim(text: str) -> bool:
    for match in _STRONG_DONE.finditer(text or ""):
        start = max(0, match.start() - 16)
        window = text[start:match.end()].casefold()
        if any(neg in window for neg in _NEG):
            continue
        return True
    return False


_local = threading.local()


def begin() -> None:
    """Start a fresh ledger for this thread's turn."""
    _local.calls = []
    _local.seen = {}


def _bag() -> Any:
    if not hasattr(_local, "calls"):
        begin()
    return _local


def signature(name: str, arguments: dict[str, Any]) -> str:
    try:
        raw = json.dumps(arguments, sort_keys=True, default=str)
    except TypeError:
        raw = str(arguments)
    return f"{name}\n{raw[:800]}"


def repeat_error(name: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
    """Refuse the third identical screen action. The first two still run."""
    if name not in ACTION_TOOLS:
        return None
    bag = _bag()
    key = signature(name, arguments)
    count = int(bag.seen.get(key, 0))
    if count >= 2:
        return {
            "ok": False,
            "repeated": True,
            "error": (
                "That same action already ran twice and did not land. "
                "Look at the screen and try a different control, or tell the user you are stuck. "
                "Do not say it worked."
            ),
        }
    bag.seen[key] = count + 1
    return None


def note(name: str, result: dict[str, Any]) -> None:
    message = " ".join(str(result.get("message") or result.get("error") or "").split())[:400]
    paths: list[str] = []
    for key in ("path", "file", "output", "saved", "output_path"):
        value = result.get(key)
        if isinstance(value, str) and value.strip():
            paths.append(value.strip()[:300])
    extra = result.get("paths")
    if isinstance(extra, list):
        for item in extra:
            text = str(item).strip()
            if text:
                paths.append(text[:300])
    bag = _bag()
    bag.calls.append({
        "name": name,
        "ok": bool(result.get("ok")),
        "message": message,
        "paths": paths[:8],
    })
    if len(bag.calls) > 12:
        bag.calls = bag.calls[-12:]


def stamp(result: dict[str, Any]) -> str:
    """One line the model is allowed to repeat."""
    if result.get("held"):
        return "This action did not run. Read the earlier result, then choose the next action."
    if result.get("repeated"):
        return "Same action twice. Change the approach. Do not invent a success."
    if result.get("ok"):
        msg = " ".join(str(result.get("message") or "ok").split())[:240]
        return f"Checked: this worked. You may say: {msg}"
    err = " ".join(str(result.get("error") or result.get("message") or "it failed").split())[:240]
    return f"Checked: this failed. You may say: {err} Do not say it worked."


def facts() -> list[str]:
    lines: list[str] = []
    for row in list(getattr(_bag(), "calls", []) or []):
        state = "worked" if row["ok"] else "failed"
        bit = f"{row['name']} {state}. {row['message']}".strip()
        lines.append(bit[:220])
    return lines[-8:]


def handoff_brief() -> str:
    """Facts the next bot must trust instead of guessing."""
    lines = facts()
    if not lines:
        return ""
    body = "\n".join(f"- {line}" for line in lines)
    return (
        "Checked facts from this turn. Trust these. Do not replace them with a guess.\n"
        f"{body}"
    )


def _evidence(user_text: str) -> str:
    chunks = [user_text or ""]
    for row in list(getattr(_bag(), "calls", []) or []):
        chunks.append(str(row["message"]))
        chunks.append(str(row["name"]))
        chunks.extend(str(path) for path in row["paths"])
    return "\n".join(chunks)


def launch_done() -> bool:
    return any(row["name"] in _LAUNCH_TOOLS and row["ok"] for row in list(getattr(_bag(), "calls", []) or []))


def claimed_link(reply: str, user_text: str = "") -> str:
    """A link the reply says it is opening. The address may be in the user's text."""
    raw = reply or ""
    if _QUOTE.search(raw):
        return ""
    verb = _OPEN_VERB.search(raw)
    if not verb:
        return ""
    start = max(0, verb.start() - 16)
    window = raw[start:verb.end()].casefold()
    if any(neg in window for neg in _NEG):
        return ""
    match = _LINK.search(raw) or _LINK.search(user_text or "")
    if not match:
        return ""
    link = match.group(0).rstrip(".,);:!?\"'")
    return link[:300]


def claimed_app(text: str) -> str:
    """The app a reply says it is opening. A quote of another bot does not count."""
    raw = text or ""
    if _QUOTE.search(raw):
        return ""
    match = _CLAIM_APP.search(raw)
    if not match:
        return ""
    start = max(0, match.start() - 16)
    window = raw[start:match.end()].casefold()
    if any(neg in window for neg in _NEG):
        return ""
    words = [word.strip(".,;:!?\"'") for word in match.group(2).split()]
    words = [word for word in words if word]
    while words and words[-1].casefold() in _NAME_TAIL:
        words.pop()
    if words and words[0].casefold() == "the":
        words = words[1:]
    name = " ".join(words).strip()
    if not name or len(name) > 40:
        return ""
    return name


def unbacked_action(text: str) -> bool:
    """True when the reply claims a real action and this turn ran no tool."""
    raw = text or ""
    if _QUOTE.search(raw):
        return False
    if claimed_app(raw):
        return True
    match = _BARE_ACTION.search(raw)
    if not match:
        return False
    start = max(0, match.start() - 16)
    window = raw[start:match.end()].casefold()
    return not any(neg in window for neg in _NEG)


def carry_out_launch(reply: str, known: Any, launch: Any) -> str:
    """Open the named app when the reply claims it and no launch tool has succeeded."""
    app = claimed_app(reply)
    if not app or launch_done():
        return reply
    canonical = str(known(app) or "").strip()
    if not canonical:
        return reply
    try:
        result = launch(canonical)
    except Exception as exc:
        result = {"ok": False, "error": str(exc)}
    if not isinstance(result, dict):
        result = {"ok": False, "error": str(result)}
    note("launch_application", result)
    if result.get("ok"):
        return str(result.get("message") or f"Opened {canonical}.")
    return str(result.get("error") or f"Could not open {canonical}.")


def _claims_done(text: str) -> bool:
    for match in _DONE.finditer(text or ""):
        start = max(0, match.start() - 16)
        window = text[start:match.end()].casefold()
        if any(neg in window for neg in _NEG):
            continue
        return True
    return False


def _keep_token(token: str, evidence: str) -> bool:
    bare = token.rstrip(".,);:]")
    return bool(bare) and bare in evidence


def ground_reply(user_text: str, reply: str) -> str:
    """Drop a path, a link, or a success that no tool in this turn returned."""
    text = strip_text_calls((reply or "").strip())
    calls = list(getattr(_bag(), "calls", []) or [])
    if not text:
        return text
    if not calls:
        if unbacked_action(text) or _strong_claim(text):
            return "I have not done that. No tool ran, so nothing was opened, clicked, or sent."
        return text
    evidence = _evidence(user_text)

    def missing(match: re.Match[str]) -> str:
        token = match.group(0)
        if _keep_token(token, evidence):
            return token
        return "[not returned by a tool]"

    cleaned = _PATH.sub(missing, text)
    cleaned = _URL.sub(missing, cleaned)
    last = calls[-1]
    if not any(row["ok"] for row in calls) and _claims_done(cleaned):
        reason = last["message"] or "the tool failed"
        return f"I am not calling this done. The last tool said: {reason}"
    if not last["ok"] and _claims_done(cleaned):
        # Never "done" and "failed" in one message: the failure wins.
        reason = last["message"] or "the tool failed"
        return f"Not done yet. The last step failed: {reason}"
    return cleaned
