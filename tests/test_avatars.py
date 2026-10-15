import re
import unittest
from pathlib import Path

import chat_app

STATIC = Path(chat_app.STATIC)
SHAPES = ["round", "robot", "cat", "ghost", "square", "bunny", "spark"]


class AvatarTests(unittest.TestCase):
    def test_eyes_are_flat_matte_and_huge(self):
        js = (STATIC / "avatar.js").read_text(encoding="utf-8")
        self.assertNotIn("av-hl", js)                 # no eye highlight
        self.assertNotIn("Gradient", js)              # no glossy gradients
        self.assertNotIn('fill="#fff"', js)           # no white shine spots
        rx, ry = map(float, re.search(r'class="av-ball" rx="([\d.]+)" ry="([\d.]+)"', js).groups())
        self.assertGreaterEqual(rx, 10)
        self.assertGreaterEqual(ry, 12)
        self.assertNotIn("base64", js)

    def test_no_twinkle_animation(self):
        css = (STATIC / "app.css").read_text(encoding="utf-8")
        self.assertNotIn("twinkle", css)

    def test_png_files_served(self):
        for s in SHAPES:
            p = STATIC / "avatars" / f"{s}.png"
            self.assertTrue(p.exists(), p)
            self.assertEqual(p.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
            self.assertEqual(chat_app.STATIC_FILES.get(f"avatars/{s}.png"), "image/png")


if __name__ == "__main__":
    unittest.main()
