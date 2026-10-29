"""1.6.0 Smart brain: pick the smartest free Gemini model the key really supports.

Free tier (ai.google.dev pricing, Oct 2026): gemini-3.8-flash (smartest, ~20 requests/day),
gemini-3.6-flash, gemini-3.5-flash-lite, gemini-3.1-flash-lite, gemma-4-31b-it.
Pro models (gemini-3.1-pro-preview, gemini-4-argon) are paid only, so they are never picked.
Google Search grounding is not on the free tier; bots use the free web_search tool instead.

- discover(): GET /v1beta/models once per 12 h (cached on disk) so retired or unknown ids are skipped.
- order_for_turn(): hard turns start on gemini-3.8-flash while its daily budget lasts, the rest on 3.6-flash.
- thinking_level(): high for hard turns, medium for normal ones, minimal for voice.
"""

from __future__ import annotations

import json
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

TOP = "gemini-3.8-flash"          # smartest free model; small daily quota
MAIN = "gemini-3.6-flash"         # strong free workhorse
CHAIN = (TOP, MAIN, "gemini-3-flash-preview", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemma-4-31b-it")
RETIRED = re.compile(r"^gemini-(1\.|2\.0|2\.5|3-pro-preview|3\.1-flash-lite-preview)")
PAID_ONLY = re.compile(r"(pro-preview|argon|-pro$|image|omni|banana)")
TOP_DAILY_BUDGET = 18             # leave 2 of the ~20 free requests as headroom
LIST_TTL = 12 * 3600

_lock = threading.Lock()
_available: list[str] | None = None
_HARD = re.compile(
    r"\b(build|make|create|code|program|script|app|fix|debug|plan|design|analy[sz]e|compare|research|"
    r"explain why|why does|how (do|can|should)|step[- ]by[- ]step|write (a|an|the)|essay|report|strategy|"
    r"optimi[sz]e|calculate|solve|prove|figure out|automate|workflow|organi[sz]e|summari[sz]e)\b", re.I)


def _storage() -> Path:
    try:
        import agent_config
        return Path(agent_config.storage_dir())
    except Exception:
        return Path.home() / ".pedbot"


def _pacific_day() -> str:
    # Free quotas reset at midnight US Pacific time.
    return (datetime.now(timezone.utc) - timedelta(hours=8)).strftime("%Y-%m-%d")


def _budget_file() -> Path:
    return _storage() / "brain_budget.json"


def _read_budget() -> dict[str, Any]:
    try:
        data = json.loads(_budget_file().read_text(encoding="utf-8"))
        if data.get("day") == _pacific_day():
            return data
    except Exception:
        pass
    return {"day": _pacific_day(), "used": {}}


def note_call(model: str) -> None:
    with _lock:
        data = _read_budget()
        data["used"][model] = int(data["used"].get(model, 0)) + 1
        try:
            _budget_file().parent.mkdir(parents=True, exist_ok=True)
            _budget_file().write_text(json.dumps(data), encoding="utf-8")
        except Exception:
            pass


def used_today(model: str) -> int:
    return int(_read_budget()["used"].get(model, 0))


def top_left() -> int:
    try:
        import rules
        cap = int(rules.agent_setting("top_model_daily_budget", TOP_DAILY_BUDGET))
    except Exception:
        cap = TOP_DAILY_BUDGET
    return max(0, cap - used_today(TOP))


def usable(name: str) -> bool:
    n = str(name or "").strip()
    return bool(n) and not RETIRED.match(n) and not PAID_ONLY.search(n)


def parse_list(body: Any) -> list[str]:
    try:
        data = json.loads(body) if isinstance(body, (str, bytes)) else (body or {})
    except Exception:
        return []
    out = []
    for m in data.get("models", []) or []:
        if "generateContent" not in (m.get("supportedGenerationMethods") or []):
            continue
        out.append(str(m.get("name", "")).replace("models/", ""))
    return out


def discover(key: str | None, fetch: Any = None) -> list[str]:
    """Model ids this key can call (cached 12 h). Empty list = unknown (use the built-in chain)."""
    global _available
    if _available is not None:
        return _available
    cache = _storage() / "brain_models.json"
    try:
        c = json.loads(cache.read_text(encoding="utf-8"))
        if time.time() - float(c.get("at", 0)) < LIST_TTL and c.get("models"):
            _available = list(c["models"])
            return _available
    except Exception:
        pass
    if not key:
        return []
    try:
        if fetch is None:
            import requests
            r = requests.get("https://generativelanguage.googleapis.com/v1beta/models",
                             params={"pageSize": 200}, headers={"x-goog-api-key": key}, timeout=8)
            if r.status_code != 200:
                return []
            body = r.text
        else:
            body = fetch()
        ids = parse_list(body)
        if ids:
            _available = ids
            try:
                cache.parent.mkdir(parents=True, exist_ok=True)
                cache.write_text(json.dumps({"at": time.time(), "models": ids}), encoding="utf-8")
            except Exception:
                pass
        return ids
    except Exception:
        return []


def reset_cache() -> None:
    global _available
    _available = None


def is_hard(text: str) -> bool:
    t = str(text or "")
    if len(t) > 280 or t.count("\n") >= 3:
        return True
    return bool(_HARD.search(t)) and len(t) > 25


def chain(extra: Iterable[str] = (), available: list[str] | None = None) -> list[str]:
    """Built-in smart chain, then the user's models, filtered to what the key supports."""
    names: list[str] = []
    for n in [*CHAIN, *extra]:
        n = str(n or "").strip()
        if usable(n) and n not in names:
            names.append(n)
    if available:
        known = set(available)
        kept = [n for n in names if n in known]
        # newest unknown flash models Google adds later still get used
        for n in sorted(available, reverse=True):
            if usable(n) and re.fullmatch(r"gemini-\d+(\.\d+)?-flash(-lite)?", n) and n not in kept:
                kept.append(n)
        names = kept or names
    return names


def order_for_turn(order: list[str], text: str, round_no: int) -> list[str]:
    """Hard request + first two rounds (planning) -> TOP first while budget lasts. Otherwise MAIN first."""
    names = list(order)
    want_top = is_hard(text) and round_no < 2 and top_left() > 0 and TOP in names
    first = TOP if want_top else (MAIN if MAIN in names else None)
    if first:
        names.remove(first)
        names.insert(0, first)
    if not want_top and TOP in names and names[0] != TOP:
        names.remove(TOP)
        names.append(TOP) if top_left() > 0 else None
    return names


def thinking_level(model: str, text: str, voice: bool) -> str:
    if voice or "gemma" in model:
        return "minimal"
    if is_hard(text):
        return "high"
    return "medium" if "lite" not in model else "low"
