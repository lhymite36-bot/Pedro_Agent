"""Ask before a high-impact tool runs.

Voice mode speaks one question and listens once. Text mode does not run the
tool until the next user message is a short yes. What needs a yes is set in
rules.yaml (confirm section).
"""

from __future__ import annotations

import contextlib
import contextvars
import os
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


def _same(a: dict[str, Any], name: str, arguments: dict[str, Any]) -> bool:
    if a.get("name") == name and a.get("arguments") == dict(arguments):
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


def is_sensitive(name: str, arguments: dict[str, Any]) -> bool:
    """The user's rules.yaml (confirm section) decides what needs a yes."""
    import rules

    if name == "run_terminal_command":   # every terminal command needs its own yes, whatever rules.yaml says
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
    if current is not None and _same(current, name, arguments):
        return   # already waiting on this exact yes: keep the one card, do not ask again
    _wait_for_approval_turn()
    _pending_by[_bucket()] = {
        "name": name,
        "arguments": dict(arguments),
        "label": label,
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
    if folded in POSITIVE and _pending_by.get(key) is not None:
        item = _pending_by.pop(key)
        _granted_by[key] = item
        import time as _t

        if item["name"] == "confirm_before":   # only a general "may I?" yes carries to the real action
            _recent_yes[key] = (_key(item["name"], item["arguments"])[0], _t.monotonic())
        return
    _pending_by.pop(key, None)
    _granted_by.pop(key, None)
    _done.clear()


def consume_grant(name: str, arguments: dict[str, Any]) -> bool:
    """True once for the approved action (or the real action a confirm_before yes was about)."""
    key = _bucket()
    granted = _granted_by.get(key)
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
    if folded not in POSITIVE or waiting["name"] == "confirm_before":
        return None
    note_user_text(text)            # pending -> granted
    result = invoke(waiting["name"], waiting["arguments"])
    detail = str(result.get("message") or result.get("error") or "")
    return ("Done: " if result.get("ok") else "That failed: ") + detail


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
