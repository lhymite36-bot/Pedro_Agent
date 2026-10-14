"""Emoji reactions: persist, toggle off, bots react via [[react:]] tags, group leader ✅."""
import os, sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import chat_store  # noqa: E402
import groups  # noqa: E402


class ReactionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db = Path(self.tmp.name) / "c.db"

    def tearDown(self):
        self.tmp.cleanup()

    def test_toggle_persists_and_removes(self):
        uid = chat_store.add("s", "user", "hi", path=self.db)
        self.assertEqual(chat_store.toggle_reaction(uid, "👍", "you", path=self.db), [{"emoji": "👍", "who": ["you"]}])
        rows = chat_store.history("s", path=self.db)
        self.assertEqual(rows[0]["reactions"], [{"emoji": "👍", "who": ["you"]}])
        self.assertEqual(chat_store.toggle_reaction(uid, "👍", "you", path=self.db), [])
        self.assertEqual(chat_store.history("s", path=self.db)[0]["reactions"], [])

    def test_rejects_text_and_unknown_message(self):
        uid = chat_store.add("s", "user", "hi", path=self.db)
        with self.assertRaises(ValueError):
            chat_store.toggle_reaction(uid, "<b>", "you", path=self.db)
        with self.assertRaises(KeyError):
            chat_store.toggle_reaction(uid + 99, "👍", "you", path=self.db)

    def test_bot_reaction_tag_becomes_reaction(self):
        uid = chat_store.add("g", "user", "build it", path=self.db)
        chat_store.add("g", "assistant", "[[@sika]] On it! [[react:👍]]", path=self.db)
        rows = chat_store.history("g", path=self.db)
        self.assertEqual(rows[1]["text"], "[[@sika]] On it!")
        self.assertEqual(rows[0]["id"], uid)
        self.assertEqual(rows[0]["reactions"], [{"emoji": "👍", "who": ["sika"]}])

    def test_delete_session_clears_reactions(self):
        uid = chat_store.add("s", "user", "hi", path=self.db)
        chat_store.toggle_reaction(uid, "🎉", "you", path=self.db)
        chat_store.delete_session("s", path=self.db)
        self.assertEqual(chat_store.reactions_for([uid], path=self.db), {})

    def test_leader_reacts_done_on_project_done(self):
        from unittest import mock
        import bots
        env = mock.patch.dict(os.environ, {"BOTS_DIR": self.tmp.name + "/b", "GROUPS_DIR": self.tmp.name + "/g"})
        env.start()
        try:
            bots.save_bot({"name": "Writer", "role": "writes"})
            g = groups.save_group({"name": "T", "members": ["writer"]})
            script = iter(["ASSIGN @writer: write it", "PROJECT DONE: written"])
            eng = lambda prompt, history, model, **kw: next(script) if "LEADER" in prompt else "DONE: wrote it"
            bots.engine = eng; groups.main_engine = eng
            seen = []
            groups.run_group(g, "@all write a poem", [], lambda e: None, react=lambda s, e, w: seen.append((e, w)))
            self.assertIn(("✅", g["coordinator"]), seen)
        finally:
            bots.engine = None; groups.main_engine = None; env.stop()


if __name__ == "__main__":
    unittest.main()
