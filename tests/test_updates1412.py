"""Quota skip, chat pins, and local Live PC control."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("PEDRO_AGENT_NO_FILE_LOG", "1")

import agent_core  # noqa: E402
import cloud_fallback  # noqa: E402
import confirm_action  # noqa: E402
import extras148  # noqa: E402
import live_pc  # noqa: E402
import rules  # noqa: E402


class WebcamCallTests(unittest.TestCase):
    def test_blank_argument_name_still_opens_the_webcam_tool(self):
        seen: list[bool] = []
        original = agent_core.TOOLS["capture_webcam_image"]

        def fake_camera() -> dict[str, bool]:
            seen.append(True)
            return {"ok": True, "message": "Captured"}

        agent_core.TOOLS["capture_webcam_image"] = fake_camera
        self.addCleanup(agent_core.TOOLS.__setitem__, "capture_webcam_image", original)
        agent_core.begin_task_turn("look at me")
        result = agent_core.invoke_tool("capture_webcam_image", {"": {}})
        self.assertTrue(result["ok"], result)
        self.assertEqual(seen, [True])
        refused = agent_core.invoke_tool("capture_webcam_image", {"rtmp_url": "rtmp://evil.example/live"})
        self.assertFalse(refused["ok"])
        self.assertIn("Bad arguments", refused["error"])
        self.assertEqual(seen, [True])


class TurnModelTests(unittest.TestCase):
    def test_models_for_turn_skips_spent_names(self):
        fresh, backup = agent_core.models_for_turn(["a", "b", "c"], {"a"})
        self.assertEqual(fresh, ["b", "c"])
        self.assertFalse(backup)
        fresh, backup = agent_core.models_for_turn(["a", "b"], {"a", "b"})
        self.assertEqual(fresh, [])
        self.assertTrue(backup)
        fresh, backup = agent_core.models_for_turn([], {"a"})
        self.assertEqual(fresh, [])
        self.assertFalse(backup)

    def test_exhausted_models_after_a_429(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        old = extras148.ROOT
        extras148.ROOT = Path(tmp.name)
        self.addCleanup(setattr, extras148, "ROOT", old)
        extras148.note_model_call("gemini-x", False, "429 quota")
        extras148.note_model_call("gemini-y", True)
        self.assertEqual(extras148.exhausted_models(), {"gemini-x"})


class _RulesCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(os.path.realpath(self.tmp.name))
        self.rules_file = self.root / "rules.json"
        self.rules_file.write_text("{}", encoding="utf-8")
        os.environ["RULES_FILE"] = str(self.rules_file)
        os.environ["STORAGE_DIR"] = str(self.root / "storage")
        rules.reset_cache()
        confirm_action.reset()
        self.saved_client = agent_core.genai_client_override
        self.saved_root = extras148.ROOT
        self.saved_transport = cloud_fallback.transport_override
        self.saved_key = os.environ.get("GROQ_API_KEY")
        extras148.ROOT = self.root
        os.environ.setdefault("GEMINI_API_KEY", "test-key-123")

    def tearDown(self):
        agent_core.genai_client_override = self.saved_client
        extras148.ROOT = self.saved_root
        cloud_fallback.transport_override = self.saved_transport
        if self.saved_key is None:
            os.environ.pop("GROQ_API_KEY", None)
        else:
            os.environ["GROQ_API_KEY"] = self.saved_key
        os.environ.pop("RULES_FILE", None)
        os.environ.pop("STORAGE_DIR", None)
        rules.reset_cache()
        confirm_action.reset()
        self.tmp.cleanup()

    def _fake_client(self, behaviour):
        class Models:
            def generate_content(self, **kwargs):
                return behaviour(kwargs)

        class Client:
            def __init__(self, key):
                self.models = Models()

        return lambda key: Client(key)


class BackupWhenSpentTests(_RulesCase):
    def _spend(self, names):
        for name in names:
            extras148.note_model_call(name, False, "429 RESOURCE_EXHAUSTED")

    def test_spent_models_are_still_tried_before_the_quota_message(self):
        called = []
        self._spend(agent_core.model_candidates("first-model"))

        def behaviour(kwargs):
            called.append(kwargs["model"])
            raise RuntimeError("429 RESOURCE_EXHAUSTED model: first-model limit: 20 retry in 1h")

        agent_core.genai_client_override = self._fake_client(behaviour)
        cloud_fallback.transport_override = lambda body: {"choices": [{"message": {"content": "from groq"}}]}
        with self.assertRaises(RuntimeError) as err:
            agent_core.run_agent("check my files", [], "first-model")  # not simple chat (1.4.15 fast path)
        self.assertIn("first-model", called)
        self.assertIn("free Gemini quota", str(err.exception))
        self.assertNotIn("from groq", str(err.exception))


class PinTests(unittest.TestCase):
    def test_pin_stays_above_newer_chats_and_delete_clears_it(self):
        import chat_store

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db = Path(tmp.name) / "h.db"
        chat_store.add("old", "user", "first", db)
        chat_store.add("new", "user", "second", db)
        self.assertEqual(chat_store.sessions(db)[0]["session"], "new")
        self.assertTrue(chat_store.set_pin("old", True, db))
        rows = chat_store.sessions(db)
        self.assertEqual([row["session"] for row in rows], ["old", "new"])
        self.assertTrue(rows[0]["pinned"])
        self.assertFalse(rows[1]["pinned"])
        self.assertFalse(chat_store.set_pin("old", False, db))
        self.assertEqual(chat_store.sessions(db)[0]["session"], "new")
        chat_store.set_pin("old", True, db)
        chat_store.delete_session("old", db)
        left = chat_store.sessions(db)
        self.assertEqual(left[0]["session"], "new")
        self.assertFalse(left[0]["pinned"])


class LocalControlTests(unittest.TestCase):
    def test_mouse_override_records_the_kind_and_skips_the_screen(self):
        seen = []
        old = live_pc.mouse_override
        live_pc.mouse_override = lambda kind, fields: seen.append((kind, dict(fields)))
        self.addCleanup(setattr, live_pc, "mouse_override", old)
        click = live_pc.local_control({"type": "click", "x": 0.25, "y": 1.4, "button": "right"})
        drag = live_pc.local_control({"type": "drag", "x": 0.1, "y": 0.2, "x2": 0.3, "y2": 0.4})
        scroll = live_pc.local_control({"type": "scroll", "x": 0.5, "y": 0.5, "delta": 120})
        typed = live_pc.local_control({"type": "type", "text": "Hi!\nthere"})
        self.assertTrue(click["ok"])
        self.assertEqual(seen[0][0], "click")
        self.assertEqual(seen[0][1]["button"], "right")
        self.assertEqual(seen[0][1]["y"], 1.0)
        self.assertEqual(seen[1][0], "drag")
        self.assertEqual(seen[1][1]["x2"], 0.3)
        self.assertEqual(seen[2][0], "scroll")
        self.assertLess(seen[2][1]["steps"], 0)
        self.assertGreaterEqual(seen[2][1]["steps"], -8)
        self.assertTrue(typed["ok"])
        self.assertNotIn("\n", seen[3][1]["text"])
        self.assertFalse(live_pc.local_control({"type": "explode"})["ok"])


class InterfaceTests(unittest.TestCase):
    def test_new_controls_are_in_the_page(self):
        root = ROOT / "app_static"
        html = (root / "index.html").read_text(encoding="utf-8")
        js = (root / "app.js").read_text(encoding="utf-8")
        live = (root / "live_ui.js").read_text(encoding="utf-8")
        css = (root / "app.css").read_text(encoding="utf-8")
        for token in ("live-size", "live-resize", "live-ctl-on"):
            self.assertIn(token, html)
        for token in ("msg-copy", "msg-reply", "addCopy", "replyBar", "reply-in", "/api/pin", "finishPing", "togglePin", "document.hidden"):
            self.assertIn(token, js)
        self.assertIn("containedPoint", live)
        self.assertIn("narrowScreen", live)
        self.assertIn("placePhonePicture", live)
        self.assertIn("img.style.width = n + '%'", live)
        remote = (ROOT / "remote_access.py").read_text(encoding="utf-8")
        self.assertIn("phone_control(self._body())", remote)   # 1.4.14: permission checks first
        self.assertIn("done-flash", css)
        self.assertIn(".sess.pinned", css)
        app = (ROOT / "chat_app.py").read_text(encoding="utf-8")
        self.assertIn('url.path == "/api/pin"', app)
        self.assertIn('url.path == "/live/control"', app)
        self.assertIn('"local": not self.remote', app)


if __name__ == "__main__":
    unittest.main()
