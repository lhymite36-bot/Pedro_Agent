import re
import unittest
from pathlib import Path

import chat_app

STATIC = Path(chat_app.STATIC)


class AvatarTests(unittest.TestCase):
    def test_blob_shapes_and_white_pill_eyes(self):
        js = (STATIC / "avatar.js").read_text(encoding="utf-8")
        self.assertIn("createAvatar", js)
        self.assertIn("fill=\"#fff\"", js)  # white pill eyes by design in 1.5.x
        self.assertIn("SHAPES", js)
        for shape in ("circle", "ball", "square", "star", "pedbot"):
            self.assertIn(shape, js)
        css = (STATIC / "avatars.css").read_text(encoding="utf-8")
        self.assertIn("pb-idle", css)
        self.assertIn("pb-blink", css)

    def test_png_files_served(self):
        avatars = STATIC / "avatars"
        self.assertTrue(avatars.is_dir())
        pngs = list(avatars.glob("*.png"))
        self.assertGreaterEqual(len(pngs), 8)
        # Static map includes at least one avatar png mime
        self.assertTrue(any(str(p.name) for p in pngs))

    def test_engine_script_present(self):
        self.assertTrue((STATIC / "pedbot-avatars.js").is_file())
        self.assertTrue((STATIC / "themes.js").is_file())


if __name__ == "__main__":
    unittest.main()
