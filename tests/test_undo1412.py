"""1.4.12: undo restores the previous file, or removes one the agent just created."""

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import extras148  # noqa: E402
import undo_store  # noqa: E402
import agent_core  # noqa: E402


class UndoTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = undo_store.ROOT
        self.old_log = extras148.ROOT
        undo_store.ROOT = Path(self.tmp.name)
        extras148.ROOT = Path(self.tmp.name)
        undo_store.recycle_override = lambda path: Path(path).unlink()

    def tearDown(self):
        undo_store.ROOT = self.old
        extras148.ROOT = self.old_log
        undo_store.recycle_override = None
        self.tmp.cleanup()

    def test_create_then_undo_removes_the_file(self):
        path = Path(self.tmp.name) / "note.txt"
        undo_store.remember(path)
        path.write_text("hello", encoding="utf-8")
        undo_store.seal(path)
        result = undo_store.undo_last_change()
        self.assertTrue(result["ok"], result)
        self.assertFalse(path.exists())

    def test_overwrite_then_undo_restores_the_old_text(self):
        path = Path(self.tmp.name) / "note.txt"
        path.write_text("old", encoding="utf-8")
        undo_store.remember(path)
        path.write_text("new", encoding="utf-8")
        undo_store.seal(path)
        result = undo_store.undo_last_change()
        self.assertTrue(result["ok"], result)
        self.assertEqual(path.read_text(encoding="utf-8"), "old")

    def test_leaves_a_file_that_changed_afterwards(self):
        path = Path(self.tmp.name) / "note.txt"
        undo_store.remember(path)
        path.write_text("hello", encoding="utf-8")
        undo_store.seal(path)
        path.write_text("hello!", encoding="utf-8")
        result = undo_store.undo_last_change()
        self.assertFalse(result["ok"])
        self.assertTrue(path.exists())
        self.assertIn("changed", result["error"])

    def test_secret_files_are_not_remembered(self):
        path = Path(self.tmp.name) / ".env"
        path.write_text("GEMINI_API_KEY=hidden", encoding="utf-8")
        undo_store.remember(path)
        self.assertFalse(undo_store._load())
        result = undo_store.undo_last_change()
        self.assertFalse(result["ok"])
        self.assertIn("hidden", path.read_text(encoding="utf-8"))

    def test_empty_new_folder_can_be_removed(self):
        folder = Path(self.tmp.name) / "scripts"
        undo_store.remember(folder, directory=True)
        folder.mkdir()
        undo_store.seal(folder)
        result = undo_store.undo_last_change()
        self.assertTrue(result["ok"], result)
        self.assertFalse(folder.exists())

    def test_a_folder_with_files_is_left_alone(self):
        folder = Path(self.tmp.name) / "scripts"
        undo_store.remember(folder, directory=True)
        folder.mkdir()
        (folder / "a.txt").write_text("x", encoding="utf-8")
        undo_store.seal(folder)
        result = undo_store.undo_last_change()
        self.assertFalse(result["ok"])
        self.assertTrue((folder / "a.txt").exists())

    def test_refuses_the_home_folder(self):
        home = Path.home().resolve()
        undo_store._save([{"id": "x", "path": str(home), "kind": "created_dir", "blob": "", "sealed_size": 0}])
        result = undo_store.undo_last_change()
        self.assertFalse(result["ok"])
        self.assertTrue(home.exists())

    def test_tool_round_trip(self):
        path = Path(self.tmp.name) / "from-tool.txt"
        saved = agent_core.invoke_tool("write_text_file", {"path": str(path), "content": "one"})
        self.assertTrue(saved["ok"], saved)
        undone = agent_core.invoke_tool("undo_last_change", {})
        self.assertTrue(undone["ok"], undone)
        self.assertFalse(path.exists())

    def test_declared(self):
        names = {item["name"] for item in agent_core.TOOL_DECLARATIONS}
        self.assertIn("undo_last_change", names)

    def test_undo_paths_leaves_the_other_file(self):
        first = Path(self.tmp.name) / "a.txt"
        second = Path(self.tmp.name) / "b.txt"
        undo_store.remember(first)
        first.write_text("A", encoding="utf-8")
        undo_store.seal(first)
        undo_store.remember(second)
        second.write_text("B", encoding="utf-8")
        undo_store.seal(second)
        result = undo_store.undo_paths([str(first)])
        self.assertTrue(result["ok"], result)
        self.assertFalse(first.exists())
        self.assertEqual(second.read_text(encoding="utf-8"), "B")

    def test_undo_paths_matches_files_inside_a_folder(self):
        folder = Path(self.tmp.name) / "proj"
        folder.mkdir()
        script = folder / "main.py"
        undo_store.remember(script)
        script.write_text("print(1)\n", encoding="utf-8")
        undo_store.seal(script)
        result = undo_store.undo_paths([str(folder)])
        self.assertTrue(result["ok"], result)
        self.assertFalse(script.exists())

    def test_chat_list_preview_rename_and_writes(self):
        import chat_store
        db = Path(self.tmp.name) / "h.db"
        chat_store.add("s1", "user", "hi", db)
        mid = chat_store.add("s1", "assistant", "the report is ready", db)
        row = chat_store.sessions(db)[0]
        self.assertEqual(row["title"], "hi")
        self.assertIn("report", row["preview"])
        self.assertEqual(chat_store.rename_session("s1", "Wingz check", db), "Wingz check")
        self.assertEqual(chat_store.sessions(db)[0]["title"], "Wingz check")
        target = str(Path(self.tmp.name) / "a.txt")
        chat_store.remember_writes(mid, [target], db)
        self.assertEqual(chat_store.history("s1", path=db)[-1]["writes"], [target])

    def test_secret_path_is_not_shown_for_undo(self):
        self.assertEqual(agent_core._undo_path({"path": r"C:\secret\.env"}), "")
        self.assertTrue(agent_core._undo_path({"path": r"C:\notes\a.txt"}).endswith("a.txt"))

    def test_interface_has_the_six_controls(self):
        root = Path(__file__).resolve().parents[1] / "app_static"
        html = (root / "index.html").read_text(encoding="utf-8")
        js = (root / "app.js").read_text(encoding="utf-8")
        for token in ("chat-find", "live-step", "hdr-stop"):
            self.assertIn(token, html)
        for token in ("addUndo", "/api/rename", "setLiveStep", "sess-meta"):
            self.assertIn(token, js)


if __name__ == "__main__":
    unittest.main()
