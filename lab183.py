"""1.8.3 Lab: the remaining big features, all on the free Gemini key.

swarm          Swarm research: 4 researcher "agents" attack a question from different angles in parallel,
               a judge merges them into one answer with agreements, disagreements and confidence.
vision         Camera vision agent: a phone/PC camera frame + a question -> Gemini vision answer.
improve        Self-improving bots: reviews a bot's recent chat (and thumbs-down reactions) and proposes a
               better role text + new skills. Nothing changes until Pedro taps Apply.
predict        Predictive bot: learns when Pedro usually asks for what (from chat history) and suggests the
               next likely tasks for this hour.
company        Bot company: a CEO bot splits a goal into roles (researcher, writer, coder, critic...), each role
               works in turn, the CEO delivers. Runs as a background job.
autopilot      YouTube autopilot planner: ideas -> scripts for 2D psychology Shorts, isAiGenerated=false,
               fits into Buffer's free 10-post limit *after* the daily Quiet Brain Shorts routine takes its
               slots, never on the routine's own times. It only plans; queueing reuses the routine's approved
               pipeline when Pedro taps Queue.
osinfo         Ped OS control center: one status snapshot of everything (bots, routines, check-ins, Studio).
voice_clone    Voice clone with consent: records Pedro's consent sentence + samples, keeps them only on this PC,
               and picks the closest free Gemini voice. A true clone needs a local open-source engine.
"""

from __future__ import annotations

import base64
import datetime as dt
import json
import os
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any


def _store() -> Path:
    base = Path(os.environ.get("STORAGE_DIR") or Path(__file__).resolve().parent / "storage") / "lab"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _ai(prompt: str, images: list[bytes] | None = None) -> str:
    import llm
    return llm.text(prompt, images or None).strip()


def _aj(prompt: str, images: list[bytes] | None = None) -> Any:
    import llm
    return llm.json_from(_ai(prompt, images))


def _nokey(exc: Exception) -> dict[str, Any]:
    return {"ok": False, "error": "This needs your free Gemini key (Settings) and internet.", "detail": str(exc)[:160]}


_jobs: dict[str, dict[str, Any]] = {}


def job(jid: str) -> dict[str, Any]:
    j = _jobs.get(jid)
    return {"ok": bool(j), **(j or {"error": "No such job."})}


def _bg(kind: str, fn, *a) -> dict[str, Any]:
    jid = uuid.uuid4().hex[:8]
    _jobs[jid] = {"kind": kind, "status": "working", "log": [], "started": time.time()}

    def run() -> None:
        try:
            _jobs[jid].update(status="done", result=fn(_jobs[jid], *a))
        except Exception as exc:
            _jobs[jid].update(status="failed", error=str(exc)[:300])
        try:
            import checkins
            checkins.post(kind, f"{kind.title()} finished: {_jobs[jid].get('status')}", key=f"{kind}-{jid}")
        except Exception:
            pass
    threading.Thread(target=run, daemon=True).start()
    return {"ok": True, "job": jid}


# ---------------- swarm research ----------------
ANGLES = [("Fact finder", "the key facts, numbers and definitions"), ("Skeptic", "what is uncertain, disputed or commonly wrong"),
          ("Practical", "what Pedro should actually do, step by step, cheapest option first"), ("Explorer", "surprising angles, alternatives, what most people miss")]


def _swarm(j: dict[str, Any], question: str) -> dict[str, Any]:
    def one(a):
        name, focus = a
        j["log"].append(f"{name} researching…")
        try:
            txt = _ai(f"You are the {name} in a research team. Question: {question}\nFocus on {focus}. 5-8 tight bullet points. "
                      "Say 'unsure' instead of guessing. Plain text.")
        except Exception as exc:
            txt = f"(failed: {exc})"
        j["log"].append(f"{name} done")
        return {"agent": name, "notes": txt}
    with ThreadPoolExecutor(4) as ex:
        notes = list(ex.map(one, ANGLES))
    j["log"].append("Judge merging…")
    merged = _aj("You are the judge. Merge these research notes into one answer for Pedro. Reply JSON: "
                 '{"answer":"clear answer, <=180 words","agree":["..."],"disagree":["..."],"next_steps":["..."],"confidence":"low|medium|high"}\n\n'
                 + json.dumps(notes, ensure_ascii=False)[:24000] + f"\n\nQuestion: {question}")
    return {"question": question, "agents": notes, **(merged if isinstance(merged, dict) else {"answer": str(merged)})}


def swarm(question: str) -> dict[str, Any]:
    q = " ".join(str(question or "").split())[:800]
    if not q:
        return {"ok": False, "error": "Ask a research question."}
    return _bg("swarm", _swarm, q)


# ---------------- camera vision ----------------
def vision(image_b64: str, question: str = "") -> dict[str, Any]:
    try:
        img = base64.b64decode(image_b64 or "")
    except Exception:
        img = b""
    if len(img) < 500:
        return {"ok": False, "error": "No camera picture."}
    q = " ".join(str(question or "").split())[:500] or "What do you see? Anything I should know or do?"
    try:
        txt = _ai("You are Pedro's camera assistant. Look at this live camera frame and answer briefly and practically, "
                  f"2-4 short sentences, spoken style, no markdown. Question: {q}", [img])
    except Exception as exc:
        return _nokey(exc)
    return {"ok": True, "text": txt}


# ---------------- self-improving bots ----------------
def improve(bot_id: str, apply: dict[str, Any] | None = None) -> dict[str, Any]:
    import bots
    bot = bots.get_bot(bot_id)
    if not bot:
        return {"ok": False, "error": "Pick a bot."}
    if apply:
        role = str(apply.get("role") or "").strip()
        if not role:
            return {"ok": False, "error": "Nothing to apply."}
        hist = _load("improve_history", [])
        hist.append({"t": time.time(), "bot": bot["id"], "old_role": bot.get("role", ""), "new_role": role})
        _save("improve_history", hist[-100:])
        data = dict(bot); data["role"] = role
        skills = list(bot.get("skills") or [])
        for s in apply.get("skills") or []:
            if isinstance(s, dict) and s.get("name") and s.get("steps"):
                skills.append({"name": str(s["name"])[:60], "steps": str(s["steps"])[:2000]})
        data["skills"] = skills
        bots.save_bot(data)
        return {"ok": True, "applied": True, "note": "Saved. The old version is kept in Lab history (Undo)."}
    try:
        import chat_store
        rows = chat_store.history(bots.session_for(bot), limit=60)
        ids = [r.get("id") for r in rows if r.get("id")]
        reacts = {r["id"]: r.get("reactions") or [] for r in rows}
    except Exception:
        rows, reacts = [], {}
    lines = []
    for r in rows[-40:]:
        tag = ""
        for x in reacts.get(r.get("id"), []):
            if x.get("emoji") in ("👎", "😡", "😞"):
                tag = " [PEDRO DISLIKED THIS]"
            elif x.get("emoji") in ("👍", "❤️", "🔥"):
                tag = " [PEDRO LIKED THIS]"
        lines.append(f"{r.get('role')}: {str(r.get('text') or '')[:300]}{tag}")
    if not lines:
        return {"ok": False, "error": "This bot has no chats yet to learn from."}
    try:
        out = _aj(f"You coach an AI helper bot named {bot['name']}. Its current role text:\n{bot.get('role') or '(empty)'}\n\n"
                  "Recent chat (with Pedro's reactions):\n" + "\n".join(lines) +
                  "\n\nFind what went wrong or what Pedro keeps asking for. Reply JSON: "
                  '{"lessons":["..."],"role":"improved full role text, keep what works","skills":[{"name":"...","steps":"..."}]}')
    except Exception as exc:
        return _nokey(exc)
    return {"ok": True, "bot": bot["id"], "current": bot.get("role", ""), **(out if isinstance(out, dict) else {})}


def improve_undo(bot_id: str) -> dict[str, Any]:
    import bots
    hist = _load("improve_history", [])
    last = next((h for h in reversed(hist) if h["bot"] == bot_id), None)
    bot = bots.get_bot(bot_id)
    if not last or not bot:
        return {"ok": False, "error": "Nothing to undo."}
    data = dict(bot); data["role"] = last["old_role"]; bots.save_bot(data)
    hist.remove(last); _save("improve_history", hist)
    return {"ok": True}


# ---------------- predictive bot ----------------
def predict(now: float | None = None) -> dict[str, Any]:
    import chat_store
    now = now or time.time()
    hour = time.localtime(now).tm_hour
    wd = time.localtime(now).tm_wday
    rows = []
    try:
        for s in chat_store.sessions()[:60]:
            for r in chat_store.history(str(s.get("session") or ""), limit=80):
                if r.get("role") == "user" and r.get("ts"):
                    rows.append(r)
    except Exception:
        pass
    near = [r for r in rows if abs(time.localtime(float(r["ts"])).tm_hour - hour) <= 1]
    texts = [str(r.get("text") or "")[:160] for r in near][-60:]
    if not texts:
        return {"ok": True, "hour": hour, "suggestions": [], "note": "I need a few days of chats to learn your routine."}
    try:
        out = _aj(f"It's {hour}:00 on weekday {wd}. These are things Pedro usually asks around this time:\n- " + "\n- ".join(texts) +
                  '\nPredict the 3 things he is most likely to want next. Reply JSON: {"suggestions":[{"label":"short button text","command":"exact chat command","why":"..."}]}')
        sug = (out or {}).get("suggestions") or []
    except Exception as exc:
        return _nokey(exc)
    return {"ok": True, "hour": hour, "suggestions": sug[:3], "learned_from": len(texts)}


# ---------------- bot company ----------------
def _company(j: dict[str, Any], goal: str) -> dict[str, Any]:
    j["log"].append("CEO planning the team…")
    plan = _aj(f"You are the CEO of a tiny AI company working for Pedro. Goal: {goal}\nHire 3-5 roles. Reply JSON: "
               '{"team":[{"role":"Researcher","task":"what exactly to produce"}],"deliverable":"what the CEO hands to Pedro"}')
    team = (plan or {}).get("team") or []
    work = []
    for m in team[:5]:
        j["log"].append(f"{m.get('role')} working…")
        prev = "\n\n".join(f"[{w['role']}]\n{w['output'][:3000]}" for w in work)
        out = _ai(f"You are the {m.get('role')} in Pedro's AI company. Goal: {goal}\nYour task: {m.get('task')}\n"
                  f"Work already done by teammates:\n{prev or '(none yet)'}\nDeliver your part, concrete and complete. Markdown ok.")
        work.append({"role": str(m.get("role")), "task": str(m.get("task")), "output": out})
    j["log"].append("CEO writing the final deliverable…")
    final = _ai(f"You are the CEO. Goal: {goal}\nDeliverable: {(plan or {}).get('deliverable')}\nTeam output:\n" +
                "\n\n".join(f"[{w['role']}]\n{w['output'][:5000]}" for w in work) + "\nWrite the final deliverable for Pedro. Markdown.")
    docs = Path.home() / "Documents" / "Ped Bot Company"
    docs.mkdir(parents=True, exist_ok=True)
    f = docs / (time.strftime("%Y-%m-%d %H%M ") + re.sub(r"[^\w -]", "", goal)[:50].strip() + ".md")
    f.write_text(f"# {goal}\n\n{final}\n\n---\n\n" + "\n\n".join(f"## {w['role']}\n_{w['task']}_\n\n{w['output']}" for w in work), encoding="utf-8")
    return {"goal": goal, "team": [{"role": w["role"], "task": w["task"]} for w in work], "final": final, "file": str(f)}


def company(goal: str) -> dict[str, Any]:
    g = " ".join(str(goal or "").split())[:1000]
    if not g:
        return {"ok": False, "error": "Give the company a goal."}
    return _bg("company", _company, g)


# ---------------- YouTube autopilot planner ----------------
def autopilot_plan(count: int = 3, now: dt.datetime | None = None) -> dict[str, Any]:
    import quiet_brain_shorts as qb
    IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
    now = now or dt.datetime.now(IST)
    st = qb.settings()
    try:
        scheduled = qb.buffer_posts(["scheduled"]) if qb.readiness()["checks"].get("buffer_token") else []
    except Exception:
        scheduled = []
    routine_on = bool(st.get("enabled"))
    per_day = int(st.get("per_day") or len(qb.SLOTS)) if routine_on else 0
    free = qb.free_slots(len(scheduled))
    reserve = min(free, per_day * 2 if routine_on else 0)   # keep room for the next two days of the routine
    room = max(0, free - reserve)
    known = qb.known_ideas(scheduled)
    n = max(1, min(int(count or 3), 5))   # queued ideas replace routine ideas, they never add posts
    ideas = []
    if n:
        try:
            ideas = _aj(f"Write {n} NEW funny, sarcastic psychology YouTube Shorts for 2D animation (stick-figure/flat cartoon style, "
                        f"not realistic, not AI-avatar). Avoid these existing ideas: {known[-60:]}\nReply JSON: "
                        '{"ideas":[{"title":"<60 chars","hook":"first line","script":"~45s voiceover","scenes":["2D scene 1","..."]}]}').get("ideas", [])[:n]
        except Exception as exc:
            return {**_nokey(exc), "room": room}
    plan = [{**i, "isAiGenerated": False, "style": "2D"} for i in ideas
            if not qb.is_duplicate(str(i.get("title", "")), known)]
    _save("autopilot_plan", plan)
    return {"ok": True, "buffer_scheduled": len(scheduled), "buffer_limit": qb.FREE_PLAN_LIMIT, "reserved_for_routine": reserve,
            "room": room, "routine_slots": qb.SLOTS, "queued": len(_load("autopilot_queue", [])), "plan": plan,
            "note": "Plan only. Queue hands an idea to the daily Shorts routine, which renders it in 2D and posts with isAiGenerated=false in its own slots - so nothing clashes and the Buffer 10-post limit is respected."}


def autopilot_queue(index: int) -> dict[str, Any]:
    """Approve one planned idea: the daily Quiet Brain routine renders it (2D, isAiGenerated=false) in its own slots."""
    plan = _load("autopilot_plan", [])
    if not 0 <= int(index) < len(plan):
        return {"ok": False, "error": "That idea is gone - plan again."}
    q = _load("autopilot_queue", [])
    it = plan[int(index)]
    q.append({"format": "POV", "title": str(it.get("title", ""))[:70],
              "idea": f"{it.get('hook', '')} {it.get('script', '')}".strip()[:900]})
    _save("autopilot_queue", q)
    return {"ok": True, "queued": len(q), "note": "Queued. The daily Shorts routine uses it next, in its normal slots and Buffer limit."}


def autopilot_take(known: list[str]) -> dict[str, str] | None:
    import quiet_brain_shorts as qb
    q = _load("autopilot_queue", [])
    while q:
        it = q.pop(0)
        if not qb.is_duplicate(it["title"], known):
            _save("autopilot_queue", q)
            return it
    _save("autopilot_queue", q)
    return None


# ---------------- Ped OS control center ----------------
def osinfo() -> dict[str, Any]:
    out: dict[str, Any] = {"ok": True, "time": time.strftime("%Y-%m-%d %H:%M")}
    def safe(k, f):
        try:
            out[k] = f()
        except Exception as exc:
            out[k] = {"error": str(exc)[:80]}
    import bots
    safe("bots", lambda: [{"id": b["id"], "name": b["name"], "tasks": len(b.get("tasks") or [])} for b in bots.list_bots()])
    safe("shorts", lambda: {k: v for k, v in __import__("quiet_brain_shorts").settings().items() if "token" not in k.lower()})
    safe("checkins", lambda: __import__("checkins").settings())
    safe("studio", lambda: {"calls": len(__import__("studio182").calls()["items"]), "prices": len(__import__("studio182").price_watch()["items"]),
                            "shortcuts": len(__import__("studio182").shortcuts()["items"])})
    safe("offline", lambda: __import__("batch180").offline(None))
    try:
        import shutil
        du = shutil.disk_usage(str(Path.home()))
        out["disk"] = {"free_gb": round(du.free / 1e9, 1), "total_gb": round(du.total / 1e9, 1)}
    except Exception:
        pass
    try:
        import psutil
        out["cpu"] = psutil.cpu_percent(interval=0.3); out["ram"] = psutil.virtual_memory().percent
        b = psutil.sensors_battery(); out["battery"] = round(b.percent) if b else None
    except Exception:
        pass
    return out


# ---------------- voice clone with consent ----------------
CONSENT = "I am Pedro, and I agree that Ped Bot may use recordings of my own voice to speak for me on my own devices."


def voice_clone(action: str = "status", audio_b64: str = "", kind: str = "sample") -> dict[str, Any]:
    d = _store() / "voice"; d.mkdir(exist_ok=True)
    meta = _load("voice_meta", {"consent": False, "samples": 0, "match": ""})
    if action == "record":
        try:
            raw = base64.b64decode(audio_b64 or "")
        except Exception:
            raw = b""
        if len(raw) < 4000:
            return {"ok": False, "error": "Recording too short."}
        if kind == "consent":
            (d / "consent.webm").write_bytes(raw); meta["consent"] = True; meta["consent_at"] = time.time()
        else:
            if not meta.get("consent"):
                return {"ok": False, "error": "Record the consent sentence first."}
            meta["samples"] = int(meta.get("samples") or 0) + 1
            (d / f"sample{meta['samples']}.webm").write_bytes(raw)
        _save("voice_meta", meta)
    elif action == "match":
        if not meta.get("samples"):
            return {"ok": False, "error": "Record a sample first."}
        key = os.environ.get("GEMINI_API_KEY", "").strip()
        if not key:
            return {"ok": False, "error": "Needs your free Gemini key."}
        sample = sorted(d.glob("sample*.webm"))[-1].read_bytes()
        import urllib.request
        body = {"contents": [{"parts": [{"text": "Describe this speaker's voice (pitch, warmth, pace, accent) in one line, then pick the closest of "
                                                 "these voices: Puck, Charon, Fenrir, Orus, Iapetus, Algenib, Achird, Zubenelgenubi, Umbriel, Enceladus. "
                                                 'Reply JSON {"describe":"...","voice":"Name"}'},
                                        {"inline_data": {"mime_type": "audio/webm", "data": base64.b64encode(sample).decode()}}]}]}
        try:
            import brain
            req = urllib.request.Request(f"https://generativelanguage.googleapis.com/v1beta/models/{brain.MAIN}:generateContent",
                                         data=json.dumps(body).encode(), headers={"Content-Type": "application/json", "x-goog-api-key": key})
            with urllib.request.urlopen(req, timeout=120) as r:
                txt = "".join(p.get("text", "") for p in json.loads(r.read())["candidates"][0]["content"]["parts"])
            import llm
            m = llm.json_from(txt)
            meta["match"], meta["describe"] = str(m.get("voice") or ""), str(m.get("describe") or "")
            _save("voice_meta", meta)
        except Exception as exc:
            return {"ok": False, "error": "Could not analyse the sample.", "detail": str(exc)[:120]}
    elif action == "delete":
        for f in d.glob("*"):
            f.unlink()
        meta = {"consent": False, "samples": 0, "match": ""}; _save("voice_meta", meta)
    return {"ok": True, **meta, "consent_text": CONSENT, "folder": str(d),
            "note": "Kept only on this PC. Ped Bot speaks with the closest free Gemini voice; a true clone needs a free local engine (for example XTTS or F5-TTS) that you install yourself."}


def _load(name: str, default: Any) -> Any:
    try:
        return json.loads((_store() / f"{name}.json").read_text(encoding="utf-8"))
    except Exception:
        return default


def _save(name: str, data: Any) -> None:
    (_store() / f"{name}.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


# ---------------- call avatar twin ----------------
def twin(text: str, history: list[dict[str, str]] | None = None, gender: str = "male") -> dict[str, Any]:
    """One turn of a face-to-face call with the 3D avatar: short spoken reply + matching body language."""
    t = " ".join(str(text or "").split())[:800]
    if not t:
        return {"ok": False, "error": "Say something."}
    hist = "\n".join(f"{h.get('who','')}: {str(h.get('text',''))[:200]}" for h in (history or [])[-8:])
    import batch180
    try:
        out = _aj("You are Ped, Pedro's AI twin, on a live video call as a 3D avatar. Talk like a close friend: short, warm, "
                  "funny when it fits, 1-3 spoken sentences, no markdown, no emoji. Pick body language too.\n"
                  f"Actions: {', '.join(batch180.CLIPS)}. Expressions: {', '.join(batch180.EXPRESSIONS)}.\n"
                  f"Call so far:\n{hist or '(just started)'}\nPedro: {t}\n"
                  'Reply JSON: {"say":"...","action":"Idle","expression":"happy"}')
    except Exception as exc:
        return _nokey(exc)
    if not isinstance(out, dict):
        out = {"say": str(out)}
    act = batch180.closest_clip(str(out.get("action") or "Idle"))
    expr = str(out.get("expression") or "neutral")
    return {"ok": True, "say": str(out.get("say") or "")[:600], "action": act,
            "expression": expr if expr in batch180.EXPRESSIONS else "neutral"}
