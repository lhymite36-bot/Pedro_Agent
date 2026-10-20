"""What people see: no protocol markers, stage cues, or written tool calls. Plus a loop guard.

Stored chat text keeps [chuckles] and similar cues because the voice uses them.
The window and the phone get the cleaned text.
"""

from __future__ import annotations

import difflib
import re
from typing import Any

_CUES = (
    "laughs?", "laughing", "giggles?", "chuckles?", "playful(?:ly)?", "softly", "sighs?", "smiles?", "smile",
    "grins?", "winks?", "gasps?", "whispers?", "clears throat", "pause", "pauses", "sarcastic(?:ally)?",
    "excited(?:ly)?", "cheerful(?:ly)?", "cheers", "happily", "sadly", "snorts?", "hums?", "coughs?",
    "thoughtful(?:ly)?", "warmly", "gently", "proudly", "nervously", "curious(?:ly)?", "breathes?",
)
CUE = re.compile(r"[ \t]*\[(?:" + "|".join(_CUES) + r")\][ \t]*", re.I)
_REACT = re.compile(r"\s*\[{1,2}react:[^\]\s]{1,16}\]{1,2}")
_STRAY_TAG = re.compile(r"(?<!\[)\[@[A-Za-z0-9_\-]+\]\]\s*")
_DOUBLE_TAG = re.compile(r"(\[\[@[A-Za-z0-9_\-]+\]\])\s*(?:\[\[?@[A-Za-z0-9_\-]+\]\]\s*)+")
_PROTOCOL_LINE = re.compile(
    r"(?im)^\s*\**\s*(?:ASSIGN\s+@?[A-Za-z0-9_\-]+\s*\**\s*[:\-]\s*|PROJECT\s+(?:DONE|COMPLETE)\s*[:\-]?\s*|"
    r"ASK\s+USER\s*[:\-]\s*|DONE\s*[:\-]\s*|BLOCKED\s*[:\-]\s*)"
)
_INLINE_PROTOCOL = re.compile(r"\s*\b(?:PROJECT\s+DONE|ASK\s+USER|ASSIGN\s+@[A-Za-z0-9_\-]+|DONE|BLOCKED)\s*:\s*")


def clean_for_display(text: str) -> str:
    """Strip markers a person should never see. A leading [[@speaker]] tag is kept (the UI reads it)."""
    import grounding

    raw = str(text or "")
    raw = _DOUBLE_TAG.sub(r"\1 ", raw)
    lead = ""
    m = re.match(r"\s*\[\[@[A-Za-z0-9_\-]+\]\]\s*", raw)
    if m:
        lead, raw = m.group(0).strip() + " ", raw[m.end():]
    raw = _STRAY_TAG.sub("", raw)
    raw = _REACT.sub("", raw)
    raw = grounding.strip_text_calls(raw)
    raw = _PROTOCOL_LINE.sub("", raw)
    raw = _INLINE_PROTOCOL.sub(" ", raw)
    raw = CUE.sub(" ", raw)
    raw = re.sub(r"[ \t]{2,}", " ", raw)
    raw = re.sub(r"(?m)^[ \t]+", "", raw)
    raw = re.sub(r"\n{3,}", "\n\n", raw).strip()
    return (lead + raw).strip() if raw else lead.strip()


def _norm(text: str) -> str:
    import grounding

    calls = " ".join(grounding.text_calls(text))
    body = clean_for_display(re.sub(r"^\s*\[\[@[^\]]+\]\]", "", str(text or ""))).casefold()
    body = re.sub(r"[^a-z0-9 ]+", " ", body)
    return (calls + " " + " ".join(body.split())).strip()


LOOP_REPLY = ("I keep giving the same answer, so I've stopped instead of repeating it again. "
              "Tell me what to change, or say 'try again'.")


def is_loop(reply: str, earlier: list[str], limit: int = 2, ratio: float = 0.85) -> bool:
    """True when this reply is the same as each of the last `limit` replies (so it would be the 3rd)."""
    if len(earlier) < limit:
        return False
    now = _norm(reply)
    if not now or now == _norm(LOOP_REPLY):
        return False
    for old in earlier[-limit:]:
        before = _norm(old)
        if not before:
            return False
        if before != now and difflib.SequenceMatcher(None, before, now).ratio() < ratio:
            return False
    return True


def guard_loop(session: str, reply: str, store: Any = None) -> str:
    """Replace a third same-as-before reply in this chat with a short 'stopped' note."""
    try:
        if store is None:
            import chat_store as store  # type: ignore[no-redef]
        rows = store.history(session, limit=12)
    except Exception:
        return reply
    speaker = re.match(r"\s*(\[\[@[^\]]+\]\])", str(reply or ""))
    tag = speaker.group(1) if speaker else ""
    earlier = [str(r.get("text") or "") for r in rows if r.get("role") == "assistant"
               and (not tag or str(r.get("text") or "").startswith(tag))]
    if is_loop(reply, earlier):
        return (tag + " " if tag else "") + LOOP_REPLY
    return reply


def clean_row(row: dict[str, Any]) -> dict[str, Any]:
    if row.get("role") != "assistant":
        return row
    return {**row, "text": clean_for_display(str(row.get("text") or ""))}
