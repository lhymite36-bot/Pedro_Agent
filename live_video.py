"""Live PC webcam output and phone-camera input.

The PC feed publishes to a Telegram RTMP address only when TELEGRAM_RTMP_URL
and TELEGRAM_STREAM_KEY are both set in the environment. The model cannot
pass that address or key. Otherwise the PC camera is served as JPEG frames
on a local page that runs only while the feed is on.

A Telegram Mini App button is sent only when LIVE_PUBLIC_URL is https.
An http address is sent as a link, with a note that Mini Apps need https.

The phone page uses getUserMedia and posts JPEG frames to this process.
Those frames are the latest picture the model can look at. This module does
not open a WebRTC peer connection and does not import aiortc.

Tests set live_frame_override and stream_process_override. They must not
open a webcam, spawn ffmpeg, or contact Telegram.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import socket
import subprocess
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

MAX_FRAME_BYTES = 1_500_000
DEFAULT_SECONDS = 120
MAX_SECONDS = 600
MIN_SECONDS = 1
_FRAME_GAP_SECONDS = 0.12
_PC_BUTTON = "📹 View Live PC Webcam"
_PHONE_BUTTON = "📹 Start Phone Camera"

_state_lock = threading.Lock()
_server: ThreadingHTTPServer | None = None
_server_thread: threading.Thread | None = None
_token = ""
_bound_port = 0
_base_url = ""
_mini_app = False
_pc_on = False
_phone_on = False
_pc_stop = threading.Event()
_phone_stop = threading.Event()
_pc_thread: threading.Thread | None = None
_pc_proc: Any = None
_pc_jpeg = b""
_phone_jpeg = b""
_phone_timer: threading.Timer | None = None
_pc_seconds = 0
_phone_seconds = 0


def _agent() -> Any:
    import agent_core

    return agent_core


def _safe(text: str) -> str:
    return _agent()._scrub(text or "")


def _ok(message: str, **extra: Any) -> dict[str, Any]:
    return _agent()._ok(_safe(message), **extra)


def _err(message: str, **extra: Any) -> dict[str, Any]:
    return _agent()._err(_safe(message), **extra)


def _duration(value: Any) -> int:
    if value is None or value == "":
        raw = os.environ.get("LIVE_STREAM_SECONDS", "").strip()
        value = raw or DEFAULT_SECONDS
    if isinstance(value, bool):
        raise ValueError("seconds must be a whole number from 1 to 600.")
    if isinstance(value, str):
        text = value.strip()
        if not text.isdigit():
            raise ValueError("seconds must be a whole number from 1 to 600.")
        number = int(text)
    elif isinstance(value, int):
        number = value
    elif isinstance(value, float) and value.is_integer():
        number = int(value)
    else:
        raise ValueError("seconds must be a whole number from 1 to 600.")
    if number < MIN_SECONDS or number > MAX_SECONDS:
        raise ValueError("seconds must be a whole number from 1 to 600.")
    return number


def _action(value: Any) -> str:
    text = str(value or "start").strip().casefold().replace("-", "_").replace(" ", "_")
    if text in {"", "start", "begin", "on"}:
        return "start"
    if text in {"stop", "off", "end"}:
        return "stop"
    if text in {"status", "state"}:
        return "status"
    if text in {"look", "frame", "see"}:
        return "look"
    return text


def _jpeg_ok(data: Any) -> bool:
    if not isinstance(data, (bytes, bytearray)):
        return False
    blob = bytes(data)
    return 16 <= len(blob) <= MAX_FRAME_BYTES and blob.startswith(b"\xff\xd8")


def _rtmp_target() -> tuple[str, str] | None:
    """Return the env RTMP target, or None when live broadcast is not configured."""
    url = os.environ.get("TELEGRAM_RTMP_URL", "").strip()
    key = os.environ.get("TELEGRAM_STREAM_KEY", "").strip()
    if not url and not key:
        return None
    if not url or not key:
        raise ValueError(
            "Set both TELEGRAM_RTMP_URL and TELEGRAM_STREAM_KEY, or leave both empty."
        )
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in {"rtmp", "rtmps"} or not parts.hostname:
        raise ValueError("TELEGRAM_RTMP_URL must start with rtmp:// or rtmps://.")
    if parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError("TELEGRAM_RTMP_URL cannot include a login, query, or fragment.")
    if re.search(r"[\s\"'`;&|$<>\\]", url) or re.search(r"[\s\"'`;&|$<>\\]", key):
        raise ValueError("The RTMP address or stream key has characters that are not allowed.")
    if len(key) < 8 or len(key) > 200:
        raise ValueError("TELEGRAM_STREAM_KEY must be 8 to 200 characters.")
    publish = url.rstrip("/") + "/" + key
    return url, publish


def _listen_address() -> tuple[str, int]:
    agent = _agent()
    override = agent.live_bind_override
    if override is not None:
        host, port = override
        return str(host), int(port)
    raw = os.environ.get("LIVE_VIDEO_PORT", "").strip()
    port = int(raw) if raw.isdigit() else 8765
    if port < 1 or port > 65535:
        port = 8765
    return "0.0.0.0", port


def _advertise_host(bound_host: str) -> str:
    agent = _agent()
    chosen = agent.live_advertise_override
    if chosen:
        return str(chosen)
    if bound_host not in {"0.0.0.0", "::", ""}:
        return bound_host
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("192.0.2.1", 9))
        return str(sock.getsockname()[0])
    except Exception:
        return "127.0.0.1"
    finally:
        sock.close()


def _public_base(port: int, bound_host: str) -> tuple[str, bool]:
    raw = os.environ.get("LIVE_PUBLIC_URL", "").strip()
    if raw:
        if re.search(r"[\s\"'`]", raw):
            raise ValueError("LIVE_PUBLIC_URL has characters that are not allowed.")
        parts = urllib.parse.urlsplit(raw)
        if parts.scheme not in {"http", "https"} or not parts.hostname:
            raise ValueError("LIVE_PUBLIC_URL must be an http or https address.")
        if parts.username or parts.password:
            raise ValueError("LIVE_PUBLIC_URL cannot include a login.")
        origin = f"{parts.scheme}://{parts.netloc}"
        return origin.rstrip("/"), parts.scheme == "https"
    host = _advertise_host(bound_host)
    return f"http://{host}:{port}", False


def _jpeg_to_bgr(data: bytes) -> tuple[bytes, int, int]:
    import io

    from PIL import Image

    image = Image.open(io.BytesIO(data))
    image = image.convert("RGB")
    width, height = image.size
    if width < 2 or height < 2:
        raise ValueError("The webcam frame is too small.")
    if width % 2 or height % 2:
        width -= width % 2
        height -= height % 2
        image = image.crop((0, 0, width, height))
        width, height = image.size
    raw = image.tobytes()
    swapped = bytearray(len(raw))
    swapped[0::3] = raw[2::3]
    swapped[1::3] = raw[1::3]
    swapped[2::3] = raw[0::3]
    return bytes(swapped), width, height


class _LiveServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


def _page(kind: str) -> bytes:
    token = _token
    if kind == "phone":
        frame_url = json.dumps(f"/live/{token}/phone/frame")
        body = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Phone camera</title></head>
<body>
<p id="status">Tap start, then allow the camera.</p>
<button type="button" id="go">Start camera</button>
<video id="video" autoplay playsinline muted></video>
<canvas id="canvas" hidden></canvas>
<script>
const status = document.getElementById("status");
const video = document.getElementById("video");
const canvas = document.getElementById("canvas");
const frameUrl = {frame_url};
let timer = 0;
function sendFrame() {{
  if (!video.videoWidth) return;
  const width = Math.min(640, video.videoWidth);
  const height = Math.max(2, Math.round(video.videoHeight * (width / video.videoWidth)));
  canvas.width = width - (width % 2);
  canvas.height = height - (height % 2);
  canvas.getContext("2d").drawImage(video, 0, 0, canvas.width, canvas.height);
  canvas.toBlob(function (blob) {{
    if (!blob) return;
    fetch(frameUrl, {{method: "POST", headers: {{"Content-Type": "image/jpeg"}}, body: blob}});
  }}, "image/jpeg", 0.7);
}}
function startCamera() {{
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {{
    status.textContent = "This browser cannot open the camera.";
    return;
  }}
  navigator.mediaDevices.getUserMedia({{video: {{facingMode: "user"}}, audio: false}})
    .then(function (stream) {{
      video.srcObject = stream;
      status.textContent = "Sending frames to the computer.";
      if (!timer) timer = setInterval(sendFrame, 400);
    }})
    .catch(function () {{
      status.textContent = "Camera permission was blocked.";
    }});
}}
document.getElementById("go").addEventListener("click", startCamera);
</script>
</body></html>
"""
        return body.encode("utf-8")
    body = """<!DOCTYPE html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Live PC Webcam</title></head>
<body>
<h1>Live PC Webcam</h1>
<img id="cam" alt="PC webcam" src="pc.mjpg">
<script>
const img = document.getElementById("cam");
img.addEventListener("error", function () {
  setInterval(function () { img.src = "pc.jpg?t=" + Date.now(); }, 400);
}, {once: true});
</script>
</body></html>
"""
    return body.encode("utf-8")


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _route(self) -> str | None:
        path = urllib.parse.urlsplit(self.path).path
        parts = [urllib.parse.unquote(part) for part in path.split("/") if part]
        if len(parts) < 3 or parts[0] != "live":
            return None
        token = parts[1]
        current = _token
        if not current or len(token) != len(current):
            return None
        if not secrets.compare_digest(token, current):
            return None
        return "/".join(parts[2:])

    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _reject(self, code: int) -> None:
        reason = b"no"
        try:
            self.send_response(code)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(reason)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(reason)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            return

    def do_GET(self) -> None:
        route = self._route()
        if route == "pc":
            if not _pc_on:
                self._reject(404)
                return
            self._send(200, _page("pc"), "text/html; charset=utf-8")
            return
        if route == "phone":
            if not _phone_on:
                self._reject(404)
                return
            self._send(200, _page("phone"), "text/html; charset=utf-8")
            return
        if route == "pc.jpg":
            frame = _pc_jpeg if _pc_on else b""
            if not frame:
                self._reject(404)
                return
            self._send(200, frame, "image/jpeg")
            return
        if route == "pc.mjpg":
            if not _pc_on:
                self._reject(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            try:
                while _pc_on and not _pc_stop.is_set():
                    frame = _pc_jpeg
                    if frame:
                        self.wfile.write(
                            b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
                        )
                        self.wfile.flush()
                    if _pc_stop.wait(0.2):
                        break
            except Exception:
                return
            return
        self._reject(404)

    def do_POST(self) -> None:
        route = self._route()
        if route != "phone/frame" or not _phone_on:
            length = self.headers.get("Content-Length", "0")
            if length.isdigit() and int(length) <= MAX_FRAME_BYTES:
                self.rfile.read(int(length))
            self._reject(404)
            return
        length_text = self.headers.get("Content-Length", "")
        if not length_text.isdigit():
            self._reject(411)
            return
        length = int(length_text)
        if length < 16 or length > MAX_FRAME_BYTES:
            self._reject(413)
            return
        data = self.rfile.read(length)
        if not _jpeg_ok(data):
            self._reject(400)
            return
        global _phone_jpeg
        with _state_lock:
            _phone_jpeg = bytes(data)
        self._send(200, b"ok", "text/plain")


def _wait_until_listening(host: str, port: int) -> None:
    target = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((target, port), timeout=0.2):
                return
        except OSError:
            time.sleep(0.02)
    raise RuntimeError("The live video page did not start.")


def _ensure_server() -> None:
    global _server, _server_thread, _token, _bound_port, _base_url, _mini_app
    with _state_lock:
        if _server is not None:
            return
        host, port = _listen_address()
        server = None
        try:
            server = _LiveServer((host, port), _Handler)
            bound_host, bound_port = server.server_address[:2]
            base, mini = _public_base(int(bound_port), str(bound_host))
        except OSError as exc:
            if server is not None:
                server.server_close()
            raise RuntimeError(f"The live video port is not available. {exc}") from exc
        except Exception:
            if server is not None:
                server.server_close()
            raise
        token = secrets.token_urlsafe(18)
        thread = threading.Thread(target=server.serve_forever, name="live-video", daemon=True)
        _server = server
        _server_thread = thread
        _token = token
        _bound_port = int(bound_port)
        _base_url = base
        _mini_app = mini
        thread.start()
    _wait_until_listening(str(bound_host), int(bound_port))


def _close_server_if_idle() -> None:
    global _server, _server_thread, _token, _bound_port, _base_url, _mini_app
    with _state_lock:
        if _pc_on or _phone_on:
            return
        server = _server
        thread = _server_thread
        _server = None
        _server_thread = None
        _token = ""
        _bound_port = 0
        _base_url = ""
        _mini_app = False
    if server is not None:
        try:
            server.shutdown()
        except Exception:
            pass
        try:
            server.server_close()
        except Exception:
            pass
    if thread is not None and thread is not threading.current_thread():
        thread.join(timeout=2)


def _close_proc(proc: Any) -> None:
    if proc is None:
        return
    stdin = getattr(proc, "stdin", None)
    if stdin is not None:
        try:
            stdin.close()
        except Exception:
            pass
    try:
        if proc.poll() is None:
            proc.terminate()
    except Exception:
        pass
    try:
        proc.wait(timeout=1)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def _write_raw(proc: Any, raw: bytes) -> None:
    stdin = getattr(proc, "stdin", None)
    if stdin is None:
        return
    stdin.write(raw)
    flush = getattr(stdin, "flush", None)
    if flush is not None:
        flush()


def _spawn_ffmpeg(command: list[str]) -> Any:
    agent = _agent()
    if agent.stream_process_override is not None:
        return agent.stream_process_override(command)
    flags: dict[str, Any] = {}
    if os.name == "nt":
        flags["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        shell=False,
        **flags,
    )


def _ffmpeg_command(width: int, height: int, publish: str) -> list[str]:
    import media_ffmpeg

    executable = media_ffmpeg.find_ffmpeg()
    if executable is None:
        raise RuntimeError(
            "ffmpeg is not installed. Install ffmpeg or set FFMPEG_EXECUTABLE. "
            "The webcam was not published."
        )
    return [
        str(executable),
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "bgr24",
        "-s",
        f"{width}x{height}",
        "-r",
        "8",
        "-i",
        "pipe:0",
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-tune",
        "zerolatency",
        "-pix_fmt",
        "yuv420p",
        "-f",
        "flv",
        publish,
    ]


def _store_pc(frame: bytes) -> None:
    global _pc_jpeg
    with _state_lock:
        _pc_jpeg = bytes(frame)


def _next_override_frame() -> bytes | None:
    agent = _agent()
    override = agent.live_frame_override
    if override is None:
        raise RuntimeError("The webcam frame source is not set.")
    frame = override()
    if frame is None:
        return None
    if not _jpeg_ok(frame):
        raise RuntimeError("The webcam frame was empty or not a JPEG.")
    return bytes(frame)


def _viewer_url(kind: str) -> str:
    if not _base_url or not _token:
        return ""
    leaf = "pc" if kind == "pc" else "phone"
    return f"{_base_url}/live/{_token}/{leaf}"


def _deliver(text: str, button: str, page_url: str, use_mini_app: bool) -> bool:
    import remote_bridge

    agent = _agent()
    chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not chat:
        return False
    if not remote_bridge.paired() and agent.remote_transport_override is None:
        return False
    body: dict[str, Any] = {"chat_id": chat, "text": _safe(text)[:1800]}
    if use_mini_app and page_url.startswith("https://"):
        body["reply_markup"] = {
            "inline_keyboard": [[{"text": button, "web_app": {"url": page_url}}]]
        }
    remote_bridge._http("telegram_send", {"body": body})
    return True


def _link_sentence(kind: str, seconds: int, publishing: bool) -> str:
    page = _viewer_url(kind)
    if kind == "phone":
        lead = (
            f"Started the phone camera page for {seconds} seconds. "
            "Open it on your phone and allow the camera. Frames come back to this PC."
        )
    elif publishing:
        lead = (
            f"Started the PC webcam on your Telegram live stream for {seconds} seconds. "
            "The stream key stays in the environment."
        )
    else:
        lead = f"Started the PC webcam viewer for {seconds} seconds."
    if _mini_app:
        return lead + " The Telegram button opens it."
    if page:
        return (
            lead
            + " Telegram Mini Apps need an https LIVE_PUBLIC_URL. Open this link: "
            + page
        )
    return lead


def _announce(kind: str, seconds: int, publishing: bool) -> bool:
    button = _PC_BUTTON if kind == "pc" else _PHONE_BUTTON
    text = _link_sentence(kind, seconds, publishing)
    page = _viewer_url(kind)
    try:
        return _deliver(text, button, page, _mini_app)
    except AssertionError:
        raise
    except Exception:
        return False


def _result(kind: str, seconds: int, publishing: bool, sent: bool) -> dict[str, Any]:
    message = _link_sentence(kind, seconds, publishing)
    if not sent:
        message += " The phone button was not sent because the phone bridge is not set up."
    return _ok(
        message,
        status="started",
        source=kind,
        seconds=seconds,
        viewer_url=_viewer_url(kind),
        mini_app=bool(_mini_app),
        rtmp=bool(publishing),
        telegram_sent=bool(sent),
    )


def _mark_pc_off() -> None:
    global _pc_on, _pc_proc, _pc_jpeg, _pc_seconds
    with _state_lock:
        _pc_on = False
        proc = _pc_proc
        _pc_proc = None
        _pc_jpeg = b""
        _pc_seconds = 0
    _close_proc(proc)
    _close_server_if_idle()


def _pc_override_loop(deadline: float, proc: Any) -> None:
    try:
        while not _pc_stop.is_set() and time.monotonic() < deadline:
            if proc is not None:
                try:
                    if proc.poll() is not None:
                        break
                except Exception:
                    break
            frame = _next_override_frame()
            if frame:
                _store_pc(frame)
                if proc is not None:
                    raw, _width, _height = _jpeg_to_bgr(frame)
                    try:
                        _write_raw(proc, raw)
                    except Exception:
                        break
            if _pc_stop.wait(_FRAME_GAP_SECONDS):
                break
    finally:
        _mark_pc_off()


def _read_camera_jpeg(cv2: Any, camera: Any) -> bytes:
    ok, frame = camera.read()
    if not ok or frame is None:
        raise RuntimeError("Failed to grab a frame from the webcam.")
    shape = getattr(frame, "shape", None)
    if not shape or len(shape) < 2:
        raise RuntimeError("Failed to grab a frame from the webcam.")
    height, width = int(shape[0]), int(shape[1])
    agent = _agent()
    limit = int(getattr(agent, "SCREENSHOT_MAX_WIDTH", 1280))
    if width > limit and hasattr(cv2, "resize"):
        new_width = limit - (limit % 2)
        new_height = max(2, round(height * (new_width / width)))
        new_height -= new_height % 2
        frame = cv2.resize(frame, (new_width, new_height))
    elif width % 2 or height % 2:
        even_w = max(2, width - (width % 2))
        even_h = max(2, height - (height % 2))
        frame = frame[0:even_h, 0:even_w]
    encoded_ok, encoded = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
    if not encoded_ok:
        raise RuntimeError("Failed to save the webcam frame.")
    data = bytes(encoded)
    if not _jpeg_ok(data):
        raise RuntimeError("Failed to save the webcam frame.")
    return data


def _pc_camera_loop(seconds: int, publish: str | None, ready: threading.Event, box: dict[str, Any]) -> None:
    global _pc_proc
    camera = None
    proc = None
    try:
        import cv2
    except ImportError as exc:
        box["error"] = RuntimeError(
            "opencv-python is not installed. From the project folder run: "
            ".\\.venv\\Scripts\\python.exe -m pip install opencv-python"
        )
        ready.set()
        return
    agent = _agent()
    try:
        camera = cv2.VideoCapture()
        timeout_ms = int(float(getattr(agent, "WEBCAM_TIMEOUT_SECONDS", 4.0)) * 1000)
        agent._set_camera_prop(camera, getattr(cv2, "CAP_PROP_OPEN_TIMEOUT_MSEC", None), timeout_ms)
        agent._set_camera_prop(camera, getattr(cv2, "CAP_PROP_READ_TIMEOUT_MSEC", None), timeout_ms)
        opened = camera.open(0, agent._webcam_backend(cv2))
        if not opened or not camera.isOpened():
            raise RuntimeError(
                "Could not access the webcam. It may be in use by another app "
                "or blocked by Windows privacy settings."
            )
        agent._set_camera_prop(camera, getattr(cv2, "CAP_PROP_BUFFERSIZE", None), 1)
        frame = _read_camera_jpeg(cv2, camera)
        raw, width, height = _jpeg_to_bgr(frame)
        if publish:
            command = _ffmpeg_command(width, height, publish)
            proc = _spawn_ffmpeg(command)
            _write_raw(proc, raw)
            with _state_lock:
                _pc_proc = proc
        _store_pc(frame)
        ready.set()
        deadline = time.monotonic() + seconds
        while not _pc_stop.is_set() and time.monotonic() < deadline:
            if proc is not None and proc.poll() is not None:
                break
            frame = _read_camera_jpeg(cv2, camera)
            _store_pc(frame)
            if proc is not None:
                raw, _width, _height = _jpeg_to_bgr(frame)
                try:
                    _write_raw(proc, raw)
                except Exception:
                    break
            if _pc_stop.wait(_FRAME_GAP_SECONDS):
                break
    except Exception as exc:
        box["error"] = exc
        ready.set()
    finally:
        if camera is not None:
            try:
                camera.release()
            except Exception:
                pass
        _mark_pc_off()


def _start_pc(seconds: int) -> dict[str, Any]:
    global _pc_on, _pc_thread, _pc_proc, _pc_seconds
    target = _rtmp_target()
    publish = target[1] if target else None
    agent = _agent()
    with _state_lock:
        if _pc_on:
            running_seconds = _pc_seconds or seconds
            already = True
        else:
            already = False
            running_seconds = seconds
            _pc_stop.clear()
            _pc_on = True
            _pc_seconds = seconds
    if already:
        return _ok(
            "The PC webcam is already on.",
            status="started",
            source="pc",
            seconds=running_seconds,
            viewer_url=_viewer_url("pc"),
            mini_app=bool(_mini_app),
            rtmp=bool(publish),
        )
    try:
        _ensure_server()
        if agent.live_frame_override is not None:
            frame = _next_override_frame()
            if not frame:
                raise RuntimeError("The webcam did not return a frame.")
            raw, width, height = _jpeg_to_bgr(frame)
            proc = None
            if publish:
                proc = _spawn_ffmpeg(_ffmpeg_command(width, height, publish))
                _write_raw(proc, raw)
            _store_pc(frame)
            with _state_lock:
                _pc_proc = proc
            worker = threading.Thread(
                target=_pc_override_loop,
                args=(time.monotonic() + seconds, proc),
                name="pc-camera",
                daemon=True,
            )
            with _state_lock:
                _pc_thread = worker
            worker.start()
        else:
            ready = threading.Event()
            box: dict[str, Any] = {}
            worker = threading.Thread(
                target=_pc_camera_loop,
                args=(seconds, publish, ready, box),
                name="pc-camera",
                daemon=True,
            )
            with _state_lock:
                _pc_thread = worker
            worker.start()
            timeout = float(getattr(agent, "WEBCAM_TIMEOUT_SECONDS", 4.0))
            if not ready.wait(timeout):
                _pc_stop.set()
                raise RuntimeError(
                    "The webcam did not respond in time. It may be in use by another "
                    "app or blocked by Windows privacy settings."
                )
            if box.get("error") is not None:
                raise box["error"]
        sent = _announce("pc", seconds, bool(publish))
        return _result("pc", seconds, bool(publish), sent)
    except AssertionError:
        _stop_pc()
        raise
    except Exception as exc:
        _stop_pc()
        return _err(f"stream_pc_camera failed: {exc}")


def _stop_pc() -> dict[str, Any]:
    global _pc_thread
    _pc_stop.set()
    with _state_lock:
        thread = _pc_thread
        _pc_thread = None
    if thread is not None and thread is not threading.current_thread() and thread.is_alive():
        thread.join(timeout=2)
    _mark_pc_off()
    return _ok("Stopped the PC webcam.", status="stopped", source="pc")


def _look(kind: str) -> dict[str, Any]:
    if kind == "pc":
        frame = _pc_jpeg if _pc_on else b""
        missing = "The PC webcam is not on. Start it with stream_pc_camera first."
        label = "PC webcam"
    else:
        frame = _phone_jpeg if _phone_on else b""
        missing = "No phone frame has arrived. Open the phone camera page and allow the camera."
        if not _phone_on:
            missing = "The phone camera page is not on. Start it with stream_phone_camera first."
        label = "phone camera"
    if not frame:
        return _err(missing)
    return _ok(
        f"Here is the latest {label} frame. Describe what is visible. Do not ask for another frame unless the user does.",
        status="ready",
        source=kind,
        _screenshot_bytes=bytes(frame),
        _screenshot_mime="image/jpeg",
    )


def _status(kind: str) -> dict[str, Any]:
    running = _pc_on if kind == "pc" else _phone_on
    seconds = _pc_seconds if kind == "pc" else _phone_seconds
    return _ok(
        f"The {kind} camera is {'on' if running else 'off'}.",
        status="started" if running else "stopped",
        source=kind,
        seconds=seconds,
        viewer_url=_viewer_url(kind) if running else "",
        mini_app=bool(_mini_app) if running else False,
    )


def stream_pc_camera(action: str = "start", seconds: Any = None) -> dict[str, Any]:
    """Start, stop, or look at the host PC webcam. RTMP settings come from the environment."""
    try:
        act = _action(action)
        if act == "stop":
            return _stop_pc()
        if act == "status":
            return _status("pc")
        if act == "look":
            return _look("pc")
        if act != "start":
            return _err("action must be start, stop, status, or look.")
        return _start_pc(_duration(seconds))
    except AssertionError:
        raise
    except Exception as exc:
        return _err(f"stream_pc_camera failed: {exc}")


def _cancel_phone_timer() -> None:
    global _phone_timer
    with _state_lock:
        timer = _phone_timer
        _phone_timer = None
    if timer is not None:
        timer.cancel()


def _mark_phone_off() -> None:
    global _phone_on, _phone_jpeg, _phone_seconds
    _cancel_phone_timer()
    with _state_lock:
        _phone_on = False
        _phone_jpeg = b""
        _phone_seconds = 0
    _close_server_if_idle()


def _stop_phone() -> dict[str, Any]:
    _phone_stop.set()
    _mark_phone_off()
    return _ok("Stopped the phone camera page.", status="stopped", source="phone")


def _start_phone(seconds: int) -> dict[str, Any]:
    global _phone_on, _phone_timer, _phone_seconds, _phone_jpeg
    with _state_lock:
        if _phone_on:
            running_seconds = _phone_seconds or seconds
            already = True
        else:
            already = False
            running_seconds = seconds
            _phone_stop.clear()
            _phone_on = True
            _phone_seconds = seconds
            _phone_jpeg = b""
    if already:
        return _ok(
            "The phone camera page is already on.",
            status="started",
            source="phone",
            seconds=running_seconds,
            viewer_url=_viewer_url("phone"),
            mini_app=bool(_mini_app),
            rtmp=False,
        )
    try:
        _ensure_server()

        def _expire() -> None:
            if _phone_on:
                _mark_phone_off()

        timer = threading.Timer(seconds, _expire)
        timer.daemon = True
        with _state_lock:
            _phone_timer = timer
        timer.start()
        sent = _announce("phone", seconds, False)
        return _result("phone", seconds, False, sent)
    except AssertionError:
        _stop_phone()
        raise
    except Exception as exc:
        _stop_phone()
        return _err(f"stream_phone_camera failed: {exc}")


def stream_phone_camera(action: str = "start", seconds: Any = None) -> dict[str, Any]:
    """Open a phone camera page, or return the latest frame that page posted."""
    try:
        act = _action(action)
        if act == "stop":
            return _stop_phone()
        if act == "status":
            return _status("phone")
        if act == "look":
            return _look("phone")
        if act != "start":
            return _err("action must be start, stop, status, or look.")
        return _start_phone(_duration(seconds))
    except AssertionError:
        raise
    except Exception as exc:
        return _err(f"stream_phone_camera failed: {exc}")


def stop_live_feeds() -> dict[str, Any]:
    """Stop both feeds and close the local page. Safe to call when nothing is running."""
    pc_was = _pc_on
    phone_was = _phone_on
    _stop_pc()
    _stop_phone()
    if not pc_was and not phone_was:
        return _ok("No live video is running.", status="stopped")
    try:
        _deliver("Stopped the live camera.", "", "", False)
    except AssertionError:
        raise
    except Exception:
        pass
    return _ok("Stopped the live camera.", status="stopped")
