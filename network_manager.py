"""Read this PC's network and switch a named Wi-Fi or VPN profile.

The model cannot pass a command string. Connect and disconnect are sensitive
and wait for a yes in the tool loop. Tests set network_runner_override and
must not spawn netsh, ipconfig, rasdial, or speedtest.
"""

from __future__ import annotations

import shutil
import subprocess
from typing import Any

_PROFILE = __import__("re").compile(r"^[\w ._-]{1,64}$")
_BLOCKED = ("&", "|", ";", ">", "<", "`", "\n", "\r")


def _agent() -> Any:
    import agent_core

    return agent_core


def _run(command: list[str], timeout: float) -> dict[str, Any]:
    agent = _agent()
    for part in command:
        if any(token in part for token in _BLOCKED):
            return agent._err("That network command is not allowed.")
    if agent.network_runner_override is not None:
        result = agent.network_runner_override(list(command))
        if not isinstance(result, dict):
            return agent._err("The network command returned nothing.")
        return result
    completed = subprocess.run(
        command,
        shell=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return {
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def _profile(value: str) -> str | None:
    text = " ".join((value or "").split())
    if not text or _PROFILE.fullmatch(text) is None:
        return None
    return text


def _finish(command: list[str], timeout: float, label: str) -> dict[str, Any]:
    agent = _agent()
    try:
        result = _run(command, timeout)
    except subprocess.TimeoutExpired:
        return agent._err(f"{label} timed out.")
    if result.get("ok") is False and "error" in result and "returncode" not in result:
        return result
    code = int(result.get("returncode") or 0)
    stdout = agent._scrub(str(result.get("stdout") or ""))[:800]
    stderr = agent._scrub(str(result.get("stderr") or ""))[:400]
    if code != 0:
        detail = stderr or stdout or f"exit {code}"
        return agent._err(f"{label} failed. {detail}".strip())
    body = stdout.strip() or f"{label} finished."
    return agent._ok(body, command=command)


def network_manager(action: str, profile: str = "") -> dict[str, Any]:
    """status, wifi_list, wifi_connect, wifi_disconnect, vpn_connect, vpn_disconnect, or speed."""
    agent = _agent()
    try:
        key = str(action or "").strip().casefold().replace("-", "_").replace(" ", "_")
        if key in {"status", "ipconfig"}:
            return _finish(["ipconfig"], 8, "Network status")
        if key in {"wifi_list", "profiles"}:
            return _finish(["netsh", "wlan", "show", "profiles"], 8, "Wi-Fi profiles")
        if key == "speed":
            if agent.network_runner_override is None:
                if shutil.which("speedtest") is None and shutil.which("speedtest-cli") is None:
                    return agent._err(
                        "speedtest-cli is not installed, so the speed test was skipped."
                    )
                command = ["speedtest", "--json"] if shutil.which("speedtest") else ["speedtest-cli", "--json"]
            else:
                command = ["speedtest", "--json"]
            return _finish(command, 20, "Speed test")
        if key in {"wifi_connect", "connect"}:
            name = _profile(profile)
            if name is None:
                return agent._err("profile must be a Wi-Fi profile name, with no shell characters.")
            return _finish(["netsh", "wlan", "connect", f"name={name}"], 20, f"Wi-Fi connect {name}")
        if key == "wifi_disconnect":
            return _finish(["netsh", "wlan", "disconnect"], 15, "Wi-Fi disconnect")
        if key == "vpn_connect":
            name = _profile(profile)
            if name is None:
                return agent._err("profile must be a VPN profile name, with no shell characters.")
            return _finish(["rasdial", name], 25, f"VPN connect {name}")
        if key in {"vpn_disconnect", "disconnect"}:
            name = _profile(profile)
            if name is None:
                return agent._err("profile must be a VPN profile name, with no shell characters.")
            return _finish(["rasdial", name, "/disconnect"], 20, f"VPN disconnect {name}")
        return agent._err(
            "action must be status, wifi_list, wifi_connect, wifi_disconnect, "
            "vpn_connect, vpn_disconnect, or speed."
        )
    except AssertionError:
        raise
    except Exception as exc:
        return agent._err(f"network_manager failed: {exc}")


DECLARATIONS = [
    {
        "name": "network_manager",
        "description": (
            "Check this PC's network, list Wi-Fi profiles, test speed, or "
            "connect or disconnect a configured Wi-Fi or VPN profile. Do not "
            "pass a command string. Connect and disconnect wait for a yes."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": (
                        "status, wifi_list, wifi_connect, wifi_disconnect, "
                        "vpn_connect, vpn_disconnect, or speed."
                    ),
                },
                "profile": {
                    "type": "string",
                    "description": "Wi-Fi or VPN profile name. Not a shell command.",
                },
            },
            "required": ["action"],
        },
    }
]
