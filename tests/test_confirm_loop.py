"""Regression: delete -> ask -> 'yes' -> deleted exactly once -> never asked again (1.4.5)."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import confirm_action
import agent_core
import rules


class ConfirmLoopTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        root = Path(self.tmp.name)
        (root / "rules.json").write_text("{}", encoding="utf-8")
        self.env = mock.patch.dict(os.environ, {"RULES_FILE": str(root / "rules.json"), "STORAGE_DIR": str(root / "s"),
                                                "BOTS_DIR": str(root / "b"), "GROUPS_DIR": str(root / "g")})
        self.env.start(); rules.reset_cache(); confirm_action.reset()
        self.deleted = []
        fake = lambda path, recursive=False: (self.deleted.append(path), agent_core._ok(f"Deleted {path}."))[1]
        self.tools = mock.patch.dict(agent_core.TOOLS, {"delete_path": fake})
        self.tools.start()

    def tearDown(self):
        self.tools.stop(); self.env.stop(); rules.reset_cache(); confirm_action.reset()
        import chat_store
        chat_store.close(); self.tmp.cleanup()

    def _chat(self, session, text, fake_model):
        import chat_app
        state = chat_app.AppState("m"); ev = []
        with mock.patch.object(agent_core, "run_agent", fake_model):
            chat_app.stream_turn(state, session, text, ev.append, speak=False)
        return [e for e in ev if e.get("event") == "done"][-1].get("text", "")

    def test_one_yes_deletes_once_in_main_chat(self):
        asks = []
        def model(text, history, m, **kw):   # the model asks for the delete on the first turn only
            agent_core.begin_task_turn(text)
            r = agent_core.invoke_tool("delete_path", {"path": "C:\\Users\\x\\Desktop\\old.txt"})
            asks.append(r.get("needs_confirmation"))
            return "Should I delete it? Reply yes."
        self._chat("s1", "delete old.txt on my desktop", model)
        self.assertEqual(asks, [True]); self.assertEqual(self.deleted, [])
        reply = self._chat("s1", "yes", lambda *a, **k: self.fail("model must not run for the yes"))
        self.assertEqual(self.deleted, ["C:\\Users\\x\\Desktop\\old.txt"]); self.assertTrue(reply.startswith("Done"))
        self.assertIsNone(confirm_action.pending())
        # the model calling it again (same or re-worded path) neither asks nor deletes twice
        again = agent_core.invoke_tool("delete_path", {"path": "c:/users/x/desktop/old.txt"})
        self.assertTrue(again.get("already_done")); self.assertEqual(len(self.deleted), 1)

    def test_confirm_before_then_delete_needs_only_one_yes(self):
        agent_core.begin_task_turn("delete old.txt")
        r = agent_core.invoke_tool("confirm_before", {"kind": "delete", "description": "delete old.txt"})
        self.assertTrue(r.get("needs_confirmation"))
        agent_core.begin_task_turn("yes")
        r1 = agent_core.invoke_tool("confirm_before", {"kind": "delete", "description": "Deleting the file old.txt now"})
        r2 = agent_core.invoke_tool("delete_path", {"path": "C:\\old.txt"})
        self.assertTrue(r1["ok"]); self.assertTrue(r2["ok"]); self.assertEqual(self.deleted, ["C:\\old.txt"])

    def test_no_cancels_and_clears(self):
        agent_core.begin_task_turn("delete it")
        agent_core.invoke_tool("delete_path", {"path": "C:\\a.txt"})
        self.assertEqual(confirm_action.answer_pending("no", agent_core.invoke_tool), "Cancelled: delete C:\\a.txt.")
        self.assertIsNone(confirm_action.pending()); self.assertEqual(self.deleted, [])

    def test_yes_in_a_bot_chat_is_not_lost_in_the_wrapped_prompt(self):
        import bots
        bots.save_bot({"name": "Helper", "role": "helps"})
        calls = []
        def model(text, history, m, **kw):
            calls.append(text)
            agent_core.begin_task_turn(text)          # sees "[You are the bot ...]\n\n<text>"
            if "remove" in text:
                agent_core.invoke_tool("delete_path", {"path": "C:\\b.txt"})
            return "ok"
        bots.engine = None
        try:
            self._chat("bot-helper", "remove b.txt", model)
            tok = confirm_action.bind_chat("bot-helper")   # approvals are per chat (1.4.14)
            try:
                self.assertIsNotNone(confirm_action.pending())
            finally:
                confirm_action.unbind_chat(tok)
            self._chat("bot-helper", "yes", model)
        finally:
            bots.engine = None
        self.assertEqual(self.deleted, ["C:\\b.txt"]); self.assertEqual(len(calls), 1)

    def test_delete_app_items_ask_once(self):
        import bots, groups, chat_store
        b = bots.save_bot({"name": "Smoke Coder", "role": "x"})
        g = groups.save_group({"name": "Smoke Project", "members": [b["id"]]})
        chat_store.add("chat-1", "user", "plan my trip to goa")
        for kind, name in (("bot", "Smoke Coder"), ("group", "Smoke Project"), ("chat", "trip to goa")):
            agent_core.begin_task_turn(f"delete the {kind}")
            self.assertTrue(agent_core.invoke_tool("delete_app_item", {"kind": kind, "name": name}).get("needs_confirmation"))
            reply = confirm_action.answer_pending("yes", agent_core.invoke_tool)
            self.assertTrue(reply.startswith("Done"), reply)
        self.assertEqual(bots.list_bots(), []); self.assertEqual(groups.list_groups(), [])
        self.assertFalse(any(r["session"] == "chat-1" for r in chat_store.sessions()))
