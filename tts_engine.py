"""Cloud speech for spoken replies.

ElevenLabs is used when ELEVENLABS_API_KEY is set. Cartesia Sonic is next
when CARTESIA_API_KEY is set, then Deepgram Aura-2 when DEEPGRAM_API_KEY is
set. With no speech key, the caller keeps the local edge-tts voice.

The HTTP calls use the standard library. Tests set transport_override and
must not open a socket. API keys stay in the headers and out of errors.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable

# George, a premade conversational male voice.
DEFAULT_VOICE_ID = "JBFqnCBsd6RMkjVDRZzb"
DEFAULT_MODEL = "eleven_v3"
# Middle of the requested expressive range.
DEFAULT_STABILITY = 0.38
DEFAULT_SIMILARITY = 0.80
DEFAULT_STYLE = 0.20
# Barbershop Man, a premade Cartesia male voice.
DEFAULT_CARTESIA_VOICE = "694f9389-aac1-45b6-b726-9d9369183238"
DEFAULT_CARTESIA_MODEL = "sonic-3.6"
# Orion, a male Aura-2 voice.
DEFAULT_DEEPGRAM_MODEL = "aura-2-orion-en"
_MAX_AUDIO = 8 * 1024 * 1024
_ELEVEN_MODELS = {"eleven_v3", "eleven_multilingual_v2"}
_HOSTS = {
    "eleven": "api.elevenlabs.io",
    "cartesia": "api.cartesia.ai",
    "deepgram": "api.deepgram.com",
}

transport_override: Callable[[dict[str, Any]], bytes] | None = None


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Speech requests must stay on the speech host. The key is in a header."""

    def redirect_request(
        self,
        req: Any,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        raise RuntimeError("The speech request was redirected.")


def _key(name: str) -> str:
    return os.environ.get(name, "").strip()


def _scrub(text: str) -> str:
    safe = text or ""
    for name in (
        "ELEVENLABS_API_KEY",
        "CARTESIA_API_KEY",
        "DEEPGRAM_API_KEY",
    ):
        secret = _key(name)
        if len(secret) >= 6:
            safe = safe.replace(secret, "[redacted]")
    return safe


def _clamped(name: str, default: float, low: float, high: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    if value < low:
        return low
    if value > high:
        return high
    return value


def eleven_model() -> str:
    """eleven_v3 keeps reaction tags. eleven_multilingual_v2 is the other model."""
    chosen = os.environ.get("ELEVENLABS_MODEL", "").strip()
    if chosen in _ELEVEN_MODELS:
        return chosen
    return DEFAULT_MODEL


def voice_settings() -> dict[str, Any]:
    """Expressive male delivery. Values stay inside the requested ranges."""
    return {
        "stability": _clamped("ELEVENLABS_STABILITY", DEFAULT_STABILITY, 0.30, 0.45),
        "similarity_boost": _clamped(
            "ELEVENLABS_SIMILARITY",
            DEFAULT_SIMILARITY,
            0.75,
            0.85,
        ),
        "style": _clamped("ELEVENLABS_STYLE", DEFAULT_STYLE, 0.15, 0.25),
        "use_speaker_boost": True,
    }


def voice_id() -> str:
    """VOICE_ID from the environment, or George when that value is unusable."""
    chosen = os.environ.get("VOICE_ID", "").strip()
    if chosen and _safe_id(chosen):
        return chosen
    return DEFAULT_VOICE_ID


def _safe_id(value: str) -> bool:
    if len(value) < 10 or len(value) > 80:
        return False
    return all(char.isalnum() or char in {"-", "_"} for char in value)


def _cartesia_voice() -> str:
    chosen = os.environ.get("CARTESIA_VOICE_ID", "").strip()
    if chosen and _safe_id(chosen):
        return chosen
    return DEFAULT_CARTESIA_VOICE


def _cartesia_model() -> str:
    chosen = os.environ.get("CARTESIA_MODEL", "").strip()
    if chosen.startswith("sonic-") and all(char.isalnum() or char in {".", "-"} for char in chosen):
        return chosen[:40]
    return DEFAULT_CARTESIA_MODEL


def _deepgram_model() -> str:
    chosen = os.environ.get("DEEPGRAM_MODEL", "").strip()
    if (
        chosen.startswith("aura-2-")
        and chosen.endswith("-en")
        and all(char.islower() or char.isdigit() or char == "-" for char in chosen)
    ):
        return chosen[:48]
    return DEFAULT_DEEPGRAM_MODEL


def engines() -> list[str]:
    """Configured cloud engines, primary first."""
    found: list[str] = []
    if _key("ELEVENLABS_API_KEY"):
        found.append("eleven")
    if _key("CARTESIA_API_KEY"):
        found.append("cartesia")
    if _key("DEEPGRAM_API_KEY"):
        found.append("deepgram")
    return found


def cloud_configured() -> bool:
    return bool(engines())


def keeps_audio_tags() -> bool:
    """True when the primary voice can perform bracket tags as sounds."""
    return "eleven" in engines() and eleven_model() == "eleven_v3"


def active_voice_label() -> str | None:
    """Voice id of the first configured cloud engine."""
    order = engines()
    if not order:
        return None
    if order[0] == "eleven":
        return voice_id()
    if order[0] == "cartesia":
        return _cartesia_voice()
    return _deepgram_model()


def _eleven_request(text: str) -> dict[str, Any]:
    voice = voice_id()
    query = urllib.parse.urlencode({"output_format": "mp3_44100_128"})
    return {
        "engine": "eleven",
        "url": f"https://api.elevenlabs.io/v1/text-to-speech/{voice}?{query}",
        "headers": {
            "xi-api-key": _key("ELEVENLABS_API_KEY"),
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        },
        "body": {
            "text": text,
            "model_id": eleven_model(),
            "voice_settings": voice_settings(),
        },
    }


def _cartesia_request(text: str) -> dict[str, Any]:
    return {
        "engine": "cartesia",
        "url": "https://api.cartesia.ai/tts/bytes",
        "headers": {
            "Authorization": f"Bearer {_key('CARTESIA_API_KEY')}",
            "Cartesia-Version": "2026-08-14",
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        },
        "body": {
            "model_id": _cartesia_model(),
            "transcript": text,
            "voice": _cartesia_voice(),
            "language": "en",
            "output_format": {
                "container": "mp3",
                "sample_rate": 44100,
                "bit_rate": 128000,
            },
        },
    }


def _deepgram_request(text: str) -> dict[str, Any]:
    query = urllib.parse.urlencode(
        {"model": _deepgram_model(), "encoding": "mp3"}
    )
    return {
        "engine": "deepgram",
        "url": f"https://api.deepgram.com/v1/speak?{query}",
        "headers": {
            "Authorization": f"Token {_key('DEEPGRAM_API_KEY')}",
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        },
        "body": {"text": text},
    }


def _request_for(engine: str, text: str) -> dict[str, Any]:
    if engine == "eleven":
        return _eleven_request(text)
    if engine == "cartesia":
        return _cartesia_request(text)
    if engine == "deepgram":
        return _deepgram_request(text)
    raise RuntimeError("Unknown speech engine.")


def _checked_audio(data: Any, mime: str) -> bytes:
    if not isinstance(data, (bytes, bytearray)):
        raise RuntimeError("The speech service returned no audio.")
    raw = bytes(data)
    if len(raw) < 16 or len(raw) > _MAX_AUDIO:
        raise RuntimeError("The speech service returned no audio.")
    kind = (mime or "").split(";", 1)[0].strip().casefold()
    if "json" in kind or raw[:1] in {b"{", b"["}:
        raise RuntimeError("The speech service did not return audio.")
    return raw


def _post(spec: dict[str, Any]) -> bytes:
    if transport_override is not None:
        return _checked_audio(transport_override(spec), "audio/mpeg")
    payload = json.dumps(spec["body"]).encode("utf-8")
    request = urllib.request.Request(
        spec["url"],
        data=payload,
        headers=spec["headers"],
        method="POST",
    )
    opener = urllib.request.build_opener(_NoRedirect)
    expected = _HOSTS[spec["engine"]]
    try:
        with opener.open(request, timeout=30) as response:
            final = response.geturl() if hasattr(response, "geturl") else spec["url"]
            host = urllib.parse.urlparse(str(final)).hostname or ""
            if host != expected:
                raise RuntimeError("The speech request left the speech service.")
            mime = ""
            headers = getattr(response, "headers", None)
            if headers is not None:
                mime = str(headers.get("Content-Type") or "")
            raw = response.read(_MAX_AUDIO + 1)
    except AssertionError:
        raise
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read(400).decode("utf-8", errors="replace")
        except Exception:
            detail = ""
        raise RuntimeError(
            f"The speech service rejected the request. {_scrub(detail)[:300]}"
        ) from None
    except Exception as exc:
        raise RuntimeError(
            f"The speech service could not be reached. {_scrub(str(exc))[:300]}"
        ) from None
    return _checked_audio(raw, mime)


def write_mp3(text: str, destination: Path) -> str:
    """Write one mp3. Tries each configured cloud engine. Returns its voice label."""
    spoken = (text or "").strip()
    if not spoken:
        raise RuntimeError("Nothing to speak.")
    errors: list[str] = []
    for engine in engines():
        spec = _request_for(engine, spoken)
        try:
            audio = _post(spec)
        except AssertionError:
            raise
        except Exception as exc:
            errors.append(_scrub(str(exc)))
            continue
        destination.write_bytes(audio)
        if engine == "eleven":
            return voice_id()
        if engine == "cartesia":
            return _cartesia_voice()
        return _deepgram_model()
    detail = errors[-1] if errors else "No speech key is set."
    raise RuntimeError(detail)
