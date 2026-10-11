"""Call a local MCP server named in the user's config.

The model picks a server name, a tool name, and a JSON object. The command
line comes from workspace/mcp_servers.json or MCP_CONFIG, not from the model.
Tests set mcp_transport_override and never start a process.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
from pathlib import Path
from typing import Any

TIMEOUT_SECONDS = 20
_PROTOCOL = "2024-11-05"


def _agent() -> Any:
    import gta5_agent

    return gta5_agent


def _config_path() -> Path | None:
    agent = _agent()
    override = agent.mcp_config_override
    if override:
        return Path(override)
    configured = os.environ.get("MCP_CONFIG", "").strip().strip('"')
    if configured:
        return Path(configured).expanduser()
    return agent.WORKSPACE / "mcp_servers.json"


def _load_servers() -> dict[str, dict[str, Any]]:
    path = _config_path()
    if path is None or not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("The MCP config could not be read.") from exc
    raw = data.get("servers") if isinstance(data, dict) else None
    if not isinstance(raw, dict):
        return {}
    servers: dict[str, dict[str, Any]] = {}
    for name, spec in raw.items():
        if not isinstance(name, str) or not name.strip():
            continue
        if not isinstance(spec, dict):
            continue
        command = spec.get("command")
        args = spec.get("args") or []
        if not isinstance(command, str) or not command.strip():
            continue
        if any(token in command for token in ("&", "|", ";", ">", "<", "`", "\n", "\r")):
            continue
        if not isinstance(args, list) or not all(isinstance(item, str) for item in args):
            continue
        servers[name.strip()] = {"command": command.strip(), "args": list(args)}
    return servers


def _object_arguments(raw: Any) -> dict[str, Any] | None:
    if raw is None or raw == "":
        return {}
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, str):
        text = raw.strip()
        if not text.startswith("{"):
            return None
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return None
        if isinstance(parsed, dict):
            return parsed
    return None


def _write_frame(stdin: Any, payload: dict[str, Any]) -> None:
    raw = json.dumps(payload).encode("utf-8")
    header = f"Content-Length: {len(raw)}\r\n\r\n".encode("ascii")
    stdin.write(header + raw)
    stdin.flush()


def _read_frame(stdout: Any) -> dict[str, Any]:
    header = b""
    while b"\r\n\r\n" not in header:
        chunk = stdout.read(1)
        if not chunk:
            raise RuntimeError("The MCP server closed the connection.")
        header += chunk
        if len(header) > 65536:
            raise RuntimeError("The MCP server sent a header that is too large.")
    text = header.split(b"\r\n\r\n", 1)[0].decode("ascii", errors="replace")
    length = 0
    for line in text.split("\r\n"):
        if line.lower().startswith("content-length:"):
            length = int(line.split(":", 1)[1].strip())
    if length <= 0 or length > 2_000_000:
        raise RuntimeError("The MCP server sent a bad content length.")
    body = b""
    while len(body) < length:
        part = stdout.read(length - len(body))
        if not part:
            raise RuntimeError("The MCP server closed the connection.")
        body += part
    parsed = json.loads(body.decode("utf-8"))
    if not isinstance(parsed, dict):
        raise RuntimeError("The MCP server sent an unexpected response.")
    return parsed


def _request(process: subprocess.Popen[bytes], method: str, params: dict[str, Any], ident: int) -> dict[str, Any]:
    _write_frame(
        process.stdin,
        {"jsonrpc": "2.0", "id": ident, "method": method, "params": params},
    )
    box: dict[str, Any] = {}

    def _read() -> None:
        try:
            while True:
                message = _read_frame(process.stdout)
                if message.get("id") == ident:
                    box["message"] = message
                    return
        except Exception as exc:
            box["error"] = exc

    reader = threading.Thread(target=_read, name="mcp-read", daemon=True)
    reader.start()
    reader.join(TIMEOUT_SECONDS)
    if reader.is_alive():
        process.kill()
        raise TimeoutError("The MCP server timed out.")
    if "error" in box:
        raise RuntimeError(str(box["error"]))
    message = box.get("message") or {}
    if message.get("error"):
        detail = message["error"]
        text = detail.get("message") if isinstance(detail, dict) else str(detail)
        raise RuntimeError(text or "The MCP server returned an error.")
    result = message.get("result")
    return result if isinstance(result, dict) else {}


def _stdio(server: dict[str, Any], method: str, params: dict[str, Any]) -> dict[str, Any]:
    command = [server["command"], *server["args"]]
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
    )
    try:
        assert process.stdin is not None
        assert process.stdout is not None
        _request(
            process,
            "initialize",
            {
                "protocolVersion": _PROTOCOL,
                "capabilities": {},
                "clientInfo": {"name": "gta5-agent", "version": "1"},
            },
            1,
        )
        _write_frame(process.stdin, {"jsonrpc": "2.0", "method": "notifications/initialized"})
        return _request(process, method, params, 2)
    finally:
        if process.stdin is not None:
            try:
                process.stdin.close()
            except Exception:
                pass
        if process.poll() is None:
            process.kill()
        try:
            process.wait(timeout=2)
        except Exception:
            pass


def _transport(name: str, server: dict[str, Any], method: str, params: dict[str, Any]) -> dict[str, Any]:
    agent = _agent()
    override = agent.mcp_transport_override
    if override is not None:
        result = override(name, method, params)
        if not isinstance(result, dict):
            raise RuntimeError("The MCP transport returned an unexpected result.")
        return result
    return _stdio(server, method, params)


def _content_text(result: dict[str, Any]) -> str:
    chunks: list[str] = []
    content = result.get("content")
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict) and item.get("text"):
                chunks.append(str(item["text"]))
            elif isinstance(item, str):
                chunks.append(item)
    if chunks:
        return "\n".join(chunks).strip()
    if result.get("tools"):
        names = []
        for tool in result["tools"]:
            if isinstance(tool, dict) and tool.get("name"):
                names.append(str(tool["name"]))
        return ", ".join(names)
    return json.dumps(result, default=str)[:2000]


def mcp_router(
    action: str,
    server: str = "",
    tool: str = "",
    arguments: Any = None,
) -> dict[str, Any]:
    """List configured servers or call one tool by the name in the config."""
    agent = _agent()
    try:
        kind = (action or "").strip().casefold().replace("-", "_").replace(" ", "_")
        try:
            servers = _load_servers()
        except ValueError as exc:
            return agent._err(str(exc))
        if kind in {"list_servers", "list"}:
            names = sorted(servers)
            if not names:
                return agent._ok(
                    "No MCP servers are configured. Add workspace/mcp_servers.json.",
                    servers=[],
                )
            return agent._ok(
                "Configured MCP servers: " + ", ".join(names) + ".",
                servers=names,
            )
        name = (server or "").strip()
        if name not in servers:
            if not name:
                return agent._err("An MCP server name is required.")
            return agent._err(f"Unknown MCP server: {name}.")
        if kind in {"list_tools", "tools"}:
            result = _transport(name, servers[name], "tools/list", {})
            tools = result.get("tools") if isinstance(result.get("tools"), list) else []
            labels = [
                str(item.get("name"))
                for item in tools
                if isinstance(item, dict) and item.get("name")
            ]
            return agent._ok(
                "Tools on " + name + ": " + (", ".join(labels) if labels else "none") + ".",
                server=name,
                tools=labels,
            )
        if kind not in {"call", "tools_call"}:
            return agent._err("action must be list_servers, list_tools, or call.")
        tool_name = (tool or "").strip()
        if not tool_name or any(token in tool_name for token in (" ", "\n", "&", "|", ";", ">", "<")):
            return agent._err("A tool name is required.")
        payload = _object_arguments(arguments)
        if payload is None:
            return agent._err("arguments must be a JSON object.")
        result = _transport(
            name,
            servers[name],
            "tools/call",
            {"name": tool_name, "arguments": payload},
        )
        text = agent._scrub(_content_text(result))
        if result.get("isError"):
            return agent._err(text or "The MCP tool failed.", server=name, tool=tool_name)
        return agent._ok(
            text or f"Called {tool_name} on {name}.",
            server=name,
            tool=tool_name,
        )
    except AssertionError:
        raise
    except Exception as exc:
        return agent._err(f"mcp_router failed: {agent._scrub(str(exc))[:500]}")
