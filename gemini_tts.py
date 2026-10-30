"""1.6.9: emotional bot voices with Gemini native TTS, the same way Voice to Short does it.

- Model: the one that last worked, then the TTS models the key lists (newest first), then a known chain.
  Nothing retired is hardcoded as the only choice; a 404/unsupported model just moves to the next.
- Request: generateContent, responseModalities AUDIO, speechConfig.voiceConfig.prebuiltVoiceConfig.voiceName.
- Emotion: a small Gemini text call picks the tone of each reply (warm, excited, sad, sarcastic, calm...)
  and writes a one-line delivery note. 3.5+ TTS models get it in speech_metadata.style (they read text
  verbatim); older ones get a spoken prefix ("Say in a ... voice: ").
- Quota (429) on every model raises Quota so the caller falls back to the old voice and tells the user.
The key is read from GEMINI_API_KEY on this PC only and never logged or returned.
"""
from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
import wave
from pathlib import Path
from typing import Any, Callable

HOST = "https://generativelanguage.googleapis.com/v1beta"
KNOWN_MODELS = ["gemini-3.8-flash-tts", "gemini-3.8-flash-lite-tts", "gemini-3.1-flash-tts-preview",
                "gemini-2.5-flash-preview-tts", "gemini-2.5-pro-preview-tts"]
TONE_MODELS = ["gemini-flash-lite-latest", "gemini-flash-latest", "gemini-2.5-flash-lite"]
VOICES = {
    "female": [("Sulafat", "Warm"), ("Aoede", "Breezy"), ("Kore", "Firm"), ("Leda", "Youthful"),
               ("Achernar", "Soft"), ("Zephyr", "Bright"), ("Despina", "Smooth"), ("Vindemiatrix", "Gentle")],
    "male": [("Puck", "Upbeat"), ("Achird", "Friendly"), ("Charon", "Informative"), ("Fenrir", "Excitable"),
             ("Orus", "Firm"), ("Algenib", "Gravelly"), ("Sadaltager", "Knowledgeable"), ("Enceladus", "Breathy")],
}
DEFAULT = {"gender": "female", "name": "Sulafat"}
# Voice to Short's delivery (its default voice is Sulafat, model gemini-3.8-flash-tts, style in speech_metadata.style)
BASE = ("young-adult General American storyteller, natural and brisk, real feeling in the voice: small hesitations, "
        "audible breaths and sighs where they fit, high pitch variation, clear emotional shifts line to line")
TONES = {
    "deadpan": "deadpan: flat, understated and unimpressed, perfectly timed pauses, never over-acted",
    "embarrassed": "embarrassed and flustered, hushed, a nervous little laugh, words tumbling out",
    "reassuring": "reassuring and kind, warm smile in the voice, slower and steady",
    "informative": "clear and informative, like a friendly teacher explaining, light and confident",
    "upbeat": "upbeat and bright, smiling, quick and lively",
    "whisper": "hushed, breathy aside, close to the mic, like sharing a secret",
    "warm": "warm, kind and caring, smiling softly",
    "excited": "genuinely excited and energetic, bright and fast, with real joy",
    "happy": "happy and upbeat, light and smiling",
    "sad": "sad and gentle, slower, a little heavy, with real sympathy",
    "sarcastic": "sarcastic best friend: dry, teasing and playful, with knowing pauses before punchlines and a smile in the voice; quick, conversational pace",
    "calm": "calm, warm and confident, like a kind teacher; unhurried pace with small natural pauses",
    "funny": "playful and comic, with comic timing and a laugh in the voice",
    "serious": "serious and focused, clear and firm",
    "apologetic": "sincerely apologetic, soft and humble",
    "proud": "proud and confident, beaming",
    "curious": "curious and intrigued, wondering aloud",
    "dramatic": "dramatic storyteller: intense and cinematic, building suspense, short punchy pauses before reveals, never cheesy",
    "angry": "frustrated and annoyed, sharp but not shouting",
    "nervous": "nervous and awkward, hesitant, a bit embarrassed",
}

transport_override: Callable[[str, dict | None], dict] | None = None   # tests
_lock = threading.Lock()
_listed: tuple[float, list[str]] = (0.0, [])
_cool: dict[str, float] = {}


class Quota(RuntimeError):
    pass


def key() -> str:
    k = os.environ.get("GEMINI_API_KEY", "").strip()
    if not k:
        for part in os.environ.get("GEMINI_API_KEYS", "").split(","):
            if part.strip():
                return part.strip()
    return k


def available() -> bool:
    import sys
    if "unittest" in sys.modules and transport_override is None:   # tests never call the real API
        return False
    return bool(key()) and os.environ.get("PEDBOT_GEMINI_VOICE", "1") != "0"


def _state_file() -> Path:
    try:
        import agent_config
        return agent_config.storage_dir() / "gemini_tts.json"
    except Exception:
        return Path(tempfile.gettempdir()) / "pedbot_gemini_tts.json"


def _remembered() -> str:
    try:
        return str(json.loads(_state_file().read_text(encoding="utf-8")).get("model") or "")
    except Exception:
        return ""


def _remember(model: str) -> None:
    try:
        p = _state_file(); p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"model": model, "at": time.time()}), encoding="utf-8")
    except Exception:
        pass


def _request(path: str, body: dict | None, timeout: float = 90) -> dict:
    if transport_override is not None:
        return transport_override(path, body)
    req = urllib.request.Request(HOST + path, data=None if body is None else json.dumps(body).encode(),
                                 method="GET" if body is None else "POST",
                                 headers={"Content-Type": "application/json", "x-goog-api-key": key()})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read().decode("utf-8")).get("error", {}).get("message", "")
        except Exception:
            msg = ""
        err = RuntimeError(f"Gemini voice error {e.code}: {msg[:200]}")
        err.status = e.code  # type: ignore[attr-defined]
        raise err from None


def _score(n: str) -> float:
    v = re.search(r"gemini-(\d+(?:\.\d+)?)", n)
    return (float(v.group(1)) if v else 0) * 10 - (2 if "lite" in n else 0) - (3 if "preview" in n else 0) - (1 if "pro" in n else 0)


def list_models() -> list[str]:
    global _listed
    if time.time() - _listed[0] < 6 * 3600 and _listed[1]:
        return _listed[1]
    try:
        d = _request("/models?pageSize=200", None, 20)
        names = [str(m.get("name", "")).replace("models/", "") for m in d.get("models") or []
                 if "generateContent" in (m.get("supportedGenerationMethods") or [])]
        names = sorted([n for n in names if n.startswith("gemini") and "tts" in n], key=_score, reverse=True)
    except Exception:
        names = []
    _listed = (time.time(), names)
    return names


def model_chain() -> list[str]:
    out: list[str] = []
    for m in [_remembered()] + list_models() + KNOWN_MODELS:
        if m and m not in out:
            out.append(m)
    return out


def structured(model: str) -> bool:
    v = re.search(r"gemini-(\d+(?:\.\d+)?)", model)
    return not v or float(v.group(1)) >= 3.5


def voice_for(bot: dict | None) -> dict:
    v = (bot or {}).get("voice") or {}
    gender = v.get("gender") if v.get("gender") in VOICES else DEFAULT["gender"]
    names = [n for n, _ in VOICES[gender]]
    name = v.get("name") if v.get("name") in names else names[0]
    return {"gender": gender, "name": name}


_SAD = re.compile(r"\b(sorry to hear|passed away|so sorry|grief|lost (?:my|your)|that's hard|heartbreak|sad)\b", re.I)
_EXC = re.compile(r"(!{1,}|\b(amazing|awesome|congrat\w*|great news|we did it|yay|woo+|incredible)\b)", re.I)
_SORRY = re.compile(r"\b(i'm sorry|my mistake|i apologi[sz]e|my bad)\b", re.I)
_FUN = re.compile(r"(\[laughs?\]|haha|lol|😂|🤣|\bjoke\b)", re.I)


def guess_tone(text: str) -> str:
    if _SAD.search(text):
        return "sad"
    if _SORRY.search(text):
        return "apologetic"
    if _FUN.search(text):
        return "funny"
    if _EXC.search(text):
        return "excited"
    return "warm"


def pick_tone(reply: str, user_text: str = "", quick: bool = False) -> dict:
    """Ask Gemini (text) for the tone of this reply. Falls back to a quick local guess."""
    tone = guess_tone(reply)
    style = TONES[tone]
    if quick or not key():
        return {"tone": tone, "style": style, "by": "guess"}
    prompt = ("You direct a voice actor. Read the user's message and the reply the actor will say. Pick the ONE tone "
              "that makes the reply feel real and emotional: " + ", ".join(TONES) + ". Then write a short delivery note "
              "(max 18 words) about feeling, pace and emphasis. Answer only JSON {\"tone\":\"...\",\"style\":\"...\"}.\n\n"
              f"User: {user_text[:600]}\nReply: {reply[:1500]}")
    body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.4, "maxOutputTokens": 120, "responseMimeType": "application/json"}}
    for m in TONE_MODELS:
        try:
            d = _request(f"/models/{m}:generateContent", body, 8)
            txt = "".join(p.get("text", "") for p in d["candidates"][0]["content"]["parts"])
            j = json.loads(re.search(r"\{.*\}", txt, re.S).group(0))
            t = str(j.get("tone", "")).lower().strip()
            if t in TONES:
                note = " ".join(str(j.get("style") or "").split())[:160]
                return {"tone": t, "style": TONES[t] + (". " + note if note else ""), "by": m}
        except Exception:
            continue
    return {"tone": tone, "style": style, "by": "guess"}


def direct(reply: str, user_text: str = "") -> dict:
    """Rewrite the reply for the ear (fillers, '...' pauses, breaths) with one emotion per line.
    Returns {"tone", "style", "lines": [{"text", "emotion"}]}; falls back to the plain text and a guessed tone."""
    t = pick_tone(reply, user_text, quick=True)
    plain = {"tone": t["tone"], "style": t["style"], "lines": [{"text": reply, "emotion": t["tone"]}], "by": "guess"}
    if not key() or len(reply) > 2400:
        return plain
    prompt = ("You are the voice director for a warm, expressive storyteller (like a Quiet Brain YouTube Short). Rewrite the "
              "REPLY below so it sounds natural spoken aloud: keep every fact and the meaning, same language, about the same length; "
              "add a few natural fillers and hesitations ('okay', 'so', 'I... I mean', 'honestly?'), '...' for pauses, and break it into "
              "short lines. Give each line one emotion from: " + ", ".join(TONES) + ". Do not add stage directions in the text. "
              "Answer only JSON {\"tone\":\"overall emotion\",\"lines\":[{\"text\":\"...\",\"emotion\":\"...\"}]} with at most 8 lines.\n\n"
              f"USER SAID: {user_text[:500]}\nREPLY: {reply}")
    body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.7, "maxOutputTokens": 1500, "responseMimeType": "application/json"}}
    for m in TONE_MODELS:
        try:
            d = _request(f"/models/{m}:generateContent", body, 12)
            txt = "".join(p.get("text", "") for p in d["candidates"][0]["content"]["parts"])
            j = json.loads(re.search(r"\{.*\}", txt, re.S).group(0))
            lines = [{"text": " ".join(str(x.get("text") or "").split())[:600],
                      "emotion": str(x.get("emotion") or "").lower().strip()} for x in (j.get("lines") or [])[:8]]
            lines = [x for x in lines if x["text"]]
            if not lines:
                continue
            for x in lines:
                if x["emotion"] not in TONES:
                    x["emotion"] = t["tone"]
            tone = str(j.get("tone") or "").lower().strip()
            tone = tone if tone in TONES else lines[0]["emotion"]
            return {"tone": tone, "style": TONES[tone], "lines": lines, "by": m}
        except Exception:
            continue
    return plain


def clean(text: str) -> str:
    t = re.sub(r"```.*?```", " ", text or "", flags=re.S)
    t = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", t)
    t = re.sub(r"https?://\S+", "a link", t)
    t = re.sub(r"[*_#>`|]+", " ", t)
    return " ".join(t.split())[:2500]


def _synth_once(model: str, text: str, voice: str, style: str, lines: list | None = None) -> tuple[bytes, int]:
    part: dict[str, Any] = {"text": text}
    parts = [part]
    if structured(model) and lines and len(lines) > 1:
        # one part per line, each with its own emotion (Voice to Short style: text verbatim, delivery in metadata)
        parts = [{"text": l["text"], "speech_metadata": {"style": BASE + "; this line: " + TONES.get(l["emotion"], style)}} for l in lines]
    elif structured(model):
        if style:
            part["speech_metadata"] = {"style": BASE + "; " + style}
    elif style:
        part["text"] = f"Say in a {style} voice: {text}"
    body = {"contents": [{"role": "user", "parts": parts}],
            "generationConfig": {"responseModalities": ["AUDIO"],
                                 "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}}}}
    try:
        d = _request(f"/models/{model}:generateContent", body, 120)
    except RuntimeError as e:
        if getattr(e, "status", 0) == 400 and any("speech_metadata" in p for p in parts):   # not accepted: spoken prefix
            body["contents"][0]["parts"] = [{"text": f"Say in a {style} voice: {text}"}]
            d = _request(f"/models/{model}:generateContent", body, 120)
        else:
            raise
    parts = (((d.get("candidates") or [{}])[0].get("content") or {}).get("parts")) or []
    audio = next((p.get("inlineData") or p.get("inline_data") for p in parts if (p.get("inlineData") or p.get("inline_data"))), None)
    if not audio or not audio.get("data"):
        raise RuntimeError("Gemini returned no audio.")
    raw = base64.b64decode(audio["data"])
    mime = audio.get("mimeType") or audio.get("mime_type") or ""
    rate = int((re.search(r"rate=(\d+)", mime) or [0, 24000])[1])
    if raw[:4] == b"RIFF":
        import io
        with wave.open(io.BytesIO(raw)) as w:
            return w.readframes(w.getnframes()), w.getframerate()
    return raw, rate


def synth(text: str, voice: str, style: str = "", lines: list | None = None) -> tuple[bytes, int, str]:
    """PCM16 mono bytes, sample rate, model used. Raises Quota when every model is out of quota."""
    if not key():
        raise RuntimeError("No Gemini key on this PC.")
    quota, last = False, None
    for m in model_chain():
        if _cool.get(m, 0) > time.time():
            quota = True
            continue
        try:
            pcm, rate = _synth_once(m, text, voice, style, lines)
            if m != _remembered() and not quota:   # a quota skip is not a reason to switch for good
                _remember(m)
            return pcm, rate, m
        except RuntimeError as e:
            last = e; st = getattr(e, "status", 0)
            if st == 429 or "quota" in str(e).lower() or "exhausted" in str(e).lower():
                quota = True; _cool[m] = time.time() + 60; continue
            if st in (404, 400, 403, 500, 503):
                continue
            raise
    if quota:
        raise Quota("Gemini voice quota is used up for now.")
    raise last or RuntimeError("No Gemini voice model worked.")


def write_audio(pcm: bytes, rate: int, dest: Path) -> str:
    """mp3 through ffmpeg when it is on the PC, else WAV bytes (players and browsers sniff the format)."""
    tmp = dest.with_suffix(".wav.tmp")
    with wave.open(str(tmp), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate); w.writeframes(pcm)
    ff = os.environ.get("FFMPEG_EXECUTABLE", "").strip().strip('"') or shutil.which("ffmpeg")
    if ff and dest.suffix == ".mp3":
        try:
            subprocess.run([ff, "-y", "-loglevel", "error", "-f", "wav", "-i", str(tmp), "-b:a", "96k", str(dest)],
                           check=True, timeout=60, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            tmp.unlink(missing_ok=True)
            return "mp3"
        except Exception:
            pass
    os.replace(tmp, dest)
    return "wav"


# who is speaking right now (set by the chat turn), so the voice matches the bot; one tone per reply
_turn: dict[str, Any] = {"bot": None, "user": "", "tone": None}
last_note = ""   # set when Gemini was out of quota and the old voice was used (shown as a toast)


def set_context(bot: dict | None, user_text: str = "") -> None:
    _turn.update(bot=bot, user=user_text, tone=None)


def speak_to_file(text: str, dest: Path, bot: dict | None = None, user_text: str = "", tone: str = "") -> dict:
    from_turn = bot is None
    bot = bot if bot is not None else _turn["bot"]
    user_text = user_text or (_turn["user"] if from_turn else "")
    v = voice_for(bot)
    words = clean(text)
    if not words:
        raise RuntimeError("Nothing to say.")
    cached = _turn["tone"] if from_turn else None
    if tone in TONES:
        t = {"tone": tone, "style": TONES[tone], "lines": [{"text": words, "emotion": tone}], "by": "given"}
    elif cached and len(words) < 400:
        # sentence-by-sentence speech: keep the reply's tone, no extra rewrite call per sentence
        t = {"tone": cached["tone"], "style": cached["style"], "lines": [{"text": words, "emotion": cached["tone"]}], "by": "turn"}
    else:
        t = direct(words, user_text)
        if from_turn:
            _turn["tone"] = t
    spoken = " ".join(l["text"] for l in t["lines"])
    pcm, rate, model = synth(spoken, v["name"], t["style"], t["lines"])
    fmt = write_audio(pcm, rate, dest)
    return {"voice": v["name"], "gender": v["gender"], "tone": t["tone"], "style": t["style"], "model": model, "format": fmt,
            "lines": t["lines"], "spoken": spoken}
