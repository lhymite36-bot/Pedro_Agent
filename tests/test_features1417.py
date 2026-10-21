import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import agent_core
import cloud_fallback
import emotion
import quiet_brain_shorts
import win_chrome


class StageDirections(unittest.TestCase):
    def test_strips_stage_but_keeps_real_brackets(self):
        self.assertEqual(emotion.strip_stage("[sighs] Pedro, please approve."), "Pedro, please approve.")
        self.assertIn("[1]", emotion.strip_stage("See note [1] and [link](x)."))
        self.assertIn("[link](x)", emotion.strip_stage("See note [1] and [link](x)."))


class ResultCache(unittest.TestCase):
    def setUp(self):
        agent_core.clear_result_cache()

    def test_read_only_result_reused_then_cleared_by_other_tool(self):
        calls = []

        def fake(name, args):
            calls.append(name)
            return {"ok": True, "message": "x"}

        with mock.patch.object(agent_core, "invoke_tool", side_effect=fake):
            agent_core._execute_logged_tool("list_files", {"path": "Downloads"})
            second = agent_core._execute_logged_tool("list_files", {"path": "Downloads"})
            self.assertTrue(second.get("cached"))
            agent_core._execute_logged_tool("run_terminal_command", {"command": "x"})
            agent_core._execute_logged_tool("list_files", {"path": "Downloads"})
        self.assertEqual(calls, ["list_files", "run_terminal_command", "list_files"])

    def test_errors_and_sensitive_tools_never_cached(self):
        with mock.patch.object(agent_core, "invoke_tool", return_value={"ok": False, "error": "e"}) as m:
            agent_core._execute_logged_tool("list_files", {"path": "Nope"})
            agent_core._execute_logged_tool("list_files", {"path": "Nope"})
        self.assertEqual(m.call_count, 2)
        self.assertNotIn("gmail_send_message", agent_core.CACHEABLE_TOOLS)


class ShortsReadiness(unittest.TestCase):
    def test_readiness_reports_missing_without_token_value(self):
        with mock.patch.dict(os.environ, {"BUFFER_ACCESS_TOKEN": ""}):
            r = quiet_brain_shorts.readiness()
        self.assertFalse(r["checks"]["buffer_token"])
        self.assertIn("Buffer token", r["missing"])
        self.assertNotIn("token", {k for k in r if k not in ("checks", "missing", "ready")})

    def test_token_only_reported_as_saved(self):
        with mock.patch.dict(os.environ, {"BUFFER_ACCESS_TOKEN": "secretvalue123"}):
            r = quiet_brain_shorts.readiness()
        self.assertTrue(r["checks"]["buffer_token"])
        self.assertNotIn("secretvalue123", repr(r))


class WarmConnection(unittest.TestCase):
    def test_warm_without_keys_is_harmless(self):
        with mock.patch.object(cloud_fallback, "providers_for", return_value=[]):
            self.assertFalse(cloud_fallback.warm())


class AppId(unittest.TestCase):
    def test_shortcut_registration_skips_off_windows(self):
        if os.name == "nt":
            self.skipTest("Windows")
        self.assertNotEqual(win_chrome.register_shortcut_app_id(), "set")


if __name__ == "__main__":
    unittest.main()
