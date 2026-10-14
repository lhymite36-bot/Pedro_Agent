"""Spoken replies: voice messages get voice answers (PC speakers or client mp3)."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["PEDRO_AGENT_NO_FILE_LOG"] = "1"

import chat_app  # noqa: E402


class FakePipe:
    def __init__(self, log):
        self.log = log

    def submit(self, text):
        self.log.append(text)

    def finish(self):
        return {"ok": True}

    def abort(self):
        pass


class VoiceReplyTests(unittest.TestCase):
    def setUp(self):
        self.state = chat_app.AppState("m")
        self.state.speak_mode = "voice"
        self.spoken = []
        self.state.pipeline_factory = lambda: FakePipe(self.spoken)
        self.state.history_for = lambda s: []
        agent = chat_app._agent()

        def run_agent(text, history, model, cancel_event=None, on_text=None, on_event=None):
            on_text("Sure thing [chuckles] done.")
            return "Sure thing [chuckles] done."

        self.patches = [
            mock.patch.object(agent, "run_agent", run_agent),
            mock.patch.object(chat_app.chat_store, "add", lambda *a, **k: None),
            mock.patch.object(chat_app.bots, "bot_for_session", lambda s: None),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def turn(self, **kw):
        ev = []
        chat_app.stream_turn(self.state, "s1", "hi", ev.append, **kw)
        return ev

    def test_modes(self):
        self.assertTrue(chat_app.should_speak("voice", True))
        self.assertFalse(chat_app.should_speak("voice", False))
        self.assertTrue(chat_app.should_speak("always", False))
        self.assertFalse(chat_app.should_speak("never", True))
        self.assertEqual(chat_app.AppState("m").speak_mode in chat_app.SPEAK_MODES, True)

    def test_voice_message_speaks_on_pc(self):
        ev = self.turn(from_voice=True)
        self.assertEqual(self.spoken, ["Sure thing [chuckles] done."])  # stage tag kept for TTS
        self.assertEqual(ev[-1], {"event": "speech_end", "status": "ok"})

    def test_typed_message_silent_in_voice_mode(self):
        ev = self.turn()
        self.assertEqual(self.spoken, [])
        self.assertEqual(ev[-1]["status"], "skipped")

    def test_never_and_always(self):
        self.state.speak_mode = "never"
        self.turn(from_voice=True)
        self.assertEqual(self.spoken, [])
        self.state.speak_mode = "always"
        self.turn()
        self.assertEqual(len(self.spoken), 1)

    def test_remote_gets_mp3_clip(self):
        agent = chat_app._agent()

        def synth(text, dest, voice):
            self.assertIn("[chuckles]", text)
            Path(dest).write_bytes(b"ID3fake")
            return voice

        with mock.patch.object(agent, "_synthesize_reply", synth):
            ev = self.turn(from_voice=True, client_audio=True)
        self.assertEqual(self.spoken, [])  # nothing on the PC speakers
        audio = [e for e in ev if e.get("event") == "audio"]
        self.assertEqual(len(audio), 1)
        clip = audio[0]["url"].split("id=")[1]
        self.assertEqual(chat_app.tts_file(clip).read_bytes(), b"ID3fake")
        self.assertIsNone(chat_app.tts_file("../etc/passwd"))
        self.assertEqual(ev[-1]["status"], "client")


if __name__ == "__main__":
    unittest.main()
