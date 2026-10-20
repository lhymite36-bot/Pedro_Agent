"""Connectors stay on this PC and never echo a secret."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

import connectors


class ConnectorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store: dict = {}
        connectors.store_override = self.store
        connectors.http_override = self._http
        connectors.imap_override = self._imap
        connectors.command_override = lambda args: (1, "")
        connectors.folder_roots_override = {}
        connectors.outlook_override = False
        connectors.outlook_reader = None
        self.calls: list[tuple] = []
        self.http_body = ("200", "{}")
        self._env = {key: os.environ.get(key) for key in ("GMAIL_ADDRESS", "GMAIL_APP_PASSWORD")}

    def tearDown(self) -> None:
        connectors.store_override = None
        connectors.http_override = None
        connectors.imap_override = None
        connectors.command_override = None
        connectors.folder_roots_override = None
        connectors.outlook_override = None
        connectors.outlook_reader = None
        for key, value in self._env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def _http(self, method, url, headers, body):
        self.calls.append((method, url, headers, body))
        status, text = self.http_body
        return int(status), text

    def _imap(self, address, password, query):
        self.calls.append((address, password, query))
        return [{
            "from": "Ada <ada@example.com>",
            "title": "Gears",
            "when": "Fri, 16 Oct 2026 10:15:00 +0000",
            "snippet": "The gears arrived.",
        }]

    def test_catalog_hides_secrets_and_search_uses_the_saved_mail(self) -> None:
        secret = "apppasswordvalue"
        saved = connectors.connect("gmail", {"address": "ada@example.com", "secret": secret})
        self.assertTrue(saved["ok"], saved)
        self.assertNotIn(secret, json.dumps(saved))
        listed = connectors.list_connectors()
        self.assertNotIn(secret, json.dumps(listed))
        self.assertIn("Gmail", listed["message"])
        gmail = next(row for row in listed["connectors"] if row["id"] == "gmail")
        self.assertTrue(gmail["connected"])
        self.assertEqual(gmail["account"], "ada@example.com")
        found = connectors.connector_search("gmail", "gears")
        self.assertTrue(found["ok"], found)
        self.assertIn("The gears arrived.", found["message"])
        self.assertEqual(self.calls[-1][0], "ada@example.com")
        self.assertEqual(self.calls[-1][1], secret)
        connectors.disconnect("gmail")
        again = connectors.connector_search("Gmail", "gears")
        self.assertFalse(again["ok"])
        self.assertIn("not connected", again["error"])

    def test_notion_token_is_checked_and_not_returned(self) -> None:
        token = "secret-notion-token"
        self.http_body = ("200", json.dumps({"results": []}))
        saved = connectors.connect("notion", {"secret": token})
        self.assertTrue(saved["ok"], saved)
        self.assertNotIn(token, json.dumps(saved))
        self.http_body = ("200", json.dumps({
            "results": [{"url": "https://www.notion.so/gears", "properties": {
                "Name": {"title": [{"plain_text": "Gear notes"}]}
            }}]
        }))
        found = connectors.connector_search("notion", "gears")
        self.assertIn("Gear notes", found["message"])
        self.assertNotIn(token, json.dumps(found))
        self.assertTrue(any(token in (call[2].get("Authorization") or "") for call in self.calls if isinstance(call[2], dict)))

    def test_refused_token_is_not_saved(self) -> None:
        self.http_body = ("401", "nope secret-slack-token")
        saved = connectors.connect("slack", {"secret": "secret-slack-token"})
        self.assertFalse(saved["ok"])
        self.assertNotIn("secret-slack-token", saved["error"])
        self.assertFalse(any(row["connected"] for row in connectors.catalog() if row["id"] == "slack"))

    def test_folder_and_outlook_and_github_read_local_results(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "Gear notes.txt"
            path.write_text("hello", encoding="utf-8")
            connectors.folder_roots_override = {"gdrive": folder, "onedrive": ""}
            found = connectors.connector_search("google drive", "gear")
            self.assertIn("Gear notes.txt", found["message"])
            self.assertNotIn("hello", found["message"])
        connectors.outlook_override = True
        connectors.outlook_reader = lambda query: [{"from": "Ada", "title": "Standup", "when": "Fri 10:00"}]
        mail = connectors.connector_search("outlook", "standup")
        self.assertIn("Standup", mail["message"])
        connectors.command_override = lambda args: (0, "owner/repo 12 Gear issue") if "search" in args else (0, "")
        code = connectors.connector_search("github", "gear")
        self.assertIn("Gear issue", code["message"])

    def test_missing_services_say_so(self) -> None:
        calendar = connectors.connector_search("google calendar", "today")
        self.assertFalse(calendar["ok"])
        self.assertIn("Google Calendar", calendar["error"])
        teams = connectors.connector_search("teams", "today")
        self.assertFalse(teams["ok"])
        self.assertIn("Teams", teams["error"])


if __name__ == "__main__":
    unittest.main()
