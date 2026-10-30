"""1.8.0 batch 1: 3D avatar commands, live Hindi->English translation, screen tutor, offline mode.

Everything uses the free Gemini key through llm.text (or works without it):
- avatar_plan: a typed/spoken command -> chained clips + expressions + speech + moves.
  Unknown actions fall back to the closest clip by keyword; no key needed for that.
- translate: Hindi (Devanagari or Hinglish) -> natural spoken English.
- tutor: one screen frame + optional question -> short spoken explanation and next step.
- offline: switch Ped Bot to the free local model (Ollama) and back. Stored in storage, not .env.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

CLIPS = ["Idle", "Walking", "Running", "Dance", "Death", "Sitting", "Standing", "Jump", "Yes", "No",
         "Wave", "Punch", "ThumbsUp"]
EXPRESSIONS = ["neutral", "happy", "sad", "angry", "surprised"]
PLACES = ["center", "left", "right", "front", "back", "here"]

_KEYWORDS: list[tuple[str, str]] = [
    (r"(walk|\bgo\b|\bcome\b|\bmove|\bstep|stroll)", "Walking"), (r"\b(run|jog|sprint|hurry|rush)\b", "Running"),
    (r"\b(danc\w*|groove|boogie|party|celebrat\w*|cheer\w*)\b", "Dance"), (r"\b(die|dead|faint|collapse|fall)\b", "Death"),
    (r"\b(sit|seat|rest|chill)\b", "Sitting"), (r"\b(stand|get up|rise)\b", "Standing"),
    (r"\b(jump|hop|leap|bounce)\b", "Jump"), (r"\b(yes|nod|agree)\b", "Yes"), (r"\b(no|shake|disagree|refuse)\b", "No"),
    (r"\b(wave|hello|hi|bye|greet)\b", "Wave"), (r"\b(punch|hit|fight|box)\b", "Punch"),
    (r"\b(thumbs?|like|good job|approve|nice)\b", "ThumbsUp"),
]
_EXPR: list[tuple[str, str]] = [
    (r"\b(sad|cry|upset|down|unhappy|sorry)\b", "sad"), (r"\b(angry|mad|furious|annoyed)\b", "angry"),
    (r"\b(surpris\w*|shock\w*|wow|amazed)\b", "surprised"), (r"\b(happy|smile|cheer\w*|glad|joy|excited)\b", "happy"),
]


def closest_clip(word: str) -> str:
    w = (word or "").strip()
    for c in CLIPS:
        if c.lower() == w.lower():
            return c
    for pat, clip in _KEYWORDS:
        if re.search(pat, w, re.I):
            return clip
    return "Yes" if w else "Idle"


def _expr(word: str) -> str:
    w = (word or "").lower().strip()
    if w in EXPRESSIONS:
        return w
    for pat, e in _EXPR:
        if re.search(pat, w, re.I):
            return e
    return "neutral"


def local_plan(command: str) -> dict[str, Any]:
    """No-key fallback: split on 'then'/'and then'/',' and map each part by keywords."""
    parts = [p.strip() for p in re.split(r"\bthen\b|,|;|\band\b", command or "", flags=re.I) if p.strip()]
    steps = []
    for p in parts or ["idle"]:
        clip = "Idle"
        for pat, c in _KEYWORDS:
            if re.search(pat, p, re.I):
                clip = c
                break
        e = _expr(p)
        if clip == "Idle" and e == "happy":
            clip = "Dance" if re.search(r"cheer", p, re.I) else "Yes"
        if clip == "Idle" and e == "sad":
            clip = "Sitting" if False else "No"
        target = next((pl for pl in PLACES if re.search(rf"\b{pl}\b", p, re.I)), "")
        steps.append({"action": clip, "expression": e, "say": "", "to": target, "seconds": 3})
    return {"ok": True, "steps": steps[:8], "source": "local"}


def clean_plan(raw: Any) -> dict[str, Any]:
    steps_in = raw.get("steps") if isinstance(raw, dict) else raw
    if not isinstance(steps_in, list):
        raise ValueError("no steps")
    steps = []
    for s in steps_in[:8]:
        if not isinstance(s, dict):
            continue
        to = str(s.get("to") or "").lower().strip()
        if to not in PLACES:
            to = ""
        try:
            sec = max(1.0, min(8.0, float(s.get("seconds") or 3)))
        except (TypeError, ValueError):
            sec = 3.0
        steps.append({"action": closest_clip(str(s.get("action") or "")), "expression": _expr(str(s.get("expression") or "")),
                      "say": str(s.get("say") or "")[:240], "to": to, "seconds": sec})
    if not steps:
        raise ValueError("empty")
    return {"ok": True, "steps": steps, "source": "gemini"}


def avatar_plan(command: str, gender: str = "male", here: str = "") -> dict[str, Any]:
    command = " ".join(str(command or "").split())[:400]
    if not command:
        return {"ok": False, "error": "Tell the avatar what to do."}
    import llm
    prompt = (
        "You direct a 3D full-body avatar. Turn the user's command into a short JSON list of steps. "
        f"Allowed actions (pick the closest for anything else): {', '.join(CLIPS)}. "
        f"Allowed expressions: {', '.join(EXPRESSIONS)}. Allowed 'to' places: {', '.join(PLACES)} or empty "
        "('here' = where the user clicked). Walking/Running steps should have a 'to'. "
        "'say' is an optional short line the avatar speaks in first person (natural, warm, max 20 words); "
        "only add it when it fits (greeting, reaction, the user asked it to say something). "
        'Reply ONLY JSON: {"steps":[{"action":"Wave","expression":"happy","say":"Hey Pedro!","to":"","seconds":2.5}]}\n'
        f"The avatar is {'a woman' if gender == 'female' else 'a man'}. Command: {command}"
    )
    try:
        return clean_plan(llm.json_from(llm.text(prompt)))
    except Exception:
        return local_plan(command)


def translate(text: str) -> dict[str, Any]:
    text = " ".join(str(text or "").split())[:1500]
    if not text:
        return {"ok": False, "error": "Nothing to translate."}
    import llm
    prompt = ("Translate this Hindi (Devanagari or Hinglish, may mix English) into natural spoken English, "
              "keeping the tone and names. Reply with the English only.\n\n" + text)
    try:
        out = llm.text(prompt).strip().strip('"')
    except Exception as exc:
        return {"ok": False, "error": "Translation needs your free Gemini key (Settings) and internet.", "detail": str(exc)[:120]}
    return {"ok": True, "source": text, "english": out}


def tutor(question: str = "", frame: bytes | None = None) -> dict[str, Any]:
    if frame is None:
        try:
            import live_pc
            frame = live_pc.frame()
        except Exception:
            frame = None
    if not frame:
        return {"ok": False, "error": "Could not see the PC screen."}
    import llm
    q = " ".join(str(question or "").split())[:300]
    prompt = ("You are a friendly screen tutor sitting next to Pedro. Look at his PC screen. "
              + (f"He asks: {q}. Answer that. " if q else "Explain briefly what he is looking at and the single best next step. ")
              + "Speak naturally in 2-4 short sentences, no markdown, no lists.")
    try:
        return {"ok": True, "text": llm.text(prompt, [frame]).strip()}
    except Exception as exc:
        return {"ok": False, "error": "The screen tutor needs your free Gemini key (Settings) and internet.", "detail": str(exc)[:120]}


def _state() -> Path:
    base = Path(os.environ.get("STORAGE_DIR") or Path(__file__).resolve().parent / "storage")
    return base / "offline_mode.json"


def offline(on: bool | None = None) -> dict[str, Any]:
    p = _state()
    if on is None:
        try:
            on = bool(json.loads(p.read_text(encoding="utf-8")).get("on"))
        except Exception:
            on = os.environ.get("LOCAL_LLM", "").strip() == "1"
    else:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"on": bool(on)}), encoding="utf-8")
    if on:
        os.environ["LOCAL_LLM"] = "1"
    else:
        os.environ.pop("LOCAL_LLM", None)
    ready = False
    try:
        import urllib.request
        with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=1.5) as r:
            ready = r.status == 200
    except Exception:
        ready = False
    return {"ok": True, "on": bool(on), "ollama": ready,
            "note": "" if ready or not on else "Install the free Ollama app and run: ollama pull llama3.2 - until then Ped Bot can't answer offline."}
