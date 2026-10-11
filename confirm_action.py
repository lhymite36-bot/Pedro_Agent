"""Ask before a high-impact tool runs.

Voice mode speaks one question and listens once. Text mode does not run the
tool until the next user message is a short yes. There is no registry editor
and no general delete tool.
"""

from __future__ import annotations

from typing import Any

POSITIVE = {
    "yes",
    "yeah",
    "yep",
    "confirm",
    "do it",
    "go ahead",
    "sure",
}
_NETWORK = {
    "wifi_connect",
    "wifi_disconnect",
    "vpn_connect",
    "vpn_disconnect",
    "connect",
    "disconnect",
}

_pending: dict[str, Any] | None = None
_granted: dict[str, Any] | None = None


def reset() -> None:
    global _pending, _granted
    _pending = None
    _granted = None


def _agent() -> Any:
    import gta5_agent

    return gta5_agent


def _folded_action(value: Any) -> str:
    return " ".join(str(value or "").casefold().replace("-", " ").replace("_", " ").split())


def is_sensitive(name: str, arguments: dict[str, Any]) -> bool:
    if name == "kill_process":
        return True
    if name == "shutdown_computer":
        return True
    if name == "manage_windows_and_processes":
        return _folded_action(arguments.get("action")) in {"kill", "kill process"}
    if name == "network_manager":
        action = str(arguments.get("action") or "").strip().casefold().replace("-", "_").replace(" ", "_")
        return action in _NETWORK
    return False


def label_for(name: str, arguments: dict[str, Any]) -> str:
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
    global _pending
    _pending = {
        "name": name,
        "arguments": dict(arguments),
        "label": label,
    }


def note_user_text(text: str) -> None:
    """A short yes grants the one action that is waiting. Anything else cancels it."""
    global _pending, _granted
    folded = " ".join((text or "").casefold().split()).strip(" .!?")
    if not folded:
        return
    if folded in POSITIVE and _pending is not None:
        _granted = _pending
        _pending = None
        return
    _pending = None
    _granted = None


def consume_grant(name: str, arguments: dict[str, Any]) -> bool:
    global _granted
    if _granted is None:
        return False
    if _granted.get("name") != name or _granted.get("arguments") != dict(arguments):
        return False
    _granted = None
    return True


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
