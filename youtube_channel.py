"""Post a video to the YouTube channel the user signs in with.

An API key cannot upload. The first call to youtube_connect opens Google's
sign-in on this PC and stores a refresh token locally. The token is never
returned to the chat.
"""

from __future__ import annotations

import json
import mimetypes
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Callable

import agent_config

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
CHANNEL_URL = "https://www.googleapis.com/youtube/v3/channels?part=snippet&mine=true"
UPLOAD_START = "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status"
SCOPES = "https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly"
PRIVACY = {"private", "unlisted", "public"}
VIDEO_TYPES = {
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".mkv": "video/x-matroska",
    ".webm": "video/webm",
    ".avi": "video/x-msvideo",
}
CHUNK = 8 * 1024 * 1024
MAX_BYTES = 8 * 1024 * 1024 * 1024

SETUP = (
    "Nothing was posted: YouTube isn't signed in yet. This is a one-time step you do yourself:\n"
    "1. Open https://console.cloud.google.com/apis/library/youtube.googleapis.com and turn on "
    "YouTube Data API v3.\n"
    "2. Under Credentials, create an OAuth client of type 'Desktop app'.\n"
    "3. Put its YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET in Settings (or .env).\n"
    "4. Open Connectors > YouTube > Connect and sign in as your channel.\n"
    "After that, uploads still ask you before they post."
)

# Tests replace this. (method, url, body, headers) -> (status, headers, body)
transport: Callable[[str, str, bytes | None, dict[str, str]], tuple[int, dict[str, str], bytes]] | None = None


def _err(message: str, **extra: Any) -> dict[str, Any]:
    return {"ok": False, "error": message, **extra}


def _ok(message: str, **extra: Any) -> dict[str, Any]:
    return {"ok": True, "message": message, **extra}


def _client() -> tuple[str, str]:
    return (
        os.environ.get("YOUTUBE_CLIENT_ID", "").strip(),
        os.environ.get("YOUTUBE_CLIENT_SECRET", "").strip(),
    )


def token_path() -> Path:
    raw = os.environ.get("YOUTUBE_TOKEN_PATH", "").strip()
    if raw:
        return Path(raw).expanduser()
    return agent_config.storage_dir() / "youtube_token.json"


def _http(method: str, url: str, data: bytes | None, headers: dict[str, str]) -> tuple[int, dict[str, str], bytes]:
    if transport is not None:
        return transport(method, url, data, headers)
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            got = {key.lower(): value for key, value in response.headers.items()}
            return int(response.status), got, response.read()
    except urllib.error.HTTPError as exc:
        got = {key.lower(): value for key, value in (exc.headers.items() if exc.headers else [])}
        return int(exc.code), got, exc.read() or b""


def _read_token() -> dict[str, Any] | None:
    path = token_path()
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get("refresh_token") else None


def _write_token(data: dict[str, Any]) -> None:
    path = token_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    os.replace(tmp, path)


def _access_token(saved: dict[str, Any]) -> str:
    expiry = float(saved.get("expiry") or 0)
    current = str(saved.get("access_token") or "")
    if current and time.time() < expiry:
        return current
    client_id, client_secret = _client()
    body = urllib.parse.urlencode({
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": saved["refresh_token"],
        "grant_type": "refresh_token",
    }).encode()
    status, _headers, raw = _http("POST", TOKEN_URL, body, {"Content-Type": "application/x-www-form-urlencoded"})
    try:
        payload = json.loads(raw.decode("utf-8", "replace"))
    except ValueError:
        payload = {}
    if status != 200 or not payload.get("access_token"):
        raise RuntimeError("The YouTube sign-in expired. Call youtube_connect and sign in again.")
    saved["access_token"] = payload["access_token"]
    saved["expiry"] = time.time() + int(payload.get("expires_in") or 3600) - 60
    if payload.get("refresh_token"):
        saved["refresh_token"] = payload["refresh_token"]
    _write_token(saved)
    return str(saved["access_token"])


def _channel(token: str) -> tuple[str, str]:
    status, _headers, raw = _http("GET", CHANNEL_URL, None, {"Authorization": f"Bearer {token}"})
    try:
        payload = json.loads(raw.decode("utf-8", "replace"))
    except ValueError:
        payload = {}
    items = payload.get("items") if isinstance(payload, dict) else None
    if status != 200 or not items:
        raise RuntimeError("Google did not return a YouTube channel for this sign-in.")
    snippet = items[0].get("snippet") or {}
    return str(items[0].get("id") or ""), str(snippet.get("title") or "your channel")


def youtube_status() -> dict[str, Any]:
    """Say whether this PC can post to a YouTube channel. No secrets."""
    client_id, client_secret = _client()
    if not client_id or not client_secret:
        return _err(SETUP, connected=False)
    saved = _read_token()
    if saved is None:
        return _err("The YouTube client is saved, but nobody has signed in. Call youtube_connect.", connected=False)
    try:
        token = _access_token(saved)
        channel_id, title = _channel(token)
    except RuntimeError as exc:
        return _err(str(exc), connected=False)
    return _ok(f"Connected to YouTube channel {title}.", connected=True, channel=title, channel_id=channel_id)


def youtube_connect() -> dict[str, Any]:
    """Open Google's sign-in on this PC and keep the channel permission locally."""
    client_id, client_secret = _client()
    if not client_id or not client_secret:
        return _err(SETUP, connected=False)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            server = self.server
            if query.get("state", [""])[0] == getattr(server, "state", ""):
                if query.get("code"):
                    server.code = query["code"][0]  # type: ignore[attr-defined]
                elif query.get("error"):
                    server.fail = query["error"][0]  # type: ignore[attr-defined]
            body = b"You can close this tab and return to Pedro."
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt: str, *args: Any) -> None:
            return

    state = os.urandom(16).hex()
    server = HTTPServer(("127.0.0.1", 0), Handler)
    server.state = state  # type: ignore[attr-defined]
    server.code = ""  # type: ignore[attr-defined]
    server.fail = ""  # type: ignore[attr-defined]
    port = server.server_address[1]
    redirect = f"http://127.0.0.1:{port}/"
    url = AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id": client_id,
        "redirect_uri": redirect,
        "response_type": "code",
        "scope": SCOPES,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    })
    try:
        webbrowser.open(url)
        deadline = time.time() + 120
        while time.time() < deadline and not server.code and not server.fail:  # type: ignore[attr-defined]
            server.timeout = max(1, int(deadline - time.time()))
            server.handle_request()
    finally:
        server.server_close()
    if server.fail:  # type: ignore[attr-defined]
        return _err("Google did not grant YouTube access. Sign in as Pedro's channel and allow the upload.", connected=False)
    if not server.code:  # type: ignore[attr-defined]
        return _err("The Google sign-in window closed before access was granted.", connected=False)
    body = urllib.parse.urlencode({
        "code": server.code,  # type: ignore[attr-defined]
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect,
        "grant_type": "authorization_code",
    }).encode()
    status, _headers, raw = _http("POST", TOKEN_URL, body, {"Content-Type": "application/x-www-form-urlencoded"})
    try:
        payload = json.loads(raw.decode("utf-8", "replace"))
    except ValueError:
        payload = {}
    if status != 200 or not payload.get("refresh_token"):
        return _err("Google did not return a YouTube permission. Create a desktop OAuth client and try youtube_connect again.", connected=False)
    saved = {
        "refresh_token": payload["refresh_token"],
        "access_token": payload.get("access_token") or "",
        "expiry": time.time() + int(payload.get("expires_in") or 3600) - 60,
    }
    _write_token(saved)
    try:
        _channel_id, title = _channel(str(saved["access_token"]))
    except RuntimeError:
        title = "your channel"
    return _ok(
        f"Signed in to YouTube channel {title}. The next upload asks you before it posts.",
        connected=True,
        channel=title,
    )


def _video_file(path: str) -> tuple[Path | None, str]:
    text = " ".join(str(path or "").split())
    if not text:
        return None, "Say which video file to post."
    file = Path(text).expanduser()
    if not file.is_file():
        return None, "That video file is not on this PC."
    mime = VIDEO_TYPES.get(file.suffix.casefold()) or mimetypes.guess_type(file.name)[0] or ""
    if not str(mime).startswith("video/"):
        return None, "That file is not a video Pedro can post. Use mp4, mov, mkv, webm, or avi."
    if file.stat().st_size <= 0:
        return None, "That video file is empty."
    if file.stat().st_size > MAX_BYTES:
        return None, "That video is over 8 GB. Trim it, then post again."
    return file, mime


def youtube_upload(
    path: str,
    title: str,
    description: str = "",
    privacy: str = "private",
    tags: str = "",
) -> dict[str, Any]:
    """Upload one video. Privacy stays private unless the user says otherwise."""
    client_id, client_secret = _client()
    if not client_id or not client_secret:
        return _err(SETUP, connected=False)
    saved = _read_token()
    if saved is None:
        return _err("The channel is not signed in. Call youtube_connect first.", connected=False)
    name = " ".join(str(title or "").split())
    if not name:
        return _err("A YouTube title is required.")
    shown = privacy.strip().casefold() or "private"
    if shown not in PRIVACY:
        return _err("Privacy must be private, unlisted, or public.")
    file, mime = _video_file(path)
    if file is None:
        return _err(mime)
    tag_list = [part.strip() for part in str(tags or "").split(",") if part.strip()][:15]
    meta = {
        "snippet": {
            "title": name[:100],
            "description": " ".join(str(description or "").split())[:5000],
            "categoryId": "22",
        },
        "status": {"privacyStatus": shown, "selfDeclaredMadeForKids": False},
    }
    if tag_list:
        meta["snippet"]["tags"] = tag_list
    try:
        token = _access_token(saved)
    except RuntimeError as exc:
        return _err(str(exc), connected=False)
    raw_meta = json.dumps(meta).encode()
    status, headers, raw = _http(
        "POST",
        UPLOAD_START,
        raw_meta,
        {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=UTF-8",
            "X-Upload-Content-Type": mime,
            "X-Upload-Content-Length": str(file.stat().st_size),
        },
    )
    location = headers.get("location") or ""
    if status not in {200, 201} or not location:
        return _err("YouTube did not accept the upload. Check the sign-in and the video file.")
    total = file.stat().st_size
    sent = 0
    result_body = b""
    with file.open("rb") as handle:
        while sent < total:
            chunk = handle.read(CHUNK)
            end = sent + len(chunk) - 1
            status, _headers, result_body = _http(
                "PUT",
                location,
                chunk,
                {
                    "Authorization": f"Bearer {token}",
                    "Content-Type": mime,
                    "Content-Length": str(len(chunk)),
                    "Content-Range": f"bytes {sent}-{end}/{total}",
                },
            )
            sent += len(chunk)
            if status in {200, 201}:
                break
            if status != 308:
                return _err("YouTube stopped the upload before the video finished.")
    try:
        payload = json.loads(result_body.decode("utf-8", "replace"))
    except ValueError:
        payload = {}
    video_id = str(payload.get("id") or "")
    if not video_id:
        return _err("YouTube did not return a video id, so the post is not confirmed.")
    link = f"https://www.youtube.com/watch?v={video_id}"
    return _ok(
        f"Posted {name} on YouTube as {shown}. {link}",
        video_id=video_id,
        url=link,
        privacy=shown,
        title=name[:100],
    )
