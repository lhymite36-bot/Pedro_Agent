"""Replies stay inside what a tool, the screen, or another bot actually said."""

import os
import tempfile
import unittest


class GroundingTests(unittest.TestCase):
    def setUp(self) -> None:
        import grounding

        self.g = grounding
        grounding.begin()

    def test_third_identical_click_is_refused(self) -> None:
        args = {"x": 10, "y": 20}
        self.assertIsNone(self.g.repeat_error("click_element", args))
        self.assertIsNone(self.g.repeat_error("click_element", args))
        blocked = self.g.repeat_error("click_element", args)
        self.assertFalse(blocked["ok"])
        self.assertIn("twice", blocked["error"])
        self.assertIsNone(self.g.repeat_error("click_element", {"x": 11, "y": 20}))
        self.assertIsNone(self.g.repeat_error("take_screenshot", {}))
        self.assertIsNone(self.g.repeat_error("take_screenshot", {}))
        self.assertIsNone(self.g.repeat_error("take_screenshot", {}))

    def test_reply_keeps_a_real_path_and_drops_an_invented_one(self) -> None:
        self.g.note("write_text_file", {
            "ok": True,
            "message": r"Saved C:\notes\real.txt",
            "path": r"C:\notes\real.txt",
        })
        reply = self.g.ground_reply(
            "save the note",
            r"Saved C:\notes\real.txt and also C:\notes\made-up.txt",
        )
        self.assertIn(r"C:\notes\real.txt", reply)
        self.assertNotIn("made-up", reply)
        self.assertIn("[not returned by a tool]", reply)

    def test_a_failed_turn_cannot_claim_success(self) -> None:
        self.g.note("click_element", {"ok": False, "error": "The control was not there."})
        reply = self.g.ground_reply("open it", "I clicked it and saved the file.")
        self.assertIn("not calling this done", reply)
        self.assertIn("The control was not there.", reply)
        quiet = self.g.ground_reply("open it", "I could not click it.")
        self.assertIn("could not click", quiet)

    def test_chat_with_no_tools_is_left_alone(self) -> None:
        self.assertEqual(self.g.ground_reply("hi", "Hello there."), "Hello there.")

    def test_a_launch_claim_with_no_tool_is_refused(self) -> None:
        reply = self.g.ground_reply("open chrome", "I am launching Google Chrome for you now.")
        self.assertIn("have not done that", reply)
        self.assertNotIn("launching", reply)
        self.assertEqual(self.g.claimed_app("I could not open Chrome."), "")
        link = self.g.claimed_link("I am opening it now.", "watch https://youtu.be/abcdefghijk")
        self.assertEqual(link, "https://youtu.be/abcdefghijk")
        self.assertEqual(self.g.claimed_link("Hello there.", "https://youtu.be/abcdefghijk"), "")
        self.assertEqual(self.g.claimed_link("I could not open https://youtu.be/abcdefghijk"), "")
        self.assertEqual(self.g.claimed_app('Ghost replied: "I am launching Google Chrome."'), "")

    def test_a_claimed_known_app_is_opened_once(self) -> None:
        seen: list[str] = []

        def known(name: str) -> str:
            return "google chrome" if "chrome" in name.casefold() else ""

        def launch(app: str) -> dict:
            seen.append(app)
            return {"ok": True, "message": "Opened google chrome."}

        out = self.g.carry_out_launch("I am launching Google Chrome for you now.", known, launch)
        self.assertEqual(seen, ["google chrome"])
        self.assertEqual(out, "Opened google chrome.")
        again = self.g.carry_out_launch("I am launching Google Chrome again.", known, launch)
        self.assertEqual(seen, ["google chrome"])
        self.assertIn("launching", again)
        quoted = self.g.carry_out_launch('Ghost replied: "I am launching Google Chrome."', known, launch)
        self.assertIn("Ghost replied", quoted)

    def test_handoff_carries_the_checked_fact(self) -> None:
        self.g.note("read_page_text", {"ok": True, "message": "The button says Save."})
        brief = self.g.handoff_brief()
        self.assertIn("The button says Save.", brief)
        self.assertIn("Do not replace them", brief)

    def test_bot_prompt_says_to_check_and_quote(self) -> None:
        import bots

        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        previous = os.environ.get("BOTS_DIR")
        os.environ["BOTS_DIR"] = folder.name
        if previous is None:
            self.addCleanup(lambda: os.environ.pop("BOTS_DIR", None))
        else:
            self.addCleanup(lambda: os.environ.__setitem__("BOTS_DIR", previous))
        bot = bots.save_bot({"name": "Ada", "role": "checks the page"})
        prompt = bots._prompt(bot, "what is on screen")
        self.assertIn("have not checked", prompt)
        self.assertIn("quote that bot", prompt)
        self.assertIn("Do not guess", prompt)


if __name__ == "__main__":
    unittest.main()
