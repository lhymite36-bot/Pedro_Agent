import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import chat_app


class FirstRunSetupTests(unittest.TestCase):
    def test_saves_keys_to_env_file(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {"GEMINI_API_KEY": ""}), \
             mock.patch.object(chat_app, "_env_path", return_value=Path(d) / ".env"):
            (Path(d) / ".env").write_text("GEMINI_API_KEY=\nOTHER=1\n")
            self.assertTrue(chat_app.setup_status()["needs_setup"])
            self.assertFalse(chat_app.save_setup({})["ok"])
            self.assertFalse(chat_app.save_setup({"gemini_api_key": "bad key\nX=1"})["ok"])
            r = chat_app.save_setup({"gemini_api_key": "AIzaTEST123", "telegram_chat_id": "42"})
            self.assertTrue(r["ok"]); self.assertFalse(r["needs_setup"])
            text = (Path(d) / ".env").read_text()
            self.assertIn("GEMINI_API_KEY=AIzaTEST123", text); self.assertIn("OTHER=1", text); self.assertIn("TELEGRAM_CHAT_ID=42", text)
