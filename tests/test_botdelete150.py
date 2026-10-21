import unittest
from unittest import mock
import bots, confirm_action, routines


class BotDeleteCleanup(unittest.TestCase):
    def test_pending_and_routines_cleared(self):
        confirm_action._pending_by["bot-gone"] = {"name": "youtube_upload", "arguments": {}, "label": "post", "id": "x1"}
        confirm_action._pending_by["bot-gone#task-1"] = {"name": "delete_path", "arguments": {}, "label": "d", "id": "x2"}
        rows = {"routines": [{"id": "r1", "name": "up", "target": "bot", "target_id": "gone", "paused": False},
                             {"id": "r2", "name": "keep", "target": "bot", "target_id": "other", "paused": False}]}
        paused = []
        with mock.patch.object(routines, "_load", return_value=rows), \
             mock.patch.object(routines, "pause_routine", side_effect=lambda rid: paused.append(rid) or {"ok": True}):
            out = bots.cleanup_after_delete("gone")
        self.assertEqual(out["approvals"], 2)
        self.assertNotIn("bot-gone", confirm_action._pending_by)
        self.assertEqual(paused, ["r1"])

    def test_orphan_routine_never_runs(self):
        with mock.patch.object(bots, "get_bot", return_value=None), \
             mock.patch.object(routines, "pause_routine", return_value={"ok": True}) as p:
            out = routines.run_routine({"id": "r9", "name": "x", "target": "bot", "target_id": "gone"})
        self.assertFalse(out["ok"]); p.assert_called_once_with("r9")


if __name__ == "__main__":
    unittest.main()
