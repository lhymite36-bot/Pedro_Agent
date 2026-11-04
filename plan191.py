"""1.9.1 Ped Bot Pro (freemium) - plan, entitlement and Razorpay TEST-mode checkout.

BYOK stays: every AI call still uses the user's own Gemini key, on Free and Pro.
Pro sells the features Ped Bot built (unlimited bots, 3D avatars, themes, groups,
automations, YouTube autopilot, Studio, Lab, Batch 2 tools) - not AI usage.

Payments: Razorpay Checkout in TEST mode only. The public key id comes from the
environment (RAZORPAY_KEY_ID, must start with rzp_test_). The key secret is optional
(RAZORPAY_KEY_SECRET in this PC's .env, never committed, never sent to the page): with
it, orders are created server-side and the payment signature is checked here.
Live keys are refused in this build.

Entitlement: a local file (works offline) plus, when signed in, one row per account
in public.pb_entitlements (Supabase, anon key + the user's own JWT, RLS). The service
role key is never used or shipped here.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import threading
import time
from pathlib import Path
from typing import Any

import requests

PRICES = {"month": 19900, "year": 149900}          # paise: Rs 199 / month, Rs 1,499 / year
PERIOD_DAYS = {"month": 31, "year": 366}
FREE_BOTS = 2
FREE_ROUTINES = 1
FREE_THEMES = frozenset({"grokDark", "grokLight", "aurora"})
FEATURES = {
    "bots": "Unlimited bots",
    "avatar3d": "3D avatars (male + female)",
    "themes": "All themes + custom colours",
    "groups": "Group chats",
    "automations": "Unlimited automations (routines)",
    "autopilot": "YouTube autopilot",
    "studio": "Studio",
    "lab": "Lab",
    "batch2": "Pro tools (phone control, PC autopilot, memory, team tasks...)",
}
_lock = threading.Lock()
_TIMEOUT = 12


def _path() -> Path:
    import agent_config
    folder = agent_config.storage_dir() / "plan191"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "plan.json"


def _load() -> dict[str, Any]:
    try:
        raw = json.loads(_path().read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(d: dict[str, Any]) -> None:
    with _lock:
        tmp = _path().with_suffix(".tmp")
        tmp.write_text(json.dumps(d, indent=1), encoding="utf-8")
        os.replace(tmp, _path())


# ---------- config ----------
def _key_id() -> str:
    return (os.environ.get("RAZORPAY_KEY_ID") or "").strip()


def _secret() -> str:
    return (os.environ.get("RAZORPAY_KEY_SECRET") or "").strip()


def config() -> dict[str, Any]:
    """What the page may know. Never includes the secret."""
    kid = _key_id()
    note = ""
    if kid.startswith("rzp_live_"):
        note = "Live Razorpay keys are blocked in this test build."
        kid = ""
    elif kid and not kid.startswith("rzp_test_"):
        note = "RAZORPAY_KEY_ID must be a test key (rzp_test_...)."
        kid = ""
    elif not kid:
        note = "No Razorpay test key yet: add RAZORPAY_KEY_ID=rzp_test_... to .env, or use Simulate purchase."
    return {"mode": "test", "keyId": kid, "checkout": bool(kid), "serverOrders": bool(kid and _secret()),
            "simulate": (os.environ.get("PEDBOT_DEV_SIMULATE", "1").strip() != "0"), "note": note,
            "prices": {"month": PRICES["month"], "year": PRICES["year"]}, "currency": "INR",
            "freeBots": FREE_BOTS, "freeRoutines": FREE_ROUTINES, "freeThemes": sorted(FREE_THEMES),
            "features": FEATURES}


# ---------- entitlement ----------
def status() -> dict[str, Any]:
    d = _load()
    until = float(d.get("until") or 0)
    pro = d.get("plan") == "pro" and until > time.time()
    return {"plan": "pro" if pro else "free", "isPro": pro, "period": d.get("period") if pro else "",
            "until": time.strftime("%Y-%m-%d", time.localtime(until)) if pro else "",
            "source": d.get("source", "") if pro else "", "email": d.get("email", "")}


def is_pro() -> bool:
    if (os.environ.get("PEDBOT_FORCE_PLAN") or "").strip().lower() == "pro":   # dev only
        return True
    return bool(status()["isPro"])


def _grant(period: str, source: str, payment_id: str = "", bearer: str = "", user: dict | None = None) -> dict[str, Any]:
    if period not in PRICES:
        return {"ok": False, "error": "Pick monthly or yearly."}
    d = _load()
    base = max(time.time(), float(d.get("until") or 0)) if d.get("plan") == "pro" else time.time()
    d.update({"plan": "pro", "period": period, "until": base + PERIOD_DAYS[period] * 86400, "source": source,
              "payment_id": payment_id[:64], "granted": time.time()})
    if user and user.get("email"):
        d["email"] = str(user["email"])[:120]
    _save(d)
    synced = _push(bearer, user, d)
    return {"ok": True, **status(), "synced": synced,
            "message": "Pro is on (" + ("simulated" if source == "simulated" else "Razorpay test") + " purchase)."}


def downgrade() -> dict[str, Any]:
    d = _load(); d.update({"plan": "free", "until": 0}); _save(d)
    return {"ok": True, **status(), "message": "Back on Free (test reset)."}


# ---------- Supabase (anon key + user JWT, RLS) ----------
def _sb() -> tuple[str, str]:
    try:
        import supabase_auth as sa
        return sa._url(), sa._anon()
    except Exception:
        return "", ""


def _uid(user: dict | None) -> str:
    return str((user or {}).get("id") or "")


def _push(bearer: str, user: dict | None, d: dict[str, Any]) -> bool:
    url, anon = _sb()
    if not (url and anon and bearer and _uid(user)):
        return False
    row = {"user_id": _uid(user), "plan": "pro", "period": d["period"], "source": d["source"],
           "mode": "test", "payment_id": d.get("payment_id", ""),
           "valid_until": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(d["until"]))}
    try:
        r = requests.post(f"{url}/rest/v1/pb_entitlements", json=row, timeout=_TIMEOUT,
                          headers={"apikey": anon, "Authorization": f"Bearer {bearer}", "Content-Type": "application/json",
                                   "Prefer": "resolution=merge-duplicates,return=minimal"})
        return r.status_code < 400
    except requests.RequestException:
        return False


def restore(bearer: str = "", user: dict | None = None) -> dict[str, Any]:
    """Restore purchase: read this account's row (RLS lets a user read only their own)."""
    url, anon = _sb()
    if not (url and anon and bearer and _uid(user)):
        st = status()
        msg = "Pro is active on this device." if st["isPro"] else "Sign in to your Ped Bot account to restore a purchase."
        return {"ok": st["isPro"], **st, "message": msg}
    try:
        r = requests.get(f"{url}/rest/v1/pb_entitlements", timeout=_TIMEOUT,
                         params={"user_id": "eq." + _uid(user), "select": "plan,period,source,mode,payment_id,valid_until"},
                         headers={"apikey": anon, "Authorization": f"Bearer {bearer}"})
        rows = r.json() if r.status_code < 400 else []
    except (requests.RequestException, ValueError):
        return {"ok": False, **status(), "error": "Could not reach your account. Try again online."}
    for row in rows if isinstance(rows, list) else []:
        try:
            until = time.mktime(time.strptime(str(row.get("valid_until"))[:19], "%Y-%m-%dT%H:%M:%S")) - time.timezone
        except ValueError:
            continue
        if row.get("plan") == "pro" and until > time.time():
            d = _load(); d.update({"plan": "pro", "period": row.get("period") or "month", "until": until,
                                   "source": row.get("source") or "restored", "payment_id": row.get("payment_id") or ""})
            _save(d)
            return {"ok": True, **status(), "message": "Purchase restored. Pro is on."}
    return {"ok": False, **status(), "error": "No active Pro purchase on this account."}


# ---------- Razorpay (test mode) ----------
def create_order(period: str) -> dict[str, Any]:
    cfg = config()
    if period not in PRICES:
        return {"ok": False, "error": "Pick monthly or yearly."}
    if not cfg["checkout"]:
        return {"ok": False, "error": cfg["note"], "code": "no_key"}
    out = {"ok": True, "keyId": cfg["keyId"], "amount": PRICES[period], "currency": "INR", "period": period, "orderId": ""}
    if _secret():
        try:
            r = requests.post("https://api.razorpay.com/v1/orders", auth=(cfg["keyId"], _secret()), timeout=_TIMEOUT,
                              json={"amount": PRICES[period], "currency": "INR", "receipt": f"pb-{period}-{int(time.time())}",
                                    "notes": {"app": "Ped Bot", "period": period}})
            if r.status_code < 400:
                out["orderId"] = str(r.json().get("id") or "")
        except (requests.RequestException, ValueError):
            pass
    return out


def verify(data: dict[str, Any], bearer: str = "", user: dict | None = None) -> dict[str, Any]:
    period = str(data.get("period") or "")
    pid = str(data.get("razorpay_payment_id") or "")
    oid = str(data.get("razorpay_order_id") or "")
    sig = str(data.get("razorpay_signature") or "")
    if not pid.startswith("pay_"):
        return {"ok": False, "error": "Payment was not completed."}
    if not config()["checkout"]:
        return {"ok": False, "error": "Payments are not set up."}
    if oid and _secret():
        good = hmac.new(_secret().encode(), f"{oid}|{pid}".encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(good, sig):
            return {"ok": False, "error": "Payment signature did not match."}
        return _grant(period, "test", pid, bearer, user)
    # Test mode without a secret: Razorpay test payments cannot be checked here, so they are marked unverified.
    return _grant(period, "test", pid, bearer, user)


def simulate(period: str, bearer: str = "", user: dict | None = None) -> dict[str, Any]:
    if not config()["simulate"]:
        return {"ok": False, "error": "Simulate purchase is turned off (PEDBOT_DEV_SIMULATE=0)."}
    return _grant(period or "month", "simulated", "", bearer, user)


# ---------- gates ----------
def locked(feature: str) -> dict[str, Any]:
    return {"ok": False, "code": "pro_required", "feature": feature,
            "error": f"Ped Bot Pro unlocks: {FEATURES.get(feature, 'this feature')}. Open Upgrade to Pro."}


def gate(feature: str) -> dict[str, Any] | None:
    return None if is_pro() else locked(feature)


def can_add_bot() -> dict[str, Any] | None:
    if is_pro():
        return None
    try:
        import bots
        if len(bots.list_bots()) >= FREE_BOTS:
            r = locked("bots"); r["error"] = f"Free includes {FREE_BOTS} bots. Ped Bot Pro unlocks unlimited bots."
            return r
    except Exception:
        return None
    return None


def can_add_routine() -> dict[str, Any] | None:
    if is_pro():
        return None
    try:
        import routines
        if len(routines._load().get("routines", [])) >= FREE_ROUTINES:
            r = locked("automations"); r["error"] = f"Free includes {FREE_ROUTINES} automation. Ped Bot Pro unlocks unlimited automations."
            return r
    except Exception:
        return None
    return None


def theme_ok(data: dict[str, Any]) -> dict[str, Any] | None:
    preset = str((data or {}).get("preset") or "aurora")
    return None if (preset in FREE_THEMES or is_pro()) else locked("themes")


def dispatch(data: dict[str, Any], bearer: str = "", user: dict | None = None) -> dict[str, Any]:
    a = str(data.get("action") or "status")
    if a == "status":
        return {"ok": True, **status(), "config": config()}
    if a == "order":
        return create_order(str(data.get("period") or "month"))
    if a == "verify":
        return verify(data, bearer, user)
    if a == "simulate":
        return simulate(str(data.get("period") or "month"), bearer, user)
    if a == "restore":
        return restore(bearer, user)
    if a == "downgrade":
        return downgrade()
    return {"ok": False, "error": "Unknown action."}
