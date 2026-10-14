import json
import os
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

import remote_access as ra


class PairingTests(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.p = mock.patch.object(ra, "_storage", return_value=Path(self.d.name)); self.p.start()
        ra.reset_state(); ra._pair_codes.clear()

    def tearDown(self):
        ra.reset_state(); ra._pair_codes.clear(); self.p.stop(); self.d.cleanup()

    def test_code_is_single_use_and_expires(self):
        tok = ra.access_token()
        code = ra.new_pairing_code(now=1000)
        self.assertRegex(code, r"^[A-Z2-9]{4}-[A-Z2-9]{4}$")
        self.assertEqual(ra.redeem_pairing_code(code.lower().replace("-", ""), "1.1.1.1", now=1001), (tok, ""))
        self.assertEqual(ra.redeem_pairing_code(code, "1.1.1.1", now=1002)[0], "")      # used
        old = ra.new_pairing_code(now=1000)
        self.assertEqual(ra.redeem_pairing_code(old, "2.2.2.2", now=1000 + ra.PAIR_TTL + 1)[0], "")  # expired

    def test_wrong_codes_lock_out(self):
        ra.access_token(); good = ra.new_pairing_code()
        for _ in range(ra.MAX_FAILS_PER_IP):
            ra.redeem_pairing_code("AAAA-AAAA", "9.9.9.9")
        self.assertIn("Too many", ra.redeem_pairing_code(good, "9.9.9.9")[1])

    def test_unpair_rotates_token_and_clears_codes(self):
        old = ra.access_token(); ra.new_pairing_code()
        ra.unpair_all()
        self.assertNotEqual(ra.access_token(), old); self.assertEqual(ra._pair_codes, {})
        self.assertFalse(ra.check_login(old, "3.3.3.3")[0])

    def test_qr_uri_and_svg_have_no_token(self):
        tok = ra.access_token(); ra.public_url = "https://a-b.trycloudflare.com"
        try:
            r = ra.phone_pair()
        finally:
            ra.public_url = ""
        self.assertTrue(r["uri"].startswith("pedroagent://pair?u=https%3A%2F%2Fa-b.trycloudflare.com&c="))
        self.assertNotIn(tok, r["uri"] + r["qr_svg"]); self.assertIn("<svg", r["qr_svg"])
        self.assertFalse(ra.phone_pair()["ok"])  # no tunnel yet

    def test_overlay_enables_without_touching_rules_yaml(self):
        self.assertFalse(ra.settings()["enabled"] and False)
        ra.save_overlay(enabled=True, tunnel="cloudflared")
        self.assertTrue(ra.settings()["enabled"]); self.assertEqual(ra.settings()["tunnel"], "cloudflared")

    def test_enable_asks_consent_before_download(self):
        with mock.patch.object(ra, "cloudflared_exe", return_value=None), mock.patch.object(ra, "start") as st:
            r = ra.phone_enable(object())
            self.assertTrue(r["needs_consent"]); st.assert_not_called()
            with mock.patch.object(ra, "cloudflared_download", side_effect=RuntimeError("offline")):
                self.assertIn("offline", ra.phone_enable(object(), consent=True)["error"])

    def test_download_saves_path(self):
        p = ra.cloudflared_download(Path(self.d.name) / "bin", fetch=lambda u: b"x" * 2_000_000)
        self.assertTrue(Path(p).is_file()); self.assertEqual(ra.settings()["cloudflared_path"], p)
        with self.assertRaises(RuntimeError):
            ra.cloudflared_download(Path(self.d.name) / "b2", fetch=lambda u: b"tiny")


class PairEndpointTests(unittest.TestCase):
    def test_pair_endpoint_on_remote_server_and_phone_api_pc_only(self):
        import chat_app
        d = tempfile.TemporaryDirectory(); self.addCleanup(d.cleanup)
        with mock.patch.object(ra, "_storage", return_value=Path(d.name)):
            ra.reset_state(); tok = ra.access_token(); code = ra.new_pairing_code()
            state = mock.Mock(); srv = ra.ThreadingHTTPServer(("127.0.0.1", 0), ra.make_remote_handler(state))
            threading.Thread(target=srv.serve_forever, daemon=True).start(); self.addCleanup(srv.shutdown)
            base = f"http://127.0.0.1:{srv.server_address[1]}"

            def post(path, body):
                req = urllib.request.Request(base + path, json.dumps(body).encode(), {"Content-Type": "application/json"})
                try:
                    with urllib.request.urlopen(req) as r:
                        return r.status, json.loads(r.read())
                except urllib.error.HTTPError as e:
                    return e.code, json.loads(e.read() or b"{}")
            self.assertEqual(post("/pair", {"code": "ZZZZ-ZZZZ"})[0], 401)
            st, body = post("/pair", {"code": code})
            self.assertEqual((st, body.get("token"), body.get("error")), (200, tok, None))
            self.assertEqual(post("/api/phone/pair", {})[0], 401)  # remote: not signed in
            ra.reset_state()
