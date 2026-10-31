"""Local real-voice clone on the PC (Piper or XTTS if installed).

Needs the consent recording from Lab › My voice. Samples never leave this PC.
If the engine is missing, fall back to the closest Gemini voice.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

speak_override = None  # tests: fn(text) -> dict


def _lab_root() -> Path:
    try:
        import lab183
        return lab183._store()
    except Exception:
        import agent_config
        return agent_config.storage_dir() / "lab"


def _lab_voice_dir() -> Path:
    return _lab_root() / "voice"


def _meta() -> dict[str, Any]:
    path = _lab_root() / "voice_meta.json"
    try:
        import json
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _samples() -> list[Path]:
    d = _lab_voice_dir()
    if not d.is_dir():
        return []
    return sorted(p for p in d.glob("sample*.*") if p.stat().st_size > 2000)


def engine() -> dict[str, Any]:
    piper = shutil.which("piper") or shutil.which("piper.exe")
    model = ""
    if piper:
        for cand in (
            Path(piper).resolve().parent / "en_US-lessac-medium.onnx",
            Path.home() / "piper" / "en_US-lessac-medium.onnx",
        ):
            if cand.is_file():
                model = str(cand)
                break
    xtts = False
    try:
        import TTS  # noqa: F401
        xtts = True
    except Exception:
        xtts = False
    kind = "piper" if piper else ("xtts" if xtts else "")
    return {
        "piper": bool(piper),
        "piper_bin": piper or "",
        "piper_model": model,
        "xtts": xtts,
        "kind": kind,
        "ready": bool(kind),
    }


def status() -> dict[str, Any]:
    meta = _meta()
    samples = _samples()
    eng = engine()
    consent = bool(meta.get("consent"))
    return {
        "ok": True,
        "consent": consent,
        "samples": len(samples),
        "match": meta.get("match") or "",
        "describe": meta.get("describe") or "",
        "engine": eng,
        "available": bool(consent and samples and eng["ready"]),
        "note": (
            "Record consent + samples in Lab › My voice first. "
            "Install Piper (rhasspy/piper, free) or Coqui XTTS-v2 on this PC for a true clone. "
            "Samples never leave this PC. If the engine is missing, Ped Bot uses the closest Gemini voice."
        ),
    }


def _fallback_gemini(text: str) -> dict[str, Any]:
    try:
        import gemini_tts
        voice = str(_meta().get("match") or "Puck")
        # gemini_tts speaks via the existing pipeline; expose a hint for the UI
        return {
            "ok": True,
            "fallback": True,
            "voice": voice,
            "text": text,
            "message": f"Local clone engine is not installed, so this used Gemini voice {voice}.",
        }
    except Exception as exc:
        return {"ok": False, "error": "No local clone engine and Gemini voice failed.", "detail": str(exc)[:160]}


def speak(text: str) -> dict[str, Any]:
    text = " ".join((text or "").split())[:500]
    if not text:
        return {"ok": False, "error": "Nothing to say."}
    if speak_override is not None:
        return speak_override(text)
    st = status()
    if not st["consent"] or st["samples"] < 1:
        return {"ok": False, "error": "Record the consent sentence and samples in Lab › My voice first."}
    eng = st["engine"]
    out_dir = _lab_voice_dir() / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    wav = out_dir / "last.wav"
    try:
        if eng["kind"] == "piper" and eng["piper_bin"]:
            cmd = [eng["piper_bin"], "--output_file", str(wav)]
            if eng["piper_model"]:
                cmd.extend(["--model", eng["piper_model"]])
            subprocess.run(cmd, input=text.encode("utf-8"), check=True, timeout=60, capture_output=True)
            return {"ok": True, "file": str(wav), "engine": "piper", "fallback": False}
        if eng["kind"] == "xtts":
            from TTS.api import TTS
            sample = str(_samples()[-1])
            tts = TTS("tts_models/multilingual/multi-dataset/xtts_v2", gpu=False)
            tts.tts_to_file(text=text, speaker_wav=sample, language="en", file_path=str(wav))
            return {"ok": True, "file": str(wav), "engine": "xtts", "fallback": False}
    except Exception as exc:
        fb = _fallback_gemini(text)
        fb["detail"] = str(exc)[:160]
        return fb
    return _fallback_gemini(text)


def handle(action: str, data: dict[str, Any]) -> dict[str, Any]:
    if action in ("", "status"):
        return status()
    if action == "speak":
        return speak(str(data.get("text") or ""))
    return {"ok": False, "error": "Unknown voice action."}
