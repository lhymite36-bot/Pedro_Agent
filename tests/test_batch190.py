"""1.9.0 Batch 2: Pro flags, phone planner, autopilot, memory, team, skills, home, income."""
import json, os, sys, tempfile, time, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class ProFlags(unittest.TestCase):
    def setUp(self):
        os.environ["STORAGE_DIR"] = tempfile.mkdtemp()
        import pro190
        self.pro = pro190

    def test_risky_defaults_off(self):
        f = self.pro.flags()["flags"]
        self.assertFalse(f["phone_control"])
        self.assertFalse(f["pc_autopilot"])
        self.assertFalse(f["self_skills"])
        self.assertTrue(f["memory"])
        self.assertTrue(f["income"])

    def test_need_blocks_when_off(self):
        r = self.pro.dispatch({"tool": "autopilot", "action": "status"})
        self.assertFalse(r["ok"])
        self.assertIn("Advanced", r["error"])

    def test_flag_toggle_persists(self):
        self.pro.flags({"pc_autopilot": True})
        self.assertTrue(self.pro.flag("pc_autopilot"))
        r = self.pro.dispatch({"tool": "autopilot", "action": "status"})
        self.assertTrue(r["ok"])

    def test_assets_wired(self):
        import chat_app
        for f in ("pro190.js", "pro190.css"):
            self.assertIn(f, chat_app.STATIC_FILES)
            self.assertTrue((ROOT / "app_static" / f).is_file(), f)
        src = (ROOT / "chat_app.py").read_text(encoding="utf-8")
        self.assertIn("/api/pro", src)
        html = (ROOT / "app_static" / "index.html").read_text(encoding="utf-8")
        self.assertIn("pro190.js", html)


class PhoneDrive(unittest.TestCase):
    def test_local_plan_youtube_search(self):
        import phone_drive
        r = phone_drive.plan("open YouTube and search cooking shorts")
        self.assertTrue(r["ok"])
        actions = [s["action"] for s in r["steps"]]
        self.assertIn("open", actions)
        self.assertTrue(any(s.get("text") and "cooking" in s["text"].casefold() for s in r["steps"]) or "type" in actions)

    def test_sensitive_bank_and_password(self):
        import phone_drive
        self.assertTrue(phone_drive.is_sensitive({"package": "com.phonepe.app"})["sensitive"])
        self.assertTrue(phone_drive.is_sensitive({"package": "com.android.chrome", "password": True})["sensitive"])
        self.assertTrue(phone_drive.is_sensitive("Please enter your UPI PIN")["sensitive"])
        self.assertFalse(phone_drive.is_sensitive({"package": "com.google.android.youtube", "text": "Search"})["sensitive"])

    def test_empty_command(self):
        import phone_drive
        self.assertFalse(phone_drive.plan("")["ok"])


class SeeClick(unittest.TestCase):
    def test_step_mode_waits_for_allow(self):
        os.environ["PEDBOT_TEST"] = "1"
        import see_click
        see_click.screenshot_fn = lambda: b"PNG"
        see_click.vision_fn = lambda img, goal: {"done": False, "action": "click", "target": "Save", "preview": "I'm about to click Save"}
        see_click.act_fn = lambda step: {"ok": True, "did": "click Save"}
        see_click.stop("reset")
        r = see_click.start("click save", mode="step")
        self.assertTrue(r["ok"])
        for _ in range(40):
            st = see_click.status()
            if st.get("pending"):
                break
            time.sleep(0.05)
        self.assertTrue(see_click.status().get("pending"))
        self.assertIn("Save", see_click.status()["pending"]["preview"])
        see_click.vision_fn = lambda img, goal: {"done": True, "preview": "Done."}
        see_click.allow()
        for _ in range(40):
            if not see_click.status()["running"]:
                break
            time.sleep(0.05)
        see_click.stop("done")

    def test_no_key_path(self):
        import see_click
        see_click.vision_fn = None
        see_click.screenshot_fn = None
        old = os.environ.pop("GEMINI_API_KEY", None)
        try:
            r = see_click.start("open notepad")
            self.assertFalse(r["ok"])
            self.assertIn("key", r["error"].casefold())
        finally:
            if old is not None:
                os.environ["GEMINI_API_KEY"] = old


class Memory(unittest.TestCase):
    def setUp(self):
        os.environ["STORAGE_DIR"] = tempfile.mkdtemp()
        import bot_ltm
        self.m = bot_ltm
        self.m.embed_override = self.m.local_embed

    def test_add_search_edit_delete_export(self):
        self.assertTrue(self.m.add("alpha", "Pedro makes Shorts and Tableau dashboards")["ok"])
        self.assertFalse(self.m.add("alpha", "password: hunter2")["ok"])
        hit = self.m.search("alpha", "shorts", k=5)
        self.assertTrue(hit["facts"])
        self.assertIn("Shorts", hit["facts"][0]["text"])
        item = self.m.listing("alpha")["items"][0]
        self.assertTrue(self.m.edit("alpha", item["id"], "Pedro makes YouTube Shorts")["ok"])
        self.assertFalse(self.m.delete("alpha", item["id"], confirm=False)["ok"])
        self.assertTrue(self.m.delete("alpha", item["id"], confirm=True)["ok"])
        self.assertEqual(self.m.listing("alpha")["count"], 0)
        self.m.add("alpha", "Lives in India")
        ex = self.m.export("alpha")
        self.assertTrue(ex["ok"])
        self.assertIn("India", ex["text"])

    def test_prompt_facts_respects_flag(self):
        import pro190
        self.m.add("default", "Favourite colour is blue")
        pro190.flags({"memory": True})
        self.assertIn("blue", self.m.prompt_facts("default", "colour"))
        pro190.flags({"memory": False})
        self.assertEqual(self.m.prompt_facts("default", "colour"), "")


class TeamBoard(unittest.TestCase):
    def test_progress_and_who(self):
        import team_board
        team_board.run_override = lambda goal: {
            "ok": True, "summary": "done",
            "results": [{"role": "research", "task": "find ideas", "result": "3 ideas"}],
        }
        r = team_board.start("plan three shorts")
        self.assertTrue(r["ok"])
        jid = r["job"]
        for _ in range(50):
            s = team_board.status(jid)
            if s.get("status") in {"done", "failed"}:
                break
            time.sleep(0.05)
        s = team_board.status(jid)
        self.assertEqual(s["status"], "done")
        self.assertIn("Who did what", s.get("answer") or "")


class Skills(unittest.TestCase):
    def setUp(self):
        os.environ["STORAGE_DIR"] = tempfile.mkdtemp()
        import skill_forge
        self.s = skill_forge
        self.s.write_override = lambda task: {
            "ok": True, "name": "wordcount", "title": "Word count",
            "code": "def run(text):\n    return str(len(text.split()))\n",
            "test": "hello world", "lang": "python",
        }

    def test_sandbox_and_approve(self):
        d = self.s.draft("count words")
        self.assertTrue(d["ok"])
        self.assertTrue(d["draft"]["test_ok"])
        self.assertEqual(d["draft"]["test_result"], "2")
        self.assertTrue(self.s.approve(d["draft"]["id"])["ok"])
        live = self.s.listing()["live"]
        self.assertTrue(live[0]["enabled"])
        self.assertTrue(self.s.disable(live[0]["id"], False)["ok"])
        self.assertFalse(self.s.listing()["live"][0]["enabled"])
        self.assertTrue(self.s.undo()["ok"])

    def test_blocks_secrets_and_system(self):
        bad = self.s._is_safe_code("import os\nos.system('rm -rf /')\n", "python")
        self.assertTrue(bad)
        bad2 = self.s._is_safe_code("open('/etc/passwd').read(); GEMINI_API_KEY", "python")
        self.assertTrue(bad2)


class Home(unittest.TestCase):
    def test_parse_and_music_links(self):
        import hey_home
        self.assertEqual(hey_home.parse_seconds("timer 5 minutes"), 300)
        hey_home.run_override = lambda kind, **kw: {"ok": True, "kind": kind, **kw}
        r = hey_home.try_handle("play lofi on youtube music")
        self.assertTrue(r["ok"])
        self.assertIn("youtube_music", r.get("links") or r)
        self.assertIsNone(hey_home.try_handle("what is the capital of Ghana"))
        paused = hey_home.try_handle("volume up", battery=10)
        self.assertTrue(paused.get("paused"))

    def test_lock_and_volume_override(self):
        import hey_home
        hey_home.run_override = lambda kind, **kw: {"ok": True, "kind": kind}
        self.assertEqual(hey_home.try_handle("lock the pc")["kind"], "lock")
        self.assertEqual(hey_home.try_handle("volume up")["kind"], "volume")


class Income(unittest.TestCase):
    def setUp(self):
        os.environ["STORAGE_DIR"] = tempfile.mkdtemp()
        import income_gigs
        self.g = income_gigs
        self.g.fetch_override = self._fetch

    def _fetch(self, url):
        if "remoteok" in url:
            return json.dumps([
                {"legal": "notice"},
                {"position": "Tableau dashboard for a Shorts studio", "company": "Acme",
                 "url": "https://remoteok.com/x", "tags": ["data", "tableau"], "description": "Build dashboards"},
                {"position": "Java Spring banker", "company": "Bank", "url": "https://remoteok.com/y",
                 "tags": ["java"], "description": "Spring"},
            ])
        rss = """<?xml version="1.0"?><rss><channel>
          <item><title>Android app for YouTube Shorts</title><link>https://example.com/1</link><description>apps</description></item>
        </channel></rss>"""
        return rss

    def test_search_filters_skills(self):
        r = self.g.search("tableau, shorts, apps")
        self.assertTrue(r["ok"])
        titles = " ".join(j["title"] for j in r["jobs"])
        self.assertIn("Tableau", titles)
        self.assertNotIn("Spring banker", titles)

    def test_draft_without_key(self):
        old = os.environ.pop("GEMINI_API_KEY", None)
        try:
            r = self.g.draft({"title": "Shorts editor", "description": "edit shorts"})
            self.assertTrue(r["ok"])
            self.assertIn("Pedro", r["draft"])
            self.assertIn("yourself", r["note"].casefold())
        finally:
            if old is not None:
                os.environ["GEMINI_API_KEY"] = old

    def test_earnings(self):
        self.assertTrue(self.g.earnings("add", 40, "one Short")["ok"])
        self.assertEqual(self.g.earnings("list")["total"], 40)


class VoiceAndLive(unittest.TestCase):
    def setUp(self):
        os.environ["STORAGE_DIR"] = tempfile.mkdtemp()

    def test_voice_needs_consent(self):
        import voice_real
        st = voice_real.status()
        self.assertFalse(st["consent"])
        r = voice_real.speak("hello")
        self.assertFalse(r["ok"])
        self.assertIn("consent", r["error"].casefold())

    def test_live_label_and_qa_gate(self):
        import live_twin
        frames = []
        live_twin.send_fn = lambda f: frames.append(True)
        st = live_twin.start("qa")
        self.assertTrue(st["ok"])
        self.assertEqual(st["mode"], "qa")
        out = live_twin.handle("speak", {"text": "I can join at 5", "approve": False})
        self.assertTrue(out.get("needs_approve"))
        self.assertIn("I can join at 5", out.get("preview") or "")
        live_twin.stop()


class AndroidPackaging(unittest.TestCase):
    def test_service_and_version(self):
        man = (ROOT / "android_app" / "AndroidManifest.xml").read_text(encoding="utf-8")
        self.assertIn("PedAccessibilityService", man)
        self.assertIn('android:versionName="1.9.0"', man)
        self.assertTrue((ROOT / "android_app" / "src" / "com" / "pedro" / "agent" / "PedAccessibilityService.java").is_file())
        self.assertTrue((ROOT / "android_app" / "res" / "xml" / "accessibility_service.xml").is_file())


if __name__ == "__main__":
    unittest.main()
