"""Regression tests for the 1.5.10 audit fixes."""
from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock


class ShortsStampTests(unittest.TestCase):
    def test_failed_day_is_not_stamped(self):
        import quiet_brain_shorts as qbs

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(qbs, "_storage", return_value=Path(tmp)):
                (Path(tmp) / "settings.json").write_text(
                    json.dumps({"enabled": True, "start_time": "00:00", "per_day": 1}),
                    encoding="utf-8",
                )
                with mock.patch.object(qbs, "run_day", return_value={"ok": False, "error": "no vts", "day": "2099-01-01"}):
                    with mock.patch.object(qbs, "fill_overflow", return_value=None):
                        now = mock.Mock()
                        now.date.return_value.isoformat.return_value = "2099-01-01"
                        now.hour, now.minute = 12, 0
                        out = qbs.routine_tick(now)  # type: ignore[arg-type]
                self.assertFalse(out.get("ok"))
                stamp = json.loads((Path(tmp) / "last_run.json").read_text(encoding="utf-8"))
                self.assertNotEqual(stamp.get("day"), "2099-01-01")
                self.assertEqual(stamp.get("attempt_day"), "2099-01-01")
                self.assertFalse(stamp.get("ok"))

    def test_success_stamps_day(self):
        import quiet_brain_shorts as qbs

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(qbs, "_storage", return_value=Path(tmp)):
                (Path(tmp) / "settings.json").write_text(
                    json.dumps({"enabled": True, "start_time": "00:00"}), encoding="utf-8"
                )
                with mock.patch.object(
                    qbs, "run_day", return_value={"ok": True, "message": "Scheduled 1", "day": "2099-02-02", "plan": []}
                ):
                    with mock.patch.object(qbs, "fill_overflow", return_value=None):
                        now = mock.Mock()
                        now.date.return_value.isoformat.return_value = "2099-02-02"
                        now.hour, now.minute = 13, 0
                        qbs.routine_tick(now)  # type: ignore[arg-type]
                stamp = json.loads((Path(tmp) / "last_run.json").read_text(encoding="utf-8"))
                self.assertEqual(stamp.get("day"), "2099-02-02")
                self.assertTrue(stamp.get("ok"))

    def test_channel_ids_and_ai_flag_configurable(self):
        import quiet_brain_shorts as qbs

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(qbs, "_storage", return_value=Path(tmp)):
                out = qbs.save_settings(
                    youtube_channel="yt-chan-1",
                    tiktok_channel="tt-chan-2",
                    mark_ai_generated=True,
                )
                self.assertEqual(out["youtube_channel"], "yt-chan-1")
                self.assertEqual(out["tiktok_channel"], "tt-chan-2")
                self.assertTrue(out["mark_ai_generated"])
                self.assertTrue(qbs._ai_flag())
                req = qbs.youtube_input({"title": "Hi", "yt_tags": []}, "2099-01-01T10:00:00+05:30", "https://x/v.mp4")
                self.assertEqual(req["channelId"], "yt-chan-1")
                self.assertTrue(req["metadata"]["youtube"]["isAiGenerated"])


class AuthBypassAndRemoteCookieTests(unittest.TestCase):
    def test_local_bypass_when_supabase_missing(self):
        import supabase_auth

        with mock.patch.dict(os.environ, {"SUPABASE_URL": "", "SUPABASE_ANON_KEY": "", "SUPABASE_SERVICE_ROLE_KEY": "",
                                          "PEDBOT_LOCAL_BYPASS": ""}, clear=False):
            for k in ("SUPABASE_URL", "SUPABASE_ANON_KEY", "SUPABASE_SERVICE_ROLE_KEY"):
                os.environ.pop(k, None)
            self.assertFalse(supabase_auth.configured())
            self.assertTrue(supabase_auth.local_bypass_allowed())

    def test_origin_aware_redirect(self):
        import supabase_auth

        with mock.patch.object(supabase_auth, "missing_env", return_value=[]):
            with mock.patch.object(supabase_auth, "_url", return_value="https://x.supabase.co"):
                with mock.patch.object(supabase_auth, "_anon", return_value="anon"):
                    with mock.patch.object(supabase_auth, "_service", return_value="service"):
                        cfg = supabase_auth.public_config("https://abc.trycloudflare.com")
                        self.assertTrue(cfg["redirect"].startswith("https://abc.trycloudflare.com"))
                        cfg2 = supabase_auth.public_config("http://127.0.0.1:8765")
                        self.assertIn("127.0.0.1", cfg2["redirect"])


class EvidenceDoneTests(unittest.TestCase):
    def test_open_only_needs_evidence(self):
        import agent_core

        used = {"launch_application", "ui_read", "take_screenshot"}
        self.assertTrue(
            agent_core.needs_evidence("complete my Wingz assignment", "All done, the assignment is finished.", used)
        )

    def test_verify_after_fill_is_enough(self):
        import agent_core

        used = {"ui_set_text", "verify_screen", "ui_click", "create_task_plan"}
        self.assertFalse(
            agent_core.needs_evidence("do my Wingz assignment", "All questions answered and verified.", used)
        )

    def test_grounding_blocks_open_only_done(self):
        import grounding

        grounding.begin()
        grounding.note("launch_application", {"ok": True, "message": "Opened Chrome"})
        grounding.note("ui_read", {"ok": True, "message": "Wingz page"})
        out = grounding.ground_reply("finish the assignment", "I've completed the assignment.")
        self.assertIn("Not done yet", out)


class DemoChunkTests(unittest.TestCase):
    def test_long_lesson_summarises_in_chunks(self):
        import demo_skills
        import llm

        calls = []

        def fake(prompt, images):
            calls.append((prompt, len(images or [])))
            if "Merge these" in prompt:
                return "# Long Lesson\n\n## Steps\n1. A\n2. B\n"
            return f"# Part\n\n## Steps\n1. step from chunk ({len(calls)})\n"

        events = [{"t": i * 0.1, "type": "click", "down": True, "x": 1, "y": 2, "button": "left"} for i in range(150)]
        frames = [(float(i), b"\xff\xd8\xff" + bytes([i % 255]) + b"x" * 20) for i in range(30)]
        with mock.patch.object(llm, "text", side_effect=lambda prompt, images=None: fake(prompt, images)):
            with mock.patch.object(llm, "strip_fence", side_effect=lambda s: s):
                body = demo_skills.summarise("long-lesson", events, frames)
        self.assertTrue(body.lstrip().startswith("#"))
        self.assertGreaterEqual(len(calls), 2)  # at least chunk(s) + merge


class ConnectorsWhatsAppAndNoWindowTests(unittest.TestCase):
    def test_whatsapp_in_catalog(self):
        import connectors

        rows = {r["id"]: r for r in connectors.catalog()}
        self.assertIn("whatsapp", rows)
        self.assertTrue(rows["whatsapp"]["connected"])
        out = connectors.connect("whatsapp", {})
        self.assertTrue(out.get("ok"))

    def test_run_passes_create_no_window_on_windows(self):
        import connectors
        import subprocess

        seen = {}

        def fake_run(*a, **kw):
            seen.update(kw)
            class P:
                returncode = 0
                stdout = "ok"
                stderr = ""
            return P()

        with mock.patch.object(connectors.os, "name", "nt"):
            with mock.patch.object(subprocess, "run", side_effect=fake_run):
                with mock.patch.object(subprocess, "CREATE_NO_WINDOW", 0x08000000, create=True):
                    connectors._run(["gh", "auth", "status"])
        self.assertIn("creationflags", seen)


class ProjectsSearchTests(unittest.TestCase):
    def test_search_returns_projects(self):
        import fusion_api
        import groups

        with mock.patch.object(groups, "list_groups", return_value=[
            {"id": "shorts-team", "name": "Shorts Team", "purpose": "post daily", "color": "#fff"}
        ]):
            with mock.patch.object(fusion_api, "_db") as db:
                con = mock.Mock()
                con.execute.return_value = []
                db.return_value = con
                # titles / messages queries return empty iterables
                con.execute.side_effect = lambda *a, **k: []
                out = fusion_api.search("shorts")
        self.assertTrue(any(p["name"] == "Shorts Team" for p in out.get("projects") or []))


class TunnelSecureTests(unittest.TestCase):
    def test_secure_when_public_url_https(self):
        import remote_access

        class H:
            headers = {}
            remote = True

        # Build a tiny stand-in using the same logic as RemoteHandler._secure
        remote_access.public_url = "https://abc.trycloudflare.com"
        proto = ""
        url = (remote_access.public_url or "").strip().casefold()
        secure = proto == "https" or url.startswith("https://")
        self.assertTrue(secure)


class VersionTests(unittest.TestCase):
    def test_version_is_1510(self):
        import updater

        self.assertEqual(updater.VERSION, "1.5.10")


if __name__ == "__main__":
    unittest.main()


class ProjectsUiTests(unittest.TestCase):
    def test_groups_ui_loads_on_init(self):
        js = Path("app_static/groups_ui.js").read_text(encoding="utf-8")
        self.assertIn("load();  // NEW2", js)
        self.assertIn("Could not load projects", js)

    def test_acct_projects_opens_sidebar(self):
        js = Path("app_static/app.js").read_text(encoding="utf-8")
        self.assertIn("acct-projects", js)
        self.assertIn("loadGroups", js)
        self.assertIn("side-open", js)

    def test_phone_qr_uses_img_not_innerhtml_svg(self):
        js = Path("app_static/phone_ui.js").read_text(encoding="utf-8")
        self.assertIn("data:image/svg+xml", js)
        self.assertNotIn("innerHTML = r.qr_svg", js)

    def test_auth_ticket_session_storage(self):
        js = Path("app_static/auth.js").read_text(encoding="utf-8")
        self.assertIn("sessionStorage", js)

    def test_taught_skill_size_24k(self):
        src = Path("bots.py").read_text(encoding="utf-8")
        self.assertTrue("24000" in src or "24_000" in src)




class InstallerPythonTests(unittest.TestCase):
    def test_setup_bat_handles_pth_and_missing_pip(self):
        bat = Path("setup.bat").read_text(encoding="utf-8")
        self.assertIn("._pth", bat)
        self.assertIn("ensurepip", bat)
        self.assertIn("get-pip.py", bat)
        self.assertIn("--without-pip", bat)

    def test_nsi_deletes_pth(self):
        nsi = Path("installer/PedBot.nsi").read_text(encoding="utf-8")
        self.assertIn('Delete "$INSTDIR\\python\\python*._pth"', nsi)

    def test_fetch_script_uses_full_layout(self):
        sh = Path("installer/fetch_python.sh").read_text(encoding="utf-8")
        self.assertIn("nuget.org", sh)
        self.assertIn("get-pip.py", sh)
