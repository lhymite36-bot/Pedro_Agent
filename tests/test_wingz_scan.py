import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import agent_core  # noqa: E402
import task_memory  # noqa: E402
import wingz_scan  # noqa: E402

ROWS = [
    ("Button", "\uf43d Topic One \uf282", ""),
    ("ListItem", "\uf26aDone item", ""), ("Text", "\uf26a", ""), ("Hyperlink", "Done item", "/a"),
    ("ListItem", "\uf28aOpen item", ""), ("Hyperlink", "Open item", "/b"),
    ("ListItem", "\uf194Locked item", ""),
    ("Hyperlink", "\uf302 EX1: Session \uf138", "/s"),
    ("Hyperlink", "\uf34a Modular Exam \uf138", "/assignment-test-student/create-test?id=9"),
]


class FakeBrowser:
    def __init__(self):
        self.visited = []

    def goto(self, url):
        self.visited.append(url)

    def title(self):
        return "Course - Edge"

    def first_content_url(self, cid):
        return f"/content?course_id={cid}"

    def expand_topics(self):
        return 1

    def rows(self):
        return ROWS

    def screenshot(self, path):
        pass


class ClassifyTests(unittest.TestCase):
    def test_buckets(self):
        r = wingz_scan.classify(ROWS)
        self.assertEqual([i["title"] for i in r["done"]], ["Done item"])
        self.assertEqual([i["title"] for i in r["unfinished"]], ["Open item"])
        self.assertEqual([i["title"] for i in r["graded"]], ["Modular Exam"])
        self.assertEqual([i["title"] for i in r["not_open_yet"]], ["Locked item"])

    def test_session_links_are_not_items(self):
        r = wingz_scan.classify(ROWS)
        titles = [i["title"] for v in r.values() for i in v]
        self.assertNotIn("EX1: Session", titles)


class ScanToolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.orig = task_memory.PATH
        task_memory.PATH = Path(self.tmp.name) / "tm.json"
        wingz_scan.browser_override = FakeBrowser()

    def tearDown(self):
        wingz_scan.browser_override = None
        task_memory.PATH = self.orig
        self.tmp.cleanup()

    def test_scan_saves_list_and_never_opens_graded(self):
        r = agent_core.invoke_tool("wingz_scan", {"course_ids": [1, 2]})
        self.assertTrue(r["ok"], r)
        self.assertIn("UNGRADED unfinished (lesson - open/read it, nothing to fill): Topic One > Open item", r["message"])
        self.assertIn("GRADED (list only): Modular Exam", r["message"])
        visited = wingz_scan.browser_override.visited
        self.assertFalse(any("test" in v for v in visited))
        self.assertIn("Open item", task_memory.get_task_progress("wingz")["log"][-1]["left"])


if __name__ == "__main__":
    unittest.main()


class WorkFolderTests(unittest.TestCase):
    def test_repack_path_is_never_used(self):
        import tempfile as _t
        with _t.TemporaryDirectory() as d:
            agent_core.WORK_DIR_OVERRIDE = Path(d) / "PedroAgent"
            orig = agent_core._load_saved_game
            agent_core._load_saved_game = lambda: {"path": r"F:\Game [FitGirl Repack]\GTA"}
            try:
                self.assertEqual(agent_core._game_root(), Path(d) / "PedroAgent")
            finally:
                agent_core._load_saved_game = orig
                agent_core.WORK_DIR_OVERRIDE = None
