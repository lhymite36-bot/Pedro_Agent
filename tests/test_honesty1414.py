"""1.4.14: written tool calls, unproven 'done', loops, and markers on screen."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import grounding  # noqa: E402
import reply_clean  # noqa: E402


class HonestyTests(unittest.TestCase):
    def setUp(self):
        grounding.begin()

    def test_written_tool_call_is_found_and_stripped(self):
        text = "[react:👍] Replaying now! [[replay_skill(inputs='a\\nb', name='lesson', speed=1)]]"
        self.assertEqual(grounding.text_calls(text), ["replay_skill"])
        self.assertNotIn("replay_skill", grounding.strip_text_calls(text))

    def test_done_without_any_tool_is_refused(self):
        out = grounding.ground_reply("do the assignment", "Completed! I advanced through the syllabus.")
        self.assertIn("I have not done that", out)

    def test_done_and_failed_never_together(self):
        grounding.note("save_pdf", {"ok": True, "message": "saved"})
        grounding.note("click_element", {"ok": False, "error": "button not found"})
        out = grounding.ground_reply("x", "I have completed the assignment and saved the PDF.")
        self.assertTrue(out.startswith("Not done yet"), out)
        self.assertNotIn("completed", out)

    def test_plain_answer_passes(self):
        self.assertEqual(grounding.ground_reply("what is DAX?", "DAX is Power BI's formula language."),
                         "DAX is Power BI's formula language.")

    def test_display_clean(self):
        raw = ("[[@pedro]] [@pedro]] ASSIGN @fay: check the folder.\n[chuckles] All good [pause] "
               "[react:✅]] DONE: verified\nPROJECT DONE: finished [[create_routine(name='x')]]")
        out = reply_clean.clean_for_display(raw)
        for bad in ("ASSIGN", "DONE:", "PROJECT DONE", "[chuckles]", "[pause]", "react:", "create_routine"):
            self.assertNotIn(bad, out)
        self.assertTrue(out.startswith("[[@pedro]]"))
        self.assertEqual(out.count("@pedro"), 1)
        self.assertIn("All good", out)

    def test_loop_guard_on_third_same_reply(self):
        earlier = ["[[@ghost]] Replaying the 'lesson' skill now! [[replay_skill(name='lesson')]]",
                   "[[@ghost]] Replaying the 'lesson' skill right now! [[replay_skill(name='lesson')]]"]
        self.assertTrue(reply_clean.is_loop("[[@ghost]] Replaying the 'lesson' skill now!! [[replay_skill(name='lesson')]]", earlier))
        self.assertFalse(reply_clean.is_loop("Here is your Power BI summary.", earlier))
        self.assertFalse(reply_clean.is_loop("same", ["same"]))   # only after two

        class Store:
            def history(self, session, limit=12):
                return [{"role": "assistant", "text": t} for t in earlier]

        out = reply_clean.guard_loop("bot-ghost", "[[@ghost]] Replaying the 'lesson' skill now!", Store())
        self.assertIn("stopped", out)


if __name__ == "__main__":
    unittest.main()
