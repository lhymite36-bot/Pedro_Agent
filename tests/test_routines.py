import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import confirm_action
import routines

T0 = time.mktime((2026, 10, 15, 6, 40, 0, 0, 0, -1))   # Thu 15 Oct 2026 06:40 local


class RoutineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = mock.patch.object(routines, "ROOT", Path(self.tmp.name))
        self.root.start()
        self.now = T0
        routines.now_override = lambda: self.now
        routines.runner = None
        confirm_action.answer_pending("no", lambda *a: None) if confirm_action.pending() else None

    def tearDown(self):
        routines.now_override = None
        routines.runner = None
        self.root.stop()
        self.tmp.cleanup()

    def test_parse_when(self):
        p = lambda w: routines.parse_when(w, T0)
        self.assertEqual(p("every day at 7 PM"), {"kind": "daily", "time": "19:00", "days": list(range(7))})
        self.assertEqual(p("weekdays at 8:30 am")["days"], [0, 1, 2, 3, 4])
        self.assertEqual(p("every monday at 9am")["days"], [0])
        self.assertEqual(p("tomorrow 9 AM"), {"kind": "once", "at": "2026-10-16 09:00"})
        self.assertEqual(p("in 10 minutes"), {"kind": "once", "at": "2026-10-15 06:50"})
        self.assertEqual(p("Friday 6 PM"), {"kind": "once", "at": "2026-10-16 18:00"})
        self.assertEqual(p("every 2 hours"), {"kind": "every", "minutes": 120})
        with self.assertRaises(ValueError):
            p("whenever you feel like it")

    def test_next_run(self):
        s = routines.parse_when("every day at 7 PM", T0)
        self.assertEqual(time.strftime("%Y-%m-%d %H:%M", time.localtime(routines.next_run(s, T0))), "2026-10-15 19:00")
        once = routines.parse_when("in 10 minutes", T0)
        self.assertIsNone(routines.next_run(once, T0 + 3600, T0 + 700))

    def test_crud_and_list(self):
        r = routines.create_routine("Hello", "Say hello", "in 10 minutes")
        self.assertTrue(r["ok"], r)
        self.assertIn("Hello", routines.list_routines()["message"])
        self.assertTrue(routines.pause_routine("Hello")["ok"])
        self.assertTrue(routines.find("Hello")["paused"])
        self.assertEqual(routines.due(T0 + 3600), [])
        self.assertTrue(routines.resume_routine("Hello")["ok"])
        self.assertTrue(routines.update_routine("Hello", when="tomorrow 9 AM")["ok"])
        self.assertEqual(routines.find("Hello")["schedule"]["at"], "2026-10-16 09:00")

    def test_delete_needs_approval(self):
        routines.create_routine("Temp", "x", "tomorrow 9 AM")
        res = routines.delete_routine("Temp")
        self.assertTrue(res.get("needs_confirmation"))
        self.assertIsNotNone(routines.find("Temp"))
        confirm_action.answer_pending("no", lambda *a: None)
        self.assertIsNotNone(routines.find("Temp"))
        routines.delete_routine("Temp")
        confirm_action.answer_pending("yes", lambda name, args: routines.TOOLS[name](**args))
        self.assertIsNone(routines.find("Temp"))

    def test_tick_runs_with_runner_and_feed(self):
        seen = []
        routines.runner = lambda r: seen.append(r["prompt"]) or "hello Pedro"
        routines.create_routine("Hello", "Say hello", "in 10 minutes")
        self.assertEqual(routines.tick(), [])
        self.now = T0 + 11 * 60
        out = routines.tick()
        self.assertEqual(seen, ["Say hello"])
        self.assertEqual(out[0]["status"], "ok")
        r = routines.find("Hello")
        self.assertEqual(r["last_status"], "ok")
        self.assertIsNone(r["next_run"])           # one-time routine is done
        self.assertEqual(routines.tick(), [])
        feed = routines.feed(0)
        self.assertEqual(feed[-1]["routine"], "Hello")

    def test_failure_recorded(self):
        def boom(r):
            raise RuntimeError("nope")
        routines.runner = boom
        routines.create_routine("Bad", "x", "in 5 minutes")
        self.now = T0 + 6 * 60
        self.assertEqual(routines.tick()[0]["status"], "failed")
        self.assertEqual(routines.find("Bad")["last_status"], "failed")

    def test_builtin_wingz_seed_once(self):
        import extras148
        with mock.patch.object(extras148, "_load", return_value={}):
            routines.seed_builtin()
            routines.seed_builtin()
        rs = [r for r in routines._load()["routines"] if r["id"] == routines.WINGZ_ID]
        self.assertEqual(len(rs), 1)
        self.assertEqual(rs[0]["schedule"]["time"], "19:00")
        routines._remove(routines.WINGZ_ID)
        routines.seed_builtin()
        self.assertIsNone(routines.find(routines.WINGZ_ID))   # deleting it is respected

    def test_builtin_runs_evening_check(self):
        import extras148
        with mock.patch.object(extras148, "_load", return_value={}):
            routines.seed_builtin()
        with mock.patch.object(extras148, "evening_check", return_value={"message": "report"}) as ec, \
             mock.patch.object(extras148, "_save"):
            self.now = T0 + 13 * 3600
            out = routines.tick()
        ec.assert_called_once()
        self.assertEqual(out[0]["message"], "report")

    def test_chat_app_routes_and_ui(self):
        import chat_app
        self.assertIn("routines_ui.js", chat_app.STATIC_FILES)
        html = (Path(chat_app.STATIC) / "index.html").read_text(encoding="utf-8")
        self.assertIn("/routines_ui.js", html)
        routines.create_routine("Temp", "x", "tomorrow 9 AM")
        rid = routines.find("Temp")["id"]
        self.assertFalse(chat_app.routine_action({"id": rid, "action": "delete"})["ok"])   # no confirm -> refused
        self.assertTrue(chat_app.routine_action({"id": rid, "action": "pause"})["ok"])
        self.assertTrue(chat_app.routine_action({"id": rid, "action": "delete", "confirm": True})["ok"])
        self.assertIsNone(routines.find(rid))

    def test_tools_registered(self):
        import agent_core
        names = [d["name"] for d in agent_core.TOOL_DECLARATIONS]
        for n in routines.TOOLS:
            self.assertIn(n, agent_core.TOOLS)
        self.assertEqual(len(names), len(set(names)))


if __name__ == "__main__":
    unittest.main()
