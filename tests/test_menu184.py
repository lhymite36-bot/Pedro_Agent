import unittest
from pathlib import Path
S = Path(__file__).resolve().parents[1] / "app_static"


class Menu184(unittest.TestCase):
    def test_injects_into_real_menus(self):
        js = (S / "menu184.js").read_text(encoding="utf-8")
        for needle in ("pd-menu", "bottomnav", "acct-updates", "'Help'", "MutationObserver", "3D avatar", "Live translate", "Screen tutor", "Studio", "Lab", "Chat face (2D)"):
            self.assertIn(needle, js)
        self.assertIn("/menu184.js", (S / "index.html").read_text(encoding="utf-8"))
        import chat_app
        self.assertIn("menu184.js", chat_app.STATIC_FILES)
