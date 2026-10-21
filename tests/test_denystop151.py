import unittest, pathlib
SRC = pathlib.Path(__file__).resolve().parents[1].joinpath("agent_core.py").read_text(encoding="utf-8")
class DenyStops(unittest.TestCase):
    def test_deny_ends_turn(self):
        self.assertIn('if result.get("denied"):', SRC)
        self.assertIn("if stop_reply:", SRC)
        self.assertIn("so I did not do it and I won't retry", SRC)
if __name__ == "__main__": unittest.main()
