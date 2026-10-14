"""Live TTS loudness for the avatar's mouth.

The voice mp3 is decoded once (pygame Sound) into a loudness envelope of
WINDOW_MS steps. While it plays, the playback loop calls `update(ms)` and the
chat app reads `current()` (0..1, or None when nothing is playing).
"""

from __future__ import annotations

import array
import math
import threading
from typing import Any

WINDOW_MS = 40
_lock = threading.Lock()
_envelope: list[float] = []
_level: float | None = None


def envelope_from_samples(samples: Any, rate: int, channels: int = 1, window_ms: int = WINDOW_MS) -> list[float]:
    """RMS per window of signed 16-bit samples, normalised so loud speech ~1."""
    data = list(samples)
    channels = max(1, int(channels))
    step = max(1, int(rate * window_ms / 1000)) * channels
    raw: list[float] = []
    for start in range(0, len(data), step):
        chunk = data[start:start + step]
        if not chunk:
            break
        raw.append(math.sqrt(sum(v * v for v in chunk) / len(chunk)))
    if not raw:
        return []
    peak = sorted(raw)[int(len(raw) * 0.95) - 1 if len(raw) > 1 else 0] or max(raw) or 1.0
    return [min(1.0, value / peak) for value in raw]


def envelope_from_raw(raw: bytes, rate: int, channels: int) -> list[float]:
    samples = array.array("h")
    samples.frombytes(raw[: len(raw) - len(raw) % 2])
    return envelope_from_samples(samples, rate, channels)


def envelope_for_file(path: Any) -> list[float]:
    """Decode with pygame's mixer (already initialised for speech)."""
    try:
        import pygame

        init = pygame.mixer.get_init()
        if not init:
            return []
        rate, _fmt, channels = init
        sound = pygame.mixer.Sound(str(path))
        return envelope_from_raw(sound.get_raw(), rate, channels)
    except Exception:
        return []


def start(envelope: list[float]) -> None:
    global _envelope, _level
    with _lock:
        _envelope = list(envelope)
        _level = 0.0 if _envelope else None


def update(ms: float) -> float | None:
    global _level
    with _lock:
        if not _envelope:
            return None
        index = int(max(0.0, ms) // WINDOW_MS)
        _level = _envelope[index] if index < len(_envelope) else 0.0
        return _level


def stop() -> None:
    global _envelope, _level
    with _lock:
        _envelope = []
        _level = None


def current() -> float | None:
    with _lock:
        return None if _level is None else round(_level, 3)
