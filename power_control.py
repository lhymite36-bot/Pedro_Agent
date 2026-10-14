"""Shut down this PC.

The model cannot pass a command string. shutdown_computer waits for a yes
in the tool loop before this module runs. Tests set shutdown_runner_override
and must not spawn shutdown.exe.
"""

from __future__ import annotations

import os
import subprocess
from typing import Any

SHUTDOWN_COMMAND = ["shutdown", "/s", "/t", "0"]


def _agent() -> Any:
    import agent_core

    return agent_core


def shutdown_computer() -> dict[str, Any]:
    """Ask Windows to shut down this PC. The command list is fixed."""
    agent = _agent()
    command = list(SHUTDOWN_COMMAND)
    try:
        if agent.shutdown_runner_override is not None:
            result = agent.shutdown_runner_override(command)
        elif os.name != "nt":
            return agent._err("Shutting down is only set up on Windows.")
        else:
            completed = subprocess.run(
                command,
                shell=False,
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
            result = {
                "returncode": completed.returncode,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
            }
    except AssertionError:
        raise
    except subprocess.TimeoutExpired:
        return agent._err("The PC did not shut down. The request timed out.")
    except Exception as exc:
        return agent._err(f"The PC did not shut down. {agent._scrub(str(exc))}")
    if not isinstance(result, dict):
        return agent._err("The shutdown command returned nothing.")
    if result.get("ok") is False and "returncode" not in result:
        return result
    code = int(result.get("returncode") or 0)
    if code != 0:
        detail = agent._scrub(
            str(result.get("stderr") or result.get("stdout") or f"exit {code}")
        )[:300]
        return agent._err(f"The PC did not shut down. {detail}".strip())
    return agent._ok("Shutting down this PC.", command=command)
