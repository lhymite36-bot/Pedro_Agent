"""Background listener for a short wake phrase.

The microphone stays closed until this loop is running. A short pause in the
room does not call a speech service. After the wake phrase, a chime plays
and the next phrase is recorded as the user's request.
"""

from __future__ import annotations

import os
import queue
import re
import threading
from typing import Any

DEFAULT_WAKE_PHRASE = "hey agent"
commands: queue.Queue[dict[str, Any]] = queue.Queue()
_stop = threading.Event()
_pause = threading.Event()
_thread: threading.Thread | None = None


def _agent() -> Any:
    import agent_core

    return agent_core


def wake_phrase() -> str:
    chosen = os.environ.get("WAKE_PHRASE", "").strip()
    return chosen or DEFAULT_WAKE_PHRASE


def split_wake_phrase(transcript: str, phrase: str | None = None) -> tuple[bool, str]:
    """Return whether the phrase was said, and any words that followed it."""
    target = (phrase or wake_phrase()).casefold().split()
    words = re.findall(r"[a-z0-9']+", (transcript or "").casefold())
    if not target:
        return False, ""
    width = len(target)
    for index in range(len(words) - width + 1):
        if words[index : index + width] == target:
            return True, " ".join(words[index + width :])
    return False, ""


def play_wake_chime() -> None:
    agent = _agent()
    if agent.chime_override is not None:
        agent.chime_override()
        return
    if os.name != "nt":
        return
    import winsound

    winsound.Beep(660, 60)
    winsound.Beep(880, 80)


def drain_commands() -> None:
    while True:
        try:
            commands.get_nowait()
        except queue.Empty:
            return


def poll_wake_command() -> dict[str, Any] | None:
    try:
        item = commands.get_nowait()
    except queue.Empty:
        return None
    if isinstance(item, dict) and item.get("text"):
        return item
    return None


def _poll_wake_audio() -> dict[str, Any]:
    agent = _agent()
    if agent.wake_listen_override is not None:
        heard = agent.wake_listen_override()
        if not isinstance(heard, dict):
            return agent._err("Wake listener returned nothing.")
        return heard
    return agent.listen_to_microphone(
        timeout=1.2,
        announce=False,
    )


def _poll_command_audio() -> dict[str, Any]:
    agent = _agent()
    if agent.command_listen_override is not None:
        heard = agent.command_listen_override()
        if not isinstance(heard, dict):
            return agent._err("Command listener returned nothing.")
        return heard
    return agent.listen_to_microphone()


def _accept_transcript(text: str) -> dict[str, Any] | None:
    matched, rest = split_wake_phrase(text)
    if not matched:
        return None
    play_wake_chime()
    phrase = wake_phrase()
    print(f"[wake] Heard {phrase}.", flush=True)
    if rest:
        return _agent()._ok("Wake word heard.", text=rest, woke=True)
    print("Listening...", flush=True)
    command = _poll_command_audio()
    if not command.get("ok"):
        return command
    payload = dict(command)
    payload["woke"] = True
    return payload


def wake_word_listener(
    stop_event: threading.Event | None = None,
    cycles: int | None = None,
) -> dict[str, Any]:
    """Listen until the wake phrase is heard or the cycle limit is reached.

    Tests pass transcripts through wake_listen_override. The live thread uses
    one open microphone instead of this one-shot helper.
    """
    agent = _agent()
    seen = 0
    while True:
        if stop_event is not None and stop_event.is_set():
            return agent._err("Wake listener stopped.")
        if cycles is not None and seen >= cycles:
            return agent._err("Wake word not heard.")
        seen += 1
        heard = _poll_wake_audio()
        if not heard.get("ok"):
            error = str(heard.get("error") or "")
            if cycles is not None and ("No speech" in error or "Try again" in error):
                continue
            if cycles is None:
                return heard
            continue
        found = _accept_transcript(str(heard.get("text") or ""))
        if found is not None:
            return found


def _persistent_mic_loop(stop: threading.Event) -> None:
    """Keep one microphone open, and release it while voice mode is active."""
    agent = _agent()
    try:
        speech = agent._load_speech_recognition()
    except ImportError:
        print("[wake] speech_recognition is not installed.", flush=True)
        return
    recognizer = speech.Recognizer()
    recognizer.pause_threshold = agent.LISTEN_PAUSE_THRESHOLD
    recognizer.non_speaking_duration = min(
        agent.LISTEN_NON_SPEAKING_SECONDS,
        agent.LISTEN_PAUSE_THRESHOLD,
    )
    try:
        microphone = speech.Microphone()
    except Exception as exc:
        print(f"[wake] {exc}", flush=True)
        return
    while not stop.is_set():
        while _pause.is_set() and not stop.is_set():
            stop.wait(0.2)
        if stop.is_set():
            return
        try:
            source_cm = microphone.__enter__()
        except Exception as exc:
            print(f"[wake] {exc}", flush=True)
            stop.wait(1.0)
            continue
        pending: dict[str, Any] | None = None
        try:
            recognizer.adjust_for_ambient_noise(source_cm, duration=0.3)
            while not stop.is_set() and not _pause.is_set():
                try:
                    audio = recognizer.listen(
                        source_cm,
                        timeout=1.2,
                        phrase_time_limit=None,
                    )
                except speech.WaitTimeoutError:
                    continue
                heard = agent._transcribe_audio(recognizer, audio, speech, None)
                if not heard.get("ok"):
                    continue
                matched, rest = split_wake_phrase(str(heard.get("text") or ""))
                if not matched:
                    continue
                play_wake_chime()
                print(f"[wake] Heard {wake_phrase()}.", flush=True)
                if rest:
                    pending = agent._ok("Wake word heard.", text=rest, woke=True)
                    break
                print("Listening...", flush=True)
                try:
                    command_audio = recognizer.listen(
                        source_cm,
                        timeout=8,
                        phrase_time_limit=None,
                    )
                except speech.WaitTimeoutError:
                    continue
                command = agent._transcribe_audio(
                    recognizer,
                    command_audio,
                    speech,
                    None,
                )
                if command.get("ok") and command.get("text"):
                    pending = dict(command)
                    pending["woke"] = True
                    break
        finally:
            microphone.__exit__(None, None, None)
        if pending is not None:
            _pause.set()
            commands.put(pending)


def _thread_main() -> None:
    agent = _agent()
    if agent.wake_listen_override is not None:
        while not _stop.is_set():
            if _pause.is_set():
                _stop.wait(0.2)
                continue
            try:
                result = wake_word_listener(_stop, cycles=1)
            except Exception as exc:
                print(f"[wake] {exc}", flush=True)
                _stop.wait(1.0)
                continue
            if result.get("ok") and result.get("text"):
                commands.put(result)
        return
    _persistent_mic_loop(_stop)


def start_wake_word_listener() -> None:
    """Start the daemon listener. A second call does nothing while it is alive."""
    global _thread
    if _thread is not None and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_thread_main, name="wake-word", daemon=True)
    _thread.start()


def stop_wake_word_listener() -> None:
    _stop.set()
    _pause.clear()


def pause_wake_listener() -> None:
    _pause.set()


def resume_wake_listener() -> None:
    _pause.clear()
