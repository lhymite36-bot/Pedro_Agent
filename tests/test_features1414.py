"""1.4.14: live sync, safe mode, crash reports, updater, Google connections, Blender docs."""

import hashlib
import io
import json
import os
import sqlite3
import tempfile
import threading
import time
import unittest
import zipfile
from pathlib import Path
from unittest import mock


class _Storage(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"STORAGE_DIR": self.tmp.name})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()


class LiveSyncTests(unittest.TestCase):
    def setUp(self):
        import live_sync
        live_sync.reset()
        self.ls = live_sync

    def test_events_are_numbered_and_caught_up_after_a_drop(self):
        a = self.ls.publish("s1", {"event": "token", "text": "Hi"}, origin="pc")
        self.ls.publish("s1", {"event": "saved"})
        items, gap = self.ls.since(a)
        self.assertFalse(gap)
        self.assertEqual([e["event"] for e in items], ["saved"])
        self.assertEqual(items[0]["session"], "s1")

    def test_audio_is_not_mirrored(self):
        self.ls.publish("s1", {"event": "audio", "url": "x"})
        self.assertEqual(self.ls.current(), 0)

    def test_wait_wakes_on_new_event(self):
        got = []
        t = threading.Thread(target=lambda: got.extend(self.ls.wait(0, timeout=5)[0]))
        t.start()
        time.sleep(0.1)
        self.ls.notify("changed", what="react")
        t.join(3)
        self.assertEqual(got[0]["event"], "changed")

    def test_gap_reported_when_ring_overflowed(self):
        for i in range(self.ls.RING + 10):
            self.ls.publish("s", {"event": "token"})
        _items, gap = self.ls.since(1)
        self.assertTrue(gap)


class LiveFeedHttpTests(unittest.TestCase):
    def test_feed_streams_with_ids_over_http(self):
        import http.client
        import live_sync
        from http.server import ThreadingHTTPServer
        import chat_app

        live_sync.reset()
        state = chat_app.AppState("test-model")
        handler = chat_app.make_handler(state) if hasattr(chat_app, "make_handler") else None
        if handler is None:
            self.skipTest("no handler factory")
        srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            live_sync.publish("chat1", {"event": "saved", "role": "assistant"})
            c = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=5)
            c.request("GET", "/api/live?since=0")
            r = c.getresponse()
            self.assertEqual(r.status, 200)
            self.assertIn("event-stream", r.getheader("Content-Type"))
            buf = b""
            while b'"saved"' not in buf:
                buf += r.read1(4096)
            self.assertIn(b"id: 1", buf)
            self.assertIn(b'"session": "chat1"', buf)
            c.close()
        finally:
            srv.shutdown()


class SafeModeTests(_Storage):
    def test_pause_refuses_tools_and_routines_then_resume(self):
        import safe_mode
        import routines
        safe_mode._loaded = False
        safe_mode._paused = None
        state = mock.Mock()
        r = safe_mode.pause_all(state, by="phone")
        self.assertTrue(r["paused"])
        state.cancel_all.assert_not_called()   # 1.4.15: running chats freeze at a safe point instead
        self.assertTrue(safe_mode.paused())
        self.assertIsNotNone(safe_mode.refuse("ui_click"))
        self.assertIsNone(safe_mode.refuse("ask_user"))
        self.assertEqual(routines.due(now=time.time() + 10**9), [])
        safe_mode._loaded = False          # survives a restart
        self.assertTrue(safe_mode.paused())
        safe_mode.resume_all(state)
        self.assertFalse(safe_mode.paused())
        self.assertIsNone(safe_mode.refuse("ui_click"))

    def test_invoke_tool_is_blocked_while_paused(self):
        import agent_core
        import safe_mode
        safe_mode._loaded = False
        safe_mode._paused = None
        safe_mode.pause_all(None)
        try:
            out = agent_core.invoke_tool("type_text", {"text": "x"})
            self.assertFalse(out["ok"])
            self.assertTrue(out.get("paused"))
        finally:
            safe_mode.resume_all(None)


class CrashReportTests(_Storage):
    def test_report_saved_locally_and_secrets_hidden(self):
        import crash_reports
        try:
            raise ValueError("boom api_key=AIzaSyA1234567890123456789012345 password: hunter2")
        except ValueError as exc:
            path = crash_reports.record(exc, "test")
        text = path.read_text(encoding="utf-8")
        self.assertIn("Ped Bot 1.5.2 crash report", text)
        self.assertIn("ValueError", text)
        self.assertNotIn("AIzaSy", text)
        self.assertNotIn("hunter2", text)
        names = [r["name"] for r in crash_reports.listing()]
        self.assertIn(path.name, names)
        self.assertEqual(crash_reports.read(path.name), text)
        self.assertEqual(crash_reports.read("../secret.txt"), "")

    def test_nothing_is_sent(self):
        import crash_reports
        src = Path(crash_reports.__file__).read_text(encoding="utf-8")
        self.assertNotIn("urlopen", src)
        self.assertNotIn("requests", src)


class UpdaterTests(_Storage):
    def _release(self, data, version="1.5.2", good=True):
        sha = hashlib.sha256(data).hexdigest() if good else "0" * 64
        return [{"tag_name": "v1.4.13-windows", "assets": []},
                {"tag_name": f"v{version}-windows", "draft": False, "prerelease": False, "html_url": "u",
                 "body": f"SHA-256\n{sha}  PedBot-Setup-{version}.exe\n",
                 "assets": [{"name": f"PedBot-Setup-{version}.exe", "browser_download_url": "https://x/s.exe"}]}]

    def test_newer_release_downloads_verifies_and_installs_only_with_yes(self):
        import updater
        data = b"MZ fake installer"
        updater.fetch_json = lambda url: self._release(data)
        updater.fetch_file = lambda url, dest: Path(dest).write_bytes(data)
        try:
            info = updater.check("1.4.14")
            self.assertTrue(info["update_available"])
            self.assertIn("Update available", info["message"])
            got = updater.download()
            self.assertTrue(got["ok"], got)
            self.assertFalse(updater.install("")["ok"])
            ran = []
            self.assertTrue(updater.install("yes", launcher=ran.append)["ok"])
            self.assertEqual(Path(ran[0][0]).read_bytes(), data)
        finally:
            updater.fetch_json = updater.fetch_file = None

    def test_hash_mismatch_is_deleted(self):
        import updater
        updater.fetch_json = lambda url: self._release(b"x", good=False)
        updater.fetch_file = lambda url, dest: Path(dest).write_bytes(b"tampered")
        try:
            updater.check("1.4.14")
            got = updater.download()
            self.assertFalse(got["ok"])
            self.assertIn("did not match", got["error"])
            self.assertEqual(list(updater.folder().glob("*.exe")), [])
        finally:
            updater.fetch_json = updater.fetch_file = None

    def test_same_version_is_up_to_date(self):
        import updater
        updater.fetch_json = lambda url: self._release(b"x", version="1.4.14")
        try:
            self.assertFalse(updater.check("1.4.14")["update_available"])
        finally:
            updater.fetch_json = None


class ConnectionsTests(_Storage):
    def test_connect_saves_token_locally_and_disconnect_deletes_it(self):
        import google_connections as gc
        import urllib.request

        calls = []

        def http(method, url, data, headers):
            calls.append(url)
            return 200, json.dumps({"access_token": "a", "refresh_token": "r", "expires_in": 3600}).encode()

        def browser(url):
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(url).query)
            self.assertEqual(q["code_challenge_method"], ["S256"])
            self.assertIn("gmail.send", q["scope"][0])
            threading.Thread(target=lambda: urllib.request.urlopen(
                q["redirect_uri"][0] + "?state=" + q["state"][0] + "&code=abc", timeout=5).read()).start()

        with mock.patch.dict(os.environ, {"GOOGLE_CLIENT_ID": "id", "GOOGLE_CLIENT_SECRET": "sec"}):
            gc.http, gc.open_browser = http, browser
            try:
                r = gc.connect("gmail", wait_seconds=10)
                self.assertTrue(r["ok"], r)
                self.assertTrue(gc.token_file("gmail").is_file())
                self.assertTrue(str(gc.token_file("gmail")).startswith(self.tmp.name))
                st = {s["id"]: s["connected"] for s in gc.status()["services"]}
                self.assertTrue(st["gmail"])
                self.assertFalse(st["drive"])
                gc.disconnect("gmail")
                self.assertFalse(gc.token_file("gmail").exists())
            finally:
                gc.http, gc.open_browser = None, __import__("webbrowser").open

    def test_without_client_it_explains_setup(self):
        import google_connections as gc
        with mock.patch.dict(os.environ, {"GOOGLE_CLIENT_ID": "", "YOUTUBE_CLIENT_ID": "",
                                          "GOOGLE_CLIENT_SECRET": "", "YOUTUBE_CLIENT_SECRET": ""}):
            r = gc.connect("drive")
        self.assertFalse(r["ok"])
        self.assertIn("Desktop app", r["error"])


class BlenderDocsTests(_Storage):
    def _zip(self, pages):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            for name, (title, body) in pages.items():
                z.writestr(name, f"<html><head><title>{title} — Blender Manual</title></head><body>"
                                 f"<nav>menu</nav><div role=\"main\"><h1>{title}</h1><p>{body}</p></div></body></html>")
        return buf.getvalue()

    def test_downloads_once_indexes_and_searches(self):
        import blender_docs
        fetched = []
        manual = self._zip({"m/modeling/modifiers/generate/bevel.html": ("Bevel Modifier",
                            "The Bevel modifier bevels the edges of the mesh, width and segments control the shape.")})
        api = self._zip({"a/bpy.ops.uv.html": ("Uv Operators", "bpy.ops.uv.smart_project(angle_limit=1.15) unwraps.")})

        def fetch(url, dest):
            fetched.append(url)
            Path(dest).write_bytes(manual if "manual" in url else api)

        blender_docs.fetch, blender_docs.version_override = fetch, "4.2"
        try:
            r = blender_docs.blender_docs_search("bevel modifier segments")
            self.assertTrue(r["ok"], r)
            self.assertEqual(r["results"][0]["title"], "Bevel Modifier")
            self.assertTrue(r["results"][0]["url"].startswith("https://docs.blender.org/manual/en/4.2/"))
            self.assertIn("4.2/blender_manual_html.zip", fetched[0])
            self.assertIn("blender_python_reference_4_2.zip", fetched[1])
            r2 = blender_docs.blender_docs_search("smart_project", source="api")
            self.assertEqual(r2["results"][0]["source"], "api")
            blender_docs.blender_docs_search("uv")
            self.assertEqual(len(fetched), 2)                 # downloaded only once
            self.assertEqual(list(blender_docs.folder().glob("*.zip")), [])   # zips removed after indexing
            g = blender_docs.blender_docs_search("retopology shrinkwrap", source="guide")
            self.assertTrue(g["results"])
        finally:
            blender_docs.fetch, blender_docs.version_override = None, None

    def test_all_expert_guides_present(self):
        import blender_docs
        topics = {p.stem for p in blender_docs.GUIDES.glob("*.md")}
        for t in ["modelling", "sculpting", "retopology", "uv", "materials_nodes", "texture_painting_baking",
                  "lighting", "cameras", "rendering", "animation", "rigging", "geometry_nodes", "physics",
                  "compositing", "vse", "grease_pencil", "import_export", "addons"]:
            self.assertIn(t, topics)
        self.assertTrue(blender_docs.blender_guide("UV")["ok"])

    def test_docs_are_not_bundled(self):
        root = Path(__file__).resolve().parents[1]
        self.assertEqual(list(root.rglob("blender_manual_html*.zip")), [])

    def test_tools_registered(self):
        import agent_core
        names = {d["name"] for d in agent_core.TOOL_DECLARATIONS}
        self.assertTrue({"blender_docs_search", "blender_guide", "drive_search"} <= names)


class NoReaNoSigningTests(unittest.TestCase):
    def test_no_signing_hook_and_no_rea(self):
        root = Path(__file__).resolve().parents[1]
        nsi = (root / "installer").glob("*.nsi")
        for p in nsi:
            t = p.read_text(encoding="utf-8", errors="ignore").lower()
            self.assertNotIn("signtool", t)
            self.assertNotIn("!finalize", t)


if __name__ == "__main__":
    unittest.main()


def test_no_tool_enum_has_an_empty_value():
    """Gemini rejects the whole request (400) if any enum value is an empty string."""
    import re
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    bad = []
    for f in root.glob("*.py"):
        for m in re.finditer(r'"enum":\s*\[([^\]]*)\]', f.read_text(encoding="utf-8")):
            if re.search(r'(^|,)\s*""\s*(,|$)', m.group(1)):
                bad.append(f.name)
    assert not bad, bad


def test_plan_survives_tool_worker_thread():
    import agent_core as a
    a._set_turn("demo", None)
    r = a._call_with_timeout("create_task_plan", a.create_task_plan, {"goal": "g", "steps": ["one", "two"]})
    assert r.get("ok"), r
    r2 = a._call_with_timeout("complete_plan_step", a.complete_plan_step, {"step": 1})
    assert r2.get("ok"), r2
    a._set_turn("", None)


def test_progress_final_is_honest_when_last_step_failed():
    import progress_notes as pn
    said = []
    n = pn.Narrator("close notepad", lambda k, t: said.append((k, t)), clock=iter(range(0, 1000, 20)).__next__)
    for name, ok in (("launch_application", True), ("write_text_file", True), ("take_screenshot", True), ("kill_process", False)):
        n.feed({"event": "tool_end", "name": name, "ok": ok, "detail": "Waiting for a yes before kill notepad." if not ok else "fine"})
    text = n.finish("Not done yet.")
    assert text.startswith("Not finished yet"), text
    assert not any(".." in t for _, t in said)


def test_review_work_accepts_this_turns_tool_results(tmp_path, monkeypatch):
    import agent_core as a, extras149
    f = tmp_path / "speedtest_after.txt"
    f.write_text("Ped Bot speed test after", encoding="utf-8")
    a._turn_local.tool_notes = ["launch application notepad Opened notepad.",
                                "type text Ped Bot speed test after Typed 24 character(s)."]
    try:
        r = extras149.review_work("notepad test", ["Opened Notepad", "Typed 'Ped Bot speed test after'"], [str(f)])
    finally:
        a._turn_local.tool_notes = []
    assert "Could not verify" not in str(r), r


def test_copy_button_on_every_message_and_jump_to_latest():
    from pathlib import Path
    js = (Path(__file__).resolve().parents[1] / "app_static" / "app.js").read_text(encoding="utf-8")
    css = (Path(__file__).resolve().parents[1] / "app_static" / "app.css").read_text(encoding="utf-8")
    user = js[js.index("function addUser("):js.index("function addBot(")]
    assert "addCopy(row)" in user                     # Pedro's own messages too
    assert "Copied" in js and "touchstart" in js       # toast + phone long-press
    assert "jump-latest" in js and "jl-badge" in js and "pbScrolledUp" in js
    assert "#jump-latest" in css and "#pb-toast" in css
