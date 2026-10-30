"""1.6.9: Gemini emotional voice - model chain, per-line emotion, quota fallback, per-bot voice."""
import base64, json, os, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gemini_tts as g

PCM = b"\x00\x01" * 2400


class GeminiVoiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        os.environ["STORAGE_DIR"] = self.tmp.name; os.environ["GEMINI_API_KEY"] = "test-key-not-real"
        self.calls = []; g._listed = (0.0, []); g._cool.clear(); g._turn.update(bot=None, user="", tone=None)
        self.addCleanup(setattr, g, "transport_override", None)

    def fake(self, quota_models=(), lines=None):
        def t(path, body):
            self.calls.append((path, body))
            if path.startswith("/models?"):
                return {"models": [{"name": "models/gemini-3.8-flash-tts", "supportedGenerationMethods": ["generateContent"]},
                                   {"name": "models/gemini-3.8-flash-lite-tts", "supportedGenerationMethods": ["generateContent"]},
                                   {"name": "models/gemini-flash-latest", "supportedGenerationMethods": ["generateContent"]}]}
            model = path.split("/")[2].split(":")[0]
            if "tts" not in model:   # the director
                return {"candidates": [{"content": {"parts": [{"text": json.dumps({"tone": "embarrassed", "lines": lines or [
                    {"text": "Okay... I... I accidentally said it.", "emotion": "embarrassed"}, {"text": "To my boss.", "emotion": "deadpan"}]})}]}}]}
            if model in quota_models:
                e = RuntimeError("Gemini voice error 429: quota"); e.status = 429; raise e
            return {"candidates": [{"content": {"parts": [{"inlineData": {"mimeType": "audio/L16;rate=24000", "data": base64.b64encode(PCM).decode()}}]}}]}
        return t

    def test_models_listed_from_key_newest_first(self):
        g.transport_override = self.fake()
        self.assertEqual(g.model_chain()[:2], ["gemini-3.8-flash-tts", "gemini-3.8-flash-lite-tts"])
        self.assertNotIn("gemini-flash-latest", g.model_chain())

    def test_per_line_emotion_and_bot_voice(self):
        g.transport_override = self.fake()
        info = g.speak_to_file("I said I love you to my boss.", Path(self.tmp.name) / "a.mp3", {"voice": {"gender": "male", "name": "Puck"}}, "what happened?")
        self.assertEqual((info["voice"], info["tone"]), ("Puck", "embarrassed"))
        tts = [b for p, b in self.calls if "tts" in p][0]
        self.assertEqual(tts["generationConfig"]["speechConfig"]["voiceConfig"]["prebuiltVoiceConfig"]["voiceName"], "Puck")
        parts = tts["contents"][0]["parts"]
        self.assertEqual(len(parts), 2); self.assertIn("embarrassed", parts[0]["speech_metadata"]["style"])
        self.assertIn("deadpan", parts[1]["speech_metadata"]["style"]); self.assertIn("...", parts[0]["text"])
        self.assertGreater((Path(self.tmp.name) / "a.mp3").stat().st_size, 1000)

    def test_quota_moves_to_next_model_then_raises(self):
        g.transport_override = self.fake(quota_models=("gemini-3.8-flash-tts",))
        info = g.speak_to_file("Hi there.", Path(self.tmp.name) / "b.mp3", {}, "", tone="warm")
        self.assertEqual(info["model"], "gemini-3.8-flash-lite-tts")
        g._cool.clear()
        g.transport_override = self.fake(quota_models=tuple(g.model_chain()))
        with self.assertRaises(g.Quota):
            g.speak_to_file("Hi there.", Path(self.tmp.name) / "c.mp3", {}, "", tone="warm")

    def test_defaults_and_voice_cleaning(self):
        self.assertEqual(g.voice_for(None), {"gender": "female", "name": "Sulafat"})
        self.assertEqual(g.voice_for({"voice": {"gender": "male"}})["name"], "Puck")
        self.assertEqual(g.voice_for({"voice": {"gender": "male", "name": "Sulafat"}})["name"], "Puck")
        self.assertEqual(g.guess_tone("I'm so sorry to hear that"), "sad")
        self.assertEqual(g.guess_tone("We did it!"), "excited")

    def test_old_models_get_spoken_prefix(self):
        g.transport_override = self.fake()
        g._synth_once("gemini-2.5-flash-preview-tts", "Hello", "Kore", "calm")
        part = [b for p, b in self.calls if "tts" in p][0]["contents"][0]["parts"][0]
        self.assertTrue(part["text"].startswith("Say in a calm")); self.assertNotIn("speech_metadata", part)

    def test_bot_saves_voice(self):
        os.environ["BOTS_DIR"] = str(Path(self.tmp.name) / "bots"); self.addCleanup(os.environ.pop, "BOTS_DIR", None)
        import bots
        b = bots.save_bot({"name": "Narrator", "voice": {"gender": "male", "name": "Fenrir"}})
        self.assertEqual(bots.get_bot(b["id"])["voice"], {"gender": "male", "name": "Fenrir"})
        self.assertEqual(bots.save_bot({"name": "Plain"})["voice"]["name"], "Sulafat")


if __name__ == "__main__":
    unittest.main()
