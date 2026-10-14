"""Optional Gemini Live realtime voice.

Streams the mic (16 kHz PCM) and, if enabled, a screen frame every
live.screen_every_seconds to a Gemini Live session, and plays the spoken
reply (24 kHz PCM). Talking over it barges in: the server sends
"interrupted" and the queued audio is dropped at once. Tool calls from the
Live model go through invoke_tool, so rules.yaml applies as usual.

If the SDK, the mic, the key or the Live model is unavailable, run() returns
fallback=True and the normal speech-to-text / text-to-speech loop is used.
Use headphones: without echo cancellation the speakers can trigger barge-in.
"""

from __future__ import annotations

import asyncio
import io
import os
import queue
import threading
import time
from typing import Any, Callable

import rules
import speech_level

DEFAULTS = {
    "enabled": False,
    "models": ["gemini-2.5-flash-native-audio-preview-12-2025", "gemini-live-2.5-flash-preview"],
    "voice_name": "Puck",
    "send_screen": True,
    "screen_every_seconds": 1.0,
    "screen_max_width": 1024,
    "allow_tools": True,
}
IN_RATE, OUT_RATE, CHUNK = 16_000, 24_000, 1024


def settings() -> dict[str, Any]:
    return rules.section("live", DEFAULTS)


def unavailable_reason() -> str | None:
    if not os.environ.get("GEMINI_API_KEY", "").strip():
        return "GEMINI_API_KEY is not set."
    try:
        from google.genai import types  # noqa: F401
        from google import genai

        if not hasattr(genai.Client, "aio") and not hasattr(genai, "Client"):
            return "This google-genai has no Live support."
    except ImportError:
        return "google-genai is not installed."
    try:
        import pyaudio  # noqa: F401  (pyaudiowpatch provides it)
    except ImportError:
        return "pyaudio (pyaudiowpatch) is not installed."
    return None


class Playback:
    """Audio out queue. clear() drops everything still queued (barge-in)."""

    def __init__(self) -> None:
        self.q: "queue.Queue[bytes]" = queue.Queue()
        self.generation = 0

    def put(self, data: bytes) -> None:
        self.q.put(data)

    def clear(self) -> int:
        dropped = 0
        self.generation += 1
        while True:
            try:
                self.q.get_nowait()
                dropped += 1
            except queue.Empty:
                return dropped


def pcm_level(data: bytes) -> float:
    env = speech_level.envelope_from_raw(data, OUT_RATE, 1)
    if not env:
        return 0.0
    import array
    import math

    samples = array.array("h")
    samples.frombytes(data[: len(data) - len(data) % 2])
    if not samples:
        return 0.0
    rms = math.sqrt(sum(v * v for v in samples) / len(samples))
    return min(1.0, rms / 6000.0)


def encode_frame(image: Any, max_width: int = 1024, quality: int = 60) -> bytes:
    """PIL image -> JPEG bytes no wider than max_width."""
    if image.width > max_width:
        image = image.resize((max_width, int(image.height * max_width / image.width)))
    out = io.BytesIO()
    image.convert("RGB").save(out, "JPEG", quality=quality)
    return out.getvalue()


def grab_screen_frame(max_width: int) -> bytes | None:
    try:
        import mss
        from PIL import Image

        with mss.mss() as sct:
            shot = sct.grab(sct.monitors[1])
        return encode_frame(Image.frombytes("RGB", shot.size, shot.rgb), max_width)
    except Exception:
        return None


def handle_message(msg: Any, playback: Playback, *, on_text: Callable[[str, str], None] | None = None,
                   run_tool: Callable[[str, dict[str, Any]], dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Process one Live server message. Returns tool responses to send back."""
    responses: list[dict[str, Any]] = []
    content = getattr(msg, "server_content", None)
    if content is not None:
        if getattr(content, "interrupted", False):
            playback.clear()
            speech_level.stop()
        turn = getattr(content, "model_turn", None)
        for part in getattr(turn, "parts", None) or []:
            blob = getattr(part, "inline_data", None)
            if blob is not None and getattr(blob, "data", None):
                playback.put(blob.data)
        for kind in ("input_transcription", "output_transcription"):
            tr = getattr(content, kind, None)
            if tr is not None and getattr(tr, "text", None) and on_text:
                on_text("user" if kind.startswith("input") else "assistant", tr.text)
    call = getattr(msg, "tool_call", None)
    for fc in getattr(call, "function_calls", None) or []:
        result = (run_tool or _invoke)(fc.name, dict(getattr(fc, "args", None) or {}))
        responses.append({"id": getattr(fc, "id", None), "name": fc.name, "response": _slim(result)})
    return responses


def _slim(result: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in (result or {}).items() if isinstance(v, (str, int, float, bool, list, dict, type(None)))}


def _invoke(name: str, args: dict[str, Any]) -> dict[str, Any]:
    import gta5_agent

    return gta5_agent.invoke_tool(name, args)


def build_config(types: Any) -> Any:
    import gta5_agent

    cfg = settings()
    kwargs: dict[str, Any] = {
        "response_modalities": ["AUDIO"],
        "speech_config": types.SpeechConfig(voice_config=types.VoiceConfig(
            prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=str(cfg["voice_name"])))),
        "system_instruction": types.Content(parts=[types.Part(text=(
            f"You are {gta5_agent.AGENT_NAME}, a voice assistant on the user's Windows PC. Keep spoken "
            "replies short. You may see the user's screen as images. Use tools for actions."))]),
        "input_audio_transcription": types.AudioTranscriptionConfig(),
        "output_audio_transcription": types.AudioTranscriptionConfig(),
    }
    if cfg.get("allow_tools"):
        allowed = [d for d in gta5_agent.TOOL_DECLARATIONS if rules.tool_block_reason(d["name"]) is None]
        kwargs["tools"] = [{"function_declarations": allowed}]
    return types.LiveConnectConfig(**kwargs)


class LiveVoice:
    def __init__(self, on_text: Callable[[str, str], None] | None = None) -> None:
        self.playback = Playback()
        self.stop_event = threading.Event()
        self.on_text = on_text or (lambda role, text: print(f"{'You' if role == 'user' else 'Agent'}: {text}", flush=True))

    async def _session(self, model: str) -> None:
        import pyaudio
        from google import genai
        from google.genai import types

        cfg = settings()
        client = genai.Client(api_key=os.environ["GEMINI_API_KEY"].strip())
        pa = pyaudio.PyAudio()
        mic = pa.open(format=pyaudio.paInt16, channels=1, rate=IN_RATE, input=True, frames_per_buffer=CHUNK)
        spk = pa.open(format=pyaudio.paInt16, channels=1, rate=OUT_RATE, output=True)
        try:
            async with client.aio.live.connect(model=model, config=build_config(types)) as session:
                print(f"Live voice on ({model}). Talk any time; Ctrl+C to stop.", flush=True)

                async def send_mic() -> None:
                    while not self.stop_event.is_set():
                        data = await asyncio.to_thread(mic.read, CHUNK, exception_on_overflow=False)
                        await session.send_realtime_input(audio=types.Blob(data=data, mime_type=f"audio/pcm;rate={IN_RATE}"))

                async def send_screen() -> None:
                    while cfg.get("send_screen") and not self.stop_event.is_set():
                        frame = await asyncio.to_thread(grab_screen_frame, int(cfg["screen_max_width"]))
                        if frame:
                            await session.send_realtime_input(video=types.Blob(data=frame, mime_type="image/jpeg"))
                        await asyncio.sleep(float(cfg["screen_every_seconds"]))

                async def receive() -> None:
                    while not self.stop_event.is_set():
                        async for msg in session.receive():
                            replies = await asyncio.to_thread(handle_message, msg, self.playback, on_text=self.on_text)
                            if replies:
                                await session.send_tool_response(function_responses=[
                                    types.FunctionResponse(id=r["id"], name=r["name"], response=r["response"]) for r in replies])

                async def play() -> None:
                    while not self.stop_event.is_set():
                        try:
                            data = await asyncio.to_thread(self.playback.q.get, True, 0.2)
                        except queue.Empty:
                            speech_level.stop()
                            continue
                        speech_level.start([pcm_level(data)])
                        speech_level.update(0)
                        await asyncio.to_thread(spk.write, data)

                tasks = [asyncio.create_task(c()) for c in (send_mic, send_screen, receive, play)]
                try:
                    await asyncio.gather(*tasks)
                finally:
                    for t in tasks:
                        t.cancel()
        finally:
            speech_level.stop()
            for stream in (mic, spk):
                try:
                    stream.close()
                except Exception:
                    pass
            pa.terminate()

    def run(self) -> dict[str, Any]:
        reason = unavailable_reason()
        if reason:
            return {"ok": False, "fallback": True, "error": f"Live voice unavailable: {reason}"}
        last = ""
        for model in settings()["models"]:
            started = time.monotonic()
            try:
                asyncio.run(self._session(str(model)))
                return {"ok": True, "message": "Live voice ended."}
            except KeyboardInterrupt:
                self.stop_event.set()
                return {"ok": True, "message": "Live voice stopped."}
            except Exception as exc:
                last = str(exc)
                if time.monotonic() - started > 20:  # it worked for a while, then dropped
                    return {"ok": False, "fallback": True, "error": f"Live voice dropped: {last}"}
        return {"ok": False, "fallback": True, "error": f"Live voice could not connect: {last}"}


def run() -> dict[str, Any]:
    return LiveVoice().run()
