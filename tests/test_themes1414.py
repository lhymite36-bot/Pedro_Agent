import os, re, unittest, tempfile, importlib
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
class ThemeTests(unittest.TestCase):
    def setUp(self):
        os.environ["STORAGE_DIR"] = tempfile.mkdtemp()
        import themes; self.t = importlib.reload(themes)
    def test_default_aurora_and_clean(self):
        self.assertEqual(self.t.get()["preset"], "aurora")
        c = self.t.clean({"preset": "hack", "custom": {"accent": "red;x", "blur": 999, "alpha": -5, "wallpaper": "zz"}})
        self.assertEqual(c["preset"], "aurora"); self.assertNotEqual(c["custom"]["accent"], "red;x")
    def test_save_roundtrip(self):
        self.t.save({"preset": "crimson"}); self.assertEqual(self.t.get()["preset"], "crimson")
    def test_js_has_all_presets(self):
        js = open(os.path.join(HERE, "app_static", "themes.js"), encoding="utf-8").read()
        for k in ("aurora", "midnight", "crimson", "emerald", "sunset", "ocean", "graphite", "lavender", "goldnoir", "neon"):
            self.assertIn(k + ":", js)
        html = open(os.path.join(HERE, "app_static", "index.html"), encoding="utf-8").read()
        self.assertIn('id="p-themes"', html); self.assertIn("/themes.js", html)
        css = open(os.path.join(HERE, "app_static", "glass.css"), encoding="utf-8").read()
        self.assertIn("@property --w1", css); self.assertIn("transition:--w1", css)


class Utf8StdoutTest(unittest.TestCase):
    def test_main_reconfigures_utf8(self):
        import subprocess, sys
        code = "import io,sys; sys.stdout=io.TextIOWrapper(io.BytesIO(),encoding='cp1252'); exec(open('main.py').read().split('try:\\n    import crash_reports')[0]); print('\\ufeff\\U0001F600'); sys.stderr.write('ok')"
        r = subprocess.run([sys.executable, "-c", code], cwd=HERE, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr); self.assertIn("ok", r.stderr)
if __name__ == "__main__": unittest.main()
