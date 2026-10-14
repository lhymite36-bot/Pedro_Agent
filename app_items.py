"""Delete the app's own chats, bots and groups from the agent chat (asks for a yes first:
rules.yaml confirm › delete)."""

from __future__ import annotations

import re
from typing import Any


def _fold(v: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(v or "").casefold()).strip()


def delete_app_item(kind: str, name: str) -> dict[str, Any]:
    import agent_core as agent
    import bots, groups, chat_store

    kind, want = _fold(kind).rstrip("s"), _fold(name)
    if not want:
        return agent._err("Say which one to delete.")
    if kind == "bot":
        b = bots.get_bot(name) or next((x for x in bots.list_bots() if _fold(x.get("name")) == want), None)
        if not b:
            return agent._err(f"No bot called {name}.")
        if not bots.delete_bot(b["id"]):
            return agent._err(f"Couldn't delete the bot {b['name']}.")
        n = groups.remove_bot(b["id"])
        return agent._ok(f"Deleted the bot {b['name']}." + (f" Removed it from {n} group(s)." if n else ""), id=b["id"])
    if kind == "group":
        g = next((x for x in groups.list_groups() if x["id"] == name or _fold(x.get("name")) == want), None)
        if not g:
            return agent._err(f"No group called {name}.")
        groups.delete_group(g["id"])
        return agent._ok(f"Deleted the group {g['name']} (its bots are kept).", id=g["id"])
    if kind == "chat":
        rows = [r for r in chat_store.sessions() if r["session"] == name or want and want in _fold(r.get("title") or "")]
        rows = [r for r in rows if not str(r["session"]).startswith((bots.SESSION_PREFIX, groups.SESSION_PREFIX))] or rows
        if not rows:
            return agent._err(f"No chat matching {name}.")
        if len(rows) > 1 and rows[0]["session"] != name:
            return agent._err("More than one chat matches: " + "; ".join(str(r.get("title") or r["session"])[:40] for r in rows[:5]) + ". Be more specific.")
        chat_store.delete_session(rows[0]["session"])
        return agent._ok(f"Deleted the chat '{str(rows[0].get('title') or rows[0]['session'])[:60]}'.", session=rows[0]["session"])
    return agent._err("kind must be chat, bot or group.")


DECLARATION = {
    "name": "delete_app_item",
    "description": "Delete one of this app's own chats, bots or groups by name. Asks the user for a yes first. "
                   "For files and folders use delete_path instead.",
    "parameters": {"type": "object", "properties": {
        "kind": {"type": "string", "description": "chat, bot or group"},
        "name": {"type": "string", "description": "Its name (chat: words from its title)."}},
        "required": ["kind", "name"]},
}
