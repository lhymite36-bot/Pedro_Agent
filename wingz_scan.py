"""Code-driven Wingz syllabus scanner (Edge, Windows UI Automation).

Reads each course's Module Syllabus, expands every topic, and classifies items:
- done: the item shows the green check-circle icon (bootstrap-icons U+F26A)
- unfinished practice: any other icon
- graded: assessments/tests (create-test / view-assesment links) -> list only, never opened
Nothing is typed into the portal and nothing is submitted. Results go to task memory.
"""

from __future__ import annotations

import time
from typing import Any, Callable

BASE = "https://wingz.itvedant.com"
CHECK = "\uf26a"
DEFAULT_COURSES = (324, 326, 327, 330)
browser_override: Any = None   # tests inject a fake browser


def _clean(s: str) -> str:
    return " ".join("".join(c for c in (s or "") if not 0xE000 <= ord(c) <= 0xF8FF).split())


def classify(rows: list[tuple[str, str, str]]) -> dict[str, list[dict[str, str]]]:
    """rows = (control_type, raw_name, url) in page order, from the syllabus panel on.

    A syllabus item is a ListItem "<icon>Title" followed by its own Hyperlink "Title".
    Items with no link are not open yet (locked/upcoming) and are listed separately.
    """
    out: dict[str, list[dict[str, str]]] = {"done": [], "unfinished": [], "graded": [], "not_open_yet": []}
    topic = ""
    item: dict[str, str] | None = None

    def flush_locked():
        if item is not None:
            out["not_open_yet"].append({"topic": topic, "title": item["title"], "url": ""})

    for kind, raw, url in rows:
        if kind == "Button" and "\uf282" in raw:
            flush_locked(); item = None
            topic = _clean(raw)
            continue
        if kind == "ListItem" and raw:
            flush_locked()
            icon = raw[0] if 0xE000 <= ord(raw[0]) <= 0xF8FF else ""
            item = {"icon": icon, "title": _clean(raw)}
            continue
        if kind != "Hyperlink":
            continue
        name = _clean(raw)
        if not name:
            continue
        if "create-test" in url or "view-assesment" in url:
            flush_locked(); item = None
            out["graded"].append({"topic": topic, "title": name, "url": url})
            continue
        if item is not None and name == item["title"]:
            bucket = "done" if item["icon"] == CHECK else "unfinished"
            out[bucket].append({"topic": topic, "title": name, "url": url})
            item = None
            continue
        flush_locked(); item = None   # session links (EX1, ML3...) are not syllabus items
    flush_locked()
    seen, uniq = set(), {k: [] for k in out}
    for k, items in out.items():
        for it in items:
            key = (k, it["topic"], it["title"], it["url"])
            if key not in seen:
                seen.add(key)
                uniq[k].append(it)
    return uniq


class EdgeBrowser:
    def _win(self):
        from pywinauto import Desktop  # type: ignore
        wins = [w for w in Desktop(backend="uia").windows(visible_only=True)
                if "Edge" in (w.window_text() or "").replace("\u200b", "")]
        if not wins:
            raise RuntimeError("Microsoft Edge is not open.")
        return wins[0]

    def goto(self, url: str) -> None:
        from pywinauto import keyboard  # type: ignore
        w = self._win()
        w.set_focus()
        keyboard.send_keys("^l")
        time.sleep(0.3)
        keyboard.send_keys(url.replace("{", "{{}").replace("}", "{}}") + "{ENTER}", with_spaces=True)
        time.sleep(7)

    def title(self) -> str:
        return (self._win().window_text() or "").replace("\u200b", "")

    def expand_topics(self) -> int:
        n = 0
        for b in self._win().descendants(control_type="Button"):
            if "\uf282" in (b.window_text() or ""):
                try:
                    b.invoke()
                    n += 1
                except Exception:
                    pass
        time.sleep(1.5)
        return n

    def rows(self) -> list[tuple[str, str, str]]:
        out, start = [], False
        for e in self._win().descendants():
            kind = e.element_info.control_type
            name = e.window_text() or ""
            if kind == "Button" and "\uf282" in name:
                start = True
            if not start:
                continue
            try:
                url = e.iface_value.CurrentValue if kind == "Hyperlink" else ""
            except Exception:
                url = ""
            if kind == "Text" and name.strip() == "Notifications":
                break
            out.append((kind, name, url))
        return out

    def screenshot(self, path: str) -> None:
        from PIL import ImageGrab  # type: ignore
        ImageGrab.grab().convert("RGB").save(path, quality=75)

    def first_content_url(self, course_id: int) -> str:
        for h in self._win().descendants(control_type="Hyperlink"):
            try:
                v = h.iface_value.CurrentValue
            except Exception:
                continue
            if "self-learn-content" in v and f"course_id={course_id}" in v:
                return v
        return ""


def scan(course_ids: tuple[int, ...] | list[int] = DEFAULT_COURSES, shot_dir: str = "",
         progress: Callable[[str], None] | None = None) -> dict[str, Any]:
    b = browser_override or EdgeBrowser()
    say = progress or (lambda s: None)
    courses = []
    for cid in course_ids:
        b.goto(f"{BASE}/student/self-learn-batch?course_id={cid}")
        if "sign in" in b.title().lower() or "accounts.google" in b.title().lower():
            return {"ok": False, "error": "Wingz asked for Google sign-in. Sign in once, then scan again.",
                    "courses": courses}
        first = b.first_content_url(cid)
        if first:
            b.goto(first)   # the content page has the Module Syllabus panel
        name = b.title().split(" and ")[0].split(" - ")[0]
        b.expand_topics()
        result = classify(b.rows())
        shot = ""
        if shot_dir:
            shot = f"{shot_dir}\\wingz_scan_{cid}.jpg"
            b.screenshot(shot)
        courses.append({"course_id": cid, "page": name, **result, "screenshot": shot})
        say(f"{cid}: {len(result['unfinished'])} unfinished, {len(result['graded'])} graded")
    return {"ok": True, "courses": courses}


def summary(res: dict[str, Any]) -> str:
    lines = []
    for c in res.get("courses", []):
        lines.append(f"Course {c['course_id']} ({c['page']}): {len(c['done'])} done")
        for it in c["unfinished"]:
            kind = "assignment - answer + Save Answer" if "assignment" in it["title"].lower() else "lesson - open/read it, nothing to fill"
            lines.append(f"  UNGRADED unfinished ({kind}): {it['topic']} > {it['title']}  {it['url']}")
        for it in c["graded"]:
            lines.append(f"  GRADED (list only): {it['title']}")
        if c.get("not_open_yet"):
            lines.append(f"  Not open yet (no link, upcoming): {len(c['not_open_yet'])} items")
    return "\n".join(lines)


def wingz_scan(course_ids: list[int] | None = None) -> dict[str, Any]:
    """Tool entry: scan, save to task memory, return the list."""
    import task_memory
    try:
        res = scan(tuple(course_ids or DEFAULT_COURSES))
    except Exception as exc:
        return {"ok": False, "error": f"Wingz scan failed: {exc}"}
    text = summary(res)
    if res.get("ok"):
        task_memory.save_task_progress("wingz", left=text, note="wingz_scan result")
    return {"ok": bool(res.get("ok")), "message": text or res.get("error", ""), "error": res.get("error"),
            "courses": res.get("courses", [])}


DECLARATION = {
    "name": "wingz_scan",
    "description": (
        "Scan the Itvedant Wingz Module Syllabus of each course in Edge and return the real list: "
        "unfinished ungraded items (no green check) with their URLs, and graded assessments (list only). "
        "Saves it to task memory ('wingz'). Use this FIRST for any Wingz job, then work item by item "
        "from its list with navigate_browser to each URL."
    ),
    "parameters": {"type": "object", "properties": {
        "course_ids": {"type": "array", "items": {"type": "integer"},
                       "description": "Course ids; default Adv Excel 324, MySQL 326, PowerBI 327, Machine Learning 330."}}},
}
