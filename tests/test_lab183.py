import json, os, sys, tempfile, time, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class Lab183(unittest.TestCase):
    def setUp(self):
        os.environ["STORAGE_DIR"] = tempfile.mkdtemp()
        import llm, lab183
        self.llm, self.lab = llm, lab183
        self.old = llm.override

    def tearDown(self):
        self.llm.override = self.old

    def test_twin_maps_unknown_action(self):
        self.llm.override = lambda *a, **k: json.dumps({"say": "hey!", "action": "moonwalk dance", "expression": "giddy"})
        r = self.lab.twin("hi")
        self.assertTrue(r["ok"]); self.assertEqual(r["say"], "hey!")
        self.assertIn(r["action"], __import__("batch180").CLIPS); self.assertEqual(r["expression"], "neutral")

    def test_swarm_job(self):
        self.llm.override = lambda p, i=None: json.dumps({"answer": "7pm", "agree": ["a"], "disagree": [], "next_steps": [], "confidence": "medium"}) if "judge" in p else "- note"
        j = self.lab.swarm("when to post?")["job"]
        for _ in range(50):
            if self.lab.job(j)["status"] != "working": break
            time.sleep(0.05)
        r = self.lab.job(j)
        self.assertEqual(r["status"], "done"); self.assertEqual(len(r["result"]["agents"]), 4); self.assertEqual(r["result"]["answer"], "7pm")

    def test_autopilot_queue_feeds_routine_and_stays_2d(self):
        self.llm.override = lambda *a, **k: json.dumps({"ideas": [{"title": "Why you reply 'ok' to everything", "hook": "h", "script": "s", "scenes": []}]})
        import quiet_brain_shorts as qb
        qb.buffer_posts = lambda st: []
        r = self.lab.autopilot_plan(1)
        self.assertTrue(r["ok"]); self.assertFalse(r["plan"][0]["isAiGenerated"]); self.assertEqual(r["plan"][0]["style"], "2D")
        self.assertTrue(self.lab.autopilot_queue(0)["ok"])
        item, src = qb.pick_idea([])
        self.assertEqual(src, "autopilot"); self.assertIn("reply 'ok'", item["title"])
        self.assertIsNone(self.lab.autopilot_take([]))

    def test_voice_needs_consent_first(self):
        import base64
        a = base64.b64encode(b"x" * 5000).decode()
        self.assertFalse(self.lab.voice_clone("record", a, "sample")["ok"])
        self.assertTrue(self.lab.voice_clone("record", a, "consent")["consent"])
        self.assertEqual(self.lab.voice_clone("record", a, "sample")["samples"], 1)
        self.assertFalse(self.lab.voice_clone("delete")["consent"])

    def test_os_snapshot_has_no_tokens(self):
        r = self.lab.osinfo()
        self.assertTrue(r["ok"])
        def walk(d):
            for k, v in (d.items() if isinstance(d, dict) else []):
                if "token" in k.lower(): self.assertIsInstance(v, bool, k)
                walk(v)
        walk(r)


if __name__ == "__main__":
    unittest.main()
