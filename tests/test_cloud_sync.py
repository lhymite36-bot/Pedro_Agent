"""1.5.12 phone-only mode: PC side of the Supabase sync."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock


class CloudSyncTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        import agent_config
        self.p = mock.patch.object(agent_config, "storage_dir", return_value=Path(self.tmp.name))
        self.p.start()
        import cloud_sync
        cloud_sync._state.update(owner="u1", last_error="", pushed=0, pulled=0, running=False)

    def tearDown(self):
        self.p.stop()
        self.tmp.cleanup()

    def test_bot_payload_has_no_secrets_or_rules(self):
        import cloud_sync
        out = cloud_sync.bot_payload({"id": "a", "name": "A", "role": "r", "rules": {"x": 1}, "tasks": [1], "api_key": "k"})
        self.assertEqual(set(out), {"id", "name", "role"})

    def test_push_then_pull_no_echo(self):
        import chat_store
        import cloud_sync
        import supabase_auth

        chat_store.add("s1", "user", "hello from pc")
        calls = []

        def fake_rest(method, path, json=None, params=None):
            calls.append((method, path, json, params))
            if method == "GET" and path == "pb_messages":
                return [{"id": 10, "session": "s1", "role": "user", "text": "hi from phone", "ts": 1.0}]
            return []

        with mock.patch.object(supabase_auth, "configured", return_value=True), \
             mock.patch.object(supabase_auth, "_rest", side_effect=fake_rest), \
             mock.patch("bots.list_bots", return_value=[{"id": "b", "name": "B", "role": "x"}]):
            out = cloud_sync.sync_once()
            self.assertTrue(out["ok"], out)
            self.assertEqual(out["pulled"], 1)
            self.assertEqual(out["pushed"], 1)          # the PC message, not the imported phone one
            pushed = [c for c in calls if c[0] == "POST" and c[1] == "pb_messages"][0][2]
            self.assertEqual([r["text"] for r in pushed], ["hello from pc"])
            self.assertTrue(all(r["origin"] == "pc" and r["user_id"] == "u1" for r in pushed))
            texts = [m["text"] for m in chat_store.history("s1")]
            self.assertIn("hi from phone", texts)
            calls.clear()
            out2 = cloud_sync.sync_once()                # second run: nothing new, phone msg not echoed
            self.assertEqual(out2["pushed"], 0)
            get = [c for c in calls if c[0] == "GET" and c[1] == "pb_messages"][0][3]
            self.assertEqual(get["id"], "gt.10")

    def test_needs_owner(self):
        import cloud_sync
        import supabase_auth
        cloud_sync._state["owner"] = None
        with mock.patch.object(supabase_auth, "configured", return_value=True), \
             mock.patch.dict("os.environ", {"ADMIN_EMAIL": "", "PEDBOT_OWNER_EMAIL": ""}):
            out = cloud_sync.sync_once()
        self.assertFalse(out["ok"])
        self.assertIn("ADMIN_EMAIL", out["error"])

    def test_schema_has_rls(self):
        sql = Path("supabase/phone_sync.sql").read_text(encoding="utf-8")
        for t in ("pb_bots", "pb_messages"):
            self.assertIn(f"alter table public.{t} enable row level security", sql)
        self.assertIn("user_id = auth.uid()", sql)
        self.assertNotIn("gemini_key", sql.lower())


class PhoneCoreJsTests(unittest.TestCase):
    def test_node(self):
        import shutil
        import subprocess
        node = shutil.which("node")
        if not node:
            self.skipTest("node missing")
        r = subprocess.run([node, "tests/test_phone_core.js"], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
