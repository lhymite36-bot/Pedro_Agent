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
        self.assertEqual(chat_app.level_payload(), {"level": 0.5, "mic": None})
        speech_level.stop()
        self.assertEqual(chat_app.level_payload(), {"level": None, "mic": None})

    def test_pygame_playback_drives_level(self) -> None:
        import inspect
        import agent_core

        src = inspect.getsource(agent_core._play_mp3_pygame)
        self.assertIn("speech_level.update", src)
        self.assertIn("speech_level.stop", src)
        self.assertIn("playback_should_continue", src)
        js = (Path(__file__).resolve().parents[1] / "app_static" / "app.js").read_text(encoding="utf-8")
        self.assertIn("/api/level", js)
        self.assertIn("voiceOpen", js)

    def test_playback_waits_out_a_false_idle_and_a_moving_voice(self) -> None:
        import agent_core
        import chat_app

        # A one-frame "not playing" just after start is not the end of the file.
        self.assertEqual(agent_core.playback_should_continue(
            busy=False, pos_ms=-1, elapsed_ms=40, duration_ms=4000, saw_busy=False, quiet_ticks=1,
        ), "wait")
        # Still inside the file, even if the device reports idle.
        self.assertEqual(agent_core.playback_should_continue(
            busy=False, pos_ms=-1, elapsed_ms=1000, duration_ms=4000, saw_busy=True, quiet_ticks=20,
        ), "wait")
        # The timeline has finished, so the device is left to drain.
        self.assertEqual(agent_core.playback_should_continue(
            busy=True, pos_ms=3980, elapsed_ms=4000, duration_ms=4000, saw_busy=True, quiet_ticks=0,
        ), "done")
        # pygame can report a position past the file on the first poll.
        # That is not the end, and it must not unload the PC voice.
        self.assertEqual(agent_core.playback_should_continue(
            busy=False, pos_ms=999999, elapsed_ms=30, duration_ms=4000, saw_busy=False, quiet_ticks=0,
        ), "wait")
        self.assertEqual(agent_core.playback_should_continue(
            busy=True, pos_ms=999999, elapsed_ms=30, duration_ms=4000, saw_busy=False, quiet_ticks=0,
        ), "play")
        # A few-hundred-millisecond decode is not trusted to end the reply at once.
        self.assertEqual(agent_core.playback_should_continue(
            busy=False, pos_ms=180, elapsed_ms=30, duration_ms=200, saw_busy=False, quiet_ticks=5,
        ), "wait")
        self.assertTrue(agent_core.barge_in_grace(0.2))
        self.assertFalse(agent_core.barge_in_grace(1.0))
        # No file length and the device has been idle: the reply is over.
        self.assertEqual(agent_core.playback_should_continue(
            busy=False, pos_ms=-1, elapsed_ms=2000, duration_ms=0, saw_busy=True, quiet_ticks=8,
        ), "done")
        now, deadline, cursor, last = 10.0, 10.5, 0, None
        deadline, last = chat_app.speech_deadline(now, deadline, cursor, last)
        self.assertEqual(last, 0)
        self.assertGreater(deadline, now)
        held = deadline
        deadline, last = chat_app.speech_deadline(now + 1, deadline, 0, last)
        self.assertEqual(deadline, held)
        deadline, last = chat_app.speech_deadline(now + 1, deadline, 400, last)
        self.assertGreater(deadline, held)
        self.assertEqual(last, 400)


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
        import agent_core

        self.write_rules({"tools": {"blocked": ["open_website"]}})
        self.assertNotIn("open_website", self.team.tools_for("browser"))
        agent_core.set_tool_scope({"recall_memory"})
        try:
            blocked = agent_core.invoke_tool("open_website", {"url": "https://example.com"})
        finally:
            agent_core.set_tool_scope(None)
        self.assertTrue(blocked.get("blocked_by_scope"))
        self.assertIn("run_team", agent_core.TOOLS)
        self.assertIn("run_team", [d["name"] for d in agent_core.TOOL_DECLARATIONS])

    def test_bad_plan_falls_back_to_research(self) -> None:
        self.llm.override = lambda prompt, images: "no json here"
        self.team.runner = lambda role, task, tools: "ok"
        self.write_rules({"team": {"review": False}})
        result = self.team.run_team("look up the weather")
        self.assertEqual(result["steps"][0]["role"], "research")
        self.assertFalse(result["reviewed"])

    def test_unattended_sensitive_action_waits(self) -> None:
        import confirm_action
        import agent_core

        confirm_action.reset()
        agent_core.set_unattended(True)
        try:
            out = agent_core.invoke_tool("shutdown_computer", {})
        finally:
            agent_core.set_unattended(False)
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
        os.environ["BOT_FILES_DIR"] = str(self.root / "botfiles")
        self.addCleanup(os.environ.pop, "BOTS_DIR", None)
        self.addCleanup(os.environ.pop, "BOT_FILES_DIR", None)
        self.addCleanup(setattr, bots, "engine", None)
        self.addCleanup(setattr, bots, "lock_for", None)
        self.addCleanup(bots._jobs.clear)
        self.addCleanup(chat_store.close)
        self.calls = []

        def fake_engine(prompt, history, model, **kw):
            import agent_core

            self.calls.append({"prompt": prompt, "model": model,
                               "scope": getattr(agent_core._tool_scope, "allowed", None),
                               "unattended": agent_core._unattended(),
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
        import agent_core

        bot = self._make(rules={"tools": {"blocked": ["open_website"]}}, model="gemini-x")
        reply = self.bots.run_bot(bot, "hi", [])
        self.assertEqual(reply, "bot reply")
        call = self.calls[-1]
        self.assertIn("Sort email.", call["prompt"])
        self.assertEqual(call["model"], "gemini-x")
        self.assertEqual(call["scope"], {"recall_memory", "open_website", "ask_bot", *self.bots.SELF_TOOLS})
        self.assertIsNotNone(call["blocked"])  # per-bot override applied in its thread
        self.assertIsNone(rules.tool_block_reason("open_website"))  # and only there
        self.assertIsNone(getattr(agent_core._tool_scope, "allowed", None))
        open_bot = self.bots.save_bot({"name": "Any"})
        self.bots.run_bot(open_bot, "x")
        self.assertIn("ask_bot", self.calls[-1]["scope"])
        self.assertNotIn("run_team", self.calls[-1]["scope"])
        self.assertIn("bot_remember", self.calls[-1]["scope"])
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

    def test_notebook_folder_lesson_and_one_handoff(self) -> None:
        import agent_core

        self.bots.save_bot({"name": "Writer", "role": "writes"})
        inbox = self._make()
        self.handed = False

        def fake(prompt, history, model, **kw):
            self.calls.append({"prompt": prompt,
                               "scope": getattr(agent_core._tool_scope, "allowed", None)})
            if "Sort email." in prompt and not self.handed:
                self.handed = True
                self.nested = agent_core.invoke_tool("ask_bot", {"name": "Writer", "task": "write the note"})
            if prompt.startswith("[You are the bot 'Writer'"):
                self.refused = agent_core.invoke_tool("ask_bot", {"name": "Inbox Helper", "task": "again"})
            return "bot reply"

        self.bots.engine = fake
        self.bots.run_bot(self.bots.get_bot(inbox["id"]), "hi", [])
        self.assertTrue(self.nested["ok"], self.nested)
        self.assertFalse(self.refused["ok"])
        self.assertNotIn("ask_bot", self.calls[-1]["scope"])
        self.assertTrue(self.bots.bot_remember("Sort invoices by date", "Inbox Helper")["ok"])
        self.assertFalse(self.bots.bot_remember("password: hunter2", "Inbox Helper")["ok"])
        self.bots.run_bot(self.bots.get_bot(inbox["id"]), "again", [])
        self.assertIn("Sort invoices by date", self.calls[-1]["prompt"])
        listed = self.bots.list_my_files("Inbox Helper")
        self.assertTrue(listed["ok"], listed)
        (Path(listed["path"]) / "note.txt").write_text("hello", encoding="utf-8")
        self.assertTrue(any(name.endswith("note.txt") for name in self.bots.list_my_files("Inbox Helper")["files"]))
        saved = self.bots.save_bot_skill("Export", "1. Open the sheet", "Inbox Helper")
        self.assertTrue(saved["ok"], saved)
        self.bots.run_bot(self.bots.get_bot(inbox["id"]), "use the lesson", [])
        self.assertIn("Open the sheet", self.calls[-1]["prompt"])

    def test_folder_watch_and_last_run_continue(self) -> None:
        folder = self.root / "incoming"
        folder.mkdir()
        (folder / "old.pdf").write_text("old", encoding="utf-8")
        bot = self.bots.save_bot({"name": "Filer", "role": "files", "tasks": [{
            "text": "file the pdf",
            "watch": {"path": str(folder), "pattern": "*.pdf"},
        }]})
        self.assertEqual(self.bots.run_due_tasks(1_000_000.0), [])
        armed = self.bots.get_bot(bot["id"])["tasks"][0]
        self.assertTrue(armed["watch_armed"])
        self.assertIn("old.pdf", armed["watch_seen"])
        new = folder / "new.pdf"
        new.write_text("new", encoding="utf-8")
        results = self.bots.run_due_tasks(1_000_000.0)
        self.assertEqual(len(results), 1, results)
        self.assertIn("new.pdf", self.calls[-1]["prompt"])
        self.assertEqual(self.bots.run_due_tasks(1_000_000.0), [])
        self.bots.run_task(bot["id"], bot["tasks"][0]["id"])
        self.assertIn("Last time you ran this", self.calls[-1]["prompt"])
        self.assertIn("bot reply", self.calls[-1]["prompt"])

    def test_main_agent_delegates_with_ask_bot(self) -> None:
        import agent_core

        self._make()
        out = agent_core.invoke_tool("ask_bot", {"name": "inbox helper", "task": "sort"})
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["message"], "bot reply")
        self.assertFalse(agent_core.invoke_tool("ask_bot", {"name": "ghost", "task": "x"})["ok"])
        self.assertIn("list_bots", agent_core.TOOLS)

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

    def test_search_transcript_and_standing_duty(self) -> None:
        import agent_core

        bot = self._make()
        self.bots.save_bot({"name": "Writer", "role": ""})
        self.bots.save_bot({"name": "Mail Clerk", "role": "email digests"})
        email = self.bots.bot_search("email")
        names = [row["name"] for row in email["bots"]]
        self.assertEqual(names[0], "Inbox Helper")
        self.assertIn("Mail Clerk", names)
        self.assertNotIn("Writer", names)
        writer = self.bots.bot_search("writer")
        self.assertEqual(writer["bots"][0]["name"], "Writer")
        self.assertEqual(writer["bots"][0]["role"], "")
        self.assertGreaterEqual(len(self.bots.bot_search("")["bots"]), 3)
        self.store.add("bot-inbox-helper", "user", "password: hunter2")
        self.store.add("bot-inbox-helper", "assistant", "Checked the inbox.")
        transcript = self.bots.bot_transcript("Inbox Helper")
        dumped = json.dumps(transcript)
        self.assertNotIn("hunter2", dumped)
        self.assertIn("[hidden]", dumped)
        self.assertIn("Checked the inbox.", dumped)
        before = len(self.bots.get_bot(bot["id"])["tasks"])
        saved = self.bots.save_standing_duty(
            "Morning inbox", "Check the inbox and report new mail.", "every day at 8 AM", "Inbox Helper")
        self.assertTrue(saved["ok"], saved)
        self.assertEqual(saved["routine"]["target"], "bot")
        self.assertEqual(saved["routine"]["target_id"], bot["id"])
        self.assertIn("awake", saved["message"])
        self.assertEqual(len(self.bots.get_bot(bot["id"])["tasks"]), before)
        self.assertIn("Morning inbox", self.bots.bot_search("inbox")["bots"][0]["routines"])
        again = self.bots.save_standing_duty(
            "Morning inbox", "Check the inbox and report new mail.", "every day at 8 AM", "Inbox Helper")
        self.assertFalse(again["ok"])
        self.bots.run_bot(self.bots.get_bot(bot["id"]), "again", [])
        self.assertIn("save_standing_duty", self.calls[-1]["prompt"])
        self.assertIn("Earlier in this chat", self.calls[-1]["prompt"])
        self.assertIn("Checked the inbox.", self.calls[-1]["prompt"])
        self.assertNotIn("hunter2", self.calls[-1]["prompt"])
        self.assertIn("bot_search", agent_core.SYSTEM_PROMPT)
        self.assertIn("save_standing_duty", agent_core.SYSTEM_PROMPT)
        self.assertIn("no separate computer", agent_core.SYSTEM_PROMPT)
        open_bot = self.bots.save_bot({"name": "Open"})
        self.assertIn("save_standing_duty", self.bots._scope_for(open_bot, None, True))
        self.assertIn("bot_send", self.bots._scope_for(open_bot, None, True))
        self.assertNotIn("bot_send", self.bots._scope_for(open_bot, None, False))

    def test_send_returns_a_handle_and_await_reads_the_reply(self) -> None:
        import time

        self._make()
        self.bots.lock_for = None
        gate = threading.Event()
        release = threading.Event()

        def slow(prompt, history, model, **kw):
            gate.set()
            if not release.wait(3):
                return "timed out"
            if "Which inbox" in prompt:
                return "Which inbox?"
            return "finished work"

        self.bots.engine = slow
        try:
            out = self.bots.bot_send("Inbox Helper", "check the inbox")
            self.assertEqual(out["status"], "running")
            self.assertTrue(out["handle"])
            self.assertTrue(gate.wait(2))
            self.assertEqual(self.bots.bot_await(out["handle"])["status"], "running")
            busy = self.bots.bot_send("Inbox Helper", "check again")
            self.assertEqual(busy["status"], "running")
            self.assertEqual(busy["handle"], out["handle"])
            release.set()
            done = {}
            deadline = time.time() + 3
            while time.time() < deadline:
                done = self.bots.bot_await(out["handle"])
                if done.get("status") != "running":
                    break
                time.sleep(0.02)
            self.assertEqual(done.get("status"), "done", done)
            self.assertEqual(done.get("message"), "finished work")
            held = threading.Lock()
            held.acquire()
            self.bots.lock_for = lambda session: held
            blocked = self.bots.bot_send("Inbox Helper", "check again")
            self.assertEqual(blocked["handle"], "")
            self.assertIn("chat turn", blocked["message"])
            held.release()
            self.bots.lock_for = None
            gate.clear()
            asked = self.bots.bot_send("Inbox Helper", "Which inbox should I open?")
            self.assertTrue(gate.wait(2))
            asked_done = {}
            deadline = time.time() + 3
            while time.time() < deadline:
                asked_done = self.bots.bot_await(asked["handle"])
                if asked_done.get("status") != "running":
                    break
                time.sleep(0.02)
            self.assertEqual(asked_done.get("status"), "question", asked_done)
            self.assertFalse(self.bots.bot_await("missing")["ok"])
        finally:
            release.set()

    def test_bot_history_keeps_earlier_turns(self) -> None:
        import chat_app

        session = "bot-memory"
        for i in range(150):
            text = "password: hunter2" if i == 1 else f"line {i} about the inbox"
            role = "user" if i % 2 == 0 else "assistant"
            self.store.add(session, role, text)
        contents = chat_app._rebuild_history(session)
        self.assertEqual(len(contents), 141)   # 1.6.0: 140 recent turns + one note
        first = contents[0].parts[0].text
        self.assertTrue(first.startswith("Earlier turns you still remember"))
        self.assertIn("line 0", first)
        self.assertNotIn("hunter2", first)
        self.assertIn("[hidden]", first)
        self.assertIn("line 149", contents[-1].parts[0].text)
        plain = "notes"
        for i in range(130):
            self.store.add(plain, "user", f"plain {i}")
        plain_contents = chat_app._rebuild_history(plain)
        self.assertEqual(len(plain_contents), 120)
        self.assertNotIn("Earlier turns", plain_contents[0].parts[0].text)
        self.assertIn("plain 10", plain_contents[0].parts[0].text)
        self.assertIn("plain 129", plain_contents[-1].parts[0].text)


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
        import agent_core

        (self.proj / ".git").mkdir()
        calls = []
        saved = agent_core.git_runner_override
        agent_core.git_runner_override = lambda cmd, cwd: (calls.append(cmd), {"returncode": 0, "stdout": " M a.py\n" if "status" in cmd else "", "stderr": ""})[1]
        self.addCleanup(setattr, agent_core, "git_runner_override", saved)
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
        self.assertIn("autopilot_control", __import__("agent_core").TOOLS)


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
        import agent_core

        self.assertTrue(agent_core._parser().parse_args(["--live"]).live)


class SelfUpgradeTests(_Tmp):
    def setUp(self) -> None:
        super().setUp()
        import agent_core
        import llm
        import self_upgrade

        self.su, self.llm, self.agent = self_upgrade, llm, agent_core
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
        agent_core.TOOLS["flaky_tool"] = flaky.flaky_tool
        self.addCleanup(agent_core.TOOLS.pop, "flaky_tool", None)
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
        seen: list[str] = []
        self.lp.mouse_override = lambda kind, fields: seen.append(kind)
        self.addCleanup(setattr, self.lp, "mouse_override", None)
        ctl = json.loads(self._req(base, "/live/control", {"type": "click", "x": .5, "y": .5}, cookie=cookie)[2])
        self.assertTrue(ctl["ok"], ctl)
        self.assertEqual(seen, ["click"])
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
        import agent_core

        calls = []
        agent_core.TOOLS["remote_control_action"] = lambda **kw: (calls.append(kw), {"ok": True})[1]
        self.addCleanup(agent_core.TOOLS.__setitem__, "remote_control_action", self.ra.remote_control_action)
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

    def _hold_tunnel_state(self):
        saved = (self.ra.public_url, self.ra._tunnel, self.ra._tunnel_gen)
        def restore():
            self.ra.public_url, self.ra._tunnel, self.ra._tunnel_gen = saved
        self.addCleanup(restore)

    def test_tunnel_keeps_reading_after_the_url(self) -> None:
        from unittest import mock

        self._hold_tunnel_state()
        lines = [
            "waiting\n",
            "2026 INF | https://quiet-river-1234.trycloudflare.com |\n",
            "metrics tick\n",
            "still writing\n",
        ]
        seen: list[str] = []

        class Out:
            def __iter__(self):
                return self

            def __next__(self):
                if not lines:
                    raise StopIteration
                item = lines.pop(0)
                seen.append(item)
                return item

        proc = mock.Mock()
        proc.stdout = Out()
        proc.poll.return_value = 0
        announced: list[str] = []
        with mock.patch.object(self.ra, "_announce", side_effect=lambda url, token: announced.append(url)), \
             mock.patch.object(self.ra, "access_token", return_value="tok"):
            alive = self.ra._follow_tunnel_output(proc)
        self.assertFalse(alive)
        self.assertEqual(announced, ["https://quiet-river-1234.trycloudflare.com"])
        self.assertEqual(len(seen), 4)
        self.assertEqual(lines, [])

    def test_tunnel_restarts_when_cloudflared_exits(self) -> None:
        from unittest import mock

        self._hold_tunnel_state()
        calls = {"n": 0}
        seen: list[str] = []

        def popen(*_a, **_k):
            calls["n"] += 1
            proc = mock.Mock()
            payload = [
                f"https://quiet-river-{calls['n']}.trycloudflare.com\n",
                "after the url\n",
            ]

            class Out:
                def __iter__(self):
                    return self

                def __next__(self):
                    if not payload:
                        raise StopIteration
                    item = payload.pop(0)
                    seen.append(item)
                    return item

            proc.stdout = Out()
            proc.poll.return_value = 0

            def wait(*_a, **_k):
                if calls["n"] >= 2:
                    self.ra._tunnel_gen += 1
                return 0

            proc.wait.side_effect = wait
            return proc

        sleeps: list[float] = []
        with mock.patch.object(self.ra.subprocess, "Popen", side_effect=popen), \
             mock.patch.object(self.ra, "cloudflared_exe", return_value="cloudflared"), \
             mock.patch.object(self.ra, "_announce"), \
             mock.patch.object(self.ra, "access_token", return_value="tok"), \
             mock.patch.object(self.ra.time, "sleep", side_effect=lambda seconds: sleeps.append(seconds)):
            self.ra.start_tunnel(8766)
        self.assertEqual(calls["n"], 2)
        self.assertEqual(sleeps, [2])
        self.assertEqual(seen.count("after the url\n"), 2)


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
        self.assertIn("changes every time", seen["prompt"])
        self.assertTrue(seen["images"])
        folder = self.root / "skills" / "export-invoice"
        md = (folder / "SKILL.md").read_text(encoding="utf-8")
        self.assertTrue(md.startswith("# Export invoice"))
        self.assertIn("replay skill export-invoice", md)
        actions = json.loads((folder / "actions.json").read_text(encoding="utf-8"))
        self.assertEqual(len(actions["events"]), 17)
        self.assertEqual(actions["inputs"], [{"id": "input_1", "label": "Input 1", "chars": 7}])
        self.assertNotIn("hunter2", json.dumps(actions["inputs"]))
        self.assertIn("Input 1", md)
        self.assertEqual(self.ds.list_skills()["skills"][0]["name"], "export-invoice")

    def test_typing_can_be_shared_when_switched_off(self) -> None:
        self.write_rules({"protect": {"skill_typing_stays_local": False}})
        seen = {}
        self.llm.override = lambda p, i: seen.setdefault("p", p) and "# t"
        self.ds.save_skill(self._recorder())
        self.assertIn("hunter2", seen["p"])

    def test_replay_asks_for_new_text_and_types_that(self) -> None:
        self.llm.override = lambda p, i: "# x"
        self.ds.save_skill(self._recorder())
        log = []
        self.ds.controller_factory = lambda: (FakeMouse(log), FakeKeys(log))
        asked = self.ds.replay_skill("Export Invoice", speed=5, sleep=lambda s: None)
        self.assertFalse(asked["ok"])
        self.assertEqual(asked["needs_input"], [{"label": "Input 1", "chars": 7}])
        self.assertNotIn("hunter2", json.dumps(asked))
        self.assertFalse(log)
        out = self.ds.replay_skill("export-invoice", speed=5, inputs="Ada", sleep=lambda s: None)
        self.assertTrue(out["ok"], out)
        self.assertNotIn("Ada", out["message"])
        self.assertEqual(log[0][0:2], ("press", (100, 200)))
        typed = [item[1] for item in log if item[0] == "kdown"]
        self.assertEqual(typed, ["A", "d", "a"])
        self.assertIn(("scroll", 0, -2), log)
        cancel = threading.Event()
        cancel.set()
        stopped = self.ds.replay_skill("export-invoice", inputs="Ada", cancel_event=cancel, sleep=lambda s: None)
        self.assertTrue(stopped["stopped"])
        self.assertFalse(self.ds.replay_skill("nope")["ok"])

    def test_two_typed_steps_take_two_new_values(self) -> None:
        rec = self.ds.Recorder("Fill Form")
        rec.name = "fill-form"
        rec.screen = (0, 0)
        rec.async_frames = False
        enter = type("K", (), {"char": None, "name": "enter"})()
        for ch in "Ann":
            rec.on_press(types_key(ch))
            rec.on_release(types_key(ch))
        rec.on_press(enter)
        rec.on_release(enter)
        for ch in "12":
            rec.on_press(types_key(ch))
            rec.on_release(types_key(ch))
        self.llm.override = lambda p, i: "# form"
        self.ds.save_skill(rec)
        log = []
        self.ds.controller_factory = lambda: (FakeMouse(log), FakeKeys(log))
        missing = self.ds.replay_skill("fill-form", inputs="only one", sleep=lambda s: None)
        self.assertFalse(missing["ok"])
        self.assertEqual(len(missing["needs_input"]), 2)
        self.assertFalse(log)
        out = self.ds.replay_skill("fill-form", inputs="Bea\n99", speed=5, sleep=lambda s: None)
        self.assertTrue(out["ok"], out)
        downs = [item[1] for item in log if item[0] == "kdown"]
        self.assertEqual(downs[:3], ["B", "e", "a"])
        self.assertTrue(any("enter" in item.casefold() for item in downs[3:-2]))
        self.assertEqual(downs[-2:], ["9", "9"])

    def _lesson(self, name: str, body: str) -> None:
        folder = self.root / "skills" / name
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "SKILL.md").write_text(body, encoding="utf-8")

    def test_follow_reads_a_new_question_and_fixes_a_miss(self) -> None:
        self._lesson("answer-form", "# Answer form\n## Steps\n1. Read the question\n2. Type the answer\n3. Click Save\n")
        replies = iter([
            '{"action":"type","text":"Paris","reason":"the question asks for the capital"}',
            '{"action":"click","x":1,"y":1,"reason":"missed the button"}',
            '{"action":"click","x":8,"y":9,"reason":"the save button"}',
            '{"action":"done","reason":"saved"}',
        ])
        seen = {}

        def fake(prompt, images):
            seen["prompt"] = prompt
            self.assertTrue(images)
            return next(replies)

        self.llm.override = fake
        log = []
        self.ds.controller_factory = lambda: (FakeMouse(log), FakeKeys(log))
        out = self.ds.follow_skill("answer-form", sleep=lambda s: None)
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["actions"], ["type", "click", "click"])
        self.assertNotIn("Paris", json.dumps(out))
        typed = "".join(item[1] for item in log if item[0] == "kdown")
        self.assertEqual(typed, "Paris")
        presses = [item[1] for item in log if item[0] == "press"]
        self.assertEqual(presses, [(1, 1), (8, 9)])
        self.assertIn("write the answer that fits", seen["prompt"])
        self.assertIn("Read the question", seen["prompt"])

    def test_follow_stops_for_a_graded_test_and_a_secret(self) -> None:
        self._lesson("quiz", "# Quiz\n## Steps\n1. Answer\n")
        self.llm.override = lambda prompt, images: '{"action":"stop","reason":"This is a graded test."}'
        log = []
        self.ds.controller_factory = lambda: (FakeMouse(log), FakeKeys(log))
        stopped = self.ds.follow_skill("quiz", sleep=lambda s: None)
        self.assertFalse(stopped["ok"])
        self.assertIn("graded test", stopped["error"])
        self.assertFalse(log)
        self.llm.override = lambda prompt, images: '{"action":"type","text":"password: hunter2","reason":"fill it"}'
        hidden = self.ds.follow_skill("quiz", sleep=lambda s: None)
        self.assertFalse(hidden["ok"])
        self.assertNotIn("hunter2", json.dumps(hidden))
        self.assertFalse(any(item[0] == "kdown" for item in log))

    def test_follow_stops_when_the_same_step_keeps_failing(self) -> None:
        self._lesson("stuck", "# Stuck\n## Steps\n1. Click Go\n")
        self.llm.override = lambda prompt, images: '{"action":"click","x":3,"y":4,"reason":"go"}'
        log = []
        self.ds.controller_factory = lambda: (FakeMouse(log), FakeKeys(log))
        out = self.ds.follow_skill("stuck", sleep=lambda s: None, limit=8)
        self.assertFalse(out["ok"])
        self.assertIn("fix", out["error"])
        self.assertEqual(len([item for item in log if item[0] == "press"]), 2)

    def test_shortcut_is_not_an_input(self) -> None:
        events = [
            {"type": "key", "key": "Key.ctrl", "down": True},
            {"type": "key", "key": "s", "down": True},
            {"type": "key", "key": "s", "down": False},
            {"type": "key", "key": "Key.ctrl", "down": False},
        ]
        self.assertEqual(self.ds.input_slots(events), [])

    def test_replay_without_typing_starts_immediately(self) -> None:
        rec = self.ds.Recorder("Click Only")
        rec.name = "click-only"
        rec.screen = (0, 0)
        rec.async_frames = False
        rec.on_click(3, 4, types_button("left"), True)
        rec.on_click(3, 4, types_button("left"), False)
        self.llm.override = lambda p, i: "# click"
        self.ds.save_skill(rec)
        log = []
        self.ds.controller_factory = lambda: (FakeMouse(log), FakeKeys(log))
        out = self.ds.replay_skill("click-only", speed=5, sleep=lambda s: None)
        self.assertTrue(out["ok"], out)
        self.assertEqual(log[0][0:2], ("press", (3, 4)))

    def test_recording_is_saved_on_the_named_bot(self) -> None:
        import bots

        os.environ["BOTS_DIR"] = str(self.root / "bots")
        self.addCleanup(os.environ.pop, "BOTS_DIR", None)
        bot = bots.save_bot({"name": "Teacher", "role": "learns"})
        rec = self._recorder()
        rec.bot_id = bot["id"]
        self.llm.override = lambda p, i: "# Export invoice\n## Steps\n1. Click Export\n"
        result = self.ds.save_skill(rec)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["bot"], "Teacher")
        lesson = bots.get_bot("Teacher")["skills"][0]
        self.assertIn("Click Export", lesson["text"])
        self.assertIn("Input 1", lesson["text"])
        self.assertNotIn("hunter2", lesson["text"])
        self.assertFalse(self.ds.record_demonstration("x", bot="nobody")["ok"])

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
