import json, tempfile, unittest, os
from pathlib import Path
import app_builder as ab


class AppBuilderLoop(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(); os.environ["PEDBOT_BUILDS"] = self.tmp
        self.calls = []
        def fake(prompt, n):
            self.calls.append(prompt[:40])
            if "Write the SPEC" in prompt:
                return json.dumps({"name": "Todo", "screens": [{"id": "a"}, {"id": "b"}, {"id": "c"}],
                                   "files": [{"path": "index.html"}, {"path": "js/app.js"}]})
            if "has problems" in prompt:
                return json.dumps({"files": [{"path": "js/app.js", "content": "console.log('fixed')"}]})
            return "<html><script src='js/app.js'></script></html>" if "`index.html`" in prompt else "brokn()"
        runs = {"n": 0}
        def shot(project, png):
            runs["n"] += 1; png.write_bytes(b"\x89PNG")
            bad = "brokn" in (project / "js/app.js").read_text()
            return {"ok": True, "errors": ["brokn is not defined (app.js:1)"] if bad else []}
        ab.ask_override, ab.shot_override = fake, shot
        ab.vision_override = lambda p, imgs: json.dumps({"score": 9, "problems": []})

    def tearDown(self):
        ab.ask_override = ab.shot_override = ab.vision_override = None
        os.environ.pop("PEDBOT_BUILDS", None)

    def test_spec_files_fix_review_ship(self):
        out = ab.build("a todo app", "todo")
        p = Path(out["project"])
        self.assertTrue((p / "SPEC.json").is_file())
        self.assertEqual(out["final_errors"], [])
        self.assertIn("fixed", (p / "js/app.js").read_text())
        self.assertTrue(Path(out["website_zip"]).is_file())
        self.assertEqual(out["scores"], [9])

    def test_never_writes_outside(self):
        with self.assertRaises(ValueError):
            ab._safe_write(Path(self.tmp), "../evil.txt", "x")

    def test_install_needs_card(self):
        import confirm_action
        self.assertTrue(confirm_action.is_sensitive("builder_install", {"manager": "pip", "package": "x"}))
        self.assertTrue(confirm_action.is_sensitive("ship_app", {"name": "a", "target": "github"}))


if __name__ == "__main__":
    unittest.main()
