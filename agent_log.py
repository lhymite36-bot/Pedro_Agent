"""Structured JSON-lines logging for Pedro_Agent.

Every tool call, model switch and error is written to
<workspace>/logs/agent.jsonl (one JSON object per line) with timings.
Secrets are scrubbed by the caller before text reaches this module.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import os
import time
from pathlib import Path
from typing import Any

_logger: logging.Logger | None = None
_listeners: list[Any] = []


def _log_dir() -> Path:
    import agent_config

    return agent_config.storage_dir() / "logs"


def logger() -> logging.Logger:
    global _logger
    if _logger is not None:
        return _logger
    log = logging.getLogger("pedro_agent")
    log.setLevel(logging.INFO)
    log.propagate = False
    if os.environ.get("PEDRO_AGENT_NO_FILE_LOG") != "1":
        try:
            folder = _log_dir()
            folder.mkdir(parents=True, exist_ok=True)
            handler = logging.handlers.RotatingFileHandler(
                folder / "agent.jsonl", maxBytes=5_000_000, backupCount=3, encoding="utf-8"
            )
            handler.setFormatter(logging.Formatter("%(message)s"))
            log.addHandler(handler)
        except OSError:
            pass
    _logger = log
    return log


def add_listener(callback: Any) -> None:
    """The chat app subscribes here to show live events."""
    if callback not in _listeners:
        _listeners.append(callback)


def remove_listener(callback: Any) -> None:
    if callback in _listeners:
        _listeners.remove(callback)


def event(kind: str, **fields: Any) -> dict[str, Any]:
    record = {"ts": round(time.time(), 3), "event": kind, **fields}
    try:
        logger().info(json.dumps(record, default=str)[:20000])
    except Exception:
        pass
    for callback in list(_listeners):
        try:
            callback(record)
        except Exception:
            pass
    return record
