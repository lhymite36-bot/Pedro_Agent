"""Two chats can run at the same time. One bot no longer blocks the other."""

from __future__ import annotations

import os
import tempfile
import threading
import time
import unittest


class ParallelChatTests(unittest.TestCase):
    def test_two_sessions_overlap(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        previous = os.environ.get("STORAGE_DIR")
        os.environ["STORAGE_DIR"] = folder.name
        if previous is None:
            self.addCleanup(lambda: os.environ.pop("STORAGE_DIR", None))
        else:
            self.addCleanup(lambda: os.environ.__setitem__("STORAGE_DIR", previous))
        import agent_core
        import chat_app
        import chat_store

        chat_store.close()
        state = chat_app.AppState("m")
        gate = threading.Event()
        seen: list[str] = []
        original = agent_core.run_agent

        def fake_run(text, history, model, **kwargs):
            seen.append(text)
            self.assertTrue(gate.wait(timeout=3))
            return "ok " + text

        agent_core.run_agent = fake_run
        errors: list[BaseException] = []

        def run(session: str, text: str) -> None:
            try:
                chat_app.stream_turn(state, session, text, lambda _event: None, speak=False)
            except BaseException as exc:
                errors.append(exc)

        first = threading.Thread(target=run, args=("chat-a", "alpha"))
        second = threading.Thread(target=run, args=("chat-b", "beta"))
        try:
            first.start()
            second.start()
            deadline = time.monotonic() + 3
            while len(seen) < 2 and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertEqual(sorted(seen), ["alpha", "beta"])
            gate.set()
            first.join(timeout=5)
            second.join(timeout=5)
        finally:
            gate.set()
            agent_core.run_agent = original
            chat_store.close()
        self.assertEqual(errors, [])
        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())

    def test_stop_cancels_only_that_chat(self) -> None:
        import chat_app

        state = chat_app.AppState("m")
        one = state.session_cancel("chat-a")
        two = state.session_cancel("chat-b")
        state.cancel_session("chat-a")
        self.assertTrue(one.is_set())
        self.assertFalse(two.is_set())

    def test_yes_in_one_chat_does_not_clear_the_other(self) -> None:
        import confirm_action

        confirm_action.reset()
        first = confirm_action.bind_chat("bot-a")
        confirm_action.remember("delete_path", {"path": "a.txt"}, "delete a")
        confirm_action.unbind_chat(first)
        second = confirm_action.bind_chat("bot-b")
        confirm_action.note_user_text("hello there")
        confirm_action.unbind_chat(second)
        back = confirm_action.bind_chat("bot-a")
        try:
            self.assertEqual((confirm_action.pending() or {}).get("label"), "delete a")
        finally:
            confirm_action.unbind_chat(back)
            confirm_action.reset()

    def test_pointer_actions_do_not_overlap(self) -> None:
        import agent_core
        import desktop_share

        previous_pointer = agent_core.pointer_override
        previous_size = agent_core.screen_size_override
        agent_core.screen_size_override = (1000, 1000)
        order: list[str] = []
        started = threading.Event()
        release = threading.Event()
        errors: list[BaseException] = []

        def record(kind: str, details: dict[str, object]) -> None:
            name = threading.current_thread().name
            if name == "b":
                self.assertIn("a:end", order)
            order.append(name + ":start")
            if name == "a":
                started.set()
                self.assertTrue(release.wait(3))
            order.append(name + ":end")

        agent_core.pointer_override = record

        def click(name: str, x: int) -> None:
            try:
                desktop_share.bind(name)
                result = agent_core.click_element(x, 10)
                if not result.get("ok"):
                    errors.append(RuntimeError(str(result)))
            except BaseException as exc:
                errors.append(exc)

        first = threading.Thread(target=click, args=("a", 10), name="a")
        second = threading.Thread(target=click, args=("b", 20), name="b")
        try:
            first.start()
            self.assertTrue(started.wait(3))
            second.start()
            time.sleep(0.15)
            self.assertEqual(order, ["a:start"])
            release.set()
            first.join(3)
            second.join(3)
        finally:
            release.set()
            agent_core.pointer_override = previous_pointer
            agent_core.screen_size_override = previous_size
            desktop_share.reset()
        self.assertEqual(errors, [])
        self.assertEqual(order, ["a:start", "a:end", "b:start", "b:end"])
        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())

    def test_each_chat_returns_to_its_window(self) -> None:
        import agent_core
        import desktop_share

        previous_pointer = agent_core.pointer_override
        previous_size = agent_core.screen_size_override
        seen: list[int] = []
        desktop_share.focus_hook = seen.append
        desktop_share.remember(11, "bot-a")
        desktop_share.remember(22, "bot-b")
        agent_core.screen_size_override = (1000, 1000)
        agent_core.pointer_override = lambda _kind, _details: None
        try:
            first = desktop_share.bind("bot-a")
            self.assertTrue(agent_core.click_element(1, 1).get("ok"))
            desktop_share.unbind(first)
            second = desktop_share.bind("bot-b")
            self.assertTrue(agent_core.click_element(2, 2).get("ok"))
            desktop_share.unbind(second)
            self.assertEqual(seen, [11, 22])
        finally:
            agent_core.pointer_override = previous_pointer
            agent_core.screen_size_override = previous_size
            desktop_share.reset()

    def test_bot_sees_the_other_bots_window(self) -> None:
        import bots
        import desktop_share

        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        previous_bots = os.environ.get("BOTS_DIR")
        previous_files = os.environ.get("BOT_FILES_DIR")
        os.environ["BOTS_DIR"] = folder.name
        os.environ["BOT_FILES_DIR"] = folder.name
        if previous_bots is None:
            self.addCleanup(lambda: os.environ.pop("BOTS_DIR", None))
        else:
            self.addCleanup(lambda: os.environ.__setitem__("BOTS_DIR", previous_bots))
        if previous_files is None:
            self.addCleanup(lambda: os.environ.pop("BOT_FILES_DIR", None))
        else:
            self.addCleanup(lambda: os.environ.__setitem__("BOT_FILES_DIR", previous_files))
        ada = bots.save_bot({"name": "Ada", "role": "writes notes"})
        bots.save_bot({"name": "Bea", "role": "reads mail"})
        desktop_share.remember(22, "bot-" + str(bots.get_bot("bea")["id"]))
        desktop_share.title_hook = lambda hwnd: "Inbox - Mail" if int(hwnd) == 22 else ""
        bots._recent_paths[ada["id"]] = [r"C:\notes\ada.txt"]
        try:
            prompt = bots._prompt(ada, "check the desk")
        finally:
            bots._recent_paths.pop(ada["id"], None)
            desktop_share.reset()
        self.assertIn("How you work", prompt)
        self.assertIn("click_screen_target", prompt)
        self.assertIn("Bea (reads mail)", prompt)
        self.assertIn("Bea is using Inbox - Mail", prompt)
        self.assertNotIn("Ada is using", prompt)
        self.assertIn(r"C:\notes\ada.txt", prompt)

    def test_each_bot_keeps_its_own_cursor(self) -> None:
        import agent_core
        import bot_cursors
        import desktop_share

        seen: list[tuple[str, int, int]] = []
        previous = agent_core.pointer_override
        agent_core.pointer_override = lambda *_args: None
        bot_cursors.draw_hook = lambda owner, x, y, _name: seen.append((owner, x, y))
        try:
            first = desktop_share.bind("bot-a")
            bot_cursors.mark(10, 20)
            desktop_share.unbind(first)
            second = desktop_share.bind("bot-b")
            bot_cursors.mark(400, 300)
            desktop_share.unbind(second)
            self.assertEqual(bot_cursors.positions()["bot-a"], (10, 20))
            self.assertEqual(bot_cursors.positions()["bot-b"], (400, 300))
            third = desktop_share.bind("bot-a")
            bot_cursors.mark(12, 22)
            desktop_share.unbind(third)
            self.assertEqual(bot_cursors.positions()["bot-b"], (400, 300))
            self.assertEqual(seen[0], ("bot-a", 10, 20))
            self.assertEqual(seen[1], ("bot-b", 400, 300))
        finally:
            agent_core.pointer_override = previous
            bot_cursors.reset()

    def test_cursor_badge_leaves_after_the_click(self) -> None:
        import bot_cursors

        self.assertFalse(bot_cursors._should_hide(0, 0.2, (10, 10), (400, 400)))
        self.assertTrue(bot_cursors._should_hide(0, 0.5, (10, 10), (80, 10)))
        self.assertFalse(bot_cursors._should_hide(0, 0.5, (10, 10), (20, 16)))
        self.assertTrue(bot_cursors._should_hide(0, 1.0, (10, 10), (12, 12)))


if __name__ == "__main__":
    unittest.main()
