"""CPU, memory, and process snapshot. This tool does not close programs.

Tests set diagnostics_override and must not inspect real processes or run
nvidia-smi. Ask the user before a later kill_process call.
"""

from __future__ import annotations

import subprocess
from typing import Any


def _agent() -> Any:
    import gta5_agent

    return gta5_agent


def _gpu_line() -> str | None:
    try:
        completed = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu",
                "--format=csv,noheader,nounits",
            ],
            shell=False,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    line = (completed.stdout or "").strip().splitlines()
    if not line:
        return None
    parts = [part.strip() for part in line[0].split(",")]
    if len(parts) < 5:
        return None
    name, util, used, total, temp = parts[:5]
    return (
        f"GPU {name} is at {util}% with {used} MB of {total} MB VRAM, "
        f"{temp} C."
    )


def _live_sample() -> dict[str, Any]:
    import psutil

    memory = psutil.virtual_memory()
    processes: list[dict[str, Any]] = []
    for proc in psutil.process_iter(["pid", "name", "memory_info"]):
        info = proc.info or {}
        name = str(info.get("name") or "")
        if not name:
            continue
        rss = getattr(info.get("memory_info"), "rss", 0) or 0
        processes.append(
            {
                "pid": int(info.get("pid") or 0),
                "name": name,
                "rss_mb": round(int(rss) / (1024 * 1024), 1),
            }
        )
    processes.sort(key=lambda row: float(row["rss_mb"]), reverse=True)
    sample: dict[str, Any] = {
        "cpu_percent": psutil.cpu_percent(interval=0.0),
        "ram_percent": memory.percent,
        "ram_used_mb": round(memory.used / (1024 * 1024)),
        "ram_total_mb": round(memory.total / (1024 * 1024)),
        "processes": processes[:8],
    }
    gpu = _gpu_line()
    if gpu:
        sample["gpu"] = gpu
    return sample


def system_diagnostics() -> dict[str, Any]:
    """Describe load and the largest processes. Does not stop any of them."""
    agent = _agent()
    try:
        if agent.diagnostics_override is not None:
            sample = agent.diagnostics_override()
            if not isinstance(sample, dict):
                return agent._err("The diagnostics sample was empty.")
        else:
            sample = _live_sample()
        cpu = sample.get("cpu_percent", "unknown")
        ram = sample.get("ram_percent", "unknown")
        used = sample.get("ram_used_mb", "?")
        total = sample.get("ram_total_mb", "?")
        lines = [
            f"CPU is at {cpu} percent.",
            f"Memory is at {ram} percent ({used} MB of {total} MB).",
        ]
        gpu = sample.get("gpu")
        if gpu:
            lines.append(str(gpu))
        else:
            lines.append("GPU stats are unavailable.")
        rows = sample.get("processes") or []
        if rows:
            lines.append("Largest processes:")
            for row in list(rows)[:8]:
                if not isinstance(row, dict):
                    continue
                lines.append(
                    f"- {row.get('name')} pid {row.get('pid')} using {row.get('rss_mb')} MB."
                )
        lines.append(
            "Ask me to close one program by name if you want it stopped. "
            "This check does not close anything."
        )
        message = " ".join(lines)
        return agent._ok(
            message,
            cpu_percent=sample.get("cpu_percent"),
            ram_percent=sample.get("ram_percent"),
            ram_used_mb=sample.get("ram_used_mb"),
            ram_total_mb=sample.get("ram_total_mb"),
            gpu=str(sample.get("gpu") or ""),
            processes=list(rows)[:8],
        )
    except AssertionError:
        raise
    except Exception as exc:
        return agent._err(f"system_diagnostics failed: {exc}")


DECLARATIONS = [
    {
        "name": "system_diagnostics",
        "description": (
            "Report CPU, memory, the largest processes, and GPU stats when "
            "they are available. It does not close or renice anything. Offer "
            "to close one named program, which still waits for a yes."
        ),
        "parameters": {"type": "object", "properties": {}},
    }
]
