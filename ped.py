"""ped - talk to Ped Bot and its bots from your own terminal.

  ped "tidy my Downloads"            ask Ped Bot (chat "terminal")
  ped -b "Night Shift" "do X"        give a task to a bot (its own chat)
  ped -s my-chat "..."               use another chat
  ped --bots                         list bots
  ped                                interactive: type messages, Ctrl+C to quit

The Ped Bot app must be running (it keeps running in the tray). When a step needs a yes
(e.g. a terminal command), ped shows it and asks you here; answering y/n replies in that chat.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

PORT = int(os.environ.get("PEDBOT_PORT", "8765"))
BASE = f"http://127.0.0.1:{PORT}"
HEAD = {"Content-Type": "application/json", "Origin": BASE}


def _get(path: str) -> dict:
    with urllib.request.urlopen(urllib.request.Request(BASE + path, headers={"Origin": BASE}), timeout=15) as r:
        return json.loads(r.read().decode("utf-8") or "{}")


def bots() -> list[dict]:
    return _get("/api/bots").get("bots") or []


def find_bot(name: str) -> dict | None:
    low = name.casefold().strip()
    items = bots()
    for b in items:
        if b.get("id", "").casefold() == low or b.get("name", "").casefold() == low:
            return b
    for b in items:
        if low in b.get("name", "").casefold():
            return b
    return None


def say(session: str, text: str, out=sys.stdout) -> tuple[str, bool]:
    """Send one message and stream the answer. Returns (reply, waiting_for_yes)."""
    body = json.dumps({"text": text, "session": session, "client": "ped-cli"}).encode()
    req = urllib.request.Request(BASE + "/api/chat", data=body, method="POST", headers=HEAD)
    reply, waiting, wrote = "", False, False
    with urllib.request.urlopen(req, timeout=3600) as r:
        for raw in r:
            raw = raw.strip()
            if not raw.startswith(b"data: "):
                continue
            ev = json.loads(raw[6:])
            k = ev.get("event")
            if k == "update" and ev.get("kind") != "final":
                print(f"  · {ev.get('text')}", file=out, flush=True)
            elif k == "terminal":
                if ev.get("kind") == "start":
                    print(f"  $ {ev.get('command')}", file=out, flush=True)
                elif ev.get("kind") == "line":
                    print(f"  | {ev.get('line')}", file=out, flush=True)
                elif ev.get("kind") == "end":
                    print(f"  (exit {ev.get('code')}, {ev.get('seconds')} s)", file=out, flush=True)
            elif k == "tool_end":
                if "waiting for a yes" in str(ev.get("detail") or "").casefold():
                    waiting = True
                    print(f"  ? {ev.get('detail')}", file=out, flush=True)
            elif k == "token":
                reply += (" " if reply else "") + ev.get("text", "")
            elif k == "done":
                reply = ev.get("text") or reply
            elif k == "error":
                print(f"  ! {ev.get('text')}", file=out, flush=True)
    if reply:
        print(reply, file=out, flush=True)
        wrote = True
    if not wrote and not waiting:
        print("(no reply)", file=out)
    if "waiting for a yes" in reply.casefold() or "approve" in reply.casefold() and "?" in reply:
        waiting = True
    return reply, waiting


def turn(session: str, text: str, ask=input) -> None:
    _, waiting = say(session, text)
    while waiting:
        try:
            yes = ask("Approve? [y/N] ").strip().casefold() in {"y", "yes"}
        except EOFError:
            yes = False
        _, waiting = say(session, "yes" if yes else "no")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="ped", description="Talk to Ped Bot from your terminal.")
    ap.add_argument("-b", "--bot", help="bot name or id to give the task to")
    ap.add_argument("-s", "--session", help="chat id (default: terminal)")
    ap.add_argument("--bots", action="store_true", help="list bots")
    ap.add_argument("text", nargs="*")
    a = ap.parse_args(argv)
    try:
        if a.bots:
            for b in bots():
                print(f"{b.get('name')}  (id: {b.get('id')})")
            return 0
        session = a.session or "terminal"
        if a.bot:
            b = find_bot(a.bot)
            if not b:
                print(f"No bot called {a.bot!r}. Try: ped --bots", file=sys.stderr)
                return 2
            session = "bot-" + b["id"]
        if a.text:
            turn(session, " ".join(a.text))
            return 0
        print(f"Ped Bot ({session}). Type a message; Ctrl+C to quit.")
        while True:
            try:
                line = input("you> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return 0
            if line:
                turn(session, line)
    except urllib.error.URLError:
        print("Ped Bot is not running. Start it from the Start menu (it then stays in the tray).", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
