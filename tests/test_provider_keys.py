"""Extra Gemini keys and free providers switch only after a live failure."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import agent_core
import chat_app
import cloud_fallback


class ProviderChainTests(unittest.TestCase):
    def tearDown(self):
        cloud_fallback.transport_override = None
        cloud_fallback.providers_override = None

    def test_quota_skips_groq_and_the_provider_that_is_out(self):
        seen = []

        def transport(body):
            seen.append(body["model"])
            if body["model"] == "openrouter/free":
                raise cloud_fallback._Switch("openrouter returned 429")
            return {"choices": [{"message": {"content": "from cerebras"}}]}

        cloud_fallback.transport_override = transport
        with mock.patch.dict(os.environ, {
            "GROQ_API_KEY": "gsk-test-key-1234",
            "OPENROUTER_API_KEY": "or-test-key-1234",
            "CEREBRAS_API_KEY": "cb-test-key-1234",
            "NVIDIA_API_KEY": "",
        }):
            text = cloud_fallback.run_chain("hello", kind="quota")
        self.assertEqual(text, "from cerebras")
        self.assertEqual(seen, ["openrouter/free", "qwen-3.8-27b"])

    def test_busy_keeps_groq_first(self):
        with mock.patch.dict(os.environ, {
            "GROQ_API_KEY": "gsk-test-key-1234",
            "OPENROUTER_API_KEY": "or-test-key-1234",
        }):
            names = [item["id"] for item in cloud_fallback.providers_for("busy")]
        self.assertEqual(names[0], "groq")
        self.assertIn("openrouter", names)
        with mock.patch.dict(os.environ, {
            "GROQ_API_KEY": "gsk-test-key-1234",
            "OPENROUTER_API_KEY": "or-test-key-1234",
        }):
            quota = [item["id"] for item in cloud_fallback.providers_for("quota")]
        self.assertNotIn("groq", quota)


class GeminiKeyTests(unittest.TestCase):
    def test_extra_keys_keep_order_and_drop_blanks(self):
        with mock.patch.dict(os.environ, {
            "GEMINI_API_KEY": "primary-key-123",
            "GEMINI_API_KEYS": "primary-key-123,second-key-456, ,second-key-456",
        }):
            self.assertEqual(agent_core.gemini_api_keys(), ["primary-key-123", "second-key-456"])
            self.assertNotIn("second-key-456", agent_core._scrub("leak second-key-456"))

    def test_a_live_quota_error_tries_the_next_key_and_not_groq(self):
        seen = []

        class Models:
            def generate_content(self, **kwargs):
                seen.append(kwargs["model"])
                raise RuntimeError("429 RESOURCE_EXHAUSTED model: only-model limit: 20")

        class Client:
            def __init__(self, key):
                seen.append("key:" + key[-3:])
                self.models = Models()

        agent_core.genai_client_override = lambda key: Client(key)
        cloud_fallback.transport_override = lambda body: {"choices": [{"message": {"content": "from groq"}}]}
        self.addCleanup(setattr, agent_core, "genai_client_override", None)
        self.addCleanup(setattr, cloud_fallback, "transport_override", None)
        with mock.patch.dict(os.environ, {
            "GEMINI_API_KEY": "aaaa-key-111",
            "GEMINI_API_KEYS": "bbbb-key-222",
            "OPENROUTER_API_KEY": "",
            "CEREBRAS_API_KEY": "",
            "NVIDIA_API_KEY": "",
        }):
            with self.assertRaises(RuntimeError) as err:
                agent_core.run_agent("hello", [], "only-model")
        self.assertIn("key:111", seen)
        self.assertIn("key:222", seen)
        self.assertIn("free Gemini quota", str(err.exception))
        self.assertNotIn("from groq", str(err.exception))


class DroppedConnectionTests(unittest.TestCase):
    def test_a_working_model_stays_ahead_of_one_that_failed(self):
        order = ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-2.5-flash"]
        self.assertEqual(
            agent_core._turn_models(order, "gemini-3.1-flash-lite", {"gemini-3.5-flash-lite"}),
            ["gemini-3.1-flash-lite", "gemini-2.5-flash"],
        )

    def test_a_closed_mail_connection_is_tried_again(self):
        import smtplib

        import gmail_mail

        calls = []

        def send(*_args, **kw):
            calls.append(kw.get("port", 587))
            if len(calls) == 1:
                raise smtplib.SMTPServerDisconnected("Connection unexpectedly closed")

        with mock.patch.object(gmail_mail, "_configured", return_value=("from@example.com", "password12")), \
             mock.patch.object(gmail_mail, "_smtp_send", side_effect=send):
            result = gmail_mail._deliver("to@example.com", "Hello", "A short note.")
        self.assertTrue(result["ok"])
        self.assertEqual(calls, [587, 465])   # the retry uses direct TLS on 465

    def test_a_rejected_login_is_not_retried(self):
        import smtplib

        import gmail_mail

        calls = []

        def send(*_args, **_kw):
            calls.append(1)
            raise smtplib.SMTPAuthenticationError(535, b"bad")

        with mock.patch.object(gmail_mail, "_configured", return_value=("from@example.com", "password12")), \
             mock.patch.object(gmail_mail, "_smtp_send", side_effect=send):
            result = gmail_mail._deliver("to@example.com", "Hello", "A short note.")
        self.assertFalse(result["ok"])
        self.assertEqual(len(calls), 1)
        self.assertIn("not sent", result["error"].casefold())


class SaveProviderKeyTests(unittest.TestCase):
    def test_settings_store_extra_keys_without_a_space(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = Path(folder.name) / ".env"
        path.write_text("GEMINI_API_KEY=already-set-key\n", encoding="utf-8")
        names = ("GEMINI_API_KEYS", "OPENROUTER_API_KEY", "CEREBRAS_API_KEY", "NVIDIA_API_KEY")
        saved = {name: os.environ.get(name) for name in names}
        previous = os.environ.get("GEMINI_API_KEY")
        if not (previous or "").strip():
            os.environ["GEMINI_API_KEY"] = "already-set-key"

            def restore_primary():
                if previous is None:
                    os.environ.pop("GEMINI_API_KEY", None)
                else:
                    os.environ["GEMINI_API_KEY"] = previous

            self.addCleanup(restore_primary)
        original = chat_app._env_path
        chat_app._env_path = lambda: path
        self.addCleanup(setattr, chat_app, "_env_path", original)

        def restore():
            for name, value in saved.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value

        self.addCleanup(restore)
        for name in names:
            os.environ.pop(name, None)
        bad = chat_app.save_setup({"openrouter_api_key": "has space"})
        self.assertFalse(bad["ok"])
        ok = chat_app.save_setup({
            "gemini_api_keys": "extra-gemini-key-1\nextra-gemini-key-2",
            "openrouter_api_key": "or-key-value-1",
            "cerebras_api_key": "cb-key-value-1",
            "nvidia_api_key": "nv-key-value-1",
        })
        self.assertTrue(ok["ok"])
        self.assertGreaterEqual(ok["gemini_keys"], 2)
        self.assertTrue(ok["openrouter"] and ok["cerebras"] and ok["nvidia"])
        stored = path.read_text(encoding="utf-8")
        self.assertIn("GEMINI_API_KEYS=extra-gemini-key-1,extra-gemini-key-2", stored)
        self.assertIn("OPENROUTER_API_KEY=or-key-value-1", stored)
        self.assertNotIn("extra-gemini-key-1\nextra", stored)


if __name__ == "__main__":
    unittest.main()
