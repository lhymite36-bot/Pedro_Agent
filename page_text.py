"""Read the visible web page's text from Chrome/Edge via Windows UI Automation.

No debugging port, no cookies, no page changes: it only reads the accessibility
tree the browser already exposes. Tests set reader_override.
"""

from __future__ import annotations

from typing import Any, Callable

reader_override: Callable[[str], list[str]] | None = None
_KEEP = {"Text", "Hyperlink", "ListItem", "Button", "Header", "HeaderItem", "Heading",
         "TabItem", "CheckBox", "Edit", "Image", "DataItem", "TreeItem", "MenuItem"}


def _lines_from_browser(window_title: str) -> list[str]:
    from pywinauto import Desktop  # type: ignore

    wanted = (window_title or "").casefold()
    def _title(w):
        return (w.window_text() or "").replace("\u200b", "")

    wins = [w for w in Desktop(backend="uia").windows(visible_only=True)
            if any(b in _title(w) for b in ("Google Chrome", "Microsoft Edge"))
            and wanted in _title(w).casefold()]
    # Prefer the window whose page is Wingz/the requested one; Edge is the default browser here.
    wins.sort(key=lambda w: 0 if "edge" in _title(w).casefold() else 1)
    if not wins:
        raise RuntimeError("No Chrome or Edge window matches that title.")
    win = wins[0]
    docs = win.descendants(control_type="Document")
    root = docs[0] if docs else win
    out: list[str] = []
    for i, el in enumerate(root.descendants()):
        if i > 4000:
            break
        try:
            kind = el.element_info.control_type
            name = " ".join((el.window_text() or "").split())
        except Exception:
            continue
        if not name or kind not in _KEEP:
            continue
        tag = "" if kind == "Text" else f"[{kind}] "
        line = tag + name
        if not out or out[-1] != line:
            out.append(line)
    return out


def read_page_text(window_title: str = "", max_chars: int = 12000) -> dict[str, Any]:
    try:
        lines = reader_override(window_title) if reader_override else _lines_from_browser(window_title)
    except Exception as exc:
        return {"ok": False, "error": f"Could not read the page text: {exc}"}
    text = "\n".join(lines)
    cut = len(text) > max_chars
    return {"ok": True, "message": f"Read {len(lines)} page lines.", "text": text[:max_chars],
            "truncated": cut,
            "note": "Text only. Icons like green checks may show as [Image] names or not at all; "
                    "confirm completion marks with take_screenshot."}


DECLARATION = {
    "name": "read_page_text",
    "description": (
        "Read the text of the web page open in Chrome/Edge (headings, links, list items, buttons) "
        "without screenshots. Use it to list syllabus items, read questions and check saved answers. "
        "Scroll is not needed for text that is already loaded. Optional window_title filters the tab title."
    ),
    "parameters": {"type": "object", "properties": {
        "window_title": {"type": "string", "description": "Part of the browser tab title, e.g. Wingz."},
        "max_chars": {"type": "integer", "description": "Cap on returned characters (default 12000)."},
    }},
}
