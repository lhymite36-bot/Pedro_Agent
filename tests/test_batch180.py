"""1.8.0 batch 1: avatar command planning, Hey Ped wake word, offline mode, wiring."""
import os, sys, tempfile, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
import batch180


class AvatarPlanTests(unittest.TestCase):
    def test_closest_clip_fallback(self):
        self.assertEqual(batch180.closest_clip("wave"), "Wave")
        self.assertEqual(batch180.closest_clip("boogie"), "Dance")
        self.assertEqual(batch180.closest_clip("hop around"), "Jump")
        self.assertEqual(batch180.closest_clip("moonwalk"), "Walking")
        self.assertIn(batch180.closest_clip("ponder deeply"), batch180.CLIPS)

    def test_local_plan_chains(self):
        p = batch180.local_plan("act sad then cheer up")
        self.assertEqual([s["expression"] for s in p["steps"]], ["sad", "happy"])
        p = batch180.local_plan("walk left and wave")
        self.assertEqual(p["steps"][0]["action"], "Walking"); self.assertEqual(p["steps"][0]["to"], "left")
        self.assertEqual(p["steps"][1]["action"], "Wave")

    def test_clean_plan_maps_unknowns(self):
        p = batch180.clean_plan({"steps": [{"action": "backflip jump", "expression": "thrilled", "to": "moon", "seconds": 99}]})
        s = p["steps"][0]
        self.assertEqual(s["action"], "Jump"); self.assertEqual(s["to"], ""); self.assertEqual(s["seconds"], 8.0)

    def test_plan_without_key_falls_back(self):
        import llm
        old = llm.override; llm.override = lambda *a: (_ for _ in ()).throw(RuntimeError("no key"))
        try:
            self.assertEqual(batch180.avatar_plan("dance")["source"], "local")
        finally:
            llm.override = old


class WakeAndOfflineTests(unittest.TestCase):
    def test_hey_ped(self):
        import wake_word
        os.environ.pop("WAKE_PHRASE", None)
        self.assertEqual(wake_word.split_wake_phrase("hey ped open chrome"), (True, "open chrome"))
        self.assertEqual(wake_word.split_wake_phrase("hey pedro what time"), (True, "what time"))
        self.assertFalse(wake_word.split_wake_phrase("hello there")[0])

    def test_offline_toggle_persists(self):
        with tempfile.TemporaryDirectory() as d:
            old = os.environ.get("STORAGE_DIR"); os.environ["STORAGE_DIR"] = d
            try:
                self.assertTrue(batch180.offline(True)["on"]); self.assertEqual(os.environ.get("LOCAL_LLM"), "1")
                self.assertTrue(batch180.offline()["on"])
                self.assertFalse(batch180.offline(False)["on"]); self.assertNotIn("LOCAL_LLM", os.environ)
            finally:
                os.environ.pop("STORAGE_DIR", None)
                if old is not None: os.environ["STORAGE_DIR"] = old

    def test_assets_wired(self):
        import chat_app
        for f in ("batch180.js", "batch180.css", "avatar3d/index.html", "avatar3d/stage.js", "avatar3d/RobotExpressive.glb", "avatar3d/three.module.min.js"):
            self.assertIn(f, chat_app.STATIC_FILES); self.assertTrue((ROOT / "app_static" / f).is_file(), f)
        src = (ROOT / "chat_app.py").read_text(encoding="utf-8")
        for r in ("/api/avatar/plan", "/api/translate", "/api/tutor", "/api/offline"):
            self.assertIn(r, src)


if __name__ == "__main__":
    unittest.main()
