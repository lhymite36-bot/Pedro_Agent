"""Gig finder + earnings tracker. Drafts only — Pedro sends proposals himself.

Public free boards: RemoteOK, We Work Remotely RSS, Jobicy. No paid APIs.
"""

from __future__ import annotations

import json
import re
import time
import urllib.request
import xml.etree.ElementTree as ET
from typing import Any

fetch_override = None  # tests: fn(url) -> str | bytes
DEFAULT_SKILLS = ("shorts", "youtube", "apps", "android", "python", "tableau", "data", "video")


def _store():
    import agent_config
    p = agent_config.storage_dir() / "pro190"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _get(url: str, timeout: int = 12) -> bytes:
    if fetch_override is not None:
        raw = fetch_override(url)
        return raw if isinstance(raw, bytes) else str(raw).encode("utf-8", "replace")
    req = urllib.request.Request(url, headers={"User-Agent": "PedBot/1.9 (gig finder; +https://github.com/lhymite36-bot/Pedro_Agent)"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()[:400_000]


def _skills(raw: Any) -> list[str]:
    if isinstance(raw, str):
        parts = re.split(r"[,;/]+", raw)
    elif isinstance(raw, list):
        parts = raw
    else:
        parts = list(DEFAULT_SKILLS)
    out = [re.sub(r"\s+", " ", str(p).strip().casefold()) for p in parts if str(p).strip()]
    return out or list(DEFAULT_SKILLS)


def _match(item: dict[str, str], skills: list[str]) -> bool:
    hay = " ".join(item.get(k, "") for k in ("title", "company", "tags", "description")).casefold()
    return any(s in hay for s in skills)


def remoteok(skills: list[str]) -> list[dict[str, str]]:
    try:
        raw = _get("https://remoteok.com/api")
        data = json.loads(raw.decode("utf-8", "replace"))
    except Exception:
        return []
    jobs = []
    for row in data if isinstance(data, list) else []:
        if not isinstance(row, dict) or not row.get("position") and not row.get("title"):
            continue
        item = {
            "source": "RemoteOK",
            "title": str(row.get("position") or row.get("title") or ""),
            "company": str(row.get("company") or ""),
            "url": str(row.get("url") or row.get("apply_url") or ""),
            "tags": " ".join(str(t) for t in (row.get("tags") or [])),
            "description": str(row.get("description") or "")[:400],
        }
        if item["title"] and _match(item, skills):
            jobs.append(item)
    return jobs[:25]


def rss(url: str, source: str, skills: list[str]) -> list[dict[str, str]]:
    try:
        raw = _get(url)
        root = ET.fromstring(raw)
    except Exception:
        return []
    jobs = []
    for item in root.iter():
        if item.tag.split("}")[-1].casefold() != "item":
            continue
        def txt(name: str) -> str:
            for child in item:
                if child.tag.split("}")[-1].casefold() == name:
                    return (child.text or "").strip()
            return ""
        row = {
            "source": source,
            "title": txt("title"),
            "company": "",
            "url": txt("link"),
            "tags": "",
            "description": re.sub(r"<[^>]+>", " ", txt("description"))[:400],
        }
        if row["title"] and _match(row, skills):
            jobs.append(row)
    return jobs[:20]


def search(skills: Any = None) -> dict[str, Any]:
    skills = _skills(skills)
    jobs: list[dict[str, str]] = []
    jobs.extend(remoteok(skills))
    jobs.extend(rss("https://weworkremotely.com/categories/remote-programming-jobs.rss", "We Work Remotely", skills))
    jobs.extend(rss("https://jobicy.com/feed/jobs", "Jobicy", skills))
    # de-dupe by url/title
    seen: set[str] = set()
    uniq = []
    for j in jobs:
        key = (j.get("url") or j.get("title") or "").casefold()
        if key and key not in seen:
            seen.add(key)
            uniq.append(j)
    path = _store() / "gigs.json"
    path.write_text(json.dumps({"at": time.time(), "skills": skills, "jobs": uniq[:40]}, indent=1), encoding="utf-8")
    return {
        "ok": True,
        "jobs": uniq[:40],
        "skills": skills,
        "count": len(uniq),
        "note": "Public free boards only. Ped Bot never applies or sends mail — you send the draft yourself.",
    }


def _style_bits() -> str:
    try:
        import agent_core
        block = agent_core.memory_prompt_block()
        return (block or "")[:800]
    except Exception:
        return ""


def draft(job: dict[str, Any] | None = None, extra: str = "") -> dict[str, Any]:
    job = job or {}
    title = str(job.get("title") or extra or "").strip()
    if not title:
        return {"ok": False, "error": "Pick a gig first."}
    prompt = (
        "Write a short freelance proposal in Pedro's voice: direct, friendly, no fluff, "
        "mentions Shorts / apps / Tableau when they fit, never claims work that is not listed. "
        "Max 140 words. Do not include an email send. This is a draft Pedro will paste himself.\n"
        f"JOB TITLE: {title}\nCOMPANY: {job.get('company') or ''}\n"
        f"TAGS: {job.get('tags') or ''}\nDESC: {job.get('description') or extra}\n"
        f"ABOUT PEDRO (facts):\n{_style_bits()}"
    )
    try:
        import llm
        text = llm.text(prompt).strip()
        source = "gemini"
    except Exception:
        text = (
            f"Hi — I'm Pedro. I make Shorts, small apps and Tableau/data work. "
            f"I can take on “{title}”. I'll send a short plan and a first draft on day one. "
            f"Happy to start with a paid trial task.\n\nPedro"
        )
        source = "local"
    return {
        "ok": True,
        "draft": text,
        "job": {"title": title, "url": job.get("url") or "", "company": job.get("company") or ""},
        "source": source,
        "note": "Copy and send it yourself. Ped Bot will not submit this.",
    }


def _earn() -> Path:
    return _store() / "earnings.json"


def _load_earn() -> list[dict[str, Any]]:
    try:
        data = json.loads(_earn().read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def earnings(action: str = "list", amount: Any = 0, note: str = "", item_id: str = "") -> dict[str, Any]:
    rows = _load_earn()
    if action == "add":
        try:
            amt = float(str(amount).replace(",", "").replace("$", "").strip() or 0)
        except ValueError:
            return {"ok": False, "error": "Enter a number."}
        row = {"id": str(int(time.time() * 1000)), "amount": amt, "note": str(note or "")[:120], "at": time.time()}
        rows.append(row)
        _earn().write_text(json.dumps(rows, indent=1), encoding="utf-8")
    elif action == "delete" and item_id:
        rows = [r for r in rows if str(r.get("id")) != str(item_id)]
        _earn().write_text(json.dumps(rows, indent=1), encoding="utf-8")
    total = sum(float(r.get("amount") or 0) for r in rows)
    return {"ok": True, "items": rows[-60:], "total": total}


def handle(action: str, data: dict[str, Any]) -> dict[str, Any]:
    if action in ("", "search"):
        return search(data.get("skills") or data.get("query"))
    if action == "draft":
        job = data.get("job") if isinstance(data.get("job"), dict) else {
            "title": data.get("title") or "",
            "company": data.get("company") or "",
            "url": data.get("url") or "",
            "description": data.get("description") or "",
            "tags": data.get("tags") or "",
        }
        return draft(job, str(data.get("extra") or ""))
    if action in ("earnings", "earn"):
        return earnings(str(data.get("earn_action") or data.get("op") or "list"), data.get("amount") or 0,
                        str(data.get("note") or ""), str(data.get("id") or ""))
    return {"ok": False, "error": "Unknown income action."}
