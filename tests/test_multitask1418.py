import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import confirm_action
import model_pool
import shared_memory
import task_board


def _wait(pred, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.02)
    return False


class Board(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"STORAGE_DIR": self.tmp.name})
        self.env.start()
        task_board.reset()
        task_board.MAX_RUNNING = 5
        self.posted = []
        task_board.poster = lambda s, t: self.posted.append((s, t))
        task_board.stopper = None

    def tearDown(self):
        task_board.runner = task_board.planner = task_board.merger = None
        task_board.poster = None
        self.env.stop()
        self.tmp.cleanup()

    def test_tasks_run_in_parallel_up_to_the_limit(self):
        live, peak, lock = [0], [0], threading.Lock()

        def run(session, text, emit):
            with lock:
                live[0] += 1
                peak[0] = max(peak[0], live[0])
            emit({"event": "tool_start", "name": "list_files"})
            time.sleep(0.3)
            with lock:
                live[0] -= 1
            return "answer " + text

        task_board.runner = run
        task_board.MAX_RUNNING = 4
        t0 = time.time()
        ids = [task_board.add(f"job {i}", origin="chat-1")["id"] for i in range(6)]
        self.assertTrue(_wait(lambda: all(task_board.get(i)["status"] == "done" for i in ids)))
        took = time.time() - t0
        self.assertEqual(peak[0], 4)
        self.assertLess(took, 6 * 0.3)            # not one after another
        self.assertEqual(len(self.posted), 6)      # every answer goes back to the chat that asked
        self.assertTrue(shared_memory.get(f"task:{ids[0]}")["ok"])   # and into the shared notebook

    def test_each_task_has_its_own_session(self):
        seen = []
        task_board.runner = lambda s, t, e: seen.append(s) or "ok"
        a = task_board.add("one")["id"]
        b = task_board.add("two")["id"]
        _wait(lambda: len(seen) == 2)
        self.assertEqual(sorted(seen), sorted([f"task-{a}", f"task-{b}"]))

    def test_pause_holds_and_stop_ends(self):
        gate = threading.Event()

        def run(session, text, emit):
            emit({"event": "step", "label": "first"})
            gate.wait(2)
            emit({"event": "tool_start", "name": "x"})
            return "finished"

        task_board.runner = run
        tid = task_board.add("long")["id"]
        _wait(lambda: task_board.get(tid)["status"] == "running")
        task_board.control(tid, "pause")
        gate.set()
        self.assertTrue(_wait(lambda: task_board.get(tid)["status"] == "paused"))
        task_board.control(tid, "resume")
        self.assertTrue(_wait(lambda: task_board.get(tid)["status"] == "done"))

        stop_gate = threading.Event()
        task_board.runner = lambda s, t, e: stop_gate.wait(2) and "late"
        sid = task_board.add("to stop")["id"]
        _wait(lambda: task_board.get(sid)["status"] == "running")
        task_board.control(sid, "stop")
        stop_gate.set()
        time.sleep(0.1)
        self.assertEqual(task_board.get(sid)["status"], "stopped")

    def test_reorder_waiting_tasks(self):
        task_board.MAX_RUNNING = 1
        hold = threading.Event()
        task_board.runner = lambda s, t, e: hold.wait(2) and "ok"
        first = task_board.add("a")["id"]
        b = task_board.add("b")["id"]
        c = task_board.add("c")["id"]
        task_board.control(c, "up")
        order = [t["id"] for t in task_board.snapshot()["tasks"]]
        self.assertLess(order.index(c), order.index(b))
        hold.set()
        _wait(lambda: task_board.get(c)["status"] == "done")

    def test_manager_splits_runs_parts_in_parallel_and_merges(self):
        task_board.planner = lambda g: [{"role": "files", "task": f"part {i}"} for i in range(3)]
        task_board.merger = lambda g, rows: " | ".join(sorted(r["result"] for r in rows))
        task_board.runner = lambda s, t, e: (time.sleep(0.3), "done:" + t.split(" (This")[0])[1]
        t0 = time.time()
        mid = task_board.split("big job", origin="chat-9", wait=True)["id"]
        self.assertTrue(_wait(lambda: task_board.get(mid)["status"] == "done"))
        self.assertLess(time.time() - t0, 0.85)
        self.assertEqual(task_board.get(mid)["result"], "done:part 0 | done:part 1 | done:part 2")
        self.assertEqual(len(task_board.get(mid)["children"]), 3)
        self.assertEqual([p[0] for p in self.posted], ["chat-9"])

    def test_task_needing_approval_waits_on_the_board(self):
        def run(session, text, emit):
            token = confirm_action.bind_chat(session)
            try:
                if text == "yes":
                    confirm_action.drop_pending(session)
                    return "sent"
                confirm_action.remember("gmail_send_message", {"to": "x"}, "send an email to x")
                return "Please approve."
            finally:
                confirm_action.unbind_chat(token)

        task_board.runner = run
        tid = task_board.add("email x")["id"]
        self.assertTrue(_wait(lambda: task_board.get(tid)["status"] == "approval"))
        self.assertIn("send an email", task_board.get(tid)["needs"])
        task_board.control(tid, "approve")
        self.assertTrue(_wait(lambda: task_board.get(tid)["status"] == "done"))
        self.assertEqual(task_board.get(tid)["result"], "sent")

    def test_no_nested_tasks_from_inside_a_task(self):
        token = confirm_action.bind_chat("task-abc")
        try:
            self.assertFalse(task_board.start_background_task("x")["ok"])
        finally:
            confirm_action.unbind_chat(token)


class ApprovalsOneAtATime(unittest.TestCase):
    def tearDown(self):
        confirm_action.reset()

    def test_second_task_card_waits_for_the_first(self):
        confirm_action.APPROVAL_QUEUE_WAIT = 5
        t1 = confirm_action.bind_chat("task-1")
        confirm_action.remember("write_text_file", {"p": 1}, "write 1")
        confirm_action.unbind_chat(t1)
        done = threading.Event()

        def second():
            tok = confirm_action.bind_chat("task-2")
            confirm_action.remember("write_text_file", {"p": 2}, "write 2")
            confirm_action.unbind_chat(tok)
            done.set()

        threading.Thread(target=second, daemon=True).start()
        self.assertFalse(done.wait(0.6))
        confirm_action.drop_pending("task-1")
        self.assertTrue(done.wait(2))

    def test_chat_cards_are_never_held(self):
        t1 = confirm_action.bind_chat("task-1")
        confirm_action.remember("write_text_file", {"p": 1}, "write 1")
        confirm_action.unbind_chat(t1)
        tok = confirm_action.bind_chat("chat-main")
        t0 = time.time()
        confirm_action.remember("write_text_file", {"p": 3}, "write 3")
        confirm_action.unbind_chat(tok)
        self.assertLess(time.time() - t0, 0.2)


class ModelPool(unittest.TestCase):
    def setUp(self):
        model_pool.reset()

    def test_least_loaded_first_and_limit(self):
        for _ in range(20):
            model_pool.note("groq:openai/gpt-oss-120b")
        self.assertEqual(model_pool.order(["groq:openai/gpt-oss-120b", "groq:openai/gpt-oss-20b"])[0],
                         "groq:openai/gpt-oss-20b")
        for _ in range(10):
            model_pool.note("groq:openai/gpt-oss-120b")
        self.assertTrue(model_pool.at_limit("groq:openai/gpt-oss-120b"))
        self.assertFalse(model_pool.acquire("groq:openai/gpt-oss-120b", max_wait=0.1))
        self.assertTrue(model_pool.acquire("groq:openai/gpt-oss-20b", max_wait=0))


class SharedNotebook(unittest.TestCase):
    def test_share_and_read_but_never_secrets(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {"STORAGE_DIR": d}):
            self.assertTrue(shared_memory.put("dl", "50 files", by="Finder")["ok"])
            self.assertEqual(shared_memory.get("dl")["message"], "50 files")
            self.assertFalse(shared_memory.put("k", "password: hunter2")["ok"])
            self.assertIn("dl", shared_memory.read_shared("")["keys"])


if __name__ == "__main__":
    unittest.main()
