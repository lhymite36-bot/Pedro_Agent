"""Record a short voice note on this PC and save bullet notes.

The microphone and the speaker loop open only when this tool runs and no
recorder override is set. Tests set recorder_override, transcriber_override,
and documents_override. Transcription stays local. Whisper is optional.
"""

from __future__ import annotations

import re
import threading
import uuid
import wave
from pathlib import Path
from typing import Any

DEFAULT_SECONDS = 30
MIN_SECONDS = 1
MAX_SECONDS = 600
_JOIN_SECONDS = 0.5
_AUDIO_SUFFIXES = (".wav", ".mp3", ".m4a", ".flac", ".ogg")

_lock = threading.Lock()
_threads: list[threading.Thread] = []


def _agent() -> Any:
    import gta5_agent

    return gta5_agent


def _seconds(value: Any) -> int:
    if value is None or isinstance(value, bool):
        raise ValueError("seconds must be between 1 and 600.")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("seconds must be between 1 and 600.") from exc
    if number < MIN_SECONDS or number > MAX_SECONDS:
        raise ValueError("seconds must be between 1 and 600.")
    return int(number)


def _source_name(source: str) -> str:
    key = (source or "mic").strip().casefold().replace("-", "_").replace(" ", "_")
    if key in {"mic", "microphone", "voice"}:
        return "mic"
    if key in {"system", "loopback", "speaker", "desktop"}:
        return "system"
    if key == "file":
        return "file"
    raise ValueError("source must be mic, system, or file.")


def notes_from_transcript(text: str) -> str:
    """Turn transcript sentences into a stable markdown list."""
    cleaned = " ".join((text or "").split())
    parts = re.split(r"(?<=[.!?])\s+", cleaned)
    lines = [f"- {part.strip()}" for part in parts if part.strip()]
    if not lines:
        return ""
    return "# Voice note\n\n" + "\n".join(lines) + "\n"


def _note_path(output_path: str) -> Path:
    agent = _agent()
    text = (output_path or "").strip()
    if text:
        return agent._resolve_user_path(text, ".md")
    folder = agent.documents_override
    if folder is None:
        folder = Path.home() / "Documents"
    destination = Path(folder)
    if agent._is_blocked_system_path(destination):
        raise ValueError("Save the note in your documents, the workspace, or the external drive.")
    destination.mkdir(parents=True, exist_ok=True)
    return destination / f"voice-note-{uuid.uuid4().hex[:8]}.md"


def _record_mic(seconds: int, dest: Path) -> None:
    import speech_recognition as sr

    recognizer = sr.Recognizer()
    with sr.Microphone() as source:
        audio = recognizer.record(source, duration=seconds)
    dest.write_bytes(audio.get_wav_data())


def _record_system(seconds: int, dest: Path) -> None:
    import pyaudiowpatch as pyaudio

    audio = pyaudio.PyAudio()
    stream = None
    try:
        wasapi = audio.get_host_api_info_by_type(pyaudio.paWASAPI)
        default = audio.get_device_info_by_index(wasapi["defaultOutputDevice"])
        if not default.get("isLoopbackDevice"):
            for loop in audio.get_loopback_device_info_generator():
                if default["name"] in loop["name"]:
                    default = loop
                    break
        rate = int(default["defaultSampleRate"])
        channels = max(1, int(default["maxInputChannels"]))
        chunk = 1024
        stream = audio.open(
            format=pyaudio.paInt16,
            channels=channels,
            rate=rate,
            input=True,
            frames_per_buffer=chunk,
            input_device_index=int(default["index"]),
        )
        frames: list[bytes] = []
        count = max(1, int(rate / chunk * seconds))
        for _ in range(count):
            frames.append(stream.read(chunk))
        with wave.open(str(dest), "wb") as handle:
            handle.setnchannels(channels)
            handle.setsampwidth(2)
            handle.setframerate(rate)
            handle.writeframes(b"".join(frames))
    finally:
        if stream is not None:
            stream.stop_stream()
            stream.close()
        audio.terminate()


def _record(source: str, seconds: int, dest: Path) -> None:
    agent = _agent()
    if agent.recorder_override is not None:
        agent.recorder_override(source, seconds, dest)
        return
    if source == "system":
        _record_system(seconds, dest)
        return
    _record_mic(seconds, dest)


def _transcribe(path: Path) -> str:
    agent = _agent()
    if agent.transcriber_override is not None:
        text = agent.transcriber_override(path)
        return "" if text is None else str(text)
    try:
        import whisper
    except ImportError:
        whisper = None
    if whisper is not None:
        model = whisper.load_model("base")
        result = model.transcribe(str(path))
        return str(result.get("text") or "").strip()
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError(
            "A local transcription model is not installed. From the project folder run: "
            ".\\.venv\\Scripts\\python.exe -m pip install openai-whisper"
        ) from exc
    model = WhisperModel("base", device="cpu", compute_type="int8")
    segments, _info = model.transcribe(str(path))
    return " ".join(segment.text.strip() for segment in segments).strip()


def _work(
    source: str,
    seconds: int,
    output_path: str,
    audio_path: str,
) -> dict[str, Any]:
    agent = _agent()
    note = _note_path(output_path)
    note.parent.mkdir(parents=True, exist_ok=True)
    wav: Path | None = None
    owned = False
    if source == "file":
        wav = agent._resolve_user_path(audio_path, _AUDIO_SUFFIXES)
        if not wav.is_file():
            return agent._err("That audio file does not exist.", path=str(wav))
    else:
        folder = agent.WORKSPACE / "scribe"
        folder.mkdir(parents=True, exist_ok=True)
        wav = folder / f"{uuid.uuid4().hex[:8]}.wav"
        owned = True
        _record(source, seconds, wav)
        if not wav.is_file() or wav.stat().st_size < 16:
            return agent._err("No audio was captured.", source=source)
    transcript = _transcribe(wav).strip()
    if owned:
        try:
            wav.unlink()
        except OSError:
            pass
    if not transcript:
        return agent._err("No speech was captured.", source=source)
    body = notes_from_transcript(transcript)
    if not body:
        return agent._err("No speech was captured.", source=source)
    note.write_text(body, encoding="utf-8")
    message = f"Saved voice notes to {note}."
    print(f"[scribe] {message}", flush=True)
    return agent._ok(
        message,
        status="ready",
        path=str(note),
        source=source,
        seconds=seconds,
    )


def audio_scribe_tool(
    source: str = "mic",
    seconds: Any = DEFAULT_SECONDS,
    output_path: str = "",
    audio_path: str = "",
) -> dict[str, Any]:
    """Capture a bounded note and write markdown bullets on this PC."""
    agent = _agent()
    try:
        kind = _source_name(source)
        duration = _seconds(seconds)
        if kind == "file" and not str(audio_path or "").strip():
            return agent._err("Pass audio_path for a file that is already on this PC.")
        if agent.recorder_override is not None or kind == "file":
            return _work(kind, duration, output_path, audio_path)
        holder: dict[str, Any] = {}

        def _thread() -> None:
            try:
                holder["result"] = _work(kind, duration, output_path, audio_path)
            except AssertionError as exc:
                holder["assertion"] = exc
            except Exception as exc:
                holder["result"] = agent._err(f"audio_scribe_tool failed: {exc}")

        worker = threading.Thread(target=_thread, name="audio-scribe", daemon=True)
        with _lock:
            _threads.append(worker)
        worker.start()
        worker.join(_JOIN_SECONDS)
        if "assertion" in holder:
            raise holder["assertion"]
        if "result" in holder and not worker.is_alive():
            return holder["result"]
        return agent._ok(
            "The voice note is recording in the background. The file is not ready yet.",
            status="started",
            source=kind,
            seconds=duration,
        )
    except AssertionError:
        raise
    except Exception as exc:
        return agent._err(f"audio_scribe_tool failed: {exc}")
