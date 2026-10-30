"""1.6.8: bot list state for the home screen / PC sidebar - sections, pin, hide, unread - plus
duplicate and share-as-template. Stored in storage/bot_home.json next to the bots, so phone and PC see the same."""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any

import bots

_lock = threading.Lock()
EMPTY = {"sections": [], "pinned": [], "hidden": [], "unread": []}


def _file() -> Path:
    return bots.bots_dir().parent / "bot_home.json"


def load() -> dict[str, Any]:
    try:
        d = json.loads(_file().read_text(encoding="utf-8"))
    except Exception:
        d = {}
    out = {k: list(d.get(k) or []) for k in ("pinned", "hidden", "unread")}
    secs = []
    for s in d.get("sections") or []:
        if isinstance(s, dict) and s.get("name"):
            secs.append({"id": str(s.get("id") or uuid.uuid4().hex[:8]), "name": str(s["name"])[:40],
                         "ids": [str(i) for i in s.get("ids") or []], "collapsed": bool(s.get("collapsed"))})
    out["sections"] = secs
    return out


def _save(d: dict[str, Any]) -> dict[str, Any]:
    p = _file(); p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp"); tmp.write_text(json.dumps(d, indent=2), encoding="utf-8"); os.replace(tmp, p)
    return d


def _toggle(lst: list, item: str, on: bool) -> None:
    if on and item not in lst:
        lst.append(item)
    if not on:
        while item in lst:
            lst.remove(item)


def apply(op: str, data: dict[str, Any]) -> dict[str, Any]:
    bid = str(data.get("id") or "")
    with _lock:
        d = load()
        if op in ("pin", "hide", "unread"):
            key = {"pin": "pinned", "hide": "hidden", "unread": "unread"}[op]
            _toggle(d[key], bid, bool(data.get("on", True)))
        elif op == "move":          # section id, or a new section name, or "" for Unassigned
            for s in d["sections"]:
                _toggle(s["ids"], bid, False)
            name = str(data.get("new_section") or "").strip()[:40]
            sid = str(data.get("section") or "")
            if name:
                sec = next((s for s in d["sections"] if s["name"].lower() == name.lower()), None)
                if not sec:
                    sec = {"id": uuid.uuid4().hex[:8], "name": name, "ids": [], "collapsed": False}
                    d["sections"].append(sec)
                sid = sec["id"]
            for s in d["sections"]:
                if s["id"] == sid:
                    s["ids"].append(bid)
        elif op == "add_section":
            name = str(data.get("name") or "New section").strip()[:40]
            d["sections"].append({"id": uuid.uuid4().hex[:8], "name": name, "ids": [], "collapsed": False})
        elif op == "collapse":
            for s in d["sections"]:
                if s["id"] == str(data.get("section") or ""):
                    s["collapsed"] = bool(data.get("on", not s["collapsed"]))
        elif op == "forget":        # bot deleted
            for k in ("pinned", "hidden", "unread"):
                _toggle(d[k], bid, False)
            for s in d["sections"]:
                _toggle(s["ids"], bid, False)
        else:
            raise ValueError("Unknown action: " + op)
        return _save(d)


def duplicate(bot_id: str) -> dict[str, Any]:
    src = bots.get_bot(bot_id)
    if not src:
        raise ValueError("No bot " + bot_id)
    copy = json.loads(json.dumps(src))
    copy.pop("id", None)
    copy["name"] = (src["name"] + " copy")[:60]
    copy["created"] = time.time()
    new = bots.save_bot(copy)          # settings, rules, tools, tasks, notes and lessons come along
    with _lock:
        d = load()
        for s in d["sections"]:
            if bot_id in s["ids"]:
                s["ids"].append(new["id"])
        _save(d)
    return new


def template(bot_id: str) -> dict[str, Any]:
    """The bot's setup for sharing - no id, no memory notes, nothing that looks like a secret."""
    b = bots.get_bot(bot_id)
    if not b:
        raise ValueError("No bot " + bot_id)
    clean = lambda t: "\n".join(l for l in str(t or "").splitlines() if not bots._looks_secret(l))
    rules = {k: v for k, v in (b.get("rules") or {}).items()
             if not any(w in str(k).lower() for w in ("key", "token", "secret", "password", "cookie"))}
    return {"pedbot_template": 1, "bot": {
        "name": b["name"], "color": b.get("color"), "avatar": b.get("avatar"), "role": clean(b.get("role")),
        "model": b.get("model") or "", "tools": b.get("tools") or [], "rules": rules,
        "tasks": b.get("tasks") or [],
        "skills": [{"name": s["name"], "text": clean(s.get("text"))} for s in b.get("skills") or []]}}
