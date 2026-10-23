"""One event feed for every window: the PC app and the phone see the same thing live.

Each turn's events (tokens, steps, tool progress, saved messages, cards, reactions)
are published here with the chat they belong to and a sequence number. A client
holds GET /api/live open (Server-Sent Events). After a drop it reconnects with
?since=<last seq> and gets what it missed from the ring buffer. The phone reaches
this only through the signed-in remote server, so phone auth is unchanged.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any

RING = 3000
_events: deque[dict[str, Any]] = deque(maxlen=RING)
_cond = threading.Condition()
_seq = 0
# Events a watcher needs. Audio chunks stay with the window that asked for them.
SKIP = {"audio", "speech_level", "mic_level"}


def publish(session: str, event: dict[str, Any], origin: str = "") -> int:
    global _seq
    kind = str(event.get("event") or "")
    if kind in SKIP:
        return _seq
    with _cond:
        _seq += 1
        item = {"seq": _seq, "session": session, "origin": origin, "t": time.time(), **event}
        item["seq"] = _seq
        _events.append(item)
        _cond.notify_all()
        return _seq


def notify(kind: str, **fields: Any) -> int:
    """App-wide change (routines, sessions list, pause) with no chat attached."""
    return publish("", {"event": kind, **fields})


def current() -> int:
    return _seq


def since(seq: int) -> tuple[list[dict[str, Any]], bool]:
    """(events after seq, gap) - gap is True when the ring no longer holds all of them."""
    with _cond:
        items = [e for e in _events if e["seq"] > seq]
        gap = bool(_events) and seq < _events[0]["seq"] - 1 and seq < _seq
        return items, gap


def wait(seq: int, timeout: float = 15.0) -> tuple[list[dict[str, Any]], bool]:
    end = time.monotonic() + timeout
    with _cond:
        while _seq <= seq:
            left = end - time.monotonic()
            if left <= 0:
                break
            _cond.wait(left)
    return since(seq)


def reset() -> None:
    global _seq
    with _cond:
        _events.clear()
        _seq = 0
