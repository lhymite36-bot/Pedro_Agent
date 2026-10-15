"""1.4.10: place orders on shopping / food sites in Pedro's own signed-in Edge.

Flow: start_order -> (agent searches, compares with read_page_text, adds to cart, goes to checkout)
-> order_summary (STOP: screenshot + summary card, Approve/Deny on PC and phone)
-> place_order runs ONLY after Approve (a one-time grant from the Approve tap / "yes").

Never typed by the agent: passwords, card numbers, CVV, UPI PIN, OTP. If the site asks for any of
those, the order is handed over to Pedro. Saved payment methods are used only as the site shows them.
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
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus, urlparse

ROOT = Path(__file__).resolve().parent / "workspace"
_lock = threading.Lock()
open_override: Any = None      # tests: callable(url)
page_override: Any = None      # tests: callable() -> page text
click_override: Any = None     # tests: callable(pattern) -> clicked button name or ""
focus_override: Any = None     # tests: callable() -> (name, is_password)
proof_override: Any = None     # tests: callable(order) -> screenshot path

SITES = {
    "amazon": ("https://www.amazon.in", "https://www.amazon.in/s?k={q}"),
    "flipkart": ("https://www.flipkart.com", "https://www.flipkart.com/search?q={q}"),
    "swiggy": ("https://www.swiggy.com", "https://www.swiggy.com/search?query={q}"),
    "instamart": ("https://www.swiggy.com/instamart", "https://www.swiggy.com/instamart/search?custom_back=true&query={q}"),
    "zomato": ("https://www.zomato.com", ""),
    "blinkit": ("https://blinkit.com", "https://blinkit.com/s/?q={q}"),
    "zepto": ("https://www.zeptonow.com", "https://www.zeptonow.com/search?query={q}"),
    "bigbasket": ("https://www.bigbasket.com", "https://www.bigbasket.com/ps/?q={q}"),
    "myntra": ("https://www.myntra.com", "https://www.myntra.com/{q}"),
    "meesho": ("https://www.meesho.com", "https://www.meesho.com/search?q={q}"),
    "nykaa": ("https://www.nykaa.com", "https://www.nykaa.com/search/result/?q={q}"),
    "ajio": ("https://www.ajio.com", "https://www.ajio.com/search/?text={q}"),
    "jiomart": ("https://www.jiomart.com", "https://www.jiomart.com/search/{q}"),
    "croma": ("https://www.croma.com", "https://www.croma.com/searchB?q={q}"),
}
ALIASES = {"amazon.in": "amazon", "amazon india": "amazon", "swiggy instamart": "instamart",
           "big basket": "bigbasket", "zepto now": "zepto", "jio mart": "jiomart"}

# Words on a page that mean "a secret is being asked for now" -> hand over to Pedro.
SECRET_ASK = re.compile(r"\b(enter|type|provide)\b[^.\n]{0,40}\b(otp|one[- ]time password|cvv|cvc|upi pin|mpin|password|card number)\b"
                        r"|\b(otp|cvv|upi pin|mpin)\b[^.\n]{0,20}\b(sent|required|enter)\b|\bverify with otp\b", re.I)
SECRET_FIELD = re.compile(r"password|passcode|\botp\b|one[- ]time|\bcvv\b|\bcvc\b|security code|upi pin|\bm?pin\b|card ?number|expiry", re.I)
PLACE_BUTTON = re.compile(r"^\s*(place (your )?order( and pay)?|place order|pay( now| securely)?|proceed to pay|pay ₹[\d,.]+|pay rs\.? ?[\d,.]+|confirm (order|and pay)|buy now and pay|complete (order|purchase)|checkout and pay)\b", re.I)
DONE_WORDS = re.compile(r"order (has been )?(placed|confirmed|successful)|thank you,? your order|order id|order #|placed successfully", re.I)


def _p(name: str) -> Path:
    ROOT.mkdir(parents=True, exist_ok=True)
    return ROOT / name


def _orders() -> list[dict[str, Any]]:
    try:
        return json.loads(_p("orders.json").read_text(encoding="utf-8"))
    except Exception:
        return []


def _save(orders: list[dict[str, Any]]) -> None:
    _p("orders.json").write_text(json.dumps(orders[-300:], indent=1, ensure_ascii=False), encoding="utf-8")


def _update(oid: str, **fields: Any) -> dict[str, Any] | None:
    with _lock:
        orders = _orders()
        for o in orders:
            if o["id"] == oid:
                o.update(fields)
                o.setdefault("log", []).append({"t": time.strftime("%Y-%m-%d %H:%M:%S"), "status": o.get("status")})
                _save(orders)
                return dict(o)
    return None


def get_order(oid: str) -> dict[str, Any] | None:
    return next((dict(o) for o in _orders() if o["id"] == oid), None)


def active_order() -> dict[str, Any] | None:
    live = [o for o in _orders() if o.get("status") in {"shopping", "awaiting_approval", "placing"}]
    return dict(live[-1]) if live else None


def resolve_site(platform: str) -> tuple[str, str, str]:
    """(key, home, search template). Any other site: its own address, no search template."""
    raw = " ".join((platform or "").lower().split())
    key = ALIASES.get(raw, raw.replace("www.", "").split(".")[0].replace(" ", ""))
    if key in SITES:
        return key, *SITES[key]
    url = raw if raw.startswith("http") else "https://" + raw
    host = urlparse(url).hostname or ""
    if "." not in host:
        raise ValueError(f"I don't know the site '{platform}'. Give its web address, e.g. tatacliq.com.")
    return host, f"https://{host}", ""


def _open_edge(url: str) -> None:
    if open_override is not None:
        open_override(url)
        return
    exe = shutil.which("msedge") or next((p for p in (
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe") if os.path.isfile(p)), None)
    if exe:
        subprocess.Popen([exe, url])          # Pedro's own Edge profile (already signed in)
    else:
        import webbrowser
        webbrowser.open(url)


def start_order(platform: str, item: str, quantity: int = 1, notes: str = "") -> dict[str, Any]:
    try:
        key, home, search = resolve_site(platform)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    item = " ".join((item or "").split())
    if not item:
        return {"ok": False, "error": "Say what to order."}
    url = search.format(q=quote_plus(item)) if search else home
    oid = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4]
    rec = {"id": oid, "platform": key, "item": item, "quantity": max(1, int(quantity or 1)), "notes": notes,
           "status": "shopping", "started": time.strftime("%Y-%m-%d %H:%M"), "url": url,
           "log": [{"t": time.strftime("%Y-%m-%d %H:%M:%S"), "status": "shopping"}]}
    with _lock:
        orders = _orders(); orders.append(rec); _save(orders)
    _open_edge(url)
    return {"ok": True, "order_id": oid, "url": url, "message": (
        f"Order {oid}: opened {key} in Edge for '{item}'. Next: wait for the page, read_page_text, compare 2-3 matching "
        "items (name, seller/restaurant, price, delivery fee, rating, delivery time), pick the best match for what Pedro "
        "said, add to cart with the right quantity, open the cart and go to checkout. Do NOT type passwords, card numbers, "
        "CVV, UPI PIN or OTPs. At the final review page call order_summary and STOP.")}


def _page_text() -> str:
    if page_override is not None:
        return page_override()
    try:
        import page_text
        r = page_text.read_page_text("", 20000)
        return str(r.get("text") or r.get("message") or "")
    except Exception:
        return ""


def _money(s: str) -> float | None:
    m = re.search(r"(\d[\d,]*(?:\.\d+)?)", str(s or "").replace(" ", ""))
    return float(m.group(1).replace(",", "")) if m else None


def secret_asked(text: str) -> bool:
    return bool(SECRET_ASK.search(text or ""))


def order_summary(order_id: str, item: str, price_total: str, seller: str = "", quantity: int = 1,
                  item_price: str = "", delivery_and_fees: str = "", address: str = "",
                  payment_method: str = "", window: str = "") -> dict[str, Any]:
    """Checkout reached: save proof, check the total really is on the page, ask Pedro (Approve/Deny)."""
    order = get_order(order_id) or active_order()
    if not order:
        return {"ok": False, "error": "No order in progress. Call start_order first."}
    page = _page_text()
    if secret_asked(page):
        _update(order["id"], status="handed_over", reason="site asks for a password/OTP/CVV/UPI PIN")
        return {"ok": False, "handed_over": True, "error": "The site is asking for a password, OTP, CVV or UPI PIN. "
                "I stopped and won't type it. Pedro: please finish this step yourself on the PC."}
    total = _money(price_total)
    seen = [_money(x) for x in re.findall(r"(?:₹|rs\.?|inr)\s?\d[\d,]*(?:\.\d+)?", page, re.I)]
    on_page = total is not None and any(v is not None and abs(v - total) < 0.51 for v in seen)
    shot = ""
    try:
        if proof_override is not None:
            shot = proof_override(order)
        else:
            import extras148
            r = extras148.record_step_proof(f"order {order['id']}", "checkout summary",
                                            f"total {price_total} {'seen' if on_page else 'NOT seen'} on page", window=window or order["platform"])
            shot = r.get("screenshot") or ""
    except Exception:
        shot = ""
    summary = {"item": item, "seller": seller, "quantity": max(1, int(quantity or 1)), "item_price": item_price,
               "delivery_and_fees": delivery_and_fees, "total": price_total, "address": address,
               "payment_method": payment_method or "as shown on the site", "screenshot": shot,
               "total_on_page": on_page}
    _update(order["id"], status="awaiting_approval", summary=summary)
    label = (f"Place order on {order['platform']}: {summary['quantity']} x {item}"
             + (f" from {seller}" if seller else "") + f", total {price_total}"
             + (f", pay by {payment_method}" if payment_method else ""))
    import confirm_action
    confirm_action.remember("place_order", {"order_id": order["id"]}, label)
    warn = "" if on_page else " WARNING: I could not find this total on the page; check the screenshot."
    return {"ok": True, "needs_confirmation": True, "order_id": order["id"], "summary": summary,
            "message": "STOP. Order summary is waiting for Pedro's Approve or Deny (PC and phone)." + warn +
                       " Do not click Place Order/Pay. Show Pedro this summary and end your turn."}


def _find_and_click(pattern: re.Pattern) -> str:
    if click_override is not None:
        return click_override(pattern)
    from pywinauto import Desktop  # type: ignore
    for w in Desktop(backend="uia").windows():
        title = (w.window_text() or "").replace("\u200b", "")
        if "edge" not in title.lower():
            continue
        try:
            controls = w.descendants(control_type="Button") + w.descendants(control_type="Hyperlink")
        except Exception:
            continue
        for c in controls:
            name = " ".join((c.window_text() or "").split())
            if name and len(name) < 60 and pattern.search(name) and c.is_visible() and c.is_enabled():
                w.set_focus(); time.sleep(0.3)
                try:
                    c.invoke()
                except Exception:
                    c.click_input()
                return name
    return ""


def place_order(order_id: str) -> dict[str, Any]:
    """Click the final Place Order / Pay button. Runs only right after Pedro approved this order."""
    import confirm_action
    order = get_order(order_id)
    if not order:
        return {"ok": False, "error": f"No order {order_id}."}
    if order.get("status") != "awaiting_approval" or not confirm_action.consume_grant("place_order", {"order_id": order_id}):
        if order.get("status") == "awaiting_approval":
            s = order.get("summary") or {}
            confirm_action.remember("place_order", {"order_id": order_id},
                                    f"Place order on {order['platform']}: {s.get('item', order['item'])}, total {s.get('total', '?')}")
        return {"ok": False, "needs_confirmation": True,
                "error": "Not approved. Only Pedro's Approve (or 'yes') places an order. Show the summary and stop."}
    page = _page_text()
    if secret_asked(page):
        _update(order_id, status="handed_over", reason="secret asked before placing")
        return {"ok": False, "handed_over": True, "error": "The site now asks for an OTP/password/CVV/UPI PIN. Pedro, please finish on the PC."}
    total = (order.get("summary") or {}).get("total")
    want = _money(total)
    if want is not None and page:
        seen = [_money(x) for x in re.findall(r"(?:₹|rs\.?|inr)\s?\d[\d,]*(?:\.\d+)?", page, re.I)]
        if seen and not any(v is not None and abs(v - want) < 0.51 for v in seen):
            _update(order_id, status="stopped", reason="total changed on the page")
            return {"ok": False, "error": f"The total on the page no longer shows {total}. I did not place the order; please look."}
    _update(order_id, status="placing")
    clicked = _find_and_click(PLACE_BUTTON)
    if not clicked:
        _update(order_id, status="stopped", reason="no Place Order/Pay button found")
        return {"ok": False, "error": "I couldn't find the Place Order / Pay button. Nothing was clicked; please finish on the PC."}
    time.sleep(0 if page_override is not None else 6)
    after = _page_text()
    if secret_asked(after):
        _update(order_id, status="handed_over", clicked=clicked, reason="payment step needs OTP/PIN")
        return {"ok": True, "handed_over": True, "message": f"Clicked '{clicked}'. The payment page now needs your OTP / UPI PIN / CVV. "
                "I won't type it: please finish it yourself on the PC."}
    placed = bool(DONE_WORDS.search(after or ""))
    _update(order_id, status="placed" if placed else "clicked_unconfirmed", clicked=clicked)
    try:
        import extras148
        extras148.record_step_proof(f"order {order_id}", "after place order", f"clicked '{clicked}'", window=order["platform"])
    except Exception:
        pass
    return {"ok": True, "message": (f"Clicked '{clicked}'. " + ("The site shows the order as placed." if placed else
            "I could not see a confirmation yet; check the page or your orders list."))}


def deny_order(order_id: str = "") -> dict[str, Any]:
    order = get_order(order_id) if order_id else active_order()
    if not order:
        return {"ok": False, "error": "No order in progress."}
    _update(order["id"], status="denied")
    return {"ok": True, "message": f"Order {order['id']} cancelled. Nothing was placed; the cart is left as it is."}


def list_orders(limit: int = 10) -> dict[str, Any]:
    rows = _orders()[-max(1, int(limit)):]
    lines = [f"{o['started']} {o['platform']}: {o['item']} - {o['status']}" +
             (f" (total {o['summary']['total']})" if o.get("summary") else "") for o in rows]
    return {"ok": True, "message": "\n".join(lines) or "No orders yet.", "orders": rows}


def pending_card() -> dict[str, Any] | None:
    """For the Approve/Deny card: the order waiting for Pedro, with its summary."""
    o = next((o for o in reversed(_orders()) if o.get("status") == "awaiting_approval"), None)
    if not o:
        return None
    s = dict(o.get("summary") or {})
    shot = s.pop("screenshot", "")
    return {"order_id": o["id"], "platform": o["platform"], **s,
            "screenshot_url": ("/api/image?path=" + quote_plus(shot)) if shot else ""}


# ---- never type secrets ----
def _luhn(digits: str) -> bool:
    total, alt = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if alt:
            d *= 2
            if d > 9:
                d -= 9
        total += d; alt = not alt
    return total % 10 == 0


def _focused() -> tuple[str, bool]:
    if focus_override is not None:
        return focus_override()
    try:
        import uiautomation as auto  # type: ignore
        c = auto.GetFocusedControl()
        name = " ".join(str(getattr(c, "Name", "") or "").split())
        aid = str(getattr(c, "AutomationId", "") or "")
        is_pw = bool(c.GetPropertyValue(30019)) if hasattr(c, "GetPropertyValue") else False   # UIA_IsPasswordPropertyId
        return f"{name} {aid}".strip(), is_pw
    except Exception:
        return "", False


def blocked_typing(text: str) -> str:
    """Reason to refuse typing this, or ''. Card numbers are never typed; during an order nothing is
    typed into password/OTP/CVV/PIN fields and short codes are refused."""
    digits = re.sub(r"[\s-]", "", text or "")
    if digits.isdigit() and 13 <= len(digits) <= 19 and _luhn(digits):
        return "Refusing to type a card number. Pedro must enter payment details himself."
    name, is_pw = _focused()
    if is_pw or SECRET_FIELD.search(name or ""):
        return f"Refusing to type into '{name or 'a password field'}': passwords, OTPs, CVV and PINs are for Pedro only."
    if active_order() and digits.isdigit() and 3 <= len(digits) <= 8 and len(digits) == len((text or "").strip()):
        return "Refusing to type a short code during an order (could be an OTP/CVV/PIN). Hand over to Pedro."
    return ""


DECLARATIONS = [
    {"name": "start_order",
     "description": "Start an order on a shopping/food site Pedro names (Amazon, Flipkart, Swiggy, Zomato, Blinkit, Zepto, BigBasket, Myntra, any site). Opens his signed-in Edge on the search. Then compare items with read_page_text, add to cart, go to checkout, and call order_summary.",
     "parameters": {"type": "object", "properties": {
         "platform": {"type": "string"}, "item": {"type": "string", "description": "What to order, as Pedro said it."},
         "quantity": {"type": "integer"}, "notes": {"type": "string", "description": "Size, brand, budget, restaurant, etc."}},
         "required": ["platform", "item"]}},
    {"name": "order_summary",
     "description": "At the final checkout/review page (before Place Order/Pay): give what the page shows. Saves a screenshot and asks Pedro Approve/Deny. After this, STOP and end your turn.",
     "parameters": {"type": "object", "properties": {
         "order_id": {"type": "string"}, "item": {"type": "string"}, "seller": {"type": "string", "description": "Seller or restaurant."},
         "quantity": {"type": "integer"}, "item_price": {"type": "string"},
         "delivery_and_fees": {"type": "string", "description": "Delivery, platform, packing fees, taxes as shown."},
         "price_total": {"type": "string", "description": "Exact total to pay as shown, e.g. ₹1,249."},
         "address": {"type": "string"}, "payment_method": {"type": "string", "description": "As shown on the page (saved method)."},
         "window": {"type": "string", "description": "Part of the Edge tab title."}},
         "required": ["order_id", "item", "price_total"]}},
    {"name": "place_order",
     "description": "Click the final Place Order / Pay button. Works ONLY after Pedro tapped Approve (or said yes) for this order; otherwise it refuses.",
     "parameters": {"type": "object", "properties": {"order_id": {"type": "string"}}, "required": ["order_id"]}},
    {"name": "deny_order", "description": "Cancel the order in progress (nothing is placed).",
     "parameters": {"type": "object", "properties": {"order_id": {"type": "string"}}}},
    {"name": "list_orders", "description": "Show recent orders and their status.",
     "parameters": {"type": "object", "properties": {"limit": {"type": "integer"}}}},
]
TOOLS = {"start_order": start_order, "order_summary": order_summary, "place_order": place_order,
         "deny_order": deny_order, "list_orders": list_orders}
