"""Judge, screen map, rewind, quiet study, private answers, traps, and a hand correction."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path


class BotMindTests(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.previous_mind = os.environ.get("BOT_MIND_DIR")
        os.environ["BOT_MIND_DIR"] = self.folder.name
        import bot_mind

        self.mind = bot_mind
        self.mind.ask_hook = None
        self.mind.screen_text_hook = None
        self.mind.cursor_hook = None
        self.mind._trap_open = False
        self.mind._trap_waiting = False
        self.mind.note_activity()

    def tearDown(self) -> None:
        self.mind.ask_hook = None
        self.mind.screen_text_hook = None
        self.mind.cursor_hook = None
        self.mind._trap_open = False
        self.mind._trap_waiting = False
        if self.previous_mind is None:
            os.environ.pop("BOT_MIND_DIR", None)
        else:
            os.environ["BOT_MIND_DIR"] = self.previous_mind

    def test_traps_spare_a_practice_page(self) -> None:
        self.assertEqual(self.mind.trap_reason("Module 2 practice\nSubmit"), "")
        self.assertEqual(self.mind.trap_reason("practice quiz\nSave"), "")
        self.assertIn("timer", self.mind.trap_reason("Time remaining 00:10"))
        self.assertIn("cannot be undone", self.mind.trap_reason("This submit cannot be undone"))
        self.assertIn("graded", self.mind.trap_reason("This is a graded exam"))

    def test_the_plan_on_the_screen_wins(self) -> None:
        screen = "the save button is here"
        self.assertEqual(self.mind.choose_plan("Cancel button", "Save button", screen), "second")
        self.assertEqual(self.mind.choose_plan("Save button", "Cancel button", screen), "first")

    def test_judge_can_say_no_and_a_saved_place_is_reused(self) -> None:
        import desktop_share

        self.mind.screen_text_hook = lambda: "practice page with a save button"
        self.mind.ask_hook = lambda kind, prompt: '{"plan_b": "", "judge": "no", "reason": "wrong button"}'
        token = desktop_share.bind("bot-ghost")
        try:
            refused = self.mind.before_click(10, 10)
            self.assertIsNotNone(refused)
            self.assertFalse(refused["ok"])
            self.assertIn("judge said no", refused["error"])
            self.mind.remember_place("Save", grid_x=40, grid_y=50, pixel=(80, 90), screen="practice page")
            found = self.mind.lookup("Save")
            self.assertEqual(found["name"], "Save on the practice page")
            self.assertEqual(found["grid_x"], 40)
            target = self.mind.bind_target("Save", trusted=True)
            try:
                allowed = self.mind.before_click(1, 1)
            finally:
                self.mind.unbind_target(target)
            self.assertTrue(allowed["ok"])
            self.assertEqual(allowed["pixel_x"], 80)
            self.assertIn("saved place", allowed["say"])
        finally:
            desktop_share.unbind(token)

    def test_the_other_plan_is_dropped(self) -> None:
        import desktop_share

        self.mind.screen_text_hook = lambda: "the save button is here"
        self.mind.ask_hook = lambda kind, prompt: '{"plan_b": "Save button", "judge": "yes", "reason": "save is visible"}'
        desk = desktop_share.bind("bot-ghost")
        target = self.mind.bind_target("Cancel button", trusted=False)
        try:
            result = self.mind.before_click(3, 4)
        finally:
            self.mind.unbind_target(target)
            desktop_share.unbind(desk)
        self.assertFalse(result["ok"])
        self.assertIn("other plan", result["error"])
        self.assertIn("Save button", result["say"])
        self.assertIn("Cancel button", result["say"])

    def test_a_shove_saves_the_new_spot(self) -> None:
        kept = self.mind.notice_hand(10, 10, 400, 10, "Save")
        self.assertIsNotNone(kept)
        place = self.mind.lookup("Save")
        self.assertEqual(place["source"], "hand")
        self.assertEqual(place["pixel_x"], 400)
        self.assertIsNone(self.mind.notice_hand(10, 10, 12, 11, "Save"))

    def test_rewind_finds_the_last_matching_screen(self) -> None:
        frames = [
            {"words": self.mind.words("capital question save button"), "note": "typed the answer"},
            {"words": self.mind.words("unrelated mailbox settings"), "note": "wrong page"},
        ]
        back = self.mind.matching_frame(frames, "capital question save button")
        self.assertEqual(back["note"], "typed the answer")
        self.assertIn("Rewind", self.mind.rewind_note(back))
        self.assertIsNone(self.mind.matching_frame(frames, ""))

    def test_the_answer_is_saved_before_it_can_be_typed(self) -> None:
        saved = self.mind.keep_draft("What is the capital of France?", "Paris", "")
        self.assertTrue(saved["ok"], saved)
        body = Path(saved["path"]).read_text(encoding="utf-8")
        self.assertIn("Question:", body)
        self.assertIn("capital of France", body)
        self.assertIn("Answer:\nParis", body)
        secret = self.mind.keep_draft("password prompt", "password: hunter2", "")
        self.assertFalse(secret["ok"])

    def test_quiet_study_writes_a_plan_and_does_not_run_while_busy(self) -> None:
        self.mind.note_mistake("ada", "Next was not on the syllabus page")
        self.assertIsNone(self.mind.study_if_idle(now=self.mind._activity, busy=False))
        self.assertIsNone(self.mind.study_if_idle(now=self.mind._activity + 100, busy=True))
        self.mind.ask_hook = lambda kind, prompt: "Look lower on the syllabus for Next" if kind == "study" else ""
        studied = self.mind.study_if_idle(now=self.mind._activity + 100, busy=False)
        self.assertEqual(studied["plan"], "Look lower on the syllabus for Next")
        self.assertEqual(self.mind.latest_plan("ada"), studied["plan"])
        self.assertIsNone(self.mind.study_if_idle(now=self.mind._activity + 200, busy=False))

    def test_yes_lifts_the_trap(self) -> None:
        import desktop_share

        self.mind.screen_text_hook = lambda: "Time remaining 01:00"
        self.mind.ask_hook = lambda kind, prompt: '{"plan_b": "", "judge": "yes", "reason": "ok"}'
        desk = desktop_share.bind("bot-ghost")
        try:
            stopped = self.mind.before_click(5, 5)
            self.assertFalse(stopped["ok"])
            self.assertIn("Reply yes", stopped["error"])
            self.mind.hear("yes")
            allowed = self.mind.before_click(5, 5)
            self.assertTrue(allowed["ok"])
        finally:
            desktop_share.unbind(desk)

    def test_follow_rewinds_instead_of_repeating_the_click(self) -> None:
        import demo_skills
        import llm

        root = Path(self.folder.name) / "skills" / "rewind-lesson"
        root.mkdir(parents=True)
        (root / "SKILL.md").write_text("# Rewind\n## Steps\n1. Click Go\n", encoding="utf-8")
        previous_skills = os.environ.get("SKILLS_DIR")
        os.environ["SKILLS_DIR"] = str(Path(self.folder.name) / "skills")
        calls = {"n": 0}

        def fake(prompt, images):
            calls["n"] += 1
            self.assertTrue(images)
            if calls["n"] <= 3:
                return '{"action":"click","x":3,"y":4,"reason":"go"}'
            if calls["n"] == 4:
                self.assertIn("Rewind", prompt)
                return '{"action":"click","x":8,"y":9,"reason":"the save button"}'
            return '{"action":"done","reason":"saved"}'

        previous_llm = llm.override
        previous_grab = demo_skills.screen_grab
        previous_factory = demo_skills.controller_factory
        llm.override = fake
        demo_skills.screen_grab = lambda: b"frame"
        log = []

        class Mouse:
            def __init__(self) -> None:
                self.position = (0, 0)

            def press(self, button) -> None:
                log.append(("press", self.position))

            def release(self, button) -> None:
                log.append(("release", self.position))

            def scroll(self, dx, dy) -> None:
                log.append(("scroll", dy))

        class Keys:
            def press(self, key) -> None:
                log.append(("kdown", key))

            def release(self, key) -> None:
                log.append(("kup", key))

        demo_skills.controller_factory = lambda: (Mouse(), Keys())
        self.mind.screen_text_hook = lambda: "capital question save button"
        try:
            out = demo_skills.follow_skill("rewind-lesson", sleep=lambda _seconds: None, limit=8)
        finally:
            llm.override = previous_llm
            demo_skills.screen_grab = previous_grab
            demo_skills.controller_factory = previous_factory
            if previous_skills is None:
                os.environ.pop("SKILLS_DIR", None)
            else:
                os.environ["SKILLS_DIR"] = previous_skills
        self.assertTrue(out["ok"], out)
        presses = [item[1] for item in log if item[0] == "press"]
        self.assertEqual(presses, [(3, 4), (3, 4), (8, 9)])


if __name__ == "__main__":
    unittest.main()
