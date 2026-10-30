"""1.6.7: written lessons resolve in replay_skill, fuzzy recording names, routine status, routine brief + retry."""
import json, os, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class ReplayResolveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        os.environ["SKILLS_DIR"] = self.tmp.name; self.addCleanup(os.environ.pop, "SKILLS_DIR", None)
        import demo_skills; self.ds = demo_skills

    def _rec(self, name):
        d = Path(self.tmp.name) / name; d.mkdir()
        (d / "actions.json").write_text(json.dumps({"events": []}))
        (d / "SKILL.md").write_text("# " + name)

    def test_fuzzy_names(self):
        self._rec("workflow-1")
        for n in ("workflow-1", "Workflow 1", "workflow_1", "WORKFLOW1"):
            self.assertEqual(self.ds.resolve_skill_name(n), "workflow-1", n)

    def test_missing_lists_recordings(self):
        self._rec("lesson")
        import bots
        orig = bots.list_bots, bots.current_bot
        bots.list_bots, bots.current_bot = (lambda: []), (lambda: None)
        self.addCleanup(lambda: (setattr(bots, "list_bots", orig[0]), setattr(bots, "current_bot", orig[1])))
        out = self.ds.missing_skill("workflow-9")
        self.assertFalse(out["ok"]); self.assertIn("lesson", out["error"]); self.assertEqual(out["available"], ["lesson"])

    def test_written_lesson_returns_steps(self):
        import bots
        bot = {"id": "brobot", "name": "brobot", "skills": [{"name": "workflow-1", "replay": "workflow-1", "text": "## Steps\\n1. Open Voice to Short"}]}
        orig = bots.list_bots, bots.current_bot
        bots.list_bots, bots.current_bot = (lambda: [bot]), (lambda: bot)
        self.addCleanup(lambda: (setattr(bots, "list_bots", orig[0]), setattr(bots, "current_bot", orig[1])))
        out = self.ds.replay_skill("Workflow 1")
        self.assertFalse(out["ok"]); self.assertTrue(out.get("written_lesson"))
        self.assertIn("Open Voice to Short", out["steps"])


class RoutineStatusTests(unittest.TestCase):
    def test_no_tool_run_is_not_ok(self):
        import routines
        r = {"id": "x1", "name": "seq", "prompt": "p", "schedule": {"kind": "daily", "time": "11:10", "days": list(range(7))}}
        saved = {}
        orig = (routines.runner, routines.find, routines._put, routines._load, routines._save)
        routines.runner = lambda r: "I have not done that. No tool ran, so nothing was opened, clicked, or sent."
        routines.find = lambda i: dict(r); routines._put = lambda f: saved.update(f)
        routines._load = lambda: {"feed": []}; routines._save = lambda d: None
        try:
            out = routines.run_routine(r)
        finally:
            routines.runner, routines.find, routines._put, routines._load, routines._save = orig
        self.assertFalse(out["ok"]); self.assertEqual(out["status"], "did nothing")


class RoutineRunnerTests(unittest.TestCase):
    def test_brief_and_retry_on_no_tools(self):
        import chat_app, routines
        calls = []
        def fake(state, session, text, emit, speak=None, **kw):
            calls.append(text)
            return chat_app.NO_TOOL_REPLY + ", clicked." if len(calls) == 1 else "Uploaded: https://youtu.be/x"
        orig_st, orig_start, orig_runner = chat_app.stream_turn, routines.start, routines.runner
        chat_app.stream_turn = fake; routines.start = lambda *a, **k: None
        try:
            try:
                chat_app.start_routines(object())
            except Exception:
                pass
            out = routines.runner({"id": "r", "name": "all-4-workflows-sequence", "prompt": "Execute workflow-1..4 then upload",
                                   "target": "bot", "target_id": "brobot"})
        finally:
            chat_app.stream_turn, routines.start, routines.runner = orig_st, orig_start, orig_runner
        self.assertEqual(out, "Uploaded: https://youtu.be/x")
        self.assertIn("Do the work now with your tools", calls[0]); self.assertIn("list_bot_skills", calls[0])
        self.assertIn("Routine retry", calls[1])


if __name__ == "__main__":
    unittest.main()
