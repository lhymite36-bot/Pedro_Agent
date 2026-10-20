"""1.4.14: Quiet Brain Shorts backup pipeline (no real posting in tests)."""

import datetime as dt
import json
import os
import tempfile
import unittest
from unittest import mock

import quiet_brain_shorts as q


def _post(i, service, due, url=""):
    return {"id": f"{i:024x}", "text": f"post {i}", "dueAt": due, "status": "scheduled", "channelService": service,
            "assets": [{"source": url}] if url else []}


class QuietBrainTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"STORAGE_DIR": self.tmp.name, "QUIET_BRAIN_POSTED_JSON": ""})
        self.env.start()
        self.sched = []
        self.mutations = []

        def transport(p):
            if p["query"].startswith("mutation"):
                self.mutations.append(p["variables"]["input"])
                return {"createPost": {"post": {"id": "%024x" % (100 + len(self.mutations)), "dueAt": ""}}}
            st = p["variables"]["st"]
            return {"posts": {"edges": [{"node": x} for x in self.sched] if "scheduled" in st else [], "pageInfo": {}}}
        q.transport = transport
        q.idea_writer = lambda prompt: "\n".join(
            f"{f}|Why title {i}|{w}"
            for i, (f, w) in enumerate(zip(q.FORMATS, [
                "Standing in the slowest supermarket queue and switching lanes three times (loss aversion; fix: pick one)",
                "Rewriting a two-line email nine times before sending it (perfectionism; fix: send the second draft)",
                "Pressing the lift button again because the first press clearly did not count (illusion of control)",
                "Buying a houseplant to fix your entire life and naming it Kevin (fresh start effect; fix: water it)",
                "Owning forty unread books and buying another one today (tsundoku; fix: read ten pages tonight)",
                "Catching your reflection in a dark window and fixing your hair for nobody (spotlight effect)"])))
        self.now = dt.datetime(2026, 10, 20, 12, 0, tzinfo=q.IST)

    def tearDown(self):
        q.transport = q.idea_writer = None
        self.env.stop()
        self.tmp.cleanup()

    def test_off_by_default(self):
        self.assertFalse(q.settings()["enabled"])
        self.assertIsNone(q.routine_tick(self.now))

    def test_dry_run_never_posts(self):
        r = q.run_day("2026-10-20", dry_run=True)
        self.assertTrue(r["ok"], r)
        self.assertEqual(self.mutations, [])
        self.assertEqual(len(r["plan"]), 6)

    def test_youtube_first_then_tiktok_overflow_at_free_limit(self):
        self.sched = [_post(i, "tiktok", f"2026-10-2{i % 9}T10:00:00.000Z") for i in range(6)]   # 6/10 used -> 4 free
        items = [{"n": i, "format": "pov", "idea": f"idea {i}", "title": f"Why {i}", "video_url": f"https://x/{i}.mp4"}
                 for i in range(1, 7)]
        plan = q.schedule_day("2026-10-20", items, self.sched, dry_run=False, now=self.now)
        yt = [m for m in self.mutations if m["channelId"] == q.YOUTUBE_CHANNEL]
        tt = [m for m in self.mutations if m["channelId"] == q.TIKTOK_CHANNEL]
        self.assertEqual((len(yt), len(tt)), (4, 0))
        for m in yt:
            self.assertTrue(m["metadata"]["youtube"]["title"].endswith("#shorts"))
            self.assertIs(m["metadata"]["youtube"]["isAiGenerated"], False)
            self.assertEqual(m["metadata"]["youtube"]["categoryId"], "27")
            self.assertTrue(m["dueAt"].endswith("+05:30"))
        self.assertTrue(all(p["tiktok_status"] == "pending-overflow" for p in plan))
        self.assertEqual(len(q.load_posted()), 6)

    def test_filler_queues_pending_tiktoks_when_slots_free_and_skips_grok_bot_ones(self):
        for n in (1, 2, 3):
            q.add_posted({"date": "2026-10-20", "n": n, "file": f"qb-short{n}.mp4", "title": f"t{n}",
                          "video_url": f"https://x/{n}.mp4", "tiktok_status": "pending-overflow",
                          "tiktok_caption": f"cap {n} #fyp #quietbrain", "scheduled_time": "2026-10-20T19:00:00+05:30"})
        self.sched = [_post(1, "tiktok", "2026-10-21T10:00:00.000Z", "https://x/2.mp4")]   # Grok Bot already queued #2
        r = q.fill_overflow(now=self.now)
        urls = [m["assets"][0]["video"]["url"] for m in self.mutations]
        self.assertEqual(urls, ["https://x/1.mp4", "https://x/3.mp4"])
        for m in self.mutations:
            self.assertIs(m["metadata"]["tiktok"]["isAiGenerated"], False)
            self.assertIn("#fyp", m["text"]); self.assertIn("#quietbrain", m["text"])
        self.assertEqual(len({m["dueAt"] for m in self.mutations}), 2)        # no double-booked slot
        self.assertEqual({e["tiktok_status"] for e in q.load_posted()}, {"scheduled"})
        self.assertEqual(len(r["queued"]), 2)

    def test_duplicate_ideas_are_dropped(self):
        q.add_posted({"date": "d", "file": "f", "topic": "Standing in the slowest supermarket queue and switching lanes three times (loss aversion; fix: pick one)"})
        ideas = q.write_ideas(5, q.known_ideas([]))
        self.assertNotIn("supermarket queue", " ".join(i["idea"] for i in ideas))
        self.assertEqual(len(ideas), 5)

    def test_token_goes_to_local_env_only(self):
        import agent_config
        with mock.patch.object(agent_config, "APP_DIR", __import__("pathlib").Path(self.tmp.name)):
            q.set_token("abc 123")
            self.assertIn("BUFFER_ACCESS_TOKEN=abc123", (agent_config.APP_DIR / ".env").read_text())
        root = __import__("pathlib").Path(__file__).resolve().parents[1]
        self.assertIn(".env", (root / ".gitignore").read_text())
        self.assertIn("BUFFER_ACCESS_TOKEN=\n", (root / ".env.example").read_text())

    def test_never_schedules_in_the_past(self):
        late = dt.datetime(2026, 10, 20, 21, 55, tzinfo=q.IST)
        times = q.slot_times("2026-10-20", late)
        self.assertTrue(all(dt.datetime.fromisoformat(t) > late for t in times))
        self.assertTrue(times[0].startswith("2026-10-21T14:30"))


if __name__ == "__main__":
    unittest.main()
