import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import cloud_fallback  # noqa: E402
import agent_core  # noqa: E402


class WingzPromptTests(unittest.TestCase):
    def setUp(self):
        self.text = (ROOT / "agent_core.py").read_text(encoding="utf-8")

    def test_upload_steps(self):
        self.assertIn("FILE upload", self.text)
        self.assertIn("Windows Open dialog", self.text)
        self.assertIn("Never upload to graded tests", self.text)

    def test_no_dashboard_only_claims(self):
        self.assertIn("Progress is below 100%", self.text)
        self.assertIn("dashboard alone", self.text)


class ReasoningPromptTests(unittest.TestCase):
    def test_section_in_system_prompt(self):
        prompt = agent_core.system_prompt()
        self.assertIn("How to work (reasoning and checking)", prompt)
        self.assertIn("Never claim something is done", prompt)
        self.assertIn("resume from the first unfinished step", prompt)


class EvidenceGuardTests(unittest.TestCase):
    def test_claim_without_looking_is_flagged(self):
        self.assertTrue(agent_core.needs_evidence(
            "do my wingz assignments", "FINAL:\n- Adv Excel: all items completed", set()))

    def test_claim_with_screenshot_is_fine(self):
        self.assertFalse(agent_core.needs_evidence(
            "make the pdf task", "FINAL: all items completed", {"take_screenshot"}))

    def test_chat_is_not_flagged(self):
        self.assertFalse(agent_core.needs_evidence("hi", "All good, done!", set()))


class BackupModelTests(unittest.TestCase):
    def tearDown(self):
        cloud_fallback.transport_override = None
        os.environ.pop("GROQ_API_KEY", None)

    def test_not_available_without_key(self):
        os.environ.pop("GROQ_API_KEY", None)
        self.assertFalse(cloud_fallback.available())
        self.assertIn("Settings", cloud_fallback.NO_BACKUP_MESSAGE)
        self.assertNotIn("Ollama", cloud_fallback.NO_BACKUP_MESSAGE)

    def test_tool_loop(self):
        calls = []
        replies = [
            {"choices": [{"message": {"content": "", "tool_calls": [
                {"id": "c1", "function": {"name": "take_screenshot", "arguments": "{}"}}]}}]},
            {"choices": [{"message": {"content": "Looked. Done."}}]},
        ]

        def transport(body):
            calls.append(body)
            return replies.pop(0)

        cloud_fallback.transport_override = transport
        orig = agent_core._execute_logged_tool
        agent_core._execute_logged_tool = lambda name, args: {"ok": True, "name": name, "_screenshot_bytes": b"x"}
        try:
            self.assertEqual(cloud_fallback.run("check screen"), "Looked. Done.")
        finally:
            agent_core._execute_logged_tool = orig
        self.assertEqual(calls[1]["messages"][-1]["role"], "tool")
        self.assertNotIn("_screenshot_bytes", calls[1]["messages"][-1]["content"])


class ResumeTests(unittest.TestCase):
    def test_busy_error_resumes_then_succeeds(self):
        seen = []

        def core(text, history, model, **kw):
            seen.append(text)
            if len(seen) == 1:
                raise RuntimeError(cloud_fallback.NO_BACKUP_MESSAGE)
            return "ok"

        orig_core, orig_wait = agent_core._run_agent_core, agent_core.RESUME_WAIT_SECONDS
        agent_core._run_agent_core, agent_core.RESUME_WAIT_SECONDS = core, 0
        events = []
        try:
            self.assertEqual(agent_core.run_agent("do task", [], "m", on_event=events.append), "ok")
        finally:
            agent_core._run_agent_core, agent_core.RESUME_WAIT_SECONDS = orig_core, orig_wait
        self.assertEqual(seen[1], agent_core.RESUME_TEXT)
        self.assertEqual(events[0]["event"], "resume")

    def test_other_errors_not_resumed(self):
        def core(*a, **k):
            raise RuntimeError("GEMINI_API_KEY is not set")
        orig = agent_core._run_agent_core
        agent_core._run_agent_core = core
        try:
            with self.assertRaises(RuntimeError):
                agent_core.run_agent("x", [], "m")
        finally:
            agent_core._run_agent_core = orig

    def test_voice_not_resumed(self):
        def core(*a, **k):
            raise RuntimeError("503 UNAVAILABLE high demand")
        orig = agent_core._run_agent_core
        agent_core._run_agent_core = core
        try:
            with self.assertRaises(RuntimeError):
                agent_core.run_agent("x", [], "m", voice=True)
        finally:
            agent_core._run_agent_core = orig


if __name__ == "__main__":
    unittest.main()


class TutorBrainstormPromptTests(unittest.TestCase):
    def test_sections(self):
        prompt = agent_core.system_prompt()
        self.assertIn('Screen tutor', prompt)
        self.assertIn('Brainstorm', prompt)
        self.assertIn('Never answer graded tests or exams through the tutor', prompt)



class WingzEvidenceTests(unittest.TestCase):
    def test_screenshot_only_is_not_enough_for_syllabus(self):
        self.assertTrue(agent_core.needs_evidence('do my wingz work', 'FINAL: all items completed', {'take_screenshot'}))
        self.assertFalse(agent_core.needs_evidence('do my wingz work', 'FINAL: all items completed', {'take_screenshot', 'scroll'}))

