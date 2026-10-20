"""Avatar conversation mode stays a separate screen on the same chat."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import chat_app

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app_static"


class AvatarModeTests(unittest.TestCase):
    def test_screen_is_separate_from_the_chat_log(self):
        page = (STATIC / "index.html").read_text(encoding="utf-8")
        css = (STATIC / "app.css").read_text(encoding="utf-8")
        js = (STATIC / "avatar_mode.js").read_text(encoding="utf-8")
        app = (STATIC / "app.js").read_text(encoding="utf-8")
        shell = (STATIC / "sw.js").read_text(encoding="utf-8")
        self.assertIn('id="avatar-mode"', page)
        self.assertIn('id="avc-open"', page)
        self.assertIn("/avatar_mode.js", page)
        self.assertIn("avatar-call", css)
        self.assertIn("wantsVoice", js)
        self.assertIn("Interrupt", js)
        self.assertIn("pedro-shell-v28", shell)
        self.assertIn("/avatar_mode.js", shell)
        self.assertIn("avatar_mode.js", chat_app.STATIC_FILES)
        self.assertIn("window.avatarMode && window.avatarMode.wantsVoice()", app)
        self.assertIn("body.speak = true", app)

    def test_speak_setting_is_unchanged_outside_the_mode(self):
        self.assertFalse(chat_app.should_speak("never", True))
        self.assertTrue(chat_app.should_speak("voice", True))
        self.assertFalse(chat_app.should_speak("voice", False))

    def test_unknown_voice_style_is_refused(self):
        previous = os.environ.pop("EDGE_TTS_VOICE", None)
        try:
            self.assertEqual(chat_app.apply_voice_style("not-a-voice"), "")
            self.assertNotIn("EDGE_TTS_VOICE", os.environ)
        finally:
            if previous is not None:
                os.environ["EDGE_TTS_VOICE"] = previous

    def test_a_known_voice_style_is_saved(self):
        previous = os.environ.get("EDGE_TTS_VOICE")
        try:
            with tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / "ui_settings.json"
                path.write_text(json.dumps({"model": "gemini-2.5-flash-lite"}), encoding="utf-8")
                with mock.patch.object(chat_app, "_ui_settings_path", return_value=path):
                    self.assertEqual(chat_app.apply_voice_style("jenny"), "jenny")
                    self.assertEqual(os.environ["EDGE_TTS_VOICE"], "en-US-JennyNeural")
                    saved = json.loads(path.read_text(encoding="utf-8"))
                    self.assertEqual(saved["voice_style"], "jenny")
                    self.assertEqual(saved["model"], "gemini-2.5-flash-lite")
                    os.environ.pop("EDGE_TTS_VOICE", None)
                    chat_app.apply_saved_voice()
                    self.assertEqual(os.environ["EDGE_TTS_VOICE"], "en-US-JennyNeural")
                    self.assertEqual(chat_app.apply_voice_style("../secret"), "")
                    self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["voice_style"], "jenny")
        finally:
            if previous is None:
                os.environ.pop("EDGE_TTS_VOICE", None)
            else:
                os.environ["EDGE_TTS_VOICE"] = previous


if __name__ == "__main__":
    unittest.main()
