import unittest
import confirm_action as ca, chat_store, agent_core


class Fixes156(unittest.TestCase):
    def setUp(self):
        ca.reset()
        self.ran = []
        tok = ca.bind_chat("bot-shorts-poster")
        self.addCleanup(ca.unbind_chat, tok)
        ca.remember("make_quiet_brain_short", {"dry_run": False}, "post")

    def invoke(self, name, args):
        self.ran.append(name); return {"ok": False, "error": "folder missing"}

    def test_typed_ok_never_runs_a_post(self):
        for word in ("ok", "yes", "Ok"):
            reply = ca.answer_pending(word, self.invoke)
            self.assertIn("tap Approve", reply)
            ca.note_user_text(word)
        self.assertEqual(self.ran, [])
        self.assertFalse(ca.consume_grant("make_quiet_brain_short", {"dry_run": False}))

    def test_card_tap_runs_once_and_leaves_nothing(self):
        rid = ca.pending()["id"]
        ca.resolve(rid, True, self.invoke)
        self.assertEqual(self.ran, ["make_quiet_brain_short"])
        self.assertIsNone(ca.pending())
        ca.note_user_text("ok")
        self.assertFalse(ca.consume_grant("make_quiet_brain_short", {"dry_run": False}))

    def test_no_empty_bot_messages(self):
        self.assertEqual(chat_store.add("t156", "assistant", "   "), 0)

    def test_busy_fallback_message(self):
        self.assertTrue(agent_core._local_failed("Ollama is not running on this PC. Start Ollama, then ask again."))
        self.assertFalse(agent_core._local_failed("Here is your answer."))


if __name__ == "__main__":
    unittest.main()
