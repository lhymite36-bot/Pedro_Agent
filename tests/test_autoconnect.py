import json
import unittest
import urllib.request
from unittest import mock

import remote_access as ra


class AutoConnectTests(unittest.TestCase):
    def test_sign_and_verify_roundtrip(self):
        body = ra.sign_url("https://a-b-c.trycloudflare.com", "abc123", 100)
        self.assertNotIn("abc123", body)
        self.assertEqual(ra.verify_signed(body, "abc123"), "https://a-b-c.trycloudflare.com")

    def test_wrong_token_or_tamper_rejected(self):
        body = ra.sign_url("https://a-b-c.trycloudflare.com", "abc", 100)
        self.assertEqual(ra.verify_signed(body, "other"), "")
        d = json.loads(body); d["url"] = "https://evil.trycloudflare.com"
        self.assertEqual(ra.verify_signed(json.dumps(d), "abc"), "")
        self.assertEqual(ra.verify_signed("junk", "abc"), "")

    def test_topic_stable_and_hides_token(self):
        t = ra.publish_topic("secret-token")
        self.assertEqual(t, ra.publish_topic("secret-token"))
        self.assertTrue(t.startswith("pedro-")); self.assertNotIn("secret", t)

    def test_publish_posts_signed_body_without_token(self):
        sent = {}

        class R:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *a): pass

        def fake(req, timeout=0):
            sent["url"] = req.full_url; sent["data"] = req.data.decode(); return R()
        with mock.patch.object(urllib.request, "urlopen", fake), \
             mock.patch.object(ra, "settings", return_value=dict(ra.DEFAULTS)):
            self.assertTrue(ra.publish_url("https://x-y.trycloudflare.com", "tok-very-secret"))
        self.assertTrue(sent["url"].endswith(ra.publish_topic("tok-very-secret")))
        self.assertNotIn("tok-very-secret", sent["data"])
        self.assertEqual(ra.verify_signed(sent["data"], "tok-very-secret"), "https://x-y.trycloudflare.com")
