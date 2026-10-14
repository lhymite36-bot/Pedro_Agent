import os
import tempfile
import unittest
from unittest import mock

import bots
import groups


class GroupTests(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"BOTS_DIR": self.d.name + "/b", "GROUPS_DIR": self.d.name + "/g"})
        self.env.start()
        bots.save_bot({"name": "Writer", "role": "writes", "color": "#ff0000", "avatar": "cat"})
        bots.save_bot({"name": "Editor", "role": "edits"})
        self.calls = []

        def eng(prompt, history, model, **kw):
            who = "Pedro" if "You are Pedro_Agent" in prompt else ("Writer" if "You are Writer" in prompt else "Editor")
            self.calls.append(who)
            return "@writer draft it and @editor check it" if who == "Pedro" else f"{who} done"
        bots.engine = eng; groups.main_engine = eng

    def tearDown(self):
        bots.engine = None; groups.main_engine = None; self.env.stop(); self.d.cleanup()

    def test_create_edit_persist_delete(self):
        g = groups.save_group({"name": "Shorts Team", "purpose": "make shorts", "members": ["writer", "ghost"]})
        self.assertEqual(g["members"], ["writer"]); self.assertEqual(g["coordinator"], "pedro")
        g2 = groups.save_group({**g, "members": ["writer", "editor"], "coordinator": "editor"})
        self.assertEqual(groups.get_group(g["id"])["members"], ["writer", "editor"])
        self.assertEqual(g2["coordinator"], "editor"); self.assertEqual(g2["created"], g["created"])
        self.assertEqual(len(groups.list_groups()), 1)
        g3 = groups.save_group({**g2, "members": ["writer"]})
        self.assertEqual(g3["coordinator"], "pedro")  # coordinator removed with its member
        self.assertTrue(groups.delete_group(g["id"])); self.assertEqual(groups.list_groups(), [])
        with self.assertRaises(ValueError):
            groups.save_group({"name": " "})

    def test_coordinator_hands_out_work_by_mention(self):
        g = groups.save_group({"name": "T", "members": ["writer", "editor"]})
        events, stored = [], []
        said = groups.run_group(g, "make a short", [], events.append, store=lambda s, r, t: stored.append(t))
        self.assertEqual([s for s, _ in said], ["pedro", "writer", "editor"])
        self.assertEqual([e["name"] for e in events if e["event"] == "speaker"], ["Pedro_Agent", "Writer", "Editor"])
        self.assertTrue(stored[1].startswith("[[@writer]] "))
        self.assertEqual(next(e for e in events if e.get("id") == "writer")["avatar"], "cat")

    def test_mentions_go_direct(self):
        g = groups.save_group({"name": "T", "members": ["writer", "editor"]})
        said = groups.run_group(g, "@Editor quick check", [], lambda e: None)
        self.assertEqual([s for s, _ in said], ["editor"])
        said = groups.run_group(g, "@all hi", [], lambda e: None)
        self.assertEqual([s for s, _ in said], ["pedro", "writer", "editor"])
        self.assertEqual(groups.mentions("@nobody", g), [])


class DeleteTests(GroupTests):
    def test_deleting_bot_leaves_groups_with_coordinator_fallback(self):
        g = groups.save_group({"name": "T", "members": ["writer", "editor"], "coordinator": "writer"})
        other = groups.save_group({"name": "U", "members": ["editor"]})
        self.assertTrue(bots.delete_bot("writer"))
        self.assertEqual(groups.remove_bot("writer"), 1)
        g2 = groups.get_group(g["id"])
        self.assertEqual(g2["members"], ["editor"]); self.assertEqual(g2["coordinator"], "pedro")
        self.assertEqual(groups.get_group(other["id"])["members"], ["editor"])

    def test_deleting_group_keeps_bots(self):
        g = groups.save_group({"name": "T", "members": ["writer"]})
        self.assertTrue(groups.delete_group(g["id"]))
        self.assertIsNotNone(bots.get_bot("writer"))

    def test_clear_chats_keeps_bot_and_group_rooms(self):
        import chat_app
        rows = [{"session": "abc"}, {"session": "bot-writer"}, {"session": "group-t"}, {"session": "telegram"}]
        gone = []
        state = mock.Mock(histories={"abc": [1]})
        with mock.patch.object(chat_app.chat_store, "sessions", return_value=rows), \
             mock.patch.object(chat_app.chat_store, "delete_session", side_effect=gone.append):
            self.assertEqual(chat_app.clear_chats(state), 2)
        self.assertEqual(gone, ["abc", "telegram"]); self.assertNotIn("abc", state.histories)


class PictureTests(GroupTests):
    def test_picture_and_preset_persist_and_validate(self):
        pic = "data:image/jpeg;base64,/9j/4AAQSkZJRg=="
        g = groups.save_group({"name": "P", "picture": pic, "color": "#123456", "avatar": "cat"})
        saved = groups.get_group(g["id"])
        self.assertEqual((saved["picture"], saved["color"], saved["avatar"]), (pic, "#123456", "cat"))
        g2 = groups.save_group({**saved, "picture": "", "color": "bad", "avatar": "dragon"})
        self.assertEqual((g2["picture"], g2["color"], g2["avatar"]), ("", "#5b9dff", "round"))
        for bad in ("javascript:alert(1)", "data:image/svg+xml;base64,PHN2Zz4=", "data:image/png;base64," + "A" * 300000):
            with self.assertRaises(ValueError):
                groups.save_group({"name": "Q", "picture": bad})
