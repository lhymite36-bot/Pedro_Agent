import threading, unittest
import bg_progress, live_steer, grounding, chat_store


class Fixes153(unittest.TestCase):
    def test_tool_thread_sees_chat(self):
        import agent_core
        seen = {}
        bg_progress.SESSION.set("bot-app-builder")
        src = open(agent_core.__file__, encoding="utf-8").read()
        self.assertIn("_ctx.run(runner)", src)
        import contextvars
        ctx = contextvars.copy_context()
        t = threading.Thread(target=lambda: ctx.run(lambda: seen.setdefault("s", bg_progress.current_session())))
        t.start(); t.join()
        self.assertEqual(seen["s"], "bot-app-builder")

    def test_side_message_kinds(self):
        self.assertEqual(live_steer.kind_of("Thank you."), "thanks")
        self.assertEqual(live_steer.kind_of("done?"), "status")
        self.assertEqual(live_steer.kind_of("tell me whn youre done"), "status")
        self.assertEqual(live_steer.kind_of("make the header blue"), "steer")

    def test_built_claim_without_tool_is_caught(self):
        self.assertTrue(grounding._strong_claim("Your budget tracker is fully built and ready!"))

    def test_loose_react_marker(self):
        self.assertTrue(chat_store.REACT_RE.match("[react:✅]] hi"))


if __name__ == "__main__":
    unittest.main()
