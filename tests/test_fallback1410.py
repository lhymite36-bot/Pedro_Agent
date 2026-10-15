import unittest

import cloud_fallback


class FallbackSizeTests(unittest.TestCase):
    def tearDown(self):
        cloud_fallback.transport_override = None

    def test_default_model_and_user_agent(self):
        self.assertNotEqual(cloud_fallback.DEFAULT_MODEL, "llama-3.3-70b-versatile")
        src = open(cloud_fallback.__file__, encoding="utf-8").read()
        self.assertIn('"User-Agent"', src)

    def test_shrinks_request_when_too_large(self):
        seen = []

        def fake(body):
            seen.append(len(body["tools"]))
            if len(seen) == 1:
                raise cloud_fallback._TooLarge("413")
            return {"choices": [{"message": {"content": "ok from backup"}}]}

        cloud_fallback.transport_override = fake
        self.assertEqual(cloud_fallback.run("hello"), "ok from backup")
        self.assertEqual(len(seen), 2)
        self.assertLess(seen[1], seen[0])
        self.assertLessEqual(seen[0], 24)


if __name__ == "__main__":
    unittest.main()
