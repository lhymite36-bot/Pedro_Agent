"""1.4.14: find controls by name, act only on what is seen, verify each click and typed value."""

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["PEDRO_AGENT_NO_FILE_LOG"] = "1"

import ui_controls  # noqa: E402


class Node:
    def __init__(self, name, control_type="Button", children=(), value="", enabled=True, password=False,
                 on_invoke=None, sticky=False):
        self.name, self.control_type, self._children = name, control_type, list(children)
        self._value, self.enabled, self.is_password = value, enabled, password
        self.on_invoke, self.sticky, self.invoked = on_invoke, sticky, 0

    def children(self):
        return list(self._children)

    def value(self):
        return self._value

    def toggle_state(self):
        return None

    def selected(self):
        return None

    def invoke(self):
        self.invoked += 1
        if self.on_invoke:
            self.on_invoke()

    def set_text(self, text):
        if not self.sticky:          # a field that ignores the fast path
            self._value = text

    def type_text(self, text):
        self._value = text


class UiControlsTests(unittest.TestCase):
    def setUp(self):
        self.filter = Node("Search", "Edit")
        self.stubborn = Node("Value", "Edit", sticky=True)
        self.pw = Node("Password", "Edit", password=True)
        self.panel = Node("Visualizations", "Pane")
        self.root = Node("Sales - Power BI Desktop", "Window", [
            Node("Home", "TabItem"), Node("Insert", "TabItem"),
            Node("Refresh", "Button", on_invoke=lambda: self.panel._children.append(Node("Refreshing data", "Text"))),
            Node("Do nothing", "Button"),
            Node("Save", "Button"), Node("Save", "Button"),
            Node("Disabled", "Button", enabled=False),
            self.filter, self.stubborn, self.pw, self.panel])
        ui_controls.tree_override = lambda title: self.root
        ui_controls.sleep = lambda s: None
        ui_controls.clear_cache()

    def tearDown(self):
        ui_controls.tree_override = None
        ui_controls.clear_cache()

    def test_read_lists_named_controls(self):
        out = ui_controls.ui_read("Power BI")
        self.assertTrue(out["ok"], out)
        names = [c["name"] for c in out["controls"]]
        self.assertIn("Refresh", names)
        self.assertIn("Search", names)

    def test_click_reports_what_changed(self):
        out = ui_controls.ui_click("refresh", "Power BI")
        self.assertTrue(out["ok"], out)
        self.assertTrue(out["verified"])
        self.assertIn("Refreshing data", out["message"])

    def test_click_with_no_effect_is_not_done(self):
        out = ui_controls.ui_click("Do nothing", "Power BI", wait_seconds=0.2)
        self.assertFalse(out["ok"])
        self.assertFalse(out["verified"])
        self.assertIn("Not done", out["error"])

    def test_unknown_control_is_not_guessed(self):
        out = ui_controls.ui_click("Publish to web", "Power BI")
        self.assertFalse(out["ok"])
        self.assertIn("Do not click a guess", out["error"])
        self.assertTrue(out["nearby"])

    def test_two_matches_ask_which(self):
        out = ui_controls.ui_click("Save", "Power BI")
        self.assertFalse(out["ok"])
        self.assertTrue(out["needs_choice"])
        self.assertEqual(len(out["matches"]), 2)

    def test_disabled_is_reported(self):
        self.assertIn("greyed out", ui_controls.ui_click("Disabled", "Power BI")["error"])

    def test_set_text_reads_back(self):
        out = ui_controls.ui_set_text("Search", "Region = West", "Power BI")
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["after"], "Region = West")
        self.assertEqual(out["method"], "set_text")

    def test_set_text_retries_another_way(self):
        out = ui_controls.ui_set_text("Value", "42", "Power BI")
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["method"], "type_text")

    def test_never_types_a_password(self):
        out = ui_controls.ui_set_text("Password", "hunter2", "Power BI")
        self.assertFalse(out["ok"])
        self.assertTrue(out["blocked"])
        self.assertEqual(self.pw.value(), "")

    def test_delete_and_pay_buttons_need_a_yes(self):
        import rules

        self.assertEqual(rules.category_for("ui_click", {"name": "Delete page"}), "delete")
        self.assertEqual(rules.category_for("ui_click", {"name": "Place order"}), "payment")
        self.assertEqual(rules.category_for("ui_click", {"name": "Send"}), "send_message")
        self.assertIsNone(rules.category_for("ui_click", {"name": "Refresh"}))

    def test_tools_are_registered_and_prompt_says_look_first(self):
        import agent_core

        for name in ("ui_read", "ui_find", "ui_click", "ui_set_text"):
            self.assertIn(name, agent_core.TOOLS)
        self.assertIn("LOOK first", agent_core.SYSTEM_PROMPT)


if __name__ == "__main__":
    unittest.main()
