"""1.8.2 Studio: batch-2 tools, all free (Gemini free key, ffmpeg, plain HTTP).

wa_draft       WhatsApp texting-style drafts. Never sends: the page shows Approve, which only
               opens WhatsApp with the text filled in (wa.me link) for Pedro to press send.
trend_radar    Google Trends daily RSS (no key) -> Gemini turns trends into psychology-Shorts angles.
video_edit     Plain-words edit ("trim 0:05-0:20, make it vertical, mute") -> a whitelisted ffmpeg command.
shortcuts      Phone automations: saved one-tap commands (and a time trigger) that run on the PC agent.
calls          "Call me at 7:30 about X": alarm-style ring on the phone/PC with the bot speaking.
app_factory    Describe an app -> app_builder builds it (existing Ped Bot builder).
meeting_notes  Recorded audio -> Gemini transcript + notes saved to Documents/Ped Bot Notes.
price_watch    URL + target price; checked every 6 h; a check-in when it drops.
photo_app      Photo/screenshot of an app or sketch -> single-file HTML app saved in builds.
mood_journal   Short daily entries -> mood score + gentle reflection; last 30 days.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


def _store() -> Path:
    base = Path(os.environ.get("STORAGE_DIR") or Path(__file__).resolve().parent / "storage") / "studio"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _load(name: str, default: Any) -> Any:
    try:
        return json.loads((_store() / f"{name}.json").read_text(encoding="utf-8"))
    except Exception:
        return default


def _save(name: str, data: Any) -> None:
    p = _store() / f"{name}.json"
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)


def _ai(prompt: str, images: list[bytes] | None = None) -> str:
    import llm
    return llm.text(prompt, images or None).strip()


def _ai_json(prompt: str, images: list[bytes] | None = None) -> Any:
    import llm
    return llm.json_from(_ai(prompt, images))


def _no_key(exc: Exception) -> dict[str, Any]:
    return {"ok": False, "error": "This needs your free Gemini key (Settings) and internet.", "detail": str(exc)[:160]}


# ---------------- WhatsApp drafts (never auto-send) ----------------
def wa_draft(to: str, intent: str, tone: str = "casual") -> dict[str, Any]:
    intent = " ".join(str(intent or "").split())[:600]
    if not intent:
        return {"ok": False, "error": "Say what the message should be about."}
    prompt = ("Write ONE WhatsApp message Pedro will send. Texting style: short, natural, lowercase is fine, "
              "1-2 fitting emoji max, no greeting essay, no hashtags, sounds like a real person in India/Ghana texting a "
              f"friend. Tone: {tone}. To: {to or 'a friend'}. What he wants to say: {intent}\n"
              'Reply JSON: {"drafts":["option 1","option 2","option 3"]} - three different options.')
    try:
        drafts = [str(d).strip() for d in (_ai_json(prompt).get("drafts") or []) if str(d).strip()][:3]
    except Exception as exc:
        return _no_key(exc)
    num = re.sub(r"\D", "", to or "")
    links = [("https://wa.me/" + num if len(num) >= 8 else "https://wa.me/") + "?text=" + urllib.parse.quote(d) for d in drafts]
    return {"ok": True, "drafts": drafts, "links": links, "note": "Nothing is sent. Approve opens WhatsApp with the text; you press send."}


# ---------------- Shorts trend radar ----------------
def _trends(geo: str) -> list[str]:
    url = f"https://trends.google.com/trending/rss?geo={urllib.parse.quote(geo or 'IN')}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 PedBot"})
    with urllib.request.urlopen(req, timeout=15) as r:
        xml = r.read().decode("utf-8", "replace")
    return [re.sub(r"<!\[CDATA\[|\]\]>", "", t).strip() for t in re.findall(r"<item>\s*<title>(.*?)</title>", xml, re.S)][:25]


def trend_radar(geo: str = "IN") -> dict[str, Any]:
    try:
        trends = _trends(geo)
    except Exception as exc:
        return {"ok": False, "error": "Could not reach Google Trends right now.", "detail": str(exc)[:120]}
    used = _load("trend_used", [])
    prompt = ("Pedro makes funny, sarcastic 2D animated psychology YouTube Shorts (POV and 'your brain when...' formats). "
              "From today's trending searches, pick up to 6 that can be turned into a relatable psychology Short "
              "without spreading misinformation or mocking tragedies (skip deaths, disasters, politics). "
              f"Avoid repeating these past ideas: {used[-30:]}\nTrends: {trends}\n"
              'Reply JSON: {"ideas":[{"trend":"...","title":"Short title <60 chars","hook":"first line","angle":"psych concept"}]}')
    try:
        ideas = (_ai_json(prompt).get("ideas") or [])[:6]
    except Exception as exc:
        return {"ok": True, "trends": trends, "ideas": [], **{k: v for k, v in _no_key(exc).items() if k != "ok"}}
    return {"ok": True, "trends": trends, "ideas": ideas}


def trend_use(title: str) -> dict[str, Any]:
    used = _load("trend_used", [])
    if title and title not in used:
        used.append(title[:120]); _save("trend_used", used[-200:])
    return {"ok": True}


# ---------------- Chat video editing (ffmpeg) ----------------
def _ffmpeg() -> str | None:
    try:
        import media_ffmpeg
        f = media_ffmpeg.find_ffmpeg()
        if f:
            return str(f)
    except Exception:
        pass
    return shutil.which("ffmpeg")


_TS = re.compile(r"^\d{1,2}(:\d{1,2}){0,2}(\.\d+)?$")


def build_ffmpeg(src: str, dst: str, ops: dict[str, Any]) -> list[str]:
    """Whitelisted options only; values are validated, never passed through raw."""
    cmd = ["-y"]
    s, e = str(ops.get("start") or ""), str(ops.get("end") or "")
    if s and _TS.match(s):
        cmd += ["-ss", s]
    if e and _TS.match(e):
        cmd += ["-to", e]
    cmd += ["-i", src]
    vf, af = [], []
    if ops.get("vertical"):
        vf.append("crop='min(iw,ih*9/16)':'min(ih,iw*16/9)',scale=1080:1920")
    try:
        sp = float(ops.get("speed") or 1)
    except (TypeError, ValueError):
        sp = 1.0
    sp = max(0.5, min(2.0, sp))
    if abs(sp - 1) > 0.01:
        vf.append(f"setpts=PTS/{sp:.3f}"); af.append(f"atempo={sp:.3f}")
    text = re.sub(r"[^\w\s!?.,'-]", "", str(ops.get("text") or ""))[:60]
    if text:
        vf.append("drawtext=text='" + text.replace("'", "") + "':fontcolor=white:fontsize=h/18:box=1:boxcolor=black@0.45:x=(w-tw)/2:y=h*0.12")
    if ops.get("grayscale"):
        vf.append("hue=s=0")
    if vf:
        cmd += ["-vf", ",".join(vf)]
    if ops.get("mute"):
        cmd += ["-an"]
    elif af:
        cmd += ["-af", ",".join(af)]
    if ops.get("compress"):
        cmd += ["-c:v", "libx264", "-crf", "28", "-preset", "veryfast"]
    cmd.append(dst)
    return cmd


def video_edit(path: str, instruction: str) -> dict[str, Any]:
    src = Path(str(path or "").strip().strip('"')).expanduser()
    if not src.is_file():
        return {"ok": False, "error": "Pick a video file on this PC first."}
    exe = _ffmpeg()
    if not exe:
        return {"ok": False, "error": "ffmpeg is not installed. Ped Bot can install it: ask in chat 'install ffmpeg'."}
    prompt = ("Turn this video edit request into JSON options. Keys (all optional): start, end (timestamps like 0:05), "
              "vertical (bool, 9:16 for Shorts), speed (0.5-2), mute (bool), text (caption <=60 chars), grayscale (bool), "
              f"compress (bool). Request: {instruction}\nReply JSON only.")
    try:
        ops = _ai_json(prompt)
        if not isinstance(ops, dict):
            raise ValueError("bad")
    except Exception:
        low = (instruction or "").lower()
        ops = {"vertical": "vertical" in low or "short" in low, "mute": "mute" in low or "no sound" in low,
               "compress": "compress" in low or "smaller" in low, "grayscale": "black and white" in low}
        m = re.search(r"(\d{1,2}:\d{2})\s*(?:-|to)\s*(\d{1,2}:\d{2})", low)
        if m:
            ops["start"], ops["end"] = m.group(1), m.group(2)
    dst = src.with_name(src.stem + "_edited_" + time.strftime("%H%M%S") + ".mp4")
    args = [exe] + build_ffmpeg(str(src), str(dst), ops)
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=900)
    except Exception as exc:
        return {"ok": False, "error": "ffmpeg did not finish.", "detail": str(exc)[:120]}
    if p.returncode != 0 or not dst.is_file():
        return {"ok": False, "error": "ffmpeg could not make that edit.", "detail": (p.stderr or "")[-300:], "ops": ops}
    return {"ok": True, "output": str(dst), "ops": ops}


# ---------------- Phone automations (shortcuts) ----------------
def shortcuts(action: str = "list", **kw: Any) -> dict[str, Any]:
    items = _load("shortcuts", [])
    if action == "add":
        label, cmd = str(kw.get("label") or "").strip()[:40], str(kw.get("command") or "").strip()[:400]
        at = str(kw.get("at") or "").strip()
        if not label or not cmd:
            return {"ok": False, "error": "Give the shortcut a name and a command."}
        if at and not re.match(r"^\d{1,2}:\d{2}$", at):
            return {"ok": False, "error": "Time must look like 07:30."}
        items.append({"id": uuid.uuid4().hex[:8], "label": label, "command": cmd, "at": at, "last": ""})
    elif action == "delete":
        items = [i for i in items if i.get("id") != kw.get("id")]
    _save("shortcuts", items)
    return {"ok": True, "items": items}


# ---------------- Bots that call him ----------------
def calls(action: str = "list", **kw: Any) -> dict[str, Any]:
    items = _load("calls", [])
    if action == "add":
        at, about = str(kw.get("at") or "").strip(), str(kw.get("about") or "").strip()[:300]
        if not re.match(r"^\d{1,2}:\d{2}$", at):
            return {"ok": False, "error": "Time must look like 07:30."}
        items.append({"id": uuid.uuid4().hex[:8], "at": at, "about": about or "a quick check-in", "repeat": bool(kw.get("repeat")),
                      "bot": str(kw.get("bot") or ""), "last": ""})
    elif action == "delete":
        items = [i for i in items if i.get("id") != kw.get("id")]
    _save("calls", items)
    return {"ok": True, "items": items}


def call_script(about: str) -> str:
    try:
        return _ai(f"You are Pedro's assistant calling him on the phone about: {about}. Write what you say when he picks up: "
                   "warm, 2-3 short spoken sentences, no markdown.")
    except Exception:
        return f"Hey Pedro, it's Ped Bot. Calling about {about}."


_pending_calls: list[dict[str, Any]] = []


def pending_call() -> dict[str, Any]:
    return {"ok": True, "call": _pending_calls.pop(0) if _pending_calls else None}


# ---------------- Meeting notes ----------------
def meeting_notes(audio_b64: str, mime: str = "audio/webm", title: str = "") -> dict[str, Any]:
    import base64
    try:
        raw = base64.b64decode(audio_b64 or "", validate=False)
    except Exception:
        raw = b""
    if len(raw) < 2000:
        return {"ok": False, "error": "The recording is empty."}
    if len(raw) > 18 * 1024 * 1024:
        return {"ok": False, "error": "Recording too long for the free tier (max ~15 minutes). Record in parts."}
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        return {"ok": False, "error": "Meeting notes need your free Gemini key (Settings)."}
    body = {"contents": [{"parts": [
        {"text": "Transcribe this meeting, then write notes. Reply JSON: {\"title\":\"...\",\"summary\":\"3 sentences\","
                 "\"decisions\":[...],\"action_items\":[{\"who\":\"\",\"what\":\"\",\"when\":\"\"}],\"transcript\":\"...\"}"},
        {"inline_data": {"mime_type": (mime or "audio/webm").split(";")[0], "data": base64.b64encode(raw).decode()}}]}]}
    out = None
    import brain
    for model in (brain.MAIN, "gemini-3.5-flash-lite", brain.TOP):
        try:
            req = urllib.request.Request(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                                         data=json.dumps(body).encode(), headers={"Content-Type": "application/json", "x-goog-api-key": key})
            with urllib.request.urlopen(req, timeout=300) as r:
                d = json.loads(r.read().decode())
            txt = "".join(p.get("text", "") for p in d["candidates"][0]["content"]["parts"])
            import llm
            out = llm.json_from(txt)
            break
        except Exception:
            continue
    if not isinstance(out, dict):
        return {"ok": False, "error": "Gemini could not make notes from that recording."}
    docs = Path.home() / "Documents" / "Ped Bot Notes"
    docs.mkdir(parents=True, exist_ok=True)
    name = re.sub(r"[^\w -]", "", title or out.get("title") or "Meeting")[:60].strip() or "Meeting"
    f = docs / f"{time.strftime('%Y-%m-%d %H%M')} {name}.md"
    lines = [f"# {out.get('title') or name}", "", out.get("summary") or "", "", "## Decisions"] + [f"- {x}" for x in out.get("decisions") or []]
    lines += ["", "## Action items"] + [f"- [ ] {a.get('what','')} ({a.get('who','')}{', ' + a['when'] if a.get('when') else ''})" for a in out.get("action_items") or [] if isinstance(a, dict)]
    lines += ["", "## Transcript", "", out.get("transcript") or ""]
    f.write_text("\n".join(lines), encoding="utf-8")
    return {"ok": True, "file": str(f), **{k: out.get(k) for k in ("title", "summary", "decisions", "action_items")}}


# ---------------- Price watcher ----------------
_PRICE = re.compile(r"(?:₹|rs\.?|inr|\$|usd|€|£|ghs|gh₵)\s*([0-9][0-9,]*(?:\.\d{1,2})?)", re.I)


def read_price(html: str) -> float | None:
    for pat in (r'"price"\s*:\s*"?([0-9][0-9,]*(?:\.\d+)?)', r'itemprop="price"[^>]*content="([0-9.,]+)"',
                r'property="product:price:amount"[^>]*content="([0-9.,]+)"'):
        m = re.search(pat, html, re.I)
        if m:
            try:
                return float(m.group(1).replace(",", ""))
            except ValueError:
                pass
    vals = []
    for m in _PRICE.finditer(html[:400000]):
        try:
            vals.append(float(m.group(1).replace(",", "")))
        except ValueError:
            pass
    vals = [v for v in vals if v > 0]
    return vals[0] if vals else None


def _fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130 Safari/537.36",
                                               "Accept-Language": "en-IN,en;q=0.9"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read(1_500_000).decode("utf-8", "replace")


def price_watch(action: str = "list", **kw: Any) -> dict[str, Any]:
    items = _load("prices", [])
    if action == "add":
        url = str(kw.get("url") or "").strip()
        if not url.startswith(("http://", "https://")):
            return {"ok": False, "error": "Paste the product link."}
        try:
            target = float(str(kw.get("target") or "0").replace(",", ""))
        except ValueError:
            target = 0.0
        it = {"id": uuid.uuid4().hex[:8], "url": url, "name": str(kw.get("name") or "")[:80], "target": target,
              "price": None, "checked": 0, "alerted": False}
        items.append(it); _save("prices", items)
        check_prices([it["id"]])
        items = _load("prices", [])
    elif action == "delete":
        items = [i for i in items if i.get("id") != kw.get("id")]; _save("prices", items)
    elif action == "check":
        check_prices()
        items = _load("prices", [])
    return {"ok": True, "items": items}


def check_prices(ids: list[str] | None = None) -> None:
    items = _load("prices", [])
    for it in items:
        if ids and it["id"] not in ids:
            continue
        try:
            html = _fetch(it["url"])
            if not it.get("name"):
                t = re.search(r"<title>(.*?)</title>", html, re.S | re.I)
                it["name"] = re.sub(r"\s+", " ", t.group(1)).strip()[:80] if t else it["url"][:60]
            p = read_price(html)
            it["price"], it["checked"] = p, time.time()
            if p and it.get("target") and p <= it["target"] and not it.get("alerted"):
                it["alerted"] = True
                try:
                    import checkins
                    checkins.post("price", f"Price drop: {it['name']} is now {p:,.0f} (your target {it['target']:,.0f}). {it['url']}", urgent=True, key="price-" + it["id"])
                except Exception:
                    pass
            elif p and it.get("target") and p > it["target"]:
                it["alerted"] = False
        except Exception as exc:
            it["error"], it["checked"] = str(exc)[:80], time.time()
    _save("prices", items)


# ---------------- Photo to app ----------------
def photo_app(image_b64: str, notes: str = "") -> dict[str, Any]:
    import base64
    try:
        img = base64.b64decode(image_b64 or "")
    except Exception:
        img = b""
    if len(img) < 500:
        return {"ok": False, "error": "Add a photo or screenshot first."}
    prompt = ("Build a working single-file web app from this photo (a screenshot, mockup or hand sketch). "
              "Recreate the layout and make every button work with plain JavaScript and localStorage. Mobile friendly. "
              f"Extra wishes: {notes or 'none'}. Reply with ONLY the full HTML document.")
    try:
        html = _ai(prompt, [img])
    except Exception as exc:
        return _no_key(exc)
    html = re.sub(r"^```(?:html)?\s*|\s*```$", "", html.strip())
    if "<html" not in html.lower():
        return {"ok": False, "error": "Gemini did not return an app. Try a clearer photo."}
    import app_builder
    root = app_builder.builds_root() / ("photo-app-" + time.strftime("%Y%m%d-%H%M%S"))
    root.mkdir(parents=True, exist_ok=True)
    (root / "index.html").write_text(html, encoding="utf-8")
    pub = _store() / "apps"; pub.mkdir(exist_ok=True)
    slug = root.name
    (pub / f"{slug}.html").write_text(html, encoding="utf-8")
    return {"ok": True, "folder": str(root), "preview": f"/studio/app/{slug}.html"}


def app_file(name: str) -> Path | None:
    if not re.match(r"^[\w-]+\.html$", name or ""):
        return None
    f = _store() / "apps" / name
    return f if f.is_file() else None


# ---------------- App factory ----------------
_jobs: dict[str, dict[str, Any]] = {}


def app_factory(goal: str) -> dict[str, Any]:
    goal = " ".join(str(goal or "").split())[:1500]
    if not goal:
        return {"ok": False, "error": "Describe the app you want."}
    jid = uuid.uuid4().hex[:8]
    _jobs[jid] = {"status": "building", "goal": goal, "started": time.time()}

    def work() -> None:
        try:
            import app_builder
            out = app_builder.build_app(goal)
            _jobs[jid].update(status="done" if out.get("ok", True) else "failed", result={k: out.get(k) for k in ("ok", "name", "folder", "path", "message", "error") if k in out},
                              message=app_builder.final_message(out) if hasattr(app_builder, "final_message") else str(out)[:400])
        except Exception as exc:
            _jobs[jid].update(status="failed", message=str(exc)[:300])
    threading.Thread(target=work, daemon=True).start()
    return {"ok": True, "job": jid}


def app_job(jid: str) -> dict[str, Any]:
    j = _jobs.get(jid)
    return {"ok": bool(j), **(j or {"error": "No such build."})}


# ---------------- Mood journal ----------------
def mood(action: str = "list", text: str = "") -> dict[str, Any]:
    items = _load("mood", [])
    if action == "add":
        text = " ".join(str(text or "").split())[:2000]
        if not text:
            return {"ok": False, "error": "Write a line about your day."}
        try:
            r = _ai_json("Pedro wrote this in his mood journal. Rate mood 1-10, name the main feeling in one word, and write a "
                         "warm, non-clinical 1-2 sentence reflection (no advice lists, no diagnosis). "
                         f'Reply JSON: {{"score":7,"feeling":"hopeful","reflection":"..."}}\n\n{text}')
            score = max(1, min(10, int(r.get("score") or 5))); feeling = str(r.get("feeling") or "")[:20]; refl = str(r.get("reflection") or "")[:400]
        except Exception:
            score, feeling, refl = 5, "", "Saved. Add your Gemini key for a reflection."
        items.append({"t": time.time(), "day": time.strftime("%Y-%m-%d"), "text": text, "score": score, "feeling": feeling, "reflection": refl})
        _save("mood", items[-400:])
    cut = time.time() - 30 * 86400
    return {"ok": True, "items": [i for i in items if i["t"] >= cut][-60:]}


# ---------------- background ticker (calls, shortcuts at a time, prices) ----------------
_started = False


def tick(now: float | None = None) -> list[str]:
    now = now or time.time()
    hm, day = time.strftime("%H:%M", time.localtime(now)), time.strftime("%Y-%m-%d", time.localtime(now))
    done = []
    items = _load("calls", [])
    changed = False
    for c in items:
        if c["at"].zfill(5) == hm and c.get("last") != day:
            c["last"] = day; changed = True
            say = call_script(c["about"])
            _pending_calls.append({"id": c["id"], "about": c["about"], "say": say, "t": now})
            try:
                import live_sync
                live_sync.notify("call", about=c["about"], say=say)
            except Exception:
                pass
            try:
                import checkins
                checkins.post("call", f"📞 Ped Bot is calling: {c['about']}", urgent=True, key="call-" + c["id"] + day)
            except Exception:
                pass
            done.append("call:" + c["id"])
    keep = [c for c in items if c.get("repeat") or c.get("last") != day]
    if changed or len(keep) != len(items):
        _save("calls", keep)
    sc = _load("shortcuts", [])
    for s in sc:
        if s.get("at") and s["at"].zfill(5) == hm and s.get("last") != day:
            s["last"] = day; _save("shortcuts", sc)
            _run_command(s["command"]); done.append("shortcut:" + s["id"])
    p = _load("prices", [])
    if p and now - max((i.get("checked") or 0) for i in p) > 6 * 3600:
        threading.Thread(target=check_prices, daemon=True).start(); done.append("prices")
    return done


def _run_command(text: str) -> None:
    """Timed shortcuts do not run unattended: they ping Pedro, and one tap on the Studio page runs them."""
    try:
        import checkins
        checkins.post("shortcut", f"⏰ Shortcut time: {text[:120]} - open Studio to run it.", urgent=False, key="sc-" + text[:20] + time.strftime("%Y%m%d"))
    except Exception:
        pass


def start() -> None:
    global _started
    if _started:
        return
    _started = True

    def loop() -> None:
        while True:
            try:
                tick()
            except Exception:
                pass
            time.sleep(60 - time.time() % 60 + 1)
    threading.Thread(target=loop, daemon=True, name="studio182").start()
