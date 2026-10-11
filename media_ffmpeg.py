"""Background ffmpeg jobs. No media GUI is opened.

Tests set media_runner_override and never start ffmpeg. Paths stay in the
user profile, the workspace, or the external drive. Filter graphs are not
accepted from the model.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Any

ACTIONS = {
    "convert": "convert",
    "transcode": "convert",
    "compress_audio": "compress_audio",
    "compress": "compress_audio",
    "extract_frames": "extract_frames",
    "frames": "extract_frames",
}
VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}
AUDIO_EXTS = {".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg"}
TIMEOUT_SECONDS = 600
MAX_BATCH = 8
MIN_BYTES = 16
_LAUNCH_JOIN_SECONDS = 0.5

_lock = threading.Lock()
_active = 0


def _agent() -> Any:
    return __import__("gta5_agent")


def reset_jobs() -> None:
    """Forget the running-job count. Used by tests."""
    global _active
    with _lock:
        _active = 0


def find_ffmpeg() -> Path | None:
    agent = _agent()
    override = agent.ffmpeg_executable_override
    if override is False:
        return None
    if override:
        return Path(override)
    configured = os.environ.get("FFMPEG_EXECUTABLE", "").strip().strip('"')
    if configured and Path(configured).is_file():
        return Path(configured)
    found = shutil.which("ffmpeg")
    return Path(found) if found else None


def _resolve_loose(agent: Any, text: str) -> Path:
    raw = (text or "").strip().strip('"')
    if not raw:
        raise ValueError("A source file or folder is required.")
    drive = agent._resolve_drive_text(raw)
    if drive is not None:
        target = drive
    else:
        target = Path(raw).expanduser()
        if ".." in target.parts:
            raise ValueError("The path cannot contain '..'.")
    resolved = target.resolve()
    if not agent._path_is_allowed(resolved):
        raise ValueError(agent._drive_path_message())
    return resolved


def _media_file(path: Path) -> bool:
    return path.suffix.casefold() in VIDEO_EXTS | AUDIO_EXTS


def _sources(source: Path) -> list[Path]:
    if source.is_file():
        if not _media_file(source):
            raise ValueError("The source must be a video or audio file.")
        return [source]
    if source.is_dir():
        found = [
            path
            for path in source.iterdir()
            if path.is_file() and not path.is_symlink() and _media_file(path)
        ]
        found.sort(key=lambda item: item.name.casefold())
        if not found:
            raise ValueError("That folder has no video or audio files.")
        return found[:MAX_BATCH]
    raise ValueError("The source file or folder was not found.")


def _output_for(action: str, source: Path, output: Path, many: bool) -> Path:
    if action == "extract_frames":
        folder = output if output.suffix == "" else output.parent / f"{source.stem}-frames"
        return folder / "frame-%04d.png"
    suffix = output.suffix.casefold()
    if action == "compress_audio":
        if suffix not in {".mp3", ".m4a"}:
            suffix = ".mp3"
        target_dir = output if output.suffix == "" else output.parent
        name = f"{source.stem}{suffix}" if many or output.suffix == "" else output.name
        return target_dir / name
    if suffix not in VIDEO_EXTS | AUDIO_EXTS:
        suffix = ".mp4"
    if output.suffix and not many:
        return output
    folder = output if output.suffix == "" else output.parent
    return folder / f"{source.stem}{suffix}"


def _command(executable: Path, action: str, source: Path, destination: Path) -> list[str]:
    base = [str(executable), "-y", "-hide_banner", "-loglevel", "error", "-i", str(source)]
    if action == "compress_audio":
        return base + ["-vn", "-b:a", "128k", str(destination)]
    if action == "extract_frames":
        return base + ["-vf", "fps=1", str(destination)]
    return base + [str(destination)]


def _run(command: list[str], destination: Path) -> dict[str, Any]:
    agent = _agent()
    if agent.media_runner_override is not None:
        result = agent.media_runner_override(command, destination)
        if not isinstance(result, dict):
            raise RuntimeError("The ffmpeg runner returned nothing.")
        return result
    flags: dict[str, Any] = {}
    if os.name == "nt":
        flags["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    process = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=TIMEOUT_SECONDS,
        shell=False,
        check=False,
        **flags,
    )
    return {
        "returncode": process.returncode,
        "stdout": process.stdout or "",
        "stderr": process.stderr or "",
    }


def _produced(destination: Path) -> bool:
    if "%" in destination.name:
        frames = list(destination.parent.glob(destination.name.replace("%04d", "*")))
        return any(path.is_file() and path.stat().st_size >= MIN_BYTES for path in frames)
    return destination.is_file() and destination.stat().st_size >= MIN_BYTES


def _alert(text: str) -> None:
    print(f"[media] {text}", flush=True)
    try:
        import remote_bridge

        remote_bridge.notify(text)
    except Exception:
        return


def process_media(
    action: str,
    source: str,
    output_path: str = "",
) -> dict[str, Any]:
    """Convert, compress, or extract frames. A fast failure returns immediately."""
    global _active
    agent = _agent()
    try:
        kind = ACTIONS.get((action or "").strip().casefold().replace("-", "_").replace(" ", "_"))
        if kind is None:
            return agent._err("action must be convert, compress_audio, or extract_frames.")
        raw_source = _resolve_loose(agent, source)
        files = _sources(raw_source)
        if output_path:
            output = _resolve_loose(agent, output_path)
        else:
            output = files[0].parent / "converted"
        if agent.ffmpeg_executable_override is False or (
            agent.media_runner_override is None and find_ffmpeg() is None
        ):
            return agent._err(
                "ffmpeg is not installed. Install ffmpeg, or set FFMPEG_EXECUTABLE."
            )
        executable = Path(agent.ffmpeg_executable_override or find_ffmpeg() or "ffmpeg")
        jobs = [
            (path, _output_for(kind, path, output, len(files) > 1))
            for path in files
        ]
        for _source_path, destination in jobs:
            destination.parent.mkdir(parents=True, exist_ok=True)

        def _work() -> dict[str, Any]:
            saved: list[str] = []
            for source_path, destination in jobs:
                command = _command(executable, kind, source_path, destination)
                completed = _run(command, destination)
                if int(completed.get("returncode", 1)) != 0 or not _produced(destination):
                    detail = agent._scrub(
                        str(completed.get("stderr") or completed.get("stdout") or "ffmpeg failed.")
                    )
                    return agent._err(detail[-500:], path=str(destination))
                saved.append(str(destination if "%" not in destination.name else destination.parent))
            return agent._ok(
                f"Processed {len(saved)} media file(s).",
                status="ready",
                files=saved,
                action=kind,
            )

        if agent.media_runner_override is not None:
            return _work()
        holder: dict[str, Any] = {}

        def _thread() -> None:
            global _active
            try:
                result = _work()
                holder["result"] = result
                text = str(result.get("message") or result.get("error") or "")
                if text:
                    _alert(agent._scrub(text))
            finally:
                with _lock:
                    _active -= 1

        with _lock:
            if _active >= 1:
                return agent._err("A media job is already running. The file is not ready yet.")
            _active += 1
        worker = threading.Thread(target=_thread, name="ffmpeg-job", daemon=True)
        worker.start()
        worker.join(_LAUNCH_JOIN_SECONDS)
        if "result" in holder and not worker.is_alive():
            return holder["result"]
        return agent._ok(
            "ffmpeg is working in the background. The file is not ready yet.",
            status="started",
            action=kind,
            path=str(jobs[0][1]),
        )
    except AssertionError:
        raise
    except Exception as exc:
        return agent._err(f"process_media failed: {exc}")
