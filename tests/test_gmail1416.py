import os, smtplib, unittest
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
