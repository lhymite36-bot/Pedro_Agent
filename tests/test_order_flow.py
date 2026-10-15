"""1.4.10: order workflow - stops at a summary; only Approve places the order; secrets never typed."""
import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import confirm_action  # noqa: E402
import order_flow  # noqa: E402
import rules  # noqa: E402
try:
    import agent_core as agent  # noqa: E402
except ImportError:
    import agent_core as agent  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CHECKOUT = "Order Summary\nItems: ₹1,199.00\nDelivery: ₹40.00\nOrder Total: ₹1,239.00\nDeliver to Pedro, Mumbai\nPay with UPI (saved)\nPlace your order"


class OrderFlowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.old_root = order_flow.ROOT
        order_flow.ROOT = Path(self.tmp.name)
        self.opened, self.clicks = [], []
        self.page = CHECKOUT
        order_flow.open_override = self.opened.append
        order_flow.page_override = lambda: self.page
        order_flow.proof_override = lambda o: str(Path(self.tmp.name) / "shot.jpg")
        order_flow.focus_override = lambda: ("Search Amazon.in", False)
        def click(pattern):
            self.clicks.append(pattern.pattern); self.page = "Thank you, your order has been placed. Order ID 123"; return "Place your order"
        order_flow.click_override = click
        confirm_action.reset()

    def tearDown(self):
        order_flow.ROOT = self.old_root
        for n in ("open_override", "page_override", "proof_override", "focus_override", "click_override"):
            setattr(order_flow, n, None)
        confirm_action.reset()
        self.tmp.cleanup()

    def _start(self, platform="Amazon", item="usb c cable 1m"):
        r = order_flow.start_order(platform, item, 2)
        self.assertTrue(r["ok"], r)
        return r["order_id"]

    def test_known_and_unknown_sites(self):
        self.assertEqual(order_flow.resolve_site("Flipkart")[0], "flipkart")
        self.assertEqual(order_flow.resolve_site("amazon.in")[0], "amazon")
        self.assertEqual(order_flow.resolve_site("Swiggy Instamart")[0], "instamart")
        self.assertEqual(order_flow.resolve_site("tatacliq.com")[1], "https://tatacliq.com")
        with self.assertRaises(ValueError):
            order_flow.resolve_site("nonsense")
        self._start("Blinkit", "milk 1 litre")
        self.assertEqual(self.opened, ["https://blinkit.com/s/?q=milk+1+litre"])
        self._start("Zomato", "paneer biryani")
        self.assertEqual(self.opened[-1], "https://www.zomato.com")

    def test_summary_stops_and_only_approve_places(self):
        oid = self._start()
        s = order_flow.order_summary(oid, "USB-C cable 1m", "₹1,239.00", seller="Cable Co", quantity=2,
                                     item_price="₹1,199", delivery_and_fees="₹40", address="Pedro, Mumbai", payment_method="UPI (saved)")
        self.assertTrue(s["needs_confirmation"]); self.assertTrue(s["summary"]["total_on_page"])
        self.assertEqual(confirm_action.pending()["name"], "place_order")
        # the model trying to place it by itself is refused, nothing clicked
        r = order_flow.place_order(oid)
        self.assertFalse(r["ok"]); self.assertEqual(self.clicks, [])
        card = order_flow.pending_card()
        self.assertEqual((card["total"], card["seller"], card["quantity"]), ("₹1,239.00", "Cable Co", 2))
        self.assertIn("/api/image?path=", card["screenshot_url"])
        # Pedro taps Approve -> "yes" -> runs once
        reply = confirm_action.answer_pending("yes", lambda n, a: order_flow.TOOLS[n](**a))
        self.assertTrue(reply.startswith("Done"), reply)
        self.assertEqual(len(self.clicks), 1)
        self.assertEqual(order_flow.get_order(oid)["status"], "placed")
        # a second call can't place it again
        self.assertFalse(order_flow.place_order(oid)["ok"]); self.assertEqual(len(self.clicks), 1)

    def test_deny_cancels(self):
        oid = self._start()
        order_flow.order_summary(oid, "cable", "₹1,239.00")
        reply = confirm_action.answer_pending("no", lambda n, a: order_flow.TOOLS[n](**a))
        self.assertTrue(reply.startswith("Cancelled"))
        order_flow.deny_order(oid)
        self.assertEqual(order_flow.get_order(oid)["status"], "denied")
        self.assertEqual(self.clicks, [])
        self.assertIsNone(order_flow.pending_card())

    def test_hand_over_when_site_asks_for_otp(self):
        oid = self._start()
        self.page = "Enter the OTP sent to your phone to continue"
        r = order_flow.order_summary(oid, "cable", "₹1,239.00")
        self.assertTrue(r["handed_over"]); self.assertIsNone(confirm_action.pending())
        self.assertEqual(order_flow.get_order(oid)["status"], "handed_over")

    def test_total_changed_blocks_click(self):
        oid = self._start()
        order_flow.order_summary(oid, "cable", "₹1,239.00")
        self.page = "Order Total: ₹1,499.00\nPlace your order"
        reply = confirm_action.answer_pending("yes", lambda n, a: order_flow.TOOLS[n](**a))
        self.assertTrue(reply.startswith("That failed"), reply)
        self.assertEqual(self.clicks, [])

    def test_payment_otp_after_click_is_handed_over(self):
        oid = self._start()
        order_flow.order_summary(oid, "cable", "₹1,239.00")
        def click(p):
            self.clicks.append(1); self.page = "Please enter your UPI PIN in the app. Enter OTP sent to +91..."; return "Pay ₹1,239"
        order_flow.click_override = click
        r = confirm_action.answer_pending("yes", lambda n, a: order_flow.TOOLS[n](**a))
        self.assertIn("won't type", r)
        self.assertEqual(order_flow.get_order(oid)["status"], "handed_over")

    def test_place_button_pattern(self):
        for ok in ("Place your order", "Place Order", "Pay ₹1,239", "Proceed to Pay", "PLACE ORDER AND PAY", "Pay Now"):
            self.assertTrue(order_flow.PLACE_BUTTON.search(ok), ok)
        for no in ("Add to cart", "Payment options", "Paytm wallet", "Save address"):
            self.assertFalse(order_flow.PLACE_BUTTON.search(no), no)

    def test_never_types_secrets(self):
        self.assertIn("card number", order_flow.blocked_typing("4111 1111 1111 1111"))
        self.assertEqual(order_flow.blocked_typing("usb c cable"), "")
        order_flow.focus_override = lambda: ("Enter OTP", False)
        self.assertTrue(order_flow.blocked_typing("hello"))
        order_flow.focus_override = lambda: ("", True)
        self.assertTrue(order_flow.blocked_typing("hello"))
        order_flow.focus_override = lambda: ("Search", False)
        self._start()
        self.assertTrue(order_flow.blocked_typing("482913"))     # short code during an order
        self.assertEqual(order_flow.blocked_typing("2 kg rice"), "")

    def test_type_text_tool_uses_the_guard(self):
        with mock.patch.object(agent, "_type_into_focused_window") as typed:
            r = agent.type_text("4111111111111111")
        self.assertFalse(r["ok"]); typed.assert_not_called()

    def test_registered_and_prompted(self):
        for n in order_flow.TOOLS:
            self.assertIn(n, agent.TOOLS)
        self.assertIn("order_summary", agent.SYSTEM_INSTRUCTION if hasattr(agent, "SYSTEM_INSTRUCTION") else
                      (ROOT / ("agent_core.py" if (ROOT / "agent_core.py").exists() else "agent_core.py")).read_text(encoding="utf-8"))


class OrderUiTests(unittest.TestCase):
    def test_card_and_deny_hook(self):
        js = (ROOT / "app_static" / "app.js").read_text(encoding="utf-8")
        self.assertIn("Place this order on", js); self.assertIn("screenshot_url", js)
        src = (ROOT / "chat_app.py").read_text(encoding="utf-8")
        self.assertIn("order_flow.pending_card()", src); self.assertIn("order_flow.deny_order", src)


if __name__ == "__main__":
    unittest.main()
