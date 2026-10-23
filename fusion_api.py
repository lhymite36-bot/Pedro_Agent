"""Extra HTTP routes for the Grok-style desktop shell. ADDED for fusion.

Does not touch chats, memory, posted.json, or quiet_brain_shorts data except
read-only search/paging and optional sidebar.json (new file).
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
from pathlib import Path
from typing import Any

_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def _storage() -> Path:
    import agent_config

    folder = agent_config.storage_dir()
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _sidebar_path() -> Path:
    return _storage() / "sidebar.json"


def health(status: dict[str, Any]) -> dict[str, Any]:
    return {"ok": True, **status}


def usage(status: dict[str, Any]) -> dict[str, Any]:
    """Real counters only. Empty models means Ped has not recorded calls this process."""
    import model_pool

    snap = model_pool.snapshot()
    return {
        "ok": True,
        "model": status.get("model"),
        "active_model": status.get("active_model"),
        "quota_note": status.get("quota_note") or "",
        "calls": snap,
        "note": "calls_last_minute is this Ped Bot process only. Missing keys mean no calls yet.",
    }


def _db() -> sqlite3.Connection:
    import chat_store

    con = sqlite3.connect(str(chat_store.db_path()), check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con


def history_page(session: str, before: int | None, limit: int) -> list[dict[str, Any]]:
    import chat_store

    session = str(session or "")
    limit = max(1, min(int(limit or 80), 200))
    con = _db()
    try:
        if before:
            rows = con.execute(
                "SELECT id, role, text, ts FROM messages WHERE session=? AND id<? ORDER BY id DESC LIMIT ?",
                (session, int(before), limit),
            ).fetchall()
            rows = list(reversed(rows))
        else:
            rows = con.execute(
                "SELECT id, role, text, ts FROM (SELECT * FROM messages WHERE session=? ORDER BY id DESC LIMIT ?) ORDER BY id",
                (session, limit),
            ).fetchall()
        out = [dict(r) for r in rows]
        ids = [int(r["id"]) for r in out]
        found = chat_store.reactions_for(ids, con=con)
        wrote = chat_store._writes_for(ids, con)
    finally:
        con.close()
    for row in out:
        row["reactions"] = found.get(row["id"], [])
        row["writes"] = wrote.get(row["id"], [])
    return out


def search(query: str) -> dict[str, Any]:
    q = " ".join(str(query or "").split())[:80]
    if len(q) < 2:
        return {"ok": True, "q": q, "bots": [], "chats": [], "messages": []}
    like = f"%{q.replace('%', '').replace('_', '')}%"
    import bots
    import chat_store

    bot_hits = []
    folded = q.casefold()
    for bot in bots.list_bots():
        blob = f"{bot.get('name','')} {bot.get('role','')} {bot.get('id','')}".casefold()
        if folded in blob:
            bot_hits.append({"id": bot["id"], "name": bot["name"], "session": bots.session_for(bot), "color": bot.get("color")})
    con = _db()
    try:
        titles = {str(r["session"]): str(r["title"]) for r in con.execute("SELECT session, title FROM titles")}
        chat_hits = []
        for row in con.execute(
            "SELECT session, MAX(ts) AS last FROM messages GROUP BY session"
        ):
            sid = str(row["session"])
            title = titles.get(sid) or sid
            if folded in title.casefold() or folded in sid.casefold():
                chat_hits.append({"session": sid, "title": title, "last": row["last"]})
        msg_hits = []
        for row in con.execute(
            "SELECT id, session, role, text, ts FROM messages WHERE text LIKE ? COLLATE NOCASE ORDER BY id DESC LIMIT 40",
            (like,),
        ):
            text = str(row["text"] or "")
            msg_hits.append({
                "id": row["id"],
                "session": row["session"],
                "role": row["role"],
                "ts": row["ts"],
                "preview": " ".join(text.split())[:180],
            })
    finally:
        con.close()
    return {"ok": True, "q": q, "bots": bot_hits[:20], "chats": chat_hits[:20], "messages": msg_hits}


def delete_message(msg_id: int, confirm: bool) -> dict[str, Any]:
    if not confirm:
        return {"ok": False, "error": "Confirm the delete."}
    try:
        mid = int(msg_id)
    except (TypeError, ValueError):
        return {"ok": False, "error": "Bad message id."}
    con = _db()
    try:
        row = con.execute("SELECT id, session FROM messages WHERE id=?", (mid,)).fetchone()
        if row is None:
            return {"ok": False, "error": "Message not found."}
        con.execute("DELETE FROM reactions WHERE msg_id=?", (mid,))
        con.execute("DELETE FROM writes WHERE msg_id=?", (mid,))
        con.execute("DELETE FROM messages WHERE id=?", (mid,))
        con.commit()
        return {"ok": True, "id": mid, "session": row["session"]}
    finally:
        con.close()


def _default_sidebar() -> dict[str, Any]:
    import bots

    ids = [b["id"] for b in bots.list_bots()]
    return {"sections": [], "unassigned": ids}


def get_sidebar() -> dict[str, Any]:
    import bots

    known = [b["id"] for b in bots.list_bots()]
    known_set = set(known)
    try:
        data = json.loads(_sidebar_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = _default_sidebar()
    sections = []
    seen: set[str] = set()
    for raw in data.get("sections") or []:
        if not isinstance(raw, dict):
            continue
        sid = str(raw.get("id") or "")[:24] or f"sec-{len(sections)+1}"
        name = " ".join(str(raw.get("name") or "Section").split())[:40] or "Section"
        bots_in = []
        for bid in raw.get("bots") or []:
            bid = str(bid)
            if bid in known_set and bid not in seen:
                bots_in.append(bid)
                seen.add(bid)
        sections.append({"id": sid, "name": name, "collapsed": bool(raw.get("collapsed")), "bots": bots_in})
    unassigned = [bid for bid in known if bid not in seen]
    saved_un = [str(x) for x in (data.get("unassigned") or []) if str(x) in known_set and str(x) not in seen]
    rest = [b for b in unassigned if b not in saved_un]
    return {"ok": True, "sections": sections, "unassigned": saved_un + rest}


def save_sidebar(data: dict[str, Any]) -> dict[str, Any]:
    current = get_sidebar()
    sections_in = data.get("sections") if isinstance(data.get("sections"), list) else current["sections"]
    unassigned_in = data.get("unassigned") if isinstance(data.get("unassigned"), list) else current["unassigned"]
    clean = {"sections": [], "unassigned": [str(x) for x in unassigned_in][:80]}
    for raw in sections_in[:24]:
        if not isinstance(raw, dict):
            continue
        clean["sections"].append({
            "id": str(raw.get("id") or f"sec-{len(clean['sections'])+1}")[:24],
            "name": " ".join(str(raw.get("name") or "Section").split())[:40] or "Section",
            "collapsed": bool(raw.get("collapsed")),
            "bots": [str(b) for b in (raw.get("bots") or [])][:40],
        })
    path = _sidebar_path()
    path.write_text(json.dumps(clean, indent=1), encoding="utf-8")
    return get_sidebar()


def backup_chats() -> dict[str, Any]:
    """Copy chat_history.db into storage/backups. Does not delete or rewrite the live DB."""
    import chat_store

    dest = chat_store.backup_db()
    return {"ok": True, "path": str(dest), "name": dest.name}
