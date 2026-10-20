"""YouTube posts need a signed-in channel. The token never comes back."""

import json
import os
import tempfile
import unittest
from pathlib import Path


class YouTubeChannelTests(unittest.TestCase):
    def setUp(self) -> None:
        import youtube_channel

        self.yt = youtube_channel
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.token = str(Path(self.folder.name) / "youtube_token.json")
        self._env = {
            "YOUTUBE_CLIENT_ID": os.environ.get("YOUTUBE_CLIENT_ID"),
            "YOUTUBE_CLIENT_SECRET": os.environ.get("YOUTUBE_CLIENT_SECRET"),
            "YOUTUBE_TOKEN_PATH": os.environ.get("YOUTUBE_TOKEN_PATH"),
        }
        os.environ["YOUTUBE_TOKEN_PATH"] = self.token
        os.environ.pop("YOUTUBE_CLIENT_ID", None)
        os.environ.pop("YOUTUBE_CLIENT_SECRET", None)
        youtube_channel.transport = None
        self.addCleanup(self._restore)

    def _restore(self) -> None:
        self.yt.transport = None
        for key, value in self._env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_missing_client_explains_the_setup_and_hides_nothing_secret(self) -> None:
        out = self.yt.youtube_upload(r"C:\clip.mp4", "Hello")
        self.assertFalse(out["ok"])
        self.assertIn("one-time step you do yourself", out["error"])
        self.assertIn("console.cloud.google.com", out["error"])
        self.assertNotIn("refresh_token", json.dumps(out))
        self.assertFalse(self.yt.youtube_status()["connected"])

    def test_upload_posts_a_private_video_and_returns_only_the_id(self) -> None:
        os.environ["YOUTUBE_CLIENT_ID"] = "client-id"
        os.environ["YOUTUBE_CLIENT_SECRET"] = "client-secret-value"
        Path(self.token).write_text(json.dumps({
            "refresh_token": "refresh-secret-value",
            "access_token": "access-secret-value",
            "expiry": 9_999_999_999,
        }), encoding="utf-8")
        video = Path(self.folder.name) / "clip.mp4"
        video.write_bytes(b"fake-video")
        seen: list[tuple[str, str]] = []

        def transport(method, url, data, headers):
            seen.append((method, url))
            self.assertNotIn("client-secret-value", url)
            if method == "POST" and "upload" in url:
                return 200, {"location": "https://upload.example/session"}, b""
            if method == "PUT":
                self.assertIn("Bearer access-secret-value", headers["Authorization"])
                return 200, {}, json.dumps({"id": "abc123"}).encode()
            raise AssertionError(method)

        self.yt.transport = transport
        out = self.yt.youtube_upload(str(video), "Pedro intro", privacy="private")
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["video_id"], "abc123")
        self.assertEqual(out["privacy"], "private")
        self.assertEqual(out["url"], "https://www.youtube.com/watch?v=abc123")
        self.assertNotIn("refresh-secret-value", json.dumps(out))
        self.assertNotIn("access-secret-value", json.dumps(out))
        self.assertEqual(seen[0][0], "POST")
        self.assertEqual(seen[1][0], "PUT")

    def test_a_missing_sign_in_does_not_pretend_to_post(self) -> None:
        os.environ["YOUTUBE_CLIENT_ID"] = "client-id"
        os.environ["YOUTUBE_CLIENT_SECRET"] = "client-secret-value"
        video = Path(self.folder.name) / "clip.mp4"
        video.write_bytes(b"fake-video")
        out = self.yt.youtube_upload(str(video), "Hello")
        self.assertFalse(out["ok"])
        self.assertIn("youtube_connect", out["error"])

    def test_upload_asks_before_it_posts(self) -> None:
        import rules

        self.assertTrue(rules.needs_confirmation("youtube_upload", {"title": "Intro", "privacy": "public"}))
        import confirm_action
        label = confirm_action.label_for("youtube_upload", {"title": "Intro", "privacy": "public"})
        self.assertIn("Intro", label)
        self.assertIn("public", label)


if __name__ == "__main__":
    unittest.main()
