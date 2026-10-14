"""Tests for the upgrade: rules file, confirm categories, timeouts, model
fallback, streaming events, vision clicking, file tools, chat app."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
import types
import unittest
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["PEDRO_AGENT_NO_FILE_LOG"] = "1"

import gta5_agent  # noqa: E402
import confirm_action  # noqa: E402
import rules  # noqa: E402


class _RulesCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        # realpath expands Windows 8.3 short names in %TEMP% (e.g. JOHNSM~1).
        self.root = Path(os.path.realpath(self.tmp.name))
        self.rules_file = self.root / "rules.json"
        self.write_rules({})
        os.environ["RULES_FILE"] = str(self.rules_file)
        os.environ["STORAGE_DIR"] = str(self.root / "storage")
        rules.reset_cache()
        confirm_action.reset()
        gta5_agent.voice_mode_active = False
        gta5_agent.begin_task_turn("")
        self.saved = (gta5_agent.genai_client_override, gta5_agent.network_up_override,
                      gta5_agent.screenshot_override, gta5_agent.vision_locator_override,
                      gta5_agent.tool_timeout_override)

    def tearDown(self) -> None:
        (gta5_agent.genai_client_override, gta5_agent.network_up_override,
         gta5_agent.screenshot_override, gta5_agent.vision_locator_override,
         gta5_agent.tool_timeout_override) = self.saved
        for key in ("RULES_FILE", "STORAGE_DIR"):
            os.environ.pop(key, None)
        rules.reset_cache()
        confirm_action.reset()
        self.tmp.cleanup()

    def write_rules(self, data: dict) -> None:
        self.rules_file.write_text(json.dumps(data), encoding="utf-8")
        # force mtime change to be seen even within the same second
        rules.reset_cache()


class RulesTests(_RulesCase):
    def test_shipped_yaml_parses_and_keeps_confirm_defaults(self) -> None:
        shipped = Path(rules.APP_DIR) / "rules.yaml"
        data = rules.parse_text(shipped.read_text(encoding="utf-8"), ".yaml")
        merged = rules._merge(rules.DEFAULT_RULES, data)
        for category in ("delete", "payment", "send_message", "power"):
            self.assertIn(category, merged["confirm"]["categories"])
        self.assertTrue(merged["confirm"]["enabled"])

    def test_defaults_are_permissive(self) -> None:
        self.assertTrue(rules.path_allowed(Path("/opt/somewhere/a.xlsx")))
        self.assertFalse(rules.path_blocked(Path("C:/Windows/System32/x.dll")))
        self.assertIsNone(rules.file_write_reason(Path("game/GTA5.exe")))
        for key, value in rules.DEFAULT_RULES["limits"].items():
            self.assertFalse(value, key)
        for key, value in rules.DEFAULT_RULES["protect"].items():
            self.assertTrue(value, key)

    def test_old_path_limits_come_back_from_rules(self) -> None:
        self.write_rules({"paths": {"allowed": ["~", "{workspace}", "{external}"],
                                    "blocked": ["?:/Windows", "?:/Program Files"]},
                          "files": {"allow_exe_writes": False}})
        self.assertTrue(rules.path_allowed(Path.home() / "Documents" / "a.xlsx"))
        self.assertFalse(rules.path_allowed(Path("/opt/somewhere/a.xlsx")))
        self.assertTrue(rules.path_blocked(Path("C:/Windows/System32/x.dll")))
        self.assertTrue(rules.path_blocked(Path("D:\\Program Files\\x")))
        self.assertIn("executable", rules.file_write_reason(Path("game/GTA5.exe")))

    def test_user_can_open_everything_and_allow_exe(self) -> None:
        self.write_rules({"paths": {"allowed": ["*"], "blocked": []},
                          "files": {"allow_exe_writes": True}})
        self.assertTrue(rules.path_allowed(Path("/opt/somewhere/a.xlsx")))
        self.assertTrue(rules.path_allowed(Path("C:/Windows/notes.txt")))
        self.assertIsNone(rules.file_write_reason(Path("tool.exe")))
        self.assertTrue(gta5_agent._path_is_allowed(Path("/opt/x.txt")))
        self.assertIsNone(gta5_agent._protected_reason(Path("x.exe")))

    def test_user_can_block_folders_and_extensions(self) -> None:
        secret = self.root / "secret"
        self.write_rules({"paths": {"allowed": ["*"], "blocked": [str(secret)]},
                          "files": {"blocked_extensions": [".bat"]}})
        self.assertFalse(rules.path_allowed(secret / "a.txt"))
        self.assertTrue(rules.path_allowed(self.root / "open" / "a.txt"))
        self.assertIn(".bat", rules.file_write_reason(Path("run.bat")))

    def test_tool_block_and_allow_lists(self) -> None:
        self.write_rules({"tools": {"blocked": ["open_website"]}})
        result = gta5_agent.invoke_tool("open_website", {"url": "https://example.com"})
        self.assertFalse(result["ok"])
        self.assertTrue(result.get("blocked_by_rules"))
        self.write_rules({"tools": {"allowed": ["recall_memory"]}})
        self.assertIsNotNone(rules.tool_block_reason("open_website"))
        self.assertIsNone(rules.tool_block_reason("recall_memory"))

    def test_confirm_categories_and_switch_off(self) -> None:
        self.assertTrue(rules.needs_confirmation("delete_path", {"path": "x"}))
        self.assertTrue(rules.needs_confirmation("gmail_send_message", {"to": "a@b.c"}))
        self.assertTrue(rules.needs_confirmation("shutdown_computer", {}))
        self.assertTrue(rules.needs_confirmation(
            "perform_actions", {"actions": [{"action": "click", "label": "Place order"}]}))
        self.assertFalse(rules.needs_confirmation("open_website", {"url": "https://a.b"}))
        self.write_rules({"confirm": {"enabled": False}})
        self.assertFalse(rules.needs_confirmation("delete_path", {"path": "x"}))
        self.write_rules({"confirm": {"categories": [], "extra_tools": ["open_website"]}})
        self.assertFalse(rules.needs_confirmation("shutdown_computer", {}))
        self.assertTrue(rules.needs_confirmation("open_website", {}))

    def test_settings_page_save_validates(self) -> None:
        with self.assertRaises(Exception):
            rules.save_text("{not json")
        rules.save_text(json.dumps({"agent": {"max_tool_rounds": 7}}))
        self.assertEqual(gta5_agent.max_tool_rounds(), 7)


class FileToolTests(_RulesCase):
    def test_delete_waits_for_yes_then_runs(self) -> None:
        self.write_rules({"paths": {"allowed": [str(self.root)]}})
        target = self.root / "old.txt"
        target.write_text("x")
        args = {"path": str(target)}
        first = gta5_agent.invoke_tool("delete_path", args)
        self.assertTrue(first.get("needs_confirmation"))
        self.assertTrue(target.exists())
        gta5_agent.begin_task_turn("yes")
        second = gta5_agent.invoke_tool("delete_path", args)
        self.assertTrue(second["ok"], second)
        self.assertFalse(target.exists())

    def test_write_respects_rules(self) -> None:
        self.write_rules({"paths": {"allowed": [str(self.root)]}})
        ok = gta5_agent.invoke_tool("write_text_file", {"path": str(self.root / "a" / "n.md"), "content": "hi"})
        self.assertTrue(ok["ok"], ok)
        bad = gta5_agent.invoke_tool("write_text_file", {"path": "/opt/nope.md", "content": "hi"})
        self.assertFalse(bad["ok"])
        exe = gta5_agent.invoke_tool("write_text_file", {"path": str(self.root / "t.exe"), "content": "x"})
        self.assertTrue(exe["ok"], exe)  # allowed by default
        self.write_rules({"paths": {"allowed": [str(self.root)]}, "files": {"allow_exe_writes": False}})
        exe = gta5_agent.invoke_tool("write_text_file", {"path": str(self.root / "u.exe"), "content": "x"})
        self.assertIn("executable", exe["error"])


class LimitSwitchTests(_RulesCase):
    def test_scheduler_runs_programs_unless_switched_off(self) -> None:
        import task_schedule

        task_schedule.clear_jobs()
        ran = []
        task_schedule.program_runner_override = ran.append
        try:
            queued = gta5_agent.invoke_tool("job_scheduler", {
                "task": "run_program", "message": "C:/tools/backup.py --full", "daily_at": "02:00"})
            self.assertTrue(queued["ok"], queued)
            job = task_schedule._jobs[-1]
            result = task_schedule._run_job(job)
            self.assertTrue(result["ok"], result)
            self.assertEqual(ran[0][1:], ["C:/tools/backup.py", "--full"])
            self.assertTrue(ran[0][0].endswith(("python", "python3", "python.exe")) or "python" in ran[0][0])
            self.write_rules({"limits": {"scheduler_allowlist_only": True}})
            refused = gta5_agent.invoke_tool("job_scheduler", {"task": "backup.py", "delay_minutes": 5})
            self.assertFalse(refused["ok"])
            self.assertIn("scheduler_allowlist_only", refused["error"])
        finally:
            task_schedule.program_runner_override = None
            task_schedule.clear_jobs()

    def test_numeric_caps(self) -> None:
        self.assertIsNone(rules.cap("max_plan_steps", 8))
        self.write_rules({"limits": {"max_plan_steps": True, "max_action_batch": 3}})
        self.assertEqual(rules.cap("max_plan_steps", 8), 8)
        self.assertEqual(rules.cap("max_action_batch", 12), 3)
        steps = [f"step {i}" for i in range(10)]
        capped = gta5_agent.invoke_tool("create_task_plan", {"goal": "g", "steps": steps})
        self.assertIn("max_plan_steps", capped["error"])
        self.write_rules({})
        gta5_agent.begin_task_turn("")
        ok = gta5_agent.invoke_tool("create_task_plan", {"goal": "g", "steps": steps})
        self.assertTrue(ok["ok"], ok)

    def test_sql_and_excel_switches(self) -> None:
        with self.assertRaises(ValueError):
            self.write_rules({"limits": {"sql_safe_mode": True}})
            gta5_agent._sql_text("EXEC xp_cmdshell 'dir'")
        self.write_rules({})
        self.assertIn("xp_cmdshell", gta5_agent._sql_text("EXEC xp_cmdshell 'dir'"))
        self.assertEqual(gta5_agent._excel_cell("=WEBSERVICE(\"x\")"), "=WEBSERVICE(\"x\")")
        self.write_rules({"limits": {"excel_block_risky_formulas": True}})
        with self.assertRaises(ValueError):
            gta5_agent._excel_cell("=WEBSERVICE(\"x\")")

    def test_secret_text_switch(self) -> None:
        import browser_download

        steps = browser_download._actions([{"action": "fill", "selector": "#p", "text": "password=hunter2"},
                                           {"action": "press", "key": "Control+A"}])
        self.assertEqual(steps[1]["key"], "Control+A")
        self.write_rules({"limits": {"refuse_secret_text": True, "browser_action_caps": True}})
        with self.assertRaises(ValueError):
            browser_download._actions([{"action": "fill", "selector": "#p", "text": "password=hunter2"}])
        with self.assertRaises(ValueError):
            browser_download._actions([{"action": "press", "key": "Control+A"}])

    def test_protect_switches(self) -> None:
        agent_file = Path(gta5_agent.__file__).resolve()
        self.write_rules({"confirm": {"enabled": False}})
        blocked = gta5_agent.invoke_tool("delete_path", {"path": str(agent_file)})
        self.assertIn("never_delete_agent_folder", blocked["error"])
        self.assertTrue(agent_file.exists())
        root = Path(Path.home().anchor)
        self.assertIn("never_delete_drive_root", gta5_agent.invoke_tool("delete_path", {"path": str(root)})["error"])

    def test_prompt_defers_to_rules(self) -> None:
        prompt = gta5_agent.SYSTEM_PROMPT
        self.assertIn("ONLY restrictions", prompt)
        self.assertNotIn("Do not schedule a script", prompt)
        self.assertNotIn("Never replace an .exe", prompt)
        self.assertIn("malware", prompt)  # fixed, non-configurable line stays


class ReliabilityTests(_RulesCase):
    def test_stuck_tool_times_out(self) -> None:
        gta5_agent.tool_timeout_override = 0.2
        gta5_agent.TOOLS["_slow_test_tool"] = lambda: (time.sleep(2), {"ok": True})[1]
        try:
            started = time.monotonic()
            result = gta5_agent.invoke_tool("_slow_test_tool", {})
            self.assertLess(time.monotonic() - started, 1.5)
            self.assertFalse(result["ok"])
            self.assertIn("timed out", result["error"])
        finally:
            del gta5_agent.TOOLS["_slow_test_tool"]

    def test_model_candidates_use_rules_order(self) -> None:
        self.write_rules({"agent": {"models": ["m-two", "m-three"]}})
        order = gta5_agent.model_candidates("m-one")
        self.assertEqual(order[:3], ["m-one", "m-two", "m-three"])
        self.assertEqual(len(order), len(set(order)))

    def _fake_client(self, behaviour):
        class Models:
            def generate_content(self, **kwargs):
                return behaviour(kwargs)

        class Client:
            def __init__(self, key):
                self.models = Models()

        return lambda key: Client(key)

    def test_quota_falls_back_to_next_model_and_emits_event(self) -> None:
        self.write_rules({"agent": {"models": ["second-model"]}})
        os.environ.setdefault("GEMINI_API_KEY", "test-key-123")
        gta5_agent.network_up_override = True
        seen = []

        def behaviour(kwargs):
            seen.append(kwargs["model"])
            if kwargs["model"] == "first-model":
                raise RuntimeError("429 RESOURCE_EXHAUSTED quota")
            part = types.SimpleNamespace(text="Done.", thought=False)
            cand = types.SimpleNamespace(content=types.SimpleNamespace(parts=[part]))
            return types.SimpleNamespace(candidates=[cand], function_calls=None, text="Done.")

        gta5_agent.genai_client_override = self._fake_client(behaviour)
        events = []
        reply = gta5_agent.run_agent("hello", [], "first-model", on_event=events.append)
        self.assertEqual(reply, "Done.")
        self.assertEqual(seen[:2], ["first-model", "second-model"])
        kinds = [e["event"] for e in events]
        self.assertIn("model_switch", kinds)
        self.assertIn("final", kinds)

    def test_tool_events_are_emitted(self) -> None:
        os.environ.setdefault("GEMINI_API_KEY", "test-key-123")
        gta5_agent.network_up_override = True
        calls = {"n": 0}

        def behaviour(kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                call = types.SimpleNamespace(name="recall_memory", args={"query": "x"}, id="1")
                part = types.SimpleNamespace(text=None, thought=False, function_call=call)
                cand = types.SimpleNamespace(content=types.SimpleNamespace(role="model", parts=[part]))
                return types.SimpleNamespace(candidates=[cand], function_calls=[call], text=None)
            part = types.SimpleNamespace(text="All set.", thought=False)
            cand = types.SimpleNamespace(content=types.SimpleNamespace(parts=[part]))
            return types.SimpleNamespace(candidates=[cand], function_calls=None, text="All set.")

        gta5_agent.genai_client_override = self._fake_client(behaviour)
        events = []
        reply = gta5_agent.run_agent("what do you remember", [], "m", on_event=events.append)
        self.assertEqual(reply, "All set.")
        names = [(e["event"], e.get("name")) for e in events]
        self.assertIn(("tool_start", "recall_memory"), names)
        self.assertIn(("tool_end", "recall_memory"), names)


class VisionTests(_RulesCase):
    def setUp(self) -> None:
        super().setUp()
        gta5_agent.VISION_SETTLE_SECONDS = 0
        self.frames = [b"frame-a", b"frame-b", b"frame-c", b"frame-d"]
        self.clicks = []
        gta5_agent.screenshot_override = None
        self.orig_shot = gta5_agent.take_screenshot
        self.orig_click = gta5_agent.click_element

        def fake_shot():
            data = self.frames.pop(0) if len(self.frames) > 1 else self.frames[0]
            return {"ok": True, "_screenshot_bytes": data, "_screenshot_mime": "image/jpeg"}

        gta5_agent.take_screenshot = fake_shot
        gta5_agent.click_element = lambda x, y, clicks=1: (self.clicks.append((x, y, clicks)), {"ok": True})[1]

    def tearDown(self) -> None:
        gta5_agent.take_screenshot = self.orig_shot
        gta5_agent.click_element = self.orig_click
        super().tearDown()

    def test_parse_box_to_centre(self) -> None:
        import screen_vision

        parsed = screen_vision._parse('```json\n{"found": true, "box_2d": [100, 200, 300, 400], "label": "OK"}\n```')
        self.assertEqual((parsed["x"], parsed["y"]), (300, 200))
        self.assertFalse(screen_vision._parse("nope")["found"])

    def test_click_retries_until_found(self) -> None:
        answers = [{"found": False}, {"found": True, "x": 510, "y": 220}]
        gta5_agent.vision_locator_override = lambda img, mime, desc: answers.pop(0)
        result = gta5_agent.invoke_tool("click_screen_target", {"description": "Sign in", "retries": 2})
        self.assertTrue(result["ok"], result)
        self.assertEqual(self.clicks, [(510, 220, 1)])
        self.assertEqual(result["attempts"], 2)
        self.assertTrue(result["screen_changed"])

    def test_find_reports_missing(self) -> None:
        gta5_agent.vision_locator_override = lambda img, mime, desc: {"found": False}
        result = gta5_agent.invoke_tool("find_on_screen", {"description": "a unicorn"})
        self.assertFalse(result["ok"])
        self.assertEqual(self.clicks, [])


def _png(color, size=(400, 300)):
    import io
    from PIL import Image

    out = io.BytesIO()
    Image.new("RGB", size, color).save(out, "PNG")
    return out.getvalue()


class SpeedTests(VisionTests):
    def test_speed_defaults_and_overrides(self) -> None:
        self.assertLessEqual(rules.speed_setting("settle_seconds"), 0.2)
        self.assertIn("lite", rules.speed_setting("vision_model"))
        self.write_rules({"speed": {"settle_seconds": 0.5, "vision_model": "my-model"}})
        self.assertEqual(rules.speed_setting("settle_seconds"), 0.5)
        import screen_vision

        self.assertEqual(screen_vision._vision_models()[0], "my-model")

    def test_shrink_for_vision_downscales_to_jpeg(self) -> None:
        import io
        import fast_screen
        from PIL import Image

        raw = _png((10, 200, 30), (2560, 1440))
        data, mime = fast_screen.shrink_for_vision(raw, "image/png")
        self.assertEqual(mime, "image/jpeg")
        self.assertEqual(Image.open(io.BytesIO(data)).width, 1024)
        self.assertLess(len(data), len(raw))

    def test_pixel_diff(self) -> None:
        import fast_screen

        a, b = _png((0, 0, 0)), _png((255, 255, 255))
        self.assertTrue(fast_screen.pixel_changed(a, b))
        self.assertFalse(fast_screen.pixel_changed(a, _png((0, 0, 0))))

    def test_control_name_from_description(self) -> None:
        import screen_vision

        self.assertEqual(screen_vision.control_name_from("the Sign in button"), "Sign in")
        self.assertEqual(screen_vision.control_name_from("click 'Save as'"), "Save as")

    def test_ui_automation_is_tried_before_vision(self) -> None:
        asked = []
        gta5_agent.uia_finder_override = lambda name, win: (asked.append(name), {"found": True, "x": 100, "y": 900, "via": "uiautomation"})[1]
        gta5_agent.vision_locator_override = lambda *a: self.fail("vision should not run")
        try:
            result = gta5_agent.invoke_tool("click_screen_target", {"description": "the OK button"})
        finally:
            gta5_agent.uia_finder_override = None
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["via"], "uiautomation")
        self.assertEqual(asked[0], "OK")
        self.assertEqual(self.clicks, [(100, 900, 1)])

    def test_vision_fallback_gets_shrunk_image_and_no_second_vision_call(self) -> None:
        self.frames[:] = [_png((0, 0, 0), (1920, 1080)), _png((255, 255, 255), (1920, 1080))]
        gta5_agent.uia_finder_override = lambda name, win: None
        seen = []
        gta5_agent.vision_locator_override = lambda img, mime, d: (seen.append((len(img), mime)), {"found": True, "x": 5, "y": 5})[1]
        try:
            result = gta5_agent.invoke_tool("click_screen_target", {"description": "logo"})
        finally:
            gta5_agent.uia_finder_override = None
        self.assertTrue(result["ok"], result)
        self.assertEqual(len(seen), 1)  # verification used pixel diff, not vision
        self.assertEqual(seen[0][1], "image/jpeg")
        self.assertTrue(result["screen_changed"])

    def test_desktop_has_no_hidden_pauses(self) -> None:
        import mouse_controller

        fake = types.SimpleNamespace(PAUSE=0.1, MINIMUM_DURATION=0.1, MINIMUM_SLEEP=0.05)
        mouse_controller.configure_desktop(fake)
        self.assertEqual((fake.PAUSE, fake.MINIMUM_DURATION, fake.MINIMUM_SLEEP), (0, 0, 0))


class ChatAppTests(_RulesCase):
    def test_history_store(self) -> None:
        import chat_store

        db = self.root / "h.db"
        chat_store.add("s1", "user", "hi", db)
        chat_store.add("s1", "assistant", "hello", db)
        self.assertEqual([m["role"] for m in chat_store.history("s1", path=db)], ["user", "assistant"])
        self.assertEqual(chat_store.sessions(db)[0]["title"], "hi")
        chat_store.close()

    def test_server_streams_events_and_edits_rules(self) -> None:
        import chat_app

        original = gta5_agent.run_agent

        def fake_run(text, history, model, *, cancel_event=None, on_text=None, on_event=None, **kw):
            on_event({"event": "tool_start", "name": "recall_memory"})
            on_text("Hello")
            on_text("Pedro.")
            return "Hello Pedro."

        gta5_agent.run_agent = fake_run
        server, _state = chat_app.serve("m", port=0)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{server.server_address[1]}"
        try:
            req = urllib.request.Request(base + "/api/chat", data=json.dumps({"text": "hi"}).encode(),
                                         headers={"Content-Type": "application/json"})
            body = urllib.request.urlopen(req, timeout=5).read().decode()
            events = [json.loads(l[6:]) for l in body.split("\n\n") if l.startswith("data: ")]
            kinds = [e["event"] for e in events]
            self.assertEqual(kinds[0], "session")
            self.assertIn("token", kinds)
            self.assertIn({"event": "done", "text": "Hello Pedro."}, events)
            self.assertEqual(events[-1], {"event": "speech_end", "status": "skipped"})
            session = events[0]["session"]
            hist = json.loads(urllib.request.urlopen(base + "/api/history?session=" + session).read())
            self.assertEqual([h["text"] for h in hist], ["hi", "Hello Pedro."])
            self.assertIn("<title>Pedro_Agent</title>", urllib.request.urlopen(base + "/").read().decode())
            save = urllib.request.Request(base + "/api/rules", data=json.dumps(
                {"text": json.dumps({"confirm": {"enabled": False}})}).encode(),
                headers={"Content-Type": "application/json"})
            self.assertTrue(json.loads(urllib.request.urlopen(save).read())["ok"])
            self.assertFalse(rules.needs_confirmation("delete_path", {}))
            evil = urllib.request.Request(base + "/api/rules", data=b"{}",
                                          headers={"Content-Type": "application/json", "Origin": "http://evil.example"})
            with self.assertRaises(urllib.error.HTTPError):
                urllib.request.urlopen(evil)
        finally:
            gta5_agent.run_agent = original
            server.shutdown()
            server.server_close()
            import chat_store

            chat_store.close()


class ChatVoiceTests(_RulesCase):
    class FakePipeline:
        def __init__(self, barge=None):
            self.spoken, self.aborted, self.barge = [], False, barge

        def submit(self, sentence):
            self.spoken.append(sentence)

        def finish(self):
            if self.barge:
                return {"ok": True, "interrupted": True, "transcript": self.barge}
            return {"ok": True}

        def abort(self):
            self.aborted = True

    def _run(self, barge=None, cancel=False):
        import chat_app

        state = chat_app.AppState("m")
        state.speak = True
        pipe = self.FakePipeline(barge)
        state.pipeline_factory = lambda: pipe
        original = gta5_agent.run_agent

        def fake_run(text, history, model, *, cancel_event=None, on_text=None, on_event=None, **kw):
            on_text("First sentence.")
            if cancel:
                cancel_event.set()
            on_text("Second one.")
            return "First sentence. Second one."

        gta5_agent.run_agent = fake_run
        events = []
        try:
            chat_app.stream_turn(state, "s", "hi", events.append)
        finally:
            gta5_agent.run_agent = original
            import chat_store

            chat_store.close()
        return pipe, events

    def test_reply_is_spoken_sentence_by_sentence(self) -> None:
        pipe, events = self._run()
        self.assertEqual(pipe.spoken, ["First sentence.", "Second one."])
        self.assertFalse(pipe.aborted)

    def test_barge_in_transcript_becomes_next_message(self) -> None:
        _pipe, events = self._run(barge="actually open notepad")
        self.assertIn({"event": "barge", "text": "actually open notepad"}, events)

    def test_stop_aborts_speech(self) -> None:
        pipe, _events = self._run(cancel=True)
        self.assertTrue(pipe.aborted)
        self.assertEqual(pipe.spoken, ["First sentence."])

    def test_listen_uses_local_microphone_pipeline(self) -> None:
        import chat_app

        original = gta5_agent.listen_to_microphone
        calls = []
        gta5_agent.listen_to_microphone = lambda **kw: (calls.append(kw), {"ok": True, "text": "what time is it"})[1]
        try:
            state = chat_app.AppState("m")
            heard = chat_app.listen_once(state)
        finally:
            gta5_agent.listen_to_microphone = original
        self.assertEqual(heard, {"ok": True, "text": "what time is it", "error": "", "kind": "speech"})
        self.assertFalse(calls[0]["announce"])

    def test_every_turn_ends_with_speech_end(self) -> None:
        _pipe, events = self._run()
        self.assertEqual(events[-1], {"event": "speech_end", "status": "ok"})
        _pipe, events = self._run(cancel=True)
        self.assertEqual(events[-1]["event"], "speech_end")

    def _turn_with_pipeline(self, pipe, speak=True):
        import chat_app
        import chat_store

        state = chat_app.AppState("m")
        state.speak = speak
        state.pipeline_factory = lambda: pipe
        original = gta5_agent.run_agent
        gta5_agent.run_agent = lambda *a, **k: "Reply."
        events = []
        try:
            chat_app.stream_turn(state, "s", "hi", events.append)
        finally:
            gta5_agent.run_agent = original
            chat_store.close()
        return state, events

    def test_speech_failure_still_ends_turn(self) -> None:
        pipe = self.FakePipeline()
        pipe.finish = lambda: (_ for _ in ()).throw(OSError("audio device lost"))
        state, events = self._turn_with_pipeline(pipe)
        self.assertEqual(events[-1], {"event": "speech_end", "status": "error"})
        self.assertTrue(any("audio device lost" in e.get("text", "") for e in events if e["event"] == "error"))
        self.assertIsNone(state.pipeline)

    def test_stuck_speech_is_aborted_after_timeout(self) -> None:
        import chat_app

        pipe = self.FakePipeline()
        pipe.finish = lambda: time.sleep(5)
        old = chat_app.SPEECH_FINISH_TIMEOUT
        chat_app.SPEECH_FINISH_TIMEOUT = 0.2
        try:
            started = time.monotonic()
            _state, events = self._turn_with_pipeline(pipe)
        finally:
            chat_app.SPEECH_FINISH_TIMEOUT = old
        self.assertLess(time.monotonic() - started, 2)
        self.assertTrue(pipe.aborted)
        self.assertEqual(events[-1], {"event": "speech_end", "status": "timeout"})

    def test_speech_off_and_model_error_still_end_turn(self) -> None:
        _s, events = self._turn_with_pipeline(self.FakePipeline(), speak=False)
        self.assertEqual(events[-1], {"event": "speech_end", "status": "skipped"})
        import chat_app

        state = chat_app.AppState("m")
        original = gta5_agent.run_agent

        def boom(*a, **k):
            raise RuntimeError("quota")

        gta5_agent.run_agent = boom
        events = []
        try:
            chat_app.stream_turn(state, "s", "hi", events.append)
        finally:
            gta5_agent.run_agent = original
        self.assertEqual(events[-1]["event"], "speech_end")
        self.assertIn("error", [e["event"] for e in events])

    def test_listen_classifies_silence_and_releases_mic_on_every_path(self) -> None:
        import chat_app
        import wake_word

        state = chat_app.AppState("m")
        original = gta5_agent.listen_to_microphone
        pauses = []
        orig_pause, orig_resume = wake_word.pause_wake_listener, wake_word.resume_wake_listener
        wake_word.pause_wake_listener = lambda: pauses.append("pause")
        wake_word.resume_wake_listener = lambda: pauses.append("resume")
        try:
            gta5_agent.listen_to_microphone = lambda **kw: {"ok": False, "error": "No speech heard. Try again."}
            self.assertEqual(chat_app.listen_once(state)["kind"], "silence")
            gta5_agent.listen_to_microphone = lambda **kw: {"ok": False, "error": "Microphone access failed: [Errno -9999]"}
            failed = chat_app.listen_once(state)
            self.assertEqual(failed["kind"], "error")
            self.assertIn("Errno", failed["error"])

            def crash(**kw):
                raise OSError("stream closed")

            gta5_agent.listen_to_microphone = crash
            crashed = chat_app.listen_once(state)
            self.assertEqual(crashed["kind"], "error")
            self.assertTrue(state.mic_lock.acquire(blocking=False), "mic lock released")
            state.mic_lock.release()
            self.assertEqual(pauses, ["pause", "resume"] * 3)
        finally:
            gta5_agent.listen_to_microphone = original
            wake_word.pause_wake_listener, wake_word.resume_wake_listener = orig_pause, orig_resume

    def test_handsfree_js_logic(self) -> None:
        import shutil
        import subprocess

        node = shutil.which("node")
        if not node:
            self.skipTest("node is not installed")
        script = Path(__file__).resolve().parent / "test_handsfree.js"
        done = subprocess.run([node, str(script)], capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)

    def test_auto_speak_default_comes_from_rules(self) -> None:
        import chat_app

        self.write_rules({"voice": {"auto_speak": True}})
        self.assertTrue(chat_app.AppState("m").speak)


class TelegramBridgeTests(_RulesCase):
    def setUp(self) -> None:
        super().setUp()
        import remote_bridge

        self.rb = remote_bridge
        remote_bridge.reset_remote_bridge()
        self.sent = []
        self.updates = []
        self.saved_env = {k: os.environ.get(k) for k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")}
        os.environ["TELEGRAM_BOT_TOKEN"] = "123456:test-token"
        os.environ["TELEGRAM_CHAT_ID"] = "42"
        self.saved_transport = gta5_agent.remote_transport_override
        self.saved_reply = gta5_agent.remote_reply_override
        gta5_agent.remote_reply_override = None

        def transport(kind, payload):
            if kind == "telegram_updates":
                batch, self.updates[:] = list(self.updates), []
                return {"ok": True, "result": batch}
            if kind == "telegram_send":
                self.sent.append(payload["body"]["text"])
            return {"ok": True}

        gta5_agent.remote_transport_override = transport

    def tearDown(self) -> None:
        import chat_app
        import chat_store

        chat_app.detach_telegram()
        self.rb.reset_remote_bridge()
        gta5_agent.remote_transport_override = self.saved_transport
        gta5_agent.remote_reply_override = self.saved_reply
        for k, v in self.saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        chat_store.close()
        super().tearDown()

    def message(self, text, chat=42):
        self.updates.append({"update_id": len(self.sent) + 100 + len(self.updates),
                             "message": {"message_id": 1, "chat": {"id": chat}, "text": text}})

    def test_app_routes_telegram_into_shared_history(self) -> None:
        import chat_app
        import chat_store

        state = chat_app.AppState("m")
        original = gta5_agent.run_agent
        seen_histories = []

        def fake_run(text, history, model, **kw):
            seen_histories.append(len(history))
            return f"echo: {text}"

        gta5_agent.run_agent = fake_run
        try:
            chat_app.attach_telegram(state)
            self.assertTrue(self.rb.bridge_running())
            self.rb.stop_remote_bridge()  # poll by hand below
            self.message("hello")
            self.message("spam", chat=99)  # other chats ignored
            self.rb.poll_once()
        finally:
            gta5_agent.run_agent = original
        self.assertEqual(self.sent, ["echo: hello"])
        rows = chat_store.history(chat_app.TELEGRAM_SESSION)
        self.assertEqual([r["text"] for r in rows], ["hello", "echo: hello"])

    def test_only_one_bridge_polls(self) -> None:
        self.rb.start_remote_bridge()
        self.assertTrue(self.rb.bridge_running())
        import subprocess

        code = (
            "import sys,os; sys.path.insert(0, %r); import remote_bridge; "
            "print('locked' if not remote_bridge._acquire_instance_lock() else 'free')"
        ) % str(Path(rules.APP_DIR))
        env = dict(os.environ)
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, timeout=30)
        self.assertIn("locked", out.stdout, out.stderr)
        self.rb.stop_remote_bridge()
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, timeout=30)
        self.assertIn("free", out.stdout, out.stderr)

    def test_409_conflict_is_reported_not_raised(self) -> None:
        def conflict(kind, payload):
            raise RuntimeError("HTTP Error 409: Conflict")

        gta5_agent.remote_transport_override = conflict
        result = self.rb.poll_once()
        self.assertFalse(result["ok"])
        self.assertTrue(result.get("conflict"))

    def test_confirm_yes_no_over_telegram(self) -> None:
        import confirm_action

        self.write_rules({"paths": {"allowed": [str(self.root)]}})
        target = self.root / "old.txt"
        target.write_text("x")

        def reply(text):
            return gta5_agent.invoke_tool("delete_path", {"path": str(target)}).get("error", "")

        gta5_agent.remote_reply_override = reply
        self.message("delete old.txt")
        self.rb.poll_once()
        self.assertIn("Reply yes", self.sent[-1])
        self.assertIsNotNone(confirm_action.pending())
        self.message("no")
        self.rb.poll_once()
        self.assertTrue(self.sent[-1].startswith("Cancelled"))
        self.assertTrue(target.exists())
        self.message("delete old.txt")
        self.rb.poll_once()
        self.message("yes")
        self.rb.poll_once()
        self.assertTrue(self.sent[-1].startswith("Done"), self.sent[-1])
        self.assertFalse(target.exists())


class NewUiTests(_RulesCase):
    STATIC = Path(rules.APP_DIR) / "app_static"

    def test_static_assets_have_no_external_urls(self) -> None:
        import re

        for f in self.STATIC.iterdir():
            if f.suffix in {".png", ".ico"}:
                continue
            text = f.read_text(encoding="utf-8")
            self.assertIsNone(re.search(r'(src|href)\s*=\s*["\']https?://', text), f.name)
            self.assertIsNone(re.search(r'@import\s+url\(\s*["\']?https?:|fetch\(\s*["\']https?:', text), f.name)

    def test_ui_js_logic(self) -> None:
        import shutil
        import subprocess

        node = shutil.which("node")
        if not node:
            self.skipTest("node is not installed")
        done = subprocess.run([node, str(Path(__file__).resolve().parent / "test_ui.js")],
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)

    def test_server_serves_assets_status_and_safe_images(self) -> None:
        import chat_app

        server, _state = chat_app.serve("m", port=0)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{server.server_address[1]}"
        try:
            for name in chat_app.STATIC_FILES:
                body = urllib.request.urlopen(base + "/" + name, timeout=5).read()
                self.assertTrue(body)
            page = urllib.request.urlopen(base + "/", timeout=5).read().decode()
            for name in ("app.js", "app.css", "markdown.js", "avatar.js", "handsfree.js"):
                self.assertIn(name, page)
            status = json.loads(urllib.request.urlopen(base + "/api/status", timeout=5).read())
            for key in ("busy", "listening", "speaking", "telegram", "model"):
                self.assertIn(key, status)
            shots = Path(os.environ["STORAGE_DIR"]) / "screenshots"
            shots.mkdir(parents=True, exist_ok=True)
            from PIL import Image

            Image.new("RGB", (4, 4)).save(shots / "latest.png")
            ok = urllib.request.urlopen(base + "/api/image?path=" + str(shots / "latest.png"), timeout=5)
            self.assertEqual(ok.headers["Content-Type"], "image/png")
            outside = self.root / "secret.png"
            Image.new("RGB", (4, 4)).save(outside)
            with self.assertRaises(urllib.error.HTTPError):
                urllib.request.urlopen(base + "/api/image?path=" + str(outside), timeout=5)
            with self.assertRaises(urllib.error.HTTPError):
                urllib.request.urlopen(base + "/../rules.py", timeout=5)
        finally:
            chat_app.shutdown(server)

    def test_tool_end_carries_image_for_preview(self) -> None:
        self.assertEqual(gta5_agent._result_image({"path": "C:/x/latest.jpg"}), "C:/x/latest.jpg")
        self.assertIsNone(gta5_agent._result_image({"path": "C:/x/notes.txt"}))

    def test_piracy_commit_message_refused_with_default_rules(self) -> None:
        import git_manager

        self.assertIn("crack", git_manager._message_problem(gta5_agent, "add the fitgirl repack"))
        self.assertIsNone(git_manager._message_problem(gta5_agent, "fix the timer"))


if __name__ == "__main__":
    unittest.main()
