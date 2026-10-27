"""Phone / away-from-home access to the chat app and the Live PC view.

OFF unless rules.yaml remote.enabled is true. It runs as a SEPARATE server
(default 127.0.0.1:8766) so the normal local app on 8765 is never exposed.
Every request needs a session cookie; you get one by logging in with a
Supabase access_token (email/password on the phone app), the long random
access token (storage/remote_token.txt), or, if set, the PIN in REMOTE_PIN
(6+ digits). Failed token/PIN logins are rate-limited and lock out.
View-only by default; remote clicks/typing need remote.allow_control: true
AND (if the remote_control confirm category is on) a "yes" from the phone.

The current tunnel URL (never the token) is also written to Supabase
pc_presence so the phone can skip pasting a Cloudflare link.

To reach it from outside your home, run a free tunnel to that port, e.g.
cloudflared (Cloudflare quick tunnel) or Tailscale. See README.
"""

from __future__ import annotations

import hmac
import json
import os
import re
import secrets
import shutil
import subprocess
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import rules

DEFAULTS = {
    "enabled": False,
    "bind": "127.0.0.1",
    "port": 8766,
    "session_hours": 12,
    "allow_control": False,
    "control_minutes": 10,
    "tunnel": "none",            # none | cloudflared
    "cloudflared_path": "",
    "public_url": "",            # e.g. your Tailscale https name; sent by Telegram
    "send_link_telegram": True,
    "max_fps": 5,
    "default_fps": 3,
    "publish_url": True,         # post the tunnel URL (never the token) so the phone app auto-connects
    "publish_server": "https://ntfy.sh",
    "publish_every_hours": 6,
}
COOKIE = "pedro_session"
MAX_FAILS_PER_IP = 5
LOCKOUT_SECONDS = 300
GLOBAL_FAIL_LIMIT = 30           # then all logins are refused until restart

_sessions: dict[str, float] = {}
_fails: dict[str, list[float]] = {}
_global_fails = 0
_control_until = 0.0
_lock = threading.Lock()


def _overlay_path() -> Path:
    return _storage() / "remote_settings.json"


def settings() -> dict[str, Any]:
    """rules.yaml remote section, then the Settings > Connect phone switch (if used)."""
    cfg = rules.section("remote", DEFAULTS)
    try:
        cfg.update(json.loads(_overlay_path().read_text(encoding="utf-8")))
    except Exception:
        pass
    return cfg


def save_overlay(**values: Any) -> None:
    path = _overlay_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        data = {}
    data.update(values)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _storage() -> Path:
    import agent_config

    return agent_config.storage_dir()


def token_path() -> Path:
    return _storage() / "remote_token.txt"


def access_token(create: bool = True) -> str:
    path = token_path()
    if path.is_file():
        value = path.read_text(encoding="utf-8").strip()
        if len(value) >= 32:
            return value
    if not create:
        return ""
    value = secrets.token_urlsafe(32)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return value


def rotate_token() -> str:
    try:
        token_path().unlink()
    except FileNotFoundError:
        pass
    with _lock:
        _sessions.clear()
    return access_token()


# ---- one-time pairing codes (QR) ----
PAIR_TTL = 600
APK_URL = "https://github.com/lhymite36-bot/Pedro_Agent/releases/download/android-v1.5.10/PedBot-1.5.10.apk"
_pair_codes: dict[str, float] = {}
_PAIR_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def new_pairing_code(now: float | None = None) -> str:
    now = time.time() if now is None else now
    raw = "".join(secrets.choice(_PAIR_ALPHABET) for _ in range(8))
    code = raw[:4] + "-" + raw[4:]
    with _lock:
        for c, exp in list(_pair_codes.items()):
            if exp < now:
                _pair_codes.pop(c, None)
        _pair_codes[code] = now + PAIR_TTL
    return code


def redeem_pairing_code(code: str, ip: str, now: float | None = None) -> tuple[str, str]:
    """(token, error). Single use, 10 minutes, shares the login lockout."""
    global _global_fails
    now = time.time() if now is None else now
    code = (code or "").strip().upper().replace(" ", "")
    if len(code) == 8:
        code = code[:4] + "-" + code[4:]
    with _lock:
        if _global_fails >= GLOBAL_FAIL_LIMIT:
            return "", "Too many failed attempts. Restart the app on your PC."
        recent = [t for t in _fails.get(ip, []) if now - t < LOCKOUT_SECONDS]
        _fails[ip] = recent
        if len(recent) >= MAX_FAILS_PER_IP:
            return "", "Too many attempts. Wait 5 minutes."
        exp = _pair_codes.pop(code, None)
        if exp is None or exp < now:
            _fails.setdefault(ip, []).append(now)
            _global_fails += 1
            return "", "That pairing code is wrong or expired. Make a new one on your PC."
    _note("Phone paired")
    return access_token(), ""


def pair_uri(url: str, code: str) -> str:
    from urllib.parse import quote

    return f"pedroagent://pair?u={quote(url.rstrip('/'), safe='')}&c={code}"


def qr_svg(text: str) -> str:
    import qrcode
    import qrcode.image.svg

    img = qrcode.make(text, image_factory=qrcode.image.svg.SvgPathImage, box_size=10, border=2)
    return img.to_string(encoding="unicode")


def cloudflared_download(dest_dir: Path | None = None, fetch: Any = None) -> str:
    """Download the free cloudflared.exe into storage/bin (user consented in Settings)."""
    import urllib.request

    dest_dir = dest_dir or (_storage() / "bin")
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / ("cloudflared.exe" if os.name == "nt" else "cloudflared")
    url = ("https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"
           if os.name == "nt" else
           "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64")
    data = (fetch or (lambda u: urllib.request.urlopen(u, timeout=120).read()))(url)
    if len(data) < 1_000_000:
        raise RuntimeError("The cloudflared download looks incomplete.")
    tmp = dest.with_suffix(".part"); tmp.write_bytes(data); os.replace(tmp, dest)
    if os.name != "nt":
        os.chmod(dest, 0o755)
    save_overlay(cloudflared_path=str(dest))
    return str(dest)


def phone_status() -> dict[str, Any]:
    cfg = settings()
    return {"enabled": bool(cfg["enabled"]), "running": _server is not None, "url": public_url,
            "tunnel": cfg["tunnel"], "cloudflared": bool(cloudflared_exe()),
            "apk": APK_URL}


def phone_enable(state: Any, consent: bool = False) -> dict[str, Any]:
    if not cloudflared_exe():
        if not consent:
            return {"ok": False, "needs_consent": True,
                    "error": "Phone access needs Cloudflare's free cloudflared tool (about 60 MB). Allow the download?"}
        try:
            cloudflared_download()
        except Exception as exc:
            return {"ok": False, "error": f"Couldn't download cloudflared: {exc}"}
    save_overlay(enabled=True, tunnel="cloudflared")
    access_token()
    r = start(state)
    return {**r, **phone_status()}


def phone_disable() -> dict[str, Any]:
    global public_url
    save_overlay(enabled=False)
    stop()
    public_url = ""
    return {"ok": True, **phone_status()}


def phone_pair() -> dict[str, Any]:
    if not public_url:
        return {"ok": False, "error": "Phone access is still starting. Wait a few seconds and try again."}
    code = new_pairing_code()
    uri = pair_uri(public_url, code)
    return {"ok": True, "code": code, "url": public_url, "uri": uri, "qr_svg": qr_svg(uri),
            "expires_in": PAIR_TTL, **phone_status()}


def unpair_all() -> dict[str, Any]:
    token = rotate_token()
    with _lock:
        _pair_codes.clear()
    if public_url:
        threading.Thread(target=_republish_loop, args=(public_url, token), daemon=True).start()
    _note("All phones unpaired")
    return {"ok": True, "message": "All phones are signed out. Pair again with a new QR code."}


def _pin() -> str:
    pin = os.environ.get("REMOTE_PIN", "").strip()
    return pin if re.fullmatch(r"\d{6,12}", pin) else ""


def reset_state() -> None:
    global _global_fails, _control_until
    with _lock:
        _sessions.clear()
        _fails.clear()
        _global_fails = 0
        _control_until = 0.0


def check_login(secret: str, ip: str, now: float | None = None) -> tuple[bool, str]:
    """Returns (ok, error). Rate-limited per IP plus a global cap."""
    global _global_fails
    now = time.time() if now is None else now
    with _lock:
        if _global_fails >= GLOBAL_FAIL_LIMIT:
            return False, "Too many failed logins. Restart the app on your PC to try again."
        recent = [t for t in _fails.get(ip, []) if now - t < LOCKOUT_SECONDS]
        _fails[ip] = recent
        if len(recent) >= MAX_FAILS_PER_IP:
            return False, "Too many attempts. Wait 5 minutes."
    secret = (secret or "").strip()
    good = bool(secret) and (hmac.compare_digest(secret, access_token())
                             or (bool(_pin()) and hmac.compare_digest(secret, _pin())))
    if good:
        return True, ""
    with _lock:
        _fails.setdefault(ip, []).append(now)
        _global_fails += 1
    return False, "Wrong token or PIN."


def new_session(now: float | None = None) -> str:
    sid = secrets.token_urlsafe(32)
    with _lock:
        _sessions[sid] = (time.time() if now is None else now) + float(settings()["session_hours"]) * 3600
    return sid


def session_valid(cookie_header: str, now: float | None = None) -> bool:
    now = time.time() if now is None else now
    sid = ""
    for part in (cookie_header or "").split(";"):
        name, _, value = part.strip().partition("=")
        if name == COOKIE:
            sid = value
    if not sid:
        return False
    with _lock:
        expires = _sessions.get(sid)
        if expires is None:
            return False
        if expires < now:
            _sessions.pop(sid, None)
            return False
    return True


def end_session(cookie_header: str) -> None:
    for part in (cookie_header or "").split(";"):
        name, _, value = part.strip().partition("=")
        if name == COOKIE:
            with _lock:
                _sessions.pop(value, None)


# ---- remote control ----

def control_needs_yes() -> bool:
    return rules.needs_confirmation("remote_control_action", {})


def allow_control(confirm: str) -> dict[str, Any]:
    global _control_until
    if not settings()["allow_control"]:
        return {"ok": False, "error": "Remote control is off (rules.yaml remote.allow_control)."}
    if control_needs_yes() and str(confirm).strip().casefold() != "yes":
        return {"ok": False, "error": "Needs your yes.", "needs_confirmation": True}
    minutes = max(1, int(settings()["control_minutes"] or 10))
    with _lock:
        _control_until = time.time() + minutes * 60
    _note(f"Remote control allowed for {minutes} min")
    return {"ok": True, "message": f"Control allowed for {minutes} minutes."}


def control_open() -> bool:
    if not settings()["allow_control"]:
        return False
    return (not control_needs_yes()) or time.time() < _control_until


def remote_control_action(type: str, x: float = 0.0, y: float = 0.0, text: str = "") -> dict[str, Any]:
    """Phone -> PC input. Registered as a tool so rules.yaml tools.blocked applies."""
    import pyautogui

    kind = (type or "").casefold()
    if kind == "click":
        width, height = pyautogui.size()
        px, py = int(max(0.0, min(1.0, float(x))) * (width - 1)), int(max(0.0, min(1.0, float(y))) * (height - 1))
        pyautogui.click(px, py)
        return {"ok": True, "message": f"Clicked {px},{py}."}
    if kind == "type":
        value = str(text)[:500]
        pyautogui.write(value, interval=0.01)
        return {"ok": True, "message": f"Typed {len(value)} characters."}
    return {"ok": False, "error": "type must be click or type."}


def control_refusal() -> dict[str, Any] | None:
    """Why phone input is refused right now, or None when it may run.
    Needs remote.allow_control, the 'Allow control' yes, and remote_control_action not blocked."""
    if not settings()["allow_control"]:
        return {"ok": False, "error": "View only. Set remote.allow_control: true in rules.yaml to allow control."}
    if not control_open():
        return {"ok": False, "error": "Tap 'Allow control' first.", "needs_confirmation": True}
    reason = rules.tool_block_reason("remote_control_action")
    if reason:
        return {"ok": False, "error": reason}
    return None


def phone_control(data: dict[str, Any]) -> dict[str, Any]:
    """Live PC input from the phone: the same permission checks as do_control, then the
    Live PC control (clicks, drags, scrolls, typing)."""
    refused = control_refusal()
    if refused is not None:
        _note("Remote control refused")
        return refused
    import live_pc

    result = live_pc.local_control(data if isinstance(data, dict) else {})
    _note(f"Remote {str((data or {}).get('type') or '')}" + (" ok" if result.get("ok") else " failed"))
    return result


def do_control(data: dict[str, Any]) -> dict[str, Any]:
    refused = control_refusal()
    if refused is not None:
        return refused
    import agent_core

    function = agent_core.TOOLS.get("remote_control_action", remote_control_action)
    args = {"type": str(data.get("type") or ""), "x": float(data.get("x") or 0), "y": float(data.get("y") or 0),
            "text": str(data.get("text") or "")}
    try:
        result = function(**args)
    except Exception as exc:
        result = {"ok": False, "error": str(exc)}
    _note(f"Remote {args['type']}" + (" ok" if result.get("ok") else " failed"))
    return result


def _note(text: str) -> None:
    try:
        import live_pc

        live_pc.note("activity", text=text)
    except Exception:
        pass


# ---- login page (self-contained, no external assets) ----

LOGIN_HTML = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Ped Bot - sign in</title><meta name="theme-color" content="#0e0f11"><link rel="manifest" href="/manifest.webmanifest">
<style>html,body{margin:0;min-height:100%;background:#0e0f11;color:#e7e9ea;font:16px system-ui,sans-serif}
body{min-height:100vh;display:grid;place-items:center;padding:24px}
.auth-card{width:min(420px,92vw);background:#16181c;border:1px solid #26292e;border-radius:16px;padding:28px 24px 22px}
.auth-mark{font-size:15px;font-weight:700;color:#8b9096;margin-bottom:10px;letter-spacing:.02em}
h1{margin:0 0 6px;font-size:28px;font-weight:700;color:#e7e9ea}
p{margin:0 0 20px;color:#8b9096;font-size:14px;line-height:1.45}
label{display:block;font-size:13px;font-weight:650;color:#e7e9ea;margin:0 0 12px}
input{display:block;width:100%;margin-top:6px;box-sizing:border-box;background:#0e0f11;border:1px solid #26292e;border-radius:10px;color:#e7e9ea;padding:11px 12px;font-size:15px;outline:none}
input:focus{border-color:#3e4247}
button{width:100%;margin-top:6px;border:0;border-radius:999px;padding:12px 16px;background:#1d9bf0;color:#fff;font-size:15px;font-weight:700;cursor:pointer}
#e{color:#f4212e;font-size:13px;min-height:1.2em;margin:4px 0 10px}</style></head>
<body><form id="f" class="auth-card"><div class="auth-mark">Ped Bot</div><h1>Sign in</h1>
<p>Use the token from your PC, or the phone app with email and password.</p>
<label>Access token or PIN<input id="s" type="password" autocomplete="current-password" autofocus></label>
<p id="e"></p><button>Sign in</button></form><script>
async function go(secret){const r=await fetch('/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({secret})});
const j=await r.json();if(j.ok){location.replace('/?ui=grokskin');}else{document.getElementById('e').textContent=j.error||'Failed';}}
document.getElementById('f').onsubmit=(e)=>{e.preventDefault();go(document.getElementById('s').value);};
const h=new URLSearchParams(location.hash.slice(1)).get('t');if(h){history.replaceState(null,'','/login');go(h);}
</script></body></html>"""

PUBLIC_PATHS = {"/login", "/manifest.webmanifest", "/icon-192.png", "/icon-512.png", "/api/auth/config"}


def make_remote_handler(state: Any) -> type:
    import chat_app

    Base = chat_app.make_handler(state)

    class RemoteHandler(Base):  # type: ignore[misc, valid-type]
        remote = True

        def _secure(self) -> bool:
            if self.headers.get("X-Forwarded-Proto", "").casefold() == "https":
                return True
            # M5: Cloudflare may omit the header; still mark Secure on https tunnels.
            url = (public_url or "").strip().casefold()
            return url.startswith("https://")

        def _gate(self) -> bool:
            path = urlparse(self.path).path
            if path in PUBLIC_PATHS:
                return True
            if session_valid(self.headers.get("Cookie", "")):
                return True
            try:
                import supabase_auth
                user = supabase_auth.user_from_request(self)
            except Exception:
                user = None
            if user:
                self.auth_user = user
                return True
            if path in {"/", "/index.html"} and self.command == "GET":
                self.send_response(302)
                self.send_header("Location", "/login")
                self.send_header("Content-Length", "0")
                self.end_headers()
            else:
                # 403 so an older APK does not treat this as a dead tunnel.
                self._send(403, b'{"ok":false,"error":"sign in first","code":"auth_required"}')
            return False

        def _body(self) -> dict[str, Any]:
            self._body_read = True
            return super()._body()

        def _drain(self) -> None:
            # A refused POST (401/403) must still read its small body, or Windows resets
            # the socket before the answer arrives. Big bodies are not read; we just close.
            if self.command != "POST" or getattr(self, "_body_read", False):
                return
            self._body_read = True
            try:
                left = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                left = 0
            if 0 < left <= 65536:
                try:
                    self.rfile.read(left)
                except Exception:
                    pass
            elif left:
                self.close_connection = True

        def _send(self, code: int, body: bytes, kind: str = "application/json") -> None:
            if code >= 400:
                self._drain()
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def _client_ip(self) -> str:
            return (self.headers.get("CF-Connecting-IP") or self.headers.get("X-Forwarded-For", "").split(",")[0].strip()
                    or self.client_address[0])

        def do_GET(self) -> None:
            path = urlparse(self.path).path
            if path == "/login":
                self._send(200, LOGIN_HTML.encode(), "text/html; charset=utf-8")
                return
            if path == "/logout":
                end_session(self.headers.get("Cookie", ""))
                self.send_response(302)
                self.send_header("Set-Cookie", f"{COOKIE}=; Max-Age=0; Path=/; HttpOnly; SameSite=Strict")
                self.send_header("Location", "/login")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if path == "/api/rules" or path == "/api/settings":
                if not self._gate():
                    return
            super().do_GET()

        def do_POST(self) -> None:
            path = urlparse(self.path).path
            if path == "/pair":   # QR pairing: one-time code -> token (rate-limited)
                token, error = redeem_pairing_code(str(self._body().get("code") or ""), self._client_ip())
                self._json({"ok": True, "token": token} if token else {"ok": False, "error": error}, 200 if token else 401)
                return
            if path == "/login":
                if not self._same_origin():
                    self._send(403, b'{"error":"cross-origin"}')
                    return
                data = self._body()
                access = str(data.get("access_token") or "").strip()
                ok, error = False, "Wrong token or PIN."
                if access:
                    try:
                        import supabase_auth
                        user = supabase_auth.user_from_token(access)
                    except Exception:
                        user = None
                    if user:
                        ok, error = True, ""
                        self.auth_user = user
                    else:
                        ok, error = False, "Please sign in."
                else:
                    ok, error = check_login(str(data.get("secret") or ""), self._client_ip())
                if not ok:
                    _note("Failed remote sign-in")
                    self._json({"ok": False, "error": error}, 403 if access else 401)
                    return
                sid = new_session()
                max_age = int(float(settings()["session_hours"]) * 3600)
                body = b'{"ok":true}'
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Set-Cookie", f"{COOKIE}={sid}; Max-Age={max_age}; Path=/; HttpOnly; SameSite=Strict"
                                 + ("; Secure" if self._secure() else ""))
                self.end_headers()
                self.wfile.write(body)
                _note("Phone signed in")
                return
            if not self._gate():
                return
            if not self._same_origin():
                self._send(403, b'{"error":"cross-origin"}')
                return
            if path == "/api/rules":  # editing rules from outside is not allowed
                self._json({"ok": False, "error": "Rules can only be changed on the PC."}, 403)
                return
            if path == "/live/control/allow":
                self._json(allow_control(str(self._body().get("confirm") or "")))
                return
            if path == "/live/control":
                result = phone_control(self._body())
                self._json(result)
                return
            super().do_POST()

    # The base do_POST calls _gate again; that is fine (cookie still valid).
    return RemoteHandler


# ---- server + tunnel ----

_server: ThreadingHTTPServer | None = None
_tunnel: subprocess.Popen | None = None
_tunnel_gen = 0
public_url = ""


def start(state: Any) -> dict[str, Any]:
    global _server
    cfg = settings()
    if not cfg["enabled"]:
        return {"ok": False, "error": "Remote access is off (rules.yaml remote.enabled)."}
    if _server is not None:
        return {"ok": True, "message": "Already running."}
    token = access_token()
    _server = ThreadingHTTPServer((str(cfg["bind"]), int(cfg["port"])), make_remote_handler(state))
    _server.daemon_threads = True
    threading.Thread(target=_server.serve_forever, name="remote-server", daemon=True).start()
    local = f"http://127.0.0.1:{_server.server_address[1]}/"
    info = {"ok": True, "local_url": local, "token_file": str(token_path())}
    if str(cfg["tunnel"]).casefold() == "cloudflared":
        threading.Thread(target=start_tunnel, args=(_server.server_address[1],), daemon=True).start()
        threading.Thread(target=_tunnel_watchdog, daemon=True, name="tunnel-watchdog").start()
    elif cfg["public_url"]:
        _announce(str(cfg["public_url"]), token)
    info["message"] = f"Remote access on {local} (token in {token_path()})."
    return info


def stop() -> None:
    global _server, _tunnel, _tunnel_gen
    _tunnel_gen += 1
    proc = _tunnel
    _tunnel = None
    if proc is not None:
        _end_process(proc)
    if _server is not None:
        try:
            _server.shutdown()
            _server.server_close()
        except Exception:
            pass
        _server = None


def _end_process(proc: subprocess.Popen) -> None:
    try:
        proc.terminate()
    except Exception:
        pass
    try:
        proc.wait(timeout=5)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def cloudflared_exe() -> str | None:
    configured = str(settings()["cloudflared_path"] or "").strip()
    if configured and Path(configured).is_file():
        return configured
    return shutil.which("cloudflared")


TUNNEL_URL = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")


def parse_tunnel_url(line: str) -> str:
    match = TUNNEL_URL.search(line or "")
    return match.group(0) if match else ""


def _follow_tunnel_output(proc: subprocess.Popen) -> bool:
    """Read until cloudflared closes its output. Returns True when that process is still running.

    Stopping at the first URL leaves the pipe unread. Once the pipe fills, cloudflared
    blocks and the phone link stops resolving.
    """
    global public_url
    announced = False
    stream = proc.stdout
    try:
        if stream is not None:
            for line in stream:
                if announced:
                    continue
                url = parse_tunnel_url(line)
                if not url:
                    continue
                announced = True
                public_url = url
                _announce(url, access_token())
    except Exception:
        pass
    try:
        alive = proc.poll() is None
    except Exception:
        alive = False
    if not alive:
        try:
            proc.wait(timeout=5)
        except Exception:
            pass
    return alive


def _tunnel_pid_file() -> Path:
    import agent_config
    return agent_config.storage_dir() / "tunnel.pid"


def _end_stale_tunnel() -> None:
    """1.4.15: a tunnel left running by an earlier app run (app killed, crash, upgrade) is closed first.
    Before this, every restart left one more cloudflared.exe (~32 MB each) running."""
    try:
        pid = int(_tunnel_pid_file().read_text(encoding="utf-8").strip() or 0)
    except Exception:
        return
    if pid <= 0 or pid == os.getpid():
        return
    try:
        if os.name == "nt":   # ctypes, not tasklist: tasklist /FI needs WMI, which is broken on some PCs
            import ctypes
            from ctypes import wintypes
            k32 = ctypes.WinDLL("kernel32", use_last_error=True)
            k32.OpenProcess.restype = wintypes.HANDLE
            handle = k32.OpenProcess(0x1000 | 0x0001, False, pid)   # QUERY_LIMITED_INFORMATION | TERMINATE
            if not handle:
                return
            try:
                buf = ctypes.create_unicode_buffer(1024)
                size = wintypes.DWORD(1024)
                if k32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)) and \
                        "cloudflared" in buf.value.casefold():
                    k32.TerminateProcess(handle, 1)
            finally:
                k32.CloseHandle(handle)
        else:
            with open(f"/proc/{pid}/comm", encoding="utf-8") as f:
                if "cloudflared" in f.read():
                    os.kill(pid, 9)
    except Exception:
        pass


def _remember_tunnel(proc: Any) -> None:
    try:
        _tunnel_pid_file().write_text(str(proc.pid), encoding="utf-8")
    except Exception:
        pass



def _tunnel_watchdog() -> None:
    """1.5.10 C3: if cloudflared exits while phone access is on, start it again."""
    while True:
        time.sleep(20)
        try:
            cfg = settings()
            if not cfg.get("enabled"):
                continue
            if str(cfg.get("tunnel") or "").casefold() != "cloudflared":
                continue
            proc = _tunnel
            if proc is not None and proc.poll() is None:
                continue
            if not _server:
                continue
            port = _server.server_address[1]
            print("Remote: watchdog restarting the phone tunnel.", flush=True)
            try:
                import agent_log
                agent_log.event("tunnel_watchdog_restart")
            except Exception:
                pass
            threading.Thread(target=start_tunnel, args=(port,), daemon=True, name="tunnel-restart").start()
        except Exception as exc:
            print(f"Remote: watchdog error: {exc}", flush=True)


def start_tunnel(port: int) -> str:
    """Cloudflare quick tunnel (free, no account). Returns the https URL."""
    global _tunnel, public_url
    exe = cloudflared_exe()
    if not exe:
        print("Remote: cloudflared not found. Install it (winget install Cloudflare.cloudflared) or use Tailscale.", flush=True)
        return ""
    _end_stale_tunnel()
    flags: dict[str, Any] = {}
    if os.name == "nt":
        flags["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    generation = _tunnel_gen
    quick_fails = 0
    while generation == _tunnel_gen:
        proc = subprocess.Popen(
            [exe, "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{port}"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
            text=True, encoding="utf-8", errors="replace", bufsize=1, shell=False, **flags)
        _tunnel = proc
        _remember_tunnel(proc)
        if generation != _tunnel_gen:
            _end_process(proc)
            if _tunnel is proc:
                _tunnel = None
            break
        opened = time.monotonic()
        alive = _follow_tunnel_output(proc)
        if generation != _tunnel_gen:
            if _tunnel is proc:
                _tunnel = None
            break
        if alive:
            break
        if _tunnel is proc:
            _tunnel = None
        public_url = ""
        if time.monotonic() - opened >= 45:
            quick_fails = 0
        else:
            quick_fails += 1
        # C3: keep retrying while phone access is enabled. Back off, never stop forever.
        wait = min(2 ** min(quick_fails, 6), 60)
        print(f"Remote: tunnel dropped; retrying in {wait}s (attempt {quick_fails}).", flush=True)
        try:
            import agent_log
            agent_log.event("tunnel_retry", attempt=quick_fails, wait=wait)
        except Exception:
            pass
        time.sleep(wait)
    return public_url


def link_with_token(url: str, token: str) -> str:
    # Token in the #fragment: browsers never send it to the server or tunnel logs.
    return url.rstrip("/") + "/login#t=" + token


# ---- auto-connect: publish the current URL (signed, never the token) ----
# Topic name and signature both come from the access token, which only this PC
# and your phone know. Strangers can't find the topic, and the phone ignores any
# message whose HMAC doesn't match, so nobody can redirect it to a fake site.

def publish_topic(token: str) -> str:
    import hashlib

    return "pedro-" + hashlib.sha256(("pedro-topic:" + token).encode()).hexdigest()[:32]


def sign_url(url: str, token: str, ts: int | None = None) -> str:
    import hashlib

    ts = int(time.time()) if ts is None else int(ts)
    mac = hmac.new(("pedro-url:" + token).encode(), f"{url}|{ts}".encode(), hashlib.sha256).hexdigest()
    return json.dumps({"url": url, "ts": ts, "sig": mac})


def verify_signed(body: str, token: str) -> str:
    try:
        d = json.loads(body)
        url, ts = str(d["url"]), int(d["ts"])
    except Exception:
        return ""
    if not TUNNEL_URL.fullmatch(url) and not url.startswith("https://"):
        return ""
    good = json.loads(sign_url(url, token, ts))["sig"]
    return url if hmac.compare_digest(good, str(d.get("sig", ""))) else ""


def publish_url(url: str, token: str) -> bool:
    import urllib.request

    cfg = settings()
    if not cfg["publish_url"] or not url or not token:
        return False
    target = str(cfg["publish_server"]).rstrip("/") + "/" + publish_topic(token)
    try:
        req = urllib.request.Request(target, data=sign_url(url, token).encode(), method="POST",
                                     headers={"Title": "pedro-url", "Cache": "yes"})
        with urllib.request.urlopen(req, timeout=15) as r:
            return 200 <= r.status < 300
    except Exception as exc:
        print(f"Remote: couldn't publish link for the phone app ({exc}).", flush=True)
        return False


def _publish_presence(url: str) -> None:
    try:
        import supabase_auth

        if supabase_auth.publish_pc_url(url):
            print("Remote: phone account can find this PC.", flush=True)
    except Exception:
        pass


def _republish_loop(url: str, token: str) -> None:
    hours = max(1.0, float(settings()["publish_every_hours"] or 6))
    _publish_presence(url)
    while public_url == url and access_token(create=False) == token:
        if publish_url(url, token):
            print("Remote: phone app auto-connect link published.", flush=True)
        _publish_presence(url)
        time.sleep(hours * 3600)


def _announce(url: str, token: str) -> None:
    """Publish the phone URL (ntfy + Supabase). Errors are logged (M6)."""
    global public_url
    public_url = url
    threading.Thread(target=_republish_loop, args=(url, token), daemon=True).start()
    print(f"Remote: {url}  (sign in with the token in {token_path()})", flush=True)
    _note("Remote link ready")
    if not settings()["send_link_telegram"]:
        return
    try:
        import remote_bridge

        if remote_bridge.paired():
            remote_bridge.notify(f"Ped Bot on your phone: {link_with_token(url, token)}\n"
                                 "Open it, then use 'Add to Home screen' to install. Don't share this link.")
    except Exception:
        pass


def status() -> dict[str, Any]:
    cfg = settings()
    return {"enabled": bool(cfg["enabled"]), "running": _server is not None, "public_url": public_url,
            "allow_control": bool(cfg["allow_control"]), "tunnel": cfg["tunnel"]}


DECLARATIONS = [{
    "name": "remote_control_action",
    "description": "Internal: phone Live PC input (click at a 0..1 screen point, or type text). Only used by the Live PC page.",
    "parameters": {"type": "object", "properties": {"type": {"type": "string"}, "x": {"type": "number"},
                                                     "y": {"type": "number"}, "text": {"type": "string"}},
                   "required": ["type"]},
}]
TOOLS = {"remote_control_action": remote_control_action}
