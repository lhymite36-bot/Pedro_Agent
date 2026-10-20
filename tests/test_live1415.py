"""1.4.15: message while working (side replies + steering) and proactive check-ins."""
import os
import tempfile
import time
import unittest
from unittest import mock

os.environ.setdefault("PEDRO_AGENT_NO_FILE_LOG", "1")
import live_steer  # noqa: E402


class LiveSteer(unittest.TestCase):
    def tearDown(self):
        live_steer.end("s1")
        live_steer.responder_override = None

    def test_kinds(self):
        self.assertEqual(live_steer.kind_of("stop"), "stop")
        self.assertEqual(live_steer.kind_of("Cancel!"), "stop")
        self.assertEqual(live_steer.kind_of("how's it going?"), "status")
        self.assertEqual(live_steer.kind_of("also save it as a PDF"), "steer")
        self.assertEqual(live_steer.kind_of("don't stop, keep the old name"), "steer")

    def test_state_and_inbox(self):
        live_steer.begin("s1", "make 8 files")
        live_steer.note("s1", {"event": "tool_start", "name": "write_text_file"})
        live_steer.note("s1", {"event": "tool_end", "name": "write_text_file", "ok": True})
        st = live_steer.snapshot("s1")
        self.assertEqual(st["task"], "make 8 files")
        self.assertIn("✓ write text file", st["done"])
        live_steer.add("s1", "also add extra.txt")
        self.assertTrue(live_steer.pending("s1"))
        self.assertEqual(live_steer.take("s1"), ["also add extra.txt"])
        self.assertEqual(live_steer.take("s1"), [])

    def test_template_reply_is_instant(self):
        live_steer.begin("s1", "task")
        with mock.patch("agent_core.gemini_api_keys", return_value=[]):
            t = time.monotonic()
            r = live_steer.respond("s1", "status?", "status")
        self.assertLess(time.monotonic() - t, 1.0)
        self.assertIn("Still on it", r)


class SideMessage(unittest.TestCase):
    def test_side_message_saves_steers_and_stops(self):
        import chat_app
        import chat_store
        with tempfile.TemporaryDirectory() as d, mock.patch("agent_config.storage_dir", return_value=__import__("pathlib").Path(d)):
            live_steer.responder_override = lambda text, st: "ok: " + text
            try:
                class S:
                    def __init__(self):
                        import threading
                        self.ev = threading.Event()

                    def cancel_session(self, s):
                        self.ev.set()

                    def session_cancel(self, s):
                        return self.ev
                st = S()
                live_steer.begin("s1", "long task")
                r = chat_app.side_message(st, "s1", "also add extra.txt")
                self.assertTrue(r["ok"])
                self.assertEqual(r["kind"], "steer")
                self.assertEqual(live_steer.take("s1"), ["also add extra.txt"])
                r2 = chat_app.side_message(st, "s1", "stop")
                self.assertEqual(r2["kind"], "stop")
                self.assertTrue(st.ev.is_set())
                rows = [m["text"] for m in chat_store.history("s1")]
                self.assertIn("also add extra.txt", rows)
                self.assertIn("ok: also add extra.txt", rows)
                live_steer.end("s1")
                self.assertFalse(chat_app.side_message(st, "s1", "hi")["ok"])
            finally:
                live_steer.responder_override = None
                live_steer.end("s1")


class Checkins(unittest.TestCase):
    def setUp(self):
        import pathlib
        self.d = tempfile.TemporaryDirectory()
        self.p = mock.patch("agent_config.storage_dir", return_value=pathlib.Path(self.d.name))
        self.p.start()
        import checkins
        self.c = checkins
        self.sent = []
        checkins.poster = lambda kind, msg: self.sent.append((kind, msg))

    def tearDown(self):
        self.c.poster = None
        self.c.now_override = None
        self.p.stop()
        self.d.cleanup()

    def _at(self, hour):
        lt = time.localtime()
        ts = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, hour, 5, 0, 0, 0, -1))
        self.c.now_override = lambda: ts

    def test_morning_once_and_cap_and_quiet(self):
        self._at(9)
        with mock.patch("routines.feed", return_value=[{"routine": "backup", "status": "failed", "text": "disk", "t": 1}]):
            self.c.tick()
            self.c.tick()
        kinds = [k for k, _ in self.sent]
        self.assertEqual(kinds.count("morning"), 1)
        self.assertIn("Good morning", self.sent[0][1])
        self._at(23)
        self.assertFalse(self.c.post("nudge", "x"))           # quiet hours
        self.assertTrue(self.c.post("failed", "y", urgent=True))   # urgent still goes
        self._at(14)
        self.c.save_settings(frequency="low")
        n = sum(1 for i in range(5) if self.c.post("done", f"d{i}"))
        self.assertLessEqual(n, 2)

    def test_toggle_off(self):
        self._at(10)
        self.c.save_settings(enabled=False)
        self.assertFalse(self.c.post("failed", "x", urgent=True))
        self.assertEqual(self.c.tick(), [])

    def test_long_task_report(self):
        self._at(15)
        self.c.task_finished("abc", "make the report", "Report saved.", 300)
        self.c.task_finished("abc", "hi", "hello", 3)
        self.assertEqual([k for k, _ in self.sent], ["done"])


if __name__ == "__main__":
    unittest.main()
