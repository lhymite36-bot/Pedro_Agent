"""1.4.18: spread model calls over the free models, each with its own per-minute limit.

Several tasks run at once now, so one free model would hit its limit (Groq answers 429) while the
others sit idle. Every call is counted per model in a one-minute window. Callers ask `order()` for
the least-loaded models first and call `acquire()` before a request, which waits briefly (never
long) when that model is at its limit. Nothing here costs money; it only counts calls.
"""

from __future__ import annotations

import collections
import threading
import time
from typing import Iterable

# Calls per minute, kept a little under each free tier's published limit.
LIMITS: dict[str, int] = {
    "groq:openai/gpt-oss-120b": 25,
    "groq:openai/gpt-oss-20b": 25,
    "openrouter": 16,
    "cerebras": 25,
    "nvidia": 30,
    "gemini": 12,          # per Gemini model (each model has its own free limit)
    "ollama": 120,         # local: limited by the PC, not a quota
}
WINDOW = 60.0
_calls: dict[str, collections.deque[float]] = collections.defaultdict(collections.deque)
_lock = threading.Lock()


def _limit(key: str) -> int:
    if key in LIMITS:
        return LIMITS[key]
    family = key.split(":", 1)[0]
    return LIMITS.get(family, 30)


def _trim(q: collections.deque[float], now: float) -> None:
    while q and now - q[0] >= WINDOW:
        q.popleft()


def load(key: str) -> float:
    """0.0 (idle) .. 1.0+ (at its limit) for the last minute."""
    now = time.monotonic()
    with _lock:
        q = _calls[key]
        _trim(q, now)
        return len(q) / max(1, _limit(key))


def at_limit(key: str) -> bool:
    return load(key) >= 1.0


def note(key: str) -> None:
    with _lock:
        _calls[key].append(time.monotonic())


def acquire(key: str, max_wait: float = 8.0, cancel: threading.Event | None = None) -> bool:
    """Count one call. Waits up to max_wait for a free slot; False means still at the limit."""
    deadline = time.monotonic() + max(0.0, max_wait)
    while True:
        now = time.monotonic()
        with _lock:
            q = _calls[key]
            _trim(q, now)
            if len(q) < _limit(key):
                q.append(now)
                return True
            wait = WINDOW - (now - q[0])
        if now >= deadline or (cancel is not None and cancel.is_set()):
            return False
        time.sleep(min(0.5, max(0.05, wait), max(0.05, deadline - now)))


def order(keys: Iterable[str]) -> list[str]:
    """Least-loaded first; ties keep the given order (so the preferred model wins when all are idle)."""
    items = list(keys)
    return sorted(items, key=lambda k: (at_limit(k), round(load(k), 1), items.index(k)))


def snapshot() -> dict[str, dict[str, float]]:
    now = time.monotonic()
    with _lock:
        out = {}
        for key, q in _calls.items():
            _trim(q, now)
            if q:
                out[key] = {"calls_last_minute": len(q), "limit": _limit(key)}
        return out


def reset() -> None:
    with _lock:
        _calls.clear()
