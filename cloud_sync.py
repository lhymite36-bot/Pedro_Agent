"""1.5.12 phone-only mode: sync bots and chat messages with Supabase so the phone app can run
the same bots on its own (with its own Gemini key) when the PC is off, and both stay in sync.

The PC writes with the service role on behalf of ONE owner account (ADMIN_EMAIL or PEDBOT_OWNER_EMAIL).
Tables and RLS: supabase/phone_sync.sql. No API keys are ever synced.
Off unless Supabase is configured and the tables exist; every failure is logged, never raised.
"""
from __future__ import annotations

import json
import os
import threading
import time
from typing import Any

INTERVAL = 30
_state: dict[str, Any] = {"owner": None, "last_error": "", "pushed": 0, "pulled": 0, "running": False}
_lock = threading.Lock()

# Bot fields the phone needs to act as the same bot (no tasks/rules internals, no secrets).
BOT_FIELDS = ("id", "name", "color", "avatar", "role", "model", "tools", "notes", "skills", "created")


def _log(msg: str) -> None:
    _state["last_error"] = msg
    try:
        import agent_log

        agent_log.event("cloud_sync", msg=msg[:300])
    except Exception:
        print(f"[cloud-sync] {msg}", flush=True)


def _sb():
    import supabase_auth

    return supabase_auth


def owner_email() -> str:
    return (os.environ.get("PEDBOT_OWNER_EMAIL") or os.environ.get("ADMIN_EMAIL") or "").strip().casefold()


def owner_id() -> str:
    if _state["owner"]:
        return _state["owner"]
    email = owner_email()
    if not email:
        return ""
    rows = _sb()._rest("GET", "profiles", params={"email": f"eq.{email}", "select": "id"})
    if isinstance(rows, list) and rows:
        _state["owner"] = str(rows[0].get("id") or "")
    return _state["owner"] or ""


def bot_payload(bot: dict[str, Any]) -> dict[str, Any]:
    return {k: bot.get(k) for k in BOT_FIELDS if k in bot}


def _cursor_path():
    import agent_config

    return agent_config.storage_dir() / "cloud_sync.json"


def _cursor() -> dict[str, Any]:
    try:
        return json.loads(_cursor_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_cursor(data: dict[str, Any]) -> None:
    try:
        _cursor_path().write_text(json.dumps(data), encoding="utf-8")
    except OSError as exc:
        _log(f"could not save cursor: {exc}")


def push_bots(uid: str) -> int:
    import bots

    rows = [{"user_id": uid, "bot_id": b["id"], "data": bot_payload(b),
             "updated_at": _sb()._now()} for b in bots.list_bots()]
    if not rows:
        return 0
    out = _sb()._rest("POST", "pb_bots", params={"on_conflict": "user_id,bot_id"}, json=rows)
    if out is None:
        _log("push_bots failed (did you run supabase/phone_sync.sql?)")
        return 0
    return len(rows)


def push_messages(uid: str, cur: dict[str, Any], batch: int = 200) -> int:
    import chat_store

    last = int(cur.get("pc_last_id") or 0)
    with chat_store._lock, chat_store._session() as con:
        found = con.execute("SELECT id, session, role, text, ts FROM messages WHERE id>? ORDER BY id LIMIT ?",
                            (last, batch)).fetchall()
    skip = set(int(x) for x in cur.get("imported") or [])
    rows = [{"user_id": uid, "client_id": f"pc:{r['id']}", "session": r["session"], "role": r["role"],
             "text": r["text"], "origin": "pc", "ts": float(r["ts"])}
            for r in found if r["role"] in ("user", "assistant") and int(r["id"]) not in skip]
    if not found:
        return 0
    if rows:
        out = _sb()._rest("POST", "pb_messages", params={"on_conflict": "user_id,client_id"}, json=rows)
        if out is None:
            _log("push_messages failed")
            return 0
    cur["pc_last_id"] = int(found[-1]["id"])
    cur["imported"] = [x for x in skip if x > cur["pc_last_id"]]
    return len(rows)


def pull_phone_messages(uid: str, cur: dict[str, Any]) -> int:
    """Copy messages written on the phone (while the PC was off) into the PC chat history."""
    import chat_store

    last = int(cur.get("phone_last_remote_id") or 0)
    rows = _sb()._rest("GET", "pb_messages", params={
        "user_id": f"eq.{uid}", "origin": "eq.phone", "id": f"gt.{last}",
        "select": "id,session,role,text,ts", "order": "id.asc", "limit": "200"})
    if not isinstance(rows, list):
        return 0
    n = 0
    imported = list(cur.get("imported") or [])
    for r in rows:
        try:
            new_id = chat_store.add(str(r["session"]), str(r["role"]), str(r["text"]))
            if new_id:
                n += 1
                imported.append(int(new_id))   # local copy of a phone message: never push it back
        except Exception as exc:
            _log(f"import phone message failed: {exc}")
        cur["phone_last_remote_id"] = int(r["id"])
    cur["imported"] = imported
    return n


def sync_once() -> dict[str, Any]:
    sb = _sb()
    if not sb.configured():
        return {"ok": False, "error": "Supabase is not configured."}
    uid = owner_id()
    if not uid:
        return {"ok": False, "error": "Set ADMIN_EMAIL (or PEDBOT_OWNER_EMAIL) in .env to your Ped Bot account email."}
    with _lock:
        cur = _cursor()
        try:
            # Pull first so phone messages are imported before we advance the push cursor.
            pulled = pull_phone_messages(uid, cur)
            pushed = push_messages(uid, cur)
            nbots = push_bots(uid)
        except Exception as exc:
            _log(f"sync failed: {exc}")
            return {"ok": False, "error": str(exc)}
        _save_cursor(cur)
    _state["pushed"] += pushed
    _state["pulled"] += pulled
    return {"ok": True, "pushed": pushed, "pulled": pulled, "bots": nbots}


def status() -> dict[str, Any]:
    return {k: _state[k] for k in ("running", "pushed", "pulled", "last_error")} | {"owner_set": bool(owner_email())}


def start() -> bool:
    if _state["running"] or os.environ.get("PEDBOT_CLOUD_SYNC", "1").strip() in {"0", "false", "off"}:
        return False
    try:
        if not _sb().configured():
            return False
    except Exception:
        return False
    _state["running"] = True

    def loop() -> None:
        while True:
            sync_once()
            time.sleep(INTERVAL)

    threading.Thread(target=loop, name="cloud-sync", daemon=True).start()
    return True
