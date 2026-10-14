import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import task_runner as tr


def png(color=(200, 220, 255), size=(400, 300)):
    from PIL import Image
    b = io.BytesIO(); Image.new("RGB", size, color).save(b, "PNG"); return b.getvalue()


class TaskRunnerTests(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.p = mock.patch.object(tr, "_storage", return_value=Path(self.d.name))
        self.p.start()
        tr.grab_png = lambda: png(); tr.sleep = lambda s: None
        self.pressed = []; tr.keys = lambda *k: self.pressed.append(k)
        self.pasted = []; tr.paste_text = self.pasted.append
        self.clip = []; tr.set_clipboard_file = self.clip.append
        self.opened = []; tr.open_url = lambda b, u: self.opened.append(b)

    def tearDown(self):
        self.p.stop(); self.d.cleanup()
        for k in ("grab_png", "vision", "keys", "paste_text", "set_clipboard_file", "open_url"):
            setattr(tr, k, None)
        tr._wa.clear()

    def test_graded_tests_refused(self):
        self.assertTrue(tr.start_task("Take my graded quiz on Canvas")["refused"])
        self.assertTrue(tr.start_task("answer the exam questions")["refused"])
        self.assertTrue(tr.start_task("do the self-learn Power BI assignment (ungraded)")["ok"])
        self.assertEqual(tr.start_task("do my Power BI assignment and send to Maya as pdf")["suggested_routine"],
                         "assignment-to-pdf-whatsapp")

    def test_screenshot_crop_and_document(self):
        full = tr.capture_screenshot_file("a")
        crop = tr.capture_screenshot_file("b", crop=[0, 0, 500, 500])
        self.assertEqual((crop["width"], crop["height"]), (200, 150))
        self.assertFalse(tr.capture_screenshot_file("c", crop=[0, 0, 1, 1])["ok"])
        out = Path(self.d.name) / "desk"
        r = tr.make_document("Power BI: 1-to-many!", [{"text": "Load <tables>", "image": full["path"]},
                                                    {"text": "Model view", "image": crop["path"]}], folder=str(out))
        self.assertTrue(r["ok"]); self.assertTrue(r["path"].endswith("Power_BI_1-to-many.pdf"))
        self.assertGreater(Path(r["path"]).stat().st_size, 1000)
        r2 = tr.make_document("Power BI: 1-to-many!", ["only text"], folder=str(out))
        self.assertNotEqual(r2["path"], r["path"])  # never overwrites by default
        r3 = tr.make_document("Notes", [{"text": "x", "image": full["path"]}], format="docx", folder=str(out))
        self.assertTrue(r3["path"].endswith(".docx") and Path(r3["path"]).is_file())
        self.assertFalse(tr.make_document("x", [{"text": "a", "image": "/nope.png"}], folder=str(out))["ok"])
        self.assertFalse(tr.make_document("x", [], folder=str(out))["ok"])

    def test_verify_retries_then_passes(self):
        answers = iter(["NO still loading", "NO", "YES it shows the model view"])
        tr.vision = lambda q, img: next(answers)
        r = tr.verify_screen("the Model view", retries=3)
        self.assertTrue(r["verified"]); self.assertEqual(r["attempts"], 3)
        tr.vision = lambda q, img: "NO"
        self.assertFalse(tr.verify_screen("x", retries=1)["verified"])

    def test_whatsapp_checks_name_and_never_sends_in_prepare(self):
        f = Path(self.d.name) / "a.pdf"; f.write_bytes(b"%PDF-1.4")
        def v(q, img):
            return "Maya✨" if "exact name" in q else "YES"
        tr.vision = v
        r = tr.whatsapp_prepare("Maya", str(f), "Here's the PDF", browser="edge")
        self.assertTrue(r["ok"]); self.assertEqual(self.opened, ["edge"])
        self.assertEqual(self.clip, [str(f.resolve())]); self.assertIn("Here's the PDF", self.pasted)
        self.assertEqual(self.pressed[-1], ("ctrl", "v"))  # staged, not sent
        self.assertFalse(tr.whatsapp_send_now("Bob")["ok"])
        self.assertTrue(tr.whatsapp_send_now("Maya")["ok"]); self.assertEqual(self.pressed[-1], ("enter",))
        self.assertFalse(tr.whatsapp_send_now("Maya")["ok"])  # nothing staged twice

    def test_whatsapp_wrong_contact_stops(self):
        tr.vision = lambda q, img: "Maya Kumar" if "exact name" in q else "YES"
        f = Path(self.d.name) / "a.pdf"; f.write_bytes(b"x")
        r = tr.whatsapp_prepare("Maya Sharma", str(f), browser="edge")
        self.assertFalse(r["ok"]); self.assertEqual(self.clip, [])

    def test_whatsapp_not_logged_in(self):
        tr.vision = lambda q, img: "NO, QR code"
        r = tr.whatsapp_prepare("Maya", caption="hi")
        self.assertFalse(r["ok"]); self.assertEqual(self.opened, ["edge", "chrome", "firefox", "brave"])

    def test_routines_save_list_get_delete(self):
        self.assertFalse(tr.save_task_routine("one", steps=["a"])["ok"])
        self.assertTrue(tr.save_task_routine("Weekly report", "make it", ["open excel", "save pdf"])["ok"])
        names = [r["name"] for r in tr.list_task_routines()["routines"]]
        self.assertIn("weekly-report", names); self.assertIn("assignment-to-pdf-whatsapp", names)
        self.assertEqual(tr.get_task_routine("weekly report")["routine"]["steps"][1], "save pdf")
        self.assertFalse(tr.delete_task_routine("assignment-to-pdf-whatsapp")["ok"])
        self.assertTrue(tr.delete_task_routine("weekly-report")["ok"])

    def test_store_app_lookup(self):
        apps = [{"Name": "Power BI Desktop", "AppID": "Microsoft.MicrosoftPowerBIDesktop_8wekyb3d8bbwe!Microsoft.MicrosoftPowerBIDesktop"},
                {"Name": "Calculator", "AppID": "Microsoft.WindowsCalculator_8wekyb3d8bbwe!App"}]
        self.assertTrue(tr.store_app_id("power bi", apps).startswith("Microsoft.MicrosoftPowerBI"))
        self.assertEqual(tr.store_app_id("calculater", apps), "Microsoft.WindowsCalculator_8wekyb3d8bbwe!App")
        self.assertEqual(tr.store_app_id("photoshop", apps), "")

    def test_rules_gate_sends_deletes_purchases(self):
        import rules
        self.assertEqual(rules.category_for("whatsapp_send_now", {}), "send_message")
        self.assertEqual(rules.category_for("confirm_before", {"kind": "purchase"}), "payment")
        self.assertEqual(rules.category_for("confirm_before", {"kind": "delete"}), "delete")
        self.assertEqual(rules.category_for("confirm_before", {"kind": "submit"}), "send_message")
        self.assertIsNone(rules.category_for("whatsapp_prepare", {}))

    def test_tools_registered(self):
        import gta5_agent
        for n in tr.TOOLS:
            self.assertIn(n, gta5_agent.TOOLS)
        self.assertEqual({d["name"] for d in tr.DECLARATIONS}, set(tr.TOOLS))
