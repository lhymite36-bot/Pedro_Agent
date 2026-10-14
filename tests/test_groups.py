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
            said = groups.run_group(g, "endless project", [], ev.append)
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
        g = groups.save_group({"name": "P", "picture": pic, "color": "#123456", "avatar": "cat"})
        saved = groups.get_group(g["id"])
        self.assertEqual((saved["picture"], saved["color"], saved["avatar"]), (pic, "#123456", "cat"))
        g2 = groups.save_group({**saved, "picture": "", "color": "bad", "avatar": "dragon"})
        self.assertEqual((g2["picture"], g2["color"], g2["avatar"]), ("", "#5b9dff", "round"))
        for bad in ("javascript:alert(1)", "data:image/svg+xml;base64,PHN2Zz4=", "data:image/png;base64," + "A" * 300000):
            with self.assertRaises(ValueError):
                groups.save_group({"name": "Q", "picture": bad})
