"""See the screen and click things by description (Gemini vision grounding).

find_on_screen("the blue Sign in button") takes a screenshot, asks a free
Gemini vision model for the element's box on a 0-1000 grid, and returns its
centre. click_screen_target does the same, optionally focuses a window
first, clicks, and retries with a fresh screenshot when the element was not
found or the screen did not change.

Tests set agent_core.vision_locator_override = fn(image_bytes, mime, description)
-> {"found": bool, "x": int, "y": int, "label": str}.
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any

import fast_screen

_PROMPT = (
    "You are a precise UI locator. Find this element on the screenshot: {target}\n"
    'Reply with JSON only: {{"found": true|false, "box_2d": [ymin, xmin, ymax, xmax], '
    '"label": "short visible text"}}. Coordinates are 0-1000 over the full image.'
)


def _agent() -> Any:
    import agent_core

    return agent_core


def _parse(text: str) -> dict[str, Any]:
    match = re.search(r"\{.*\}", text or "", re.S)
    if not match:
        return {"found": False}
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return {"found": False}
    box = data.get("box_2d")
    if data.get("found") and isinstance(box, list) and len(box) == 4:
        ymin, xmin, ymax, xmax = (float(v) for v in box)
        data["x"] = int(round((xmin + xmax) / 2))
        data["y"] = int(round((ymin + ymax) / 2))
    else:
        data["found"] = False
    return data


def _vision_models() -> list[str]:
    agent = _agent()
    first = str(fast_screen.speed("vision_model") or "").strip()
    order = [first] if first else []
    for name in agent.model_candidates():
        if name not in order:
            order.append(name)
    # flash-lite models answer fastest; try them first.
    return sorted(order, key=lambda n: (0 if n == first else 1 if "lite" in n else 2))


def _ask_gemini(image: bytes, mime: str, description: str) -> dict[str, Any]:
    agent = _agent()
    image, mime = fast_screen.shrink_for_vision(image, mime)
    override = getattr(agent, "vision_locator_override", None)
    if override is not None:
        return override(image, mime, description)
    from google import genai
    from google.genai import types

    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("GEMINI_API_KEY is not set.")
    client = _client(key)
    last: Exception | None = None
    for model in _vision_models():
        try:
            config: dict[str, Any] = {"temperature": 0, "max_output_tokens": 120}
            try:
                config["thinking_config"] = types.ThinkingConfig(thinking_budget=0)
            except Exception:
                pass
            response = client.models.generate_content(
                model=model,
                contents=[
                    types.Part.from_bytes(data=image, mime_type=mime),
                    _PROMPT.format(target=description),
                ],
                config=types.GenerateContentConfig(**config),
            )
            return _parse(getattr(response, "text", "") or "")
        except Exception as exc:  # quota or unsupported option -> next model
            last = exc
            if not (agent._is_daily_quota(exc) or "thinking" in str(exc).casefold() or "404" in str(exc)):
                raise
    raise RuntimeError(f"All vision models failed: {last}")


_clients: dict[str, Any] = {}


def _client(key: str) -> Any:
    """Reuse one Gemini client (saves a TLS handshake per click)."""
    if key not in _clients:
        from google import genai

        _clients[key] = genai.Client(api_key=key)
    return _clients[key]


def _shot() -> tuple[bytes, str]:
    shot = _agent().take_screenshot()
    if not shot.get("ok"):
        raise RuntimeError(shot.get("error") or "Screenshot failed.")
    return shot["_screenshot_bytes"], shot.get("_screenshot_mime", "image/jpeg")


_FILLER = re.compile(r"^(the|a|an)\s+|\s+(button|link|tab|icon|field|box|menu|item|option|checkbox)$", re.I)


def control_name_from(description: str) -> str:
    """'the blue Sign in button' -> 'blue Sign in' -> tried as-is by UIA."""
    text = " ".join(str(description or "").split()).strip("'\"")
    quoted = re.findall(r"['\"]([^'\"]+)['\"]", str(description or ""))
    if quoted:
        return quoted[0]
    previous = None
    while previous != text:
        previous = text
        text = _FILLER.sub("", text).strip()
    return text


def _locate(description: str, control_name: str, window_title: str) -> dict[str, Any]:
    """UI Automation by name first (fast, exact), then vision."""
    names = [n for n in dict.fromkeys([control_name, control_name_from(description)]) if n]
    for name in names:
        found = fast_screen.uia_find(name, window_title)
        if found and found.get("found"):
            return found
    image, mime = _shot()
    found = _ask_gemini(image, mime, description)
    found["via"] = found.get("via", "vision")
    found["_before"] = image
    return found


def find_on_screen(description: str, control_name: str = "", window_title: str = "") -> dict[str, Any]:
    agent = _agent()
    text = " ".join(str(description or "").split())
    if not text:
        return agent._err("Describe what to find, e.g. 'the Sign in button'.")
    started = time.monotonic()
    try:
        found = _locate(text, control_name, window_title)
    except Exception as exc:
        return agent._err(f"find_on_screen failed: {exc}")
    if not found.get("found"):
        return agent._err(f"Could not see '{text}' on the screen.", found=False)
    return agent._ok(
        f"Found '{text}' at grid {found['x']},{found['y']} via {found.get('via')}.",
        found=True, x=found["x"], y=found["y"], label=found.get("label", ""),
        via=found.get("via"), ms=int((time.monotonic() - started) * 1000),
    )


def click_screen_target(
    description: str,
    window_title: str = "",
    double_click: bool = False,
    retries: Any = None,
    control_name: str = "",
) -> dict[str, Any]:
    agent = _agent()
    text = " ".join(str(description or "").split())
    if not text:
        return agent._err("Describe what to click.")
    if retries is None:
        retries = fast_screen.speed("retries")
    try:
        attempts = max(1, min(int(retries) + 1, 5))
    except (TypeError, ValueError):
        attempts = 2
    settle = float(fast_screen.speed("settle_seconds") or 0)
    retry_wait = float(fast_screen.speed("retry_wait_seconds") or 0)
    started = time.monotonic()
    if window_title:
        focused = fast_screen.focus_cached(window_title)
        if not focused.get("ok"):
            return agent._err(f"Could not focus '{window_title}': {focused.get('error')}")
        time.sleep(settle)
    last_error = ""
    import bot_mind

    if bot_mind.bot_id():
        place = bot_mind.lookup(text)
        if place is not None and place.get("grid_x") is not None and place.get("grid_y") is not None:
            token = bot_mind.bind_target(text, trusted=True)
            try:
                clicked = agent.click_element(
                    place["grid_x"], place["grid_y"], clicks=2 if double_click else 1
                )
            finally:
                bot_mind.unbind_target(token)
            if clicked.get("ok"):
                return agent._ok(
                    f"Clicked the saved place '{place.get('name') or text}'. {clicked.get('mind') or ''}".strip(),
                    x=place["grid_x"], y=place["grid_y"], attempts=1, via="map",
                    ms=int((time.monotonic() - started) * 1000),
                )
    for attempt in range(1, attempts + 1):
        try:
            found = _locate(text, control_name, window_title)
        except Exception as exc:
            last_error = str(exc)
            time.sleep(retry_wait)
            continue
        if not found.get("found"):
            last_error = f"'{text}' not visible"
            time.sleep(retry_wait)
            continue
        before = found.pop("_before", None)
        if before is None:
            try:
                before, _ = _shot()
            except Exception:
                before = None
        token = bot_mind.bind_target(text, trusted=False)
        try:
            clicked = agent.click_element(found["x"], found["y"], clicks=2 if double_click else 1)
        finally:
            bot_mind.unbind_target(token)
        if not clicked.get("ok"):
            last_error = clicked.get("error", "click failed")
            folded = last_error.casefold()
            if "judge said no" in folded or "reply yes" in folded or "other plan" in folded:
                return agent._err(last_error)
            continue
        time.sleep(settle)
        changed = None
        if before is not None:
            try:
                after, _ = _shot()
                changed = fast_screen.pixel_changed(before, after)
            except Exception:
                pass
        if bot_mind.bot_id():
            bot_mind.remember_place(text, grid_x=int(found["x"]), grid_y=int(found["y"]), screen=bot_mind.screen_text())
        mind = str(clicked.get("mind") or "")
        message = f"Clicked '{text}' at grid {found['x']},{found['y']} via {found.get('via')} (attempt {attempt})."
        if mind:
            message = f"{message} {mind}"
        return agent._ok(
            message,
            x=found["x"], y=found["y"], attempts=attempt, screen_changed=changed,
            via=found.get("via"), ms=int((time.monotonic() - started) * 1000),
        )
    return agent._err(f"click_screen_target failed after {attempts} tries: {last_error}")
