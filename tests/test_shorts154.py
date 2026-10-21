import os, tempfile, unittest, pathlib
from unittest import mock
import quiet_brain_shorts as q, confirm_action


class Shorts154(unittest.TestCase):
    def test_token_reloads_from_env_file(self):
        with tempfile.TemporaryDirectory() as d, mock.patch("agent_config.APP_DIR", pathlib.Path(d)), \
                mock.patch.dict(os.environ, {"BUFFER_ACCESS_TOKEN": ""}):
            pathlib.Path(d, ".env").write_text("X=1\nBUFFER_ACCESS_TOKEN=abc123\n", encoding="utf-8")
            self.assertEqual(q._token(), "abc123")
            self.assertEqual(os.environ["BUFFER_ACCESS_TOKEN"], "abc123")

    def test_status_names_the_right_switch(self):
        with mock.patch.object(q, "check_token", return_value={"saved": True, "valid": True, "message": "ok."}), \
                mock.patch.object(q, "buffer_posts", return_value=[]), \
                mock.patch.object(q, "settings", return_value={"enabled": False, "ready": True, "missing": []}):
            s = q.shorts_status()
        self.assertTrue(s["token_valid"]); self.assertIn("not the Routines list", s["message"])

    def test_real_run_needs_a_yes_dry_run_does_not(self):
        self.assertTrue(confirm_action.is_sensitive("make_quiet_brain_short", {"dry_run": False}))
        self.assertFalse(confirm_action.is_sensitive("make_quiet_brain_short", {"dry_run": True}))
        self.assertFalse(confirm_action.is_sensitive("make_quiet_brain_short", {}))

    def test_role_avoids_old_routines(self):
        self.assertIn("workflow-1..4", q.BOT_ROLE)
        self.assertIn("make_quiet_brain_short", q.BOT_TOOLS)


if __name__ == "__main__":
    unittest.main()
