import unittest
import win_chrome


class FakeWin:
    x = y = 10; width = 1000; height = 700
    def __init__(self): self.calls = []
    def __getattr__(self, n): return lambda *a: self.calls.append((n,) + a)


class WinChromeTests(unittest.TestCase):
    def test_buttons(self):
        api = win_chrome.WindowApi(); api._window = w = FakeWin()
        api.minimize(); self.assertTrue(api.toggle_maximize()); self.assertFalse(api.toggle_maximize()); api.close()
        self.assertEqual([c[0] for c in w.calls], ["minimize", "maximize", "restore", "destroy"])

    def test_resize_has_minimum(self):
        api = win_chrome.WindowApi(); api._window = w = FakeWin()
        api.set_geometry(5, 6, 100, 100)
        self.assertIn(("resize", 760, 520), w.calls); self.assertIn(("move", 5, 6), w.calls)

    def test_icon_exists(self):
        self.assertIsNotNone(win_chrome.icon_path())
