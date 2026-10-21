import unittest
import agent_core, confirm_action, pc_fast_tools, cloud_fallback


class Grounding(unittest.TestCase):
    def test_claim_without_tool_is_flagged(self):
        out = agent_core.ground_reply("All done! The 10-second clip is saved.", [])
        self.assertIn("no action actually ran", out)

    def test_claim_with_failed_tool_names_it(self):
        out = agent_core.ground_reply("I've saved it to Documents.", [("record_pc_camera", False)])
        self.assertIn("record_pc_camera failed", out)

    def test_claim_with_success_kept(self):
        txt = "Recorded 10 s, saved to C:\\Users\\P\\Pictures\\Ped Bot\\camera.mp4"
        self.assertEqual(agent_core.ground_reply(txt, [("record_pc_camera", True)]), txt)

    def test_plain_chat_untouched(self):
        self.assertEqual(agent_core.ground_reply("Goldie is a nice name.", []), "Goldie is a nice name.")

    def test_voice_fast_path_skips_camera_requests(self):
        for t in ("Can you see me", "record 10 seconds", "take a photo", "Open it", "save that"):
            self.assertFalse(agent_core._voice_chat_only(t), t)
        self.assertTrue(agent_core._voice_chat_only("how are you this morning"))

    def test_camera_needs_card(self):
        for n in confirm_action.CAMERA_TOOLS:
            self.assertTrue(confirm_action.is_sensitive(n, {"seconds": 10}))
        self.assertIn("10 seconds", confirm_action.label_for("record_pc_camera", {"seconds": 10}))

    def test_known_folder_subpath(self):
        self.assertEqual(pc_fast_tools._folder("Documents\\PedroAgent"),
                         pc_fast_tools.known_folder("Documents") / "PedroAgent")
        self.assertEqual(pc_fast_tools._folder("my pictures/Ped Bot").name, "Ped Bot")

    def test_backup_gets_camera_tools(self):
        names = [t["function"]["name"] for t in cloud_fallback._tools("record me for 10 seconds")]
        self.assertIn("record_pc_camera", names)
        self.assertIn("webcam_vision_tool", names)


if __name__ == "__main__":
    unittest.main()


class ApprovalIds(unittest.TestCase):
    def setUp(self):
        confirm_action._pending_by.clear(); confirm_action._granted_by.clear(); confirm_action._denied.clear()

    def test_deny_by_id_blocks_reask_and_approve_runs_once(self):
        tok = confirm_action.bind_chat("s1")
        self.addCleanup(confirm_action.unbind_chat, tok)
        confirm_action.remember("capture_webcam_image", {}, "take one photo")
        p = confirm_action.all_pending()[0]
        ran = []
        out = confirm_action.resolve(p["id"], False, lambda n, a: ran.append(n) or {"ok": True})
        self.assertFalse(out["approved"]); self.assertEqual(ran, [])
        self.assertTrue(confirm_action.was_denied("capture_webcam_image", {}))
        self.assertFalse(confirm_action.resolve(p["id"], True, lambda n, a: ran.append(n) or {"ok": True})["resolved"])
        confirm_action._denied.clear()
        confirm_action.remember("record_pc_camera", {"seconds": 10}, "record 10 s")
        q = confirm_action.all_pending()[0]
        out = confirm_action.resolve(q["id"], True, lambda n, a: (ran.append(n), {"ok": True, "message": "Recorded.", "download_path": "C:/x.mp4"})[1])
        self.assertTrue(out["approved"]); self.assertEqual(ran, ["record_pc_camera"]); self.assertIn("C:/x.mp4", out["text"])
        self.assertEqual(confirm_action.all_pending(), [])
