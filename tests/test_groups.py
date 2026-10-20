import os
import tempfile
import unittest
from unittest import mock

import bots
import groups


class GroupTests(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"BOTS_DIR": self.d.name + "/b", "GROUPS_DIR": self.d.name + "/g"})
        self.env.start()
        bots.save_bot({"name": "Writer", "role": "writes", "color": "#ff0000", "avatar": "cat"})
        bots.save_bot({"name": "Editor", "role": "edits"})
        self.calls = []

        def eng(prompt, history, model, **kw):
            who = "Pedro" if "You are Pedro_Agent" in prompt else ("Writer" if "You are Writer" in prompt else "Editor")
            self.calls.append(who)
            return "@writer draft it and @editor check it" if who == "Pedro" else f"{who} done"
        bots.engine = eng; groups.main_engine = eng

    def tearDown(self):
        bots.engine = None; groups.main_engine = None; self.env.stop(); self.d.cleanup()

    def test_create_edit_persist_delete(self):
        g = groups.save_group({"name": "Shorts Team", "purpose": "make shorts", "members": ["writer", "ghost"]})
        self.assertEqual(g["members"], ["writer"]); self.assertEqual(g["coordinator"], "pedro")
        g2 = groups.save_group({**g, "members": ["writer", "editor"], "coordinator": "editor"})
        self.assertEqual(groups.get_group(g["id"])["members"], ["writer", "editor"])
        self.assertEqual(g2["coordinator"], "editor"); self.assertEqual(g2["created"], g["created"])
        self.assertEqual(len(groups.list_groups()), 1)
        g3 = groups.save_group({**g2, "members": ["writer"]})
        self.assertEqual(g3["coordinator"], "pedro")  # coordinator removed with its member
        self.assertTrue(groups.delete_group(g["id"])); self.assertEqual(groups.list_groups(), [])
        with self.assertRaises(ValueError):
            groups.save_group({"name": " "})

    def test_leader_loop_assigns_reviews_and_finishes(self):
        g = groups.save_group({"name": "T", "members": ["writer", "editor"]})
        script = iter(["Plan: research then write.\nASSIGN @writer: draft 3 facts about owls",
                       "Good draft.\nASSIGN @editor: tidy it and save owls.pdf on the Desktop",
                       "Checked the file.\nPROJECT DONE: owls.pdf saved at C:/Users/x/Desktop/owls.pdf"])
        def eng(prompt, history, model, **kw):
            self.calls.append(prompt)
            if "LEADER" in prompt:
                return next(script)
            kw.get("on_text", lambda c: None)("work")
            return "DONE: did it"
        bots.engine = eng; groups.main_engine = eng
        events, stored = [], []
        said = groups.run_group(g, "Make a short PDF about owls", [], events.append, store=lambda s, r, t: stored.append(t))
        self.assertEqual([s for s, _ in said], ["pedro", "writer", "pedro", "editor", "pedro"])
        self.assertIn("draft 3 facts about owls", self.calls[1])
        self.assertTrue(said[-1][1].startswith("Checked") and "PROJECT DONE" in said[-1][1])
        status = [e["doing"] for e in events if e["event"] == "group_status"]
        self.assertTrue(any(d.startswith("Writer is working on: draft 3 facts") for d in status))
        self.assertEqual(status[-1], "Project complete")
        self.assertTrue(any(e["event"] == "token" for e in events))   # replies stream
        self.assertTrue(stored[1].startswith("[[@writer]] "))

    def test_loop_safety_limit_and_stop(self):
        g = groups.save_group({"name": "T", "members": ["writer"]})
        def eng(prompt, history, model, **kw):
            return "ASSIGN @writer: more" if "LEADER" in prompt else "DONE: ok"
        bots.engine = eng; groups.main_engine = eng
        with mock.patch.object(groups, "limits", return_value={"max_turns": 6, "max_minutes": 30}):
            ev = []
            said = groups.run_group(g, "build an endless project", [], ev.append)
        self.assertEqual(len(said), 6)
        self.assertIn("Paused after 6 turns", [e for e in ev if e["event"] == "done"][-1]["text"])
        import threading
        stop = threading.Event()
        def eng2(prompt, history, model, **kw):
            stop.set(); return "ASSIGN @writer: x"
        groups.main_engine = eng2
        ev = []
        said = groups.run_group(g, "project", [], ev.append, cancel_event=stop)
        self.assertEqual(len(said), 1)

    def test_loop_pauses_for_confirmation(self):
        g = groups.save_group({"name": "T", "members": ["writer"]})
        groups.main_engine = lambda p, h, m, **k: "ASSIGN @writer: send it"
        bots.engine = lambda p, h, m, **k: "Waiting for a yes"
        with mock.patch.object(groups, "_pending_confirmation", side_effect=["", "send a WhatsApp message to Maya"]):
            ev = []
            said = groups.run_group(g, "send the pdf", [], ev.append)
        self.assertEqual([s for s, _ in said], ["pedro", "writer"])
        self.assertIn("Waiting for your yes", ev[-1]["text"])

    def test_direct_mention_goes_to_that_bot_only(self):
        g = groups.save_group({"name": "T", "members": ["writer", "editor"]})
        seen = []
        bots.engine = lambda p, h, m, **k: (seen.append(p), "DONE: wrote it")[1]
        groups.main_engine = lambda p, h, m, **k: self.fail("leader must not run for a direct mention")
        said = groups.run_group(g, "@writer write a haiku about owls", [], lambda e: None)
        self.assertEqual([s for s, _ in said], ["writer"])
        self.assertIn("addressed YOU (Writer) directly", seen[0]); self.assertIn("haiku about owls", seen[0])

    def test_chitchat_answers_once(self):
        g = groups.save_group({"name": "T", "members": ["writer"]})
        groups.main_engine = lambda p, h, m, **k: "Hi! What should we build?"
        self.assertEqual(len(groups.run_group(g, "hello", [], lambda e: None)), 1)

    def test_mentions_go_direct(self):
        g = groups.save_group({"name": "T", "members": ["writer", "editor"]})
        said = groups.run_group(g, "@Editor quick check", [], lambda e: None)
        self.assertEqual([s for s, _ in said], ["editor"])
        said = groups.run_group(g, "@all hi", [], lambda e: None)
        self.assertEqual([s for s, _ in said], ["pedro", "writer", "editor"])
        self.assertEqual(groups.mentions("@nobody", g), [])


class DisplayTests(GroupTests):
    def test_markers_become_natural_text_and_chips(self):
        g = groups.save_group({"name": "T", "members": ["writer"]})
        text, chips = groups.for_display("Plan ready.\nASSIGN @writer: Write the intro.", g)
        self.assertNotIn("ASSIGN", text); self.assertIn("Writer, could you write the intro?", text)
        self.assertEqual(chips, [{"kind": "assign", "text": "→ assigned to Writer"}])
        text, chips = groups.for_display("Wrote it.\nDONE: intro.txt on the Desktop")
        self.assertNotIn("DONE:", text); self.assertIn("intro.txt", text); self.assertEqual(chips[0]["text"], "✓ done")
        text, chips = groups.for_display("Working… DONE: finished my part")
        self.assertEqual(text, "Working. finished my part"); self.assertEqual(chips[0]["text"], "✓ done")
        text, chips = groups.for_display("PROJECT DONE: All saved.")
        self.assertEqual(text, "All saved."); self.assertEqual(chips[0]["text"], "✓ project complete")

    def test_emitted_and_stored_text_is_clean(self):
        g = groups.save_group({"name": "T", "members": ["writer"]})
        replies = iter(["ASSIGN @writer: write a line", "PROJECT DONE: finished"])
        groups.main_engine = lambda p, h, m, **k: next(replies)
        bots.engine = lambda p, h, m, **k: "Here it is.\nDONE: a line"
        events, stored = [], []
        groups.run_group(g, "Write a short poem file", [], events.append, store=lambda s, r, t: stored.append(t))
        shown = [e["text"] for e in events if e.get("event") == "done"]
        self.assertTrue(all("ASSIGN" not in t and "DONE:" not in t for t in shown), shown)
        self.assertTrue(any(c["text"] == "✓ done" for e in events if e.get("event") == "done" for c in e["chips"]))
        self.assertTrue(all("ASSIGN @" not in t for t in stored))
        row = groups.clean_row({"role": "assistant", "text": "[[@pedro]] ASSIGN @writer: old raw row"})
        self.assertNotIn("ASSIGN", row["text"]); self.assertTrue(row["text"].startswith("[[@pedro]]"))

    def test_greeting_skips_project_loop(self):
        g = groups.save_group({"name": "T", "members": ["writer", "editor"]})
        seen = []
        groups.main_engine = lambda p, h, m, **k: (seen.append(p), "ASSIGN @writer: say hi")[1]
        bots.engine = lambda p, h, m, **k: self.fail("members must not be assigned for a greeting")
        for hi in ("hi", "Hello everyone!", "how are you guys", "good morning", "thanks"):
            said = groups.run_group(g, hi, [], lambda e: None)
            self.assertEqual(len(said), 1, hi)
        self.assertIn("small talk", seen[0])
        self.assertTrue(groups.is_chitchat("hey"))
        self.assertFalse(groups.is_chitchat("make a PDF about owls"))
        self.assertFalse(groups.is_chitchat("research the best laptops under 500 dollars"))


class DeleteTests(GroupTests):
    def test_deleting_bot_leaves_groups_with_coordinator_fallback(self):
        g = groups.save_group({"name": "T", "members": ["writer", "editor"], "coordinator": "writer"})
        other = groups.save_group({"name": "U", "members": ["editor"]})
        self.assertTrue(bots.delete_bot("writer"))
        self.assertEqual(groups.remove_bot("writer"), 1)
        g2 = groups.get_group(g["id"])
        self.assertEqual(g2["members"], ["editor"]); self.assertEqual(g2["coordinator"], "pedro")
        self.assertEqual(groups.get_group(other["id"])["members"], ["editor"])

    def test_deleting_group_keeps_bots(self):
        g = groups.save_group({"name": "T", "members": ["writer"]})
        self.assertTrue(groups.delete_group(g["id"]))
        self.assertIsNotNone(bots.get_bot("writer"))

    def test_clear_chats_keeps_bot_and_group_rooms(self):
        import chat_app
        rows = [{"session": "abc"}, {"session": "bot-writer"}, {"session": "group-t"}, {"session": "telegram"}]
        gone = []
        state = mock.Mock(histories={"abc": [1]})
        with mock.patch.object(chat_app.chat_store, "sessions", return_value=rows), \
             mock.patch.object(chat_app.chat_store, "delete_session", side_effect=gone.append):
            self.assertEqual(chat_app.clear_chats(state), 2)
        self.assertEqual(gone, ["abc", "telegram"]); self.assertNotIn("abc", state.histories)


class PictureTests(GroupTests):
    def test_picture_and_preset_persist_and_validate(self):
        pic = "data:image/jpeg;base64,/9j/4AAQSkZJRg=="
        g = groups.save_group({"name": "P", "picture": pic, "color": "#123456", "avatar": "cloud"})
        saved = groups.get_group(g["id"])
        self.assertEqual((saved["picture"], saved["color"], saved["avatar"]), (pic, "#123456", "cloud"))
        g2 = groups.save_group({**saved, "picture": "", "color": "bad", "avatar": "dragon"})
        self.assertEqual((g2["picture"], g2["color"], g2["avatar"]), ("", "#5b9dff", "blob"))
        for bad in ("javascript:alert(1)", "data:image/svg+xml;base64,PHN2Zz4=", "data:image/png;base64," + "A" * 300000):
            with self.assertRaises(ValueError):
                groups.save_group({"name": "Q", "picture": bad})


class ProjectIntentTests(GroupTests):
    def test_at_all_with_a_real_job_runs_the_project_loop(self):
        g = groups.save_group({"name": "T", "members": ["writer", "editor"]})
        lead = iter(["ASSIGN @writer: build the shorts app", "Verified.\nPROJECT DONE: saved"])
        seen = []
        def eng(prompt, history, model, **kw):
            seen.append(prompt)
            if "LEADER" in prompt:
                return next(lead)
            return "Built it with build_local_program.\nDONE: C:\\Users\\x\\Desktop\\Shorts\\main.py"
        bots.engine = eng; groups.main_engine = eng
        said = groups.run_group(g, "@all make an app that makes nice youtube shorts", [], lambda e: None)
        self.assertEqual([s for s, _ in said], ["pedro", "writer", "pedro"])
        self.assertIn("don't discuss", seen[1]); self.assertIn("build_local_program", seen[1])
        self.assertIn("build_local_program", groups.GROUP_TOOLS)

    def test_two_mentions_with_a_task_also_orchestrate(self):
        g = groups.save_group({"name": "T", "members": ["writer", "editor"]})
        groups.main_engine = lambda p, h, m, **k: "PROJECT DONE: ok" if "LEADER" in p else self.fail("not direct")
        bots.engine = lambda p, h, m, **k: self.fail("no worker yet")
        said = groups.run_group(g, "@writer @editor create a PDF about owls", [], lambda e: None)
        self.assertEqual(said[0][0], "pedro")

    def test_intent_helpers(self):
        self.assertTrue(groups.is_task("@all make an app that makes nice youtube shorts"))
        self.assertTrue(groups.is_task("code a script"))
        self.assertFalse(groups.is_task("@all hi"))
        self.assertFalse(groups.is_task("hello everyone"))
        self.assertTrue(groups.is_chitchat("hey guys"))

    def test_leader_that_only_chats_is_nudged_to_assign(self):
        g = groups.save_group({"name": "T", "members": ["writer"]})
        lead = iter(["Sounds like a fun project!", "ASSIGN @writer: build it", "PROJECT DONE: done"])
        groups.main_engine = lambda p, h, m, **k: next(lead)
        bots.engine = lambda p, h, m, **k: "DONE: built"
        said = groups.run_group(g, "@all build a todo app", [], lambda e: None)
        self.assertEqual([s for s, _ in said], ["pedro", "pedro", "writer", "pedro"])

    def test_project_done_without_work_or_with_missing_files_is_rejected_once(self):
        g = groups.save_group({"name": "T", "members": ["writer"]})
        logs = []
        lead = iter(["PROJECT DONE: all good", "ASSIGN @writer: build it", "PROJECT DONE: at C:\\nope\\missing.py", "PROJECT DONE: fine"])
        def leader(p, h, m, **k):
            logs.append(p); return next(lead)
        groups.main_engine = leader
        bots.engine = lambda p, h, m, **k: "DONE: built"
        said = groups.run_group(g, "make an app", [], lambda e: None)
        self.assertEqual([s for s, _ in said], ["pedro", "pedro", "writer", "pedro", "pedro"])
        self.assertIn("no member has reported DONE", logs[1])
        self.assertIn("these files don't exist: C:\\nope\\missing.py", logs[3])
        self.assertEqual(groups._done_problem("PROJECT DONE: C:\\nope\\x.py", True), "these files don't exist: C:\\nope\\x.py.")
        self.assertEqual(groups._done_problem("PROJECT DONE: summary", True), "")

    def test_a_plain_assignment_runs_that_bot_now(self):
        g = groups.save_group({"name": "T", "members": ["writer", "editor"]})
        lead = iter([
            "I'll assign Writer to draft 3 facts about owls.",
            "PROJECT DONE: saved",
        ])
        seen = []

        def eng(prompt, history, model, **kw):
            seen.append(prompt)
            if "LEADER" in prompt:
                return next(lead)
            return "DONE: drafted the facts"

        bots.engine = eng
        groups.main_engine = eng
        said = groups.run_group(g, "Make a short note about owls", [], lambda e: None)
        self.assertEqual([s for s, _ in said], ["pedro", "writer", "pedro"])
        self.assertIn("draft 3 facts about owls", seen[1])

    def test_a_direct_bot_that_hands_off_runs_the_other_bot(self):
        g = groups.save_group({"name": "T", "members": ["writer", "editor"]})
        seen = []

        def eng(prompt, history, model, **kw):
            seen.append(prompt)
            if "addressed YOU (Writer)" in prompt:
                return "I'll let Editor check the rhyme."
            return "DONE: the rhyme checks out"

        bots.engine = eng
        groups.main_engine = lambda *a, **k: self.fail("the leader does not take a direct message")
        said = groups.run_group(g, "@writer write a haiku about owls", [], lambda e: None)
        self.assertEqual([s for s, _ in said], ["writer", "editor"])
        self.assertIn("check the rhyme", seen[1])

    def test_a_refusal_or_a_maybe_does_not_hand_off(self):
        g = groups.save_group({"name": "T", "members": ["writer", "editor"]})
        self.assertIsNone(groups.promised_job("I will not assign Writer to draft it.", g, "pedro"))
        self.assertIsNone(groups.promised_job("Maybe Editor could check it later.", g, "pedro"))
        self.assertIsNone(groups.promised_job("Sounds like a fun project!", g, "pedro"))
        who, task = groups.promised_job("Let Editor check the file.", g, "writer")
        self.assertEqual(who, "editor")
        self.assertEqual(task, "check the file")

    def test_at_all_greeting_stays_a_quick_round(self):
        g = groups.save_group({"name": "T", "members": ["writer"]})
        groups.main_engine = lambda p, h, m, **k: "hi" if "LEADER" not in p else self.fail("no loop for hi")
        bots.engine = lambda p, h, m, **k: "hey"
        self.assertEqual(len(groups.run_group(g, "@all hi", [], lambda e: None)), 2)
