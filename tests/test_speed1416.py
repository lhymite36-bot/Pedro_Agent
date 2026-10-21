import os, tempfile, threading, time, unittest
from pathlib import Path
from unittest import mock

import agent_core
import cloud_fallback
import pc_fast_tools
import terminal_tool


class ListFiles(unittest.TestCase):
    def test_sorted_counted_and_filtered(self):
        with tempfile.TemporaryDirectory() as d:
            for i, n in enumerate(["a.pdf", "b.txt", "c.pdf"]):
                p = Path(d, n); p.write_text("x" * (i + 1)); os.utime(p, (1000 + i, 1000 + i))
            r = pc_fast_tools.list_files(d, sort="newest", limit=2)
            self.assertEqual([x["name"] for x in r["items"]], ["c.pdf", "b.txt"]); self.assertEqual(r["count"], 3)
            self.assertEqual(pc_fast_tools.list_files(d, pattern="*.PDF")["count"], 2)

    def test_pc_status(self):
        r = pc_fast_tools.pc_status(3)
        self.assertTrue(r["ok"]); self.assertTrue(r["drives"])

    def test_plain_dir_becomes_list_files_without_approval(self):
        self.assertEqual(pc_fast_tools.listing_from_terminal('dir "C:\\x" | Sort-Object LastWriteTime -Descending | Select-Object -First 5')["limit"], 5)
        for risky in ("dir C:\\x | Remove-Item", "dir C:\\a; del b", "Get-ChildItem C:\\x > out.txt"):
            self.assertIsNone(pc_fast_tools.listing_from_terminal(risky))
        with tempfile.TemporaryDirectory() as d, mock.patch("confirm_action.is_sensitive", side_effect=lambda n, a: n == "run_terminal_command") as sens:
            r = agent_core.invoke_tool("run_terminal_command", {"command": f"dir {d}"})
        self.assertTrue(r["ok"], r); self.assertIn("folder", r)
        self.assertFalse(any(c.args[0] == "run_terminal_command" for c in sens.call_args_list))

    def test_other_terminal_commands_still_need_approval(self):
        import confirm_action
        self.assertTrue(confirm_action.is_sensitive("run_terminal_command", {"command": "Get-PSDrive C"}))


class Parallel(unittest.TestCase):
    def test_read_only_calls_run_together(self):
        def slow(**kw):
            time.sleep(0.4); return {"ok": True, "t": threading.current_thread().name}
        with mock.patch.dict(agent_core.TOOLS, {"list_files": slow, "pc_status": slow}):
            t = time.monotonic()
            r = agent_core.parallel_results([("list_files", {}), ("pc_status", {}), ("list_files", {})])
            self.assertLess(time.monotonic() - t, 1.0); self.assertEqual(len(r), 3)

    def test_sensitive_or_unknown_tools_stay_sequential(self):
        self.assertEqual(agent_core.parallel_results([("list_files", {}), ("delete_path", {"path": "x"})]), {})
        self.assertEqual(agent_core.parallel_results([("list_files", {})]), {})
        with mock.patch("confirm_action.is_sensitive", return_value=True):
            self.assertEqual(agent_core.parallel_results([("list_files", {}), ("pc_status", {})]), {})


class Planner(unittest.TestCase):
    def test_pc_tasks_use_the_backup_planner_big_jobs_do_not(self):
        with mock.patch.object(cloud_fallback, "providers_for", return_value=[{"id": "groq"}]):
            self.assertTrue(agent_core._fast_planner_turn("How much free space is on C:?"))
            self.assertFalse(agent_core._fast_planner_turn("make a blender scene"))
            self.assertFalse(agent_core._fast_planner_turn("[resume] go on"))
        with mock.patch.object(cloud_fallback, "providers_for", return_value=[]):
            self.assertFalse(agent_core._fast_planner_turn("How much free space is on C:?"))

    def test_history_is_passed_on(self):
        from google.genai import types
        hist = [types.Content(role="user", parts=[types.Part.from_text(text="list Downloads")]),
                types.Content(role="model", parts=[types.Part.from_text(text="a.txt, b.txt")])]
        seen = {}
        def chain(text, **kw):
            seen.update(kw); return "done"
        with mock.patch.object(cloud_fallback, "run_chain", side_effect=chain):
            self.assertEqual(agent_core._plan_with_backup("and the oldest?", hist, types, None, None), "done")
        self.assertEqual(seen["history"][1], {"role": "assistant", "content": "a.txt, b.txt"})
        self.assertEqual(len(hist), 4)

    def test_failure_falls_back_to_gemini(self):
        from google.genai import types
        with mock.patch.object(cloud_fallback, "run_chain", return_value=None):
            self.assertIsNone(agent_core._plan_with_backup("x", [], types, None, None))


class WarmShell(unittest.TestCase):
    def test_only_plain_cmdlets_use_the_warm_console(self):
        with mock.patch.object(terminal_tool.os, "name", "nt"):
            self.assertTrue(terminal_tool.warm_ok("Get-PSDrive C | Select-Object Used,Free"))
            self.assertTrue(terminal_tool.warm_ok("(Get-PSDrive C).Free / 1GB"))
            for no in ("python app.py", "git status", "Read-Host x", "Get-Item a\nRemove-Item b", "winget install x",
                       "Start-Process notepad", "cmd /c dir", "exit 3"):
                self.assertFalse(terminal_tool.warm_ok(no), no)
            self.assertFalse(terminal_tool.warm_ok("Get-PSDrive C", "cmd"))


if __name__ == "__main__":
    unittest.main()
