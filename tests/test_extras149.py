import json
import tempfile
import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import extras148  # noqa: E402
import extras149  # noqa: E402
import task_memory  # noqa: E402


class Extras149Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.old = (extras148.ROOT, extras149.ROOT, extras148.shot_override)
        extras148.ROOT = extras149.ROOT = self.tmp
        extras148.shot_override = None
        self.shots = []
        extras149.grab_override = lambda path, box: (self.shots.append(box), Path(path).write_bytes(b"jpg"))
        extras149.windows_override = lambda: [
            ("Pedro Agent", (0, 0, 800, 600), True),
            ("Power_BI_Tips.pdf - Google Chrome", (10, 10, 900, 700), False),
            ("Wingz - Personal - Microsoft Edge", (0, 0, 1366, 740), False)]
        self.tm_old = task_memory.PATH
        task_memory.PATH = self.tmp / "tm.json"

    def tearDown(self):
        extras148.ROOT, extras149.ROOT, extras148.shot_override = self.old
        extras149.grab_override = extras149.windows_override = None
        task_memory.PATH = self.tm_old

    def test_proof_never_shoots_the_agent_window(self):
        r = extras148.record_step_proof("pdf task", "made pdf", "opened in Chrome")
        self.assertEqual(r["window"], "Power_BI_Tips.pdf - Google Chrome")
        self.assertEqual(self.shots[-1], (10, 10, 900, 700))

    def test_proof_targets_named_window(self):
        r = extras148.record_step_proof("pdf task", "scan", "list read", window="wingz")
        self.assertIn("Wingz", r["window"])
        log = json.loads((self.tmp / "proof_log.json").read_text(encoding="utf-8"))
        self.assertIn("Wingz", log[-1]["window"])

    def test_missing_window_is_noted(self):
        extras148.record_step_proof("pdf task", "x", "c", window="Notepad")
        log = json.loads((self.tmp / "proof_log.json").read_text(encoding="utf-8"))
        self.assertIn("'Notepad' not found", log[-1]["check"])

    def test_review_flags_unbacked_claims_and_missing_files(self):
        f = self.tmp / "out.pdf"; f.write_bytes(b"%PDF data")
        extras148.record_step_proof("pdf task", "made pdf", "Power BI tips pdf opened in Chrome")
        r = extras149.review_work("pdf task", claims=["Power BI tips PDF opened in Chrome", "Uploaded to Wingz portal"],
                                  files=[str(f), str(self.tmp / "nope.docx")])
        self.assertEqual(r["verdict"], "needs attention")
        self.assertTrue(any("Could not verify: Uploaded" in p for p in r["problems"]))
        self.assertTrue(any("nope.docx" in p for p in r["problems"]))
        self.assertTrue(any("Backed by proof: Power BI" in c for c in r["checked"]))

    def test_review_flags_agent_window_screenshot(self):
        extras149.windows_override = lambda: [("Pedro Agent", (0, 0, 8, 6), True)]
        extras148.record_step_proof("t", "s", "c", window="Pedro Agent")
        log = json.loads((self.tmp / "proof_log.json").read_text(encoding="utf-8"))
        log[-1]["window"] = "Pedro Agent"; (self.tmp / "proof_log.json").write_text(json.dumps(log))
        r = extras149.review_work("t")
        self.assertTrue(any("shows this app" in p for p in r["problems"]))

    def test_review_flags_search_page_instead_of_file(self):
        f = self.tmp / "Power_BI_Tips.pdf"; f.write_bytes(b"%PDF")
        extras149.windows_override = lambda: [(":\\uSERS\\pOWER_bi_tIPS.PDF - Search - Microsoft Edge", (0, 0, 900, 700), True)]
        extras148.record_step_proof("t2", "PDF opened", "PDF opened", window="Power_BI_Tips.pdf")
        r = extras149.review_work("t2", claims=["PDF opened"], files=[str(f)])
        self.assertEqual(r["verdict"], "needs attention")
        self.assertTrue(any("web search" in p for p in r["problems"]))
        self.assertTrue(any("No proof screenshot shows Power_BI_Tips.pdf" in p for p in r["problems"]))

    def test_open_local_file_only_documents(self):
        opened = []
        extras149.open_override = opened.append
        try:
            f = self.tmp / "a.pdf"; f.write_bytes(b"%PDF")
            self.assertTrue(extras149.open_local_file(str(f))["ok"])
            exe = self.tmp / "x.exe"; exe.write_bytes(b"MZ")
            self.assertFalse(extras149.open_local_file(str(exe))["ok"])
            self.assertFalse(extras149.open_local_file(str(self.tmp / "missing.pdf"))["ok"])
        finally:
            extras149.open_override = None
        self.assertEqual(opened, [str(f)])

    def test_review_pass(self):
        f = self.tmp / "a.xlsx"; f.write_bytes(b"x")
        self.assertEqual(extras149.review_work("t", files=[str(f)])["verdict"], "pass")

    def test_skills_roundtrip_and_safety(self):
        self.assertTrue(extras149.save_task_skill("Weekly Excel report", ["open data.xlsx", "make chart", "save"], "Mondays")["ok"])
        self.assertIn("Weekly Excel report", extras149.list_task_skills()["message"])
        u = extras149.use_task_skill("weekly excel")
        self.assertEqual(u["steps"][1], "make chart")
        self.assertFalse(extras149.save_task_skill("bad", ["type the password"])["ok"])
        self.assertFalse(extras149.save_task_skill("bad2", ["submit test answers"])["ok"])
        self.assertTrue(extras149.forget_task_skill("Weekly Excel report")["ok"])
        self.assertFalse(extras149.use_task_skill("weekly excel")["ok"])

    def test_checklist_never_shows_key_values(self):
        import os
        os.environ["GROQ_API_KEY"] = "gsk_secret_value_123"
        try:
            r = extras149.setup_checklist()
        finally:
            del os.environ["GROQ_API_KEY"]
        self.assertNotIn("gsk_secret", json.dumps(r))
        self.assertTrue(any(i["item"].startswith("Backup") and i["ok"] for i in r["items"]))

    def test_tools_registered(self):
        names = {d["name"] for d in extras149.DECLARATIONS}
        self.assertEqual(names, set(extras149.TOOLS))
        props = next(d for d in extras148.DECLARATIONS if d["name"] == "record_step_proof")["parameters"]["properties"]
        self.assertIn("window", props)


if __name__ == "__main__":
    unittest.main()


class RegistrationTests(unittest.TestCase):
    def test_no_duplicate_tool_names_in_the_agent(self):
        import collections
        try:
            import agent_core as agent
        except ImportError:
            import agent_core as agent
        dup = [k for k, v in collections.Counter(d["name"] for d in agent.TOOL_DECLARATIONS).items() if v > 1]
        self.assertEqual(dup, [])
        for name in extras149.TOOLS:
            self.assertIn(name, agent.TOOLS)


class PhoneVoiceAndSetupUiTests(unittest.TestCase):
    def test_phone_mic_uses_phone_not_pc_microphone(self):
        root = Path(__file__).resolve().parents[1]
        js = (root / "app_static" / "app.js").read_text(encoding="utf-8")
        self.assertIn("webkitSpeechRecognition", js)
        self.assertIn("if (ON_PC) hands.listen(true); else phoneListen();", js)
        self.assertNotIn("base64,", js)
        html = (root / "app_static" / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="setup-check"', html)
        self.assertIn("/api/checklist", (root / "chat_app.py").read_text(encoding="utf-8"))
