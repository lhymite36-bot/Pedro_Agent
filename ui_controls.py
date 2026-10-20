"""Look before acting, then check it landed. Works for every Windows app and browser window.

ui_read   - the named controls in a window (Windows UI Automation). Much faster and
            more exact than a screenshot, and it is what the bot must base a click on.
ui_find   - controls whose name matches.
ui_click  - click one control found by name, then re-read it and the window to say
            what actually changed. Nothing changed = not done (no guessing).
ui_set_text - put a value into a field (not just click it), read the field back,
            retry another way on a mismatch, and report the value that is there now.

Password fields are never typed into. Buttons that delete, pay, send or post ask
the user first (rules.py ui_click categories). Tests set tree_override.
"""

from __future__ import annotations

import re
import time
from typing import Any, Callable, Iterable

# Tests: (window_title) -> root node with .name .control_type .value() .enabled .children()
# .invoke() .set_text(str) .type_text(str) .is_password .toggle_state() .selected()
tree_override: Callable[[str], Any] | None = None
sleep: Callable[[float], None] = time.sleep

_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}
CACHE_SECONDS = 1.5
MAX_NODES = 1500
_ACT_TYPES = {"Button", "MenuItem", "Hyperlink", "TabItem", "ListItem", "TreeItem", "CheckBox",
              "RadioButton", "ComboBox", "SplitButton", "Edit", "Document", "DataItem", "Text"}


def _ok(message: str, **extra: Any) -> dict[str, Any]:
    return {"ok": True, "message": message, **extra}


def _err(message: str, **extra: Any) -> dict[str, Any]:
    return {"ok": False, "error": message, **extra}


# ---------------------------------------------------------------- real backend
class _Uia:
    """pywinauto wrapper with the small interface the tests fake."""

    def __init__(self, wrapper: Any) -> None:
        self.w = wrapper
        info = getattr(wrapper, "element_info", None)
        self.name = str(getattr(info, "name", "") or "")
        self.control_type = str(getattr(info, "control_type", "") or "")
        self.automation_id = str(getattr(info, "automation_id", "") or "")
        try:
            self.enabled = bool(wrapper.is_enabled())
        except Exception:
            self.enabled = True
        try:
            self.is_password = bool(getattr(info.element, "CurrentIsPassword", False))
        except Exception:
            self.is_password = False

    def children(self) -> list["_Uia"]:
        try:
            return [_Uia(c) for c in self.w.children()]
        except Exception:
            return []

    def value(self) -> str:
        for getter in ("get_value", "window_text"):
            try:
                got = getattr(self.w, getter)()
                if got is not None:
                    return str(got)
            except Exception:
                continue
        return ""

    def toggle_state(self) -> Any:
        try:
            return self.w.get_toggle_state()
        except Exception:
            return None

    def selected(self) -> Any:
        try:
            return self.w.is_selected()
        except Exception:
            return None

    def invoke(self) -> None:
        try:
            self.w.invoke()
            return
        except Exception:
            pass
        self.w.click_input()

    def set_text(self, text: str) -> None:
        self.w.set_edit_text(text)

    def type_text(self, text: str) -> None:
        self.w.set_focus()
        self.w.type_keys("^a{BACKSPACE}", set_foreground=True)
        self.w.type_keys(text, with_spaces=True, with_tabs=True, with_newlines=True, pause=0.01)


def _root(window_title: str) -> Any:
    if tree_override is not None:
        return tree_override(window_title)
    from pywinauto import Desktop  # type: ignore

    desk = Desktop(backend="uia")
    want = " ".join((window_title or "").split())
    if want:
        win = desk.window(title_re=f"(?i).*{re.escape(want)}.*", visible_only=True)
        return _Uia(win.wrapper_object())
    for w in desk.windows(visible_only=True):
        try:
            if w.has_keyboard_focus() or w.is_active():
                return _Uia(w)
        except Exception:
            continue
    wins = desk.windows(visible_only=True)
    if not wins:
        raise RuntimeError("No open window.")
    return _Uia(wins[0])


# ---------------------------------------------------------------- tree helpers
def _walk(node: Any, path: str = "", out: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    out = [] if out is None else out
    stack: list[tuple[Any, str, int]] = [(node, path, 0)]
    while stack and len(out) < MAX_NODES:
        cur, where, depth = stack.pop(0)
        name = " ".join(str(getattr(cur, "name", "") or "").split())
        kind = str(getattr(cur, "control_type", "") or "")
        out.append({"node": cur, "name": name, "type": kind, "path": where, "depth": depth,
                    "enabled": bool(getattr(cur, "enabled", True))})
        if depth < 40:
            for i, child in enumerate(cur.children() if hasattr(cur, "children") else []):
                stack.append((child, f"{where}/{i}", depth + 1))
    return out


def _nodes(window_title: str, fresh: bool = False) -> list[dict[str, Any]]:
    key = (window_title or "").casefold()
    hit = _CACHE.get(key)
    if hit and not fresh and time.monotonic() - hit[0] < CACHE_SECONDS:
        return hit[1]
    rows = _walk(_root(window_title))
    _CACHE[key] = (time.monotonic(), rows)
    return rows


def clear_cache() -> None:
    _CACHE.clear()


def _fold(text: str) -> str:
    return " ".join(str(text or "").casefold().replace("&", "").split())


def _matches(rows: Iterable[dict[str, Any]], name: str, control_type: str = "") -> list[dict[str, Any]]:
    want, kind = _fold(name), _fold(control_type)
    rows = [r for r in rows if r["name"] and (not kind or _fold(r["type"]) == kind)]
    exact = [r for r in rows if _fold(r["name"]) == want]
    if exact:
        return exact
    starts = [r for r in rows if _fold(r["name"]).startswith(want)]
    if starts:
        return starts
    return [r for r in rows if want and want in _fold(r["name"])]


def _value(row: dict[str, Any]) -> str:
    try:
        return str(row["node"].value() or "")
    except Exception:
        return ""


def _state(row: dict[str, Any]) -> tuple[Any, ...]:
    node = row["node"]
    toggle = node.toggle_state() if hasattr(node, "toggle_state") else None
    sel = node.selected() if hasattr(node, "selected") else None
    return (_value(row), toggle, sel)


def _shown(rows: list[dict[str, Any]]) -> set[tuple[str, str]]:
    return {(r["type"], r["name"]) for r in rows if r["name"]}


def _describe(row: dict[str, Any]) -> dict[str, Any]:
    out = {"name": row["name"][:120], "type": row["type"]}
    value = _value(row)
    if value and value != row["name"] and row["type"] in {"Edit", "ComboBox", "Document", "Spinner", "Slider"}:
        out["value"] = value[:200]
    if not row["enabled"]:
        out["enabled"] = False
    return out


def _secretish(row: dict[str, Any]) -> bool:
    node = row["node"]
    if bool(getattr(node, "is_password", False)):
        return True
    return bool(re.search(r"pass(word|code)|\bpin\b|\bcvv\b|\bcvc\b|card number|\botp\b|one.time code",
                          row["name"], re.I))


# ---------------------------------------------------------------- tools
def ui_read(window_title: str = "", only: str = "", limit: int = 150) -> dict[str, Any]:
    """Named, usable controls in a window, top to bottom. Use this before acting."""
    try:
        rows = _nodes(window_title, fresh=True)
    except Exception as exc:
        return _err(f"Could not read that window: {exc}")
    kind = _fold(only)
    shown = [r for r in rows if r["name"] and (r["type"] in _ACT_TYPES or r["depth"] <= 1)
             and (not kind or _fold(r["type"]) == kind)]
    items = [_describe(r) for r in shown[: max(1, min(int(limit or 150), 400))]]
    title = rows[0]["name"] if rows else ""
    return _ok(f"Window '{title}': {len(items)} named controls (of {len(rows)} in the tree).",
               window=title, controls=items)


def ui_find(name: str, window_title: str = "", control_type: str = "") -> dict[str, Any]:
    if not str(name or "").strip():
        return _err("Say the control's name, as shown on screen.")
    try:
        rows = _nodes(window_title)
    except Exception as exc:
        return _err(f"Could not read that window: {exc}")
    found = _matches(rows, name, control_type)
    if not found:
        return _err(f"No control named '{name}' is on screen. Do not click a guess.",
                    nearby=_nearby(rows, name))
    return _ok(f"{len(found)} control(s) named like '{name}'.", matches=[_describe(r) for r in found[:20]])


def _nearby(rows: list[dict[str, Any]], name: str) -> list[str]:
    import difflib

    names = sorted({r["name"] for r in rows if r["name"] and r["type"] in _ACT_TYPES})
    return difflib.get_close_matches(name, names, n=8, cutoff=0.3) or names[:12]


def _pick(rows: list[dict[str, Any]], name: str, control_type: str, index: int) -> dict[str, Any] | str:
    found = _matches(rows, name, control_type)
    if not found:
        return f"No control named '{name}' is on screen. Do not click a guess."
    if len(found) > 1 and not index:
        return "ambiguous"
    pos = (int(index) - 1) if index else 0
    if pos < 0 or pos >= len(found):
        return f"There are {len(found)} matches; index must be 1 to {len(found)}."
    return found[pos]


def _wait_change(window_title: str, target: dict[str, Any], before_state: tuple[Any, ...],
                 before_shown: set[tuple[str, str]], timeout: float) -> tuple[list[dict[str, Any]], list[str]]:
    """Poll the window (short, cheap) until something visibly changes."""
    end = time.monotonic() + max(0.1, timeout)
    changes: list[str] = []
    rows: list[dict[str, Any]] = []
    while True:
        try:
            rows = _nodes(window_title, fresh=True)
        except Exception:
            rows = []
        try:
            after_state = _state(target)
        except Exception:
            after_state = before_state
        if after_state != before_state:
            labels = ("value", "check state", "selection")
            for label, a, b in zip(labels, before_state, after_state):
                if a != b:
                    changes.append(f"{label}: {str(a)[:60]!r} -> {str(b)[:60]!r}")
        now_shown = _shown(rows)
        added = sorted(n for _t, n in now_shown - before_shown)[:6]
        gone = sorted(n for _t, n in before_shown - now_shown)[:6]
        if added:
            changes.append("now showing: " + ", ".join(added))
        if gone:
            changes.append("no longer showing: " + ", ".join(gone))
        if changes or time.monotonic() >= end:
            return rows, changes
        sleep(0.12)


def ui_click(name: str, window_title: str = "", control_type: str = "", index: int = 0,
             wait_seconds: float = 2.0) -> dict[str, Any]:
    """Click a control found by its name, then report what changed. Nothing changed = not done."""
    if not str(name or "").strip():
        return _err("Say the control's name, as shown on screen.")
    try:
        rows = _nodes(window_title, fresh=True)
    except Exception as exc:
        return _err(f"Could not read that window: {exc}")
    picked = _pick(rows, name, control_type, index)
    if picked == "ambiguous":
        found = _matches(rows, name, control_type)
        return _err(f"{len(found)} controls are named like '{name}'. Ask the user which one, or pass index.",
                    needs_choice=True, matches=[_describe(r) for r in found[:12]])
    if isinstance(picked, str):
        return _err(picked, nearby=_nearby(rows, name))
    if not picked["enabled"]:
        return _err(f"'{picked['name']}' is greyed out, so it cannot be clicked yet.", control=_describe(picked))
    before_state, before_shown = _state(picked), _shown(rows)
    try:
        picked["node"].invoke()
    except Exception as exc:
        return _err(f"Clicking '{picked['name']}' failed: {exc}")
    _rows, changes = _wait_change(window_title, picked, before_state, before_shown, wait_seconds)
    if not changes:
        return _err(f"Clicked '{picked['name']}', but nothing on screen changed. Not done. "
                    "Read the window again and try a different control.", verified=False,
                    control=_describe(picked))
    return _ok(f"Clicked '{picked['name']}' ({picked['type']}). Checked: " + "; ".join(changes[:4]),
               verified=True, changed=changes[:8], control=_describe(picked))


def ui_set_text(name: str, text: str, window_title: str = "", control_type: str = "Edit",
                index: int = 0) -> dict[str, Any]:
    """Put text into a field found by name, read it back, retry another way on a mismatch."""
    try:
        rows = _nodes(window_title, fresh=True)
    except Exception as exc:
        return _err(f"Could not read that window: {exc}")
    picked = _pick(rows, name, control_type, index)
    if picked == "ambiguous":
        found = _matches(rows, name, control_type)
        return _err(f"{len(found)} fields are named like '{name}'. Ask the user which one, or pass index.",
                    needs_choice=True, matches=[_describe(r) for r in found[:12]])
    if isinstance(picked, str) and control_type:
        picked = _pick(rows, name, "", index)
    if isinstance(picked, str):
        return _err(picked if picked != "ambiguous" else f"Several fields match '{name}'.", nearby=_nearby(rows, name))
    if _secretish(picked):
        return _err("That is a password, PIN, card or code field. The user types it themselves.", blocked=True)
    want = str(text or "")
    before = _value(picked)
    tried: list[str] = []
    for method in ("set_text", "type_text"):
        node = picked["node"]
        if not hasattr(node, method):
            continue
        try:
            getattr(node, method)(want)
            tried.append(method)
        except Exception as exc:
            tried.append(f"{method} failed: {exc}")
            continue
        end = time.monotonic() + 1.0
        got = _value(picked)
        while _norm(got) != _norm(want) and time.monotonic() < end:
            sleep(0.1)
            got = _value(picked)
        if _norm(got) == _norm(want):
            clear_cache()
            return _ok(f"'{picked['name']}' now reads {got[:120]!r} (was {before[:60]!r}). Checked by reading it back.",
                       verified=True, before=before[:200], after=got[:200], method=method)
    got = _value(picked)
    return _err(f"Typed into '{picked['name']}', but it reads {got[:120]!r}, not {want[:120]!r}. Not done.",
                verified=False, before=before[:200], after=got[:200], tried=tried)


def _norm(text: str) -> str:
    return " ".join(str(text or "").replace("\r", "").split())


DECLARATIONS = [
    {"name": "ui_read",
     "description": ("Read the named buttons, fields, menus, tabs and links in a window (any app, File Explorer, "
                     "Settings, or a browser page) with Windows UI Automation. Fast and exact. Use it BEFORE "
                     "acting and act only on controls it lists. Prefer it over a screenshot."),
     "parameters": {"type": "object", "properties": {
         "window_title": {"type": "string", "description": "Part of the window title. Empty = the active window."},
         "only": {"type": "string", "description": "Optional control type, e.g. Button or Edit."},
         "limit": {"type": "integer"}}}},
    {"name": "ui_find",
     "description": "Find controls by the name shown on screen. Returns matches or close names. Never click a guess.",
     "parameters": {"type": "object", "properties": {
         "name": {"type": "string"}, "window_title": {"type": "string"}, "control_type": {"type": "string"}},
         "required": ["name"]}},
    {"name": "ui_click",
     "description": ("Click a control by its on-screen name (any app or browser window), then re-read the window "
                     "and report what changed. If it says nothing changed, the step is NOT done: read again and "
                     "try another control or ask the user."),
     "parameters": {"type": "object", "properties": {
         "name": {"type": "string"}, "window_title": {"type": "string"}, "control_type": {"type": "string"},
         "index": {"type": "integer", "description": "1-based, when several controls share the name."},
         "wait_seconds": {"type": "number"}}, "required": ["name"]}},
    {"name": "ui_set_text",
     "description": ("Type a value into a field found by name (e.g. a Power BI filter box, a Settings field, "
                     "a web form field), read it back and retry another way if it differs. Never for passwords, "
                     "PINs, card numbers or codes."),
     "parameters": {"type": "object", "properties": {
         "name": {"type": "string"}, "text": {"type": "string"}, "window_title": {"type": "string"},
         "control_type": {"type": "string"}, "index": {"type": "integer"}}, "required": ["name", "text"]}},
]

TOOLS = {"ui_read": ui_read, "ui_find": ui_find, "ui_click": ui_click, "ui_set_text": ui_set_text}
