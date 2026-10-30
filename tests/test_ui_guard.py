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
            self.assertEqual(v, "180", name); self.assertIn(name, chat_app.STATIC_FILES, name)
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


class FreshPcTests(unittest.TestCase):
    def test_service_key_optional_and_builtin_defaults(self):
        import os, importlib, supabase_auth
        old = {k: os.environ.pop(k, None) for k in ("SUPABASE_URL", "SUPABASE_ANON_KEY", "SUPABASE_SERVICE_ROLE_KEY")}
        try:
            os.environ["SUPABASE_URL"] = "https://abc.supabase.co"; os.environ["SUPABASE_ANON_KEY"] = "anon"
            self.assertEqual(supabase_auth.missing_env(), [])
            self.assertFalse(supabase_auth.has_service())
            self.assertIsNone(supabase_auth._rest("GET", "profiles"))
            self.assertEqual(supabase_auth.list_profiles()["code"], "no_service_key")
        finally:
            for k, v in old.items():
                os.environ.pop(k, None)
                if v is not None: os.environ[k] = v

    def test_no_service_key_in_repo_or_builtin(self):
        self.assertIn("supabase_public.py", (ROOT / ".gitignore").read_text())
        gen = (ROOT / "installer" / "make_supabase_public.py").read_text()
        self.assertNotIn("SERVICE_ROLE_KEY =", gen)

    def test_pc_session_persists_and_phone_locks(self):
        js = (ROOT / "app_static" / "auth.js").read_text()
        self.assertIn("localStorage.setItem(key, val)", js)
        java = (ROOT / "android_app/src/com/pedro/agent/MainActivity.java").read_text()
        self.assertIn("grant_type=password", java); self.assertIn("showLock(", java)
        self.assertNotIn('putString("password"', java)


class SettingsPageTests(unittest.TestCase):
    def test_settings_page_assets_wired(self):
        import chat_app
        html = (ROOT / "app_static" / "index.html").read_text(encoding="utf-8")
        for f in ("settings_page.css", "settings_page.js"):
            self.assertIn(f, html); self.assertIn(f, chat_app.STATIC_FILES)
        js = (ROOT / "app_static" / "settings_page.js").read_text(encoding="utf-8")
        for k in ("p-updates", "sp-status", "sp-q", "Connect apps", "Authorize"):
            self.assertIn(k, js)
        self.assertIn('data-pane="p-updates"', (ROOT / "app_static" / "app.js").read_text(encoding="utf-8"))
