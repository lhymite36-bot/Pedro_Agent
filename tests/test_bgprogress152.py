import unittest
import bg_progress


class Clock:
    t = 0.0
    def __call__(self): return self.t


class ReporterTests(unittest.TestCase):
    def setUp(self):
        self.posts = []
        bg_progress.poster = lambda s, text, kind, img="": self.posts.append((s, kind, text, img))

    def tearDown(self):
        bg_progress.poster = None

    def test_throttle_and_final(self):
        c = Clock()
        r = bg_progress.Reporter("chat1", "App Builder (x)", gap=60, clock=c)
        r.milestone("plan ready")
        c.t = 10; r.milestone("run 1: 2 errors")
        c.t = 20; r.milestone("fix round 1: 0 errors")   # replaces the waiting one
        self.assertEqual(len(self.posts), 1)
        c.t = 70; r._flush()
        self.assertEqual(len(self.posts), 2)
        self.assertIn("fix round 1", self.posts[1][2])
        self.assertTrue(self.posts[1][2].startswith(bg_progress.PROGRESS_MARK))
        r.final("Done", ok=True, image="shot.png")
        self.assertEqual(self.posts[-1][1], "final")
        self.assertEqual(self.posts[-1][3], "shot.png")
        r.milestone("late")                 # nothing after the final
        self.assertEqual(len(self.posts), 3)

    def test_failure_kind(self):
        r = bg_progress.Reporter("chat1", "Job")
        r.final("broke", ok=False)
        self.assertEqual(self.posts[-1][1], "failed")
        self.assertTrue(self.posts[-1][2].startswith(bg_progress.FAIL_MARK))


class BuilderWiring(unittest.TestCase):
    def test_final_message_says_how_to_open(self):
        import app_builder
        msg = app_builder.final_message({"screens": 4, "files": ["a", "b"], "final_errors": [], "scores": [6, 8],
                                         "seconds": 600, "project": "C:/x", "website_zip": "C:/x/dist/x.zip"})
        self.assertIn("index.html", msg); self.assertIn("8/10", msg); self.assertIn("no errors", msg)


if __name__ == "__main__":
    unittest.main()
