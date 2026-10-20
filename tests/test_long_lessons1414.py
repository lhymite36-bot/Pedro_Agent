"""1.4.14: taught tasks have no step or time limit, and replay runs every step."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["PEDRO_AGENT_NO_FILE_LOG"] = "1"

import rules  # noqa: E402
from tests.test_stage2 import FakeKeys, FakeMouse, types_button  # noqa: E402


class LongLessonTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(os.path.realpath(self.tmp.name))
        self.rules_file = root / "rules.json"
        self.rules_file.write_text("{}", encoding="utf-8")
        self._env = {k: os.environ.get(k) for k in ("RULES_FILE", "STORAGE_DIR", "SKILLS_DIR")}
        os.environ["RULES_FILE"] = str(self.rules_file)
        os.environ["STORAGE_DIR"] = str(root / "storage")
        os.environ["SKILLS_DIR"] = str(root / "skills")
        rules.reset_cache()
        import demo_skills
        import llm

        self.ds, self.llm = demo_skills, llm
        demo_skills.screen_grab = lambda: b"\xff\xd8fakejpeg"
        self.addCleanup(setattr, demo_skills, "screen_grab", None)
        self.addCleanup(setattr, demo_skills, "controller_factory", None)
        self.addCleanup(setattr, demo_skills, "progress_hook", None)
        self.addCleanup(setattr, llm, "override", None)

    def tearDown(self) -> None:
        for key, value in self._env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        rules.reset_cache()
        self.tmp.cleanup()

    def _record(self, name: str, clicks: int):
        rec = self.ds.Recorder(name)
        rec.name = self.ds.skill_name(name)
        rec.screen = (0, 0)
        rec.async_frames = False
        for i in range(clicks):
            rec.on_click(10 + i, 20 + i, types_button("left"), True)
            rec.on_click(10 + i, 20 + i, types_button("left"), False)
        return rec

    def test_no_time_limit_by_default_and_legacy_300_is_unlimited(self) -> None:
        self.assertEqual(self.ds.record_limit_seconds(), 0)
        self.rules_file.write_text(json.dumps({"skills": {"max_record_seconds": 300}}), encoding="utf-8")
        rules.reset_cache()
        self.assertEqual(self.ds.record_limit_seconds(), 0)
        self.rules_file.write_text(json.dumps({"skills": {"max_record_seconds": 900}}), encoding="utf-8")
        rules.reset_cache()
        self.assertEqual(self.ds.record_limit_seconds(), 900)

    def test_250_step_lesson_saves_every_step_and_replays_all(self) -> None:
        seen = {}

        def fake(prompt, images):
            seen["prompt"] = prompt
            raise RuntimeError("offline")   # fallback summary must still list every step

        self.llm.override = fake
        saved = self.ds.save_skill(self._record("Long Report", 250))
        self.assertTrue(saved["ok"], saved)
        self.assertIn("STEPS IN LOG", seen["prompt"])
        md = (Path(os.environ["SKILLS_DIR"]) / "long-report" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("250. ", md)
        log, notes = [], []
        self.ds.controller_factory = lambda: (FakeMouse(log), FakeKeys(log))
        self.ds.progress_hook = notes.append
        result = self.ds.replay_skill("Long Report", speed=10, sleep=lambda s: None)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["done"], 500)
        self.assertEqual(result["total"], 500)
        self.assertTrue(any("action 40 of 500" in n for n in notes), notes)
        self.assertIn("all 500 recorded actions ran", notes[-1])

    def test_several_taught_tasks_each_replay_fully(self) -> None:
        self.llm.override = lambda p, i: "# lesson"
        for name, clicks in (("Task A", 30), ("Task B", 120), ("Task C", 9)):
            self.assertTrue(self.ds.save_skill(self._record(name, clicks))["ok"])
        names = sorted(s["name"] for s in self.ds.list_skills()["skills"])
        self.assertEqual(names, ["task-a", "task-b", "task-c"])
        for name, clicks in (("Task A", 30), ("Task B", 120), ("Task C", 9)):
            log = []
            self.ds.controller_factory = lambda: (FakeMouse(log), FakeKeys(log))
            result = self.ds.replay_skill(name, speed=10, sleep=lambda s: None)
            self.assertEqual(result["done"], clicks * 2, name)

    def test_follow_is_not_capped_at_twelve(self) -> None:
        self.assertGreaterEqual(self.ds.follow_max_steps(), 200)


if __name__ == "__main__":
    unittest.main()
