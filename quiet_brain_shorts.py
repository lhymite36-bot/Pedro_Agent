"""Quiet Brain Shorts - Ped Bot's backup of the Grok Bot daily Shorts routine (1.4.14).

Same pipeline as the Grok Bot routines "daily-youtube-shorts-6-a-day" and
"shorts-overflow-queue-buffer-free-slot-filler" (see daily-shorts/PIPELINE.md):

  1. ideas   6 funny, sarcastic psychology Shorts a day, formats rotated (pov, brain-like,
             nobody-me, expectation, brain-vs-me, storytime), each with a calm, kind fix.
             Never an idea already in posted.json or already in Buffer (shared with Grok Bot).
  2. render  Voice to Short (lhymite36-bot/voice-to-short) tests/live/e2e-live.js, ~60 s,
             ANIM=2d MOTION=smooth TONE=sarcastic (2D only, Shorts only). Resumable.
  3. verify  1080x1920 h264+aac, 23-60 fps, < 60 s, audio not silent.
  4. host    gh release upload <day> -R lhymite36-bot/quiet-brain-shorts, URL must return 200.
  5. queue   Buffer API (customScheduled, +05:30): YouTube first (title "... #shorts", category 27,
             public, notifySubscribers false, madeForKids false, isAiGenerated false), then the
             TikTok twin (caption with #fyp #quietbrain, isAiGenerated false). Free plan = 10
             scheduled posts: YouTube takes free slots first; TikTok twins wait as
             "pending-overflow" and the filler queues them when slots free up.
  6. record  posted.json entry (same fields as add_posted.py).

Off by default. Settings > Quiet Brain Shorts turns the routine on; the Buffer token is kept
only in the local .env (BUFFER_ACCESS_TOKEN). dry_run=True never renders uploads or posts.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import shutil
import subprocess
import threading
import time
import urllib.request
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Callable

ORG_ID = "6ab28e988594de36fbfdb2c5"
YOUTUBE_CHANNEL = "6abdd883ea19ca0bde3dc021"
TIKTOK_CHANNEL = "6abddc23ea19ca0bde3dfad1"
HOST_REPO = "lhymite36-bot/quiet-brain-shorts"
API = "https://api.buffer.com"
FREE_PLAN_LIMIT = 10
SLOTS = ["14:30", "16:00", "19:00", "20:30", "21:30", "22:30"]   # 1.5.8: Pedro's times (IST)
OVERFLOW_SLOTS = ["15:30", "16:00", "16:30", "19:30", "20:30", "21:30", "22:00", "22:30"]
FORMATS = ["pov", "brain-like", "nobody-me", "expectation", "brain-vs-me", "storytime"]
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
SIMILAR = 0.72

transport: Callable[[dict[str, Any]], dict[str, Any]] | None = None   # tests / dry runs
idea_writer: Callable[[str], str] | None = None
_lock = threading.Lock()


# ---------- settings / record ----------
def _storage() -> Path:
    import agent_config

    d = agent_config.storage_dir() / "quiet_brain_shorts"
    d.mkdir(parents=True, exist_ok=True)
    return d


def settings() -> dict[str, Any]:
    try:
        data = json.loads((_storage() / "settings.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    return {"enabled": bool(data.get("enabled", False)), "per_day": int(data.get("per_day", 6)),
            "start_time": _hm(data.get("start_time") or "12:30"),
            "vts_dir": data.get("vts_dir") or os.environ.get("VTS_DIR", ""),
            "token_set": bool(_token()), **readiness()}


def _hm(v: Any) -> str:
    m = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*", str(v or ""))
    return f"{int(m.group(1)):02d}:{m.group(2)}" if m and int(m.group(1)) < 24 and int(m.group(2)) < 60 else "12:30"


def _token() -> str:
    """1.5.4: the saved token, re-read from the local .env when this process doesn't have it yet
    (saved by another window, by hand, or before a restart). Never logged or returned."""
    tok = os.environ.get("BUFFER_ACCESS_TOKEN", "").strip()
    if tok:
        return tok
    try:
        import agent_config
        env = agent_config.APP_DIR / ".env"
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith("BUFFER_ACCESS_TOKEN="):
                tok = line.split("=", 1)[1].strip().strip('"').strip("'")
        if tok:
            os.environ["BUFFER_ACCESS_TOKEN"] = tok
    except OSError:
        pass
    return tok


def readiness() -> dict[str, Any]:
    """1.4.17: what posting still needs, without touching the token (only whether one is saved)."""
    cur_vts = (settings_raw().get("vts_dir") or os.environ.get("VTS_DIR", "")).strip()
    checks = {
        "buffer_token": bool(_token()),
        "voice_to_short_folder": bool(cur_vts) and (Path(cur_vts) / "tests" / "live" / "e2e-live.js").is_file(),
        "node": bool(shutil.which("node")),
        "ffprobe": bool(shutil.which("ffprobe")),
        "gh": bool(shutil.which("gh")),
    }
    names = {"buffer_token": "Buffer token", "voice_to_short_folder": "Voice to Short folder", "node": "Node.js",
             "ffprobe": "ffprobe (FFmpeg)", "gh": "GitHub CLI"}
    missing = [names[k] for k, ok in checks.items() if not ok]
    return {"checks": checks, "missing": missing, "ready": not missing}


def settings_raw() -> dict[str, Any]:
    try:
        return json.loads((_storage() / "settings.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_settings(**changes: Any) -> dict[str, Any]:
    cur = settings()
    for k in ("enabled", "per_day", "vts_dir", "start_time"):
        if k in changes:
            cur[k] = changes[k]
    (_storage() / "settings.json").write_text(json.dumps({k: cur[k] for k in ("enabled", "per_day", "vts_dir", "start_time")}),
                                              encoding="utf-8")
    return settings()


def set_token(token: str) -> dict[str, Any]:
    """Save BUFFER_ACCESS_TOKEN in the local .env only (never git, never logs)."""
    import agent_config

    token = "".join(str(token or "").split())
    if not token:
        return {"ok": False, "error": "Paste the Buffer access token."}
    env = agent_config.APP_DIR / ".env"
    lines = env.read_text(encoding="utf-8").splitlines() if env.is_file() else []
    lines = [l for l in lines if not l.startswith("BUFFER_ACCESS_TOKEN=")] + [f"BUFFER_ACCESS_TOKEN={token}"]
    env.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.environ["BUFFER_ACCESS_TOKEN"] = token   # live at once, no restart
    v = check_token()
    return {"ok": True, "valid": v.get("valid"), "message": "Buffer token saved in your local .env. " + v["message"]}


def posted_path() -> Path:
    raw = os.environ.get("QUIET_BRAIN_POSTED_JSON", "").strip()
    return Path(raw) if raw else _storage() / "posted.json"


def load_posted() -> list[dict[str, Any]]:
    try:
        d = json.loads(posted_path().read_text(encoding="utf-8"))
        return d if isinstance(d, list) else []
    except (OSError, ValueError):
        return []


def add_posted(entry: dict[str, Any]) -> int:
    """Same rule as add_posted.py: replace the entry for the same file+date, else append."""
    with _lock:
        d = [x for x in load_posted() if not (x.get("file") == entry.get("file") and x.get("date") == entry.get("date"))]
        d.append(entry)
        p = posted_path()
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(d, indent=1, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, p)
        return len(d)


# ---------- Buffer ----------
def _gql(query: str, variables: dict[str, Any]) -> dict[str, Any]:
    payload = {"query": query, "variables": variables}
    if transport is not None:
        return transport(payload)
    token = _token()
    if not token:
        raise RuntimeError("No Buffer token. Add it in Settings > Quiet Brain Shorts (saved in your local .env only).")
    req = urllib.request.Request(API, data=json.dumps(payload).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        out = json.loads(r.read().decode("utf-8"))
    if out.get("errors"):
        raise RuntimeError("Buffer: " + "; ".join(e.get("message", "") for e in out["errors"])[:300])
    return out.get("data") or {}


POSTS_Q = ("query Q($org: OrganizationId!, $st: [PostStatus!], $after: String){ posts(first: 50, after: $after, "
           "input:{organizationId:$org, filter:{status:$st}}){ edges{ node{ id text dueAt status channelId "
           "channelService assets{ ... on VideoAsset { source } } } } pageInfo{hasNextPage endCursor} } }")


def buffer_posts(statuses: list[str], max_pages: int = 10) -> list[dict[str, Any]]:
    out, after = [], None
    for _ in range(max_pages):
        data = _gql(POSTS_Q, {"org": ORG_ID, "st": statuses, "after": after})
        posts = (data.get("posts") or {})
        out += [e["node"] for e in posts.get("edges") or []]
        info = posts.get("pageInfo") or {}
        if not info.get("hasNextPage"):
            break
        after = info.get("endCursor")
    return out


CREATE_M = ("mutation M($input: CreatePostInput!){ createPost(input:$input){ ... on PostActionSuccess { post { id dueAt } } "
            "... on MutationError { message } } }")


def create_post(inp: dict[str, Any]) -> dict[str, Any]:
    res = (_gql(CREATE_M, {"input": inp}).get("createPost") or {})
    if "post" in res:
        return {"ok": True, "id": res["post"]["id"]}
    return {"ok": False, "error": res.get("message") or "Buffer refused the post."}


# ---------- ideas ----------
def _norm(t: str) -> str:
    t = re.sub(r"#\w+", " ", str(t or "").lower())
    return " ".join(re.findall(r"[a-z0-9']+", t))


def is_duplicate(idea: str, known: list[str]) -> bool:
    a = _norm(idea)
    if not a:
        return True
    for k in known:
        b = _norm(k)
        if b and (a == b or SequenceMatcher(None, a[:220], b[:220]).ratio() >= SIMILAR):
            return True
    return False


def known_ideas(buffer_rows: list[dict[str, Any]] | None = None) -> list[str]:
    known = []
    for x in load_posted():   # 1.5.6: only real posts/schedules count, not failed attempts or dry runs
        if str(x.get("status") or "scheduled") in {"failed", "would-schedule", "dry-run"}:
            continue
        known += [x.get("topic") or "", x.get("title") or ""]
    for p in buffer_rows or []:
        known.append(p.get("text") or "")
    return [k for k in known if k]


IDEA_PROMPT = """You write ideas for "Quiet Brain", a channel of funny, sarcastic 2D cartoon psychology Shorts (~1 minute).
Give {n} NEW ideas, one per line, exactly as: format|title|idea
(title: a catchy YouTube title, max 60 characters, may start with "Why", one emoji allowed, no hashtags)
Formats, in this order: {formats}
Each idea: a hyper-specific relatable everyday moment, the psychology behind it (name the effect or study),
and a calm, kind, practical fix. Sarcastic but never mean. Safe for everyone.
Do NOT repeat or closely resemble any of these already-used ideas:
{used}
"""


def write_ideas(n: int, known: list[str]) -> list[dict[str, str]]:
    formats = [FORMATS[i % len(FORMATS)] for i in range(n)]
    prompt = IDEA_PROMPT.format(n=n, formats=", ".join(formats), used="\n".join("- " + k[:140] for k in known[-150:]))
    out: list[dict[str, str]] = []
    for _attempt in range(3):
        try:
            text = idea_writer(prompt) if idea_writer else _llm(prompt)
        except Exception:
            text = ""
        for line in text.splitlines():
            if "|" not in line:
                continue
            parts = [s.strip(" -*0123456789.") if i == 0 else s.strip() for i, s in enumerate(line.split("|", 2))]
            fmt, title, idea = (parts + ["", ""])[:3] if len(parts) == 3 else (parts[0], "", parts[1])
            fmt = fmt if fmt in FORMATS else formats[len(out) % len(formats)]
            if len(idea) > 30 and not is_duplicate(idea, known + [o["idea"] for o in out]):
                out.append({"format": fmt, "idea": idea, "title": (title or _title(idea))[:70]})
            if len(out) >= n:
                return out
    return out


RETRY_NOTE = """
Your last answer repeated a used topic or was empty. Pick a clearly DIFFERENT everyday moment.
Topics already used (do not use any of them):
{used}
"""


def pick_idea(known: list[str], say: Callable[[str], Any] | None = None) -> tuple[dict[str, str], str]:
    """1.5.6: never stop just because the model repeated itself. Returns (item, source)."""
    import random

    import qb_idea_bank
    for attempt in range(3):                       # 1) model, up to 3 tries, explicit used list on retries
        got = write_ideas(1, known) if attempt == 0 else _retry_ideas(known)
        if got:
            return got[0], "model"
    bank = qb_idea_bank.ideas()                    # 2) built-in bank, unused first
    fresh = [b for b in bank if not is_duplicate(b["idea"], known) and not is_duplicate(b["title"], known)]
    if fresh:
        if say:
            say("The model kept repeating used topics, so I picked an unused idea from the built-in idea bank.")
        return random.choice(fresh), "bank"
    base = random.choice(bank)                     # 3) a new angle on an old topic
    where, how = random.choice(qb_idea_bank.ANGLES)
    if say:
        say("Every bank idea is used already, so I'm making a new angle on an old topic.")
    return {"format": base["format"], "title": (base["title"] + " " + where)[:70],
            "idea": base["idea"] + f" New angle: {how}."}, "variant"


def _retry_ideas(known: list[str]) -> list[dict[str, str]]:
    old = IDEA_PROMPT
    try:
        globals()["IDEA_PROMPT"] = IDEA_PROMPT + RETRY_NOTE
        return write_ideas(1, known)
    finally:
        globals()["IDEA_PROMPT"] = old


def _llm(prompt: str) -> str:
    import llm

    return str(llm.text(prompt))


# ---------- render / verify / host ----------
def _no_window() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


def render(day_dir: Path, n: int, item: dict[str, str], vts_dir: str, length: int = 60) -> Path:
    out = day_dir / f"short{n}"
    final = day_dir / f"qb-short{n}.mp4"
    if final.is_file() and (day_dir / f"short{n}.json").is_file():
        return final
    env = dict(os.environ, ANIM="2d", MOTION="smooth", FORMAT=item["format"], TONE="sarcastic",
               HUMOUR=os.environ.get("HUMOUR", "2"), IDEA=item["idea"])
    if os.name == "nt" and not env.get("CHROME"):
        for c in (r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                  r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"):
            if Path(c).is_file():
                env["CHROME"] = c
                break
    node = shutil.which("node") or "node"
    for attempt in range(3):
        with open(str(out) + ".log", "a", encoding="utf-8") as log:
            subprocess.run([node, "tests/live/e2e-live.js", str(length), str(out)], cwd=vts_dir, env=env,
                           stdout=log, stderr=subprocess.STDOUT, timeout=1500, creationflags=_no_window())
        if Path(str(out) + ".json").is_file() and Path(str(out) + ".mp4").is_file():
            break
        time.sleep(30 * (attempt + 1))
    src = Path(str(out) + ".mp4")
    if not src.is_file():
        raise RuntimeError(f"Short {n} did not render; see {out}.log")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                    "-movflags", "+faststart", str(final)], check=True, creationflags=_no_window())
    return final


def verify(path: Path) -> dict[str, Any]:
    probe = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
                                      capture_output=True, text=True, check=True, creationflags=_no_window()).stdout)
    v = next((s for s in probe["streams"] if s["codec_type"] == "video"), {})
    a = next((s for s in probe["streams"] if s["codec_type"] == "audio"), {})
    num, den = (v.get("r_frame_rate") or "0/1").split("/")
    fps = float(num) / max(1.0, float(den))
    dur = float(probe["format"].get("duration") or 0)
    vol = subprocess.run(["ffmpeg", "-i", str(path), "-af", "volumedetect", "-vn", "-f", "null", "-"],
                         capture_output=True, text=True, creationflags=_no_window()).stderr
    m = re.search(r"mean_volume:\s*(-?[\d.]+)", vol)
    mean = float(m.group(1)) if m else -99.0
    problems = []
    if (v.get("width"), v.get("height")) != (1080, 1920):
        problems.append("not 1080x1920")
    if v.get("codec_name") != "h264" or a.get("codec_name") != "aac":
        problems.append("needs h264 + aac")
    if not 23 <= fps <= 60:
        problems.append(f"fps {fps:.1f}")
    if not 0 < dur < 60:
        problems.append(f"duration {dur:.1f}s")
    if mean < -50:
        problems.append("audio is silent")
    return {"ok": not problems, "problems": problems, "duration_s": round(dur, 1), "fps": round(fps, 1)}


def host(day: str, path: Path) -> str:
    gh = shutil.which("gh")
    if not gh:
        raise RuntimeError("GitHub CLI (gh) is needed to host the video for Buffer.")
    exists = subprocess.run([gh, "release", "view", day, "-R", HOST_REPO], capture_output=True,
                            creationflags=_no_window()).returncode == 0
    if not exists:
        subprocess.run([gh, "release", "create", day, "-R", HOST_REPO, "-t", day, "-n", "Quiet Brain Shorts"],
                       check=True, capture_output=True, creationflags=_no_window())
    subprocess.run([gh, "release", "upload", day, str(path), "-R", HOST_REPO, "--clobber"], check=True,
                   capture_output=True, creationflags=_no_window())
    url = f"https://github.com/{HOST_REPO}/releases/download/{day}/{path.name}"
    with urllib.request.urlopen(urllib.request.Request(url, method="HEAD"), timeout=60) as r:
        if r.status != 200:
            raise RuntimeError(f"Hosted video answered {r.status}")
    return url


# ---------- posts ----------
def youtube_input(item: dict[str, Any], due: str, url: str) -> dict[str, Any]:
    title = re.sub(r"\s*#shorts\b", "", item["title"], flags=re.I).strip()[:90] + " #shorts"
    tags = " ".join(dict.fromkeys(["#shorts", "#psychology", "#quietbrain"] + [t for t in item.get("yt_tags", [])
                                                                            if t.lower() != "#shorts"]))
    return {"channelId": YOUTUBE_CHANNEL, "schedulingType": "automatic", "mode": "customScheduled", "dueAt": due,
            "text": f"{item.get('description') or item['title']}\n\n— Quiet Brain 🧠\n{tags}",
            "assets": [{"video": {"url": url}}],
            "metadata": {"youtube": {"title": title, "categoryId": "27", "privacy": "public", "notifySubscribers": False,
                                     "madeForKids": False, "embeddable": True, "isAiGenerated": False}}}


def tiktok_input(item: dict[str, Any], due: str, url: str) -> dict[str, Any]:
    cap = re.sub(r"\s+", " ", item.get("tiktok_caption") or item["title"]).strip()
    for tag in ("#fyp", "#quietbrain"):
        if tag not in cap.lower():
            cap += " " + tag
    return {"channelId": TIKTOK_CHANNEL, "schedulingType": "automatic", "mode": "customScheduled", "dueAt": due,
            "text": cap, "assets": [{"video": {"url": url}}], "metadata": {"tiktok": {"isAiGenerated": False}}}


def free_slots(scheduled_count: int) -> int:
    return max(0, FREE_PLAN_LIMIT - scheduled_count)


def slot_times(day: str, now: dt.datetime, slots: list[str] = SLOTS) -> list[str]:
    """Slots on that day still in the future (+10 min), then the next evening's slots."""
    out = []
    d0 = dt.date.fromisoformat(day)
    for add in range(0, 4):
        for hm in slots:
            h, m = map(int, hm.split(":"))
            t = dt.datetime.combine(d0 + dt.timedelta(days=add), dt.time(h, m), IST)
            if t > now + dt.timedelta(minutes=10):
                out.append(t.isoformat(timespec="seconds"))
    return out


def schedule_day(day: str, items: list[dict[str, Any]], scheduled: list[dict[str, Any]], dry_run: bool,
                 now: dt.datetime | None = None) -> list[dict[str, Any]]:
    """YouTube first into free slots; TikTok twins after, or pending-overflow."""
    now = now or dt.datetime.now(IST)
    free = free_slots(len(scheduled))
    taken = {p.get("dueAt") for p in scheduled}
    times = [t for t in slot_times(day, now) if t not in taken]
    plan = []
    for it in items:
        due = times.pop(0) if times else None
        entry = {"date": day, "n": it["n"], "file": f"qb-short{it['n']}.mp4", "title": it["title"], "topic": it["idea"],
                 "format": it["format"], "platform": "youtube+tiktok", "video_url": it["video_url"],
                 "yt_isAiGenerated": False, "tiktok_isAiGenerated": False, "tiktok_caption": tiktok_input(it, "", "")["text"],
                 "anim": "2d smooth", "duration_s": it.get("duration_s")}
        if due is None or free <= 0:
            entry.update(status="pending-overflow", tiktok_status="pending-overflow")
        else:
            entry["scheduled_time"] = due
            entry["yt_request"] = youtube_input(it, due, it["video_url"])
            free -= 1
            entry["status"] = "would-schedule" if dry_run else "scheduled"
            entry["tiktok_status"] = "pending-overflow"
        plan.append(entry)
    for entry in plan:                     # TikTok twins take whatever is left
        if entry.get("scheduled_time") and free > 0:
            it = next(i for i in items if i["n"] == entry["n"])
            entry["tiktok_request"] = tiktok_input(it, entry["scheduled_time"], it["video_url"])
            entry["tiktok_scheduled_time"] = entry["scheduled_time"]
            entry["tiktok_status"] = "would-schedule" if dry_run else "scheduled"
            free -= 1
    if not dry_run:
        for entry in plan:
            if "yt_request" in entry:
                r = create_post(entry.pop("yt_request"))
                entry["buffer_post_id"] = r.get("id", "")
                if not r["ok"]:
                    entry["status"], entry["error"] = "failed", r["error"]
            if "tiktok_request" in entry:
                r = create_post(entry.pop("tiktok_request"))
                entry["tiktok_buffer_id"] = r.get("id", "")
                if not r["ok"]:
                    entry["tiktok_status"] = "pending-overflow"
            add_posted(entry)
    return plan


def fill_overflow(dry_run: bool = False, now: dt.datetime | None = None) -> dict[str, Any]:
    """The overflow filler: queue TikTok twins marked pending-overflow as Buffer slots free up."""
    now = now or dt.datetime.now(IST)
    scheduled = buffer_posts(["scheduled"])
    free = free_slots(len(scheduled))
    known_urls = {(a.get("source") or "") for p in scheduled if p.get("channelService") == "tiktok" for a in p.get("assets") or []}
    taken = {p.get("dueAt") for p in scheduled if p.get("channelService") == "tiktok"}
    queued = []
    for e in sorted(load_posted(), key=lambda x: (x.get("date", ""), x.get("n", 0))):
        if free <= 0:
            break
        if e.get("tiktok_status") != "pending-overflow" or not e.get("video_url"):
            continue
        if e["video_url"] in known_urls:            # Grok Bot already queued it
            e["tiktok_status"] = "scheduled"
            add_posted(e) if not dry_run else None
            continue
        want = e.get("scheduled_time")
        due = want if want and dt.datetime.fromisoformat(want) > now + dt.timedelta(minutes=10) else None
        if due is None or due in taken:
            due = next(t for t in slot_times(now.date().isoformat(), now, OVERFLOW_SLOTS) if t not in taken)
        req = {"channelId": TIKTOK_CHANNEL, "schedulingType": "automatic", "mode": "customScheduled", "dueAt": due,
               "text": e.get("tiktok_caption") or (e.get("title", "") + " #fyp #quietbrain"),
               "assets": [{"video": {"url": e["video_url"]}}], "metadata": {"tiktok": {"isAiGenerated": False}}}
        taken.add(due)
        free -= 1
        if dry_run:
            queued.append({"file": e.get("file"), "date": e.get("date"), "dueAt": due, "request": req})
            continue
        r = create_post(req)
        if r["ok"]:
            e.update(tiktok_status="scheduled", tiktok_buffer_id=r["id"], tiktok_scheduled_time=due)
            add_posted(e)
            queued.append({"file": e.get("file"), "date": e.get("date"), "dueAt": due, "id": r["id"]})
    return {"ok": True, "free_before": free_slots(len(scheduled)), "queued": queued, "dry_run": dry_run}


# ---------- the daily run ----------
def run_day(day: str | None = None, dry_run: bool = True, render_videos: bool = False,
            progress: Callable[[str], Any] | None = None) -> dict[str, Any]:
    say = progress or (lambda m: None)
    st = settings()
    day = day or dt.datetime.now(IST).date().isoformat()
    n = max(1, min(6, st["per_day"]))
    scheduled = buffer_posts(["scheduled"])
    recent = buffer_posts(["sent"], max_pages=4)
    known = known_ideas(scheduled + recent)
    say(f"Writing {n} new Quiet Brain ideas (checked against {len(known)} used ones)…")
    ideas = write_ideas(n, known)
    while len(ideas) < n:          # 1.5.8: model retries, idea bank, then a new angle; never stop for repeats
        extra, _src = pick_idea(known + [x["idea"] for x in ideas] + [x["title"] for x in ideas])
        ideas.append(extra)
    if len(ideas) < n:
        return {"ok": False, "error": f"Only {len(ideas)} unique ideas came back; nothing was scheduled.", "ideas": ideas}
    day_dir = _storage() / day
    day_dir.mkdir(parents=True, exist_ok=True)
    (day_dir / "ideas.txt").write_text("\n".join(f"{i + 1}|{x['format']}|{x['idea']}" for i, x in enumerate(ideas)),
                                       encoding="utf-8")
    items = []
    for i, x in enumerate(ideas, 1):
        item = {"n": i, **x, "title": x.get("title") or _title(x["idea"]), "video_url": f"https://github.com/{HOST_REPO}/releases/download/{day}/qb-short{i}.mp4"}
        if render_videos and not dry_run:
            if not st["vts_dir"]:
                return {"ok": False, "error": "Set the Voice to Short folder in Settings > Quiet Brain Shorts."}
            say(f"Rendering Short {i} of {n} (2D, ~1 min)…")
            path = render(day_dir, i, x, st["vts_dir"], length=30)   # 1.5.8: same length as the one-Short run
            check = verify(path)
            if not check["ok"]:
                say(f"Short {i} failed checks: {', '.join(check['problems'])}; skipped.")
                continue
            item["duration_s"] = check["duration_s"]
            pkg = _pkg(day_dir, i)
            item.update(title=pkg.get("title") or item["title"], tiktok_caption=pkg.get("tiktokCaption", ""),
                        yt_tags=pkg.get("hashtags") or [], description=pkg.get("hooks", [""])[0] if pkg.get("hooks") else "")
            if pkg.get("tiktokHashtags"):
                item["tiktok_caption"] = (item["tiktok_caption"] + " #fyp #quietbrain " + " ".join(pkg["tiktokHashtags"])).strip()
            item["video_url"] = host(day, path)
        items.append(item)
    plan = schedule_day(day, items, scheduled, dry_run=dry_run)
    yt = sum(1 for p in plan if p["status"] in {"scheduled", "would-schedule"})
    tt = sum(1 for p in plan if p.get("tiktok_status") in {"scheduled", "would-schedule"})
    msg = (f"{'Dry run: would schedule' if dry_run else 'Scheduled'} {yt} YouTube Shorts and {tt} TikToks for {day}; "
           f"{len(plan) - tt} TikTok twin(s) wait for free Buffer slots ({len(scheduled)}/{FREE_PLAN_LIMIT} used).")
    say(msg)
    return {"ok": True, "message": msg, "day": day, "plan": plan, "dry_run": dry_run}


def _title(idea: str) -> str:
    core = re.sub(r"^(pov|nobody|your brain be like|expectation vs reality|brain vs me|storytime)\s*[:/]\s*", "", idea, flags=re.I)
    core = re.split(r"[(;]", core)[0].strip().rstrip(".")
    return ("Why " + core[0].lower() + core[1:] if not core.lower().startswith("why") else core)[:80]


def _pkg(day_dir: Path, n: int) -> dict[str, Any]:
    try:
        p = json.loads((day_dir / f"short{n}.pkg.json").read_text(encoding="utf-8"))
        return p.get("pkg") or p
    except (OSError, ValueError):
        return {}


# ---------- built-in routine ----------
def routine_tick(now: dt.datetime | None = None) -> dict[str, Any] | None:
    """Called by the scheduler: daily run at 11:00 IST and the overflow filler every 30 min. Off by default."""
    if not settings()["enabled"]:
        return None
    try:
        import safe_mode

        if safe_mode.paused():
            return None
    except Exception:
        pass
    now = now or dt.datetime.now(IST)
    stamp = _storage() / "last_run.json"
    try:
        last = json.loads(stamp.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        last = {}
    out = None
    sh, sm = map(int, settings()["start_time"].split(":"))
    if (now.hour, now.minute) >= (sh, sm) and last.get("day") != now.date().isoformat():
        stamp.write_text(json.dumps({**last, "day": now.date().isoformat()}), encoding="utf-8")
        out = run_day(now.date().isoformat(), dry_run=False, render_videos=True)
    if time.time() - float(last.get("filler", 0)) >= 1800:
        last = json.loads(stamp.read_text(encoding="utf-8")) if stamp.is_file() else {}
        stamp.write_text(json.dumps({**last, "filler": time.time()}), encoding="utf-8")
        out = out or fill_overflow()
    return out


def start_routine(every: float = 300.0) -> None:
    def loop() -> None:
        while True:
            try:
                r = routine_tick()
                if r and (r.get("message") or r.get("error")):
                    import background

                    background.notify("Quiet Brain Shorts", r.get("message") or r["error"])
                    if r.get("day"):
                        _post_report(r)
            except Exception as exc:
                print(f"[quiet-brain] {exc}", flush=True)
            time.sleep(every)

    threading.Thread(target=loop, daemon=True, name="quiet-brain-shorts").start()


def report_text(r: dict[str, Any]) -> str:
    """1.5.8: the titles and times, for Pedro's chat after each daily run."""
    if not r.get("ok"):
        return "Daily Shorts stopped: " + str(r.get("error") or "unknown error") + " Nothing more was scheduled."
    lines = [r.get("message", "")]
    for e in r.get("plan") or []:
        def t(v: Any) -> str:
            return dt.datetime.fromisoformat(v).strftime("%I:%M %p").lstrip("0") + " IST" if v else "waiting for a free Buffer slot"
        lines.append(f"{e.get('n')}. {e.get('title')} - YouTube {t(e.get('scheduled_time')) if e.get('status') == 'scheduled' else e.get('status')}"
                     f", TikTok {t(e.get('tiktok_scheduled_time')) if e.get('tiktok_status') == 'scheduled' else 'waiting for a free Buffer slot'}")
    return "\n".join(x for x in lines if x)


def _post_report(r: dict[str, Any]) -> None:
    try:
        import bg_progress
        bg_progress.Reporter("bot-shorts-poster", "Daily Shorts").final(report_text(r), ok=bool(r.get("ok")))
    except Exception as exc:
        print(f"[quiet-brain] report: {exc}", flush=True)


def quiet_brain_shorts_dry_run() -> dict[str, Any]:
    """Tool: plan today's Quiet Brain Shorts without rendering, uploading or posting."""
    try:
        return run_day(dry_run=True)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


# ---------- 1.5.4: the Shorts Poster bot's own workflow ----------
WORKFLOW = """Shorts Poster workflow (Quiet Brain), one Short at a time:
1) pick a fresh psychology / self-help topic from the idea bank (never a repeat; history kept)
2) write a funny, sarcastic, punchy 30-60 s script
3) render a 9:16 2D video with the Voice to Short pipeline
4) quality-check it (1080x1920, 23-60 fps, under 60 s, audio not silent, no blank frames)
5) write the title, description and hashtags
6) schedule it via the Buffer API to YouTube (Quiet Brain) and TikTok at free slots, isAiGenerated=false,
   never over the 10-post free queue (asks Pedro first)
7) post a summary here (title, time, link) and notify; on any failure say exactly what failed."""

BOT_ROLE = ("You are the Shorts Poster for Pedro's Quiet Brain channel. You have ONE workflow and it is built in: "
            "the make_quiet_brain_short tool (dry_run=true renders and checks only; dry_run=false also schedules on "
            "YouTube + TikTok via Buffer after Pedro's yes on the card). Use shorts_status to check the Buffer token "
            "and setup before saying anything is missing - never guess. You do NOT use, resume, pause or mention his "
            "old routines (workflow-1..4, all-4-workflows-sequence, automated-youtube-video-pipeline, brobot); they are "
            "not yours. The daily automatic run is the 'Daily Shorts' switch in Settings > Quiet Brain Shorts, which "
            "is separate from the Routines list; manual runs work without it. Report results plainly; never claim a "
            "post was scheduled unless the tool returned it. " + WORKFLOW)
BOT_TOOLS = ["make_quiet_brain_short", "shorts_status", "quiet_brain_shorts_dry_run", "list_files"]


def check_token() -> dict[str, Any]:
    """Read-only `{ account { id } }` against Buffer. Never returns or logs the token."""
    tok = _token()
    if not tok:
        return {"saved": False, "valid": False, "message": "No Buffer token is saved yet (Settings > Quiet Brain Shorts)."}
    if transport is not None:
        return {"saved": True, "valid": True, "message": "Buffer token saved (test transport)."}
    req = urllib.request.Request(API, data=json.dumps({"query": "{ account { id } }"}).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {tok}"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            out = json.loads(r.read().decode("utf-8"))
    except Exception as exc:
        code = getattr(exc, "code", "")
        return {"saved": True, "valid": False, "message": f"Buffer token is saved but Buffer did not accept it ({code or type(exc).__name__})."}
    ok = bool(((out.get("data") or {}).get("account") or {}).get("id"))
    return {"saved": True, "valid": ok, "message": "Buffer token is saved and Buffer accepts it." if ok else
            "Buffer token is saved but Buffer rejected it: " + "; ".join(e.get("message", "") for e in out.get("errors", []))[:200]}


def shorts_status() -> dict[str, Any]:
    st = settings()
    tok = check_token()
    try:
        queued = len(buffer_posts(["scheduled"])) if tok["valid"] else None
    except Exception:
        queued = None
    lines = [tok["message"],
             ("Daily Shorts switch (Settings > Quiet Brain Shorts) is ON." if st["enabled"] else
              "Daily Shorts switch (Settings > Quiet Brain Shorts) is OFF, so nothing posts automatically. "
              "This is not the Routines list. Manual runs still work."),
             ("Setup ready." if st["ready"] else "Still missing: " + ", ".join(st["missing"]) + "."),
             (f"Buffer queue: {queued}/{FREE_PLAN_LIMIT} scheduled." if queued is not None else "")]
    return {"ok": True, "token_saved": tok["saved"], "token_valid": tok["valid"], "daily_switch_on": st["enabled"],
            "ready": st["ready"], "missing": st["missing"], "queued": queued,
            "message": " ".join(x for x in lines if x)}


def _history_file() -> Path:
    return _storage() / "idea_history.json"


def idea_history() -> list[dict[str, Any]]:
    try:
        d = json.loads(_history_file().read_text(encoding="utf-8"))
        return d if isinstance(d, list) else []
    except (OSError, ValueError):
        return []


def _remember_idea(item: dict[str, Any], status: str) -> None:
    h = idea_history()
    h.append({"at": dt.datetime.now(IST).isoformat(timespec="seconds"), "idea": item.get("idea"),
              "title": item.get("title"), "format": item.get("format"), "status": status})
    _history_file().write_text(json.dumps(h[-500:], indent=1, ensure_ascii=False), encoding="utf-8")


def blank_frames(path: Path) -> float:
    """Seconds of (near) black video, via ffmpeg blackdetect."""
    err = subprocess.run(["ffmpeg", "-i", str(path), "-vf", "blackdetect=d=0.5:pix_th=0.10", "-an", "-f", "null", "-"],
                         capture_output=True, text=True, creationflags=_no_window()).stderr
    return round(sum(float(x) for x in re.findall(r"black_duration:([\d.]+)", err)), 1)


_JOB: dict[str, Any] = {"running": False}


def make_quiet_brain_short(dry_run: Any = True) -> dict[str, Any]:
    """Run the built-in workflow for ONE Short in the background; progress and the result post in this chat."""
    dry = not (dry_run is False or str(dry_run).strip().casefold() in {"false", "0", "no"})
    if _JOB.get("running"):
        return {"ok": False, "error": "A Short is already being made; I'll post here when it's done."}
    st = settings()
    if not st["vts_dir"] or not (Path(st["vts_dir"]) / "tests" / "live" / "e2e-live.js").is_file():
        return {"ok": False, "error": "The Voice to Short folder isn't set up: Settings > Quiet Brain Shorts needs the folder "
                f"that contains tests\\live\\e2e-live.js (now: {st['vts_dir'] or 'not set'}). Nothing was made."}
    if not dry:
        tok = check_token()
        if not tok["valid"]:
            return {"ok": False, "error": tok["message"] + " Nothing was made or posted."}
    import bg_progress
    rep = bg_progress.Reporter(bg_progress.current_session(), "Shorts Poster" + (" (dry run)" if dry else ""))
    _JOB["running"] = True
    _JOB["buffer_touched"] = False

    def run() -> None:
        try:
            out = _workflow(dry, rep.milestone)
            rep.final(out["summary"], ok=True, image=out.get("thumb", ""))
        except Exception as exc:
            rep.final(f"Stopped: {str(exc)[:300]}. Nothing was posted." if dry else
                      (f"Stopped: {str(exc)[:300]}. " + ("Check the Buffer queue before trying again; " if _JOB.get("buffer_touched") else "nothing was sent to Buffer. ")
                       + "Nothing was marked as posted."), ok=False)
        finally:
            _JOB["running"] = False
    threading.Thread(target=run, daemon=True, name="qb-short").start()
    return {"ok": True, "message": ("Dry run started: idea, script, render and checks only, nothing will be posted. "
                                    if dry else "Started: I'll make the Short and schedule it. ")
            + "I'll post progress and the result here."}


def _workflow(dry: bool, say: Callable[[str], Any]) -> dict[str, Any]:
    st = settings()
    day = dt.datetime.now(IST).date().isoformat()
    scheduled = buffer_posts(["scheduled"]) if _token() else []
    recent = buffer_posts(["sent"], max_pages=4) if _token() else []
    known = known_ideas(scheduled + recent) + [h.get("idea") or "" for h in idea_history() if h.get("status") == "scheduled"]
    first, _src = pick_idea([k for k in known if k], say)
    ideas = [first]
    day_dir = _storage() / day
    day_dir.mkdir(parents=True, exist_ok=True)
    n = 1 + max([int(m.group(1)) for f in day_dir.glob("qb-short*.mp4") if (m := re.search(r"(\d+)", f.stem))] or [0])
    item = {"n": n, **ideas[0]}
    item["title"] = item.get("title") or _title(item["idea"])
    say(f"Topic: {item['title']} ({item['format']}). Writing the script and rendering the 9:16 video (a few minutes).")
    path = render(day_dir, n, item, st["vts_dir"], length=30)   # 1.5.5: a real Voice to Short length id ("55" fell back to the saved default)
    check = verify(path)
    black = blank_frames(path)
    if black >= 1.0:
        check["ok"] = False
        check["problems"].append(f"{black}s of blank frames")
    if not check["ok"]:
        _remember_idea(item, "failed-check")
        raise RuntimeError("the video failed the quality check: " + ", ".join(check["problems"]) + f" ({path})")
    say(f"Video passed checks: {check['duration_s']} s, {check['fps']} fps, audio OK, no blank frames.")
    pkg = _pkg(day_dir, n)
    item.update(title=pkg.get("title") or item["title"], duration_s=check["duration_s"],
                tiktok_caption=pkg.get("tiktokCaption", ""), yt_tags=pkg.get("hashtags") or [],
                description=(pkg.get("hooks") or [""])[0])
    thumb = day_dir / f"qb-short{n}.jpg"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", "3", "-i", str(path), "-frames:v", "1", str(thumb)],
                   creationflags=_no_window())
    if dry:
        _remember_idea(item, "dry-run")
        return {"summary": f"Dry run done: \"{item['title']}\" ({check['duration_s']} s) rendered and checked. "
                           f"Nothing was posted. Video: {path}", "thumb": str(thumb) if thumb.is_file() else ""}
    if free_slots(len(scheduled)) <= 0:
        _remember_idea(item, "made-not-scheduled")
        raise RuntimeError(f"the Buffer queue is full ({len(scheduled)}/{FREE_PLAN_LIMIT}); the video is saved at {path}")
    say("Uploading the video for Buffer and scheduling it.")
    _JOB["buffer_touched"] = True
    item["video_url"] = host(day, path)
    plan = schedule_day(day, [item], scheduled, dry_run=False)
    e = plan[0]
    if e.get("status") != "scheduled":
        _remember_idea(item, "schedule-failed")
        raise RuntimeError("Buffer did not schedule it: " + str(e.get("error") or e.get("status")))
    _remember_idea(item, "scheduled")
    tt = "TikTok too" if e.get("tiktok_status") == "scheduled" else "TikTok waits for a free Buffer slot"
    return {"summary": f"Scheduled \"{item['title']}\" on YouTube (Quiet Brain) for {e['scheduled_time']} IST; {tt}. "
                       f"Video: {item['video_url']}", "thumb": str(thumb) if thumb.is_file() else ""}


def ensure_bot_workflow() -> bool:
    """Give an existing Shorts Poster bot the built-in workflow (role + tools). Touches no routine."""
    try:
        import bots
        b = bots.get_bot("shorts-poster") or bots.get_bot("Shorts Poster")
        if not b or (b.get("role") == BOT_ROLE and set(BOT_TOOLS) <= set(b.get("tools") or [])):
            return False
        bots.save_bot({**b, "role": BOT_ROLE, "tools": sorted(set(BOT_TOOLS))})
        return True
    except Exception:
        return False


DECLARATIONS = [{"name": "quiet_brain_shorts_dry_run",
                 "description": "Plan today's 6 Quiet Brain Shorts (ideas, titles, Buffer slots, overflow) without posting anything.",
                 "parameters": {"type": "object", "properties": {}}},
                {"name": "shorts_status",
                 "description": "Check Quiet Brain Shorts setup: is the Buffer token saved and accepted by Buffer (read-only), "
                                "is the Daily Shorts switch on, what is missing, Buffer queue use. Use before saying anything is missing.",
                 "parameters": {"type": "object", "properties": {}}},
                {"name": "make_quiet_brain_short",
                 "description": "Run the Shorts Poster workflow for ONE Short in the background: fresh topic, script, 9:16 2D render, "
                                "quality check, title/description/hashtags, then (only when dry_run is false, after Pedro's yes) "
                                "schedule on YouTube + TikTok via Buffer. Progress and the result are posted in the chat.",
                 "parameters": {"type": "object", "properties": {
                     "dry_run": {"type": "boolean", "description": "true (default): render and check only, never post."}}}}]
TOOLS = {"quiet_brain_shorts_dry_run": quiet_brain_shorts_dry_run, "shorts_status": shorts_status,
         "make_quiet_brain_short": make_quiet_brain_short}
