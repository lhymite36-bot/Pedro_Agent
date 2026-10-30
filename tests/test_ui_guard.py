"""1.7.0: phone UI safety - every stylesheet is served and versioned, the guard sheet hides the Live panel,
reactions save (the /api/react UnboundLocalError), Settings tab label fits."""
import re, sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))


class UiGuardTests(unittest.TestCase):
    def test_stylesheets_versioned_and_served(self):
        import chat_app
        html = (ROOT / "app_static" / "index.html").read_text(encoding="utf-8")
        links = re.findall(r'<link rel="stylesheet" href="/([a-z_]+\.css)\?v=(\w+)"', html)
        self.assertTrue(links); self.assertIn("ui_guard.css", [l[0] for l in links])
        for name, v in links:
            self.assertEqual(v, "170", name); self.assertIn(name, chat_app.STATIC_FILES, name)
        self.assertNotIn("grokskin16", html)
        self.assertIn("stylesheet failed to load", html)
        self.assertNotIn("Connections &amp; updates", html)

    def test_guard_rules(self):
        css = (ROOT / "app_static" / "ui_guard.css").read_text(encoding="utf-8")
        for rule in ("#livepane:not(.open){display:none!important}", "resize:none", "body.pl .react-btn{display:none", "#settings .tabs"):
            self.assertIn(rule, css)

    def test_react_post_has_no_local_chat_store_import(self):
        src = (ROOT / "chat_app.py").read_text(encoding="utf-8")
        body = src[src.index("def _do_post"):]
        body = body[:body.index("\n        def ", 10)]
        self.assertNotRegex(body, r"\n\s+import chat_store")


if __name__ == "__main__":
    unittest.main()
