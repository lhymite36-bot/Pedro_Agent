"""Stage 2 tests: TTS mouth sync, team, demonstration skills, code loop,
autopilot, live voice fallback, self-upgrade. No network, no Gemini."""

from __future__ import annotations

import json
import math
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["PEDRO_AGENT_NO_FILE_LOG"] = "1"

import rules  # noqa: E402


class _Tmp(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(os.path.realpath(self.tmp.name))
        self.rules_file = self.root / "rules.json"
        self.rules_file.write_text("{}", encoding="utf-8")
        self._env = {k: os.environ.get(k) for k in ("RULES_FILE", "STORAGE_DIR")}
        os.environ["RULES_FILE"] = str(self.rules_file)
        os.environ["STORAGE_DIR"] = str(self.root / "storage")
        rules.reset_cache()

    def tearDown(self) -> None:
        for key, value in self._env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        rules.reset_cache()
        self.tmp.cleanup()

    def write_rules(self, data: dict) -> None:
        self.rules_file.write_text(json.dumps(data), encoding="utf-8")
        rules.reset_cache()


class SpeechLevelTests(unittest.TestCase):
    def test_envelope_follows_loudness(self) -> None:
        import speech_level

        rate = 1000
        quiet = [0] * 40
        loud = [int(20000 * math.sin(i)) for i in range(40)]
        env = speech_level.envelope_from_samples(quiet + loud + quiet, rate, 1)
        self.assertEqual(len(env), 3)
        self.assertEqual(env[0], 0.0)
        self.assertGreater(env[1], 0.9)

    def test_update_and_stop(self) -> None:
        import speech_level

        speech_level.start([0.1, 0.8])
        self.assertEqual(speech_level.update(0), 0.1)
        self.assertEqual(speech_level.update(speech_level.WINDOW_MS + 1), 0.8)
        self.assertEqual(speech_level.current(), 0.8)
        self.assertEqual(speech_level.update(10_000), 0.0)
        speech_level.stop()
        self.assertIsNone(speech_level.current())

    def test_raw_bytes_and_chat_level_payload(self) -> None:
        import array
        import chat_app
        import speech_level

        raw = array.array("h", [1000, -1000] * 100).tobytes()
        self.assertTrue(speech_level.envelope_from_raw(raw, 1000, 2))
        speech_level.start([0.5])
        speech_level.update(0)
        self.assertEqual(chat_app.level_payload(), {"level": 0.5})
        speech_level.stop()
        self.assertEqual(chat_app.level_payload(), {"level": None})

    def test_pygame_playback_drives_level(self) -> None:
        import inspect
        import gta5_agent

        src = inspect.getsource(gta5_agent._play_mp3_pygame)
        self.assertIn("speech_level.update", src)
        self.assertIn("speech_level.stop", src)
        js = (Path(__file__).resolve().parents[1] / "app_static" / "app.js").read_text(encoding="utf-8")
        self.assertIn("/api/level", js)


class TeamTests(_Tmp):
    def setUp(self) -> None:
        super().setUp()
        import llm
        import team_agent

        self.llm, self.team = llm, team_agent
        self.addCleanup(setattr, llm, "override", None)
        self.addCleanup(setattr, team_agent, "runner", None)

    def test_plan_parallel_run_and_review_redo(self) -> None:
        replies = iter([
            '```json\n[{"role":"research","task":"find X"},{"role":"coder","task":"write Y"},{"role":"hacker","task":"z"}]\n```',
            '{"ok": false, "summary": "", "redo": [{"index": 1, "task": "write Y with tests"}]}',
            '{"ok": true, "summary": "All done", "redo": []}',
        ])
        self.llm.override = lambda prompt, images: next(replies)
        seen, threads = [], set()

        def fake(role, task, tools):
            seen.append((role, task))
            threads.add(threading.current_thread().name)
            self.assertNotIn("run_team", tools)
            return f"{role} did {task}"

        self.team.runner = fake
        result = self.team.run_team("make a tool")
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["message"], "All done")
        self.assertTrue(result["approved"])
        self.assertEqual([s["role"] for s in result["steps"]], ["research", "coder"])
        self.assertIn(("coder", "write Y with tests"), seen)
        self.assertTrue(any(name.startswith("team") for name in threads))

    def test_role_tools_respect_rules_and_scope(self) -> None:
        import gta5_agent

        self.write_rules({"tools": {"blocked": ["open_website"]}})
        self.assertNotIn("open_website", self.team.tools_for("browser"))
        gta5_agent.set_tool_scope({"recall_memory"})
        try:
            blocked = gta5_agent.invoke_tool("open_website", {"url": "https://example.com"})
        finally:
            gta5_agent.set_tool_scope(None)
        self.assertTrue(blocked.get("blocked_by_scope"))
        self.assertIn("run_team", gta5_agent.TOOLS)
        self.assertIn("run_team", [d["name"] for d in gta5_agent.TOOL_DECLARATIONS])

    def test_bad_plan_falls_back_to_research(self) -> None:
        self.llm.override = lambda prompt, images: "no json here"
        self.team.runner = lambda role, task, tools: "ok"
        self.write_rules({"team": {"review": False}})
        result = self.team.run_team("look up the weather")
        self.assertEqual(result["steps"][0]["role"], "research")
        self.assertFalse(result["reviewed"])

    def test_unattended_sensitive_action_waits(self) -> None:
        import confirm_action
        import gta5_agent

        confirm_action.reset()
        gta5_agent.set_unattended(True)
        try:
            out = gta5_agent.invoke_tool("shutdown_computer", {})
        finally:
            gta5_agent.set_unattended(False)
        self.assertTrue(out.get("needs_confirmation"), out)
        self.assertIsNotNone(confirm_action.pending())
        confirm_action.reset()


class BotTests(_Tmp):
    def setUp(self) -> None:
        super().setUp()
        import bots
        import chat_store

        self.bots, self.store = bots, chat_store
        os.environ["BOTS_DIR"] = str(self.root / "bots")
        self.addCleanup(os.environ.pop, "BOTS_DIR", None)
        self.addCleanup(setattr, bots, "engine", None)
        self.addCleanup(chat_store.close)
        self.calls = []

        def fake_engine(prompt, history, model, **kw):
            import gta5_agent

            self.calls.append({"prompt": prompt, "model": model,
                               "scope": getattr(gta5_agent._tool_scope, "allowed", None),
                               "unattended": gta5_agent._unattended(),
                               "blocked": rules.tool_block_reason("open_website")})
            return "bot reply"

        bots.engine = fake_engine

    def _make(self, **extra):
        data = {"name": "Inbox Helper", "color": "#ff0000", "role": "Sort email.",
                "tools": "recall_memory, open_website", "tasks": [{"text": "check mail", "schedule": {"every_minutes": 5}},
                                                                   {"text": "one off"}]}
        data.update(extra)
        return self.bots.save_bot(data)

    def test_crud_persists_to_json(self) -> None:
        bot = self._make()
        self.assertEqual(bot["id"], "inbox-helper")
        self.assertTrue((self.root / "bots" / "inbox-helper.json").is_file())
        self.assertEqual(bot["tools"], ["open_website", "recall_memory"])
        self.assertIsNone(bot["tasks"][1]["schedule"])
        twin = self._make()
        self.assertEqual(twin["id"], "inbox-helper-2")
        bot["role"] = "Changed"
        self.bots.save_bot(bot)
        self.assertEqual(self.bots.get_bot("Inbox Helper")["role"], "Changed")
        self.assertEqual(len(self.bots.list_bots()), 2)
        self.assertTrue(self.bots.delete_bot("inbox-helper-2"))
        self.assertFalse(self.bots.delete_bot("inbox-helper-2"))
        with self.assertRaises(ValueError):
            self.bots.save_bot({"name": "  "})
        self.assertEqual(self.bots.save_bot({"name": "x", "color": "red"})["color"], "#7c5cff")

    def test_run_uses_scope_rules_override_and_role(self) -> None:
        import gta5_agent

        bot = self._make(rules={"tools": {"blocked": ["open_website"]}}, model="gemini-x")
        reply = self.bots.run_bot(bot, "hi", [])
        self.assertEqual(reply, "bot reply")
        call = self.calls[-1]
        self.assertIn("Sort email.", call["prompt"])
        self.assertEqual(call["model"], "gemini-x")
        self.assertEqual(call["scope"], {"recall_memory", "open_website"})
        self.assertIsNotNone(call["blocked"])  # per-bot override applied in its thread
        self.assertIsNone(rules.tool_block_reason("open_website"))  # and only there
        self.assertIsNone(getattr(gta5_agent._tool_scope, "allowed", None))
        open_bot = self.bots.save_bot({"name": "Any"})
        self.bots.run_bot(open_bot, "x")
        self.assertNotIn("ask_bot", self.calls[-1]["scope"])
        self.assertIn("recall_memory", self.calls[-1]["scope"])

    def test_scheduled_tasks_and_thread_history(self) -> None:
        bot = self._make()
        now = 10_000_000.0
        results = self.bots.run_due_tasks(now)
        self.assertEqual(len(results), 1)  # the one-off task does not auto-run
        self.assertTrue(self.calls[-1]["unattended"])
        self.assertEqual(self.bots.run_due_tasks(now + 60), [])
        self.assertGreater(self.bots.get_bot(bot["id"])["tasks"][0]["last_run"], 0)
        rows = self.store.history("bot-inbox-helper")
        self.assertEqual([r["role"] for r in rows][:2], ["user", "assistant"])

    def test_daily_due(self) -> None:
        import time as _time

        lt = _time.localtime()
        target = _time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 8, 0, 0, 0, 0, -1))
        task = {"enabled": True, "schedule": {"daily": "08:00"}, "last_run": 0}
        self.assertTrue(self.bots._due(task, target + 5))
        self.assertFalse(self.bots._due(task, target - 5))
        task["last_run"] = target + 1
        self.assertFalse(self.bots._due(task, target + 60))

    def test_main_agent_delegates_with_ask_bot(self) -> None:
        import gta5_agent

        self._make()
        out = gta5_agent.invoke_tool("ask_bot", {"name": "inbox helper", "task": "sort"})
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["message"], "bot reply")
        self.assertFalse(gta5_agent.invoke_tool("ask_bot", {"name": "ghost", "task": "x"})["ok"])
        self.assertIn("list_bots", gta5_agent.TOOLS)

    def test_chat_app_bot_api_and_thread_routing(self) -> None:
        import urllib.request
        import chat_app

        server, state = chat_app.serve("m", 0)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{server.server_address[1]}"
        try:
            def post(path, body):
                req = urllib.request.Request(base + path, json.dumps(body).encode(),
                                             {"Content-Type": "application/json", "Origin": base})
                return json.loads(urllib.request.urlopen(req, timeout=5).read())

            made = post("/api/bots", {"name": "Coder", "role": "Write code"})
            self.assertTrue(made["ok"])
            self.assertEqual(made["session"], "bot-coder")
            listed = json.loads(urllib.request.urlopen(base + "/api/bots", timeout=5).read())
            self.assertEqual(listed["bots"][0]["name"], "Coder")
            self.assertIn("ask_bot", listed["tools"])
            self.assertEqual(urllib.request.urlopen(base + "/bots_ui.js", timeout=5).status, 200)
            events = []
            chat_app.stream_turn(state, "bot-coder", "hello", events.append, speak=False)
            self.assertIn("Write code", self.calls[-1]["prompt"])
            self.assertEqual(events[-2]["text"], "bot reply")
            self.assertTrue(post("/api/bots/delete", {"id": "coder", "confirm": True})["ok"])
            self.assertEqual(self.bots.list_bots(), [])
        finally:
            chat_app.shutdown(server)


class CodeLoopTests(_Tmp):
    def setUp(self) -> None:
        super().setUp()
        import code_loop
        import llm

        self.cl, self.llm = code_loop, llm
        self.addCleanup(setattr, llm, "override", None)
        self.addCleanup(setattr, code_loop, "test_runner", None)
        self.proj = self.root / "proj"
        self.proj.mkdir()

    def test_loops_until_tests_pass_and_feeds_back_output(self) -> None:
        prompts = []
        replies = iter([
            '{"files": {"calc.py": "def add(a, b):\\n    return a - b\\n"}, "message": "add"}',
            '{"files": {"calc.py": "def add(a, b):\\n    return a + b\\n", "../evil.py": "x"}, "message": "fix add"}',
        ])
        self.llm.override = lambda p, i: (prompts.append(p), next(replies))[1]
        runs = []

        def runner(cmd, cwd, timeout):
            runs.append(cmd)
            body = (cwd / "calc.py").read_text()
            return (0, "1 passed") if "a + b" in body else (1, "AssertionError: add(1,1) == 0")

        self.cl.test_runner = runner
        out = self.cl.code_engineer("make add work", str(self.proj), "python -m pytest -q")
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["rounds"], 2)
        self.assertIn("AssertionError", prompts[1])
        self.assertTrue(out["log"][1]["refused"])
        self.assertFalse((self.root / "evil.py").exists())
        self.assertEqual(runs[0], ["python", "-m", "pytest", "-q"])
        self.assertIn("not committed", out["log"][1]["git"])

    def test_cap_and_bad_json(self) -> None:
        self.llm.override = lambda p, i: "sorry"
        self.cl.test_runner = lambda c, w, t: (1, "fail")
        out = self.cl.code_engineer("x", str(self.proj), max_iterations=2)
        self.assertFalse(out["ok"])
        self.assertEqual(out["rounds"], 2)

    def test_rules_block_writes(self) -> None:
        self.write_rules({"files": {"blocked_extensions": [".py"]}})
        self.llm.override = lambda p, i: '{"files": {"a.py": "x"}}'
        self.cl.test_runner = lambda c, w, t: (1, "fail")
        out = self.cl.code_engineer("x", str(self.proj), max_iterations=1)
        self.assertFalse((self.proj / "a.py").exists())
        self.assertTrue(out["log"][0]["refused"])

    def test_commits_in_git_repo(self) -> None:
        import gta5_agent

        (self.proj / ".git").mkdir()
        calls = []
        saved = gta5_agent.git_runner_override
        gta5_agent.git_runner_override = lambda cmd, cwd: (calls.append(cmd), {"returncode": 0, "stdout": " M a.py\n" if "status" in cmd else "", "stderr": ""})[1]
        self.addCleanup(setattr, gta5_agent, "git_runner_override", saved)
        self.llm.override = lambda p, i: '{"files": {"a.py": "x=1"}, "message": "add a"}'
        self.cl.test_runner = lambda c, w, t: (0, "ok")
        out = self.cl.code_engineer("x", str(self.proj))
        self.assertTrue(out["ok"], out)
        self.assertIn(["git", "commit", "-m", "add a"], calls)


class AutopilotTests(_Tmp):
    def setUp(self) -> None:
        super().setUp()
        import autopilot

        self.ap = autopilot
        self.cfg = self.root / "autopilot.yaml"
        os.environ["AUTOPILOT_FILE"] = str(self.cfg)
        self.addCleanup(os.environ.pop, "AUTOPILOT_FILE", None)
        for name in ("runner", "fetcher", "mail_reader", "notifier"):
            self.addCleanup(setattr, autopilot, name, None)
        self.fired, self.sent = [], []
        autopilot.runner = lambda w, prompt: (self.fired.append((w["name"], prompt)), "done")[1]
        autopilot.notifier = self.sent.append
        self.inbox = self.root / "inbox"
        self.inbox.mkdir()

    def write(self, watchers, **extra):
        data = {"enabled": True, "notify": True, "watchers": watchers, **extra}
        self.cfg.write_text(json.dumps(data), encoding="utf-8")  # JSON is valid YAML

    def test_folder_baseline_then_new_file_fires(self) -> None:
        (self.inbox / "old.pdf").write_text("x")
        self.write([{"name": "pdfs", "type": "folder", "path": str(self.inbox), "pattern": "*.pdf",
                     "prompt": "New file {name}"}])
        pilot = self.ap.Autopilot()
        self.assertEqual(pilot.check_once(), [])
        (self.inbox / "new.pdf").write_text("x")
        (self.inbox / "skip.txt").write_text("x")
        self.assertEqual(pilot.check_once(), ["done"])
        self.assertIn("New file new.pdf", self.fired[0][1])
        self.assertIn("pdfs: done", self.sent[0])
        self.assertEqual(pilot.check_once(), [])

    def test_url_contains_and_change(self) -> None:
        pages = iter(["<p>Sold out</p>", "<p>In stock now</p>", "<p>In stock now</p>"])
        self.ap.fetcher = lambda url: next(pages)
        self.write([{"name": "price", "type": "url", "url": "https://x.test", "contains": "in stock", "prompt": "{url}"}])
        pilot = self.ap.Autopilot()
        pilot.check_once()
        self.assertEqual(len(pilot.check_once()), 1)
        self.assertEqual(pilot.check_once(), [])

    def test_gmail_filters_and_only_new(self) -> None:
        batches = iter([
            [{"uid": "1", "from": "Boss <boss@x.com>", "subject": "Hi", "snippet": "a"}],
            [{"uid": "1", "from": "Boss <boss@x.com>", "subject": "Hi", "snippet": "a"},
             {"uid": "2", "from": "Boss <boss@x.com>", "subject": "Report", "snippet": "b"},
             {"uid": "3", "from": "spam@y.com", "subject": "Win", "snippet": "c"}],
        ])
        self.ap.mail_reader = lambda w: next(batches)
        self.write([{"name": "boss", "type": "gmail", "from": "boss@x.com", "prompt": "{subject}"}])
        pilot = self.ap.Autopilot()
        pilot.check_once()
        pilot.check_once()
        self.assertEqual([p for _n, p in self.fired], ["[Autopilot trigger: boss] Report"])

    def test_telegram_listener_and_errors_logged(self) -> None:
        import remote_bridge

        self.write([{"name": "backup", "type": "telegram", "match": "^run backup", "prompt": "go {text}"},
                    {"name": "broken", "type": "url", "url": "ftp://nope", "prompt": "x"}])
        pilot = self.ap.Autopilot()
        self.assertEqual(pilot.on_telegram("hello"), [])
        self.assertEqual(pilot.on_telegram("Run backup please"), ["done"])
        pilot.check_once()
        self.assertIn("error", pilot.log[-1])
        self.ap._register_telegram(pilot)
        try:
            self.assertEqual(len(remote_bridge.message_listeners), 1)
        finally:
            self.ap._register_telegram(None)
        self.assertEqual(remote_bridge.message_listeners, [])

    def test_disabled_start_refused_and_default_runner_is_unattended(self) -> None:
        import inspect

        self.write([], enabled=False)
        self.assertFalse(self.ap.autopilot_control("start")["ok"])
        self.assertIn("set_unattended(True)", inspect.getsource(self.ap._default_runner))
        self.assertIn("autopilot_control", __import__("gta5_agent").TOOLS)


class LiveVoiceTests(_Tmp):
    def test_falls_back_without_key(self) -> None:
        import live_voice

        saved = os.environ.pop("GEMINI_API_KEY", None)
        try:
            out = live_voice.run()
        finally:
            if saved is not None:
                os.environ["GEMINI_API_KEY"] = saved
        self.assertTrue(out["fallback"])
        self.assertFalse(out["ok"])

    def test_barge_in_clears_audio_and_tools_go_through_invoke(self) -> None:
        import live_voice
        from types import SimpleNamespace as NS

        pb = live_voice.Playback()
        texts, tools = [], []
        audio = NS(server_content=NS(interrupted=False, model_turn=NS(parts=[NS(inline_data=NS(data=b"\x00\x10" * 50))]),
                                     input_transcription=NS(text="open notepad"), output_transcription=None), tool_call=None)
        live_voice.handle_message(audio, pb, on_text=lambda r, t: texts.append((r, t)))
        live_voice.handle_message(audio, pb)
        self.assertEqual(pb.q.qsize(), 2)
        self.assertEqual(texts, [("user", "open notepad")])
        stop = NS(server_content=NS(interrupted=True, model_turn=None, input_transcription=None, output_transcription=None),
                  tool_call=None)
        live_voice.handle_message(stop, pb)
        self.assertEqual(pb.q.qsize(), 0)
        call = NS(server_content=None, tool_call=NS(function_calls=[NS(id="7", name="recall_memory", args={"query": "x"})]))
        out = live_voice.handle_message(call, pb, run_tool=lambda n, a: (tools.append((n, a)), {"ok": True, "obj": object()})[1])
        self.assertEqual(tools, [("recall_memory", {"query": "x"})])
        self.assertEqual(out, [{"id": "7", "name": "recall_memory", "response": {"ok": True}}])

    def test_frame_and_level(self) -> None:
        import array
        import live_voice

        self.assertEqual(live_voice.pcm_level(b""), 0.0)
        loud = array.array("h", [12000, -12000] * 500).tobytes()
        self.assertEqual(live_voice.pcm_level(loud), 1.0)
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow not installed")
        jpg = live_voice.encode_frame(Image.new("RGB", (2048, 1000)), 1024)
        self.assertEqual(jpg[:2], b"\xff\xd8")
        self.assertEqual(Image.open(__import__("io").BytesIO(jpg)).width, 1024)

    def test_cli_flag(self) -> None:
        import gta5_agent

        self.assertTrue(gta5_agent._parser().parse_args(["--live"]).live)


class SelfUpgradeTests(_Tmp):
    def setUp(self) -> None:
        super().setUp()
        import gta5_agent
        import llm
        import self_upgrade

        self.su, self.llm, self.agent = self_upgrade, llm, gta5_agent
        self.app = self.root / "app"
        self.app.mkdir()
        (self.app / "flaky.py").write_text("def flaky_tool():\n    raise ValueError('boom')\n", encoding="utf-8")
        (self.app / ".env").write_text("GEMINI_API_KEY=secret\n")
        os.environ["UPGRADE_APP_DIR"] = str(self.app)
        self.addCleanup(os.environ.pop, "UPGRADE_APP_DIR", None)
        sys.path.insert(0, str(self.app))
        self.addCleanup(sys.path.remove, str(self.app))
        import importlib

        flaky = importlib.import_module("flaky")
        gta5_agent.TOOLS["flaky_tool"] = flaky.flaky_tool
        self.addCleanup(gta5_agent.TOOLS.pop, "flaky_tool", None)
        self.addCleanup(sys.modules.pop, "flaky", None)
        self.addCleanup(setattr, llm, "override", None)
        self.addCleanup(setattr, self_upgrade, "test_runner", None)
        logs = self.root / "storage" / "logs"
        logs.mkdir(parents=True)
        rows = [{"event": "tool_error", "tool": "flaky_tool", "error": "flaky_tool failed: boom"}] * 3
        rows.append({"event": "tool", "tool": "recall_memory", "ok": True})
        (logs / "agent.jsonl").write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
        self.llm.override = lambda p, i: "```python\ndef flaky_tool():\n    return {'ok': True, 'message': 'fixed'}\n```"

    def test_report_propose_apply_rollback(self) -> None:
        report = self.su.failure_report()
        self.assertEqual(report["failures"][0], {"tool": "flaky_tool", "failures": 3, "errors": ["flaky_tool failed: boom"]})
        seen = {}

        def runner(cmd, cwd, timeout):
            seen["cwd"] = cwd
            seen["copied"] = (cwd / "flaky.py").read_text()
            seen["env_copied"] = (cwd / ".env").exists()
            return 0, "5 passed"

        self.su.test_runner = runner
        prop = self.su.propose_upgrade()
        self.assertTrue(prop["tests_passed"], prop)
        self.assertIn("fixed", seen["copied"])
        self.assertFalse(seen["env_copied"])
        self.assertNotEqual(seen["cwd"], self.app)
        self.assertIn("raise ValueError", (self.app / "flaky.py").read_text())  # live file untouched
        self.assertIn("+    return", prop["diff"])
        refused = self.su.apply_upgrade(prop["id"])
        self.assertTrue(refused["needs_confirmation"])
        applied = self.su.apply_upgrade(prop["id"], confirm="yes")
        self.assertTrue(applied["ok"], applied)
        self.assertIn("fixed", (self.app / "flaky.py").read_text())
        self.assertFalse(self.su.apply_upgrade(prop["id"], confirm="yes")["ok"])
        self.assertTrue(self.su.rollback_upgrade(prop["id"])["ok"])
        self.assertIn("raise ValueError", (self.app / "flaky.py").read_text())
        self.assertEqual(self.su.list_upgrades()["upgrades"][0]["status"], "rolled_back")

    def test_failed_tests_block_apply(self) -> None:
        self.su.test_runner = lambda c, w, t: (1, "1 failed")
        prop = self.su.propose_upgrade("flaky_tool")
        self.assertFalse(prop["tests_passed"])
        self.assertFalse(self.su.apply_upgrade(prop["id"], confirm="yes")["ok"])

    def test_tool_apply_needs_confirm_category(self) -> None:
        import confirm_action

        confirm_action.reset()
        self.assertTrue(rules.needs_confirmation("self_upgrade", {"action": "apply"}))
        self.assertFalse(rules.needs_confirmation("self_upgrade", {"action": "report"}))
        out = self.agent.invoke_tool("self_upgrade", {"action": "apply", "upgrade_id": "x", "confirm": "yes"})
        self.assertTrue(out.get("needs_confirmation"), out)
        confirm_action.reset()


class RemoteAccessTests(_Tmp):
    def setUp(self) -> None:
        super().setUp()
        import live_pc
        import remote_access

        self.ra, self.lp = remote_access, live_pc
        remote_access.reset_state()
        self.addCleanup(remote_access.reset_state)
        self.addCleanup(remote_access.stop)
        self.addCleanup(setattr, live_pc, "grabber", None)
        live_pc.grabber = lambda: b"\xff\xd8jpegdata\xff\xd9"

    def _start(self, **remote):
        import chat_app

        self.write_rules({"remote": {"enabled": True, "port": 0, **remote}})
        state = chat_app.AppState("m")
        info = self.ra.start(state)
        self.assertTrue(info["ok"], info)
        return info["local_url"].rstrip("/")

    def _req(self, base, path, body=None, cookie="", origin=True):
        import urllib.error
        import urllib.request

        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **k):
                return None

        headers = {"Content-Type": "application/json"}
        if cookie:
            headers["Cookie"] = cookie
        if origin and body is not None:
            headers["Origin"] = base
        data = json.dumps(body).encode() if body is not None else None
        opener = urllib.request.build_opener(NoRedirect)
        try:
            resp = opener.open(urllib.request.Request(base + path, data, headers), timeout=5)
            return resp.status, dict(resp.headers), resp.read()
        except urllib.error.HTTPError as exc:
            return exc.code, dict(exc.headers), exc.read()

    def test_off_by_default(self) -> None:
        import chat_app

        self.assertFalse(self.ra.settings()["enabled"])
        self.assertFalse(self.ra.start(chat_app.AppState("m"))["ok"])
        self.assertFalse(self.ra.settings()["allow_control"])

    def test_token_is_long_random_and_persisted(self) -> None:
        token = self.ra.access_token()
        self.assertGreaterEqual(len(token), 40)
        self.assertEqual(self.ra.access_token(), token)
        self.assertNotEqual(self.ra.rotate_token(), token)

    def test_everything_needs_sign_in(self) -> None:
        base = self._start()
        for path in ("/api/status", "/api/sessions", "/api/bots", "/live/frame.jpg", "/live/activity",
                     "/live/stream.mjpg", "/app.js", "/api/history?session=x", "/api/rules"):
            code, _h, _b = self._req(base, path)
            self.assertEqual(code, 401, path)
        code, headers, _b = self._req(base, "/")
        self.assertEqual((code, headers.get("Location")), (302, "/login"))
        self.assertEqual(self._req(base, "/api/chat", {"text": "hi"})[0], 401)
        self.assertEqual(self._req(base, "/login")[0], 200)
        self.assertEqual(self._req(base, "/manifest.webmanifest")[0], 200)

    def test_login_cookie_then_view_only(self) -> None:
        base = self._start()
        code, _h, body = self._req(base, "/login", {"secret": "wrong"})
        self.assertEqual(code, 401)
        code, headers, _b = self._req(base, "/login", {"secret": self.ra.access_token()})
        self.assertEqual(code, 200)
        cookie_hdr = headers["Set-Cookie"]
        self.assertIn("HttpOnly", cookie_hdr)
        self.assertIn("SameSite=Strict", cookie_hdr)
        cookie = cookie_hdr.split(";")[0]
        self.assertEqual(self._req(base, "/api/status", cookie=cookie)[0], 200)
        code, headers, frame = self._req(base, "/live/frame.jpg", cookie=cookie)
        self.assertEqual((code, headers["Content-Type"], frame[:2]), (200, "image/jpeg", b"\xff\xd8"))
        act = json.loads(self._req(base, "/live/activity", cookie=cookie)[2])
        self.assertTrue(act["remote"])
        self.assertFalse(act["control"])
        self.assertTrue(any("signed in" in a["text"] for a in act["items"]))
        self.assertEqual(self._req(base, "/api/rules", {"text": "x"}, cookie=cookie)[0], 403)
        ctl = json.loads(self._req(base, "/live/control", {"type": "click", "x": .5, "y": .5}, cookie=cookie)[2])
        self.assertIn("View only", ctl["error"])
        self.assertEqual(self._req(base, "/api/status", cookie=cookie + "x")[0], 401)
        self.assertEqual(self._req(base, "/api/settings", {"model": "x"}, cookie=cookie, origin=False)[0], 200)

    def test_cross_origin_post_refused(self) -> None:
        import urllib.error
        import urllib.request

        base = self._start()
        _c, headers, _b = self._req(base, "/login", {"secret": self.ra.access_token()})
        cookie = headers["Set-Cookie"].split(";")[0]
        req = urllib.request.Request(base + "/api/chat", b'{"text":"x"}',
                                     {"Origin": "https://evil.example", "Cookie": cookie, "Content-Type": "application/json"})
        with self.assertRaises(urllib.error.HTTPError) as err:
            urllib.request.urlopen(req, timeout=5)
        self.assertEqual(err.exception.code, 403)

    def test_rate_limit_lockout_and_pin(self) -> None:
        for _ in range(5):
            self.assertFalse(self.ra.check_login("nope", "1.2.3.4")[0])
        ok, error = self.ra.check_login(self.ra.access_token(), "1.2.3.4")
        self.assertFalse(ok)
        self.assertIn("Wait", error)
        self.assertTrue(self.ra.check_login(self.ra.access_token(), "5.6.7.8")[0])
        os.environ["REMOTE_PIN"] = "123"
        self.addCleanup(os.environ.pop, "REMOTE_PIN", None)
        self.assertFalse(self.ra.check_login("123", "9.9.9.9")[0])  # too short: PIN ignored
        os.environ["REMOTE_PIN"] = "48151623"
        self.assertTrue(self.ra.check_login("48151623", "9.9.9.8")[0])

    def test_session_expiry(self) -> None:
        sid = self.ra.new_session(now=1000.0)
        self.assertTrue(self.ra.session_valid(f"a=b; pedro_session={sid}", now=1001.0))
        self.assertFalse(self.ra.session_valid(f"pedro_session={sid}", now=1000.0 + 13 * 3600))
        self.assertFalse(self.ra.session_valid("pedro_session=forged"))

    def test_control_needs_rules_and_yes(self) -> None:
        import gta5_agent

        calls = []
        gta5_agent.TOOLS["remote_control_action"] = lambda **kw: (calls.append(kw), {"ok": True})[1]
        self.addCleanup(gta5_agent.TOOLS.__setitem__, "remote_control_action", self.ra.remote_control_action)
        self.write_rules({"remote": {"allow_control": True}})
        self.assertTrue(self.ra.do_control({"type": "click"})["needs_confirmation"])
        self.assertTrue(self.ra.allow_control("")["needs_confirmation"])
        self.assertTrue(self.ra.allow_control("yes")["ok"])
        self.assertTrue(self.ra.do_control({"type": "click", "x": 0.25, "y": 0.75})["ok"])
        self.assertEqual(calls[0]["x"], 0.25)
        self.write_rules({"remote": {"allow_control": True}, "tools": {"blocked": ["remote_control_action"]}})
        self.assertFalse(self.ra.do_control({"type": "click"})["ok"])

    def test_local_app_refuses_foreign_host(self) -> None:
        import urllib.error
        import urllib.request
        import chat_app

        server, _s = chat_app.serve("m", 0)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            base = f"http://127.0.0.1:{server.server_address[1]}"
            self.assertEqual(urllib.request.urlopen(base + "/live/frame.jpg", timeout=5).status, 200)
            req = urllib.request.Request(base + "/api/status", headers={"Host": "abc.trycloudflare.com"})
            with self.assertRaises(urllib.error.HTTPError) as err:
                urllib.request.urlopen(req, timeout=5)
            self.assertEqual(err.exception.code, 403)
        finally:
            chat_app.shutdown(server)

    def test_tunnel_link_and_mjpeg(self) -> None:
        line = "2026 INF |  https://quiet-river-1234.trycloudflare.com  |"
        self.assertEqual(self.ra.parse_tunnel_url(line), "https://quiet-river-1234.trycloudflare.com")
        self.assertEqual(self.ra.parse_tunnel_url("nothing"), "")
        link = self.ra.link_with_token("https://x.trycloudflare.com/", "TOKEN")
        self.assertEqual(link, "https://x.trycloudflare.com/login#t=TOKEN")
        parts = []
        sent = self.lp.mjpeg(parts.append, 99, max_frames=3, sleep=lambda s: None)
        self.assertEqual(sent, 3)
        self.assertTrue(parts[0].startswith(b"--frame\r\nContent-Type: image/jpeg"))
        self.assertEqual(self.lp.clamp_fps(99), 30)
        self.assertEqual(self.lp.clamp_fps(0.1), 0.5)
        self.assertEqual(self.lp.clamp_fps("x"), 10)


class FakeMouse:
    def __init__(self, log):
        self.log, self.position = log, (0, 0)

    def press(self, b):
        self.log.append(("press", self.position, str(b)))

    def release(self, b):
        self.log.append(("release", self.position, str(b)))

    def scroll(self, dx, dy):
        self.log.append(("scroll", dx, dy))


class FakeKeys:
    def __init__(self, log):
        self.log = log

    def press(self, k):
        self.log.append(("kdown", str(k)))

    def release(self, k):
        self.log.append(("kup", str(k)))


class DemoSkillTests(_Tmp):
    def setUp(self) -> None:
        super().setUp()
        import demo_skills
        import llm

        self.ds, self.llm = demo_skills, llm
        os.environ["SKILLS_DIR"] = str(self.root / "skills")
        self.addCleanup(os.environ.pop, "SKILLS_DIR", None)
        self.addCleanup(setattr, llm, "override", None)
        self.addCleanup(setattr, demo_skills, "screen_grab", None)
        self.addCleanup(setattr, demo_skills, "controller_factory", None)
        demo_skills.screen_grab = lambda: b"\xff\xd8fakejpeg"

    def _recorder(self):
        rec = self.ds.Recorder("Export Invoice")
        rec.name = self.ds.skill_name("Export Invoice")
        rec.screen = (0, 0)
        rec.async_frames = False
        rec.on_click(100, 200, types_button("left"), True)
        rec.on_click(100, 200, types_button("left"), False)
        for ch in "hunter2":
            rec.on_press(types_key(ch))
            rec.on_release(types_key(ch))
        rec.on_scroll(5, 5, 0, -2)
        rec._frame(True)
        return rec

    def test_summary_keeps_typing_local_and_saves_files(self) -> None:
        seen = {}

        def fake(prompt, images):
            seen["prompt"], seen["images"] = prompt, images
            return "```markdown\n# Export invoice\n## Steps\n1. Click Export\n```"

        self.llm.override = fake
        result = self.ds.save_skill(self._recorder())
        self.assertTrue(result["ok"], result)
        self.assertNotIn("hunter2", seen["prompt"])
        self.assertIn("7 characters typed", seen["prompt"])
        self.assertTrue(seen["images"])
        folder = self.root / "skills" / "export-invoice"
        md = (folder / "SKILL.md").read_text(encoding="utf-8")
        self.assertTrue(md.startswith("# Export invoice"))
        self.assertIn("replay skill export-invoice", md)
        actions = json.loads((folder / "actions.json").read_text(encoding="utf-8"))
        self.assertEqual(len(actions["events"]), 17)
        self.assertEqual(self.ds.list_skills()["skills"][0]["name"], "export-invoice")

    def test_typing_can_be_shared_when_switched_off(self) -> None:
        self.write_rules({"protect": {"skill_typing_stays_local": False}})
        seen = {}
        self.llm.override = lambda p, i: seen.setdefault("p", p) and "# t"
        self.ds.save_skill(self._recorder())
        self.assertIn("hunter2", seen["p"])

    def test_replay_by_name_and_cancel(self) -> None:
        self.llm.override = lambda p, i: "# x"
        self.ds.save_skill(self._recorder())
        log = []
        self.ds.controller_factory = lambda: (FakeMouse(log), FakeKeys(log))
        out = self.ds.replay_skill("Export Invoice", speed=5, sleep=lambda s: None)
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["done"], 17)
        self.assertEqual(log[0][0:2], ("press", (100, 200)))
        self.assertIn(("kdown", "h"), log)
        self.assertIn(("scroll", 0, -2), log)
        cancel = threading.Event()
        cancel.set()
        stopped = self.ds.replay_skill("export-invoice", cancel_event=cancel, sleep=lambda s: None)
        self.assertTrue(stopped["stopped"])
        self.assertFalse(self.ds.replay_skill("nope")["ok"])

    def test_vision_failure_still_writes_steps(self) -> None:
        def boom(p, i):
            raise RuntimeError("offline")

        self.llm.override = boom
        self.ds.save_skill(self._recorder())
        md = (self.root / "skills" / "export-invoice" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("No vision summary", md)
        self.assertNotIn("hunter2", md)


def types_button(name):
    return type("B", (), {"name": name})()


def types_key(ch):
    return type("K", (), {"char": ch})()


if __name__ == "__main__":
    unittest.main()


class StepLabelTests(__import__("unittest").TestCase):
    def test_labels_are_human_and_hide_secrets(self):
        import step_labels
        self.assertEqual(step_labels.label_for("launch_application", {"name": "Chrome"}), "Opening Chrome")
        self.assertEqual(step_labels.label_for("take_screenshot", {}), "Looking at your screen")
        self.assertNotIn("hunter2", step_labels.label_for("type_text", {"text": "hunter2"}))
        self.assertEqual(step_labels.label_for("some_new_tool"), "Some new tool")
        out = []
        step_labels.wrap_emit(out.append)({"event": "tool_start", "name": "open_website", "arguments": {"url": "x.com"}})
        self.assertEqual(out[0], {"event": "step", "label": "Opening x.com", "name": "open_website"})
        self.assertEqual(out[1]["label"], "Opening x.com")


class LiveAdaptiveTests(unittest.TestCase):
    def test_adaptive_quality_drops_on_slow_link_and_recovers(self):
        import live_pc
        a = live_pc.Adaptive(55, 1 / 30)
        for _ in range(6):
            a.update(0.2)
        self.assertLess(a.q, 40); self.assertLess(a.scale, 1.0)
        for _ in range(400):
            a.update(0.001)
        self.assertEqual((a.q, a.scale), (55, 1.0))

    def test_stream_paces_to_30fps(self):
        import live_pc
        live_pc.grabber = lambda: b"jpg"
        try:
            got, st = [], {}
            n = live_pc.mjpeg(got.append, 30, max_frames=5, sleep=lambda s: None, stats=st)
            self.assertEqual(n, 5); self.assertEqual(st["frames"], 5)
        finally:
            live_pc.grabber = None
