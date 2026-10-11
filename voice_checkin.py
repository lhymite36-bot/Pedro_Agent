"""A soft check-in after a long quiet stretch in voice mode.

It stays off outside voice mode. One prompt, then the normal listen. Silence
does not ask again until the person has been active and then idle once more.
"""

from __future__ import annotations

import os
from typing import Any

PHRASES = (
    "Hey, are you doing all right?",
    "Just checking in—are you okay?",
    "Hey, everything going fine over there?",
)
ACK = "Glad to hear! I'm right here if you need anything."

_last_voice = 0.0
_snoozed = False
_phrase_index = 0


def _agent() -> Any:
    import gta5_agent

    return gta5_agent


def _now() -> float:
    agent = _agent()
    if agent.scheduler_clock is not None:
        return float(agent.scheduler_clock())
    import time

    return time.time()


def reset() -> None:
    global _last_voice, _snoozed, _phrase_index
    _last_voice = _now()
    _snoozed = False
    _phrase_index = 0


def note_activity() -> None:
    """The user just spoke or came back. The idle wait starts over."""
    global _last_voice, _snoozed
    _last_voice = _now()
    _snoozed = False


def threshold_seconds() -> float:
    agent = _agent()
    if agent.checkin_idle_minutes_override is not None:
        minutes = float(agent.checkin_idle_minutes_override)
    else:
        raw = os.environ.get("CHECKIN_IDLE_MINUTES", "").strip()
        try:
            minutes = float(raw) if raw else 20.0
        except ValueError:
            minutes = 20.0
    minutes = min(30.0, max(15.0, minutes))
    return minutes * 60.0


def _machine_idle() -> float:
    agent = _agent()
    if agent.idle_seconds_override is not None:
        return float(agent.idle_seconds_override)
    return _last_input_idle()


def _last_input_idle() -> float:
    """Seconds since the last keyboard or mouse input. Zero when it cannot be read."""
    import sys

    if sys.platform != "win32":
        return 0.0
    import ctypes

    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]

    info = LASTINPUTINFO()
    info.cbSize = ctypes.sizeof(info)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
        return 0.0
    tick = int(ctypes.windll.kernel32.GetTickCount())
    elapsed = (tick - int(info.dwTime)) & 0xFFFFFFFF
    return elapsed / 1000.0


def _speak(text: str) -> None:
    agent = _agent()
    speaker = agent.checkin_speaker_override
    if speaker is not None:
        speaker(text)
        return
    agent.speak_response(text)


def _listen() -> str:
    agent = _agent()
    listener = agent.checkin_listener_override
    if listener is not None:
        heard = listener()
        return "" if heard is None else str(heard)
    heard = agent.listen_to_microphone(timeout=6, phrase_time_limit=None, announce=False)
    if not isinstance(heard, dict) or not heard.get("ok"):
        return ""
    return str(heard.get("text") or "").strip()


def maybe_check_in() -> str | None:
    """Speak one check-in when voice mode has been idle long enough.

    Returns "reply", "quiet", or None when it is not time.
    """
    global _snoozed, _phrase_index
    agent = _agent()
    if not agent.voice_mode_active:
        return None
    machine = _machine_idle()
    if _snoozed:
        if machine < 60:
            note_activity()
        return None
    limit = threshold_seconds()
    voice_idle = _now() - _last_voice
    if voice_idle < limit or machine < limit:
        return None
    phrase = PHRASES[_phrase_index % len(PHRASES)]
    _phrase_index += 1
    _speak(phrase)
    heard = _listen()
    if heard:
        _speak(ACK)
        note_activity()
        return "reply"
    _snoozed = True
    return "quiet"
