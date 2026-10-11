"""Instant pointer actions for the desktop agent.

The model sends coordinates on a 0-1000 grid. This module converts them with
the physical screen size from pyautogui, which matches the screenshot after
Windows DPI awareness is enabled. Clicks do not glide.
"""

from __future__ import annotations

import ctypes
import re
import sys
from typing import Any

GRID = 1000
PAUSE_SECONDS = 0

_NAV_KEYS = {
    "tab",
    "enter",
    "esc",
    "backspace",
    "delete",
    "up",
    "down",
    "left",
    "right",
    "home",
    "end",
    "space",
    "pageup",
    "pagedown",
}
_MODIFIERS = {"ctrl", "alt", "shift"}
_KEY_ALIASES = {
    "return": "enter",
    "escape": "esc",
    "control": "ctrl",
    "pgup": "pageup",
    "pgdn": "pagedown",
}
_MAX_KEY_STEPS = 8


def enable_windows_dpi_awareness() -> None:
    """Make this process use physical pixels on each monitor.

    SetProcessDPIAware is the fallback when the per-monitor API is missing.
    """
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            return


enable_windows_dpi_awareness()


def configure_desktop(desktop: Any) -> Any:
    """Turn on the corner failsafe and do not pause between pointer actions."""
    desktop.FAILSAFE = True
    desktop.PAUSE = PAUSE_SECONDS
    return desktop


def norm_to_pixel(
    norm_x: float,
    norm_y: float,
    screen_width: int,
    screen_height: int,
) -> tuple[int, int]:
    """Map a 0-1000 point onto physical pixels from pyautogui.size()."""
    actual_x = int(norm_x * screen_width / GRID)
    actual_y = int(norm_y * screen_height / GRID)
    if screen_width > 0:
        actual_x = min(max(actual_x, 0), screen_width - 1)
    if screen_height > 0:
        actual_y = min(max(actual_y, 0), screen_height - 1)
    return actual_x, actual_y


def align_to_screen(image: Any, screen_width: int, screen_height: int) -> Any:
    """Resize a grab so its pixels match pyautogui.size()."""
    if screen_width < 1 or screen_height < 1:
        return image
    if image.size == (screen_width, screen_height):
        return image
    return image.resize((screen_width, screen_height))


def instant_click(desktop: Any, x: int, y: int, clicks: int, button: str) -> None:
    """Move to the pixel and click in one call. No duration, so there is no glide."""
    desktop.click(x, y, clicks=clicks, button=button)


def _normalize_key(token: str) -> str:
    name = _KEY_ALIASES.get(token, token)
    if name in _MODIFIERS or name in _NAV_KEYS:
        return name
    if re.fullmatch(r"f([1-9]|1[0-2])", name):
        return name
    if re.fullmatch(r"[a-z0-9]", name):
        return name
    raise ValueError(f'Unknown key "{token}".')


def parse_key_steps(keys: str) -> list[list[str]]:
    """Parse tab, enter, or a shortcut such as ctrl+l.

    A step is one navigation key, or modifiers plus one key. Bare letters are
    refused so this cannot type a password.
    """
    text = " ".join((keys or "").split()).casefold()
    if not text:
        raise ValueError("keys is required.")
    parts = [part.strip() for part in re.split(r"[,;]+", text) if part.strip()]
    if len(parts) > _MAX_KEY_STEPS:
        raise ValueError(f"At most {_MAX_KEY_STEPS} key steps are allowed.")
    steps: list[list[str]] = []
    for part in parts:
        tokens = [_normalize_key(token) for token in re.split(r"[+\s]+", part) if token]
        if not tokens:
            raise ValueError("keys is required.")
        modifiers = tokens[:-1]
        last = tokens[-1]
        if any(token not in _MODIFIERS for token in modifiers):
            raise ValueError("Only ctrl, alt, and shift can modify a key.")
        if len(set(modifiers)) != len(modifiers):
            raise ValueError("A shortcut cannot repeat a modifier.")
        if not modifiers:
            if last not in _NAV_KEYS:
                raise ValueError(
                    "Use tab, enter, arrows, or a shortcut such as ctrl+l."
                )
        elif last in _MODIFIERS:
            raise ValueError("A shortcut needs a key after the modifier.")
        steps.append([*modifiers, last])
    return steps


def press_key_steps(desktop: Any, steps: list[list[str]]) -> None:
    """Press each shortcut immediately. A single key uses press, a chord uses hotkey."""
    for step in steps:
        if len(step) == 1:
            desktop.press(step[0])
        else:
            desktop.hotkey(*step)
