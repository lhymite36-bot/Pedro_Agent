"""Chat history for the desktop app, stored in sqlite (chat_history.db)."""

from __future__ import annotations

import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

_lock = threading.Lock()


def db_path() -> Path:
    import agent_config

    folder = agent_config.storage_dir()
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "chat_history.db"


def _connect(path: Path | None = None) -> sqlite3.Connection:
    con = sqlite3.connect(str(path or db_path()), check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute(
        "CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " session TEXT NOT NULL, role TEXT NOT NULL, text TEXT NOT NULL, ts REAL NOT NULL)"
    )
    con.execute("CREATE INDEX IF NOT EXISTS idx_session ON messages(session, id)")
    return con


@contextmanager
def _session(path: Path | None = None):
    """One connection per call, always closed (Windows locks open .db files)."""
    con = _connect(path)
    try:
        with con:
            yield con
    finally:
        con.close()


def close() -> None:
    """Nothing stays open between calls; kept for callers and tests."""
    return None


def add(session: str, role: str, text: str, path: Path | None = None) -> None:
    with _lock, _session(path) as con:
        con.execute(
            "INSERT INTO messages(session, role, text, ts) VALUES (?,?,?,?)",
            (session, role, text, time.time()),
        )


def history(session: str, limit: int = 200, path: Path | None = None) -> list[dict[str, Any]]:
    with _lock, _session(path) as con:
        rows = con.execute(
            "SELECT role, text, ts FROM (SELECT * FROM messages WHERE session=? ORDER BY id DESC LIMIT ?) ORDER BY ts",
            (session, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def sessions(path: Path | None = None) -> list[dict[str, Any]]:
    with _lock, _session(path) as con:
        rows = con.execute(
            "SELECT session, MAX(ts) AS last, COUNT(*) AS n,"
            " (SELECT text FROM messages m2 WHERE m2.session=m.session AND role='user' ORDER BY id LIMIT 1) AS title"
            " FROM messages m GROUP BY session ORDER BY last DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def delete_session(session: str, path: Path | None = None) -> None:
    with _lock, _session(path) as con:
        con.execute("DELETE FROM messages WHERE session=?", (session,))
