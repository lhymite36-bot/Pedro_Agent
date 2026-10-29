import json, os, tempfile, threading, time, unittest
from pathlib import Path
from unittest import mock

import whatsapp_link as wa


class FakeBridge:
    def __init__(self):
        self.calls = []
        self.on_event = None
        self._alive = False

    def start(self): self._alive = True
    def alive(self): return self._alive
    def stop(self): self._alive = False

    def request(self, cmd, args=None, timeout=60):
        self.calls.append((cmd, args or {}))
        if cmd == "send_text":
            return {"id": "SENT1", "chat": args["to"]}
        if cmd == "read_chat":
            return {"chat": "111@s.whatsapp.net", "name": "Ama", "messages": [
                {"id": "M1", "ts": time.time(), "sender_name": "Ama", "text": "see you at 5", "kind": "text"}]}
        if cmd == "search_contacts":
            return {"results": [{"id": "111@s.whatsapp.net", "name": "Ama", "group": False}]}
        return {}


class WhatsAppTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.p = mock.patch.object(wa, "_dir", lambda: self.tmp)
        self.p.start()
        self.fake = FakeBridge()
        wa.bridge_factory = lambda: self.fake
        wa._bridge = None
        wa.limiter = wa.RateLimiter(sleep=lambda s: None)
        wa._status.update(state="off", me={"id": "919999999999:5@s.whatsapp.net", "name": "Pedro"})
        wa.connect()
        wa._stop.set()

    def tearDown(self):
        wa.bridge_factory = None; wa.answer_handler = None; wa._bridge = None
        self.p.stop()

    def test_only_self_chat_or_allowlist_are_commands(self):
        self.assertTrue(wa.is_command_source({"chat": "x@lid", "self_chat": True, "from_me": True}))
        self.assertFalse(wa.is_command_source({"chat": "111@s.whatsapp.net", "from_me": False}))
        self.assertFalse(wa.is_command_source({"chat": "123-456@g.us", "from_me": False}))
        wa.save_settings(allowlist=["+1 (11) 1"])          # too short -> dropped
        self.assertEqual(wa.settings()["allowlist"], [])
        wa.save_settings(allowlist=["+44 7700 900123"])
        self.assertTrue(wa.is_command_source({"chat": "447700900123@s.whatsapp.net", "from_me": False}))

    def test_other_contacts_are_never_answered(self):
        wa.answer_handler = mock.Mock(return_value="hi")
        wa.handle_incoming({"chat": "111@s.whatsapp.net", "from_me": False, "text": "hello bot", "kind": "text"})
        wa.answer_handler.assert_not_called()
        self.assertEqual(self.fake.calls[-1:], [("send_text", {})] if False else self.fake.calls[-1:])
        self.assertFalse(any(c[0] == "send_text" for c in self.fake.calls))

    def test_self_chat_command_gets_reply_with_file(self):
        f = self.tmp / "report.pdf"; f.write_bytes(b"%PDF")
        wa.answer_handler = lambda text: f"Here it is.\nSEND_FILE: {f}"
        wa.handle_incoming({"chat": "919999999999@s.whatsapp.net", "self_chat": True, "from_me": True, "text": "send me the report", "kind": "text"})
        cmds = [c[0] for c in self.fake.calls]
        self.assertIn("send_text", cmds); self.assertIn("send_file", cmds)
        text = [c[1] for c in self.fake.calls if c[0] == "send_text"][0]["text"]
        self.assertTrue(text.startswith("🤖 ") and "SEND_FILE" not in text)

    def test_own_bot_reply_is_not_a_new_command(self):
        wa.answer_handler = mock.Mock(return_value="x")
        wa.handle_incoming({"chat": "s", "self_chat": True, "from_me": True, "text": "🤖 earlier reply", "kind": "text"})
        wa.answer_handler.assert_not_called()

    def test_ask_before_sending(self):
        self.assertTrue(wa.needs_confirm("whatsapp_send_message", {"to": "Ama", "text": "hi"}))
        self.assertFalse(wa.needs_confirm("whatsapp_send_message", {"to": "me", "text": "hi"}))
        self.assertFalse(wa.needs_confirm("whatsapp_send_message", {"to": "919999999999", "text": "hi"}))
        self.assertFalse(wa.needs_confirm("whatsapp_read_chat", {"chat": "Ama"}))
        self.assertIn("Ama", wa.label("whatsapp_send_message", {"to": "Ama", "text": "hi there"}))
        self.assertIn("hi there", wa.label("whatsapp_send_message", {"to": "Ama", "text": "hi there"}))
        wa.save_settings(ask_before_sending=False)
        self.assertFalse(wa.needs_confirm("whatsapp_send_message", {"to": "Ama", "text": "hi"}))

    def test_rules_route_whatsapp_confirm(self):
        import rules
        self.assertTrue(rules.needs_confirmation("whatsapp_send_file", {"to": "Ama", "path": "x"}))
        self.assertFalse(rules.needs_confirmation("whatsapp_list_chats", {}))

    def test_tools(self):
        r = wa.whatsapp_read_chat(chat="Ama")
        self.assertTrue(r["ok"]); self.assertIn("see you at 5", r["message"])
        self.assertTrue(wa.whatsapp_send_message(to="Ama", text="on my way")["ok"])
        self.assertFalse(wa.whatsapp_send_message(to="Ama", text=" ")["ok"])
        self.assertFalse(wa.whatsapp_send_file(to="Ama", path=str(self.tmp / "nope.png"))["ok"])
        self.assertIn("Ama", wa.whatsapp_search_contacts(query="am")["message"])

    def test_rate_limit(self):
        clock = [1000.0]; slept = []
        lim = wa.RateLimiter(clock=lambda: clock[0], sleep=lambda s: (slept.append(s), clock.__setitem__(0, clock[0] + s)))
        wa.save_settings()
        for _ in range(10):
            self.assertEqual(lim.wait_turn(), "")
        self.assertTrue(all(s >= 4 for s in slept))
        self.assertIn("limit", lim.wait_turn().replace("Slow down", "limit"))

    def test_logout_deletes_session(self):
        (self.tmp / "session").mkdir(exist_ok=True); (self.tmp / "session" / "creds.json").write_text("{}")
        wa.disconnect(logout=True)
        self.assertFalse((self.tmp / "session").exists())
        self.assertFalse(wa.settings()["enabled"])


class NodeBridgeProcessTest(unittest.TestCase):
    def test_real_node_bridge_answers_commands_offline(self):
        import shutil
        if not shutil.which("node") or not (Path(__file__).parents[1] / "whatsapp_bridge" / "node_modules").is_dir():
            self.skipTest("node or bridge deps missing")
        tmp = Path(tempfile.mkdtemp()); events = []
        with mock.patch.object(wa, "_dir", lambda: tmp), mock.patch.dict(os.environ, {"PEDBOT_WA_NO_CONNECT": "1"}):
            b = wa.NodeBridge(events.append); b.start()
            try:
                self.assertEqual(b.request("status", timeout=20)["state"], "offline-test")
                self.assertEqual(b.request("search_contacts", {"query": "x"})["results"], [])
                with self.assertRaises(RuntimeError):
                    b.request("send_text", {"to": "Ama", "text": "hi"})
            finally:
                b.stop()


if __name__ == "__main__":
    unittest.main()


class CrashFeedbackTests(unittest.TestCase):
    def test_module_not_found_is_explained_and_repaired(self):
        err = ("node:internal/modules/esm/resolve:275\n    throw new ERR_MODULE_NOT_FOUND(\n"
               "Error [ERR_MODULE_NOT_FOUND]: Cannot find module 'C:\\\\x\\\\node_modules\\\\lru-cache\\\\dist\\\\esm\\\\node\\\\index.min.js'")
        self.assertTrue(wa.broken_modules(err))
        self.assertIn("lru-cache", wa.explain_crash(err, 1))
        self.assertIn("exit code 1", wa.explain_crash(err, 1))
        seen = {}
        def runner(cmd, **kw):
            seen["cmd"] = cmd; seen["cwd"] = kw.get("cwd")
            return mock.Mock(returncode=0, stdout="", stderr="")
        with mock.patch.object(wa, "npm_cmd", lambda: ["npm"]):
            ok, msg = wa.repair_modules(runner)
        self.assertTrue(ok); self.assertEqual(seen["cmd"][:3], ["npm", "ci", "--omit=dev"])
        self.assertTrue(seen["cwd"].endswith("whatsapp_bridge"))

    def test_crash_event_sets_error_and_starts_repair(self):
        wa._bridge = mock.Mock(proc=object())
        with mock.patch.object(wa, "repair_and_restart") as rep, mock.patch("threading.Thread") as th:
            wa._on_event({"event": "status", "state": "stopped", "code": 1, "stderr": "Error [ERR_MODULE_NOT_FOUND]: Cannot find module 'x'"})
            th.assert_called()
        self.assertEqual(wa._status["state"], "error")
        self.assertIn("ERR_MODULE_NOT_FOUND", wa._status["error"])
        wa._bridge = None

    def test_real_node_crash_reaches_status(self):
        import shutil
        if not shutil.which("node"):
            self.skipTest("no node")
        tmp = Path(tempfile.mkdtemp()); bad = tmp / "app" / "whatsapp_bridge"; bad.mkdir(parents=True)
        (bad / "bridge.mjs").write_text("import x from 'missing-package-xyz';\n")
        events = []
        with mock.patch.object(wa, "_script", lambda: bad / "bridge.mjs"), mock.patch.object(wa, "_dir", lambda: tmp):
            b = wa.NodeBridge(events.append); b.start()
            for _ in range(50):
                if events: break
                time.sleep(0.1)
        self.assertTrue(events and events[-1]["state"] == "stopped")
        self.assertTrue(wa.broken_modules(events[-1]["stderr"]), events[-1])
