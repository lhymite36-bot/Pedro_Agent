"""Connections panel: one-time Google sign-ins for YouTube, Gmail and Google Drive.

You press Connect and sign in yourself in your own browser (Google's page). The
permission (refresh token) is saved only on this PC under storage/connections/;
it is never put in code, logs, GitHub or chat. Disconnect deletes the local copy.
You need one Google OAuth client of type "Desktop app" (GOOGLE_CLIENT_ID and
GOOGLE_CLIENT_SECRET in .env; the old YOUTUBE_CLIENT_* names still work).
Sending mail or posting still asks you first, as before.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Callable

import agent_config

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
SERVICES: dict[str, dict[str, str]] = {
    "youtube": {"label": "YouTube", "scopes": "https://www.googleapis.com/auth/youtube.upload "
                "https://www.googleapis.com/auth/youtube.readonly"},
    "gmail": {"label": "Gmail", "scopes": "https://www.googleapis.com/auth/gmail.send "
              "https://www.googleapis.com/auth/gmail.readonly"},
    "drive": {"label": "Google Drive", "scopes": "https://www.googleapis.com/auth/drive.file "
              "https://www.googleapis.com/auth/drive.metadata.readonly"},
}
SETUP = ("Connections need a Google OAuth client you create once yourself: in Google Cloud Console > "
         "Credentials, create an OAuth client of type 'Desktop app', then put GOOGLE_CLIENT_ID and "
         "GOOGLE_CLIENT_SECRET in Settings (.env). Then press Connect and sign in.")

# Tests replace these.
http: Callable[[str, str, bytes | None, dict[str, str]], tuple[int, bytes]] | None = None
open_browser: Callable[[str], Any] = webbrowser.open


def _client() -> tuple[str, str]:
    cid = os.environ.get("GOOGLE_CLIENT_ID", "").strip() or os.environ.get("YOUTUBE_CLIENT_ID", "").strip()
    sec = os.environ.get("GOOGLE_CLIENT_SECRET", "").strip() or os.environ.get("YOUTUBE_CLIENT_SECRET", "").strip()
    return cid, sec


def token_file(service: str) -> Path:
    if service == "youtube":
        import youtube_channel

        return youtube_channel.token_path()   # same file the uploader already uses
    return agent_config.storage_dir() / "connections" / f"{service}_token.json"


def _http(method: str, url: str, data: bytes | None, headers: dict[str, str]) -> tuple[int, bytes]:
    if http is not None:
        return http(method, url, data, headers)
    import urllib.error
    import urllib.request

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return int(r.status), r.read()
    except urllib.error.HTTPError as exc:
        return int(exc.code), exc.read() or b""


def _read(service: str) -> dict[str, Any] | None:
    try:
        data = json.loads(token_file(service).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get("refresh_token") else None


def _write(service: str, data: dict[str, Any]) -> None:
    p = token_file(service)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    os.replace(tmp, p)


def status() -> dict[str, Any]:
    cid, sec = _client()
    out = []
    for key, info in SERVICES.items():
        saved = _read(key)
        out.append({"id": key, "label": info["label"], "connected": bool(saved),
                    "since": (saved or {}).get("connected_at")})
    return {"ok": True, "client_ready": bool(cid and sec), "setup": "" if cid and sec else SETUP, "services": out}


def access_token(service: str) -> str:
    saved = _read(service)
    if not saved:
        raise RuntimeError(f"{SERVICES[service]['label']} is not connected. Open Settings > Connections and press Connect.")
    if saved.get("access_token") and time.time() < float(saved.get("expiry") or 0):
        return str(saved["access_token"])
    cid, sec = _client()
    body = urllib.parse.urlencode({"client_id": cid, "client_secret": sec, "refresh_token": saved["refresh_token"],
                                   "grant_type": "refresh_token"}).encode()
    code, raw = _http("POST", TOKEN_URL, body, {"Content-Type": "application/x-www-form-urlencoded"})
    try:
        payload = json.loads(raw.decode("utf-8", "replace"))
    except ValueError:
        payload = {}
    if code != 200 or not payload.get("access_token"):
        raise RuntimeError(f"The {SERVICES[service]['label']} sign-in expired. Press Connect again in Settings > Connections.")
    saved["access_token"] = payload["access_token"]
    saved["expiry"] = time.time() + int(payload.get("expires_in") or 3600) - 60
    _write(service, saved)
    return str(saved["access_token"])


def connect(service: str, wait_seconds: int = 180) -> dict[str, Any]:
    """Open Google's sign-in in the user's browser and keep the permission on this PC."""
    if service not in SERVICES:
        return {"ok": False, "error": f"Unknown connection: {service}"}
    cid, sec = _client()
    if not cid or not sec:
        return {"ok": False, "error": SETUP, "connected": False}
    verifier = secrets.token_urlsafe(48)
    challenge = hashlib.sha256(verifier.encode()).digest()
    # base64url without padding, written out so no encoder module is needed
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    bits = int.from_bytes(challenge, "big")
    nbits = len(challenge) * 8
    pad = (6 - nbits % 6) % 6
    bits <<= pad
    chars = (nbits + pad) // 6
    challenge_text = "".join(alphabet[(bits >> (6 * (chars - 1 - i))) & 63] for i in range(chars))
    state = secrets.token_hex(16)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if q.get("state", [""])[0] == state:
                if q.get("code"):
                    self.server.code = q["code"][0]  # type: ignore[attr-defined]
                elif q.get("error"):
                    self.server.fail = q["error"][0]  # type: ignore[attr-defined]
            body = b"Signed in. You can close this tab and go back to Ped Bot."
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a: Any) -> None:
            return

    server = HTTPServer(("127.0.0.1", 0), Handler)
    server.code = ""  # type: ignore[attr-defined]
    server.fail = ""  # type: ignore[attr-defined]
    redirect = f"http://127.0.0.1:{server.server_address[1]}/"
    url = AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id": cid, "redirect_uri": redirect, "response_type": "code",
        "scope": SERVICES[service]["scopes"], "access_type": "offline", "prompt": "consent",
        "state": state, "code_challenge": challenge_text, "code_challenge_method": "S256"})
    try:
        open_browser(url)
        deadline = time.time() + wait_seconds
        while time.time() < deadline and not server.code and not server.fail:  # type: ignore[attr-defined]
            server.timeout = max(1, int(deadline - time.time()))
            server.handle_request()
    finally:
        server.server_close()
    if not server.code:  # type: ignore[attr-defined]
        return {"ok": False, "connected": False,
                "error": "Sign-in was cancelled." if server.fail else "The sign-in window closed before access was granted."}  # type: ignore[attr-defined]
    body = urllib.parse.urlencode({"code": server.code, "client_id": cid, "client_secret": sec,  # type: ignore[attr-defined]
                                   "redirect_uri": redirect, "grant_type": "authorization_code",
                                   "code_verifier": verifier}).encode()
    code, raw = _http("POST", TOKEN_URL, body, {"Content-Type": "application/x-www-form-urlencoded"})
    try:
        payload = json.loads(raw.decode("utf-8", "replace"))
    except ValueError:
        payload = {}
    if code != 200 or not payload.get("refresh_token"):
        return {"ok": False, "connected": False, "error": "Google did not return a permission. Try Connect again."}
    _write(service, {"refresh_token": payload["refresh_token"], "access_token": payload.get("access_token") or "",
                     "expiry": time.time() + int(payload.get("expires_in") or 3600) - 60,
                     "connected_at": time.time()})
    return {"ok": True, "connected": True, "message": f"{SERVICES[service]['label']} is connected on this PC."}


def disconnect(service: str) -> dict[str, Any]:
    if service not in SERVICES:
        return {"ok": False, "error": f"Unknown connection: {service}"}
    saved = _read(service)
    if saved:
        try:
            _http("POST", REVOKE_URL + "?" + urllib.parse.urlencode({"token": saved["refresh_token"]}), b"",
                  {"Content-Type": "application/x-www-form-urlencoded"})
        except Exception:
            pass
    try:
        token_file(service).unlink()
    except FileNotFoundError:
        pass
    return {"ok": True, "connected": False, "message": f"{SERVICES[service]['label']} disconnected; the local permission was deleted."}


def gmail_send(recipient: str, subject: str, body: str, sender: str = "") -> None:
    """Send through the Gmail API with the signed-in account (raw RFC 822 upload)."""
    from email.message import EmailMessage

    msg = EmailMessage()
    msg["To"] = recipient
    if sender:
        msg["From"] = sender
    msg["Subject"] = subject
    msg.set_content(body)
    code, raw = _http("POST", "https://gmail.googleapis.com/upload/gmail/v1/users/me/messages/send?uploadType=media",
                      msg.as_bytes(), {"Authorization": f"Bearer {access_token('gmail')}", "Content-Type": "message/rfc822"})
    if code not in (200, 201):
        raise RuntimeError(f"Gmail refused the message (HTTP {code}).")


def drive_search(query: str = "", limit: int = 20) -> dict[str, Any]:
    """List files in the connected Google Drive by name (read-only)."""
    try:
        token = access_token("drive")
    except RuntimeError as exc:
        return {"ok": False, "error": str(exc)}
    q = "trashed = false"
    if query.strip():
        safe = query.replace("\\", "").replace("'", "\\'")
        q += f" and name contains '{safe}'"
    url = "https://www.googleapis.com/drive/v3/files?" + urllib.parse.urlencode(
        {"q": q, "pageSize": max(1, min(100, int(limit))), "fields": "files(id,name,mimeType,modifiedTime,webViewLink)"})
    code, raw = _http("GET", url, None, {"Authorization": f"Bearer {token}"})
    try:
        files = json.loads(raw.decode("utf-8", "replace")).get("files", [])
    except ValueError:
        files = []
    if code != 200:
        return {"ok": False, "error": f"Google Drive answered HTTP {code}."}
    return {"ok": True, "files": files, "message": f"{len(files)} file(s) found."}


DECLARATIONS = [{
    "name": "drive_search",
    "description": "Search the user's connected Google Drive by file name (read-only). Needs Settings > Connections > Google Drive.",
    "parameters": {"type": "object", "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}}},
}]
TOOLS = {"drive_search": drive_search}
