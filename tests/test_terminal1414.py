import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import confirm_action
import terminal_tool


class TerminalToolTests(unittest.TestCase):
    def test_every_command_needs_its_own_yes_and_label_shows_it(self):
        args = {"command": "git status", "shell": "powershell"}
        self.assertTrue(confirm_action.is_sensitive("run_terminal_command", args))
        self.assertIn("git status", confirm_action.label_for("run_terminal_command", args))

    def test_blocks_encoded_hidden_and_wiping(self):
        for bad in ("powershell -enc SQBFAFgA", "[Convert]::FromBase64String('x')", "Start-Process x -WindowStyle Hidden",
                    "format c:", "Remove-Item -Recurse C:\\Windows"):
            self.assertIsNotNone(terminal_tool.check(bad), bad)
        self.assertIsNone(terminal_tool.check("git status"))

    def test_runs_and_streams_lines(self):
        seen = []
        terminal_tool.listener = seen.append
        try:
            import agent_core
            agent_core._turn_local.listener_bound = True
            agent_core._turn_local.listener = seen.append
            r = terminal_tool.run_terminal_command("echo one; echo two" if False else "echo one && echo two", shell="cmd")
        finally:
            agent_core._turn_local.listener_bound = False
            agent_core._turn_local.listener = None
        self.assertTrue(r["ok"], r)
        self.assertIn("one", r["output"])
        kinds = [e["kind"] for e in seen if e.get("event") == "terminal"]
        self.assertEqual(kinds[0], "start"); self.assertEqual(kinds[-1], "end"); self.assertIn("line", kinds)

    def test_tool_is_declared(self):
        import agent_core
        self.assertIn("run_terminal_command", agent_core.TOOLS)
        self.assertIn("run_terminal_command", agent_core._NO_TIMEOUT_TOOLS)


class PedCliTests(unittest.TestCase):
    def test_ped_streams_reply_and_asks_for_yes(self):
        sent = []

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a): pass

            def do_GET(self):
                body = json.dumps({"bots": [{"id": "night-shift", "name": "Night Shift"}]}).encode()
                self.send_response(200); self.end_headers(); self.wfile.write(body)

            def do_POST(self):
                data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                sent.append(data)
                self.send_response(200); self.send_header("Content-Type", "text/event-stream"); self.end_headers()
                if data["text"] == "yes":
                    evs = [{"event": "terminal", "kind": "start", "command": "git status"},
                           {"event": "terminal", "kind": "line", "line": "clean"},
                           {"event": "terminal", "kind": "end", "code": 0, "seconds": 0.2},
                           {"event": "done", "text": "Done: clean."}]
                else:
                    evs = [{"event": "tool_end", "name": "run_terminal_command", "ok": False, "detail": "Waiting for a yes before run this powershell command: git status."},
                           {"event": "done", "text": "Approve the command?"}]
                for e in evs:
                    self.wfile.write(b"data: " + json.dumps(e).encode() + b"\n\n")

        srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        import importlib, os
        os.environ["PEDBOT_PORT"] = str(srv.server_address[1])
        import ped
        importlib.reload(ped)
        try:
            ped.turn("bot-" + ped.find_bot("night")["id"], "check git", ask=lambda _p: "y")
        finally:
            srv.shutdown(); os.environ.pop("PEDBOT_PORT", None)
        self.assertEqual([s["text"] for s in sent], ["check git", "yes"])
        self.assertEqual(sent[0]["session"], "bot-night-shift")


if __name__ == "__main__":
    unittest.main()

class CmdQuotingTest(unittest.TestCase):
    def test_cmd_keeps_quotes(self):
        import terminal_tool
        from unittest import mock
        with mock.patch.object(terminal_tool.os, "name", "nt"):
            a = terminal_tool.argv_for('dir /b | find /c /v ""', "cmd")
        self.assertIsInstance(a, str); self.assertIn('/s /c "dir /b | find /c /v """', a)

class CardOutsideChatTest(unittest.TestCase):
    def test_open_card_stays_open_when_viewed_without_chat(self):
        import os, tempfile
        os.environ["STORAGE_DIR"] = tempfile.mkdtemp()
        import polls
        confirm_action.reset()
        tok = confirm_action.bind_chat("s1")
        try:
            confirm_action.remember("run_terminal_command", {"command": "ver"}, "run this cmd command: ver")
        finally:
            confirm_action.unbind_chat(tok)
        card = polls.approval_card("run this cmd command: ver", "run_terminal_command")
        self.assertEqual(polls.view(card["id"], confirm_action.pending())["status"], "open")
        confirm_action.reset()
        self.assertEqual(polls.view(card["id"], None)["status"], "expired")

class OutputInReplyTest(unittest.TestCase):
    def test_message_keeps_output(self):
        r = terminal_tool.run_terminal_command("echo hello-ped", "cmd", timeout_seconds=20)
        self.assertIn("hello-ped", r["message"]); self.assertIn("```", r["message"])
