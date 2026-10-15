"""1.4.10: ask_user question cards and Approve/Deny cards in chats and groups."""
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import confirm_action  # noqa: E402
import polls  # noqa: E402
import rules  # noqa: E402
try:
    import agent_core as agent  # noqa: E402
except ImportError:
    import agent_core as agent  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


class PollTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.old = polls.ROOT; polls.ROOT = Path(self.tmp.name); polls.begin_turn(); confirm_action.reset()

    def tearDown(self):
        polls.ROOT = self.old; confirm_action.reset(); self.tmp.cleanup()

    def test_single_choice(self):
        r = polls.ask_user("Which size?", ["S", "M", "L", "M"])
        self.assertTrue(r["ok"] and r["stop"])
        c = polls.get(r["card_id"]); self.assertEqual(c["options"], ["S", "M", "L"])
        self.assertFalse(polls.answer(c["id"], ["XL"])["ok"])
        a = polls.answer(c["id"], ["M", "L"])
        self.assertEqual(a["text"], '(Answer to "Which size?") M')
        self.assertFalse(polls.answer(c["id"], ["S"])["ok"])          # answers once
        self.assertEqual(polls.get(c["id"])["status"], "answered")

    def test_multi_and_other(self):
        c = polls.get(polls.ask_user("Toppings?", ["Cheese", "Olives", "Corn"], multi_select=True, allow_other=True)["card_id"])
        a = polls.answer(c["id"], ["Cheese", "Corn"], other="extra chilli")
        self.assertEqual(a["text"], '(Answer to "Toppings?") Cheese, Corn, extra chilli')
        c2 = polls.get(polls.ask_user("Where?", ["Home"], allow_other=True)["card_id"])
        self.assertIn("Office", polls.answer(c2["id"], [], other="Office")["text"])

    def test_limits(self):
        self.assertFalse(polls.ask_user("", ["a", "b"])["ok"])
        self.assertFalse(polls.ask_user("Q?", ["only one"])["ok"])
        r = polls.ask_user("Q?", [str(i) for i in range(9)])
        self.assertFalse(r["ok"])

    def test_approval_card_expires_when_not_waiting(self):
        confirm_action.remember("delete_path", {"path": "C:/x.txt"}, "delete C:/x.txt")
        c = polls.approval_card("delete C:/x.txt", "delete_path")
        self.assertEqual(polls.view(c["id"], confirm_action.pending())["status"], "open")
        self.assertEqual(polls.view(c["id"], None)["status"], "expired")
        a = polls.answer(c["id"], decision="approve"); self.assertEqual(a["text"], "yes")
        c2 = polls.approval_card("send email", "gmail_send_message")
        self.assertEqual(polls.answer(c2["id"], decision="deny")["text"], "no")
        self.assertFalse(polls.answer(c2["id"], decision="approve")["ok"])

    def test_registered_and_prompted(self):
        self.assertIn("ask_user", agent.TOOLS)
        src = (ROOT / ("agent_core.py" if (ROOT / "agent_core.py").exists() else "agent_core.py")).read_text(encoding="utf-8")
        self.assertIn("call ask_user", src)


class CardChatTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        root = Path(self.tmp.name); (root / "rules.json").write_text("{}", encoding="utf-8")
        self.env = mock.patch.dict(os.environ, {"RULES_FILE": str(root / "rules.json"), "STORAGE_DIR": str(root / "s"),
                                                "BOTS_DIR": str(root / "b"), "GROUPS_DIR": str(root / "g")})
        self.env.start(); rules.reset_cache(); confirm_action.reset()
        self.old = polls.ROOT; polls.ROOT = root

    def tearDown(self):
        polls.ROOT = self.old; self.env.stop(); rules.reset_cache(); confirm_action.reset()
        import chat_store
        chat_store.close(); self.tmp.cleanup()

    def test_question_card_round_trip_over_http(self):
        import chat_app
        server, state = chat_app.serve("m", 0)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{server.server_address[1]}"
        seen = []
        def model(text, history, m, **kw):
            seen.append(text)
            if len(seen) == 1:
                agent.invoke_tool("ask_user", {"question": "Which phone case colour?", "options": ["Black", "Blue"]})
                return "Which colour do you want?"
            return f"Got it: {text}"
        def post(path, body):
            req = urllib.request.Request(base + path, json.dumps(body).encode(), {"Content-Type": "application/json", "Origin": base})
            return json.loads(urllib.request.urlopen(req, timeout=5).read())
        try:
            ev = []
            with mock.patch.object(agent, "run_agent", model):
                chat_app.stream_turn(state, "c1", "order a phone case", ev.append, speak=False)
            cards = [e["card"] for e in ev if e.get("event") == "card"]
            self.assertEqual(len(cards), 1); self.assertEqual(cards[0]["options"], ["Black", "Blue"])
            rows = json.loads(urllib.request.urlopen(base + "/api/history?session=c1", timeout=5).read())
            self.assertEqual(rows[-1]["card"]["id"], cards[0]["id"])          # survives reload
            a = post("/api/card/answer", {"id": cards[0]["id"], "choices": ["Blue"]})
            self.assertTrue(a["ok"]); self.assertIn("Blue", a["text"])
            self.assertFalse(post("/api/card/answer", {"id": cards[0]["id"], "choices": ["Black"]})["ok"])
            with mock.patch.object(agent, "run_agent", model):
                chat_app.stream_turn(state, "c1", a["text"], ev.append, speak=False)
            self.assertIn("Blue", seen[-1])
            got = json.loads(urllib.request.urlopen(base + "/api/card?id=" + cards[0]["id"], timeout=5).read())
            self.assertEqual(got["card"]["status"], "answered")
        finally:
            chat_app.shutdown(server)

    def test_approval_card_for_a_waiting_delete(self):
        import chat_app
        state = chat_app.AppState("m")
        deleted = []
        fake = lambda path, recursive=False: (deleted.append(path), agent._ok(f"Deleted {path}."))[1]
        def model(text, history, m, **kw):
            agent.begin_task_turn(text)
            agent.invoke_tool("delete_path", {"path": "C:\\\\Users\\\\x\\\\Desktop\\\\old.txt"})
            return "Should I delete it?"
        with mock.patch.dict(agent.TOOLS, {"delete_path": fake}), mock.patch.object(agent, "run_agent", model):
            ev = []
            chat_app.stream_turn(state, "c2", "delete old.txt on my desktop", ev.append, speak=False)
            cards = [e["card"] for e in ev if e.get("event") == "card"]
            self.assertEqual(len(cards), 1, ev); self.assertEqual(cards[0]["kind"], "approval")
            self.assertEqual(cards[0]["status"], "open")
            a = polls.answer(cards[0]["id"], decision="approve")
            ev2 = []
            chat_app.stream_turn(state, "c2", a["text"], ev2.append, speak=False)
        self.assertEqual(len(deleted), 1)
        self.assertEqual(polls.view(cards[0]["id"], confirm_action.pending())["status"], "answered")


class CardUiTests(unittest.TestCase):
    def test_ui(self):
        js = (ROOT / "app_static" / "app.js").read_text(encoding="utf-8")
        for want in ("function renderCard", "/api/card/answer", "pa-btn primary", "pa-btn danger", "ev.event === 'card'", "if (m.card)"):
            self.assertIn(want, js)
        self.assertIn(".pa-opt.sel", (ROOT / "app_static" / "app.css").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
