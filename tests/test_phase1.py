import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import agent_core  # noqa: E402
import page_text  # noqa: E402
import task_memory  # noqa: E402


class PageTextTests(unittest.TestCase):
    def tearDown(self):
        page_text.reader_override = None

    def test_reads_and_caps(self):
        page_text.reader_override = lambda title: ["Module Syllabus", "[Hyperlink] Assignment 1"] * 50
        r = agent_core.invoke_tool("read_page_text", {"window_title": "Wingz", "max_chars": 100})
        self.assertTrue(r["ok"])
        self.assertTrue(r["truncated"])
        self.assertIn("Module Syllabus", r["text"])

    def test_error_is_reported(self):
        def boom(title):
            raise RuntimeError("no window")
        page_text.reader_override = boom
        self.assertFalse(page_text.read_page_text("x")["ok"])

    def test_declared(self):
        names = {d["name"] for d in agent_core.TOOL_DECLARATIONS}
        self.assertTrue({"read_page_text", "save_task_progress", "get_task_progress"} <= names)


class TaskMemoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.orig = task_memory.PATH
        task_memory.PATH = Path(self.tmp.name) / "tm.json"

    def tearDown(self):
        task_memory.PATH = self.orig
        self.tmp.cleanup()

    def test_save_and_resume(self):
        task_memory.save_task_progress("Wingz", done="Excel A1 saved", left="PowerBI A3")
        log = task_memory.get_task_progress("wingz")["log"]
        self.assertEqual(log[-1]["left"], "PowerBI A3")

    def test_empty(self):
        self.assertEqual(task_memory.get_task_progress("none")["log"], [])


class WingzGuardTests(unittest.TestCase):
    def tearDown(self):
        agent_core.wingz_turn = False

    def test_desktop_apps_blocked_in_wingz(self):
        agent_core.wingz_turn = True
        r = agent_core.invoke_tool("launch_application", {"name": "Power BI"})
        self.assertFalse(r["ok"])
        self.assertIn("web portal", r["error"])

    def test_page_text_counts_as_evidence(self):
        agent_core.wingz_turn = True
        self.assertFalse(agent_core.needs_evidence("continue", "FINAL: all completed", {"read_page_text"}))

    def test_could_not_verify_text(self):
        msg = agent_core.could_not_verify("wingz", {"take_screenshot"})
        self.assertTrue(msg.startswith("Could not verify"))
        self.assertIn("never scrolled", msg)


if __name__ == "__main__":
    unittest.main()
