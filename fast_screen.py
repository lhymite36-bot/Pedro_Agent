"""Fast screen-control helpers used by screen_vision.

- shrink_for_vision: downscale + JPEG before sending to Gemini (smaller upload,
  faster model response).
- pixel_changed: verify a click by a cheap thumbnail diff, not a second vision call.
- focus_cached: remembers window handles so repeated focus calls skip the
  full window enumeration.
- uia_find: finds a control by its visible name with Windows UI Automation
  (uiautomation or pywinauto, whichever is installed). Much faster and more
  exact than vision when the app exposes accessibility names.

All timings come from the `speed:` section of rules.yaml.
Tests set agent_core.uia_finder_override = fn(name, window_title) -> dict | None.
"""

from __future__ import annotations

import io
import os
import time
from typing import Any

import rules

_window_cache: dict[str, tuple[int, str, float]] = {}


def _agent() -> Any:
    import agent_core

    return agent_core


def speed(key: str) -> Any:
    return rules.speed_setting(key)


def shrink_for_vision(raw: bytes, mime: str = "image/png") -> tuple[bytes, str]:
    """Downscale to speed.vision_max_width and JPEG-compress."""
    try:
        from PIL import Image
    except ImportError:
        return raw, mime
    try:
        image = Image.open(io.BytesIO(raw))
        image.load()
    except Exception:
        return raw, mime
    width = int(speed("vision_max_width") or 1024)
    if image.width > width:
        height = max(1, round(image.height * width / image.width))
        image = image.resize((width, height), Image.BILINEAR)
    if image.mode != "RGB":
        image = image.convert("RGB")
    out = io.BytesIO()
    image.save(out, "JPEG", quality=int(speed("vision_jpeg_quality") or 60), optimize=False)
    data = out.getvalue()
    return (data, "image/jpeg") if len(data) < len(raw) or mime != "image/jpeg" else (raw, mime)


def pixel_changed(before: bytes, after: bytes) -> bool | None:
    """True when enough pixels differ between two screenshots. None if unknown."""
    if before == after:
        return False
    try:
        from PIL import Image, ImageChops
    except ImportError:
        return None
    try:
        size = (160, 90)
        a = Image.open(io.BytesIO(before)).convert("L").resize(size)
        b = Image.open(io.BytesIO(after)).convert("L").resize(size)
    except Exception:
        return True  # undecodable but different bytes
    diff = ImageChops.difference(a, b).point(lambda v: 255 if v > 24 else 0)
    changed = diff.histogram()[255] / float(size[0] * size[1])
    return changed >= float(speed("pixel_diff_threshold") or 0.002)


def focus_cached(title: str) -> dict[str, Any]:
    """Focus a window, reusing a cached handle when it is still valid."""
    agent = _agent()
    key = " ".join((title or "").split()).casefold()
    ttl = float(speed("window_cache_seconds") or 0)
    if os.name == "nt" and agent.window_override is None and key:
        import window_control

        cached = _window_cache.get(key)
        try:
            import ctypes

            if cached and time.monotonic() - cached[2] < ttl and ctypes.windll.user32.IsWindow(cached[0]):
                window_control._focus_hwnd(cached[0])
                return agent._ok(f"Brought {cached[1]} to the front.", title=cached[1], cached=True)
            matches = window_control._matching_windows(title)
            if matches:
                hwnd, shown = matches[0]
                _window_cache[key] = (hwnd, shown, time.monotonic())
                window_control._focus_hwnd(hwnd)
                return agent._ok(f"Brought {shown} to the front.", title=shown, cached=False)
        except Exception:
            pass
    return agent.TOOLS["focus_window"](window_title=title)


def clear_window_cache() -> None:
    _window_cache.clear()


def _to_grid(left: float, top: float, right: float, bottom: float) -> tuple[int, int]:
    agent = _agent()
    width, height = agent._screen_size()
    if width < 1 or height < 1:
        raise RuntimeError("Screen size unknown.")
    x = (left + right) / 2 / width * 1000
    y = (top + bottom) / 2 / height * 1000
    return int(round(min(max(x, 0), 1000))), int(round(min(max(y, 0), 1000)))


def uia_find(name: str, window_title: str = "") -> dict[str, Any] | None:
    """Find a control by name with UI Automation. Returns grid x,y or None."""
    agent = _agent()
    override = getattr(agent, "uia_finder_override", None)
    if override is not None:
        return override(name, window_title)
    if os.name != "nt" or not speed("use_ui_automation"):
        return None
    wanted = " ".join((name or "").split()).strip("'\"")
    if not wanted:
        return None
    timeout = float(speed("ui_automation_timeout_seconds") or 1.5)
    try:
        import uiautomation as auto  # type: ignore

        root = auto.GetForegroundControl() if not window_title else auto.WindowControl(
            searchDepth=1, SubName=window_title)
        control = root.Control(searchDepth=25, SubName=wanted)
        if control.Exists(maxSearchSeconds=timeout, searchIntervalSeconds=0.05):
            rect = control.BoundingRectangle
            if rect.width() > 0 and rect.height() > 0:
                x, y = _to_grid(rect.left, rect.top, rect.right, rect.bottom)
                return {"found": True, "x": x, "y": y, "label": control.Name, "via": "uiautomation"}
        return None
    except ImportError:
        pass
    except Exception:
        return None
    try:
        from pywinauto import Desktop  # type: ignore

        desk = Desktop(backend="uia")
        window = desk.window(title_re=f".*{window_title}.*") if window_title else desk.top_window()
        control = window.child_window(title_re=f"(?i).*{_re_escape(wanted)}.*", found_index=0)
        control.wait("exists", timeout=timeout, retry_interval=0.05)
        rect = control.rectangle()
        x, y = _to_grid(rect.left, rect.top, rect.right, rect.bottom)
        return {"found": True, "x": x, "y": y, "label": control.window_text(), "via": "pywinauto"}
    except Exception:
        return None


def _re_escape(text: str) -> str:
    import re

    return re.escape(text)
