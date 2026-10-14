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
    con.execute(
        "CREATE TABLE IF NOT EXISTS reactions (msg_id INTEGER NOT NULL, emoji TEXT NOT NULL, who TEXT NOT NULL,"
        " ts REAL NOT NULL, PRIMARY KEY (msg_id, emoji, who))"
    )
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


def add(session: str, role: str, text: str, path: Path | None = None) -> int:
    """Save one message; returns its id. [[react:EMOJI]] markers in a reply become reactions on the
    user's latest message (by the speaker) instead of text."""
    text, emojis = extract_reactions(text) if role == "assistant" else (text, [])
    with _lock, _session(path) as con:
        cur = con.execute(
            "INSERT INTO messages(session, role, text, ts) VALUES (?,?,?,?)",
            (session, role, text, time.time()),
        )
        new_id = int(cur.lastrowid)
        if emojis:
            row = con.execute("SELECT id FROM messages WHERE session=? AND role='user' ORDER BY id DESC LIMIT 1",
                              (session,)).fetchone()
            who = speaker_of(text)
            for e in emojis:
                if row:
                    con.execute("INSERT OR IGNORE INTO reactions(msg_id, emoji, who, ts) VALUES (?,?,?,?)",
                                (row["id"], e, who, time.time()))
    if emojis and added_hook is not None:
        try:
            added_hook(session)
        except Exception:
            pass
    return new_id


# ---- reactions ----
import re as _re

QUICK = ["👍", "❤️", "😂", "😮", "😢", "🎉", "✅"]
REACT_RE = _re.compile(r"\s*\[\[react:([^\]\s]{1,16})\]\]")
_TAG = _re.compile(r"^\[\[@([a-z0-9-]+)\]\]")
added_hook = None   # chat_app sets it to push fresh reactions to the window


def extract_reactions(text: str) -> tuple[str, list[str]]:
    found = [e for e in REACT_RE.findall(text or "") if valid_emoji(e)]
    return REACT_RE.sub("", text or ""), list(dict.fromkeys(found))


def speaker_of(text: str) -> str:
    m = _TAG.match(text or "")
    return m.group(1) if m else "assistant"


def valid_emoji(e: str) -> bool:
    e = (e or "").strip()
    return 0 < len(e) <= 16 and not any(c.isalnum() or c in "<>&\"'" for c in e)


def reactions_for(ids: list[int], path: Path | None = None, con: Any = None) -> dict[int, list[dict[str, Any]]]:
    if not ids:
        return {}
    def run(c: Any) -> list[Any]:
        q = ",".join("?" * len(ids))
        return c.execute(f"SELECT msg_id, emoji, who FROM reactions WHERE msg_id IN ({q}) ORDER BY ts", ids).fetchall()
    if con is not None:
        rows = run(con)
    else:
        with _lock, _session(path) as c:
            rows = run(c)
    out: dict[int, list[dict[str, Any]]] = {}
    for r in rows:
        group = out.setdefault(int(r["msg_id"]), [])
        hit = next((g for g in group if g["emoji"] == r["emoji"]), None)
        if hit is None:
            hit = {"emoji": r["emoji"], "who": []}
            group.append(hit)
        hit["who"].append(r["who"])
    return out


def toggle_reaction(msg_id: int, emoji: str, who: str = "you", path: Path | None = None) -> list[dict[str, Any]]:
    """Add the reaction, or remove it if this person already gave it. Returns the message's reactions."""
    if not valid_emoji(emoji):
        raise ValueError("not an emoji")
    with _lock, _session(path) as con:
        if con.execute("SELECT 1 FROM messages WHERE id=?", (msg_id,)).fetchone() is None:
            raise KeyError("no such message")
        gone = con.execute("DELETE FROM reactions WHERE msg_id=? AND emoji=? AND who=?", (msg_id, emoji, who)).rowcount
        if not gone:
            con.execute("INSERT INTO reactions(msg_id, emoji, who, ts) VALUES (?,?,?,?)", (msg_id, emoji, who, time.time()))
        return reactions_for([msg_id], con=con).get(msg_id, [])


def react_last_user(session: str, emoji: str, who: str, path: Path | None = None) -> int | None:
    """A bot/member reacts to the user's latest message (never toggles off). Returns the message id."""
    if not valid_emoji(emoji):
        return None
    with _lock, _session(path) as con:
        row = con.execute("SELECT id FROM messages WHERE session=? AND role='user' ORDER BY id DESC LIMIT 1",
                          (session,)).fetchone()
        if row is None:
            return None
        con.execute("INSERT OR IGNORE INTO reactions(msg_id, emoji, who, ts) VALUES (?,?,?,?)",
                    (row["id"], emoji, who, time.time()))
        return int(row["id"])


def history(session: str, limit: int = 200, path: Path | None = None) -> list[dict[str, Any]]:
    with _lock, _session(path) as con:
        rows = con.execute(
            "SELECT id, role, text, ts FROM (SELECT * FROM messages WHERE session=? ORDER BY id DESC LIMIT ?) ORDER BY id",
            (session, limit),
        ).fetchall()
        out = [dict(r) for r in rows]
        found = reactions_for([r["id"] for r in out], con=con)
    for r in out:
        r["reactions"] = found.get(r["id"], [])
    return out


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
        con.execute("DELETE FROM reactions WHERE msg_id IN (SELECT id FROM messages WHERE session=?)", (session,))
        con.execute("DELETE FROM messages WHERE session=?", (session,))
