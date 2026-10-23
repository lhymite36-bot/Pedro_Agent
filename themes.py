"""Look-and-feel theme (Liquid Glass presets + Custom), shared by the PC app and the phone."""
from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from typing import Any

PRESETS = ("grokDark", "grokLight", "aurora", "midnight", "crimson", "emerald", "sunset", "ocean", "graphite", "lavender", "goldnoir", "neon", "custom")
WALLPAPERS = ("aurora", "nebula", "dusk", "deep", "plain")
DEFAULT = {"preset": "aurora", "custom": {"accent": "#8fa6ff", "wallpaper": "aurora", "blur": 26, "alpha": 46}}
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
_lock = threading.Lock()


def _path() -> Path:
    import agent_config
    return agent_config.storage_dir() / "theme.json"


def clean(data: dict[str, Any] | None) -> dict[str, Any]:
    data = data or {}
    preset = str(data.get("preset") or "aurora")
    c = data.get("custom") if isinstance(data.get("custom"), dict) else {}
    accent = str(c.get("accent") or DEFAULT["custom"]["accent"])
    wall = str(c.get("wallpaper") or "aurora")

    def num(v: Any, lo: int, hi: int, d: int) -> int:
        try:
            return max(lo, min(hi, int(float(v))))
        except (TypeError, ValueError):
            return d
    return {"preset": preset if preset in PRESETS else "aurora",
            "custom": {"accent": accent if _HEX.match(accent) else DEFAULT["custom"]["accent"],
                       "wallpaper": wall if wall in WALLPAPERS else "aurora",
                       "blur": num(c.get("blur"), 0, 60, 26), "alpha": num(c.get("alpha"), 15, 95, 46)}}


def get() -> dict[str, Any]:
    try:
        return clean(json.loads(_path().read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return clean(DEFAULT)


def save(data: dict[str, Any]) -> dict[str, Any]:
    theme = clean(data)
    with _lock:
        p = _path(); p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(theme, indent=1), encoding="utf-8")
    try:
        import live_sync
        live_sync.notify("theme", theme=theme)      # PC window and phone switch together
    except Exception:
        pass
    return {"ok": True, "theme": theme}
