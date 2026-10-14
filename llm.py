"""One-shot Gemini calls for Stage 2 modules (planner, reviewer, vision
summaries, code edits, upgrade proposals).

Tests set `llm.override = fn(prompt, images) -> str` so nothing goes online.
Model fallback follows agent.models in rules.yaml.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Callable

override: Callable[[str, list[bytes]], str] | None = None


def _models() -> list[str]:
    import rules

    models = [str(m) for m in (rules.agent_setting("models", []) or []) if str(m).strip()]
    env = os.environ.get("GEMINI_MODEL", "").strip()
    return ([env] if env else []) + [m for m in models if m != env] or ["gemini-3.5-flash-lite"]


def text(prompt: str, images: list[bytes] | None = None, *, model: str | None = None) -> str:
    """Return the model's text. Images are JPEG/PNG bytes (vision)."""
    images = list(images or [])
    if override is not None:
        return str(override(prompt, images) or "")
    import agent_core

    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("GEMINI_API_KEY is not set.")
    from google import genai
    from google.genai import types

    client = agent_core.genai_client_override(key) if agent_core.genai_client_override else genai.Client(api_key=key)
    parts: list[Any] = [prompt]
    for blob in images:
        mime = "image/png" if blob[:4] == b"\x89PNG" else "image/jpeg"
        parts.append(types.Part.from_bytes(data=blob, mime_type=mime))
    last: Exception | None = None
    for name in ([model] if model else _models()):
        try:
            response = client.models.generate_content(model=name, contents=parts)
            return getattr(response, "text", None) or agent_core._text_from(response)
        except Exception as exc:  # quota or unknown model: try the next one
            last = exc
    raise RuntimeError(f"Gemini call failed: {last}")


def strip_fence(value: str) -> str:
    match = re.search(r"```[a-zA-Z0-9_+-]*\n(.*?)```", value or "", re.S)
    return (match.group(1) if match else value or "").strip()


def json_from(value: str) -> Any:
    """Parse the first JSON object/array in a model reply."""
    body = strip_fence(value)
    for opener, closer in (("{", "}"), ("[", "]")):
        start, end = body.find(opener), body.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(body[start:end + 1])
            except json.JSONDecodeError:
                continue
    raise ValueError("The model did not return JSON.")


def read_bytes(path: Path) -> bytes:
    return Path(path).read_bytes()
