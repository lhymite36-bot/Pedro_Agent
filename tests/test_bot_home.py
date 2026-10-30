"""1.6.8: bot row menu state - pin, hide, unread, move/sections, duplicate, share-as-template."""
import json, os, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class BotHomeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        os.environ["BOTS_DIR"] = str(Path(self.tmp.name) / "bots"); self.addCleanup(os.environ.pop, "BOTS_DIR", None)
        import bots, bot_home; self.bots, self.h = bots, bot_home
        self.a = bots.save_bot({"name": "Assistant", "role": "Helps.\napi_key = sk-abcdefghijklmnopqrstuvwxyz123456", "rules": {"api_key": "x", "allow_control": True},
                                "notes": [{"text": "Pedro likes tea"}], "skills": [{"name": "workflow-1", "text": "1. Open app"}]})
        self.b = bots.save_bot({"name": "Soul"})

    def test_toggles_persist(self):
        self.h.apply("pin", {"id": self.a["id"]}); self.h.apply("unread", {"id": self.b["id"]}); self.h.apply("hide", {"id": self.b["id"]})
        d = self.h.load()
        self.assertEqual(d["pinned"], [self.a["id"]]); self.assertIn(self.b["id"], d["unread"]); self.assertIn(self.b["id"], d["hidden"])
        self.h.apply("pin", {"id": self.a["id"], "on": False}); self.h.apply("hide", {"id": self.b["id"], "on": False}); self.h.apply("unread", {"id": self.b["id"], "on": False})
        d = self.h.load(); self.assertEqual((d["pinned"], d["hidden"], d["unread"]), ([], [], []))

    def test_move_creates_section_and_moves_between(self):
        d = self.h.apply("move", {"id": self.a["id"], "new_section": "Work"})
        self.assertEqual(d["sections"][0]["name"], "Work"); self.assertEqual(d["sections"][0]["ids"], [self.a["id"]])
        d = self.h.apply("move", {"id": self.a["id"], "new_section": "work"})   # same name reuses the section
        self.assertEqual(len(d["sections"]), 1)
        d = self.h.apply("add_section", {"name": "Fun"}); fun = d["sections"][1]["id"]
        d = self.h.apply("move", {"id": self.a["id"], "section": fun})
        self.assertEqual(d["sections"][0]["ids"], []); self.assertEqual(d["sections"][1]["ids"], [self.a["id"]])
        d = self.h.apply("move", {"id": self.a["id"], "section": ""})
        self.assertFalse(any(s["ids"] for s in d["sections"]))
        d = self.h.apply("collapse", {"section": fun, "on": True}); self.assertTrue(d["sections"][1]["collapsed"])

    def test_duplicate_copies_settings_and_lessons(self):
        self.h.apply("move", {"id": self.a["id"], "new_section": "Work"})
        c = self.h.duplicate(self.a["id"])
        self.assertEqual(c["name"], "Assistant copy"); self.assertNotEqual(c["id"], self.a["id"])
        self.assertEqual(c["skills"][0]["name"], "workflow-1"); self.assertEqual(c["role"], self.a["role"])
        self.assertIn(c["id"], self.h.load()["sections"][0]["ids"])
        self.assertEqual(len(self.bots.list_bots()), 3)

    def test_template_has_no_secrets_or_memory(self):
        t = self.h.template(self.a["id"]); raw = json.dumps(t)
        self.assertEqual(t["pedbot_template"], 1); self.assertEqual(t["bot"]["name"], "Assistant")
        self.assertNotIn("id", t["bot"]); self.assertNotIn("notes", t["bot"]); self.assertNotIn("tea", raw)
        self.assertNotIn("api_key", t["bot"]["rules"]); self.assertIn("allow_control", t["bot"]["rules"])
        self.assertEqual(t["bot"]["skills"][0]["text"], "1. Open app")

    def test_forget_after_delete(self):
        self.h.apply("pin", {"id": self.b["id"]}); self.h.apply("move", {"id": self.b["id"], "new_section": "X"})
        self.h.apply("forget", {"id": self.b["id"]}); d = self.h.load()
        self.assertEqual(d["pinned"], []); self.assertEqual(d["sections"][0]["ids"], [])


if __name__ == "__main__":
    unittest.main()
