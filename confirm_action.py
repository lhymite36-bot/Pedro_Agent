"""Ask before a high-impact tool runs.

Voice mode speaks one question and listens once. Text mode does not run the
tool until the next user message is a short yes. What needs a yes is set in
rules.yaml (confirm section).
"""

from __future__ import annotations

import contextlib
import contextvars
import os
import re
import threading
import time
from typing import Any, Callable, Iterator

POSITIVE = {
    "yes",
    "yeah",
    "yep",
    "confirm",
    "do it",
    "go ahead",
    "sure",
    "y",
    "ok",
    "okay",
}
_NETWORK = {
    "wifi_connect",
    "wifi_disconnect",
    "vpn_connect",
    "vpn_disconnect",
    "connect",
    "disconnect",
}

NEGATIVE = {"no", "nope", "nah", "cancel", "stop", "don't", "dont", "n"}

# 1.5.6: public posts need their own fresh Approve tap on the card; typed "ok"/"yes" never runs them,
# a card expires after CARD_TTL seconds, and every grant is used once and then cleared everywhere.
CARD_ONLY_TOOLS = {"make_quiet_brain_short", "youtube_upload"}
CARD_TTL = 600.0


def card_only(item: dict[str, Any] | None) -> bool:
    return bool(item) and item.get("name") in CARD_ONLY_TOOLS

# One waiting action per chat. Texting a different bot does not cancel this chat's yes.
_pending_by: dict[str, dict[str, Any]] = {}
_granted_by: dict[str, dict[str, Any]] = {}
_done: list[dict[str, Any]] = []      # actions already run after a yes (this conversation turn)
_recent_yes: dict[str, tuple[str, float]] = {}   # chat -> (category, when) of the last yes
YES_WINDOW_SECONDS = 180
_turn = threading.local()              # set while the chat layer has already read the user's message
_chat = contextvars.ContextVar("pedro_confirm_chat", default="")


def bind_chat(session: str) -> contextvars.Token:
    """Later yes/no answers apply only to this chat."""
    return _chat.set(session or "")


def unbind_chat(token: contextvars.Token) -> None:
    _chat.reset(token)


def _bucket() -> str:
    return _chat.get() or ""


def reset() -> None:
    _recent_yes.clear()
    _pending_by.clear()
    _granted_by.clear()
    _done.clear()


@contextlib.contextmanager
def user_turn(text: str) -> Iterator[None]:
    """The chat layer saw the user's real words. Nested agent calls (bot/group prompts wrap the
    text in instructions) must not re-read the wrapped prompt and cancel the yes."""
    note_user_text(text)
    _turn.noted = True
    try:
        yield
    finally:
        _turn.noted = False


def turn_already_noted() -> bool:
    return bool(getattr(_turn, "noted", False))


def _category(name: str, arguments: dict[str, Any]) -> str:
    try:
        import rules

        return str(rules.category_for(name, arguments) or name)
    except Exception:
        return name


def _key(name: str, arguments: dict[str, Any]) -> tuple[str, str]:
    """What the yes was about: the category plus the real target (free-text descriptions ignored)."""
    target = ""
    for k in ("path", "to", "recipient", "contact", "process_name", "target", "profile", "name", "id"):
        if arguments.get(k):
            target = str(arguments[k])
            break
    if target and ("path" in arguments):
        target = os.path.normcase(os.path.normpath(os.path.expandvars(os.path.expanduser(target.strip().strip('"')))))
    return _category(name, arguments), target.strip().replace("\\", "/").rstrip("/").casefold()


_PHOTO = {"capture_webcam_image", "webcam_vision_tool"}


def _same(a: dict[str, Any], name: str, arguments: dict[str, Any]) -> bool:
    if a.get("name") == name and a.get("arguments") == dict(arguments):
        return True
    if a.get("name") in _PHOTO and name in _PHOTO:   # 1.4.19: one photo request, whichever camera tool asks
        return True
    ka, kb = _key(a["name"], a["arguments"]), _key(name, arguments)
    if ka[0] != kb[0]:
        return False
    # confirm_before(kind=delete, description=...) approves the delete the model then makes
    return ka[1] == kb[1] or a["name"] == "confirm_before" or name == "confirm_before"


def _agent() -> Any:
    import agent_core

    return agent_core


def _folded_action(value: Any) -> str:
    return " ".join(str(value or "").casefold().replace("-", " ").replace("_", " ").split())


CAMERA_TOOLS = frozenset({"capture_webcam_image", "webcam_vision_tool", "record_pc_camera"})


def is_sensitive(name: str, arguments: dict[str, Any]) -> bool:
    """The user's rules.yaml (confirm section) decides what needs a yes."""
    import rules

    if name == "run_terminal_command":   # every terminal command needs its own yes, whatever rules.yaml says
        return True
    if name == "browser_login":   # 1.4.19: signing in always asks first
        return True
    if name == "make_quiet_brain_short" and not _truthy_dry(arguments):
        return True   # 1.5.4: scheduling a public post always asks
    if name == "builder_install" or (name == "ship_app" and str(arguments.get("target") or "").casefold() == "github"):
        return True   # 1.5.0: installs and GitHub pushes always ask
    if name in CAMERA_TOOLS:   # 1.4.19: the camera never opens without a yes on the card
        if set(k for k in arguments if k) - {"seconds", "question"}:
            return False   # bad arguments are refused by the tool itself, no card for them
        if name == "record_pc_camera":   # no length: the tool records nothing and asks, so no card yet
            return _agent()._record_length(arguments.get("seconds")) is not None
        return True
    return rules.needs_confirmation(name, arguments)


def label_for(name: str, arguments: dict[str, Any]) -> str:
    if name == "run_terminal_command":
        shell = str(arguments.get("shell") or "powershell")
        where = f" in {arguments.get('cwd')}" if arguments.get("cwd") else ""
        return f"run this {shell} command{where}: {' '.join(str(arguments.get('command') or '').split())[:300]}"
    if name == "delete_path":
        return f"delete {arguments.get('path') or 'that path'}"
    if name == "gmail_send_message":   # 1.4.16: the card names the sending account
        sender = ""
        try:
            import gmail_mail
            sender = gmail_mail.sending_account(str(arguments.get("from_account") or ""))
        except Exception:
            pass
        to = arguments.get('to') or arguments.get('recipient') or 'that contact'
        return f"send an email to {to}" + (f" from {sender}" if sender else "")
    if name == "youtube_upload":
        title = " ".join(str(arguments.get("title") or "that video").split())
        privacy = " ".join(str(arguments.get("privacy") or "private").split()) or "private"
        return f"post {title} on YouTube as {privacy}"
    if name == "create_routine":
        what = " ".join(str(arguments.get("name") or "a routine").split())[:60]
        when = " ".join(str(arguments.get("when") or "").split())[:40]
        return f"create the routine '{what}'" + (f" ({when})" if when else "")
    if name == "builder_install":
        return f"install {arguments.get('package') or 'a package'} with {arguments.get('manager') or 'pip'}"
    if name == "ship_app":
        return f"push the app '{arguments.get('name')}' to a new private GitHub repo"
    if name == "make_quiet_brain_short":
        return "make one Quiet Brain Short and schedule it publicly on YouTube (Quiet Brain) and TikTok via Buffer"
    if name == "browser_login":
        return f"log in to {arguments.get('site') or 'that site'} in your Chrome with its saved login"
    if name == "record_pc_camera":
        return f"record {arguments.get('seconds') or 'a few'} seconds of video with the PC camera (saved to Pictures\\Ped Bot)"
    if name in ("capture_webcam_image", "webcam_vision_tool"):
        return "take one photo with the PC camera (saved to Pictures\\Ped Bot)"
    if name == "send_remote_update":
        return "send a message to your phone"
    if name not in {"kill_process", "shutdown_computer", "manage_windows_and_processes", "network_manager"}:
        return f"run {name.replace('_', ' ')}"
    if name == "kill_process":
        return f"kill {arguments.get('process_name') or 'a program'}"
    if name == "shutdown_computer":
        return "shut down this PC"
    if name == "manage_windows_and_processes":
        return f"kill {arguments.get('target') or 'a program'}"
    action = str(arguments.get("action") or "network change").replace("_", " ")
    profile = " ".join(str(arguments.get("profile") or "").split())
    if profile:
        return f"{action} {profile}"
    return action


def remember(name: str, arguments: dict[str, Any], label: str) -> None:
    if name == "run_terminal_command":   # 1.4.16: start the console while Pedro reads the card (runs nothing)
        try:
            import terminal_tool
            if terminal_tool.warm_ok(str(arguments.get("command") or ""), str(arguments.get("shell") or "powershell")):
                threading.Thread(target=terminal_tool.prewarm, daemon=True).start()
        except Exception:
            pass
    current = _pending_by.get(_bucket())
    if current is not None and (_same(current, name, arguments) or
                                (current.get("name") in CAMERA_TOOLS and name in CAMERA_TOOLS)):
        return   # already waiting on this yes: keep the one card (same id), never a new popup
    _wait_for_approval_turn()
    import uuid
    _pending_by[_bucket()] = {
        "name": name,
        "arguments": dict(arguments),
        "label": label,
        "id": uuid.uuid4().hex[:12],   # 1.4.19: Approve/Deny answer this exact request
        "bucket": _bucket(),
        "ts": __import__("time").monotonic(),
    }


APPROVAL_QUEUE_WAIT = 600.0


def _board_bucket(bucket: str) -> bool:
    return bucket.startswith("task-") or "#task-" in bucket


def _wait_for_approval_turn() -> None:
    """1.4.18: background tasks ask for approval one at a time.

    A board task that reaches a change while another board task's card is still open waits here
    (Stop still works) until that card is answered. Chats Pedro is typing in are never held.
    """
    me = _bucket()
    if not _board_bucket(me):
        return
    import stop_token
    deadline = time.monotonic() + APPROVAL_QUEUE_WAIT
    while time.monotonic() < deadline:
        others = [b for b in list(_pending_by) if b != me and _board_bucket(b)]
        if not others:
            return
        if stop_token.wait(0.5):
            return


def drop_pending(bucket: str) -> None:
    """1.4.18: a stopped board task's open card is withdrawn (nothing runs)."""
    _pending_by.pop(bucket, None)
    _granted_by.pop(bucket, None)


def waiting_labels() -> set[str]:
    """Labels of every action waiting for a yes, in any chat (cards are drawn outside the chat's context)."""
    return {str(v.get("label") or "") for v in list(_pending_by.values()) if v}


def pending() -> dict[str, Any] | None:
    """The action waiting for a yes in this chat, or None."""
    item = _pending_by.get(_bucket())
    return dict(item) if item is not None else None


def note_user_text(text: str) -> None:
    """A short yes grants the one action that is waiting. Anything else cancels it.
    Ignored while the chat layer already handled this message (nested bot/group prompts)."""
    if turn_already_noted():
        return
    folded = " ".join((text or "").casefold().split()).strip(" .!?")
    if not folded:
        return
    key = _bucket()
    if folded in POSITIVE and card_only(_pending_by.get(key)):
        return   # typed yes/ok never approves a public post; the card stays for a real tap
    if folded in POSITIVE and _pending_by.get(key) is not None:
        item = _pending_by.pop(key)
        _granted_by[key] = item
        import time as _t

        if item["name"] == "confirm_before":   # only a general "may I?" yes carries to the real action
            _recent_yes[key] = (_key(item["name"], item["arguments"])[0], _t.monotonic())
        return
    _lift_denied_by_request(key, folded)
    dropped = _pending_by.pop(key, None)
    if dropped is not None and folded in NEGATIVE:
        _note_denied(key, dropped)
    _granted_by.pop(key, None)
    _done.clear()


# 1.4.19: a denied action is never asked again in that chat for a while (no card loops)
DENY_MEMORY_SECONDS = 600.0
_denied: dict[str, list[tuple[tuple[str, str], float]]] = {}


def _note_denied(bucket: str, item: dict[str, Any]) -> None:
    import time as _t
    rows = [r for r in _denied.get(bucket, []) if _t.monotonic() - r[1] < DENY_MEMORY_SECONDS]
    rows.append((_key(item["name"], item["arguments"]), _t.monotonic(), _words(str(item.get("label") or item["name"]))))
    _denied[bucket] = rows[-20:]


_STOP = {"with", "that", "this", "your", "from", "saved", "into", "file", "the", "pictures", "bot"}


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]{4,}", text.casefold()) if w not in _STOP}


def _lift_denied_by_request(bucket: str, folded: str) -> None:
    """Pedro asking for the same thing again in his own words lifts his earlier no (the bot may not re-ask by itself)."""
    if folded in NEGATIVE or folded in POSITIVE:
        return
    rows = _denied.get(bucket)
    if rows:
        said = _words(folded)
        _denied[bucket] = [r for r in rows if not (len(r) > 2 and r[2] & said)]


def was_denied(name: str, arguments: dict[str, Any]) -> bool:
    import time as _t
    k = _key(name, arguments)
    return any(r[0][0] == k[0] and (r[0][1] == k[1] or not r[0][1] or not k[1])
               and _t.monotonic() - r[1] < DENY_MEMORY_SECONDS for r in _denied.get(_bucket(), []))


def clear_denied(name: str = "") -> None:
    """A new explicit request from Pedro (his own words) lifts an earlier no."""
    rows = _denied.get(_bucket())
    if rows:
        _denied[_bucket()] = [r for r in rows if name and r[0][0] != _category(name, {})]


def all_pending() -> list[dict[str, Any]]:
    return [dict(v) for v in _pending_by.values() if v]


def resolve(request_id: str, approve: bool, invoke: Callable[[str, dict[str, Any]], dict[str, Any]]) -> dict[str, Any]:
    """Answer one exact pending request (from the Approve/Deny buttons). Unknown or already answered: nothing runs."""
    hit = next(((b, v) for b, v in list(_pending_by.items()) if v and v.get("id") == request_id), None)
    if hit is None:
        return {"ok": False, "resolved": False, "error": "That request was already answered."}
    bucket, item = hit
    token = _chat.set(bucket)
    try:
        _pending_by.pop(bucket, None)
        import time as _t
        if approve and card_only(item) and _t.monotonic() - float(item.get("ts") or 0) > CARD_TTL:
            return {"ok": True, "resolved": True, "session": bucket, "approved": False,
                    "text": "That approval card expired, so nothing was posted. Ask again for a fresh card."}
        if not approve:
            _note_denied(bucket, item)
            _granted_by.pop(bucket, None)
            return {"ok": True, "resolved": True, "session": bucket, "approved": False,
                    "text": f"Cancelled: {item.get('label') or item['name']}. I won't ask again for this."}
        _granted_by[bucket] = item
        try:
            result = invoke(item["name"], item["arguments"])
        finally:
            if card_only(item):   # used once, success or failure; nothing left for a later "ok"
                _granted_by.pop(bucket, None)
                for b, v in list(_pending_by.items()):
                    if v and v.get("name") == item["name"]:
                        _pending_by.pop(b, None)
        detail = str(result.get("message") or result.get("error") or "")
        return {"ok": True, "resolved": True, "session": bucket, "approved": True, "result_ok": bool(result.get("ok")),
                "text": ("Done: " if result.get("ok") else "That failed: ") + _user_detail(result, detail),
                "image": result.get("download_path") if str(result.get("download_path") or "").lower().endswith((".jpg", ".png")) else None,
                "video": result.get("video")}
    finally:
        _chat.reset(token)


def consume_grant(name: str, arguments: dict[str, Any]) -> bool:
    """True once for the approved action (or the real action a confirm_before yes was about)."""
    key = _bucket()
    granted = _granted_by.get(key)
    if name in CARD_ONLY_TOOLS:
        if granted is not None and granted.get("name") == name and _same(granted, name, arguments):
            _granted_by.pop(key, None)
            return True
        return False
    if granted is None or not _same(granted, name, arguments):
        # Asked once: a yes to confirm_before for this kind of action covers the real action
        # that follows in the next few minutes, so the user is not asked again and again.
        recent = _recent_yes.get(key)
        import time as _t

        if (recent and name != "confirm_before" and recent[0] == _key(name, arguments)[0]
                and _t.monotonic() - recent[1] <= YES_WINDOW_SECONDS
                and (granted is None or granted.get("name") == "confirm_before")):
            _granted_by.pop(key, None)
            _recent_yes.pop(key, None)   # used once
            return True
        return False
    if name == "confirm_before" and granted.get("name") == "confirm_before":
        return True   # the model re-checking; keep the grant for the delete/send that follows
    _granted_by.pop(key, None)
    return True


def already_done(name: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
    """The result of this action if it already ran after a yes (so it is never asked or run twice)."""
    if _category(name, arguments) not in {"delete", "send_message"}:   # repeating those is never wanted
        return None
    for d in _done:
        if _same(d, name, arguments) and name != "confirm_before":
            return d["result"]
    return None


def note_done(name: str, arguments: dict[str, Any], result: dict[str, Any]) -> None:
    _done.append({"name": name, "arguments": dict(arguments), "result": dict(result)})
    del _done[:-10]


def _user_detail(result: dict[str, Any], detail: str) -> str:
    """1.4.19: show Pedro the outcome, not instructions meant for the model; name the saved file."""
    keep = [x for x in re.split(r"(?<=[.!?])\s+", detail) if x and not re.match(
        r"(Describe|Do not|Use the path|Only describe|Answer)\b", x)]
    text = " ".join(keep).strip() or detail
    where = result.get("download_path") or result.get("video_path") or result.get("path") or ""
    if result.get("ok") and where and str(where) not in text:
        text += f" Saved to {where}"
    if result.get("what_i_see"):
        text += f" What I see: {result['what_i_see']}"
    return text


def answer_pending(text: str, invoke: Callable[[str, dict[str, Any]], dict[str, Any]]) -> str | None:
    """Chat layer: a yes/no to the waiting action. 'yes' runs it once right away (no model round,
    so it can't be re-asked); 'no' cancels. Returns the reply, or None to carry on normally
    (also for confirm_before, whose yes is granted and the model then does the clicking)."""
    waiting = pending()
    if waiting is None:
        return None
    folded = " ".join((text or "").casefold().split()).strip(" .!?")
    label = waiting.get("label") or waiting["name"]
    if folded in NEGATIVE:
        note_user_text(text)
        return f"Cancelled: {label}."
    if folded in POSITIVE and card_only(waiting):
        return f"To {label}, tap Approve on the card. A typed reply doesn't approve public posts."
    if folded not in POSITIVE or waiting["name"] == "confirm_before":
        return None
    note_user_text(text)            # pending -> granted
    result = invoke(waiting["name"], waiting["arguments"])
    detail = str(result.get("message") or result.get("error") or "")
    return ("Done: " if result.get("ok") else "That failed: ") + _user_detail(result, detail)


def _positive(text: str) -> bool:
    folded = " ".join((text or "").casefold().split()).strip(" .!?")
    return folded in POSITIVE


def _speak(prompt: str) -> None:
    agent = _agent()
    speaker = agent.confirm_speaker_override
    if speaker is not None:
        speaker(prompt)
        return
    agent.speak_response(prompt)


def _listen() -> str:
    agent = _agent()
    listener = agent.confirm_listener_override
    if listener is not None:
        heard = listener()
        return "" if heard is None else str(heard)
    heard = agent.listen_to_microphone(timeout=6, phrase_time_limit=None, announce=False)
    if not isinstance(heard, dict) or not heard.get("ok"):
        return ""
    return str(heard.get("text") or "")


def confirm_sensitive_action(label: str) -> dict[str, Any]:
    """Ask once. approved is true only after a clear yes."""
    agent = _agent()
    shown = " ".join((label or "that action").split())
    if agent.voice_mode_active:
        _speak(f"Are you sure you want to execute {shown}?")
        if _positive(_listen()):
            return agent._ok("Confirmed.", approved=True, label=shown)
        return agent._err("Not confirmed.", approved=False, label=shown)
    return agent._err(
        f"Waiting for a yes before {shown}.",
        needs_confirmation=True,
        approved=False,
        label=shown,
    )


def is_short_yes(text: str) -> bool:
    """1.4.15: a bare yes/no goes to the normal chat path (it answers a waiting action), not to the mid-task responder."""
    folded = " ".join((text or "").casefold().split()).strip(" .!?")
    return folded in POSITIVE or folded in NEGATIVE


def _truthy_dry(arguments: dict[str, Any]) -> bool:
    v = arguments.get("dry_run", True)
    return not (v is False or str(v).strip().casefold() in {"false", "0", "no"})
