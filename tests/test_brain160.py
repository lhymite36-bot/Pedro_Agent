import json, tempfile, unittest
from pathlib import Path
from unittest import mock

import brain


class BrainTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.p = mock.patch.object(brain, "_storage", lambda: self.tmp)
        self.p.start(); brain.reset_cache()

    def tearDown(self):
        self.p.stop(); brain.reset_cache()

    def test_retired_and_paid_models_are_never_used(self):
        for m in ("gemini-2.0-flash", "gemini-2.5-flash", "gemini-3-pro-preview", "gemini-3.1-pro-preview", "gemini-4-argon"):
            self.assertFalse(brain.usable(m), m)
        self.assertTrue(brain.usable("gemini-3.6-flash"))

    def test_hard_requests_start_on_the_top_model_until_the_budget_is_spent(self):
        order = brain.chain()
        self.assertEqual(brain.order_for_turn(order, "build me a budget tracker app with charts", 0)[0], brain.TOP)
        self.assertEqual(brain.order_for_turn(order, "hi there", 0)[0], brain.MAIN)
        self.assertEqual(brain.order_for_turn(order, "build me a budget tracker app with charts", 5)[0], brain.MAIN)
        for _ in range(brain.TOP_DAILY_BUDGET):
            brain.note_call(brain.TOP)
        self.assertEqual(brain.order_for_turn(order, "build me a budget tracker app with charts", 0)[0], brain.MAIN)
        self.assertNotIn(brain.TOP, brain.order_for_turn(order, "hi", 0))

    def test_model_list_filters_to_what_the_key_supports(self):
        body = json.dumps({"models": [
            {"name": "models/gemini-3.6-flash", "supportedGenerationMethods": ["generateContent"]},
            {"name": "models/gemini-3.1-flash-lite", "supportedGenerationMethods": ["generateContent"]},
            {"name": "models/gemini-4.0-flash", "supportedGenerationMethods": ["generateContent"]},
            {"name": "models/gemini-embedding-2", "supportedGenerationMethods": ["embedContent"]}]})
        avail = brain.discover("k", fetch=lambda: body)
        names = brain.chain(available=avail)
        self.assertEqual(names[:2], ["gemini-3.6-flash", "gemini-3.1-flash-lite"])
        self.assertIn("gemini-4.0-flash", names)   # a newer flash Google adds later is used too
        self.assertNotIn("gemini-3.8-flash", names)

    def test_thinking_levels(self):
        self.assertEqual(brain.thinking_level("gemini-3.8-flash", "plan and build a website for my shop", False), "high")
        self.assertEqual(brain.thinking_level("gemini-3.6-flash", "hi", False), "medium")
        self.assertEqual(brain.thinking_level("gemini-3.6-flash", "plan it", True), "minimal")


class PastChatTests(unittest.TestCase):
    def test_search_past_finds_related_lines_and_hides_secrets(self):
        import chat_store
        db = Path(tempfile.mkdtemp()) / "c.db"
        chat_store.add("s1", "user", "My favourite football club is Chelsea", path=db)
        chat_store.add("s1", "user", "my api key is AIzaSECRET football", path=db)
        chat_store.add("s2", "user", "unrelated text about cooking rice", path=db)
        rows = chat_store.search_past("which football club do I support?", path=db)
        texts = [r["text"] for r in rows]
        self.assertTrue(any("Chelsea" in t for t in texts))
        self.assertFalse(any("AIza" in t for t in texts))


if __name__ == "__main__":
    unittest.main()


class SmartTurnTests(unittest.TestCase):
    def test_hard_turn_uses_top_model_with_high_thinking_and_skips_a_missing_model(self):
        import os, agent_core
        from google.genai import types
        tmp = Path(tempfile.mkdtemp())
        calls = []

        class Models:
            def generate_content(self, **kw):
                cfg = kw["config"]
                level = getattr(getattr(cfg, "thinking_config", None), "thinking_level", None)
                calls.append((kw["model"], str(level)))
                if kw["model"] == brain.TOP:
                    raise RuntimeError("404 NOT_FOUND models/gemini-3.8-flash is not found for API version v1beta")
                return types.GenerateContentResponse(candidates=[types.Candidate(content=types.Content(
                    role="model", parts=[types.Part.from_text(text="Plan: 1. sketch 2. build")]))])

            def generate_content_stream(self, **kw):
                yield self.generate_content(**kw)

        class Client:
            def __init__(self, key): self.models = Models()

        with mock.patch.object(brain, "_storage", lambda: tmp), \
             mock.patch.object(agent_core, "_smart_on", lambda: True), \
             mock.patch.object(agent_core, "_gemini_client", lambda genai, key: Client(key)), \
             mock.patch.object(agent_core, "_past_chat_note", lambda *a: ""), \
             mock.patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}):
            brain.reset_cache(); brain._available = list(brain.CHAIN)
            out = agent_core.run_agent("build me a simple budget tracker app with charts and explain the plan", [], agent_core.DEFAULT_MODEL)
            brain.reset_cache()
        self.assertEqual(calls[0][0], brain.TOP)
        self.assertIn("HIGH", calls[0][1])
        self.assertEqual(calls[1][0], brain.MAIN)
        self.assertIn("Plan", out)
