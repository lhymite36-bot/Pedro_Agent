"""PC camera stills and timed recordings stay downloadable. Tests never open the camera."""

from __future__ import annotations

import io
import sys
import tempfile
import threading
import types
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

import agent_core
import chat_app


class CameraRecordTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.original_workspace = agent_core.WORKSPACE
        self.original_webcam = agent_core.webcam_override
        self.original_record = agent_core.record_override
        self.original_process = agent_core.record_process_override
        self.original_clock = agent_core.record_clock
        self.original_wait = agent_core.record_wait
        self.original_ffmpeg = agent_core.ffmpeg_executable_override
        agent_core.WORKSPACE = Path(self.temp.name)
        agent_core.webcam_override = None
        agent_core.record_override = None
        agent_core.record_process_override = None
        agent_core.record_clock = None
        agent_core.record_wait = None
        agent_core.ffmpeg_executable_override = None
        self.addCleanup(self.restore)

    def restore(self) -> None:
        agent_core.WORKSPACE = self.original_workspace
        agent_core.webcam_override = self.original_webcam
        agent_core.record_override = self.original_record
        agent_core.record_process_override = self.original_process
        agent_core.record_clock = self.original_clock
        agent_core.record_wait = self.original_wait
        agent_core.ffmpeg_executable_override = self.original_ffmpeg

    def test_still_keeps_a_downloadable_copy(self) -> None:
        buffer = io.BytesIO()
        from PIL import Image

        Image.new("RGB", (8, 4), (1, 2, 3)).save(buffer, format="PNG")
        calls = {"n": 0}

        def injected() -> dict[str, object]:
            calls["n"] += 1
            return {"png": buffer.getvalue()}

        agent_core.webcam_override = injected
        shot = agent_core.capture_webcam_image()
        self.assertTrue(shot["ok"], shot)
        self.assertEqual(calls["n"], 1)
        saved = Path(shot["path"])
        self.assertEqual(saved.name, "vision_capture.jpg")
        download = Path(shot["download_path"])
        self.assertEqual(download.parent.name, "camera")
        self.assertTrue(download.name.startswith("camera-"))
        self.assertEqual(download.suffix, ".jpg")
        self.assertEqual(download.read_bytes(), shot["_screenshot_bytes"])
        self.assertEqual(agent_core._result_image(shot), str(download))
        self.assertIsNone(agent_core._result_video(shot))
        self.assertEqual(agent_core._undo_path(shot), str(download))
        self.assertIn("downloaded", shot["message"].casefold())

    def test_missing_length_records_nothing(self) -> None:
        def refuse(seconds: int) -> dict[str, object]:
            raise AssertionError(f"recorded {seconds}")

        agent_core.record_override = refuse
        for value in (None, "", "   ", 0, -3, 601, True, "nope", float("nan")):
            result = agent_core.record_pc_camera(value)
            self.assertFalse(result["ok"], value)
            self.assertIn("nothing was recorded", result["error"].casefold())
        asked = agent_core.invoke_tool("record_pc_camera", {})
        self.assertFalse(asked["ok"])
        self.assertIn("nothing was recorded", asked["error"].casefold())
        refused = agent_core.invoke_tool(
            "record_pc_camera", {"seconds": 5, "rtmp_url": "rtmp://evil.example/live"}
        )
        self.assertFalse(refused["ok"])
        self.assertIn("Bad arguments", refused["error"])
        self.assertNotIn("evil.example", refused["error"])

    def test_override_saves_the_given_length_without_the_camera(self) -> None:
        seen: list[int] = []

        def fake(seconds: int) -> dict[str, object]:
            seen.append(seconds)
            return {
                "mp4": b"\x00\x00\x00\x18ftypmp42" + b"x" * 16,
                "jpeg": b"\xff\xd8\xff\xd9",
                "width": 6,
                "height": 4,
            }

        agent_core.record_override = fake
        agent_core.record_process_override = lambda command: (_ for _ in ()).throw(
            AssertionError("real ffmpeg")
        )
        real_import = __import__("builtins").__import__

        def block_cv2(name: str, *args: object, **kwargs: object) -> object:
            if str(name).split(".", 1)[0] == "cv2":
                raise AssertionError("real webcam")
            return real_import(name, *args, **kwargs)

        with mock.patch("builtins.__import__", block_cv2):
            clip = agent_core.record_pc_camera("10")
            longer = agent_core.record_pc_camera(10.6)
        self.assertEqual(seen, [10, 11])
        self.assertTrue(clip["ok"], clip)
        self.assertEqual(clip["seconds"], 10)
        video = Path(clip["video"])
        self.assertEqual(video.suffix, ".mp4")
        self.assertEqual(video.parent.name, "camera")
        self.assertGreaterEqual(video.stat().st_size, 16)
        self.assertEqual(agent_core._result_video(clip), str(video))
        self.assertIsNone(agent_core._result_image(clip))
        self.assertNotIn("viewer_url", clip)
        part = agent_core._function_response("record_pc_camera", clip, "rec-1")
        response = part.function_response
        self.assertNotIn("_screenshot_bytes", response.response)
        self.assertEqual(response.parts[0].inline_data.mime_type, "image/jpeg")
        self.assertIn("record_pc_camera", agent_core.TOOLS)
        self.assertIn("record_pc_camera", agent_core._NO_TIMEOUT_TOOLS)
        self.assertIn("record_pc_camera", agent_core.SYSTEM_PROMPT)
        self.assertIn("Do not guess", agent_core.SYSTEM_PROMPT)
        names = [item["name"] for item in agent_core.TOOL_DECLARATIONS]
        self.assertEqual(names.count("record_pc_camera"), 1)
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(names[49], "desktop_ui_automation")
        self.assertEqual(names[54], "routine_macro_engine")
        self.assertLess(names.index("stream_pc_camera"), names.index("record_pc_camera"))
        self.assertTrue(longer["ok"], longer)
        self.assertEqual(longer["seconds"], 11)

    def test_directshow_records_the_asked_seconds_and_releases_the_camera(self) -> None:
        opened: list[object] = []
        clock = {"t": 0.0}
        seen: dict[str, object] = {}

        class FakeCapture:
            def __init__(self) -> None:
                self.reads = 0
                self.released = False
                self.was_opened = False
                self.opened_with: tuple[object, ...] | None = None

            def set(self, prop: object, value: object) -> bool:
                return True

            def open(self, index: int, backend: int = 0) -> bool:
                self.opened_with = (index, backend)
                self.was_opened = True
                return True

            def isOpened(self) -> bool:
                return self.was_opened

            def read(self) -> tuple[bool, object]:
                self.reads += 1
                frame = np.zeros((4, 6, 3), dtype=np.uint8)
                return True, frame

            def release(self) -> None:
                self.released = True

        class Encoded:
            def tobytes(self) -> bytes:
                return b"\xff\xd8\xff\xd9"

        class FakeStdin(io.BytesIO):
            def close(self) -> None:
                self.kept = self.getvalue()
                super().close()

        class FakeProc:
            def __init__(self) -> None:
                self.stdin = FakeStdin()
                self.returncode = 0
                self.killed = False

            def wait(self, timeout: float | None = None) -> int:
                return 0

            def poll(self) -> int:
                return 0

            def kill(self) -> None:
                self.killed = True

        fake = types.ModuleType("cv2")
        fake.CAP_DSHOW = 700
        fake.CAP_ANY = 0
        fake.CAP_PROP_BUFFERSIZE = 38
        fake.CAP_PROP_OPEN_TIMEOUT_MSEC = 53
        fake.CAP_PROP_READ_TIMEOUT_MSEC = 54

        def video_capture(*args: object) -> FakeCapture:
            camera = FakeCapture()
            opened.append(camera)
            return camera

        def imencode(ext: str, frame: object, params: object = None) -> tuple[bool, Encoded]:
            return True, Encoded()

        fake.VideoCapture = video_capture
        fake.imencode = imencode

        def now() -> float:
            return clock["t"]

        def wait(delay: float) -> None:
            clock["t"] += delay

        def spawn(command: list[str]) -> FakeProc:
            self.assertNotIn("flv", command)
            self.assertNotIn("rtmp", " ".join(command).casefold())
            self.assertIn("libx264", command)
            self.assertIn("-an", command)
            self.assertTrue(str(command[-1]).endswith(".mp4"))
            Path(command[-1]).write_bytes(b"\x00\x00\x00\x18ftyp" + b"x" * 16)
            proc = FakeProc()
            seen["proc"] = proc
            seen["command"] = command
            return proc

        agent_core.record_clock = now
        agent_core.record_wait = wait
        agent_core.record_process_override = spawn
        agent_core.ffmpeg_executable_override = Path("ffmpeg-test")
        started = agent_core.time.perf_counter()
        with mock.patch.dict(sys.modules, {"cv2": fake}):
            clip = agent_core.record_pc_camera(2)
        elapsed = agent_core.time.perf_counter() - started
        self.assertLess(elapsed, 2.0)
        self.assertTrue(clip["ok"], clip)
        self.assertEqual(clip["seconds"], 2)
        self.assertEqual(len(opened), 1)
        camera = opened[0]
        self.assertTrue(camera.released)
        self.assertEqual(camera.reads, 16)
        self.assertEqual(camera.opened_with, (0, fake.CAP_DSHOW if sys.platform == "win32" else fake.CAP_ANY))
        proc = seen["proc"]
        self.assertEqual(len(proc.stdin.kept), 16 * 4 * 6 * 3)
        self.assertFalse(proc.killed)
        self.assertTrue(Path(clip["video"]).is_file())

    def test_a_closed_camera_or_missing_ffmpeg_records_nothing(self) -> None:
        opened: list[object] = []

        class FakeCapture:
            def __init__(self, opened_ok: bool = True) -> None:
                self.opened_ok = opened_ok
                self.released = False
                self.reads = 0
                self.was_opened = False

            def set(self, prop: object, value: object) -> bool:
                return True

            def open(self, index: int, backend: int = 0) -> bool:
                self.was_opened = True
                return self.opened_ok

            def isOpened(self) -> bool:
                return self.opened_ok and self.was_opened

            def read(self) -> tuple[bool, object]:
                self.reads += 1
                raise AssertionError("read")

            def release(self) -> None:
                self.released = True

        fake = types.ModuleType("cv2")
        fake.CAP_DSHOW = 700
        fake.CAP_ANY = 0
        fake.CAP_PROP_BUFFERSIZE = 38
        fake.CAP_PROP_OPEN_TIMEOUT_MSEC = 53
        fake.CAP_PROP_READ_TIMEOUT_MSEC = 54

        def closed(*args: object) -> FakeCapture:
            camera = FakeCapture(opened_ok=False)
            opened.append(camera)
            return camera

        fake.VideoCapture = closed
        agent_core.record_process_override = lambda command: (_ for _ in ()).throw(
            AssertionError("ffmpeg")
        )
        with mock.patch.dict(sys.modules, {"cv2": fake}):
            unavailable = agent_core.record_pc_camera(3)
        self.assertFalse(unavailable["ok"])
        self.assertIn("privacy", unavailable["error"].casefold())
        self.assertTrue(opened[0].released)
        self.assertEqual(opened[0].reads, 0)
        self.assertEqual(list(Path(self.temp.name).rglob("*.mp4")), [])

        class OpenCapture(FakeCapture):
            def read(self) -> tuple[bool, object]:
                self.reads += 1
                return True, np.zeros((4, 6, 3), dtype=np.uint8)

        def opened_camera(*args: object) -> OpenCapture:
            camera = OpenCapture()
            opened.append(camera)
            return camera

        fake.VideoCapture = opened_camera
        agent_core.ffmpeg_executable_override = False
        with mock.patch.dict(sys.modules, {"cv2": fake}):
            missing = agent_core.record_pc_camera(3)
        self.assertFalse(missing["ok"])
        self.assertIn("ffmpeg", missing["error"].casefold())
        self.assertIn("nothing was recorded", missing["error"].casefold())
        self.assertTrue(opened[1].released)
        self.assertEqual(opened[1].reads, 1)
        self.assertEqual(list(Path(self.temp.name).rglob("*.mp4")), [])

    def test_media_route_stays_inside_the_workspace(self) -> None:
        root = Path(chat_app.__file__).resolve().parent / "workspace" / "camera"
        root.mkdir(parents=True, exist_ok=True)
        video = root / "camera-test-route.mp4"
        picture = root / "camera-test-route.jpg"
        video.write_bytes(b"\x00" * 32)
        picture.write_bytes(b"\xff\xd8\xff\xd9")
        self.addCleanup(video.unlink, missing_ok=True)
        self.addCleanup(picture.unlink, missing_ok=True)
        self.assertEqual(chat_app.safe_media_path(str(video)), video.resolve())
        self.assertEqual(chat_app.safe_image_path(str(picture)), picture.resolve())
        self.assertIsNone(chat_app.safe_image_path(str(video)))
        self.assertIsNone(chat_app.safe_media_path(r"C:\Windows\notepad.exe"))
        outside = Path(self.temp.name) / "camera-test-route.mp4"
        outside.write_bytes(b"\x00" * 32)
        self.assertIsNone(chat_app.safe_media_path(str(outside)))
        script = (Path(agent_core.__file__).resolve().parent / "app_static" / "app.js").read_text(encoding="utf-8")
        self.assertIn("Download video", script)
        self.assertIn("Download image", script)
        self.assertIn("function addVideo", script)
        self.assertIn("addSavedMedia", script)


if __name__ == "__main__":
    unittest.main()
