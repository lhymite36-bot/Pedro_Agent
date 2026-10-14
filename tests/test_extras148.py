import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import extras148  # noqa: E402
import agent_core  # noqa: E402
import task_memory  # noqa: E402


class ExtrasTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.o1, self.o2 = extras148.ROOT, task_memory.PATH
        extras148.ROOT = Path(self.tmp.name)
        task_memory.PATH = Path(self.tmp.name) / "tm.json"
        extras148.shot_override = lambda path: Path(path).write_bytes(b"jpg")

    def tearDown(self):
        extras148.ROOT, task_memory.PATH = self.o1, self.o2
        extras148.shot_override = None
        self.tmp.cleanup()

    def test_proof_saves_shot_and_progress(self):
        r = agent_core.invoke_tool("record_step_proof", {"task": "wingz", "step": "A1 saved", "check": "Saved banner"})
        self.assertTrue(r["ok"], r)
        self.assertTrue(Path(r["screenshot"]).exists())
        self.assertEqual(task_memory.get_task_progress("wingz")["log"][-1]["done"], "A1 saved")

    def test_usage_tracker(self):
        extras148.note_model_call("m1", True)
        extras148.note_model_call("m1", False, "503 UNAVAILABLE high demand")
        msg = agent_core.invoke_tool("gemini_usage", {})["message"]
        self.assertIn("m1: 2 calls, 1 errors (1 busy/quota)", msg)

    def test_change_log(self):
        extras148.note_change("make_document", "C:/x.pdf")
        self.assertIn("C:/x.pdf", agent_core.invoke_tool("show_change_log", {})["message"])

    def test_deadlines_and_report(self):
        import time
        today = time.strftime("%Y-%m-%d")
        self.assertFalse(extras148.add_deadline("bad", "tomorrow")["ok"])
        self.assertTrue(agent_core.invoke_tool("add_deadline", {"title": "ML assignment", "due": today})["ok"])
        task_memory.save_task_progress("wingz", left="GRADED (list only): SQL Modular Exam")
        rep = agent_core.invoke_tool("daily_report", {})["message"]
        self.assertIn("ML assignment", rep)
        self.assertIn("SQL Modular Exam", rep)
        self.assertIn("Gemini today", rep)

    def test_declared(self):
        names = {d["name"] for d in agent_core.TOOL_DECLARATIONS}
        self.assertTrue(set(extras148.TOOLS) <= names)


if __name__ == "__main__":
    unittest.main()


class EveningTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.o1, self.o2 = extras148.ROOT, task_memory.PATH
        extras148.ROOT = Path(self.tmp.name)
        task_memory.PATH = Path(self.tmp.name) / "tm.json"

    def tearDown(self):
        extras148.ROOT, task_memory.PATH = self.o1, self.o2
        extras148.scan_override = None
        self.tmp.cleanup()

    def test_due_logic(self):
        import time as _t
        at7 = _t.strptime("2026-10-15 19:05", "%Y-%m-%d %H:%M")
        at6 = _t.strptime("2026-10-15 18:55", "%Y-%m-%d %H:%M")
        self.assertTrue(extras148._due(at7, "2026-10-14"))
        self.assertFalse(extras148._due(at7, "2026-10-15"))
        self.assertFalse(extras148._due(at6, "2026-10-14"))

    def test_evening_posts_report_in_app(self):
        import chat_store
        posted = []
        calls = []
        extras148.scan_override = lambda: calls.append("scan")
        orig = chat_store.add
        chat_store.add = lambda s, r, t, path=None: posted.append((s, r, t)) or 1
        try:
            extras148.evening_check()
        finally:
            chat_store.add = orig
        self.assertEqual(calls, ["scan"])
        self.assertEqual(posted[0][0], extras148.REPORT_SESSION)
        self.assertIn("Evening report", posted[0][2])


class ApprovalBarTests(unittest.TestCase):
    def test_pending_endpoint_and_bar_present(self):
        src = (ROOT / "chat_app.py").read_text(encoding="utf-8")
        js = (ROOT / "app_static" / "app.js").read_text(encoding="utf-8")
        self.assertIn('url.path == "/api/pending"', src)
        self.assertIn("approve-yes", js)
        self.assertIn("send(word)", js)  # it answers in chat; the normal confirm flow does the rest

    def test_evening_job_started_by_app(self):
        self.assertIn("extras148.start_evening_job()", (ROOT / "chat_app.py").read_text(encoding="utf-8"))
