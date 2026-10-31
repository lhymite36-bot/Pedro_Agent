"""Phone control planner (Batch 2).

The Android AccessibilityService does the taps. This module only turns a
plain-English command into a preview of steps. Banking / password / payment
screens are refused both here (by package/text) and again on the phone.
"""

from __future__ import annotations

import json
import re
from typing import Any

SENSITIVE_PACKAGES = (
    "com.google.android.apps.nbu.paisa.user",  # GPay
    "com.google.android.apps.walletnfcrel",
    "com.phonepe.app",
    "net.one97.paytm",
    "com.csam.icici.bank.imobile",
    "com.sbi.lotusintouch",
    "com.axis.mobile",
    "com.snapwork.hdfc",
    "com.msf.kbank.mobile",
    "com.bankofbaroda.mconnect",
    "org.thoughtcrime.securesms",
)
SENSITIVE_WORDS = (
    "password", "passcode", "pin", "upi pin", "cvv", "cvc", "otp",
    "one-time", "one time password", "card number", "expiry", "net banking",
    "confirm payment", "enter your pin", "bank account", "cvv2", "3-d secure",
    "3d secure", "authorize payment", "pay now",
)

plan_override = None  # tests: fn(command) -> list[dict]


def is_sensitive(tree: Any) -> dict[str, Any]:
    """Refuse banking, password and payment screens from a dumped tree."""
    blob = json.dumps(tree) if not isinstance(tree, str) else tree
    low = blob.casefold()
    pkg = ""
    if isinstance(tree, dict):
        pkg = str(tree.get("package") or tree.get("pkg") or "").casefold()
    for name in SENSITIVE_PACKAGES:
        if name and name.casefold() in low:
            return {"ok": False, "sensitive": True, "reason": "This looks like a banking or payment app, so Ped Bot will not tap it."}
    if pkg.endswith(".bank") or ".banking" in pkg or pkg.endswith(".upi"):
        return {"ok": False, "sensitive": True, "reason": "Banking screens are blocked."}
    for word in SENSITIVE_WORDS:
        if word in low:
            return {"ok": False, "sensitive": True, "reason": "This screen asks for a password, PIN or payment detail. Ped Bot will not type here."}
    if isinstance(tree, dict) and tree.get("password"):
        return {"ok": False, "sensitive": True, "reason": "A password field is focused. Ped Bot will not type here."}
    return {"ok": True, "sensitive": False}


def _local_plan(command: str) -> list[dict[str, Any]]:
    text = " ".join((command or "").split())
    low = text.casefold()
    steps: list[dict[str, Any]] = []
    app = ""
    for name in ("youtube", "chrome", "gmail", "whatsapp", "instagram", "maps", "spotify", "settings", "camera", "photos"):
        if re.search(rf"\b{name}\b", low):
            app = name
            steps.append({"action": "open", "app": name, "say": f"Open {name.title()}", "preview": f"I'm about to open {name.title()}."})
            break
    m = re.search(r"(?:search(?:\s+for)?|look up|find|type)\s+(.+)$", text, re.I)
    query = (m.group(1) if m else "").strip(" .\"'")
    if "search" in low or "look up" in low or "find" in low:
        if not app:
            steps.append({"action": "open", "app": "chrome", "say": "Open Chrome", "preview": "I'm about to open Chrome."})
        if query:
            steps.append({"action": "tap", "target": "Search", "say": "Tap Search", "preview": "I'm about to tap Search."})
            steps.append({"action": "type", "text": query, "say": f"Type {query}", "preview": f"I'm about to type “{query}”."})
            steps.append({"action": "key", "key": "enter", "say": "Press Enter", "preview": "I'm about to press Enter."})
    if not steps:
        steps.append({"action": "ask", "say": text, "preview": f"I'm about to try: {text}"})
    return steps[:12]


def plan(command: str) -> dict[str, Any]:
    command = " ".join((command or "").split())[:400]
    if not command:
        return {"ok": False, "error": "Tell the phone what to do, e.g. open YouTube and search cooking shorts."}
    if plan_override is not None:
        steps = plan_override(command)
        return {"ok": True, "steps": steps, "source": "test", "note": "Each step waits for Allow on the phone. Red STOP is always on screen."}
    import llm
    prompt = (
        "Turn this Android phone command into short tap/type steps. "
        "Allowed actions: open, tap, type, key, swipe, back, home, wait. "
        "Never include a step that types a password, PIN, OTP, CVV or card number. "
        "Never open a banking or payment app. "
        'Reply JSON only: {"steps":[{"action":"open","app":"youtube","preview":"I\'m about to open YouTube."}]}\n'
        f"Command: {command}"
    )
    try:
        data = llm.json_from(llm.text(prompt))
        raw = data.get("steps") if isinstance(data, dict) else data
        steps = []
        for item in raw if isinstance(raw, list) else []:
            if not isinstance(item, dict):
                continue
            action = str(item.get("action") or "tap").casefold()
            if action not in {"open", "tap", "type", "key", "swipe", "back", "home", "wait"}:
                continue
            preview = str(item.get("preview") or item.get("say") or action)
            step = {"action": action, "preview": preview, "say": str(item.get("say") or preview)}
            for k in ("app", "target", "text", "key", "seconds"):
                if item.get(k) not in (None, ""):
                    step[k] = item[k]
            steps.append(step)
        if not steps:
            raise ValueError("empty")
        source = "gemini"
    except Exception:
        steps = _local_plan(command)
        source = "local"
    return {
        "ok": True,
        "steps": steps[:12],
        "source": source,
        "note": "On the phone, every step shows Allow / Stop. A big red STOP stays on screen. Banking, password and payment screens are blocked.",
        "how": "Turn on Ped Bot control in Android Settings › Accessibility. Ped Bot only taps after you Allow each step.",
    }


def handle(action: str, data: dict[str, Any]) -> dict[str, Any]:
    if action in ("", "plan"):
        return plan(str(data.get("command") or data.get("text") or ""))
    if action == "sensitive":
        return is_sensitive(data.get("tree") or data.get("screen") or {})
    if action == "how":
        return {
            "ok": True,
            "title": "Phone control",
            "why": "Ped Bot can open apps, tap buttons and type on this phone the way you would, so you can say “open YouTube and search X”.",
            "how": [
                "On the phone: Settings › Accessibility › Ped Bot control › turn it on.",
                "Android will warn that a full-control service can see the screen. That is true — only turn it on if you want Ped Bot to tap for you.",
                "Every tap shows a floating Allow / Stop bubble. A big red STOP is always on screen.",
                "Banking, password and payment screens are blocked.",
                "Nothing runs until you tap Allow.",
            ],
        }
    return {"ok": False, "error": "Unknown phone-control action."}
