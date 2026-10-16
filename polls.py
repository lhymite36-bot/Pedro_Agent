"""1.4.10: question cards (ask_user) and Approve/Deny cards in the chat.

A bot that needs a decision calls ask_user: a card with up to 6 tap options (single or multi-select,
optional free-text "Other") is saved in the chat as a row "[[card:<id>]]", so it survives reloads.
The tapped answer is sent back as the user's next message and the task continues.
Approval requests (send / delete / order / pay) get the same kind of card with Approve / Deny.
"""

from __future__ import annotations

import json
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent / "workspace"
_DEFAULT_ROOT = ROOT
_lock = threading.Lock()
MARK = re.compile(r"^\[\[card:([0-9a-f]{12})\]\]$")
_turn_cards = threading.local()  # cards made during this chat's turn


def _card_ids() -> list[str]:
    ids = getattr(_turn_cards, "ids", None)
    if ids is None:
        ids = []
        _turn_cards.ids = ids
    return ids


def _path() -> Path:
    import os
    base = ROOT
    if ROOT == _DEFAULT_ROOT and os.environ.get("STORAGE_DIR"):   # tests and portable setups keep cards with the chats
        base = Path(os.environ["STORAGE_DIR"])
    base.mkdir(parents=True, exist_ok=True)
    return base / "cards.json"


def _load() -> dict[str, Any]:
    try:
        return json.loads(_path().read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(data: dict[str, Any]) -> None:
    if len(data) > 500:
        for k in sorted(data, key=lambda k: data[k].get("t", ""))[:-500]:
            data.pop(k, None)
    _path().write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")


def begin_turn() -> None:
    _turn_cards.ids = []


def take_turn_cards() -> list[dict[str, Any]]:
    ids = list(_card_ids())
    _turn_cards.ids = []
    data = _load()
    return [data[i] for i in ids if i in data]


def _add(card: dict[str, Any]) -> dict[str, Any]:
    card = {"id": uuid.uuid4().hex[:12], "t": time.strftime("%Y-%m-%d %H:%M:%S"), "status": "open", **card}
    with _lock:
        data = _load(); data[card["id"]] = card; _save(data)
    _card_ids().append(card["id"])
    return card


def ask_user(question: str, options: list[str], multi_select: bool = False, allow_other: bool = False) -> dict[str, Any]:
    question = " ".join(str(question or "").split())
    opts = []
    for o in options or []:
        o = " ".join(str(o or "").split())[:80]
        if o and o not in opts:
            opts.append(o)
    if not question:
        return {"ok": False, "error": "Give the question."}
    if not 2 <= len(opts) <= 6 and not (allow_other and len(opts) >= 1):
        return {"ok": False, "error": "Give 2 to 6 short options."}
    card = _add({"kind": "question", "question": question[:300], "options": opts[:6],
                 "multi": bool(multi_select), "other": bool(allow_other)})
    return {"ok": True, "card_id": card["id"], "stop": True,
            "message": "The question card is shown to Pedro. STOP now and end your turn without guessing; "
                       "his tapped answer comes back as his next message, then continue the task."}


def approval_card(label: str, action: str, order: dict[str, Any] | None = None) -> dict[str, Any]:
    """Card for a waiting send/delete/order/pay. Replaces any older open approval card."""
    with _lock:
        data = _load()
        for c in data.values():
            if c.get("kind") == "approval" and c.get("status") == "open":
                c["status"] = "expired"
        _save(data)
    return _add({"kind": "approval", "question": label, "action": action, "order": order or None})


def expire_open_approvals(except_label: str = "") -> None:
    with _lock:
        data = _load(); changed = False
        for c in data.values():
            if c.get("kind") == "approval" and c.get("status") == "open" and c.get("question") != except_label:
                c["status"] = "expired"; changed = True
        if changed:
            _save(data)


def get(cid: str) -> dict[str, Any] | None:
    return _load().get(str(cid or ""))


def answer(cid: str, choices: list[str] | None = None, other: str = "", decision: str = "") -> dict[str, Any]:
    """Record a tap. Returns the text to send as Pedro's reply. A card can be answered once."""
    with _lock:
        data = _load(); c = data.get(str(cid or ""))
        if not c:
            return {"ok": False, "error": "That card no longer exists."}
        if c.get("status") != "open":
            return {"ok": False, "error": "Already answered." if c.get("status") == "answered" else "This request expired.", "card": c}
        if c["kind"] == "approval":
            if decision not in {"approve", "deny"}:
                return {"ok": False, "error": "Choose Approve or Deny."}
            c["answer"] = {"decision": decision}
            text = "yes" if decision == "approve" else "no"
        else:
            picked = [x for x in (choices or []) if x in c["options"]]
            other = " ".join(str(other or "").split())[:300] if c.get("other") else ""
            if not c.get("multi"):
                picked = picked[:1]
                if picked and other:
                    other = ""
            if not picked and not other:
                return {"ok": False, "error": "Pick an option."}
            c["answer"] = {"choices": picked, "other": other}
            parts = picked + ([other] if other else [])
            text = ", ".join(parts) if c.get("multi") else parts[0]
            text = f"{text}" if len(text) < 200 else text[:200]
            text = f"(Answer to \"{c['question'][:80]}\") {text}"
        c["status"] = "answered"; c["answered"] = time.strftime("%Y-%m-%d %H:%M:%S")
        _save(data)
    return {"ok": True, "text": text, "card": c}


def view(cid: str, pending: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Card as the page shows it. An open approval that is no longer the waiting action shows expired."""
    c = get(cid)
    if not c:
        return None
    c = dict(c)
    if c["kind"] == "approval" and c["status"] == "open":
        if not pending or (pending.get("label") or "") != c["question"]:
            c["status"] = "expired"
    if c.get("order"):
        try:
            import order_flow
            live = order_flow.pending_card()
            if live and live.get("order_id") == c["order"].get("order_id"):
                c["order"] = live
        except Exception:
            pass
    return c


DECLARATIONS = [
    {"name": "ask_user",
     "description": "Ask Pedro to choose when you need a decision (which item, which option, which time). Shows a card with up to 6 tap options (multi_select for several, allow_other for a free-text answer). After calling it, STOP and end your turn; his answer arrives as his next message. Don't use it for yes/no approvals of send/delete/order (those get Approve/Deny cards automatically).",
     "parameters": {"type": "object", "properties": {
         "question": {"type": "string"},
         "options": {"type": "array", "items": {"type": "string"}, "description": "2 to 6 short options."},
         "multi_select": {"type": "boolean"}, "allow_other": {"type": "boolean"}},
         "required": ["question", "options"]}},
]
TOOLS = {"ask_user": ask_user}
