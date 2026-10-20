"""1.4.14: MCP stdio uses one JSON message per line (servers timed out before)."""

import json
import os
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["PEDRO_AGENT_NO_FILE_LOG"] = "1"

import agent_core  # noqa: E402
import mcp_router  # noqa: E402

FAKE = textwrap.dedent('''
    import json, sys
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        if line.lower().startswith("content-length"):
            print("this server only reads JSON lines", file=sys.stderr)
            continue
        msg = json.loads(line)
        if "id" not in msg:
            continue
        if msg["method"] == "initialize":
            result = {"protocolVersion": "2024-11-05", "capabilities": {}, "serverInfo": {"name": "fake", "version": "1"}}
        elif msg["method"] == "tools/list":
            result = {"tools": [{"name": "open_binary"}, {"name": "analyze_javascript_application"}]}
        else:
            result = {"content": [{"type": "text", "text": "looked at " + json.dumps(msg["params"]["arguments"])}]}
        sys.stdout.write("log line from the server\\n")
        sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": result}) + "\\n")
        sys.stdout.flush()
''')


class McpLineTransportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        server = root / "fake_mcp.py"
        server.write_text(FAKE, encoding="utf-8")
        config = root / "mcp.json"
        config.write_text(json.dumps({"servers": {"notes": {"command": sys.executable, "args": [str(server)]}}}),
                          encoding="utf-8")
        self.old = agent_core.mcp_config_override, agent_core.mcp_transport_override
        agent_core.mcp_config_override = str(config)
        agent_core.mcp_transport_override = None

    def tearDown(self) -> None:
        agent_core.mcp_config_override, agent_core.mcp_transport_override = self.old
        self.tmp.cleanup()

    def test_line_delimited_server_answers(self) -> None:
        listed = mcp_router.mcp_router("list_tools", server="notes")
        self.assertTrue(listed["ok"], listed)
        self.assertIn("open_binary", listed["tools"])
        own = mcp_router.mcp_router("call", server="notes", tool="open_binary",
                                    arguments={"path": "C:\\Users\\P\\Projects\\myapp\\dist\\myapp.exe"})
        self.assertTrue(own["ok"], own)
        self.assertIn("myapp.exe", own["message"])


if __name__ == "__main__":
    unittest.main()
