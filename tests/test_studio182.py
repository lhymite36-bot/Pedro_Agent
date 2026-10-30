import json, os, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class Studio182(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(); os.environ["STORAGE_DIR"] = self.tmp
        import llm, studio182
        self.llm, self.s = llm, studio182
        self.old = getattr(llm, "override", None)

    def tearDown(self):
        self.llm.override = self.old

    def ai(self, reply):
        self.llm.override = lambda *a, **k: reply

    def test_wa_never_sends(self):
        self.ai(json.dumps({"drafts": ["running 10 late, bringing food 🍕", "b", "c"]}))
        r = self.s.wa_draft("+233 20 123 4567", "late but bringing food")
        self.assertTrue(r["ok"]); self.assertEqual(len(r["drafts"]), 3)
        self.assertTrue(r["links"][0].startswith("https://wa.me/233201234567?text="))
        self.assertIn("Nothing is sent", r["note"])

    def test_ffmpeg_whitelist(self):
        cmd = self.s.build_ffmpeg("a.mp4", "b.mp4", {"start": "0:05", "end": "0:20; rm -rf /", "vertical": True, "speed": 9, "text": "hi';x", "mute": True})
        self.assertIn("-ss", cmd); self.assertNotIn("-to", cmd)
        self.assertTrue(any("scale=1080:1920" in c for c in cmd)); self.assertTrue(any("setpts=PTS/2.000" in c for c in cmd))
        self.assertIn("-an", cmd); self.assertFalse(any("';x" in c for c in cmd))

    def test_price_reader(self):
        self.assertEqual(self.s.read_price('<meta property="product:price:amount" content="1,299.00">'), 1299.0)
        self.assertEqual(self.s.read_price("<span>₹ 2,499</span>"), 2499.0)

    def test_calls_and_tick(self):
        self.ai("Hey Pedro, gym time!")
        self.assertFalse(self.s.calls("add", at="7am")["ok"])
        self.s.calls("add", at="07:30", about="gym")
        import time
        t = time.mktime(time.strptime("2026-10-31 07:30:10", "%Y-%m-%d %H:%M:%S"))
        self.assertIn("call:", " ".join(self.s.tick(t)))
        c = self.s.pending_call()["call"]; self.assertEqual(c["about"], "gym")
        self.assertEqual(self.s.calls()["items"], [])   # one-off removed

    def test_mood_and_shortcuts(self):
        self.ai(json.dumps({"score": 8, "feeling": "proud", "reflection": "Nice."}))
        r = self.s.mood("add", "short hit 2k views"); self.assertEqual(r["items"][-1]["score"], 8)
        self.assertTrue(self.s.shortcuts("add", label="Game", command="open steam")["ok"])
        self.assertFalse(self.s.shortcuts("add", label="x", command="y", at="nine")["ok"])

    def test_app_file_safe(self):
        self.assertIsNone(self.s.app_file("../x.html"))


if __name__ == "__main__":
    unittest.main()
