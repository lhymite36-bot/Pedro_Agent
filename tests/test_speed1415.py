"""1.4.15: fast path, failover, Stop within 0.5 s, Pause freeze, Delete all chats with Undo."""
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

os.environ.setdefault("PEDRO_AGENT_NO_FILE_LOG", "1")
import stop_token  # noqa: E402


class SimpleChat(unittest.TestCase):
    def test_greetings_and_questions(self):
        import agent_core as a
        for t in ("hi", "hey", "sup", "hello!", "good morning", "thanks", "how are you?",
                  "what is photosynthesis?", "who was Alan Turing", "explain recursion"):
            self.assertTrue(a.simple_chat(t), t)

    def test_tasks_take_the_full_agent(self):
        import agent_core as a
        for t in ("open notepad", "what time is it", "what is in my downloads folder", "hi, open chrome and search cats",
                  "list files on the desktop", "how do I fix this", "[resume] go on", "run workflow 1",
                  "what's the weather today"):
            self.assertFalse(a.simple_chat(t), t)

    def test_no_backoff_constants(self):
        import agent_core as a
        self.assertLessEqual(a.RESUME_WAIT_SECONDS, 5)
        self.assertEqual(a.ATTEMPT_TIMEOUT_MS, 8000)
        import cloud_fallback
        self.assertLessEqual(cloud_fallback._TIMEOUT, 20)


class StopToken(unittest.TestCase):
    def test_wait_ends_on_stop(self):
        ev = threading.Event()
        threading.Timer(0.1, ev.set).start()
        t = time.monotonic()
        self.assertTrue(stop_token.wait(30, ev))
        self.assertLess(time.monotonic() - t, 0.5)

    def test_run_returns_on_stop(self):
        ev = threading.Event()
        threading.Timer(0.1, ev.set).start()
        t = time.monotonic()
        with self.assertRaises(stop_token.Stopped):
            stop_token.run(lambda: time.sleep(20), ev)
        self.assertLess(time.monotonic() - t, 0.5)

    def test_fire_kills_tracked_process(self):
        ev = threading.Event()
        proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], start_new_session=True)
        stop_token.track(proc, ev)
        t = time.monotonic()
        stop_token.fire(ev)
        proc.wait(5)
        self.assertLess(time.monotonic() - t, 1.0)

    def test_held_keys_released(self):
        class C:
            def __init__(self):
                self.up = []

            def release(self, k):
                self.up.append(k)
        c = C()
        ev = threading.Event()
        stop_token.bind(ev)
        stop_token.hold("key", "shift", c)
        stop_token.fire(ev)
        stop_token.bind(None)
        self.assertEqual(c.up, ["shift"])

    def test_checkpoint_pauses_then_resumes(self):
        import safe_mode
        state = {"p": True}
        orig = safe_mode.paused
        safe_mode.paused = lambda: state["p"]
        try:
            threading.Timer(0.3, lambda: state.update(p=False)).start()
            t = time.monotonic()
            stop_token.checkpoint(threading.Event())
            self.assertGreaterEqual(time.monotonic() - t, 0.25)
            state["p"] = True
            ev = threading.Event()
            threading.Timer(0.1, ev.set).start()
            with self.assertRaises(stop_token.Stopped):
                stop_token.checkpoint(ev)
        finally:
            safe_mode.paused = orig

    def test_tool_stop_returns_fast(self):
        import agent_core as a
        ev = threading.Event()
        a._turn_local.cancel_event = ev
        try:
            threading.Timer(0.1, ev.set).start()
            t = time.monotonic()
            r = a._call_with_timeout("slow", lambda: time.sleep(20), {})
            self.assertTrue(r.get("stopped"))
            self.assertLess(time.monotonic() - t, 0.5)
        finally:
            a._turn_local.cancel_event = None


class DeleteAllChats(unittest.TestCase):
    def test_backup_then_undo_on_a_copy(self):
        import chat_store
        with tempfile.TemporaryDirectory() as d:
            db = Path(d) / "chat_history.db"
            chat_store.add("s1", "user", "hello", path=db)
            chat_store.add("s2", "user", "hey", path=db)
            chat_store.add("bot-x", "user", "bot room", path=db)
            chat_store.rename_session("s1", "First", path=db)
            back = chat_store.backup_db(Path(d) / "backups", path=db)
            self.assertTrue(back.name.startswith("chat_history-") and back.exists())
            for s in ("s1", "s2"):
                chat_store.delete_session(s, path=db)
            chat_store.add("s3", "user", "new after delete", path=db)
            self.assertEqual(chat_store.restore_sessions(back, ["s1", "s2"], path=db), 2)
            con = sqlite3.connect(str(db))
            got = sorted(r[0] for r in con.execute("SELECT DISTINCT session FROM messages"))
            title = con.execute("SELECT title FROM titles WHERE session='s1'").fetchone()
            con.close()
            self.assertEqual(got, ["bot-x", "s1", "s2", "s3"])
            self.assertEqual(title[0], "First")


if __name__ == "__main__":
    unittest.main()
