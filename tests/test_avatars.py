import unittest
from pathlib import Path

import chat_app

STATIC = Path(chat_app.STATIC)
SHAPES = ["circle", "ball", "square", "pill", "triangle", "hexagon", "cloud", "drop", "clover", "star", "heart"]


class AvatarTests(unittest.TestCase):
    """1.4.14 flat blob avatars (pb-* CSS states)."""

    def test_flat_blob_set(self):
        js = (STATIC / "avatar.js").read_text(encoding="utf-8")
        css = (STATIC / "avatars.css").read_text(encoding="utf-8")
        self.assertNotIn("Gradient", js)
        self.assertNotIn("base64", js)
        for s in SHAPES:
            self.assertIn(f"{s}:", js)
        for cls in ("pb-idle", "pb-thinking", "pb-roll", "pb-spin", "pb-happy", "pb-sleepy"):
            self.assertIn("." + cls, css)
            self.assertIn(cls, js)
        self.assertEqual(chat_app.STATIC_FILES.get("avatars.css"), "text/css; charset=utf-8")

    def test_no_twinkle_animation(self):
        css = (STATIC / "app.css").read_text(encoding="utf-8")
        self.assertNotIn("twinkle", css)

    def test_bots_store_shapes_and_old_bots_get_a_default(self):
        import bots
        self.assertEqual(list(bots.AVATARS), SHAPES)
        self.assertEqual(len(bots.PALETTE), 10)
        self.assertEqual(bots.avatar_shape("round"), "circle")
        self.assertEqual(bots.avatar_shape("cat"), "ball")
        self.assertEqual(bots.avatar_shape("hexagon"), "hexagon")
        self.assertEqual(bots.avatar_shape(None), "circle")

    def test_new_bot_screen_and_store_are_served(self):
        html = (STATIC / "index.html").read_text(encoding="utf-8")
        js = (STATIC / "newbot_ui.js").read_text(encoding="utf-8")
        self.assertIn("/newbot_ui.js", html)
        self.assertIn('id="storebtn"', html)
        for word in ("Get started", "Suggestions", "Night Shift", "Inbox Triage", "Shorts Poster", "Featured", "st-chip", "Add"):
            self.assertIn(word, js)
        self.assertEqual(chat_app.STATIC_FILES.get("newbot_ui.js"), "application/javascript; charset=utf-8")


if __name__ == "__main__":
    unittest.main()


class Avatar3dTests(unittest.TestCase):
    def test_3d_engine_is_loaded_first_and_mapped(self):
        html = (STATIC / "index.html").read_text(encoding="utf-8")
        self.assertLess(html.index("/pedbot-avatars.js"), html.index("/avatar.js"))
        eng = (STATIC / "pedbot-avatars.js").read_text(encoding="utf-8")
        for s in ("circle", "square", "hexagon", "star", "heart"):
            self.assertIn(f" {s}:{{", eng)
        self.assertIn("setColor", eng)
        self.assertIn("isConnected", eng)              # removed avatars stop animating
        js = (STATIC / "avatar.js").read_text(encoding="utf-8")
        for a, b in (("thinking", "thinking"), ("working", "working"), ("done", "done"), ("sleeping", "sleepy"), ("idle", "idle")):
            self.assertIn(f"{a}: '{b}'", js)
        self.assertEqual(chat_app.STATIC_FILES.get("pedbot-avatars.js"), "application/javascript; charset=utf-8")
