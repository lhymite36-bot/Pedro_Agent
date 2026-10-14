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
