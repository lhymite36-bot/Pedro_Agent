import json, os, smtplib, unittest
from unittest import mock
import gmail_mail


class AppPasswordShape(unittest.TestCase):
    def test_shape(self):
        self.assertTrue(gmail_mail.app_password_ok("abcd efgh ijkl mnop"))
        for bad in ("", "short", "abcd efgh ijkl mno1", "abcdefghijklmnopq", "MyNormalPassw0rd"):
            self.assertFalse(gmail_mail.app_password_ok(bad))

    def test_rejected_before_sending(self):
        agent = gmail_mail._agent()
        with mock.patch.object(agent, "gmail_transport_override", None), \
             mock.patch.object(gmail_mail, "_configured", return_value=("me@gmail.com", "hunter2hunter2")), \
             mock.patch.object(gmail_mail, "_smtp_send") as send, \
             mock.patch.dict("sys.modules", {"google_connections": None}):
            r = gmail_mail._deliver("you@example.com", "s", "b")
        send.assert_not_called()
        self.assertEqual(r["error"] if "error" in r else r.get("message"), gmail_mail.APP_PASSWORD_HINT)
        self.assertNotIn("hunter2", str(r))

    def test_drop_during_sign_in_is_not_retried(self):
        agent = gmail_mail._agent()
        smtp = mock.MagicMock()
        smtp.__enter__.return_value = smtp
        smtp.login.side_effect = smtplib.SMTPServerDisconnected("Connection unexpectedly closed")
        with mock.patch.object(agent, "gmail_transport_override", None), \
             mock.patch.object(gmail_mail, "_configured", return_value=("me@gmail.com", "abcdefghijklmnop")), \
             mock.patch("smtplib.SMTP", return_value=smtp) as plain, mock.patch("smtplib.SMTP_SSL") as tls, \
             mock.patch.dict("sys.modules", {"google_connections": None}):
            r = gmail_mail._deliver("you@example.com", "s", "b")
        self.assertEqual(plain.call_count, 1)
        tls.assert_not_called()
        text = str(r)
        self.assertIn("sign-in problem", text)
        self.assertNotIn("network problem.", text.replace("not a network problem", ""))
        self.assertNotIn("abcdefghijklmnop", text)


if __name__ == "__main__":
    unittest.main()


class MultiAccount(unittest.TestCase):
    def setUp(self):
        import tempfile, connectors
        self.tmp = tempfile.TemporaryDirectory()
        self.p = mock.patch.object(connectors, "_store_path", return_value=__import__("pathlib").Path(self.tmp.name, "connectors.json"))
        self.p.start(); self.c = connectors
        self.env = mock.patch.dict(os.environ, {"GMAIL_ADDRESS": "", "GMAIL_APP_PASSWORD": ""}); self.env.start()

    def tearDown(self):
        self.p.stop(); self.env.stop(); self.tmp.cleanup()

    def test_old_single_account_becomes_the_default(self):
        self.c._write_store({"gmail": {"address": "p26635577@gmail.com", "password": "abcdefghijklmnop"}})
        self.assertEqual(self.c.gmail_accounts()["default"], "p26635577@gmail.com")
        self.assertEqual(self.c.gmail_login()[0], "p26635577@gmail.com")

    def test_add_pick_default_remove(self):
        self.c._write_store({"gmail": {"address": "p26635577@gmail.com", "password": "abcdefghijklmnop"}})
        r = self.c.connect("gmail", {"address": "work@gmail.com", "secret": "qrst uvwx yzab cdef"})
        self.assertTrue(r["ok"], r); self.assertEqual(r["default"], "p26635577@gmail.com")
        self.assertNotIn("qrst", json.dumps(self.c.catalog()))
        self.assertEqual(self.c.gmail_login("work")[0], "work@gmail.com")
        self.assertEqual(self.c.gmail_login()[0], "p26635577@gmail.com")
        self.assertTrue(self.c.gmail_set_default("work@gmail.com")["ok"])
        self.assertEqual(self.c.gmail_login()[0], "work@gmail.com")
        self.assertEqual(self.c._read_store()["gmail"]["address"], "work@gmail.com")   # older builds see the default
        self.assertTrue(self.c.disconnect("gmail", "work@gmail.com")["ok"])
        self.assertEqual(self.c.gmail_accounts()["default"], "p26635577@gmail.com")
        self.assertFalse(self.c.connect("gmail", {"address": "x@gmail.com", "secret": "notanapppassword1"})["ok"])

    def test_send_uses_named_or_default_and_card_names_it(self):
        import confirm_action
        self.c._write_store({"gmail": {"address": "p26635577@gmail.com", "password": "abcdefghijklmnop"}})
        self.c.gmail_add("work@gmail.com", "qrstuvwxyzabcdef")
        sent = []
        agent = gmail_mail._agent()
        with mock.patch.object(agent, "gmail_transport_override", None), \
             mock.patch.dict("sys.modules", {"google_connections": None}), \
             mock.patch.object(gmail_mail, "_smtp_send", side_effect=lambda a, p, *x, **k: sent.append(a)):
            self.assertTrue(gmail_mail.gmail_send_message(to="you@example.com", body="hi", from_account="work")["ok"])
            self.assertTrue(gmail_mail.gmail_send_message(to="you@example.com", body="hi")["ok"])
            r = gmail_mail.gmail_send_message(to="you@example.com", body="hi", from_account="nobody")
            self.assertIn("No saved Gmail account", json.dumps(r))
            self.assertEqual(sent, ["work@gmail.com", "p26635577@gmail.com"])
            label = confirm_action.label_for("gmail_send_message", {"to": "you@example.com", "from_account": "work"})
            self.assertIn("from work@gmail.com", label)
            self.assertIn("from p26635577@gmail.com", confirm_action.label_for("gmail_send_message", {"to": "a@b.co"}))
