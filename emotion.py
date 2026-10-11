"""Expressive speech cues for the edge-tts voice.

ElevenLabs can keep reaction tags such as [laughs] and turn them into
non-speech sounds. This agent speaks with edge-tts (Azure Aria). That voice
would read the brackets aloud, so the standard path removes the tags before
synthesis. Laugh tags become a short spoken laugh. The printed reply is
unchanged. ElevenLabs is not installed and is not called.
"""

from __future__ import annotations

import re

_LAUGH_COMMAND = re.compile(
    r"\b(laugh for me|tell me a joke|giggle|chuckle)\b",
    re.IGNORECASE,
)
_JOKE = re.compile(
    r"\b(joke|funny|hilarious|haha|ha ha|lol)\b",
    re.IGNORECASE,
)
_SAD = re.compile(
    r"\b(sad|upset|frustrated|depress\w*|cry|crying|terrible|awful|"
    r"died|death|grief|lonely|bad news|so hard)\b",
    re.IGNORECASE,
)
_TAG = re.compile(
    r"\[(laughs|laugh|giggles|giggle|chuckles|chuckle|playful|softly|"
    r"crying|sighs|sigh|sorrowful|gasps|gasp|clears throat|excited|"
    r"soft tone)\]",
    re.IGNORECASE,
)
_CAPS = re.compile(r"\b[A-Z]{3,}\b")
_VOCAL = {
    "laughs": "Ha ha ha",
    "laugh": "Ha ha ha",
    "giggles": "He he he",
    "giggle": "He he he",
    "chuckles": "Ha ha",
    "chuckle": "Ha ha",
    "sighs": "...",
    "sigh": "...",
}
_LAUGH_TAGS = set(_VOCAL) - {"sighs", "sigh"}
_SOFT_TAGS = {"softly", "crying", "sighs", "sigh", "sorrowful", "soft tone"}
_DELIVERY = {
    "neutral": ("+0%", "+0Hz"),
    "pause": ("-8%", "+0Hz"),
    "cheerful": ("+8%", "+4Hz"),
    "excited": ("+12%", "+8Hz"),
    "laugh": ("+12%", "+6Hz"),
    "empathetic": ("-15%", "-10Hz"),
}

_base = "neutral"
_active = "neutral"


def reset() -> None:
    """Return the voice to a neutral delivery. Tests call this."""
    global _base, _active
    _base = "neutral"
    _active = "neutral"


def detect_emotion(user_text: str) -> str:
    """cheerful, laugh, empathetic, or neutral from the user's words."""
    text = user_text or ""
    if _LAUGH_COMMAND.search(text):
        return "laugh"
    if _SAD.search(text):
        return "empathetic"
    if _JOKE.search(text):
        return "cheerful"
    return "neutral"


def note_user(user_text: str) -> str:
    """Remember the mood of this turn before the reply is spoken."""
    global _base, _active
    _base = detect_emotion(user_text)
    _active = _base
    return _active


def current() -> str:
    return _active


def delivery() -> tuple[str, str]:
    """edge-tts rate and pitch for the active mood."""
    return _DELIVERY.get(_active, _DELIVERY["neutral"])


def prepare_for_speech(text: str, *, provider: str = "edge") -> str:
    """Tags for the selected speech engine.

    provider "elevenlabs" would keep the brackets. This project never selects
    that provider. The default Azure path strips them.
    """
    if provider == "elevenlabs":
        return text or ""
    return _apply_standard(text or "")


def _apply_standard(text: str) -> str:
    """Remove reaction tags. Laugh tags become a short laugh."""
    global _active
    found: list[str] = []

    def replace(match: re.Match[str]) -> str:
        tag = match.group(1).casefold()
        found.append(tag)
        return _VOCAL.get(tag, "")

    cleaned = _TAG.sub(replace, text)
    if any(tag in _LAUGH_TAGS for tag in found):
        _active = "laugh"
    elif any(tag in _SOFT_TAGS for tag in found):
        _active = "empathetic"
    elif any(tag in {"excited", "gasps", "gasp"} for tag in found):
        if _active != "empathetic":
            _active = "excited"
    elif "playful" in found and _active == "neutral":
        _active = "cheerful"
    elif _active == "neutral" and _CAPS.search(text):
        _active = "excited"
    elif _active == "neutral" and "..." in text:
        _active = "pause"
    return cleaned
