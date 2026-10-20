"""1.4.14: 24/7 worker (persisted queue, resume, notifications) and natural progress updates."""

import os
import tempfile
import time
import unittest
from unittest import mock


class NarratorTests(unittest.TestCase):
    def _n(self):
        import progress_notes
        self.t = [0.0]
        self.out = []
        return progress_notes.Narrator("[Routine: x] Make a report of sales and save it", lambda k, s: self.out.append((k, s)),
                                       clock=lambda: self.t[0])

    def test_short_task_is_quiet(self):
        n = self._n()
        n.feed({"event": "tool_end", "name": "ui_read", "ok": True})
        self.assertEqual(n.finish("Here it is."), "")
        self.assertEqual(self.out, [])

    def test_long_task_opening_milestones_blocker_final_without_spam(self):
        n = self._n()
        for i in range(40):                       # 40 commands
            self.t[0] += 2
            n.feed({"event": "tool_end", "name": "ui_click", "ok": True, "detail": f"Clicked Next {i}"})
        n.feed({"event": "tool_end", "name": "write_file", "ok": False, "detail": "disk full"})
        n.feed({"event": "tool_end", "name": "write_file", "ok": True, "detail": "Saved report", "path": "C:/r.pdf"})
        n.finish("Done.")
        kinds = [k for k, _ in self.out]
        self.assertEqual(kinds[0], "opening")
        self.assertIn("Make a report of sales", self.out[0][1])
        self.assertNotIn("[Routine", self.out[0][1])
        self.assertIn("blocker", kinds)
        self.assertEqual(kinds[-1], "final")
        self.assertIn("C:/r.pdf", self.out[-1][1])
        self.assertLessEqual(kinds.count("milestone"), 3)    # ~80 s of work -> a few notes, not 40
        self.assertLess(len(self.out), 8)


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"STORAGE_DIR": self.tmp.name})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_unfinished_task_is_resumed_once_after_restart(self):
        import background
        tid = background.task_started("chat1", "render the city", [])
        done = background.task_started("chat1", "short", [])
        background.task_finished(done)
        self.assertEqual([t["id"] for t in background.unfinished()], [tid])
        ran = []
        got = background.resume_unfinished(lambda t: ran.append(t["text"]))
        time.sleep(0.2)
        self.assertEqual(got, [tid])
        self.assertEqual(ran, ["render the city"])
        self.assertEqual(background.unfinished(), [])        # not resumed again on the next start

    def test_paused_keeps_queue_without_running(self):
        import background
        import safe_mode
        safe_mode._loaded, safe_mode._paused = True, {"paused": True}
        try:
            background.task_started("c", "job", [])
            ran = []
            self.assertEqual(background.resume_unfinished(lambda t: ran.append(t)), [])
            self.assertEqual(ran, [])
            self.assertEqual(len(background.unfinished()), 1)
        finally:
            safe_mode._loaded, safe_mode._paused = False, None

    def test_notifications_and_settings(self):
        import background
        got = []
        background.notifier = lambda title, msg: got.append(msg)
        try:
            background.notify("Ped Bot", "Finished")
            self.assertEqual(got, ["Finished"])
            background.save_settings(notifications=False)
            background.notify("Ped Bot", "quiet")
            self.assertEqual(got, ["Finished"])
            self.assertTrue(background.settings()["keep_running"])
        finally:
            background.notifier = None

    def test_autostart_is_off_by_default_and_uses_hidden_background_flag(self):
        import background
        self.assertFalse(background.autostart_enabled() and os.name != "nt")
        self.assertIn("--background", background._launch_command())
        self.assertNotIn("powershell", background._launch_command().lower())


if __name__ == "__main__":
    unittest.main()
