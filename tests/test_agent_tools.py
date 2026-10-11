"""Tests for path safety, zip extraction, and mod layout. No network or API key."""

from __future__ import annotations

import asyncio
import builtins
import inspect
import io
import json
import os
import struct
import sys
import threading
import tempfile
import time
import types
import unittest
import zipfile
from datetime import datetime
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import gta5_agent


def _guard_screenshot() -> dict[str, object]:
    raise AssertionError("real screenshot")


def _guard_webcam() -> dict[str, object]:
    raise AssertionError("real webcam")


def _guard_pointer(kind: str, details: dict[str, object]) -> None:
    raise AssertionError(f"real pointer {kind}")


def _guard_navigate(url: str) -> None:
    raise AssertionError("real browser")


def _guard_keys(*args: object, **kwargs: object) -> int:
    raise AssertionError("real keyboard")


def _guard_clipboard() -> str:
    raise AssertionError("real clipboard")


def _guard_chime() -> None:
    raise AssertionError("real chime")


def _guard_wake() -> dict[str, object]:
    raise AssertionError("real wake")


def _guard_process(kind: str, payload: dict[str, object] | None = None) -> list[object]:
    raise AssertionError("real process")


def _guard_window(kind: str, payload: dict[str, object] | None = None) -> None:
    raise AssertionError("real window")


def _guard_blender(
    command: list[str],
    script_path: Path,
    output_path: Path,
) -> dict[str, object]:
    raise AssertionError("real blender")


def _guard_blender_notify(message: str) -> None:
    raise AssertionError("real blender voice")


def _guard_blender_open(path: str) -> None:
    raise AssertionError("real file open")


def _guard_program(command: list[str], cwd: Path) -> None:
    raise AssertionError("real program")


def _guard_ffmpeg(command: list[str], destination: Path) -> dict[str, object]:
    raise AssertionError("real ffmpeg")


def _guard_git(command: list[str], cwd: Path) -> dict[str, object]:
    raise AssertionError("real git")


def _guard_browser(plan: dict[str, object], folder: Path) -> dict[str, object]:
    raise AssertionError("real browser")


def _guard_heal(command: list[str], script_path: Path) -> dict[str, object]:
    raise AssertionError("real heal")


def _guard_rewriter(source: str, error: str) -> str:
    raise AssertionError("real gemini")


def _guard_mcp(server: str, method: str, params: dict[str, object]) -> dict[str, object]:
    raise AssertionError("real mcp")


def _guard_genai(api_key: str) -> object:
    raise AssertionError("real gemini")


def _guard_recorder(source: str, seconds: int, dest: Path) -> None:
    raise AssertionError("real microphone")


def _guard_transcriber(path: Path) -> str:
    raise AssertionError("real whisper")


def _guard_telegram_voice(data: bytes) -> str:
    raise AssertionError("real voice note")


def _guard_clipboard_image() -> bytes:
    raise AssertionError("real clipboard image")


def _guard_idle(task: str) -> None:
    raise AssertionError("real idle")


def _guard_delegate(worker: str, task: str) -> dict[str, object]:
    raise AssertionError("real delegate")


def _guard_confirm() -> str:
    raise AssertionError("real confirm")


def _guard_confirm_speak(text: str) -> None:
    raise AssertionError("real confirm")


def _guard_network(command: list[str]) -> dict[str, object]:
    raise AssertionError("real network")


def _guard_diagnostics() -> dict[str, object]:
    raise AssertionError("real diagnostics")


def _guard_checkin() -> str:
    raise AssertionError("real checkin")


def _guard_checkin_speak(text: str) -> None:
    raise AssertionError("real checkin")


def _guard_live_frame() -> bytes:
    raise AssertionError("real webcam")


def _guard_stream_process(command: list[str]) -> object:
    raise AssertionError("real ffmpeg")


def _guard_gmail(payload: dict[str, object]) -> dict[str, object]:
    raise AssertionError("real email")


class AgentToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.original_workspace = gta5_agent.WORKSPACE
        self.original_cache = gta5_agent._game_cache
        self.original_min_exe = gta5_agent.MIN_EXE_BYTES
        self.original_volumes = gta5_agent._volumes
        self.original_downloads = gta5_agent.downloads_override
        self.original_start_menu = gta5_agent.start_menu_override
        self.original_start_target = gta5_agent._start_target
        self.original_screenshot = gta5_agent.screenshot_override
        self.original_webcam = gta5_agent.webcam_override
        self.original_screen_size = gta5_agent.screen_size_override
        self.original_pointer = gta5_agent.pointer_override
        self.original_navigate = gta5_agent.navigate_override
        self.original_keys = gta5_agent.windows_input_override
        self.original_clipboard = gta5_agent.clipboard_override
        self.original_turn = gta5_agent._turn_request
        self.original_plan = gta5_agent._task_plan
        self.original_background = gta5_agent.background_services_enabled
        self.original_search_root = gta5_agent.search_root_override
        self.original_chime = gta5_agent.chime_override
        self.original_wake = gta5_agent.wake_listen_override
        self.original_command_listen = gta5_agent.command_listen_override
        self.original_process = gta5_agent.process_override
        self.original_window = gta5_agent.window_override
        self.original_clock = gta5_agent.scheduler_clock
        self.original_schedule_module = gta5_agent.schedule_module_override
        self.original_blender_exe = gta5_agent.blender_executable_override
        self.original_blender_runner = gta5_agent.blender_runner_override
        self.original_blender_notify = gta5_agent.blender_notify_override
        self.original_blender_open = gta5_agent.blender_open_override
        self.original_program_runner = gta5_agent.program_runner_override
        self.original_remote_transport = gta5_agent.remote_transport_override
        self.original_remote_reply = gta5_agent.remote_reply_override
        self.original_telegram_voice = gta5_agent.telegram_voice_transcriber_override
        self.original_ffmpeg_exe = gta5_agent.ffmpeg_executable_override
        self.original_media_runner = gta5_agent.media_runner_override
        self.original_git_runner = gta5_agent.git_runner_override
        self.original_browser_runner = gta5_agent.browser_runner_override
        self.original_desktop = gta5_agent.desktop_override
        self.original_self_heal = gta5_agent.self_heal_enabled
        self.original_heal_runner = gta5_agent.heal_runner_override
        self.original_heal_rewriter = gta5_agent.heal_rewriter_override
        self.original_mcp_transport = gta5_agent.mcp_transport_override
        self.original_mcp_config = gta5_agent.mcp_config_override
        self.original_network = gta5_agent.network_up_override
        self.original_ollama = gta5_agent.ollama_transport_override
        self.original_ollama_up = gta5_agent.ollama_reachable_override
        self.original_genai_client = gta5_agent.genai_client_override
        self.original_recorder = gta5_agent.recorder_override
        self.original_transcriber = gta5_agent.transcriber_override
        self.original_documents = gta5_agent.documents_override
        self.original_clipboard_image = gta5_agent.clipboard_image_override
        self.original_idle_seconds = gta5_agent.idle_seconds_override
        self.original_idle_limit = gta5_agent.idle_task_seconds_override
        self.original_idle_runner = gta5_agent.idle_runner_override
        self.original_delegate_runner = gta5_agent.delegate_runner_override
        self.original_confirm_listener = gta5_agent.confirm_listener_override
        self.original_confirm_speaker = gta5_agent.confirm_speaker_override
        self.original_network_runner = gta5_agent.network_runner_override
        self.original_diagnostics = gta5_agent.diagnostics_override
        self.original_voice_mode = gta5_agent.voice_mode_active
        self.original_audio_outputs = gta5_agent.audio_output_override
        self.original_checkin_minutes = gta5_agent.checkin_idle_minutes_override
        self.original_checkin_listener = gta5_agent.checkin_listener_override
        self.original_checkin_speaker = gta5_agent.checkin_speaker_override
        self.original_live_frame = gta5_agent.live_frame_override
        self.original_stream_process = gta5_agent.stream_process_override
        self.original_live_bind = gta5_agent.live_bind_override
        self.original_live_advertise = gta5_agent.live_advertise_override
        self.original_gmail = gta5_agent.gmail_transport_override
        self.original_contacts = gta5_agent.contacts_override
        self.original_local_turn = gta5_agent._turn_is_local
        self._drive_env = {
            key: os.environ.pop(key, None)
            for key in ("EXTERNAL_DRIVE_LABEL", "EXTERNAL_DRIVE_PATH", "STORAGE_DIR")
        }
        os.environ["EXTERNAL_DRIVE_LABEL"] = "GameDrive"
        self._remote_env = {
            key: os.environ.pop(key, None)
            for key in (
                "TELEGRAM_BOT_TOKEN",
                "TELEGRAM_CHAT_ID",
                "DISCORD_WEBHOOK_URL",
                "TELEGRAM_RTMP_URL",
                "TELEGRAM_STREAM_KEY",
                "LIVE_PUBLIC_URL",
                "LIVE_VIDEO_PORT",
                "LIVE_STREAM_SECONDS",
                "GMAIL_ADDRESS",
                "GMAIL_APP_PASSWORD",
                "TELEGRAM_VOICE_REACTION",
            )
        }
        self._local_env = {
            key: os.environ.pop(key, None)
            for key in ("PRIVACY_MODE", "LOCAL_LLM")
        }
        gta5_agent.WORKSPACE = self.root / "workspace"
        gta5_agent._game_cache = None
        gta5_agent.MIN_EXE_BYTES = 1
        gta5_agent.downloads_override = None
        gta5_agent.screenshot_override = _guard_screenshot
        gta5_agent.webcam_override = _guard_webcam
        gta5_agent.screen_size_override = (1920, 1080)
        gta5_agent.pointer_override = _guard_pointer
        gta5_agent.navigate_override = _guard_navigate
        gta5_agent.windows_input_override = _guard_keys
        gta5_agent.clipboard_override = _guard_clipboard
        gta5_agent.background_services_enabled = False
        gta5_agent.search_root_override = self.root / "pedro"
        gta5_agent.search_root_override.mkdir()
        gta5_agent.chime_override = _guard_chime
        gta5_agent.wake_listen_override = _guard_wake
        gta5_agent.command_listen_override = _guard_wake
        gta5_agent.process_override = _guard_process
        gta5_agent.window_override = _guard_window
        gta5_agent.scheduler_clock = None
        gta5_agent.schedule_module_override = None
        gta5_agent.blender_executable_override = None
        gta5_agent.blender_runner_override = _guard_blender
        gta5_agent.blender_notify_override = _guard_blender_notify
        gta5_agent.blender_open_override = _guard_blender_open
        gta5_agent.program_runner_override = _guard_program
        gta5_agent.remote_transport_override = None
        gta5_agent.remote_reply_override = None
        gta5_agent.telegram_voice_transcriber_override = _guard_telegram_voice
        gta5_agent.ffmpeg_executable_override = Path("ffmpeg-test")
        gta5_agent.media_runner_override = _guard_ffmpeg
        gta5_agent.git_runner_override = _guard_git
        gta5_agent.browser_runner_override = _guard_browser
        gta5_agent.desktop_override = self.root / "Desktop"
        gta5_agent.self_heal_enabled = False
        gta5_agent.heal_runner_override = _guard_heal
        gta5_agent.heal_rewriter_override = _guard_rewriter
        gta5_agent.mcp_transport_override = _guard_mcp
        gta5_agent.mcp_config_override = self.root / "no-mcp-servers.json"
        gta5_agent.network_up_override = True
        gta5_agent.ollama_transport_override = None
        gta5_agent.ollama_reachable_override = False
        gta5_agent.genai_client_override = _guard_genai
        gta5_agent.recorder_override = _guard_recorder
        gta5_agent.transcriber_override = _guard_transcriber
        gta5_agent.documents_override = self.root / "Documents"
        gta5_agent.clipboard_image_override = _guard_clipboard_image
        gta5_agent.idle_seconds_override = 0
        gta5_agent.idle_task_seconds_override = None
        gta5_agent.idle_runner_override = _guard_idle
        gta5_agent.delegate_runner_override = _guard_delegate
        gta5_agent.confirm_listener_override = _guard_confirm
        gta5_agent.confirm_speaker_override = _guard_confirm_speak
        gta5_agent.network_runner_override = _guard_network
        gta5_agent.diagnostics_override = _guard_diagnostics
        gta5_agent.voice_mode_active = False
        gta5_agent.audio_output_override = None
        gta5_agent.checkin_idle_minutes_override = None
        gta5_agent.checkin_listener_override = _guard_checkin
        gta5_agent.checkin_speaker_override = _guard_checkin_speak
        gta5_agent.live_frame_override = _guard_live_frame
        gta5_agent.stream_process_override = _guard_stream_process
        gta5_agent.live_bind_override = ("127.0.0.1", 0)
        gta5_agent.live_advertise_override = "127.0.0.1"
        gta5_agent.gmail_transport_override = _guard_gmail
        gta5_agent.contacts_override = []
        gta5_agent._turn_is_local = False
        gta5_agent.reset_background_state()
        gta5_agent.begin_task_turn("")
        import confirm_action
        import emotion
        import routine_macros
        import voice_checkin

        emotion.reset()
        confirm_action.reset()
        voice_checkin.reset()
        routine_macros.reset()
        gta5_agent._disarm_playback()
        self.addCleanup(self.restore)

    def restore(self) -> None:
        gta5_agent.WORKSPACE = self.original_workspace
        gta5_agent._game_cache = self.original_cache
        gta5_agent.MIN_EXE_BYTES = self.original_min_exe
        gta5_agent._volumes = self.original_volumes
        gta5_agent.downloads_override = self.original_downloads
        gta5_agent.start_menu_override = self.original_start_menu
        gta5_agent._start_target = self.original_start_target
        gta5_agent.screenshot_override = self.original_screenshot
        gta5_agent.webcam_override = self.original_webcam
        gta5_agent.screen_size_override = self.original_screen_size
        gta5_agent.pointer_override = self.original_pointer
        gta5_agent.navigate_override = self.original_navigate
        gta5_agent.windows_input_override = self.original_keys
        gta5_agent.clipboard_override = self.original_clipboard
        gta5_agent._turn_request = self.original_turn
        gta5_agent._task_plan = self.original_plan
        gta5_agent.background_services_enabled = self.original_background
        gta5_agent.search_root_override = self.original_search_root
        gta5_agent.chime_override = self.original_chime
        gta5_agent.wake_listen_override = self.original_wake
        gta5_agent.command_listen_override = self.original_command_listen
        gta5_agent.process_override = self.original_process
        gta5_agent.window_override = self.original_window
        gta5_agent.scheduler_clock = self.original_clock
        gta5_agent.schedule_module_override = self.original_schedule_module
        gta5_agent.reset_background_state()
        gta5_agent.blender_executable_override = self.original_blender_exe
        gta5_agent.blender_runner_override = self.original_blender_runner
        gta5_agent.blender_notify_override = self.original_blender_notify
        gta5_agent.blender_open_override = self.original_blender_open
        gta5_agent.program_runner_override = self.original_program_runner
        gta5_agent.remote_transport_override = self.original_remote_transport
        gta5_agent.remote_reply_override = self.original_remote_reply
        gta5_agent.telegram_voice_transcriber_override = self.original_telegram_voice
        gta5_agent.ffmpeg_executable_override = self.original_ffmpeg_exe
        gta5_agent.media_runner_override = self.original_media_runner
        gta5_agent.git_runner_override = self.original_git_runner
        gta5_agent.browser_runner_override = self.original_browser_runner
        gta5_agent.desktop_override = self.original_desktop
        gta5_agent.self_heal_enabled = self.original_self_heal
        gta5_agent.heal_runner_override = self.original_heal_runner
        gta5_agent.heal_rewriter_override = self.original_heal_rewriter
        gta5_agent.mcp_transport_override = self.original_mcp_transport
        gta5_agent.mcp_config_override = self.original_mcp_config
        gta5_agent.network_up_override = self.original_network
        gta5_agent.ollama_transport_override = self.original_ollama
        gta5_agent.ollama_reachable_override = self.original_ollama_up
        gta5_agent.genai_client_override = self.original_genai_client
        gta5_agent.recorder_override = self.original_recorder
        gta5_agent.transcriber_override = self.original_transcriber
        gta5_agent.documents_override = self.original_documents
        gta5_agent.clipboard_image_override = self.original_clipboard_image
        gta5_agent.idle_seconds_override = self.original_idle_seconds
        gta5_agent.idle_task_seconds_override = self.original_idle_limit
        gta5_agent.idle_runner_override = self.original_idle_runner
        gta5_agent.delegate_runner_override = self.original_delegate_runner
        gta5_agent.confirm_listener_override = self.original_confirm_listener
        gta5_agent.confirm_speaker_override = self.original_confirm_speaker
        gta5_agent.network_runner_override = self.original_network_runner
        gta5_agent.diagnostics_override = self.original_diagnostics
        gta5_agent.voice_mode_active = self.original_voice_mode
        gta5_agent.audio_output_override = self.original_audio_outputs
        gta5_agent.checkin_idle_minutes_override = self.original_checkin_minutes
        gta5_agent.checkin_listener_override = self.original_checkin_listener
        gta5_agent.checkin_speaker_override = self.original_checkin_speaker
        gta5_agent.live_frame_override = self.original_live_frame
        gta5_agent.stream_process_override = self.original_stream_process
        gta5_agent.live_bind_override = self.original_live_bind
        gta5_agent.live_advertise_override = self.original_live_advertise
        gta5_agent.gmail_transport_override = self.original_gmail
        gta5_agent.contacts_override = self.original_contacts
        gta5_agent._turn_is_local = self.original_local_turn
        for key, value in self._remote_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        for key, value in self._drive_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        for key, value in self._local_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def make_game(self) -> Path:
        game = self.root / "Grand Theft Auto V"
        game.mkdir()
        (game / "GTA5.exe").write_bytes(b"exe")
        gta5_agent._game_cache = {
            "path": str(game),
            "volume_label": "GameDrive",
            "drive": "E:",
        }
        return game

    def test_search_finds_common_folder(self) -> None:
        drive = self.root / "drive"
        game = drive / "Games" / "Grand Theft Auto V"
        game.mkdir(parents=True)
        (game / "GTA5.exe").write_bytes(b"exe")
        found = gta5_agent._search_for_gta5(drive)
        self.assertEqual(found, game)

    def test_locate_matches_volume_label(self) -> None:
        drive = self.root / "pedro"
        game = drive / "Games" / "Grand Theft Auto V"
        game.mkdir(parents=True)
        (game / "GTA5.exe").write_bytes(b"exe")
        gta5_agent._volumes = lambda: [(str(drive) + "\\", "GameDrive")]
        result = gta5_agent.locate_gta5_directory(rescan=True)
        self.assertTrue(result["ok"])
        self.assertEqual(Path(result["game_root"]), game)

        gta5_agent._volumes = lambda: []
        cached = gta5_agent.locate_gta5_directory(rescan=False)
        self.assertTrue(cached["ok"])
        self.assertTrue(cached["cached"])

    def test_locate_reports_missing_label(self) -> None:
        gta5_agent._volumes = lambda: [("E:\\", "Other Disk")]
        result = gta5_agent.locate_gta5_directory(rescan=True, volume_label="GameDrive")
        self.assertFalse(result["ok"])
        self.assertIn("GameDrive", result["error"])
        self.assertIn("Other Disk", result["error"])

    def test_create_directory_stays_inside_game(self) -> None:
        game = self.make_game()
        created = gta5_agent.create_directory("scripts/AddonPeds")
        self.assertTrue(created["ok"])
        self.assertTrue((game / "scripts" / "AddonPeds").is_dir())
        escaped = gta5_agent.create_directory("../Windows")
        self.assertFalse(escaped["ok"])
        self.assertIn("escapes", escaped["error"])

    def test_copy_refuses_executables_and_keeps_existing_files(self) -> None:
        game = self.make_game()
        source = self.root / "ScriptHookV.dll"
        source.write_bytes(b"dll")
        copied = gta5_agent.copy_mod_files(str(source), ".")
        self.assertTrue(copied["ok"])
        self.assertEqual((game / "ScriptHookV.dll").read_bytes(), b"dll")

        again = gta5_agent.copy_mod_files(str(source), ".")
        self.assertFalse(again["ok"])
        self.assertIn("Already exists", again["error"])

        exe = self.root / "patch.exe"
        exe.write_bytes(b"nope")
        refused = gta5_agent.copy_mod_files(str(exe), ".")
        self.assertFalse(refused["ok"])
        self.assertIn("executable", refused["error"])
        self.assertEqual((game / "GTA5.exe").read_bytes(), b"exe")

    def test_copy_merges_scripts_folder(self) -> None:
        game = self.make_game()
        folder = self.root / "scripts"
        folder.mkdir()
        (folder / "MyMod.dll").write_bytes(b"mod")
        result = gta5_agent.copy_mod_files(str(folder), "scripts")
        self.assertTrue(result["ok"])
        self.assertEqual((game / "scripts" / "MyMod.dll").read_bytes(), b"mod")

    def test_integrate_sorts_types_and_preserves_dlcpacks(self) -> None:
        game = self.make_game()
        source = self.root / "extracted"
        (source / "scripts").mkdir(parents=True)
        (source / "update" / "x64" / "dlcpacks" / "horror").mkdir(parents=True)
        (source / "ScriptHookV.dll").write_bytes(b"hook")
        (source / "trainer.asi").write_bytes(b"asi")
        (source / "scripts" / "Story.dll").write_bytes(b"story")
        model = source / "update" / "x64" / "dlcpacks" / "horror" / "hero.ytd"
        model.write_bytes(b"ytd")
        (source / "launcher.exe").write_bytes(b"bad")

        result = gta5_agent.integrate_custom_assets(str(source), pack_name="ignored")
        self.assertTrue(result["ok"])
        self.assertEqual((game / "ScriptHookV.dll").read_bytes(), b"hook")
        self.assertEqual((game / "trainer.asi").read_bytes(), b"asi")
        self.assertEqual((game / "scripts" / "Story.dll").read_bytes(), b"story")
        placed = game / "mods" / "update" / "x64" / "dlcpacks" / "horror" / "hero.ytd"
        self.assertEqual(placed.read_bytes(), b"ytd")
        self.assertFalse((game / "launcher.exe").exists())
        self.assertTrue(any("OpenIV" in note for note in result["notes"]))

    def test_integrate_addon_peds_layout(self) -> None:
        game = self.make_game()
        source = self.root / "ped"
        source.mkdir()
        (source / "hero.ydd").write_bytes(b"ydd")
        (source / "hero.yft").write_bytes(b"yft")
        result = gta5_agent.integrate_custom_assets(
            str(source),
            pack_name="horror ped",
            layout="addon_peds",
        )
        self.assertTrue(result["ok"])
        ped = game / "scripts" / "AddonPeds" / "horror_ped"
        self.assertEqual((ped / "hero.ydd").read_bytes(), b"ydd")
        self.assertEqual((ped / "hero.yft").read_bytes(), b"yft")

    def test_zip_slip_is_rejected_and_safe_zip_extracts(self) -> None:
        dest = self.root / "out"
        good = self.root / "good.zip"
        with zipfile.ZipFile(good, "w") as archive:
            archive.writestr("pack/readme.txt", "hello")
            archive.writestr("pack/hero.ytd", "tex")
        summary = gta5_agent._extract_zip(good, dest)
        self.assertEqual(summary["files_written"], 2)
        self.assertEqual((dest / "pack" / "readme.txt").read_text(encoding="utf-8"), "hello")

        slipped = self.root / "bad.zip"
        with zipfile.ZipFile(slipped, "w") as archive:
            archive.writestr("../outside.txt", "nope")
        with self.assertRaises(ValueError):
            gta5_agent._extract_zip(slipped, self.root / "bad-out")
        self.assertFalse((self.root / "outside.txt").exists())

    def test_download_rejects_non_http_and_local_addresses(self) -> None:
        file_url = gta5_agent.download_and_extract_zip("file:///C:/Windows/notepad.exe")
        self.assertFalse(file_url["ok"])
        local = gta5_agent.download_and_extract_zip("http://127.0.0.1/mod.zip")
        self.assertFalse(local["ok"])
        self.assertIn("non-public", local["error"])
        missing = gta5_agent.download_and_extract_zip("")
        self.assertFalse(missing["ok"])

    def test_archive_links_are_extracted_from_html(self) -> None:
        html = """
        <html><body>
          <a href="/files/mod.zip">direct</a>
          <a href="https://cdn.example.com/a/pack.7z?token=1">cdn</a>
          <a href="https://duckduckgo.com/l/?uddg=https%3A%2F%2Ffiles.example.com%2Fhero.rar">
            wrapped
          </a>
          <a href="/readme.html">notes</a>
          <a href="javascript:void(0)">nope</a>
        </body></html>
        """
        links = gta5_agent._archive_links_from_html(html, "https://mods.example.com/page")
        self.assertEqual(
            links,
            [
                "https://mods.example.com/files/mod.zip",
                "https://cdn.example.com/a/pack.7z?token=1",
                "https://files.example.com/hero.rar",
            ],
        )

    def test_search_refuses_game_repacks(self) -> None:
        result = gta5_agent.search_and_find_mod_download("gta v fitgirl repack")
        self.assertFalse(result["ok"])
        self.assertIn("does not download", result["error"])

    def test_scan_downloads_matches_and_extracts_without_deleting_original(self) -> None:
        folder = self.root / "Downloads"
        folder.mkdir()
        archive = folder / "simple-zombies-reborn.zip"
        with zipfile.ZipFile(archive, "w") as packed:
            packed.writestr("scripts/Zombies.dll", "z")
        with zipfile.ZipFile(folder / "unrelated.zip", "w") as packed:
            packed.writestr("a.txt", "a")
        gta5_agent.downloads_override = folder

        found = gta5_agent.scan_user_downloads_folder("Simple Zombies Reborn")
        self.assertTrue(found["ok"])
        self.assertEqual(found["matches"][0]["name"], "simple-zombies-reborn.zip")

        extracted = gta5_agent.scan_user_downloads_folder(
            "Simple Zombies Reborn",
            extract=True,
        )
        self.assertTrue(extracted["ok"])
        extracted_root = Path(extracted["extracted_root"])
        self.assertTrue((extracted_root / "Zombies.dll").is_file())
        self.assertTrue(archive.is_file())
        missed = gta5_agent.scan_user_downloads_folder("missing mod name", extract=True)
        self.assertFalse(missed["ok"])

    def test_daily_quota_message_is_short(self) -> None:
        error = RuntimeError(
            "429 RESOURCE_EXHAUSTED. Quota exceeded for metric: "
            "generativelanguage.googleapis.com/generate_content_free_tier_requests, "
            "limit: 20, model: gemini-3.8-flash. Please retry in 15h3m35.9s."
        )
        self.assertTrue(gta5_agent._is_daily_quota(error))
        message = gta5_agent._quota_message(error)
        self.assertIn("gemini-3.8-flash", message)
        self.assertIn("20", message)
        self.assertIn("15h", message)
        self.assertNotIn("RESOURCE_EXHAUSTED", message)

    def test_connection_drop_is_retryable(self) -> None:
        error = ConnectionAbortedError(
            10053,
            "An established connection was aborted by the software in your host machine",
        )
        self.assertTrue(gta5_agent._transient_network_error(error))
        self.assertFalse(gta5_agent._transient_network_error(FileNotFoundError("missing")))

    def test_launch_matches_start_menu_and_rejects_shell_text(self) -> None:
        menu = self.root / "start" / "Programs"
        menu.mkdir(parents=True)
        shortcut = menu / "Widget Studio.lnk"
        shortcut.write_bytes(b"")
        gta5_agent.start_menu_override = self.root / "start"
        started: list[str] = []
        gta5_agent._start_target = lambda target: started.append(str(target))

        opened = gta5_agent.launch_application("widget studio")
        self.assertTrue(opened["ok"])
        self.assertEqual(Path(started[0]), shortcut)
        rejected = gta5_agent.launch_application("widget & calc.exe")
        self.assertFalse(rejected["ok"])
        self.assertEqual(len(started), 1)

    def test_browser_tools_build_safe_addresses(self) -> None:
        self.assertEqual(
            gta5_agent._youtube_search_url("GTA 5 mods"),
            "https://www.youtube.com/results?search_query=GTA+5+mods",
        )
        blocked = gta5_agent.open_website("file:///C:/Windows/notepad.exe")
        self.assertFalse(blocked["ok"])
        script = gta5_agent.open_website("javascript:alert(1)")
        self.assertFalse(script["ok"])

    def test_excel_task_saves_on_pedro_and_blocks_formulas(self) -> None:
        drive = self.root / "pedrodrive"
        drive.mkdir()
        gta5_agent._volumes = lambda: [(str(drive) + "\\", "GameDrive")]
        instructions = json.dumps(
            {"sheet": "Sales", "headers": ["Item", "Amount"], "rows": [["Hats", 12]]}
        )
        saved = gta5_agent.automate_excel_task("GameDrive/reports/sales.xlsx", instructions)
        self.assertTrue(saved["ok"], saved)
        workbook_path = drive / "reports" / "sales.xlsx"
        self.assertTrue(workbook_path.is_file())
        from openpyxl import load_workbook

        workbook = load_workbook(workbook_path)
        self.assertEqual(workbook["Sales"]["A2"].value, "Hats")
        self.assertEqual(workbook["Sales"]["B2"].value, 12)

        dangerous = json.dumps(
            {"sheet": "Sales", "headers": ["Item"], "rows": [["=cmd|'/c calc'!A0"]]}
        )
        refused = gta5_agent.automate_excel_task(str(workbook_path), dangerous)
        self.assertFalse(refused["ok"])
        system_path = gta5_agent.automate_excel_task(
            r"C:\Windows\sales.xlsx",
            instructions,
        )
        self.assertFalse(system_path["ok"])

    def test_sql_task_exports_and_blocks_unsafe_statements(self) -> None:
        database = self.root / "workspace" / "shop.db"
        created = gta5_agent.execute_sql_task(
            str(database),
            "CREATE TABLE sale (item TEXT, amount INT)",
            allow_changes=True,
        )
        self.assertTrue(created["ok"], created)
        inserted = gta5_agent.execute_sql_task(
            str(database),
            "INSERT INTO sale VALUES ('Hats', 12)",
            allow_changes=True,
        )
        self.assertTrue(inserted["ok"], inserted)
        output = self.root / "workspace" / "sale.csv"
        selected = gta5_agent.execute_sql_task(
            str(database),
            "SELECT item, amount FROM sale",
            str(output),
        )
        self.assertTrue(selected["ok"], selected)
        self.assertIn("Hats,12", output.read_text(encoding="utf-8"))

        attached = gta5_agent.execute_sql_task(
            str(database),
            "ATTACH DATABASE 'other.db' AS other",
            allow_changes=True,
        )
        self.assertFalse(attached["ok"])
        dropped = gta5_agent.execute_sql_task(str(database), "DROP TABLE sale")
        self.assertFalse(dropped["ok"])
        self.assertIn("allow_changes", dropped["error"])
        stacked = gta5_agent.execute_sql_task(
            str(database),
            "SELECT 1; DROP TABLE sale",
        )
        self.assertFalse(stacked["ok"])
        remote = gta5_agent.execute_sql_task(
            "Driver={SQL Server};Server=evil.example.com;Database=x;",
            "SELECT 1",
        )
        self.assertFalse(remote["ok"])
        self.assertIn("localhost", remote["error"])

    def test_locked_copy_returns_an_error_string(self) -> None:
        game = self.make_game()
        target_dir = game / "scripts"
        target_dir.mkdir()
        blocked = target_dir / "MyMod.dll"
        blocked.write_bytes(b"old")

        def explode(source: Path, dest: Path) -> None:
            raise PermissionError("used by another process")

        original = gta5_agent.shutil.copy2
        gta5_agent.shutil.copy2 = explode
        self.addCleanup(setattr, gta5_agent.shutil, "copy2", original)
        source = self.root / "MyMod.dll"
        source.write_bytes(b"new")
        result = gta5_agent.copy_mod_files(str(source), "scripts", overwrite=True)
        self.assertFalse(result["ok"])
        self.assertIn("Close Grand Theft Auto V", result["error"])

    def test_voice_commands_stay_out_of_the_model_tools(self) -> None:
        names = [item["name"] for item in gta5_agent.TOOL_DECLARATIONS]
        self.assertNotIn("listen_to_microphone", gta5_agent.TOOLS)
        self.assertNotIn("speak_response", gta5_agent.TOOLS)
        self.assertNotIn("listen_to_microphone", names)
        self.assertNotIn("speak_response", names)
        self.assertEqual(gta5_agent.local_input_command("V", spoken=False), "voice")
        self.assertEqual(
            gta5_agent.local_input_command("Text mode.", spoken=True),
            "text",
        )
        self.assertEqual(gta5_agent.local_input_command("exit", spoken=True), "exit")
        self.assertIsNone(
            gta5_agent.local_input_command("Install text mode pack", spoken=True)
        )
        self.assertIsNone(gta5_agent.local_input_command("Open Excel", spoken=False))
        self.assertEqual(gta5_agent._mode_from_key("T"), "text")
        self.assertEqual(gta5_agent._mode_from_key("v"), "voice")

    def test_windows_audio_wheel_is_used_as_pyaudio(self) -> None:
        fake = types.ModuleType("pyaudiowpatch")
        with mock.patch.dict(
            sys.modules,
            {"pyaudio": None, "pyaudiowpatch": fake},
        ):
            gta5_agent._ensure_pyaudio()
            self.assertIs(sys.modules["pyaudio"], fake)

    def test_listen_transcribes_and_reports_microphone_errors(self) -> None:
        speech = _speech_module(google_text="Open Excel")
        captured: dict[str, float] = {}
        real_listen = speech.Recognizer.listen

        def listen(
            self: object,
            source: object,
            timeout: float = 8,
            phrase_time_limit: float = 20,
        ) -> bytes:
            captured["pause_threshold"] = getattr(self, "pause_threshold")
            captured["non_speaking_duration"] = getattr(self, "non_speaking_duration")
            captured["phrase_time_limit"] = phrase_time_limit
            return real_listen(self, source, timeout, phrase_time_limit)

        speech.Recognizer.listen = listen
        heard = gta5_agent.listen_to_microphone(
            speech_module=speech,
            whisper_loader=_whisper_must_not_run,
        )
        self.assertTrue(heard["ok"])
        self.assertEqual(heard["text"], "Open Excel")
        self.assertEqual(captured["pause_threshold"], 2.0)
        self.assertEqual(
            captured["non_speaking_duration"],
            gta5_agent.LISTEN_NON_SPEAKING_SECONDS,
        )
        self.assertLessEqual(
            captured["non_speaking_duration"],
            captured["pause_threshold"],
        )
        self.assertIsNone(captured["phrase_time_limit"])

        quiet = _speech_module(listen="timeout")
        timed_out = gta5_agent.listen_to_microphone(speech_module=quiet)
        self.assertFalse(timed_out["ok"])
        self.assertIn("No speech", timed_out["error"])
        self.assertFalse(gta5_agent._voice_hardware_failure(timed_out["error"]))

        unclear = _speech_module(google="unknown")
        missed = gta5_agent.listen_to_microphone(speech_module=unclear)
        self.assertIn("understand", missed["error"])

        offline = _speech_module(google="request")
        fallback = gta5_agent.listen_to_microphone(
            speech_module=offline,
            whisper_loader=lambda: object(),
        )
        self.assertTrue(fallback["ok"])
        self.assertEqual(fallback["text"], "Open Excel")

        no_whisper = gta5_agent.listen_to_microphone(
            speech_module=offline,
            whisper_loader=_missing_whisper,
        )
        self.assertFalse(no_whisper["ok"])
        self.assertIn("Whisper", no_whisper["error"])
        self.assertFalse(gta5_agent._voice_hardware_failure(no_whisper["error"]))

        missing_mic = _speech_module(microphone="missing")
        blocked = gta5_agent.listen_to_microphone(speech_module=missing_mic)
        self.assertIn("No microphone", blocked["error"])
        self.assertTrue(gta5_agent._voice_hardware_failure(blocked["error"]))

        missing_audio = _speech_module(microphone="pyaudio")
        unavailable = gta5_agent.listen_to_microphone(speech_module=missing_audio)
        self.assertIn("PyAudio", unavailable["error"])
        self.assertTrue(gta5_agent._voice_hardware_failure(unavailable["error"]))

        with mock.patch.object(
            gta5_agent,
            "_load_speech_recognition",
            side_effect=ImportError("no module"),
        ):
            missing = gta5_agent.listen_to_microphone()
        self.assertIn("speech_recognition", missing["error"])
        self.assertTrue(gta5_agent._voice_hardware_failure(missing["error"]))

    def test_speak_response_uses_the_neural_voice_and_hides_failures(self) -> None:
        played: list[Path] = []

        def synthesize(text: str, destination: Path, voice: str) -> None:
            self.assertEqual(text, "Open Excel.")
            self.assertEqual(voice, "en-US-AriaNeural")
            destination.write_bytes(b"mp3-bytes")

        def play(path: Path) -> None:
            self.assertEqual(path.read_bytes(), b"mp3-bytes")
            played.append(path)

        spoken = gta5_agent.speak_response(
            "  Open   Excel. ",
            synthesizer=synthesize,
            player=play,
        )
        self.assertTrue(spoken["ok"])
        self.assertEqual(spoken["text"], "Open Excel.")
        self.assertEqual(spoken["voice"], "en-US-AriaNeural")
        self.assertEqual(len(played), 1)
        self.assertFalse(played[0].exists())

        previous = os.environ.get("EDGE_TTS_VOICE")
        os.environ["EDGE_TTS_VOICE"] = "en-US-ChristopherNeural"
        self.addCleanup(self._restore_env, "EDGE_TTS_VOICE", previous)
        voices: list[str] = []

        def synthesize_named(text: str, destination: Path, voice: str) -> None:
            voices.append(voice)
            destination.write_bytes(b"mp3")

        named = gta5_agent.speak_response(
            "Hello",
            synthesizer=synthesize_named,
            player=lambda path: None,
        )
        self.assertEqual(voices, ["en-US-ChristopherNeural"])
        self.assertEqual(named["voice"], "en-US-ChristopherNeural")

        def fail_playback(path: Path) -> None:
            raise RuntimeError("mixer busy")

        failed = gta5_agent.speak_response(
            "Hi",
            synthesizer=lambda text, destination, voice: destination.write_bytes(b"x"),
            player=fail_playback,
        )
        self.assertFalse(failed["ok"])
        self.assertIn("mixer busy", failed["error"])

        missing = gta5_agent.speak_response(
            "Hi",
            synthesizer=lambda text, destination, voice: (_ for _ in ()).throw(
                ImportError("No module named 'edge_tts'")
            ),
        )
        self.assertIn("edge-tts", missing["error"])

        silent = gta5_agent.speak_response(
            "Hi",
            synthesizer=lambda text, destination, voice: None,
            player=lambda path: None,
        )
        self.assertIn("no audio", silent["error"])

    def test_tts_strips_markdown_and_keeps_the_chat_text(self) -> None:
        raw = "See **bold** and `code` in [# heading](https://example.com/a)."
        display = " ".join(raw.split())
        self.assertEqual(
            gta5_agent.clean_text_for_tts(raw),
            "See bold and code in heading.",
        )
        self.assertEqual(
            gta5_agent.clean_text_for_tts("Read [the notes](https://example.com)."),
            "Read the notes.",
        )
        self.assertEqual(gta5_agent.clean_text_for_tts("*** ` ` ###"), "")

        heard: list[str] = []

        def synthesize(text: str, destination: Path, voice: str) -> None:
            heard.append(text)
            destination.write_bytes(b"mp3")

        spoken = gta5_agent.speak_response(
            raw,
            synthesizer=synthesize,
            player=lambda path: None,
        )
        self.assertTrue(spoken["ok"])
        self.assertEqual(spoken["text"], display)
        self.assertIn("**", spoken["text"])
        self.assertEqual(heard, ["See bold and code in heading."])

        skipped = gta5_agent.speak_response(
            "***",
            synthesizer=synthesize,
            player=lambda path: None,
        )
        self.assertTrue(skipped["ok"])
        self.assertEqual(skipped["text"], "***")
        self.assertEqual(heard, ["See bold and code in heading."])

        pipeline_heard: list[str] = []

        def synthesize_sentence(text: str, destination: Path, voice: str) -> None:
            pipeline_heard.append(text)
            destination.write_bytes(b"mp3")

        pipeline = gta5_agent._SpeechPipeline(
            synthesizer=synthesize_sentence,
            player=lambda path: None,
        )
        self.addCleanup(pipeline.abort)
        pipeline.submit("**Hello** [docs](https://example.com).")
        pipeline.submit("###")
        result = pipeline.finish()
        self.assertTrue(result["ok"], result)
        self.assertEqual(pipeline_heard, ["Hello docs."])

    def test_neural_voice_stream_writes_audio_bytes(self) -> None:
        captured: list[tuple[str, str]] = []

        class Communicate:
            def __init__(
                self,
                text: str,
                voice: str,
                rate: str = "+0%",
                pitch: str = "+0Hz",
            ) -> None:
                captured.append((text, voice))

            async def stream(self) -> Any:
                yield {"type": "audio", "data": b"abc"}
                yield {"type": "WordBoundary", "text": "Hi"}
                yield {"type": "audio", "data": b"def"}

        fake = types.ModuleType("edge_tts")
        fake.Communicate = Communicate
        destination = self.root / "reply.mp3"
        with mock.patch.dict(sys.modules, {"edge_tts": fake}):
            gta5_agent._run_coroutine(
                gta5_agent._stream_neural_speech(
                    "Hi",
                    "en-US-AriaNeural",
                    destination,
                )
            )
        self.assertEqual(captured, [("Hi", "en-US-AriaNeural")])
        self.assertEqual(destination.read_bytes(), b"abcdef")

        with mock.patch.dict(sys.modules, {"edge_tts": fake}):
            gta5_agent._run_coroutine(
                gta5_agent._stream_neural_speech(
                    "Use **mods** from [Pedro](https://example.com).",
                    "en-US-AriaNeural",
                    destination,
                )
            )
        self.assertEqual(
            captured[-1],
            ("Use mods from Pedro.", "en-US-AriaNeural"),
        )

        class EmptyCommunicate:
            def __init__(
                self,
                text: str,
                voice: str,
                rate: str = "+0%",
                pitch: str = "+0Hz",
            ) -> None:
                return None

            async def stream(self) -> Any:
                if False:
                    yield {"type": "audio", "data": b""}

        empty = types.ModuleType("edge_tts")
        empty.Communicate = EmptyCommunicate
        empty_path = self.root / "empty.mp3"
        with mock.patch.dict(sys.modules, {"edge_tts": empty}):
            with self.assertRaises(RuntimeError):
                gta5_agent._run_coroutine(
                    gta5_agent._stream_neural_speech("Hi", "en-US-AriaNeural", empty_path)
                )

    def test_sentences_split_as_soon_as_punctuation_arrives(self) -> None:
        buffer = gta5_agent._SentenceBuffer()
        self.assertEqual(buffer.push("First sentence. "), ["First sentence."])
        self.assertEqual(buffer.pending, "")
        self.assertEqual(buffer.push("Second"), [])
        self.assertEqual(buffer.flush(), ["Second"])
        self.assertEqual(buffer.push("One\nTwo."), ["One"])
        self.assertEqual(buffer.flush(), ["Two."])

        long_text = ("alpha " * 40).strip()
        limited = gta5_agent._SentenceBuffer()
        pieces = limited.push(long_text)
        self.assertTrue(pieces)
        self.assertLessEqual(len(pieces[0]), gta5_agent.VOICE_SENTENCE_CHARS)
        self.assertTrue(limited.flush())

    def test_voice_stream_speaks_the_first_sentence_before_the_rest(self) -> None:
        release = threading.Event()
        pulled_second = {"yes": False}

        def chunks() -> object:
            yield _voice_chunk(_voice_text("First sentence. "))
            pulled_second["yes"] = True
            if not release.wait(2):
                raise TimeoutError("the first sentence was not handed off")
            yield _voice_chunk(_voice_text("Second sentence."))

        seen: list[str] = []

        def on_sentence(sentence: str) -> None:
            seen.append(sentence)
            if sentence.startswith("First"):
                self.assertFalse(pulled_second["yes"])
                release.set()

        _parts, _calls, text = gta5_agent._accumulate_voice_stream(
            chunks(),
            on_sentence,
            None,
        )
        self.assertEqual(seen, ["First sentence.", "Second sentence."])
        self.assertIn("First sentence.", text)
        self.assertIn("Second sentence.", text)

        repeated: list[str] = []
        _parts, _calls, repeated_text = gta5_agent._accumulate_voice_stream(
            [
                _voice_chunk(_voice_text("First sentence. ")),
                _voice_chunk(_voice_text("First sentence. Second sentence.")),
            ],
            repeated.append,
            None,
        )
        self.assertEqual(repeated, ["First sentence.", "Second sentence."])
        self.assertEqual(repeated_text, "First sentence. Second sentence.")

        spoken: list[str] = []
        cancel = threading.Event()

        def stop_after_first(sentence: str) -> None:
            spoken.append(sentence)
            cancel.set()

        gta5_agent._accumulate_voice_stream(
            [
                _voice_chunk(_voice_text("First sentence. ")),
                _voice_chunk(
                    _voice_text("hidden plan", thought=True),
                    _voice_call("launch_application", {"app_name": "Excel"}, "1"),
                    _voice_text("Second sentence."),
                ),
            ],
            stop_after_first,
            cancel,
        )
        self.assertEqual(spoken, ["First sentence."])

        thought_only: list[str] = []
        parts, calls, quiet = gta5_agent._accumulate_voice_stream(
            [
                _voice_chunk(_voice_text("planning", thought=True)),
                _voice_chunk(_voice_call("click_element", {"x": 1}, "a")),
                _voice_chunk(_voice_call("click_element", {"x": 1, "y": 2}, "a")),
                _voice_chunk(_voice_text("Done.")),
            ],
            thought_only.append,
            None,
        )
        self.assertEqual(thought_only, ["Done."])
        self.assertEqual(quiet, "Done.")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].args["y"], 2)
        self.assertTrue(any(getattr(part, "thought", False) for part in parts))

    def test_playback_starts_while_the_next_sentence_is_synthesized(self) -> None:
        playing = threading.Event()
        order: list[str] = []

        def synthesize(text: str, destination: Path, voice: str) -> None:
            if text.startswith("Second"):
                self.assertTrue(playing.wait(2))
                order.append("synth-second")
            else:
                order.append("synth-first")
            destination.write_bytes(b"mp3")

        def play(path: Path) -> None:
            self.assertEqual(path.read_bytes(), b"mp3")
            order.append("play")
            playing.set()

        pipeline = gta5_agent._SpeechPipeline(synthesizer=synthesize, player=play)
        self.addCleanup(pipeline.abort)
        pipeline.submit("First sentence.")
        pipeline.submit("Second sentence.")
        result = pipeline.finish()
        self.assertTrue(result["ok"], result)
        self.assertEqual(order[0], "synth-first")
        self.assertLess(order.index("play"), order.index("synth-second"))
        self.assertFalse(pipeline.cancel.is_set())

    def test_voice_config_is_capped_and_text_config_is_not(self) -> None:
        voiced, plain = gta5_agent._model_configs(True)
        typed, extra = gta5_agent._model_configs(False)
        self.assertEqual(voiced.max_output_tokens, gta5_agent.VOICE_MAX_OUTPUT_TOKENS)
        self.assertIn("MINIMAL", str(voiced.thinking_config.thinking_level))
        self.assertIsNone(plain.thinking_config)
        self.assertEqual(plain.max_output_tokens, gta5_agent.VOICE_MAX_OUTPUT_TOKENS)
        self.assertIsNone(typed.max_output_tokens)
        self.assertIsNone(extra)
        self.assertIn("short spoken sentences", voiced.system_instruction)
        self.assertNotIn("short spoken sentences", typed.system_instruction)
        self.assertTrue(
            gta5_agent._thinking_rejected(
                RuntimeError("400 invalid argument: thinking_level is not supported")
            )
        )
        self.assertFalse(
            gta5_agent._thinking_rejected(ConnectionError("connection reset"))
        )

    def _restore_env(self, name: str, previous: str | None) -> None:
        if previous is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = previous

    def test_voice_transcript_uses_the_same_agent_path(self) -> None:
        code, prompts, spoken = self.run_chat(
            [],
            ["v", "exit"],
            [
                {"ok": True, "text": "Open Excel"},
                {"ok": True, "text": "text mode"},
            ],
        )
        self.assertEqual(code, 0)
        self.assertEqual(prompts, ["Open Excel"])
        self.assertEqual(spoken, ["did:Open Excel"])

        code, prompts, spoken = self.run_chat(
            ["--voice"],
            [],
            [
                {"ok": False, "error": "Could not understand that. Try again."},
                {"ok": True, "text": "Open Excel"},
                {"ok": True, "text": "exit"},
            ],
        )
        self.assertEqual(code, 0)
        self.assertEqual(prompts, ["Open Excel"])
        self.assertEqual(spoken, ["did:Open Excel"])

        code, prompts, spoken = self.run_chat(
            ["--voice"],
            ["exit"],
            [{"ok": False, "error": "No microphone is available: missing"}],
        )
        self.assertEqual(code, 0)
        self.assertEqual(prompts, [])
        self.assertEqual(spoken, [])

        code, prompts, spoken = self.run_chat([], ["Open Excel", "exit"], [])
        self.assertEqual(prompts, ["Open Excel"])
        self.assertEqual(spoken, [])

    def test_barge_in_stops_playback_and_becomes_the_next_turn(self) -> None:
        meter = gta5_agent._BargeMeter()
        quiet = _pcm_frame(100)
        loud = _pcm_frame(4000)
        for _ in range(gta5_agent.BARGE_WARMUP_FRAMES):
            self.assertEqual(meter.push(quiet), "continue")
        saw_speech = False
        for _ in range(gta5_agent.BARGE_HOT_FRAMES + 2):
            if meter.push(loud) == "speech":
                saw_speech = True
                break
        self.assertTrue(saw_speech)
        echo = gta5_agent._BargeMeter()
        speaker = _pcm_frame(2000)
        for _ in range(gta5_agent.BARGE_WARMUP_FRAMES):
            self.assertEqual(echo.push(speaker), "continue")
        self.assertEqual(echo.push(_pcm_frame(2600)), "continue")
        self.assertFalse(echo.speaking)
        self.assertEqual(echo.push(loud), "speech")

        frames = (
            [quiet] * gta5_agent.BARGE_WARMUP_FRAMES
            + [loud] * (gta5_agent.BARGE_HOT_FRAMES + 3)
            + [quiet] * (gta5_agent.BARGE_TRAILING_FRAMES + 2)
        )
        stopped = threading.Event()

        def player(stop_event: threading.Event) -> None:
            self.assertTrue(stop_event.wait(2))
            stopped.set()

        def transcriber(pcm: bytes) -> dict[str, object]:
            self.assertGreater(len(pcm), 0)
            return {"ok": True, "text": "Stop"}

        result = asyncio.run(
            gta5_agent._barge_during_playback(
                self.root / "reply.mp3",
                frames=iter(frames),
                player=player,
                transcriber=transcriber,
            )
        )
        self.assertTrue(stopped.is_set())
        self.assertTrue(result.get("interrupted"))
        self.assertEqual(result.get("transcript"), "Stop")
        follow = gta5_agent._barge_followup(result)
        self.assertEqual(follow, {"ok": True, "text": "Stop"})
        self.assertEqual(
            gta5_agent._barge_followup(
                {"interrupted": True, "transcript": "text mode"}
            ),
            {"ok": True, "command": "text"},
        )
        self.assertIsNone(gta5_agent._barge_followup({"ok": True, "text": "Hi"}))

        prompts: list[str] = []
        spoken: list[str] = []
        listens = [
            {"ok": True, "text": "Open Excel"},
            {"ok": True, "command": "exit"},
        ]
        replies = [
            {
                "ok": True,
                "text": "did:Open Excel",
                "interrupted": True,
                "transcript": "Stop",
            },
            {"ok": True, "text": "did:Stop"},
        ]

        def fake_turn() -> dict[str, object]:
            return listens.pop(0)

        def fake_run(text: str, history: list[object], model: str, **kwargs: object) -> str:
            prompts.append(text)
            return f"did:{text}"

        def fake_speak(text: str, **kwargs: object) -> dict[str, object]:
            spoken.append(text)
            return replies.pop(0)

        with (
            mock.patch.object(gta5_agent, "_watch_mode_keys", lambda pressed, stop: None),
            mock.patch.object(gta5_agent, "_voice_turn", side_effect=fake_turn),
            mock.patch.object(gta5_agent, "run_agent", side_effect=fake_run),
            mock.patch.object(gta5_agent, "speak_response", side_effect=fake_speak),
        ):
            outcome = asyncio.run(
                gta5_agent._voice_session([], "gemini-3.5-flash-lite")
            )
        self.assertEqual(outcome, "exit")
        self.assertEqual(prompts, ["Open Excel", "Stop"])
        self.assertEqual(spoken, ["did:Open Excel", "did:Stop"])
        self.assertEqual(listens, [])

    def test_webcam_capture_is_one_frame_and_closes_the_camera(self) -> None:
        names = [item["name"] for item in gta5_agent.TOOL_DECLARATIONS]
        self.assertIn("capture_webcam_image", gta5_agent.TOOLS)
        self.assertIn("capture_webcam_image", names)
        description = next(
            item["description"]
            for item in gta5_agent.TOOL_DECLARATIONS
            if item["name"] == "capture_webcam_image"
        )
        self.assertIn("one frame", description.casefold())
        self.assertIn("close", description.casefold())

        with self.assertRaises(AssertionError):
            gta5_agent.capture_webcam_image()

        buffer = io.BytesIO()
        from PIL import Image

        Image.new("RGB", (32, 16), (8, 16, 32)).save(buffer, format="PNG")
        png = buffer.getvalue()
        calls = {"n": 0}

        def injected() -> dict[str, object]:
            calls["n"] += 1
            return {"png": png}

        gta5_agent.webcam_override = injected
        real_import = builtins.__import__

        def block_cv2(
            name: str,
            globals: object = None,
            locals: object = None,
            fromlist: tuple[str, ...] = (),
            level: int = 0,
        ) -> object:
            if name.split(".", 1)[0] == "cv2":
                raise AssertionError("real webcam")
            return real_import(name, globals, locals, fromlist, level)

        with mock.patch("builtins.__import__", block_cv2):
            shot = gta5_agent.capture_webcam_image()
        self.assertTrue(shot["ok"], shot)
        self.assertEqual(calls["n"], 1)
        self.assertEqual(shot["image_width"], 32)
        self.assertEqual(shot["image_height"], 16)
        self.assertTrue(shot["_screenshot_bytes"].startswith(b"\xff\xd8"))
        self.assertEqual(shot["_screenshot_mime"], "image/jpeg")
        saved = Path(shot["path"])
        self.assertEqual(saved.name, "vision_capture.jpg")
        self.assertEqual(saved.parent, gta5_agent.WORKSPACE)
        self.assertEqual(saved.read_bytes(), shot["_screenshot_bytes"])
        part = gta5_agent._function_response("capture_webcam_image", shot, "cam-1")
        response = part.function_response
        self.assertNotIn("_screenshot_bytes", response.response)
        self.assertEqual(response.parts[0].inline_data.mime_type, "image/jpeg")
        self.assertEqual(bytes(response.parts[0].inline_data.data), shot["_screenshot_bytes"])

        def empty() -> dict[str, object]:
            return {}

        gta5_agent.webcam_override = empty
        missing = gta5_agent.capture_webcam_image()
        self.assertFalse(missing["ok"])
        self.assertIn("no image", missing["error"].casefold())

        import numpy as np

        opened: list[FakeCapture] = []

        class FakeCapture:
            def __init__(self, opened_ok: bool = True, hang: bool = False) -> None:
                self.opened_ok = opened_ok
                self.hang = hang
                self.reads = 0
                self.released = False
                self.was_opened = False
                self.opened_with: tuple[object, ...] | None = None
                self.props: dict[object, object] = {}
                self.release_gate = threading.Event()

            def set(self, prop: object, value: object) -> bool:
                self.props[prop] = value
                return True

            def open(self, index: int, backend: int = 0) -> bool:
                self.opened_with = (index, backend)
                self.was_opened = True
                return self.opened_ok

            def isOpened(self) -> bool:
                return self.opened_ok and self.was_opened

            def read(self) -> tuple[bool, object]:
                self.reads += 1
                if self.hang:
                    self.release_gate.wait(5)
                    return False, None
                frame = np.zeros((4, 6, 3), dtype=np.uint8)
                frame[:, :, 0] = 20
                return True, frame

            def release(self) -> None:
                self.released = True

        fake = types.ModuleType("cv2")
        fake.CAP_DSHOW = 700
        fake.CAP_ANY = 0
        fake.CAP_PROP_BUFFERSIZE = 38
        fake.CAP_PROP_OPEN_TIMEOUT_MSEC = 53
        fake.CAP_PROP_READ_TIMEOUT_MSEC = 54

        def video_capture(*args: object) -> FakeCapture:
            camera = FakeCapture()
            opened.append(camera)
            return camera

        def imwrite(path: str, frame: object) -> bool:
            self.assertEqual(tuple(np.asarray(frame).shape), (4, 6, 3))
            Path(path).write_bytes(b"\xff\xd8\xff\xd9")
            return True

        fake.VideoCapture = video_capture
        fake.imwrite = imwrite
        gta5_agent.webcam_override = None
        with mock.patch.dict(sys.modules, {"cv2": fake}):
            live = gta5_agent.capture_webcam_image()
        self.assertTrue(live["ok"], live)
        self.assertEqual(len(opened), 1)
        camera = opened[0]
        self.assertTrue(camera.released)
        self.assertEqual(camera.reads, 1)
        expected_backend = fake.CAP_DSHOW if sys.platform == "win32" else fake.CAP_ANY
        self.assertEqual(camera.opened_with, (0, expected_backend))
        self.assertEqual(
            list(camera.props),
            [
                fake.CAP_PROP_OPEN_TIMEOUT_MSEC,
                fake.CAP_PROP_READ_TIMEOUT_MSEC,
                fake.CAP_PROP_BUFFERSIZE,
            ],
        )
        self.assertEqual(camera.props[fake.CAP_PROP_OPEN_TIMEOUT_MSEC], 4000)
        self.assertEqual(live["image_width"], 6)
        self.assertEqual(live["image_height"], 4)
        self.assertEqual((gta5_agent.WORKSPACE / "vision_capture.jpg").read_bytes(), b"\xff\xd8\xff\xd9")

        failed_open: list[FakeCapture] = []

        def closed_capture(*args: object) -> FakeCapture:
            camera = FakeCapture(opened_ok=False)
            failed_open.append(camera)
            return camera

        fake.VideoCapture = closed_capture
        gta5_agent.webcam_override = None
        with mock.patch.dict(sys.modules, {"cv2": fake}):
            unavailable = gta5_agent.capture_webcam_image()
        self.assertFalse(unavailable["ok"])
        self.assertIn("privacy", unavailable["error"].casefold())
        self.assertEqual(len(failed_open), 1)
        self.assertTrue(failed_open[0].released)
        self.assertEqual(failed_open[0].reads, 0)

        hung_gate = threading.Event()

        class HungCapture(FakeCapture):
            def read(self) -> tuple[bool, object]:
                self.reads += 1
                hung_gate.wait(5)
                return False, None

        hung_cameras: list[HungCapture] = []

        def hung_capture(*args: object) -> HungCapture:
            camera = HungCapture()
            hung_cameras.append(camera)
            return camera

        fake.VideoCapture = hung_capture
        gta5_agent.webcam_override = None
        previous_timeout = gta5_agent.WEBCAM_TIMEOUT_SECONDS
        gta5_agent.WEBCAM_TIMEOUT_SECONDS = 0.25
        self.addCleanup(setattr, gta5_agent, "WEBCAM_TIMEOUT_SECONDS", previous_timeout)
        self.addCleanup(hung_gate.set)
        started = gta5_agent.time.perf_counter()
        with mock.patch.dict(sys.modules, {"cv2": fake}):
            timed_out = gta5_agent.capture_webcam_image()
        elapsed = gta5_agent.time.perf_counter() - started
        self.assertFalse(timed_out["ok"])
        self.assertIn("did not respond", timed_out["error"].casefold())
        self.assertLess(elapsed, 2.0)
        self.assertEqual(len(hung_cameras), 1)
        self.assertEqual(hung_cameras[0].reads, 1)

    def test_memory_persists_and_is_added_to_the_prompt(self) -> None:
        names = [item["name"] for item in gta5_agent.TOOL_DECLARATIONS]
        self.assertIn("remember_fact", gta5_agent.TOOLS)
        self.assertIn("recall_memory", gta5_agent.TOOLS)
        self.assertIn("remember_fact", names)
        self.assertIn("recall_memory", names)

        saved = gta5_agent.remember_fact("The user likes quiet installs.", "preference")
        self.assertTrue(saved["ok"])
        again = gta5_agent.remember_fact("The user likes quiet installs.", "preference")
        self.assertIn("already saved", again["message"])
        recalled = gta5_agent.recall_memory("quiet installs")
        self.assertEqual(len(recalled["matches"]), 1)
        self.assertEqual(recalled["matches"][0]["topic"], "preference")
        self.assertTrue((gta5_agent.WORKSPACE / "memory.sqlite").is_file())

        blocked = gta5_agent.remember_fact("password=hunter2")
        self.assertFalse(blocked["ok"])
        self.assertEqual(gta5_agent.recall_memory("hunter2")["matches"], [])
        self.assertFalse(
            gta5_agent.remember_fact("hello", "secret")["ok"]
        )

        gta5_agent._capture_user_memory(
            "My name is Pedro. Remember that AddonPeds is the layout."
        )
        self.assertTrue(
            any("Pedro" in item["fact"] for item in gta5_agent.recall_memory("Pedro")["matches"])
        )
        self.assertEqual(
            gta5_agent.recall_memory("AddonPeds")["matches"][0]["topic"],
            "instruction",
        )

        gta5_agent._autosave_tool_memory(
            "locate_gta5_directory",
            {
                "ok": True,
                "game_root": "E:/Games/GTA",
                "volume_label": "GameDrive",
                "drive": "E:",
            },
        )
        located = gta5_agent.recall_memory("Games GTA")
        self.assertIn("GameDrive", located["matches"][0]["fact"])
        self.assertEqual(located["matches"][0]["topic"], "path")

        prompt = gta5_agent.system_prompt()
        self.assertIn("Known facts saved on this computer", prompt)
        self.assertIn("quiet installs", prompt)
        self.assertIn("Pedro", prompt)
        self.assertIn("E:/Games/GTA", prompt)

    def test_computer_actions_stay_off_the_real_desktop(self) -> None:
        names = [item["name"] for item in gta5_agent.TOOL_DECLARATIONS]
        for name in (
            "take_screenshot",
            "capture_webcam_image",
            "perform_actions",
            "click_element",
            "press_keys",
            "type_text",
            "scroll",
            "navigate_browser",
        ):
            self.assertIn(name, gta5_agent.TOOLS)
            self.assertIn(name, names)
        self.assertNotIn("computer_action", names)
        self.assertIn("0-1000", gta5_agent.SYSTEM_PROMPT)
        self.assertIn("capture_webcam_image", gta5_agent.SYSTEM_PROMPT)
        self.assertIn("one frame", gta5_agent.SYSTEM_PROMPT)

        import mouse_controller
        from PIL import Image

        mouse_controller.enable_windows_dpi_awareness()
        self.assertEqual(mouse_controller.norm_to_pixel(0, 0, 1920, 1080), (0, 0))
        self.assertEqual(mouse_controller.norm_to_pixel(500, 250, 2000, 1000), (1000, 250))
        self.assertEqual(
            mouse_controller.norm_to_pixel(1000, 1000, 1920, 1080),
            (1919, 1079),
        )
        wide_image = Image.new("RGB", (200, 100), (1, 2, 3))
        self.assertEqual(mouse_controller.align_to_screen(wide_image, 100, 50).size, (100, 50))

        class FakePointer:
            def __init__(self) -> None:
                self.calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
                self.FAILSAFE = False
                self.PAUSE = 1.0

            def click(self, *args: object, **kwargs: object) -> None:
                self.calls.append((args, kwargs))

        fake_pointer = FakePointer()
        mouse_controller.configure_desktop(fake_pointer)
        self.assertEqual(fake_pointer.PAUSE, 0)
        self.assertTrue(fake_pointer.FAILSAFE)
        mouse_controller.instant_click(fake_pointer, 10, 20, 1, "left")
        self.assertEqual(fake_pointer.calls, [((10, 20), {"clicks": 1, "button": "left"})])
        self.assertNotIn("duration", fake_pointer.calls[0][1])

        buffer = io.BytesIO()
        Image.new("RGB", (2000, 1000), (12, 24, 36)).save(buffer, format="PNG")
        wide = buffer.getvalue()
        actions: list[tuple[str, dict[str, object]]] = []
        opened: list[str] = []
        imports: list[str] = []
        real_import = builtins.__import__

        def blocking_import(
            name: str,
            globals: object = None,
            locals: object = None,
            fromlist: tuple[str, ...] = (),
            level: int = 0,
        ) -> object:
            root = name.split(".", 1)[0]
            if root in {"pyautogui", "pynput", "mss"}:
                imports.append(name)
                raise AssertionError(name)
            return real_import(name, globals, locals, fromlist, level)

        def capture() -> dict[str, object]:
            return {"png": wide, "screen_width": 2000, "screen_height": 1000}

        def record(kind: str, details: dict[str, object]) -> None:
            actions.append((kind, details))

        gta5_agent.screenshot_override = capture
        gta5_agent.screen_size_override = (2000, 1000)
        gta5_agent.pointer_override = record
        gta5_agent.navigate_override = opened.append

        with mock.patch("builtins.__import__", blocking_import):
            shot = gta5_agent.take_screenshot()
            self.assertTrue(shot["ok"], shot)
            self.assertEqual(shot["screen_width"], 2000)
            self.assertEqual(shot["image_width"], 1280)
            self.assertEqual(shot["image_height"], 640)
            self.assertEqual(shot["scale"], 0.64)
            self.assertEqual(shot["grid"], 1000)
            self.assertIn("0-1000", shot["message"])
            self.assertTrue(shot["_screenshot_bytes"].startswith(b"\xff\xd8"))
            self.assertEqual(shot["_screenshot_mime"], "image/jpeg")
            self.assertTrue(str(shot["path"]).endswith(".jpg"))
            saved = Path(shot["path"])
            self.assertTrue(saved.is_file())
            self.assertEqual(saved.read_bytes(), shot["_screenshot_bytes"])

            part = gta5_agent._function_response("take_screenshot", shot, "call-1")
            response = part.function_response
            self.assertNotIn("_screenshot_bytes", response.response)
            self.assertNotIn("_screenshot_mime", response.response)
            json.dumps(response.response)
            self.assertEqual(response.id, "call-1")
            self.assertEqual(response.parts[0].inline_data.mime_type, "image/jpeg")
            self.assertEqual(
                bytes(response.parts[0].inline_data.data),
                shot["_screenshot_bytes"],
            )
            self.assertIn("_screenshot_bytes", shot)

            hit = gta5_agent.click_element(500, 250, button="right", clicks=2)
            self.assertTrue(hit["ok"], hit)
            corner = gta5_agent.click_element(1000, 1000)
            self.assertTrue(corner["ok"], corner)
            self.assertEqual((corner["x"], corner["y"]), (1999, 999))
            miss = gta5_agent.click_element(1001, 0)
            self.assertFalse(miss["ok"])
            bad_button = gta5_agent.click_element(1, 1, button="shift")
            self.assertFalse(bad_button["ok"])

            typed = gta5_agent.type_text("hello")
            self.assertTrue(typed["ok"], typed)
            secret = gta5_agent.type_text("password=hunter2")
            self.assertFalse(secret["ok"])
            controls = gta5_agent.type_text("line\nnext")
            self.assertFalse(controls["ok"])
            accented = gta5_agent.type_text("café")
            self.assertTrue(accented["ok"], accented)

            wheeled = gta5_agent.computer_action("scroll", direction="down", amount=2)
            self.assertTrue(wheeled["ok"], wheeled)
            sideways = gta5_agent.scroll("sideways")
            self.assertFalse(sideways["ok"])
            too_far = gta5_agent.scroll("up", 50)
            self.assertFalse(too_far["ok"])
            keyed = gta5_agent.press_keys("tab, enter")
            self.assertTrue(keyed["ok"], keyed)
            chord = gta5_agent.press_keys("ctrl+l")
            self.assertTrue(chord["ok"], chord)
            blocked_keys = gta5_agent.press_keys("win+r")
            self.assertFalse(blocked_keys["ok"])
            spelled = gta5_agent.press_keys("password")
            self.assertFalse(spelled["ok"])

            page = gta5_agent.navigate_browser("https://example.com/mods")
            self.assertTrue(page["ok"], page)
            script = gta5_agent.navigate_browser("javascript:alert(1)")
            self.assertFalse(script["ok"])
            local_file = gta5_agent.navigate_browser("file:///C:/Windows/notepad.exe")
            self.assertFalse(local_file["ok"])
            locked = gta5_agent.navigate_browser("https://user:pass@example.com")
            self.assertFalse(locked["ok"])
            unknown = gta5_agent.computer_action("format_disk")
            self.assertFalse(unknown["ok"])

            sent: list[int] = []

            def fake_send(count: int, pointer: object, size: int) -> int:
                sent.append(count)
                return count

            gta5_agent.windows_input_override = fake_send
            gta5_agent._type_windows_unicode("é")

        self.assertEqual(imports, [])
        self.assertEqual(
            actions[0],
            (
                "click",
                {
                    "x": 1000,
                    "y": 250,
                    "norm_x": 500,
                    "norm_y": 250,
                    "button": "right",
                    "clicks": 2,
                },
            ),
        )
        self.assertEqual(
            [kind for kind, _ in actions],
            ["click", "click", "type", "type", "scroll", "keys", "keys"],
        )
        self.assertEqual(actions[2][1]["text"], "hello")
        self.assertEqual(actions[3][1]["text"], "café")
        self.assertEqual(actions[4][1], {"direction": "down", "amount": 2})
        self.assertEqual(actions[5][1]["steps"], [["tab"], ["enter"]])
        self.assertEqual(actions[6][1]["steps"], [["ctrl", "l"]])
        self.assertEqual(opened, ["https://example.com/mods"])
        self.assertEqual(sent, [2])

        music = mock.Mock()
        music.get_busy.return_value = True
        mixer = mock.Mock()
        mixer.get_init.return_value = True
        mixer.music = music
        fake_pygame = mock.Mock()
        fake_pygame.mixer = mixer
        cut = threading.Event()
        gta5_agent._arm_playback(cut, use_pygame=True)
        try:
            with mock.patch.dict(sys.modules, {"pygame": fake_pygame}):
                gta5_agent.stop_agent_speech()
            music.stop.assert_called_once()
            music.unload.assert_called_once()
            self.assertTrue(cut.is_set())
        finally:
            gta5_agent._disarm_playback()

        before = len(actions)
        shots = {"n": 0}

        def counting_capture() -> dict[str, object]:
            shots["n"] += 1
            return {"png": wide, "screen_width": 2000, "screen_height": 1000}

        gta5_agent.screenshot_override = counting_capture
        batch = gta5_agent.perform_actions(
            [
                {"action": "click", "x": 500, "y": 250},
                {"action": "type", "text": "hello"},
                {"action": "press", "key": "enter"},
            ]
        )
        self.assertTrue(batch["ok"], batch)
        self.assertEqual(shots["n"], 0)
        self.assertEqual(
            [kind for kind, _ in actions[before:]],
            ["click", "type", "keys"],
        )
        self.assertEqual(actions[before + 2][1]["steps"], [["enter"]])
        self.assertNotIn("_screenshot_bytes", batch)
        stopped = gta5_agent.perform_actions(
            [
                {"action": "type", "text": "password=hunter2"},
                {"action": "click", "x": 10, "y": 10},
            ]
        )
        self.assertFalse(stopped["ok"])
        self.assertEqual(len(actions), before + 3)
        too_many = gta5_agent.perform_actions(
            [{"action": "press", "key": "tab"}] * 13
        )
        self.assertFalse(too_many["ok"])
        self.assertEqual(len(actions), before + 3)
        seen = gta5_agent.perform_actions(
            [
                {"action": "click", "x": 0, "y": 0},
                {"action": "screenshot"},
            ]
        )
        self.assertTrue(seen["ok"], seen)
        self.assertEqual(shots["n"], 1)
        self.assertTrue(seen["_screenshot_bytes"].startswith(b"\xff\xd8"))

    def test_mode_key_overrides_a_transcript(self) -> None:
        def watch(pressed: dict[str, str | None], stop: object) -> None:
            pressed["key"] = "text"

        with mock.patch.object(gta5_agent, "_watch_mode_keys", watch):
            with mock.patch.object(
                gta5_agent,
                "listen_to_microphone",
                return_value={"ok": True, "text": "Open Excel"},
            ):
                heard = gta5_agent._voice_turn()
        self.assertEqual(heard.get("command"), "text")

    def test_clipboard_text_stays_out_of_memory(self) -> None:
        names = [item["name"] for item in gta5_agent.TOOL_DECLARATIONS]
        for name in (
            "get_clipboard_text",
            "create_task_plan",
            "complete_plan_step",
            "revise_task_plan",
        ):
            self.assertIn(name, gta5_agent.TOOLS)
            self.assertIn(name, names)
        self.assertNotIn("computer_action", names)
        self.assertIn("get_clipboard_text", gta5_agent.SYSTEM_PROMPT)
        self.assertIn("create_task_plan", gta5_agent.SYSTEM_PROMPT)

        with self.assertRaises(AssertionError) as raised:
            gta5_agent.get_clipboard_text()
        self.assertIn("real clipboard", str(raised.exception))

        real_import = builtins.__import__

        def blocked(
            name: str,
            globals: dict[str, object] | None = None,
            locals: dict[str, object] | None = None,
            fromlist: tuple[str, ...] = (),
            level: int = 0,
        ) -> object:
            if name == "pyperclip" or name.startswith("pyperclip."):
                raise AssertionError("pyperclip imported")
            return real_import(name, globals, locals, fromlist, level)

        gta5_agent.clipboard_override = lambda: "def fix():\n    return 1\n"
        with mock.patch("builtins.__import__", blocked):
            read = gta5_agent.get_clipboard_text()
        self.assertTrue(read["ok"])
        self.assertIn("def fix", read["text"])
        self.assertIn("characters", read["message"])
        self.assertNotIn("def fix", read["message"])
        wired = gta5_agent.invoke_tool("get_clipboard_text", {})
        self.assertEqual(wired["text"], read["text"])

        gta5_agent.clipboard_override = lambda: " \n\t"
        empty = gta5_agent.get_clipboard_text()
        self.assertFalse(empty["ok"])
        self.assertIn("empty", empty["error"].casefold())

        gta5_agent.clipboard_override = lambda: None
        blank = gta5_agent.get_clipboard_text()
        self.assertFalse(blank["ok"])

        long_text = "x" * (gta5_agent.CLIPBOARD_TEXT_LIMIT + 40)
        gta5_agent.clipboard_override = lambda: long_text
        clipped = gta5_agent.get_clipboard_text()
        self.assertTrue(clipped["truncated"])
        self.assertEqual(len(clipped["text"]), gta5_agent.CLIPBOARD_TEXT_LIMIT)
        self.assertIn("truncated", clipped["message"].casefold())

        saved = os.environ.get("GEMINI_API_KEY")
        os.environ["GEMINI_API_KEY"] = "test-key-abc"
        try:
            gta5_agent.clipboard_override = lambda: "token test-key-abc end"
            scrubbed = gta5_agent.get_clipboard_text()
        finally:
            if saved is None:
                os.environ.pop("GEMINI_API_KEY", None)
            else:
                os.environ["GEMINI_API_KEY"] = saved
        self.assertNotIn("test-key-abc", scrubbed["text"])
        self.assertNotIn("test-key-abc", scrubbed["message"])
        self.assertIn("[redacted]", scrubbed["text"])

        snippet = "clipboard-only-snippet-zz9"
        gta5_agent.clipboard_override = lambda: snippet
        self.assertTrue(gta5_agent.get_clipboard_text()["ok"])
        listed = gta5_agent.recall_memory("")
        self.assertNotIn(snippet, json.dumps(listed.get("matches", [])))

    def test_multi_step_plan_gates_execution(self) -> None:
        import inspect

        source = inspect.getsource(gta5_agent.run_agent)
        self.assertLess(
            source.find("begin_task_turn(user_text)"),
            source.find("from google import genai"),
        )
        complex_request = (
            "Organize my GameDrive drive, pull sales data from SQL, "
            "and update my tracking sheet"
        )
        self.assertTrue(gta5_agent._request_needs_plan(complex_request))
        self.assertFalse(gta5_agent._request_needs_plan("Open Excel"))
        self.assertFalse(
            gta5_agent._request_needs_plan("Open Excel and create a sales report")
        )
        self.assertFalse(
            gta5_agent._request_needs_plan("Open YouTube and search for GTA 5 mods")
        )
        self.assertFalse(
            gta5_agent._request_needs_plan("Find Simple Zombies Reborn and install it")
        )
        self.assertFalse(
            gta5_agent._request_needs_plan(
                "Fix the code I just copied and analyze this error log"
            )
        )
        self.assertTrue(
            gta5_agent._request_needs_plan("Install the mod and copy it into scripts")
        )

        gta5_agent.begin_task_turn(complex_request)
        blocked = gta5_agent.invoke_tool("click_element", {"x": 1, "y": 1})
        self.assertFalse(blocked["ok"])
        self.assertIn("create_task_plan", blocked["error"])
        self.assertNotIn("real pointer", blocked["error"])

        gta5_agent.clipboard_override = lambda: "NameError: missing name"
        copied = gta5_agent.invoke_tool("get_clipboard_text", {})
        self.assertTrue(copied["ok"])
        self.assertIn("NameError", copied["text"])

        seen: list[str] = []

        def record(kind: str, details: dict[str, object]) -> None:
            seen.append(kind)

        with mock.patch("builtins.print") as printed:
            plan = gta5_agent.create_task_plan(
                "Organize and report",
                [
                    "Group the GameDrive folders",
                    "Query the sales database",
                    "Update the tracking sheet",
                ],
            )
            self.assertTrue(plan["ok"])
            self.assertEqual(len(plan["steps"]), 3)
            gta5_agent.pointer_override = record
            clicked = gta5_agent.invoke_tool("click_element", {"x": 1, "y": 1})
            done = gta5_agent.complete_plan_step(1, "Folders are grouped")
            revised = gta5_agent.revise_task_plan(
                2,
                "The database file is missing",
                ["Ask for the database path", "Update the sheet"],
            )
        self.assertTrue(clicked["ok"], clicked)
        self.assertEqual(seen, ["click"])
        self.assertEqual(done["steps"][0]["status"], "done")
        self.assertIn("Next is step 2", done["message"])
        self.assertEqual(
            [step["status"] for step in revised["steps"]],
            ["done", "blocked", "pending", "pending"],
        )
        self.assertIn("database file is missing", revised["message"])
        logged = "\n".join(
            str(call.args[0]) for call in printed.call_args_list if call.args
        )
        self.assertIn("[plan] plan:", logged)
        self.assertIn("[ ]", logged)
        self.assertIn("[plan] done 1.", logged)
        self.assertIn("[plan] pivot at 2: The database file is missing", logged)
        self.assertIn("[!]", logged)

        gta5_agent.pointer_override = _guard_pointer
        gta5_agent.begin_task_turn(complex_request)
        blocked_again = gta5_agent.invoke_tool("click_element", {"x": 1, "y": 1})
        self.assertFalse(blocked_again["ok"])
        self.assertIn("create_task_plan", blocked_again["error"])
        self.assertNotIn("real pointer", blocked_again["error"])

        kept = gta5_agent.create_task_plan(
            "Two jobs",
            '["1. Read the log", {"task": "Fix the file"}]',
        )
        self.assertTrue(kept["ok"])
        self.assertEqual(kept["steps"][0]["text"], "Read the log")
        self.assertEqual(kept["steps"][1]["text"], "Fix the file")
        rejected = gta5_agent.create_task_plan("Only one", ["Just open Excel"])
        self.assertFalse(rejected["ok"])
        self.assertEqual(gta5_agent._task_plan["goal"], "Two jobs")

        gta5_agent.begin_task_turn("Open Excel")
        gta5_agent.pointer_override = record
        opened = gta5_agent.invoke_tool("click_element", {"x": 2, "y": 2})
        self.assertTrue(opened["ok"], opened)
        self.assertEqual(seen, ["click", "click"])

        gta5_agent.begin_task_turn("Fix the code I just copied")
        free = gta5_agent.invoke_tool("click_element", {"x": 3, "y": 3})
        self.assertTrue(free["ok"], free)

    def test_pedro_search_finds_notes_and_old_backups(self) -> None:
        names = [item["name"] for item in gta5_agent.TOOL_DECLARATIONS]
        for name in (
            "search_local_files",
            "kill_process",
            "focus_window",
            "manage_window_layout",
            "manage_windows_and_processes",
            "schedule_background_task",
            "run_blender_task",
            "blender_job_status",
            "build_local_program",
        ):
            self.assertIn(name, gta5_agent.TOOLS)
            self.assertIn(name, names)
        self.assertNotIn("computer_action", names)
        self.assertNotIn("wake_word_listener", names)
        self.assertIn("search_local_files", gta5_agent.SYSTEM_PROMPT)
        self.assertIn("hey agent", gta5_agent.SYSTEM_PROMPT)

        root = gta5_agent.search_root_override
        assert root is not None
        notes = root / "notes"
        mods = root / "mods"
        notes.mkdir()
        mods.mkdir()
        (notes / "project-notes.md").write_text(
            "database design for the shop schema",
            encoding="utf-8",
        )
        old_backup = mods / "zombie-mod-backup.txt"
        old_backup.write_text("zombie mod backup copy", encoding="utf-8")
        fresh = mods / "zombie-mod-backup-today.txt"
        fresh.write_text("zombie mod backup copy", encoding="utf-8")
        now = time.time()
        os.utime(old_backup, (now - 30 * 86400, now - 30 * 86400))
        os.utime(fresh, (now - 86400, now - 86400))
        (root / "launch-me.exe").write_bytes(b"MZ")
        saved = os.environ.get("GEMINI_API_KEY")
        os.environ["GEMINI_API_KEY"] = "test-key-abc"
        try:
            (notes / "secret-note.txt").write_text(
                "database design test-key-abc",
                encoding="utf-8",
            )
            found = gta5_agent.invoke_tool(
                "search_local_files",
                {"query": "Where did I save that zombie mod backup from last month?"},
            )
            notes_found = gta5_agent.local_search.search_local_files(
                "Find my project notes about database design"
            )
        finally:
            if saved is None:
                os.environ.pop("GEMINI_API_KEY", None)
            else:
                os.environ["GEMINI_API_KEY"] = saved
        self.assertTrue(found["ok"], found)
        self.assertIn("zombie-mod-backup.txt", found["matches"][0]["name"])
        self.assertNotEqual(found["matches"][0]["name"], "zombie-mod-backup-today.txt")
        self.assertTrue(notes_found["ok"], notes_found)
        blob = json.dumps(notes_found["matches"])
        self.assertIn("project-notes.md", blob)
        self.assertNotIn("test-key-abc", blob)
        self.assertIn("[redacted]", blob)
        self.assertTrue((root / "launch-me.exe").is_file())

    def test_windows_scheduler_and_wake_word_stay_local(self) -> None:
        with self.assertRaises(AssertionError) as raised:
            gta5_agent.window_control.kill_process("notepad")
        self.assertIn("real process", str(raised.exception))

        killed: list[dict[str, object]] = []

        def processes(kind: str, payload: dict[str, object] | None = None) -> list[object]:
            if kind == "list":
                return [
                    {"pid": 10, "name": "notepad.exe"},
                    {"pid": os.getpid(), "name": "python.exe"},
                    {"pid": 4, "name": "lsass.exe"},
                    {"pid": 20, "name": "svchost.exe"},
                ]
            killed.append(dict(payload or {}))
            return []

        windows: list[dict[str, object]] = []

        def windows_seen(kind: str, payload: dict[str, object] | None = None) -> None:
            windows.append({"kind": kind, **(payload or {})})

        real_import = builtins.__import__

        def blocked(
            name: str,
            globals: dict[str, object] | None = None,
            locals: dict[str, object] | None = None,
            fromlist: tuple[str, ...] = (),
            level: int = 0,
        ) -> object:
            if name in {"psutil", "pygetwindow", "pvporcupine"} or name.startswith(
                ("psutil.", "pygetwindow.", "pvporcupine.")
            ):
                raise AssertionError(f"{name} imported")
            return real_import(name, globals, locals, fromlist, level)

        gta5_agent.process_override = processes
        gta5_agent.window_override = windows_seen
        with mock.patch("builtins.__import__", blocked):
            closed = gta5_agent.window_control.kill_process("notepad")
            denied = gta5_agent.window_control.kill_process("lsass")
            own = gta5_agent.window_control.kill_process("python")
            service = gta5_agent.window_control.kill_process("svchost")
            focused = gta5_agent.window_control.focus_window("Excel")
            snapped = gta5_agent.window_control.manage_window_layout(
                "snap_left",
                "Excel",
            )
            routed = gta5_agent.invoke_tool(
                "manage_windows_and_processes",
                {"action": "minimize", "target": "Excel"},
            )
        self.assertTrue(closed["ok"], closed)
        self.assertEqual(killed, [{"pid": 10, "name": "notepad.exe"}])
        self.assertFalse(denied["ok"])
        self.assertIn("system process", denied["error"])
        self.assertFalse(own["ok"])
        self.assertFalse(service["ok"])
        self.assertEqual(len(killed), 1)
        self.assertTrue(focused["ok"], focused)
        self.assertEqual(windows[0]["kind"], "focus")
        self.assertTrue(snapped["ok"], snapped)
        self.assertEqual(snapped["rect"], (0, 0, 960, 1080))
        self.assertTrue(routed["ok"], routed)
        self.assertEqual(windows[-1]["action"], "minimize")

        folder = self.root / "Downloads"
        folder.mkdir()
        (folder / "notes.txt").write_text("hello", encoding="utf-8")
        (folder / "photo.png").write_bytes(b"png")
        (folder / "tool.exe").write_bytes(b"MZ")
        gta5_agent.downloads_override = folder
        clock = {"now": 1_000_000.0}
        gta5_agent.scheduler_clock = lambda: clock["now"]
        refused = gta5_agent.task_schedule.schedule_background_task(
            "cleanup.bat",
            delay_minutes=30,
        )
        self.assertFalse(refused["ok"])
        self.assertIn("scripts", refused["error"])
        planned = gta5_agent.invoke_tool(
            "schedule_background_task",
            {"task": "organize_downloads", "delay_minutes": 30},
        )
        self.assertTrue(planned["ok"], planned)
        self.assertIn("minute", planned["rule"])
        self.assertEqual(gta5_agent.task_schedule.run_due_tasks(), [])
        clock["now"] += 30 * 60
        ran = gta5_agent.task_schedule.run_due_tasks()
        self.assertTrue(ran[0]["ok"], ran)
        self.assertTrue((folder / "Documents" / "notes.txt").is_file())
        self.assertTrue((folder / "Pictures" / "photo.png").is_file())
        self.assertTrue((folder / "tool.exe").is_file())
        self.assertFalse((folder / "notes.txt").exists())
        reminded = gta5_agent.task_schedule.schedule_background_task(
            "remind",
            delay_minutes=1,
            message="stand up",
        )
        self.assertTrue(reminded["ok"], reminded)
        clock["now"] += 60
        with mock.patch("builtins.print") as printed:
            gta5_agent.task_schedule.run_due_tasks()
        logged = "\n".join(str(call.args[0]) for call in printed.call_args_list if call.args)
        self.assertIn("[schedule] reminder: stand up", logged)

        phrases = iter(["not now", "hey agent", "hey agent open notepad"])
        commands = {"n": 0}
        chimes = {"n": 0}

        def wake_audio() -> dict[str, object]:
            return {"ok": True, "text": next(phrases)}

        def command_audio() -> dict[str, object]:
            commands["n"] += 1
            return {"ok": True, "text": "Open Excel"}

        gta5_agent.wake_listen_override = wake_audio
        gta5_agent.command_listen_override = command_audio
        gta5_agent.chime_override = lambda: chimes.__setitem__("n", chimes["n"] + 1)

        def blocked_audio(
            name: str,
            globals: dict[str, object] | None = None,
            locals: dict[str, object] | None = None,
            fromlist: tuple[str, ...] = (),
            level: int = 0,
        ) -> object:
            if name in {"speech_recognition", "pyaudio", "pvporcupine"} or name.startswith(
                ("speech_recognition.", "pyaudio.", "pvporcupine.")
            ):
                raise AssertionError(f"{name} imported")
            return real_import(name, globals, locals, fromlist, level)

        with mock.patch("builtins.__import__", blocked_audio):
            missed = gta5_agent.wake_word.wake_word_listener(cycles=1)
            heard = gta5_agent.wake_word.wake_word_listener(cycles=1)
            inline = gta5_agent.wake_word.wake_word_listener(cycles=1)
        self.assertFalse(missed["ok"])
        self.assertTrue(heard["ok"], heard)
        self.assertEqual(heard["text"], "Open Excel")
        self.assertEqual(commands["n"], 1)
        self.assertEqual(chimes["n"], 2)
        self.assertEqual(inline["text"], "open notepad")
        self.assertEqual(commands["n"], 1)

    def test_blender_task_runs_headless_and_checks_the_export(self) -> None:
        cube = "import bpy\nbpy.ops.mesh.primitive_cube_add()\n"
        mesh = "o Basket\nv 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n"
        self.assertIn("run_blender_task", gta5_agent.SYSTEM_PROMPT)
        self.assertIn("background", gta5_agent.SYSTEM_PROMPT)

        gta5_agent.begin_task_turn("Make a basket in Blender and open Excel")
        blocked = gta5_agent.invoke_tool(
            "run_blender_task",
            {"script": cube, "output_path": str(self.root / "workspace" / "basket.obj")},
        )
        self.assertFalse(blocked["ok"])
        self.assertIn("create_task_plan", blocked["error"])

        gta5_agent.begin_task_turn("Make a basket in Blender")
        guarded = gta5_agent.invoke_tool(
            "run_blender_task",
            {"script": cube, "output_path": str(self.root / "workspace" / "guard.obj")},
        )
        self.assertTrue(guarded["ok"], guarded)
        with self.assertRaises(AssertionError) as caught:
            gta5_agent.blender_task.wait_for_jobs()
        self.assertIn("real blender", str(caught.exception))

        refused = gta5_agent.invoke_tool(
            "run_blender_task",
            {"script": "import bpy\nos.system('calc')\n", "output_path": "basket.obj"},
        )
        self.assertFalse(refused["ok"])
        self.assertIn("program", refused["error"].casefold())
        windows = gta5_agent.invoke_tool(
            "run_blender_task",
            {"script": cube, "output_path": r"C:\Windows\basket.obj"},
        )
        self.assertFalse(windows["ok"])
        syntax = gta5_agent.invoke_tool(
            "run_blender_task",
            {"script": "import bpy\n(\n", "output_path": "basket.obj"},
        )
        self.assertIn("syntax", syntax["error"].casefold())

        gta5_agent.blender_runner_override = None
        gta5_agent.blender_executable_override = False
        with mock.patch("subprocess.Popen", side_effect=AssertionError("real blender")):
            missing = gta5_agent.invoke_tool(
                "run_blender_task",
                {"script": cube, "output_path": str(self.root / "workspace" / "missing.obj")},
            )
        self.assertFalse(missing["ok"])
        self.assertIn("not installed", missing["error"])

        drive = self.root / "pedrodrive"
        drive.mkdir()
        gta5_agent._volumes = lambda: [(str(drive) + "\\", "GameDrive")]
        release = threading.Event()
        arrived = threading.Semaphore(0)
        notes: list[str] = []
        self.addCleanup(release.set)

        def runner(
            command: list[str],
            script_path: Path,
            output_path: Path,
        ) -> dict[str, object]:
            self.assertIsInstance(command, list)
            self.assertEqual(command[1:3], ["-b", "-P"])
            self.assertTrue(str(command[3]).endswith(".py"))
            script = script_path.read_text(encoding="utf-8")
            self.assertIn("primitive_cube_add", script)
            self.assertIn(json.dumps(str(output_path)), script)
            self.assertNotIn("os.system", script)
            arrived.release()
            self.assertTrue(release.wait(2))
            if output_path.suffix.casefold() == ".obj":
                output_path.write_text(mesh, encoding="utf-8")
            return {"returncode": 0, "stdout": "export ok", "stderr": ""}

        gta5_agent.blender_runner_override = runner
        gta5_agent.blender_notify_override = notes.append
        gta5_agent.blender_executable_override = self.root / "blender.exe"
        started = gta5_agent.invoke_tool(
            "run_blender_task",
            {"script": cube, "output_path": "GameDrive/models/basket.obj"},
        )
        self.assertTrue(started["ok"], started)
        self.assertEqual(started["status"], "started")
        self.assertTrue(arrived.acquire(timeout=1))
        target = drive / "models" / "basket.obj"
        self.assertFalse(target.exists())
        second = gta5_agent.invoke_tool(
            "run_blender_task",
            {"script": cube, "name": "crate"},
        )
        self.assertTrue(second["ok"], second)
        self.assertTrue(arrived.acquire(timeout=1))
        third = gta5_agent.invoke_tool(
            "run_blender_task",
            {"script": cube, "name": "extra"},
        )
        self.assertFalse(third["ok"])
        self.assertIn("already", third["error"])
        release.set()
        gta5_agent.blender_task.wait_for_jobs()
        self.assertTrue(target.is_file())
        self.assertGreaterEqual(target.stat().st_size, gta5_agent.blender_task.MIN_MODEL_BYTES)
        self.assertTrue(any("ready" in note.casefold() for note in notes))
        self.assertTrue(gta5_agent.blender_task.last_notice["ok"])
        ready = gta5_agent.invoke_tool("blender_job_status", {})
        self.assertTrue(ready["ok"], ready)
        self.assertEqual(ready["status"], "ready")
        opened: list[str] = []
        gta5_agent.blender_open_override = opened.append
        showed = gta5_agent.invoke_tool("blender_job_status", {"open_file": True})
        self.assertTrue(showed["ok"], showed)
        self.assertEqual(opened, [ready["path"]])

        def fail(
            command: list[str],
            script_path: Path,
            output_path: Path,
        ) -> dict[str, object]:
            return {
                "returncode": 1,
                "stdout": "",
                "stderr": (
                    "Traceback (most recent call last):\n"
                    "ModuleNotFoundError: No module named 'basket_addon'\n"
                ),
            }

        gta5_agent.blender_runner_override = fail
        broken = gta5_agent.invoke_tool(
            "run_blender_task",
            {"script": cube, "output_path": "GameDrive/models/broken.obj"},
        )
        self.assertFalse(broken["ok"])
        self.assertEqual(broken["status"], "failed")
        self.assertIn("basket_addon", broken["error"])
        self.assertFalse((drive / "models" / "broken.obj").exists())
        asked = gta5_agent.invoke_tool("blender_job_status", {"open_file": True})
        self.assertFalse(asked["ok"])
        self.assertIn("basket_addon", asked["error"])
        self.assertEqual(opened, [ready["path"]])

        def invalid(
            command: list[str],
            script_path: Path,
            output_path: Path,
        ) -> dict[str, object]:
            output_path.write_bytes(b"")
            return {
                "returncode": 1,
                "stdout": "",
                "stderr": (
                    "AttributeError: 'bpy.ops.mesh' object has no attribute "
                    "'primitive_basket_add'\n"
                ),
            }

        gta5_agent.blender_runner_override = invalid
        rejected = gta5_agent.invoke_tool(
            "run_blender_task",
            {"script": cube, "output_path": "GameDrive/models/bad.obj"},
        )
        self.assertFalse(rejected["ok"])
        self.assertIn("primitive_basket_add", rejected["error"])
        self.assertNotIn("ready", rejected["error"].casefold())

        spoken: list[str] = []

        def fake_speak(text: str, **kwargs: object) -> dict[str, object]:
            self.assertIs(kwargs.get("barge_in"), False)
            spoken.append(text)
            return {"ok": True, "text": text}

        gta5_agent.blender_notify_override = None
        with mock.patch.object(gta5_agent, "speak_response", side_effect=fake_speak):
            gta5_agent.blender_task._notify(
                "The 3D model is ready.",
                ok=True,
                path=str(target),
                job_id="voice",
            )
        self.assertEqual(spoken, ["The 3D model is ready."])
        gta5_agent._speech_stop = threading.Event()
        try:
            with mock.patch.object(gta5_agent, "speak_response", side_effect=fake_speak):
                gta5_agent.blender_task._notify(
                    "The 3D model is ready.",
                    ok=True,
                    path=str(target),
                    job_id="quiet",
                )
        finally:
            gta5_agent._speech_stop = None
        self.assertEqual(spoken, ["The 3D model is ready."])

    def test_blender_launch_passes_the_script_and_output(self) -> None:
        mesh = "o Basket\nv 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n"
        output = self.root / "workspace" / "launch-basket.obj"
        gta5_agent.blender_runner_override = None
        gta5_agent.blender_executable_override = self.root / "blender.exe"
        gta5_agent.blender_notify_override = lambda message: None
        calls: list[list[str]] = []

        class Process:
            returncode = 0

            def communicate(self, timeout: float | None = None) -> tuple[str, str]:
                output.write_text(mesh, encoding="utf-8")
                return ("export ok", "")

        def popen(command: list[str], **kwargs: object) -> Process:
            self.assertIsInstance(command, list)
            self.assertEqual(command[1:3], ["-b", "-P"])
            self.assertIs(kwargs.get("shell"), False)
            if os.name == "nt":
                self.assertIn("creationflags", kwargs)
            calls.append(command)
            return Process()

        with mock.patch("blender_task.subprocess.Popen", side_effect=popen):
            built = gta5_agent.invoke_tool(
                "run_blender_task",
                {
                    "script": "import bpy\nbpy.ops.mesh.primitive_cube_add()\n",
                    "output_path": str(output),
                },
            )
        self.assertTrue(built["ok"], built)
        self.assertEqual(built["status"], "ready")
        self.assertEqual(len(calls), 1)
        self.assertTrue(output.is_file())
        self.assertNotIn("positional argument", built["message"])

        def missing_program(command: list[str], **kwargs: object) -> Process:
            raise OSError("The system cannot find blender.exe")

        with mock.patch("blender_task.subprocess.Popen", side_effect=missing_program):
            failed = gta5_agent.invoke_tool(
                "run_blender_task",
                {
                    "script": "import bpy\nbpy.ops.mesh.primitive_cube_add()\n",
                    "output_path": str(self.root / "workspace" / "missing-basket.obj"),
                },
            )
        self.assertFalse(failed["ok"])
        self.assertEqual(failed["status"], "failed")
        self.assertIn("cannot find", failed["error"].casefold())
        self.assertNotIn("positional argument", failed["error"])

    def test_local_program_writes_files_and_does_not_launch_unless_asked(self) -> None:
        self.assertIn("build_local_program", gta5_agent.SYSTEM_PROMPT)
        self.assertIn("original program", gta5_agent.SYSTEM_PROMPT)
        self.assertIn("Adobe After Effects", gta5_agent.SYSTEM_PROMPT)

        gta5_agent.begin_task_turn("build me a cheap video editor")
        files = json.dumps(
            [
                {
                    "path": "main.py",
                    "content": "import tkinter as tk\nroot = tk.Tk()\nroot.title('Test editor')\nroot.mainloop()\n",
                },
                {"path": "notes.txt", "content": "A small original layer editor.\n"},
            ]
        )
        saved = gta5_agent.invoke_tool(
            "build_local_program",
            {"name": "test-editor", "files": files, "run": False},
        )
        self.assertTrue(saved["ok"], saved)
        self.assertFalse(saved["started"])
        project = Path(saved["path"])
        self.assertEqual(
            project,
            (gta5_agent.WORKSPACE / "builds" / "test-editor").resolve(),
        )
        self.assertIn("Test editor", (project / "main.py").read_text(encoding="utf-8"))
        self.assertTrue((project / "notes.txt").is_file())

        gta5_agent.begin_task_turn(
            "build me a cheap video editor and organize my GameDrive drive"
        )
        blocked = gta5_agent.invoke_tool(
            "build_local_program",
            {"name": "test-editor", "files": files},
        )
        self.assertFalse(blocked["ok"])
        self.assertIn("create_task_plan", blocked["error"])

        gta5_agent.begin_task_turn("")
        outside = gta5_agent.invoke_tool(
            "build_local_program",
            {
                "name": "escape",
                "files": json.dumps(
                    [{"path": "../outside.py", "content": "print(1)\n"}]
                ),
            },
        )
        self.assertFalse(outside["ok"])
        self.assertIn("inside the project", outside["error"])
        windows = gta5_agent.invoke_tool(
            "build_local_program",
            {
                "name": "bad",
                "output_path": r"C:\Windows\editor",
                "files": files,
            },
        )
        self.assertFalse(windows["ok"])
        cracked = gta5_agent.invoke_tool(
            "build_local_program",
            {
                "name": "bad",
                "files": json.dumps(
                    [{"path": "main.py", "content": "print('fitgirl repack')\n"}]
                ),
            },
        )
        self.assertFalse(cracked["ok"])
        self.assertIn("original program", cracked["error"])

        game = self.make_game()
        in_game = gta5_agent.invoke_tool(
            "build_local_program",
            {"name": "mod", "output_path": str(game), "files": files},
        )
        self.assertFalse(in_game["ok"])
        self.assertIn("game folder", in_game["error"])

        with self.assertRaises(AssertionError) as caught:
            gta5_agent.local_build.build_local_program(
                "test-editor",
                files,
                entry="main.py",
                run=True,
            )
        self.assertIn("real program", str(caught.exception))

        drive = self.root / "pedrodrive"
        drive.mkdir()
        gta5_agent._volumes = lambda: [(str(drive) + "\\", "GameDrive")]
        launched: list[list[str]] = []

        def runner(command: list[str], cwd: Path) -> None:
            self.assertIsInstance(command, list)
            self.assertFalse(any("|" in part or "&" in part for part in command))
            self.assertEqual(cwd, (drive / "Apps" / "editor").resolve())
            launched.append(command)

        gta5_agent.program_runner_override = runner
        started = gta5_agent.invoke_tool(
            "build_local_program",
            {
                "name": "editor",
                "output_path": "GameDrive/Apps/editor",
                "files": files,
                "entry": "main.py",
                "run": True,
            },
        )
        self.assertTrue(started["ok"], started)
        self.assertTrue(started["started"])
        self.assertEqual(len(launched), 1)
        self.assertEqual(launched[0][0], sys.executable)
        self.assertTrue(launched[0][1].endswith("main.py"))
        self.assertIn("Test editor", (drive / "Apps" / "editor" / "main.py").read_text(encoding="utf-8"))

    def test_time_search_keeps_last_week_videos(self) -> None:
        names = [item["name"] for item in gta5_agent.TOOL_DECLARATIONS]
        for name in (
            "send_remote_update",
            "process_media",
            "git_manager",
            "search_files_by_time",
        ):
            self.assertIn(name, gta5_agent.TOOLS)
            self.assertIn(name, names)
        for phrase in (
            "search_files_by_time",
            "send_remote_update",
            "process_media",
            "git_manager",
            "Never force-push",
        ):
            self.assertIn(phrase, gta5_agent.SYSTEM_PROMPT)
        self.assertFalse(gta5_agent._request_needs_plan("Open Excel"))
        self.assertFalse(gta5_agent._request_needs_plan("videos from last week"))
        self.assertFalse(gta5_agent._request_needs_plan("convert this video"))
        self.assertTrue(
            gta5_agent._request_needs_plan("text me on telegram and transcode the video")
        )

        root = gta5_agent.search_root_override
        assert root is not None
        clips = root / "clips"
        clips.mkdir()
        newer = clips / "trip-new.mp4"
        older = clips / "trip-old.mp4"
        outside = clips / "this-week.mp4"
        february = clips / "february.mp4"
        note = clips / "notes.txt"
        secret = clips / "archive.key"
        for path, payload in (
            (newer, b"n"),
            (older, b"o"),
            (outside, b"x"),
            (february, b"m"),
            (secret, b"k"),
        ):
            path.write_bytes(payload)
        note.write_text("hello", encoding="utf-8")
        (clips / ".env").write_text("nope", encoding="utf-8")
        elsewhere = self.root / "elsewhere"
        elsewhere.mkdir()
        (elsewhere / "lost.mp4").write_bytes(b"lost")
        frozen = datetime(2026, 3, 15, 15, 0, 0).timestamp()
        gta5_agent.scheduler_clock = lambda: frozen
        os.utime(newer, (datetime(2026, 3, 6, 12).timestamp(),) * 2)
        os.utime(older, (datetime(2026, 3, 4, 12).timestamp(),) * 2)
        os.utime(outside, (datetime(2026, 3, 12, 12).timestamp(),) * 2)
        os.utime(february, (datetime(2026, 2, 10, 12).timestamp(),) * 2)
        os.utime(note, (datetime(2026, 3, 6, 12).timestamp(),) * 2)
        os.utime(secret, (datetime(2026, 3, 6, 12).timestamp(),) * 2)
        os.utime(elsewhere / "lost.mp4", (datetime(2026, 3, 6, 12).timestamp(),) * 2)

        found = gta5_agent.invoke_tool(
            "search_files_by_time",
            {"query": "videos from last week"},
        )
        self.assertTrue(found["ok"], found)
        self.assertEqual(
            [item["name"] for item in found["matches"]],
            ["trip-new.mp4", "trip-old.mp4"],
        )
        blob = json.dumps(found)
        self.assertNotIn("archive.key", blob)
        self.assertNotIn("notes.txt", blob)
        self.assertNotIn("lost.mp4", blob)
        self.assertNotIn(".env", blob)
        self.assertTrue(newer.is_file())

        month = gta5_agent.local_search.search_files_by_time("videos from last month")
        self.assertTrue(month["ok"], month)
        self.assertEqual([item["name"] for item in month["matches"]], ["february.mp4"])
        bare = gta5_agent.local_search.search_files_by_time("hello")
        self.assertFalse(bare["ok"])
        self.assertIn("file type or a time", bare["error"])

    def test_file_search_covers_desktop_unless_a_folder_is_named(self) -> None:
        home = self.root / "profile"
        desktop = home / "Desktop"
        documents = home / "Documents"
        downloads = home / "Downloads"
        appdata = home / "AppData" / "Local"
        pedro = self.root / "pedro-drive"
        project = self.root / "project-folder"
        for path in (desktop, documents, downloads, appdata, pedro / "clips", project):
            path.mkdir(parents=True)
        files = {
            desktop / "budget.xlsx": datetime(2026, 10, 10, 15),
            documents / "old-budget.xlsx": datetime(2026, 9, 2, 15),
            downloads / "notes.txt": datetime(2026, 10, 10, 15),
            appdata / "hidden.xlsx": datetime(2026, 10, 10, 15),
            home / "loose.xlsx": datetime(2026, 10, 10, 16),
            pedro / "clips" / "pedro.xlsx": datetime(2026, 10, 10, 9),
            project / "project.xlsx": datetime(2026, 10, 10, 12),
        }
        for path, moment in files.items():
            path.write_bytes(b"sheet")
            stamp = moment.timestamp()
            os.utime(path, (stamp, stamp))
        self.assertFalse(
            gta5_agent._request_needs_plan("Where is the Excel file I saved yesterday?")
        )
        gta5_agent.search_root_override = None
        gta5_agent.scheduler_clock = lambda: datetime(2026, 10, 11, 15).timestamp()
        gta5_agent._volumes = lambda: [(str(pedro) + "\\", "GameDrive")]
        original_app = gta5_agent.APP_DIR
        gta5_agent.APP_DIR = project
        try:
            with mock.patch("local_search.Path.home", return_value=home):
                found = gta5_agent.local_search.search_files_by_time(
                    "Where is the Excel file I saved yesterday?"
                )
                self.assertTrue(found["ok"], found)
                names = [item["name"] for item in found["matches"]]
                self.assertEqual(names, ["loose.xlsx", "budget.xlsx", "pedro.xlsx"])
                blob = json.dumps(found)
                self.assertNotIn("old-budget.xlsx", blob)
                self.assertNotIn("hidden.xlsx", blob)
                self.assertNotIn("notes.txt", blob)
                self.assertNotIn("project.xlsx", blob)

                pedro_only = gta5_agent.local_search.search_files_by_time(
                    "Excel file I saved yesterday on GameDrive"
                )
                self.assertEqual(
                    [item["name"] for item in pedro_only["matches"]],
                    ["pedro.xlsx"],
                )
                desk = gta5_agent.local_search.search_files_by_time(
                    "Excel file on the desktop from yesterday"
                )
                self.assertEqual(
                    [item["name"] for item in desk["matches"]],
                    ["budget.xlsx"],
                )
                owned = gta5_agent.local_search.search_files_by_time(
                    "Excel file in my project folder from yesterday"
                )
                self.assertEqual(
                    [item["name"] for item in owned["matches"]],
                    ["project.xlsx"],
                )
                blocked = gta5_agent.local_search.search_files_by_time(
                    r"Excel file saved yesterday in C:\Windows"
                )
                self.assertFalse(blocked["ok"])
                self.assertIn("outside the folders", blocked["error"])
        finally:
            gta5_agent.APP_DIR = original_app
            gta5_agent.search_root_override = self.root / "pedro"

    def test_ffmpeg_converts_without_a_shell(self) -> None:
        self.assertIn("shell=False", inspect.getsource(gta5_agent.media_ffmpeg._run))
        clip = self.root / "clips" / "a.mp4"
        clip.parent.mkdir()
        clip.write_bytes(b"source-video")
        with self.assertRaises(AssertionError) as guarded:
            gta5_agent.media_ffmpeg.process_media("convert", str(clip), str(self.root / "out.mp4"))
        self.assertIn("real ffmpeg", str(guarded.exception))

        gta5_agent.ffmpeg_executable_override = False
        gta5_agent.media_runner_override = None
        with mock.patch(
            "media_ffmpeg.subprocess.run",
            side_effect=AssertionError("real ffmpeg"),
        ):
            missing = gta5_agent.media_ffmpeg.process_media("convert", str(clip))
        self.assertFalse(missing["ok"])
        self.assertIn("not installed", missing["error"])

        calls: list[list[str]] = []

        def runner(command: list[str], destination: Path) -> dict[str, object]:
            self.assertIsInstance(command, list)
            self.assertIn("-i", command)
            self.assertNotIn("-filter_complex", command)
            calls.append(command)
            if "fps=1" in command:
                self.assertEqual(command[command.index("-vf") + 1], "fps=1")
                frame = destination.parent / "frame-0001.png"
                frame.write_bytes(b"f" * 20)
            else:
                destination.write_bytes(b"x" * 32)
            return {"returncode": 0, "stdout": "", "stderr": ""}

        drive = self.root / "media-drive"
        source = drive / "clips" / "a.mp4"
        source.parent.mkdir(parents=True)
        source.write_bytes(b"pedro-video")
        gta5_agent._volumes = lambda: [(str(drive) + "\\", "GameDrive")]
        gta5_agent.ffmpeg_executable_override = self.root / "ffmpeg-test"
        gta5_agent.media_runner_override = runner
        with mock.patch(
            "media_ffmpeg.subprocess.run",
            side_effect=AssertionError("real ffmpeg"),
        ):
            converted = gta5_agent.invoke_tool(
                "process_media",
                {
                    "action": "convert",
                    "source": "GameDrive/clips/a.mp4",
                    "output_path": "GameDrive/clips/a-out.mp4",
                },
            )
        self.assertTrue(converted["ok"], converted)
        self.assertEqual(converted["status"], "ready")
        output = drive / "clips" / "a-out.mp4"
        self.assertGreaterEqual(output.stat().st_size, 16)
        self.assertEqual(calls[0][calls[0].index("-i") + 1], str(source.resolve()))
        blocked = gta5_agent.invoke_tool(
            "process_media",
            {"action": "convert", "source": r"C:\Windows\clip.mp4"},
        )
        self.assertFalse(blocked["ok"])
        self.assertIn("GameDrive", blocked["error"])

        folder = self.root / "batch"
        folder.mkdir()
        for index in range(9):
            (folder / f"a{index}.mp4").write_bytes(b"clip")
        calls.clear()
        batched = gta5_agent.media_ffmpeg.process_media(
            "convert",
            str(folder),
            str(self.root / "batch-out"),
        )
        self.assertTrue(batched["ok"], batched)
        self.assertEqual(len(calls), 8)
        self.assertEqual(len(batched["files"]), 8)

        frames = gta5_agent.media_ffmpeg.process_media(
            "extract_frames",
            str(clip),
            str(self.root / "frames"),
        )
        self.assertTrue(frames["ok"], frames)
        self.assertTrue((self.root / "frames" / "frame-0001.png").is_file())

    def test_git_commit_unstages_secrets_and_push_is_plain(self) -> None:
        self.assertIn("shell=False", inspect.getsource(gta5_agent.git_manager._run))
        repo = self.root / "repo"
        repo.mkdir()
        (repo / "main.py").write_text("print(1)\n", encoding="utf-8")
        (repo / ".env").write_text("TOKEN=1\n", encoding="utf-8")
        with self.assertRaises(AssertionError) as guarded:
            gta5_agent.git_manager.git_manager("status", str(repo))
        self.assertIn("real git", str(guarded.exception))

        calls: list[list[str]] = []

        def runner(command: list[str], cwd: Path) -> dict[str, object]:
            self.assertIsInstance(command, list)
            self.assertNotIn("-f", command)
            self.assertNotIn("--force", command)
            self.assertNotIn("config", command)
            self.assertFalse(any(part.startswith("http://") or part.startswith("https://") for part in command))
            self.assertEqual(cwd, repo.resolve())
            calls.append(list(command))
            if command == ["git", "status", "--porcelain"]:
                return {"returncode": 0, "stdout": "A  .env\n M main.py\n", "stderr": ""}
            if command[:4] == ["git", "reset", "HEAD", "--"]:
                self.assertEqual(command[4:], [".env"])
                return {"returncode": 0, "stdout": "", "stderr": ""}
            if command[:3] == ["git", "commit", "-m"]:
                self.assertEqual(command, ["git", "commit", "-m", "Save the editor"])
                return {"returncode": 0, "stdout": "", "stderr": ""}
            return {"returncode": 0, "stdout": "", "stderr": ""}

        gta5_agent.git_runner_override = runner
        with mock.patch("git_manager.subprocess.run", side_effect=AssertionError("real git")):
            committed = gta5_agent.invoke_tool(
                "git_manager",
                {"action": "commit", "path": str(repo), "message": "Save the editor"},
            )
        self.assertTrue(committed["ok"], committed)
        self.assertIn(["git", "status", "--porcelain"], calls)
        self.assertIn(["git", "reset", "HEAD", "--", ".env"], calls)
        self.assertIn(["git", "add", "--", "main.py"], calls)
        self.assertIn(["git", "commit", "-m", "Save the editor"], calls)
        self.assertNotIn(".env", committed["files"])

        calls.clear()
        forced = gta5_agent.invoke_tool(
            "git_manager",
            {"action": "push --force", "path": str(repo)},
        )
        self.assertFalse(forced["ok"])
        self.assertIn("Force push", forced["error"])
        self.assertEqual(calls, [])
        pushed = gta5_agent.invoke_tool("git_manager", {"action": "push", "path": str(repo)})
        self.assertTrue(pushed["ok"], pushed)
        self.assertEqual(calls, [["git", "push"]])

        calls.clear()

        def missing_identity(command: list[str], cwd: Path) -> dict[str, object]:
            calls.append(list(command))
            if command[:3] == ["git", "commit", "-m"]:
                return {
                    "returncode": 128,
                    "stdout": "",
                    "stderr": "Please tell me who you are.\nRun git config user.email",
                }
            if command == ["git", "status", "--porcelain"]:
                return {"returncode": 0, "stdout": " M main.py\n", "stderr": ""}
            return {"returncode": 0, "stdout": "", "stderr": ""}

        gta5_agent.git_runner_override = missing_identity
        unnamed = gta5_agent.git_manager.git_manager("commit", str(repo), "Save the editor")
        self.assertFalse(unnamed["ok"])
        self.assertIn("will not change git config", unnamed["error"])
        self.assertTrue(all("config" not in command for command in calls))

        calls.clear()
        gta5_agent.git_runner_override = runner
        cracked = gta5_agent.git_manager.git_manager(
            "commit",
            str(repo),
            "add the fitgirl repack",
        )
        self.assertFalse(cracked["ok"])
        self.assertEqual(calls, [])
        empty = gta5_agent.git_manager.git_manager("commit", str(repo), " ")
        self.assertFalse(empty["ok"])
        self.assertIn("commit message", empty["error"])

    def test_phone_bridge_replies_only_to_the_paired_chat(self) -> None:
        token = "phone-token-value"
        hook = "https://discord.com/api/webhooks/9/phone-hook-value"
        os.environ["TELEGRAM_BOT_TOKEN"] = token
        os.environ["TELEGRAM_CHAT_ID"] = "42"
        os.environ["DISCORD_WEBHOOK_URL"] = hook
        seen: list[tuple[str, dict[str, object]]] = []

        def transport(kind: str, payload: dict[str, object]) -> dict[str, object]:
            encoded = json.dumps(payload)
            self.assertNotIn(token, encoded)
            self.assertNotIn(hook, encoded)
            self.assertNotIn(token, kind)
            seen.append((kind, payload))
            if kind == "telegram_updates":
                if payload.get("offset") == 0:
                    return {
                        "result": [
                            {
                                "update_id": 7,
                                "message": {"chat": {"id": 99}, "text": "ignore me"},
                            },
                            {
                                "update_id": 8,
                                "message": {"chat": {"id": 42}, "text": "is the export done?"},
                            },
                            {
                                "update_id": 8,
                                "message": {"chat": {"id": 42}, "text": ""},
                            },
                        ]
                    }
                return {"result": []}
            return {"ok": True}

        gta5_agent.remote_transport_override = transport
        gta5_agent.remote_reply_override = lambda text: "The export is ready."
        with mock.patch("urllib.request.urlopen", side_effect=AssertionError("real network")):
            with mock.patch("builtins.print") as printed:
                checked = gta5_agent.remote_bridge.poll_once()
                again = gta5_agent.remote_bridge.poll_once()
        self.assertTrue(checked["ok"], checked)
        self.assertEqual(checked["replied"], 1)
        self.assertEqual(again["replied"], 0)
        self.assertEqual([item[0] for item in seen], ["telegram_updates", "telegram_send", "telegram_updates"])
        self.assertEqual(seen[1][1]["body"]["chat_id"], "42")
        self.assertEqual(seen[1][1]["body"]["text"], "The export is ready.")
        self.assertEqual(seen[2][1]["offset"], 9)
        logged = "\n".join(str(call.args[0]) for call in printed.call_args_list if call.args)
        self.assertNotIn(token, logged)
        self.assertNotIn(hook, logged)

        def boom(kind: str, payload: dict[str, object]) -> dict[str, object]:
            raise RuntimeError(f"failed bot{token} and {hook}")

        gta5_agent.remote_transport_override = boom
        failed = gta5_agent.remote_bridge.poll_once()
        self.assertFalse(failed["ok"])
        self.assertNotIn(token, failed["error"])
        self.assertNotIn(hook, failed["error"])
        self.assertIn("[redacted]", failed["error"])

        sent: list[tuple[str, dict[str, object]]] = []

        def alerts(kind: str, payload: dict[str, object]) -> dict[str, object]:
            encoded = json.dumps(payload)
            self.assertNotIn(token, encoded)
            self.assertNotIn(hook, encoded)
            sent.append((kind, payload))
            return {"ok": True}

        gta5_agent.remote_transport_override = alerts
        with mock.patch("urllib.request.urlopen", side_effect=AssertionError("real network")):
            note = gta5_agent.remote_bridge.notify("Blender export is done")
        self.assertTrue(note["ok"], note)
        self.assertEqual(note["channels"], ["discord", "telegram"])
        self.assertEqual(sent[0][0], "discord")
        self.assertEqual(sent[0][1]["body"]["content"], "Blender export is done")
        self.assertNotIn("url", sent[0][1])

        os.environ.pop("TELEGRAM_BOT_TOKEN", None)
        os.environ.pop("TELEGRAM_CHAT_ID", None)
        sent.clear()
        discord_only = gta5_agent.remote_bridge.notify("Script finished")
        self.assertTrue(discord_only["ok"], discord_only)
        self.assertEqual(discord_only["channels"], ["discord"])
        self.assertEqual([item[0] for item in sent], ["discord"])

        os.environ.pop("DISCORD_WEBHOOK_URL", None)
        gta5_agent.remote_transport_override = None
        quiet = gta5_agent.invoke_tool("send_remote_update", {"message": "hello"})
        self.assertFalse(quiet["ok"])
        self.assertIn("not set up", quiet["error"])

    def test_phone_screenshot_sends_a_photo_without_blocking(self) -> None:
        from PIL import Image

        bridge = gta5_agent.remote_bridge
        self.assertTrue(bridge.wants_screenshot("/screenshot"))
        self.assertTrue(bridge.wants_screenshot("/screenshot@desk_bot"))
        self.assertTrue(bridge.wants_screenshot("send a screenshot"))
        self.assertTrue(bridge.wants_screenshot("take a screenshot"))
        self.assertTrue(bridge.wants_screenshot("screenshot"))
        self.assertTrue(bridge.wants_screenshot("can you send a screenshot"))
        self.assertTrue(bridge.wants_screenshot("send me a picture of my screen"))
        self.assertTrue(bridge.wants_screenshot("show me my screen"))
        self.assertTrue(bridge.wants_screenshot("what's on my screen"))
        self.assertFalse(bridge.wants_screenshot("is the export done?"))
        self.assertFalse(bridge.wants_screenshot("show me my documents"))
        self.assertFalse(bridge.wants_screenshot("send a screenshot and organize my drive"))
        self.assertIn("send a screenshot", gta5_agent.SYSTEM_PROMPT)

        token = "phone-token-value"
        hook = "https://discord.com/api/webhooks/9/phone-hook-value"
        os.environ["TELEGRAM_BOT_TOKEN"] = token
        os.environ["TELEGRAM_CHAT_ID"] = "42"
        os.environ["DISCORD_WEBHOOK_URL"] = hook
        buffer = io.BytesIO()
        Image.new("RGB", (20, 10), (20, 40, 60)).save(buffer, format="PNG")
        png = buffer.getvalue()
        shots: list[str] = []

        def capture() -> dict[str, object]:
            shots.append("shot")
            return {"png": png, "screen_width": 20, "screen_height": 10}

        gta5_agent.screenshot_override = capture
        expected = gta5_agent.take_screenshot()["_screenshot_bytes"]
        self.assertTrue(expected.startswith(b"\xff\xd8"))
        prepared = bridge._telegram_jpeg(expected)
        self.assertTrue(prepared.startswith(b"\xff\xd8"))
        self.assertNotEqual(prepared, expected)
        self.assertIn(b"\xff\xc0", prepared)
        shots.clear()
        seen: list[tuple[str, dict[str, object]]] = []

        def transport(kind: str, payload: dict[str, object]) -> dict[str, object]:
            public = {key: value for key, value in payload.items() if key != "image"}
            encoded = json.dumps(public)
            self.assertNotIn(token, encoded)
            self.assertNotIn(hook, encoded)
            seen.append((kind, payload))
            return {"ok": True}

        gta5_agent.remote_transport_override = transport
        gta5_agent.remote_reply_override = lambda text: "The export is ready."

        def updates(commands: list[tuple[int, int, str]]) -> dict[str, object]:
            return {
                "result": [
                    {
                        "update_id": update_id,
                        "message": {"chat": {"id": chat_id}, "text": text},
                    }
                    for update_id, chat_id, text in commands
                ]
            }

        with mock.patch("urllib.request.urlopen", side_effect=AssertionError("real network")):
            gta5_agent.remote_transport_override = lambda kind, payload: (
                updates([(7, 99, "/screenshot"), (8, 42, "show me my screen")])
                if kind == "telegram_updates"
                else transport(kind, payload)
            )
            checked = bridge.poll_once()
        self.assertTrue(checked["ok"], checked)
        self.assertEqual(checked["replied"], 1)
        self.assertEqual(shots, ["shot"])
        kinds = [item[0] for item in seen]
        self.assertEqual(kinds, ["telegram_photo", "discord_photo"])
        self.assertEqual(seen[0][1]["chat_id"], "42")
        self.assertEqual(seen[0][1]["image"], expected)
        self.assertEqual(seen[1][1]["image"], expected)
        self.assertFalse(list((gta5_agent.WORKSPACE / "screenshots").glob("phone-*")))

        seen.clear()
        shots.clear()

        def empty() -> dict[str, object]:
            shots.append("empty")
            return {"png": b"", "screen_width": 8, "screen_height": 8}

        gta5_agent.screenshot_override = empty
        gta5_agent.remote_transport_override = lambda kind, payload: (
            updates([(9, 42, "send a screenshot")])
            if kind == "telegram_updates"
            else transport(kind, payload)
        )
        failed = bridge.poll_once()
        self.assertTrue(failed["ok"], failed)
        self.assertEqual([item[0] for item in seen], ["telegram_send"])
        self.assertNotIn("telegram_photo", [item[0] for item in seen])
        self.assertIn("no image", str(seen[0][1]).casefold())
        self.assertFalse(list((gta5_agent.WORKSPACE / "screenshots").glob("phone-*")))

        gta5_agent.screenshot_override = capture
        gta5_agent.remote_transport_override = None
        bridge.reset_remote_bridge()
        release = threading.Event()
        entered = threading.Event()
        bodies: list[bytes] = []

        class Response:
            def __init__(self, raw: bytes) -> None:
                self.raw = raw

            def __enter__(self) -> "Response":
                return self

            def __exit__(self, *args: object) -> bool:
                return False

            def read(self) -> bytes:
                return self.raw

        def urlopen(target: object, timeout: float = 15) -> Response:
            url = str(getattr(target, "full_url", target))
            if "getUpdates" in url:
                raw = json.dumps(
                    {
                        "ok": True,
                        "result": [
                            {
                                "update_id": 1,
                                "message": {"chat": {"id": 42}, "text": "/screenshot"},
                            }
                        ],
                    }
                ).encode("utf-8")
                return Response(raw)
            body = bytes(getattr(target, "data", b"") or b"")
            self.assertNotIn(token.encode(), body)
            self.assertNotIn(hook.encode(), body)
            self.assertNotIn(expected, body)
            start = body.find(b"\xff\xd8")
            self.assertGreaterEqual(start, 0)
            sof = body.find(b"\xff\xc0", start)
            self.assertGreaterEqual(sof, 0)
            self.assertEqual(body[sof + 11], 0x22)
            bodies.append(body)
            if "sendPhoto" in url:
                self.assertIn(b'name="photo"', body)
                self.assertIn(b'name="chat_id"', body)
                self.assertIn(b'filename="screen.jpg"', body)
                entered.set()
                release.wait(1.5)
                return Response(
                    b'{"ok":true,"result":{"photo":[{"file_id":"shot","width":20,"height":10}]}}'
                )
            self.assertIn(b"files[0]", body)
            return Response(b'{"ok":true}')

        try:
            with mock.patch("urllib.request.urlopen", side_effect=urlopen):
                started = time.perf_counter()
                sent = bridge.poll_once()
                elapsed = time.perf_counter() - started
                self.assertTrue(sent["ok"], sent)
                self.assertLess(elapsed, 0.8)
                self.assertTrue(entered.wait(2))
                release.set()
                for worker in threading.enumerate():
                    if worker.name == "phone-photo":
                        self.assertTrue(worker.daemon)
                        worker.join(2)
        finally:
            release.set()
            for worker in threading.enumerate():
                if worker.name == "phone-photo":
                    worker.join(2)
        self.assertGreaterEqual(len(bodies), 1)
        self.assertFalse(list((gta5_agent.WORKSPACE / "screenshots").glob("phone-*")))

    def test_phone_screenshot_reports_telegram_rejection(self) -> None:
        import urllib.error
        from PIL import Image

        bridge = gta5_agent.remote_bridge
        token = "phone-token-value"
        os.environ["TELEGRAM_BOT_TOKEN"] = token
        os.environ["TELEGRAM_CHAT_ID"] = "42"
        buffer = io.BytesIO()
        Image.new("RGB", (20, 10), (20, 40, 60)).save(buffer, format="PNG")

        def capture() -> dict[str, object]:
            return {"png": buffer.getvalue(), "screen_width": 20, "screen_height": 10}

        gta5_agent.screenshot_override = capture
        gta5_agent.remote_transport_override = None
        gta5_agent.remote_reply_override = lambda text: "should not run"
        bridge.reset_remote_bridge()
        entered = threading.Event()
        sent: list[bytes] = []

        class Response:
            def __init__(self, raw: bytes) -> None:
                self.raw = raw

            def __enter__(self) -> "Response":
                return self

            def __exit__(self, *args: object) -> bool:
                return False

            def read(self) -> bytes:
                return self.raw

        def urlopen(target: object, timeout: float = 15) -> Response:
            url = str(getattr(target, "full_url", target))
            if "getUpdates" in url:
                raw = json.dumps(
                    {
                        "ok": True,
                        "result": [
                            {
                                "update_id": 3,
                                "message": {"chat": {"id": 42}, "text": "/screenshot"},
                            }
                        ],
                    }
                ).encode("utf-8")
                return Response(raw)
            if "sendPhoto" in url:
                raise urllib.error.HTTPError(
                    "https://api.telegram.org/bothidden/sendPhoto",
                    400,
                    "Bad Request",
                    None,
                    io.BytesIO(
                        b'{"ok":false,"description":"Bad Request: IMAGE_PROCESS_FAILED","error_code":400}'
                    ),
                )
            body = bytes(getattr(target, "data", b"") or b"")
            self.assertNotIn(token.encode(), body)
            self.assertNotIn(b"bothidden", body)
            self.assertIn(b"IMAGE_PROCESS_FAILED", body)
            sent.append(body)
            entered.set()
            return Response(b'{"ok":true}')

        try:
            with mock.patch("urllib.request.urlopen", side_effect=urlopen):
                checked = bridge.poll_once()
                self.assertTrue(checked["ok"], checked)
                self.assertTrue(entered.wait(2))
        finally:
            entered.set()
            for worker in threading.enumerate():
                if worker.name == "phone-photo":
                    worker.join(2)
        self.assertEqual(len(sent), 1)
        self.assertFalse(list((gta5_agent.WORKSPACE / "screenshots").glob("phone-*")))

    def test_browser_download_saves_a_report_without_opening_chromium(self) -> None:
        import browser_download

        tool = browser_download.browser_download_tool
        downloads = self.root / "Downloads"
        gta5_agent.downloads_override = downloads
        with self.assertRaises(AssertionError):
            tool("https://example.com/reports")
        calls: list[dict[str, object]] = []

        def runner(plan: dict[str, object], folder: Path) -> dict[str, object]:
            calls.append(plan)
            target = folder / "report.csv"
            target.write_bytes(b"item,amount\nhats,12\n")
            return {"title": "Reports", "saved": target}

        gta5_agent.browser_runner_override = runner
        secret = "desk-secret-value"
        os.environ["BROWSER_PASSWORD"] = secret
        self.addCleanup(lambda: os.environ.pop("BROWSER_PASSWORD", None))
        saved = tool(
            "https://example.com/reports",
            actions=[
                {"action": "fill", "selector": "#user", "text": "ada"},
                {"action": "fill", "selector": "#pass", "env": "BROWSER_PASSWORD"},
                {"action": "click", "selector": "a.report", "download": True},
            ],
            destination="downloads",
        )
        self.assertTrue(saved["ok"], saved)
        self.assertTrue(str(saved["path"]).endswith("report.csv"))
        self.assertEqual(Path(saved["path"]).resolve().parent, downloads.resolve())
        self.assertNotIn(secret, json.dumps(calls))
        self.assertNotIn(secret, saved["message"])
        self.assertEqual(calls[0]["actions"][1]["env"], "BROWSER_PASSWORD")

        blocked = [
            tool("javascript:alert(1)"),
            tool("https://user:pass@example.com/file"),
            tool("https://www.gta5-mods.com/misc/simple-zombies"),
            tool("https://example.com/fitgirl-repack"),
            tool("https://example.com/report", destination=r"C:\Windows"),
            tool(
                "https://example.com/report",
                actions=[{"action": "fill", "selector": "#pass", "text": "password=hunter2"}],
            ),
            tool(
                "https://example.com/report",
                actions=[{"action": "fill", "selector": "#pass", "env": "GEMINI_API_KEY"}],
            ),
        ]
        self.assertTrue(all(not item["ok"] for item in blocked), blocked)
        self.assertEqual(len(calls), 1)
        self.assertIn("direct file", blocked[2]["error"])
        self.assertIn("skip a download gate", gta5_agent.SYSTEM_PROMPT)
        self.assertIn("browser_download_tool", gta5_agent.SYSTEM_PROMPT)
        self.assertFalse(
            gta5_agent._request_needs_plan(
                "Go to this link, log in, and download the latest data report"
            )
        )
        self.assertTrue(
            gta5_agent._request_needs_plan(
                "download the report and update my spreadsheet"
            )
        )

        def plant_exe(plan: dict[str, object], folder: Path) -> dict[str, object]:
            target = folder / "tool.exe"
            target.write_bytes(b"MZ" + b"x" * 20)
            return {"title": "nope", "saved": target}

        gta5_agent.browser_runner_override = plant_exe
        refused = tool("https://example.com/tool", destination="downloads")
        self.assertFalse(refused["ok"], refused)
        self.assertFalse((downloads / "tool.exe").exists())

        gta5_agent._volumes = lambda: [(str(self.root / "pedro") + "\\", "GameDrive")]
        (self.root / "pedro").mkdir(exist_ok=True)

        def plant_pedro(plan: dict[str, object], folder: Path) -> dict[str, object]:
            target = folder / "report.csv"
            target.write_bytes(b"item,amount\nhats,12\n")
            return {"title": "Pedro", "saved": target}

        gta5_agent.browser_runner_override = plant_pedro
        on_drive = tool("https://example.com/reports", destination="GameDrive")
        self.assertTrue(on_drive["ok"], on_drive)
        self.assertEqual(Path(on_drive["path"]).resolve().parent, (self.root / "pedro").resolve())

    def test_browser_engine_uses_the_fake_playwright(self) -> None:
        import browser_download

        class Download:
            def __init__(self, name: str, data: bytes) -> None:
                self.suggested_filename = name
                self.data = data

            def save_as(self, path: str) -> None:
                Path(path).write_bytes(self.data)

        class Pending:
            def __init__(self, download: Download) -> None:
                self.value = download

            def __enter__(self) -> "Pending":
                return self

            def __exit__(self, *args: object) -> bool:
                return False

        class Page:
            def __init__(self, frames: list[object], download: Download | None) -> None:
                self.frames = frames
                self.download = download
                self.events: list[tuple[object, ...]] = []
                self.keyboard = self

            def goto(self, url: str, **kwargs: object) -> None:
                self.events.append(("goto", url))

            def fill(self, selector: str, text: str) -> None:
                self.events.append(("fill", selector, text))

            def click(self, selector: str) -> None:
                self.events.append(("click", selector))

            def press(self, key: str) -> None:
                self.events.append(("press", key))

            def title(self) -> str:
                return "Reports"

            def expect_download(self, timeout: int = 0) -> Pending:
                assert self.download is not None
                return Pending(self.download)

            def wait_for_timeout(self, delay: int) -> None:
                self.events.append(("wait", delay))

            def eval_on_selector_all(self, selector: str, script: str) -> list[dict[str, str]]:
                return [{"tag": "a", "text": "Download report", "id": "report", "name": ""}]

        class Context:
            def __init__(self, page: Page, fail: bool = False) -> None:
                self.page = page
                self.fail = fail

            def new_page(self) -> Page:
                return self.page

            def close(self) -> None:
                return None

        class Browser:
            def __init__(self, context: Context) -> None:
                self.context = context
                self.headless: bool | None = None
                self.kwargs: dict[str, object] | None = None

            def new_context(self, **kwargs: object) -> Context:
                self.kwargs = kwargs
                if self.context.fail:
                    raise RuntimeError("cookie blob secret=should-not-leak")
                return self.context

            def close(self) -> None:
                return None

        class Chromium:
            def __init__(self, browser: Browser) -> None:
                self.browser = browser

            def launch(self, headless: bool) -> Browser:
                self.browser.headless = headless
                return self.browser

        class Session:
            def __init__(self, browser: Browser) -> None:
                self.chromium = Chromium(browser)

            def __enter__(self) -> "Session":
                return self

            def __exit__(self, *args: object) -> bool:
                return False

        holder: dict[str, Browser] = {}

        def launcher() -> Session:
            page = Page(
                [type("Frame", (), {"url": "about:blank"})()],
                Download("report.csv", b"item,amount\nhats,12\n"),
            )
            browser = Browser(Context(page))
            holder["browser"] = browser
            return Session(browser)

        previous_launcher = browser_download.playwright_launcher
        previous_wait = browser_download.CHECK_WAIT_SECONDS
        browser_download.playwright_launcher = launcher
        browser_download.CHECK_WAIT_SECONDS = 0
        os.environ["BROWSER_PASSWORD"] = "desk-secret-value"
        folder = self.root / "fetched"
        folder.mkdir()
        try:
            outcome = browser_download._run_playwright(
                {
                    "url": "https://example.com/reports",
                    "visible": True,
                    "cookie_file": "",
                    "actions": [
                        {"action": "fill", "selector": "#pass", "env": "BROWSER_PASSWORD"},
                        {"action": "click", "selector": "a.report", "download": True},
                    ],
                },
                folder,
            )
            self.assertFalse(holder["browser"].headless)
            self.assertEqual(outcome["saved"].name, "report.csv")
            self.assertNotIn("desk-secret-value", json.dumps({"title": outcome["title"]}))
            self.assertEqual(outcome["saved"].read_bytes(), b"item,amount\nhats,12\n")

            page = Page(
                [type("Frame", (), {"url": "https://www.google.com/recaptcha/api2/anchor"})()],
                None,
            )
            holder["browser"] = Browser(Context(page))

            def captcha_launcher() -> Session:
                return Session(holder["browser"])

            browser_download.playwright_launcher = captcha_launcher
            with self.assertRaises(RuntimeError) as caught:
                browser_download._run_playwright(
                    {
                        "url": "https://example.com/reports",
                        "visible": True,
                        "cookie_file": "",
                        "actions": [{"action": "click", "selector": "a.report"}],
                    },
                    folder,
                )
            self.assertIn("Finish it in the browser window", str(caught.exception))
            self.assertEqual(page.events, [("goto", "https://example.com/reports")])

            cookie = gta5_agent.WORKSPACE / "session.json"
            cookie.parent.mkdir(parents=True, exist_ok=True)
            cookie.write_text('{"cookies":[]}', encoding="utf-8")
            page = Page([type("Frame", (), {"url": "about:blank"})()], None)
            browser = Browser(Context(page, fail=True))

            def cookie_launcher() -> Session:
                return Session(browser)

            browser_download.playwright_launcher = cookie_launcher
            with self.assertRaises(RuntimeError) as cookie_error:
                browser_download._run_playwright(
                    {
                        "url": "https://example.com/reports",
                        "visible": False,
                        "cookie_file": str(cookie),
                        "actions": [],
                    },
                    folder,
                )
            self.assertEqual(str(cookie_error.exception), "The cookie file could not be loaded.")
            self.assertNotIn("should-not-leak", str(cookie_error.exception))
            self.assertTrue(browser.headless)
        finally:
            browser_download.playwright_launcher = previous_launcher
            browser_download.CHECK_WAIT_SECONDS = previous_wait
            os.environ.pop("BROWSER_PASSWORD", None)

    def test_self_heal_fixes_python_and_blender_without_a_live_model(self) -> None:
        self.assertIn("self_heal_execution", gta5_agent.SYSTEM_PROMPT)
        self.assertIn("git push", gta5_agent.SYSTEM_PROMPT)
        workspace = self.root / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)
        script = workspace / "guard.py"
        script.write_text("print('hi')\n", encoding="utf-8")
        with self.assertRaises(AssertionError) as guarded:
            gta5_agent.self_heal.self_heal_execution(str(script))
        self.assertIn("real heal", str(guarded.exception))

        calls: list[list[str]] = []

        def runner(command: list[str], path: Path) -> dict[str, object]:
            self.assertIsInstance(command, list)
            self.assertEqual(command[0], sys.executable)
            self.assertEqual(command[1], str(path))
            calls.append(list(command))
            text = path.read_text(encoding="utf-8")
            if "fixed" in text:
                return {"returncode": 0, "stdout": "ok", "stderr": ""}
            return {
                "returncode": 1,
                "stdout": "",
                "stderr": "NameError: name 'value' is not defined",
            }

        gta5_agent.heal_runner_override = runner
        blocked = gta5_agent.invoke_tool(
            "self_heal_execution",
            {"script_path": r"C:\Windows\heal.py"},
        )
        self.assertFalse(blocked["ok"])
        self.assertEqual(calls, [])

        game = self.make_game()
        game_script = game / "bad.py"
        game_script.write_text("print(1)\n", encoding="utf-8")
        inside = gta5_agent.self_heal.self_heal_execution(str(game_script))
        self.assertFalse(inside["ok"])
        self.assertIn("game folder", inside["error"])
        self.assertEqual(calls, [])

        cracked = workspace / "cracked.py"
        cracked.write_text("print('fitgirl repack')\n", encoding="utf-8")
        piracy = gta5_agent.self_heal.self_heal_execution(str(cracked))
        self.assertFalse(piracy["ok"])
        self.assertIn("crack", piracy["error"].casefold())
        self.assertEqual(calls, [])

        previous_key = os.environ.get("GEMINI_API_KEY")
        secret = "AIzaSyTESTKEY1234567890abcd"
        os.environ["GEMINI_API_KEY"] = secret
        try:
            leaked = workspace / "leaked.py"
            leaked.write_text(f"print('{secret}')\n", encoding="utf-8")
            hidden = gta5_agent.self_heal.self_heal_execution(str(leaked))
            self.assertFalse(hidden["ok"])
            self.assertIn("API key", hidden["error"])
            self.assertEqual(calls, [])

            job = workspace / "job.py"
            job.write_text("print('start')\n", encoding="utf-8")

            def rewriter(source: str, error: str) -> str:
                self.assertIn("NameError", error)
                return "print('fixed')\n"

            gta5_agent.heal_rewriter_override = rewriter
            fixed = gta5_agent.invoke_tool("self_heal_execution", {"script_path": str(job)})
            self.assertTrue(fixed["ok"], fixed)
            self.assertEqual(fixed["status"], "ready")
            self.assertIn("Fixed and finished on attempt 2", fixed["message"])
            self.assertEqual(job.read_text(encoding="utf-8"), "print('fixed')\n")
            self.assertEqual(len(calls), 2)

            calls.clear()
            rewrites: list[str] = []

            def always_fail(command: list[str], path: Path) -> dict[str, object]:
                calls.append(list(command))
                return {"returncode": 1, "stdout": "", "stderr": "NameError: still broken"}

            def keep_rewriting(source: str, error: str) -> str:
                rewrites.append(error)
                return f"print({len(rewrites)!r})\n"

            gta5_agent.heal_runner_override = always_fail
            gta5_agent.heal_rewriter_override = keep_rewriting
            stopped = gta5_agent.self_heal.self_heal_execution(str(job))
            self.assertFalse(stopped["ok"])
            self.assertIn("Stopped after 3 attempts", stopped["error"])
            self.assertEqual(len(calls), 3)
            self.assertEqual(len(rewrites), 2)

            gta5_agent.heal_rewriter_override = _guard_rewriter
            with self.assertRaises(AssertionError) as live:
                gta5_agent.self_heal.self_heal_execution(str(job))
            self.assertIn("real gemini", str(live.exception))

            private = workspace / "private_job.py"
            private.write_text("print('hi')\n", encoding="utf-8")
            sent: list[dict[str, object]] = []

            def ollama_rewrite(payload: dict[str, object]) -> dict[str, object]:
                sent.append(payload)
                blob = json.dumps(payload)
                self.assertNotIn(secret, blob)
                self.assertIn("NameError", blob)
                self.assertIn("[redacted]", blob)
                return {"message": {"content": "print('fixed')\n"}}

            def private_runner(command: list[str], path: Path) -> dict[str, object]:
                if "fixed" in path.read_text(encoding="utf-8"):
                    return {"returncode": 0, "stdout": "ok", "stderr": ""}
                return {
                    "returncode": 1,
                    "stdout": "",
                    "stderr": f"NameError: missing {secret}",
                }

            gta5_agent.network_up_override = False
            gta5_agent.heal_rewriter_override = None
            gta5_agent.heal_runner_override = private_runner
            gta5_agent.ollama_transport_override = ollama_rewrite
            original_import = builtins.__import__

            def guarded_import(name: str, *args: object, **kwargs: object) -> object:
                if str(name).split(".")[0] == "google":
                    raise AssertionError("real gemini")
                return original_import(name, *args, **kwargs)

            with mock.patch("local_llm.socket.create_connection", side_effect=AssertionError("real socket")):
                with mock.patch("builtins.__import__", guarded_import):
                    healed = gta5_agent.self_heal.self_heal_execution(str(private))
            self.assertTrue(healed["ok"], healed)
            self.assertIn("Fixed and finished on attempt 2", healed["message"])
            self.assertEqual(len(sent), 1)
        finally:
            if previous_key is None:
                os.environ.pop("GEMINI_API_KEY", None)
            else:
                os.environ["GEMINI_API_KEY"] = previous_key

        mesh = "o Basket\nv 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n"
        cube = "import bpy\nbpy.ops.mesh.primitive_cube_add()\n"
        broken_script = "import bpy\nbpy.ops.mesh.primitive_basket_add()\n"
        notes: list[str] = []
        gta5_agent.blender_notify_override = notes.append
        gta5_agent.blender_executable_override = self.root / "blender.exe"
        gta5_agent.self_heal_enabled = False
        gta5_agent.network_up_override = True
        blender_calls: list[str] = []

        def fail_once(
            command: list[str],
            script_path: Path,
            output_path: Path,
        ) -> dict[str, object]:
            blender_calls.append(script_path.read_text(encoding="utf-8"))
            return {
                "returncode": 1,
                "stdout": "",
                "stderr": "AttributeError: primitive_basket_add",
            }

        gta5_agent.blender_runner_override = fail_once
        gta5_agent.begin_task_turn("Make a basket in Blender")
        once = gta5_agent.invoke_tool(
            "run_blender_task",
            {"script": broken_script, "output_path": str(workspace / "once.obj")},
        )
        self.assertFalse(once["ok"], once)
        self.assertEqual(once["status"], "failed")
        self.assertEqual(len(blender_calls), 1)

        gta5_agent.self_heal_enabled = True

        def heal_runner(
            command: list[str],
            script_path: Path,
            output_path: Path,
        ) -> dict[str, object]:
            text = script_path.read_text(encoding="utf-8")
            blender_calls.append(text)
            if "primitive_basket_add" in text:
                return {
                    "returncode": 1,
                    "stdout": "",
                    "stderr": "AttributeError: primitive_basket_add",
                }
            output_path.write_text(mesh, encoding="utf-8")
            return {"returncode": 0, "stdout": "export ok", "stderr": ""}

        def heal_rewriter(source: str, error: str) -> str:
            self.assertIn("primitive_basket_add", source)
            self.assertNotIn("save_as_mainfile", source)
            self.assertIn("AttributeError", error)
            return cube

        gta5_agent.blender_runner_override = heal_runner
        gta5_agent.heal_rewriter_override = heal_rewriter
        ready = gta5_agent.invoke_tool(
            "run_blender_task",
            {"script": broken_script, "output_path": str(workspace / "healed.obj")},
        )
        self.assertTrue(ready["ok"], ready)
        self.assertEqual(ready["status"], "ready")
        self.assertIn("Fixed and finished on attempt 2", ready["message"])
        self.assertTrue((workspace / "healed.obj").is_file())

        gta5_agent.heal_rewriter_override = None
        gta5_agent.network_up_override = False
        local_payloads: list[dict[str, object]] = []

        def local_fix(payload: dict[str, object]) -> dict[str, object]:
            local_payloads.append(payload)
            return {"message": {"content": cube}}

        gta5_agent.ollama_transport_override = local_fix
        offline = gta5_agent.invoke_tool(
            "run_blender_task",
            {"script": broken_script, "output_path": str(workspace / "offline.obj")},
        )
        self.assertTrue(offline["ok"], offline)
        self.assertEqual(offline["status"], "ready")
        self.assertGreaterEqual(len(local_payloads), 1)
        gta5_agent.blender_task.last_notice = None

    def test_mcp_router_uses_config_and_a_fake_transport(self) -> None:
        self.assertIn("mcp_router", gta5_agent.SYSTEM_PROMPT)
        self.assertIn("mcp_servers.json", gta5_agent.SYSTEM_PROMPT)
        missing = gta5_agent.invoke_tool("mcp_router", {"action": "list_servers"})
        self.assertTrue(missing["ok"], missing)
        self.assertEqual(missing["servers"], [])
        self.assertIn("mcp_servers.json", missing["message"])

        config = self.root / "workspace" / "mcp_servers.json"
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text("{", encoding="utf-8")
        gta5_agent.mcp_config_override = config
        unreadable = gta5_agent.mcp_router.mcp_router("list_servers")
        self.assertFalse(unreadable["ok"])
        self.assertIn("could not be read", unreadable["error"])

        config.write_text(
            json.dumps(
                {
                    "servers": {
                        "notes": {"command": "python", "args": ["-m", "notes_server"]},
                        "shell": {"command": "cmd & calc", "args": []},
                    }
                }
            ),
            encoding="utf-8",
        )
        listed = gta5_agent.invoke_tool("mcp_router", {"action": "list_servers"})
        self.assertTrue(listed["ok"], listed)
        self.assertEqual(listed["servers"], ["notes"])

        unknown = gta5_agent.mcp_router.mcp_router(
            "call",
            server="github",
            tool="query",
            arguments={"sql": "select 1"},
        )
        self.assertFalse(unknown["ok"])
        self.assertIn("Unknown MCP server", unknown["error"])

        shell = gta5_agent.mcp_router.mcp_router(
            "call",
            server="notes",
            tool="query",
            arguments="git push --force",
        )
        self.assertFalse(shell["ok"])
        self.assertIn("JSON object", shell["error"])
        empty_tool = gta5_agent.mcp_router.mcp_router(
            "call",
            server="notes",
            tool="",
            arguments={},
        )
        self.assertFalse(empty_tool["ok"])

        seen: list[tuple[str, str, dict[str, object]]] = []

        def transport(server: str, method: str, params: dict[str, object]) -> dict[str, object]:
            seen.append((server, method, params))
            if method == "tools/list":
                return {"tools": [{"name": "query", "description": "read rows"}]}
            if method == "tools/call":
                self.assertEqual(params["name"], "query")
                self.assertEqual(params["arguments"], {"sql": "select 1"})
                return {"content": [{"type": "text", "text": "1"}]}
            raise AssertionError(method)

        gta5_agent.mcp_transport_override = transport
        with mock.patch("subprocess.Popen", side_effect=AssertionError("real process")):
            tools = gta5_agent.invoke_tool("mcp_router", {"action": "list_tools", "server": "notes"})
            called = gta5_agent.mcp_router.mcp_router(
                "call",
                server="notes",
                tool="query",
                arguments='{"sql": "select 1"}',
            )
        self.assertTrue(tools["ok"], tools)
        self.assertEqual(tools["tools"], ["query"])
        self.assertTrue(called["ok"], called)
        self.assertIn("1", called["message"])
        self.assertEqual(seen[0][1], "tools/list")
        self.assertEqual(seen[1][1], "tools/call")

        gta5_agent.mcp_transport_override = _guard_mcp
        with self.assertRaises(AssertionError) as live:
            gta5_agent.mcp_router.mcp_router("list_tools", server="notes")
        self.assertIn("real mcp", str(live.exception))

    def test_private_or_offline_turn_stays_on_ollama(self) -> None:
        self.assertIn("Ollama", gta5_agent.SYSTEM_PROMPT)
        self.assertIn("llama3.2", gta5_agent.SYSTEM_PROMPT)
        self.assertFalse(gta5_agent.local_llm.use_local_first("is the export done?"))
        self.assertFalse(gta5_agent.local_llm.use_local_first("my password is hunter2"))
        self.assertTrue(gta5_agent.local_llm.use_local_first("keep this private"))
        self.assertTrue(gta5_agent.local_llm.use_local_first("please work offline today"))
        self.assertFalse(
            gta5_agent._request_needs_plan("keep this private and update my spreadsheet")
        )
        previous_key = os.environ.get("GEMINI_API_KEY")
        secret = "AIzaSyTESTKEY1234567890abcd"
        os.environ["GEMINI_API_KEY"] = secret
        sent: list[dict[str, object]] = []

        def transport(payload: dict[str, object]) -> dict[str, object]:
            sent.append(payload)
            if len(sent) == 1:
                return {
                    "message": {
                        "content": "",
                        "tool_calls": [
                            {"function": {"name": "blender_job_status", "arguments": {}}}
                        ],
                    }
                }
            return {"message": {"content": "Checked on this PC."}}

        original_import = builtins.__import__

        def guarded_import(name: str, *args: object, **kwargs: object) -> object:
            if str(name).split(".")[0] == "google":
                raise AssertionError("real gemini")
            return original_import(name, *args, **kwargs)

        try:
            gta5_agent.ollama_transport_override = transport
            with mock.patch("local_llm.socket.create_connection", side_effect=AssertionError("real socket")):
                with mock.patch("builtins.__import__", guarded_import):
                    private = gta5_agent.run_agent(
                        f"keep this private {secret}",
                        [],
                        "gemini-3.5-flash-lite",
                    )
            self.assertEqual(private, "Checked on this PC.")
            self.assertEqual(len(sent), 2)
            blob = json.dumps(sent)
            self.assertNotIn(secret, blob)
            self.assertIn("[redacted]", blob)
            roles = [item.get("role") for item in sent[1]["messages"]]  # type: ignore[index]
            self.assertIn("tool", roles)

            sent.clear()
            gta5_agent.ollama_transport_override = None
            gta5_agent.ollama_reachable_override = False
            gta5_agent.network_up_override = False
            with mock.patch("local_llm.socket.create_connection", side_effect=AssertionError("real socket")):
                with mock.patch("builtins.__import__", guarded_import):
                    offline = gta5_agent.run_agent("hello", [], "gemini-3.5-flash-lite")
            self.assertIn("Ollama is not running", offline)
            self.assertIn("not sent online", offline)

            os.environ["PRIVACY_MODE"] = "1"
            gta5_agent.network_up_override = True
            gta5_agent.ollama_transport_override = (
                lambda payload: {"message": {"content": "Private mode."}}
            )
            try:
                with mock.patch("builtins.__import__", guarded_import):
                    flagged = gta5_agent.run_agent("hello there", [], "gemini-3.5-flash-lite")
            finally:
                os.environ.pop("PRIVACY_MODE", None)
            self.assertEqual(flagged, "Private mode.")

            gemini_calls: list[str] = []

            class FakeModels:
                def generate_content(self, **kwargs: object) -> object:
                    gemini_calls.append("gemini")
                    part = types.SimpleNamespace(text="Checked on Gemini.", thought=False)
                    content = types.SimpleNamespace(parts=[part])
                    candidate = types.SimpleNamespace(content=content)
                    return types.SimpleNamespace(
                        candidates=[candidate],
                        function_calls=None,
                        text="Checked on Gemini.",
                    )

            class FakeClient:
                def __init__(self, api_key: str) -> None:
                    self.models = FakeModels()

            sent.clear()
            gta5_agent.network_up_override = True
            gta5_agent.ollama_transport_override = transport
            gta5_agent.genai_client_override = lambda api_key: FakeClient(api_key)
            online = gta5_agent.run_agent(
                "is the export done?",
                [],
                "gemini-3.5-flash-lite",
            )
            self.assertEqual(online, "Checked on Gemini.")
            self.assertEqual(gemini_calls, ["gemini"])
            self.assertEqual(sent, [])

            class DropModels:
                def generate_content(self, **kwargs: object) -> object:
                    raise ConnectionResetError("connection reset by peer")

            class DropClient:
                def __init__(self, api_key: str) -> None:
                    self.models = DropModels()

            sent.clear()
            gta5_agent.genai_client_override = lambda api_key: DropClient(api_key)

            def answer(payload: dict[str, object]) -> dict[str, object]:
                sent.append(payload)
                return {"message": {"content": "Answered on this PC."}}

            gta5_agent.ollama_transport_override = answer
            slept: list[float] = []
            with mock.patch("local_llm.socket.create_connection", side_effect=AssertionError("real socket")):
                with mock.patch("gta5_agent.time.sleep", side_effect=lambda seconds: slept.append(seconds)):
                    dropped = gta5_agent.run_agent(
                        "is the export done?",
                        [],
                        "gemini-3.5-flash-lite",
                    )
            self.assertEqual(dropped, "Answered on this PC.")
            self.assertEqual(slept, [2, 5, 12])
            self.assertEqual(len(sent), 1)
        finally:
            os.environ.pop("PRIVACY_MODE", None)
            if previous_key is None:
                os.environ.pop("GEMINI_API_KEY", None)
            else:
                os.environ["GEMINI_API_KEY"] = previous_key

    def test_audio_scribe_saves_notes_without_opening_the_microphone(self) -> None:
        self.assertIn("audio_scribe_tool", gta5_agent.SYSTEM_PROMPT)
        self.assertFalse(gta5_agent._request_needs_plan("record a voice note"))
        with self.assertRaises(AssertionError) as guarded:
            gta5_agent.audio_scribe.audio_scribe_tool(seconds=5)
        self.assertIn("real microphone", str(guarded.exception))

        seen: list[tuple[str, int]] = []

        def recorder(source: str, seconds: int, dest: Path) -> None:
            seen.append((source, seconds))
            dest.write_bytes(b"0123456789abcdef")

        def transcriber(path: Path) -> str:
            self.assertGreaterEqual(path.stat().st_size, 16)
            return "Today we covered hooks. Then we saved the file."

        gta5_agent.recorder_override = recorder
        gta5_agent.transcriber_override = transcriber
        note = self.root / "workspace" / "lecture.md"
        saved = gta5_agent.invoke_tool(
            "audio_scribe_tool",
            {"source": "system", "output_path": str(note)},
        )
        self.assertTrue(saved["ok"], saved)
        self.assertEqual(saved["status"], "ready")
        self.assertEqual(seen, [("system", 30)])
        self.assertEqual(
            note.read_text(encoding="utf-8"),
            "# Voice note\n\n- Today we covered hooks.\n- Then we saved the file.\n",
        )

        def empty_transcriber(path: Path) -> str:
            return "   "

        gta5_agent.transcriber_override = empty_transcriber
        empty_note = self.root / "workspace" / "empty.md"
        empty = gta5_agent.audio_scribe.audio_scribe_tool(
            seconds=5,
            output_path=str(empty_note),
        )
        self.assertFalse(empty["ok"])
        self.assertIn("No speech", empty["error"])
        self.assertFalse(empty_note.exists())

        recorded = len(seen)
        refused = gta5_agent.audio_scribe.audio_scribe_tool(seconds=900)
        self.assertFalse(refused["ok"])
        self.assertIn("600", refused["error"])
        zero = gta5_agent.audio_scribe.audio_scribe_tool(seconds=0)
        self.assertFalse(zero["ok"])
        self.assertEqual(len(seen), recorded)

        used: list[str] = []

        def file_recorder(source: str, seconds: int, dest: Path) -> None:
            used.append(source)
            raise AssertionError("real microphone")

        gta5_agent.recorder_override = file_recorder
        gta5_agent.transcriber_override = transcriber
        audio = self.root / "workspace" / "clip.wav"
        audio.write_bytes(b"0123456789abcdef")
        filed = gta5_agent.audio_scribe.audio_scribe_tool(
            source="file",
            audio_path=str(audio),
            output_path=str(self.root / "workspace" / "from-file.md"),
        )
        self.assertTrue(filed["ok"], filed)
        self.assertEqual(used, [])

        drive = self.root / "pedrodrive"
        drive.mkdir()
        gta5_agent._volumes = lambda: [(str(drive) + "\\", "GameDrive")]
        gta5_agent.recorder_override = recorder
        pedro = gta5_agent.audio_scribe.audio_scribe_tool(
            source="mic",
            seconds=12,
            output_path="GameDrive/notes/lecture.md",
        )
        self.assertTrue(pedro["ok"], pedro)
        self.assertTrue((drive / "notes" / "lecture.md").is_file())
        self.assertEqual(seen[-1], ("mic", 12))

        gta5_agent.recorder_override = recorder
        gta5_agent.transcriber_override = _guard_transcriber
        with self.assertRaises(AssertionError) as whisper_guard:
            gta5_agent.audio_scribe.audio_scribe_tool(
                seconds=5,
                output_path=str(self.root / "workspace" / "guard.md"),
            )
        self.assertIn("real whisper", str(whisper_guard.exception))

        gta5_agent.transcriber_override = None
        original_import = builtins.__import__

        def block_whisper(name: str, *args: object, **kwargs: object) -> object:
            root = str(name).split(".")[0]
            if root in {"whisper", "faster_whisper"}:
                raise ImportError("no whisper")
            return original_import(name, *args, **kwargs)

        with mock.patch("builtins.__import__", block_whisper):
            missing_model = gta5_agent.audio_scribe.audio_scribe_tool(
                seconds=5,
                output_path=str(self.root / "workspace" / "needs-whisper.md"),
            )
        self.assertFalse(missing_model["ok"])
        self.assertIn("openai-whisper", missing_model["error"])

    def run_chat(
        self,
        argv: list[str],
        lines: list[str],
        heard: list[dict[str, object]],
    ) -> tuple[int, list[str], list[str]]:
        prompts: list[str] = []
        spoken: list[str] = []
        pending = list(heard)

        def fake_run(text: str, history: list[object], model: str, **kwargs: object) -> str:
            prompts.append(text)
            return f"did:{text}"

        def fake_speak(text: str, engine: object = None) -> dict[str, object]:
            spoken.append(text)
            return {"ok": True, "text": text}

        def fake_listen(**kwargs: object) -> dict[str, object]:
            if not pending:
                return {"ok": False, "error": "No microphone is available."}
            return pending.pop(0)

        with (
            mock.patch.object(gta5_agent, "_watch_mode_keys", lambda pressed, stop: None),
            mock.patch.object(gta5_agent, "run_agent", side_effect=fake_run),
            mock.patch.object(gta5_agent, "speak_response", side_effect=fake_speak),
            mock.patch.object(
                gta5_agent, "listen_to_microphone", side_effect=fake_listen
            ),
            mock.patch("builtins.input", side_effect=lines),
        ):
            code = gta5_agent.main(argv)
        return code, prompts, spoken


    def test_idle_delegate_confirm_and_clipboard_stay_local(self) -> None:
        import clipboard_context
        import confirm_action
        import delegate_agent
        import idle_tasks

        with self.assertRaises(AssertionError) as idle_guard:
            gta5_agent.idle_seconds_override = 9999
            idle_tasks.run_idle_pass()
        self.assertIn("real idle", str(idle_guard.exception))
        seen: list[str] = []

        def runner(task: str) -> None:
            seen.append(task)
            if task == "reindex_files":
                gta5_agent.idle_seconds_override = 0

        gta5_agent.idle_task_seconds_override = 10
        gta5_agent.idle_seconds_override = 11
        gta5_agent.idle_runner_override = runner
        paused = idle_tasks.run_idle_pass()
        self.assertEqual(paused["status"], "paused")
        self.assertEqual(seen, ["reindex_files"])
        self.assertEqual(idle_tasks.idle_task_scheduler("status")["status"], "active")

        with self.assertRaises(AssertionError) as delegate_guard:
            delegate_agent.delegate_subagent("files", "find the notes")
        self.assertIn("real delegate", str(delegate_guard.exception))
        refused = delegate_agent.delegate_subagent(
            "system",
            "stop notepad",
            tool="kill_process",
            arguments={"process_name": "notepad"},
        )
        self.assertFalse(refused["ok"])
        self.assertIn("not", refused["error"].casefold())
        release = threading.Event()
        started: list[str] = []

        def slow(worker: str, task: str) -> dict[str, object]:
            started.append(worker)
            release.wait(2)
            return {"ok": True, "message": task}

        gta5_agent.delegate_runner_override = slow
        first = delegate_agent.delegate_subagent("blender", "status of the mesh")
        second = delegate_agent.delegate_subagent("files", "find notes")
        third = delegate_agent.delegate_subagent("system", "health")
        fourth = delegate_agent.delegate_subagent("files", "one more")
        self.assertEqual(first["status"], "started")
        self.assertEqual(len(started), 3)
        self.assertFalse(fourth["ok"])
        self.assertIn("Three workers", fourth["error"])
        release.set()
        deadline = time.time() + 2
        while time.time() < deadline and delegate_agent._inflight:
            time.sleep(0.02)
        self.assertEqual(delegate_agent._inflight, 0)
        gta5_agent.delegate_runner_override = lambda worker, task: {
            "ok": True,
            "message": f"{worker} finished {task}",
        }
        ready = delegate_agent.delegate_subagent("files", "find the blender notes")
        self.assertEqual(ready["status"], "ready")
        self.assertTrue(ready["ok"], ready)

        killed: list[dict[str, object]] = []

        def processes(kind: str, payload: dict[str, object] | None = None) -> list[object]:
            if kind == "list":
                return [{"pid": 10, "name": "notepad.exe"}]
            killed.append(dict(payload or {}))
            return []

        gta5_agent.process_override = processes
        gta5_agent.voice_mode_active = False
        blocked = gta5_agent.invoke_tool("kill_process", {"process_name": "notepad"})
        self.assertTrue(blocked.get("needs_confirmation"))
        self.assertEqual(killed, [])
        gta5_agent.begin_task_turn("yes")
        closed = gta5_agent.invoke_tool("kill_process", {"process_name": "notepad"})
        self.assertTrue(closed["ok"], closed)
        self.assertEqual(killed, [{"pid": 10, "name": "notepad.exe"}])
        spoken: list[str] = []
        gta5_agent.voice_mode_active = True
        gta5_agent.confirm_speaker_override = spoken.append
        gta5_agent.confirm_listener_override = lambda: "no"
        denied = gta5_agent.invoke_tool("kill_process", {"process_name": "notepad"})
        self.assertFalse(denied["ok"])
        self.assertFalse(denied.get("approved"))
        self.assertIn("Are you sure you want to execute", spoken[0])
        self.assertEqual(len(killed), 1)
        gta5_agent.confirm_listener_override = lambda: "yes"
        allowed = gta5_agent.invoke_tool("kill_process", {"process_name": "notepad"})
        self.assertTrue(allowed["ok"], allowed)
        gta5_agent.confirm_speaker_override = _guard_confirm_speak
        gta5_agent.voice_mode_active = True
        with self.assertRaises(AssertionError) as confirm_guard:
            confirm_action.confirm_sensitive_action("kill notepad")
        self.assertIn("real confirm", str(confirm_guard.exception))
        gta5_agent.voice_mode_active = False

        with self.assertRaises(AssertionError) as clip_guard:
            clipboard_context.read_clipboard_context()
        self.assertIn("real clipboard", str(clip_guard.exception))
        gta5_agent.clipboard_override = lambda: ""
        with self.assertRaises(AssertionError) as image_guard:
            clipboard_context.read_clipboard_context()
        self.assertIn("real clipboard image", str(image_guard.exception))
        gta5_agent.clipboard_image_override = lambda: None
        trace = "Traceback (most recent call last):\n  File \"a.py\", line 3\nNameError: missing\n"
        gta5_agent.clipboard_override = lambda: trace
        proposed = clipboard_context.clipboard_action_dispatcher()
        self.assertEqual(proposed["kind"], "traceback")
        self.assertFalse(proposed["executed"])
        self.assertIn("explain", proposed["proposal"].casefold())
        gta5_agent.clipboard_override = lambda: "https://example.com/report"
        linked = clipboard_context.clipboard_action_dispatcher()
        self.assertEqual(linked["kind"], "url")
        gta5_agent.clipboard_override = lambda: "name,amount\nhats,3\n"
        sheet = clipboard_context.clipboard_action_dispatcher()
        self.assertEqual(sheet["kind"], "csv")
        gta5_agent.clipboard_override = lambda: "def build():\n    return 1\n"
        code = clipboard_context.clipboard_action_dispatcher()
        self.assertEqual(code["kind"], "code")
        from PIL import Image

        frame = io.BytesIO()
        Image.new("RGB", (4, 4), (9, 8, 7)).save(frame, format="JPEG")
        jpeg = frame.getvalue()
        gta5_agent.clipboard_override = lambda: ""
        gta5_agent.clipboard_image_override = lambda: jpeg
        pictured = clipboard_context.read_clipboard_context()
        self.assertTrue(pictured["ok"], pictured)
        self.assertEqual(pictured["kind"], "image")
        self.assertTrue(pictured["_screenshot_bytes"].startswith(b"\xff\xd8"))
        self.assertIn("[giggles]", gta5_agent.SYSTEM_PROMPT)
        self.assertIn("HUGE", gta5_agent.SYSTEM_PROMPT)
        self.assertNotIn("elevenlabs", gta5_agent.SYSTEM_PROMPT.casefold())

    def test_desktop_network_webcam_and_diagnostics_stay_local(self) -> None:
        import desktop_automation
        import diagnostics
        import network_manager

        with self.assertRaises(AssertionError) as network_guard:
            network_manager.network_manager("status")
        self.assertIn("real network", str(network_guard.exception))
        commands: list[list[str]] = []

        def runner(command: list[str]) -> dict[str, object]:
            commands.append(list(command))
            return {"returncode": 0, "stdout": "ok", "stderr": ""}

        gta5_agent.network_runner_override = runner
        with mock.patch("network_manager.subprocess.run", side_effect=AssertionError("spawned")):
            status = network_manager.network_manager("status")
            listed = network_manager.network_manager("wifi_list")
            speed = network_manager.network_manager("speed")
            bad = network_manager.network_manager("wifi_connect", profile="Office & calc")
        self.assertTrue(status["ok"], status)
        self.assertEqual(commands[0], ["ipconfig"])
        self.assertEqual(commands[1], ["netsh", "wlan", "show", "profiles"])
        self.assertEqual(commands[2], ["speedtest", "--json"])
        self.assertFalse(bad["ok"])
        self.assertEqual(len(commands), 3)
        gta5_agent.network_runner_override = None
        with mock.patch("network_manager.shutil.which", return_value=None):
            missing = network_manager.network_manager("speed")
        self.assertIn("not installed", missing["error"].casefold())
        gta5_agent.network_runner_override = runner
        gta5_agent.voice_mode_active = False
        waiting = gta5_agent.invoke_tool(
            "network_manager",
            {"action": "wifi_connect", "profile": "Office"},
        )
        self.assertTrue(waiting.get("needs_confirmation"))
        self.assertEqual(len(commands), 3)
        gta5_agent.begin_task_turn("yes")
        connected = gta5_agent.invoke_tool(
            "network_manager",
            {"action": "wifi_connect", "profile": "Office"},
        )
        self.assertTrue(connected["ok"], connected)
        self.assertEqual(commands[-1], ["netsh", "wlan", "connect", "name=Office"])

        pressed: list[str] = []
        focused: list[str] = []
        started: list[str] = []
        gta5_agent.pointer_override = lambda kind, details: pressed.append(kind)
        gta5_agent.window_override = lambda kind, payload: focused.append(str((payload or {}).get("title")))
        gta5_agent._start_target = lambda target: started.append(str(target))
        gta5_agent.start_menu_override = self.root / "empty-start"
        too_many = desktop_automation.desktop_ui_automation(
            steps=[{"action": "press", "key": "enter"} for _ in range(9)]
        )
        self.assertFalse(too_many["ok"])
        self.assertEqual(pressed, [])
        ran = desktop_automation.desktop_ui_automation(
            app="notepad",
            window_title="Notes",
            steps=[{"action": "press", "key": "enter"}],
        )
        self.assertTrue(ran["ok"], ran)
        self.assertEqual(pressed, ["keys"])
        self.assertIn("Notes", focused)
        self.assertTrue(started)

        self.assertIs(gta5_agent.TOOLS["webcam_vision_tool"], gta5_agent.capture_webcam_image)
        description = next(
            item["description"]
            for item in gta5_agent.TOOL_DECLARATIONS
            if item["name"] == "webcam_vision_tool"
        )
        self.assertIn("desk", description.casefold())

        with self.assertRaises(AssertionError) as health_guard:
            diagnostics.system_diagnostics()
        self.assertIn("real diagnostics", str(health_guard.exception))

        def sample() -> dict[str, object]:
            return {
                "cpu_percent": 12,
                "ram_percent": 40,
                "ram_used_mb": 4000,
                "ram_total_mb": 10000,
                "processes": [{"name": "notepad.exe", "pid": 10, "rss_mb": 200}],
            }

        gta5_agent.diagnostics_override = sample
        with mock.patch("diagnostics.subprocess.run", side_effect=AssertionError("nvidia")):
            health = diagnostics.system_diagnostics()
        self.assertTrue(health["ok"], health)
        self.assertIn("notepad.exe", health["message"])
        self.assertIn("GPU stats are unavailable", health["message"])
        self.assertIn("does not close", health["message"])

    def test_rag_scheduler_clipboard_actions_and_macros(self) -> None:
        import routine_macros

        root = gta5_agent.search_root_override
        assert root is not None
        (root / "materials.py").write_text(
            "configured blender materials for the glass shader\n",
            encoding="utf-8",
        )
        (root / ".env").write_text("GEMINI_API_KEY=test-key-abc\n", encoding="utf-8")
        (root / "tool.exe").write_bytes(b"MZ")
        document = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            "<w:body><w:p><w:r><w:t>Specs: aluminum frame and 12 volt pack</w:t></w:r></w:p></w:body>"
            "</w:document>"
        )
        with zipfile.ZipFile(root / "project-notes.docx", "w") as archive:
            archive.writestr("word/document.xml", document)
        found = gta5_agent.invoke_tool(
            "file_content_rag_search",
            {"query": "Find the script where I configured Blender materials"},
        )
        self.assertTrue(found["ok"], found)
        self.assertEqual(found["engine"], "fts5")
        self.assertIn("not a cloud embedding model", found["message"].casefold())
        blob = json.dumps(found["matches"])
        self.assertIn("materials.py", blob)
        self.assertIn("blender", blob.casefold())
        self.assertNotIn("test-key-abc", blob)
        specs = gta5_agent.local_search.file_content_rag_search(
            "What are the specs listed in my project notes file?"
        )
        self.assertTrue(specs["ok"], specs)
        self.assertIn("aluminum", json.dumps(specs["matches"]).casefold())

        old = gta5_agent.task_schedule.schedule_background_task(
            "health_check",
            delay_minutes=5,
        )
        self.assertFalse(old["ok"])
        self.assertIn("organize_downloads, reindex_files, or remind", old["error"])
        game_copy = gta5_agent.task_schedule.job_scheduler(
            "full backup of the game",
            daily_at="02:00",
        )
        self.assertFalse(game_copy["ok"])
        self.assertIn("notes", game_copy["error"].casefold())
        moment = datetime(2026, 10, 11, 1, 0, 0).timestamp()
        clock = {"now": moment}
        gta5_agent.scheduler_clock = lambda: clock["now"]
        nightly = gta5_agent.task_schedule.job_scheduler(
            "remind",
            daily_at="02:00",
            message="check the notes",
        )
        self.assertTrue(nightly["ok"], nightly)
        self.assertIn("02:00", nightly["rule"])
        clock["now"] = datetime(2026, 10, 11, 2, 0, 0).timestamp()
        reminded = gta5_agent.task_schedule.run_due_tasks()
        self.assertTrue(reminded[0]["ok"], reminded)
        gta5_agent.diagnostics_override = lambda: {
            "cpu_percent": 3,
            "ram_percent": 10,
            "ram_used_mb": 100,
            "ram_total_mb": 1000,
            "processes": [],
        }
        health_job = gta5_agent.task_schedule.job_scheduler(
            "health_check",
            delay_minutes=1,
        )
        self.assertTrue(health_job["ok"], health_job)
        clock["now"] += 60
        checked = gta5_agent.task_schedule.run_due_tasks()
        self.assertIn("CPU", checked[0]["message"])
        from PIL import Image

        frame = io.BytesIO()
        Image.new("RGB", (8, 8), (2, 3, 4)).save(frame, format="PNG")
        png = frame.getvalue()
        shots = {"n": 0}

        def screenshot() -> dict[str, object]:
            shots["n"] += 1
            return {"png": png, "screen_width": 8, "screen_height": 8}

        sent: list[str] = []

        def transport(kind: str, payload: dict[str, object]) -> dict[str, object]:
            sent.append(kind)
            return {"ok": True, "result": {"photo": [{"file_id": "1"}]}}

        gta5_agent.screenshot_override = screenshot
        gta5_agent.remote_transport_override = transport
        os.environ["TELEGRAM_BOT_TOKEN"] = "test-token"
        os.environ["TELEGRAM_CHAT_ID"] = "1"
        photo_job = gta5_agent.task_schedule.job_scheduler(
            "screenshot_to_phone",
            delay_minutes=1,
        )
        self.assertTrue(photo_job["ok"], photo_job)
        clock["now"] += 60
        delivered = gta5_agent.task_schedule.run_due_tasks()
        self.assertTrue(delivered[0]["ok"], delivered)
        self.assertEqual(shots["n"], 1)
        self.assertIn("telegram_photo", sent)
        (root / "only-notes.txt").write_text("hello notes", encoding="utf-8")
        backup_job = gta5_agent.task_schedule.job_scheduler("backup", delay_minutes=1)
        self.assertTrue(backup_job["ok"], backup_job)
        clock["now"] += 60
        copied = gta5_agent.task_schedule.run_due_tasks()
        self.assertTrue(copied[0]["ok"], copied)
        backup_root = gta5_agent.WORKSPACE / "backups" / "notes"
        self.assertTrue((backup_root / "only-notes.txt").is_file())
        self.assertFalse(any(path.suffix == ".exe" for path in backup_root.rglob("*")))
        self.assertFalse(any(path.name == ".env" for path in backup_root.rglob("*")))

        focused: list[dict[str, object]] = []
        gta5_agent.window_override = lambda kind, payload: focused.append(dict(payload or {}))
        saved = routine_macros.routine_macro_engine(
            "save",
            "3D-Export",
            steps=[{"tool": "focus_window", "arguments": {"window_title": "Blender"}}],
        )
        self.assertTrue(saved["ok"], saved)
        played = routine_macros.routine_macro_engine("run", "3D-Export")
        self.assertTrue(played["ok"], played)
        self.assertEqual(focused[0]["title"], "Blender")
        secret = routine_macros.routine_macro_engine(
            "save",
            "nope",
            steps=[{"tool": "type_text", "arguments": {"text": "api_key=abc"}}],
        )
        self.assertFalse(secret["ok"])
        cracked = routine_macros.routine_macro_engine(
            "save",
            "crack",
            steps=[{"tool": "focus_window", "arguments": {"window_title": "fitgirl repack"}}],
        )
        self.assertFalse(cracked["ok"])
        routine_macros.note_tool("focus_window")
        recent = routine_macros.routine_macro_engine("recent")
        self.assertIn("focus_window", recent["tools"])

    def test_voice_checkin_waits_and_does_not_nag(self) -> None:
        import voice_checkin

        clock = {"now": 1_000.0}
        gta5_agent.scheduler_clock = lambda: clock["now"]
        voice_checkin.reset()
        gta5_agent.voice_mode_active = False
        gta5_agent.idle_seconds_override = 30 * 60
        self.assertIsNone(voice_checkin.maybe_check_in())
        spoken: list[str] = []
        gta5_agent.checkin_speaker_override = spoken.append
        gta5_agent.checkin_listener_override = lambda: "Yeah, I'm good, just thinking"
        gta5_agent.voice_mode_active = True
        gta5_agent.idle_seconds_override = 0
        self.assertIsNone(voice_checkin.maybe_check_in())
        self.assertEqual(spoken, [])
        gta5_agent.checkin_idle_minutes_override = 15
        gta5_agent.idle_seconds_override = 15 * 60
        self.assertIsNone(voice_checkin.maybe_check_in())
        clock["now"] += 15 * 60
        heard = voice_checkin.maybe_check_in()
        self.assertEqual(heard, "reply")
        self.assertIn(spoken[0], voice_checkin.PHRASES)
        self.assertEqual(spoken[1], voice_checkin.ACK)
        again = voice_checkin.maybe_check_in()
        self.assertIsNone(again)
        self.assertEqual(len(spoken), 2)
        gta5_agent.checkin_listener_override = lambda: ""
        clock["now"] += 15 * 60
        quiet = voice_checkin.maybe_check_in()
        self.assertEqual(quiet, "quiet")
        self.assertEqual(len(spoken), 3)
        nag = voice_checkin.maybe_check_in()
        self.assertIsNone(nag)
        self.assertEqual(len(spoken), 3)
        gta5_agent.idle_seconds_override = 0
        self.assertIsNone(voice_checkin.maybe_check_in())
        gta5_agent.idle_seconds_override = 15 * 60
        self.assertIsNone(voice_checkin.maybe_check_in())
        clock["now"] += 15 * 60
        gta5_agent.checkin_listener_override = lambda: "all good"
        follow = voice_checkin.maybe_check_in()
        self.assertEqual(follow, "reply")
        self.assertEqual(spoken[-1], voice_checkin.ACK)

    def test_expressive_voice_strips_tags_and_matches_mood(self) -> None:
        import emotion

        sample = "[giggles] Oh stop, that's hilarious! [laughs] I didn't see that coming."
        spoken_text = gta5_agent.clean_text_for_tts(sample)
        self.assertNotIn("[", spoken_text)
        self.assertNotIn("]", spoken_text)
        self.assertNotIn("giggles", spoken_text.casefold())
        self.assertNotIn("laughs", spoken_text.casefold())
        self.assertIn("He he he", spoken_text)
        self.assertIn("Ha ha ha", spoken_text)
        self.assertIn(
            "[laughs]",
            emotion.prepare_for_speech("[laughs] Hi", provider="elevenlabs"),
        )
        emotion.reset()
        self.assertEqual(
            gta5_agent.clean_text_for_tts("Wait... that is HUGE!"),
            "Wait... that is HUGE!",
        )
        self.assertEqual(emotion.current(), "excited")
        self.assertTrue(emotion.delivery()[0].startswith("+"))
        emotion.reset()
        self.assertEqual(gta5_agent.clean_text_for_tts("Wait... I think so."), "Wait... I think so.")
        self.assertEqual(emotion.current(), "pause")
        self.assertTrue(emotion.delivery()[0].startswith("-"))

        heard: list[str] = []

        def synthesize(text: str, destination: Path, voice: str) -> None:
            heard.append(text)
            destination.write_bytes(b"mp3")

        gta5_agent.begin_task_turn("Laugh for me")
        laugh = gta5_agent.speak_response(
            "[laughs] Here is one.",
            synthesizer=synthesize,
            player=lambda path: None,
        )
        self.assertTrue(laugh["ok"], laugh)
        self.assertIn("[laughs]", laugh["text"])
        self.assertNotIn("[", heard[0])
        self.assertIn("Ha ha ha", heard[0])
        self.assertEqual(laugh["emotion"], "laugh")
        self.assertTrue(str(laugh["rate"]).startswith("+"))
        gta5_agent.begin_task_turn("I feel awful and this is bad news")
        soft = gta5_agent.speak_response(
            "[softly] Oh, I'm so sorry. That really is tough.",
            synthesizer=synthesize,
            player=lambda path: None,
        )
        self.assertNotIn("[", heard[1])
        self.assertNotIn("softly", heard[1].casefold())
        self.assertIn("sorry", heard[1].casefold())
        self.assertEqual(soft["emotion"], "empathetic")
        self.assertTrue(str(soft["rate"]).startswith("-"))
        self.assertEqual(emotion.detect_emotion("Tell me a joke"), "laugh")
        self.assertEqual(emotion.detect_emotion("That joke was hilarious"), "cheerful")

    def test_array_tool_parameters_include_item_schemas(self) -> None:
        from google.genai import types as genai_types

        tool = genai_types.Tool(function_declarations=gta5_agent.TOOL_DECLARATIONS)
        missing: list[str] = []

        def walk(schema: object, path: str) -> None:
            if schema is None:
                return
            kind = getattr(schema, "type", None)
            kind_name = str(getattr(kind, "value", kind) or "").upper()
            if kind_name == "ARRAY" and getattr(schema, "items", None) is None:
                missing.append(path)
            properties = getattr(schema, "properties", None) or {}
            for key, child in properties.items():
                walk(child, f"{path}.{key}")
            items = getattr(schema, "items", None)
            if items is not None:
                walk(items, f"{path}[]")

        for index, declaration in enumerate(tool.function_declarations or []):
            walk(declaration.parameters, f"{index}:{declaration.name}")
        self.assertEqual(missing, [])
        names = [item.name for item in tool.function_declarations or []]
        self.assertEqual(names[48], "desktop_ui_automation")
        self.assertEqual(names[53], "routine_macro_engine")

    def test_bluetooth_headphones_play_without_opening_the_microphone(self) -> None:
        names = [
            "Headset (JBL TUNE510BT Hands-Free AG Audio)",
            "Headphones (JBL TUNE510BT Stereo)",
            "Speakers (Realtek High Definition Audio)",
        ]
        chosen = gta5_agent.preferred_output_device(names)
        self.assertEqual(chosen, "Headphones (JBL TUNE510BT Stereo)")
        self.assertTrue(gta5_agent.playback_should_skip_barge(names, chosen))
        speakers = ["Speakers (Realtek High Definition Audio)"]
        speaker = gta5_agent.preferred_output_device(speakers)
        self.assertEqual(speaker, "Speakers (Realtek High Definition Audio)")
        self.assertFalse(gta5_agent.playback_should_skip_barge(speakers, speaker))

        gta5_agent.audio_output_override = names
        gta5_agent._barge_skip_announced = False
        played: list[bool] = []

        def player(stop_event: threading.Event) -> None:
            played.append(True)

        def boom(*args: object, **kwargs: object) -> None:
            raise AssertionError("real microphone")

        with mock.patch.object(gta5_agent, "_collect_barge_from_microphone", boom):
            result = asyncio.run(
                gta5_agent._barge_during_playback(
                    self.root / "reply.mp3",
                    player=player,
                )
            )
        self.assertEqual(played, [True])
        self.assertFalse(result.get("interrupted"))

    def test_live_video_uses_overrides_instead_of_the_camera(self) -> None:
        import socket
        import urllib.error
        import urllib.request

        from PIL import Image

        bridge = gta5_agent.remote_bridge
        video = gta5_agent.live_video
        self.assertTrue(bridge.wants_pc_camera("/pc_camera"))
        self.assertTrue(bridge.wants_pc_camera("/pc_camera@desk_bot"))
        self.assertTrue(bridge.wants_pc_camera("Show me what your computer camera sees"))
        self.assertTrue(bridge.wants_pc_camera("Send live PC camera feed"))
        self.assertTrue(bridge.wants_pc_camera("What is your computer seeing?"))
        self.assertFalse(bridge.wants_pc_camera("What is your computer seeing on the spreadsheet?"))
        self.assertTrue(bridge.wants_phone_camera("/phone_camera"))
        self.assertTrue(bridge.wants_phone_camera("Look at me through my phone"))
        self.assertTrue(bridge.wants_phone_camera("Start phone video feed"))
        self.assertTrue(bridge.wants_phone_camera("Look at me live"))
        self.assertFalse(bridge.wants_phone_camera("look at me"))
        self.assertFalse(bridge.wants_phone_camera("look at me holding a cup"))
        self.assertTrue(bridge.wants_stop_camera("/stop_camera"))
        self.assertTrue(bridge.wants_stop_camera("stop the camera"))
        self.assertTrue(bridge.wants_stop_camera("stop live video"))
        self.assertFalse(bridge.wants_stop_camera("stop the camera and organize my files"))
        self.assertFalse(bridge.wants_pc_camera("show me my screen"))
        self.assertIn("stream_pc_camera", gta5_agent.SYSTEM_PROMPT)
        self.assertIn("stream_phone_camera", gta5_agent.SYSTEM_PROMPT)
        self.assertNotIn("stream_pc_camera", gta5_agent._PLAN_FREE_TOOLS)
        self.assertNotIn("stream_phone_camera", gta5_agent._PLAN_FREE_TOOLS)
        names = [item["name"] for item in gta5_agent.TOOL_DECLARATIONS]
        self.assertEqual(names[48], "desktop_ui_automation")
        self.assertEqual(names[53], "routine_macro_engine")
        self.assertLess(names.index("routine_macro_engine"), names.index("stream_pc_camera"))
        self.assertFalse(
            gta5_agent._request_needs_plan("Show me what your computer camera sees")
        )
        self.assertFalse(
            gta5_agent._request_needs_plan(
                "Go to this link, log in, and download the latest data report"
            )
        )
        gta5_agent.begin_task_turn("organize my folder and update my spreadsheet")
        blocked = gta5_agent.invoke_tool("stream_pc_camera", {"action": "start"})
        self.assertFalse(blocked["ok"])
        self.assertIn("create_task_plan", blocked["error"])
        gta5_agent.begin_task_turn("")
        refused = gta5_agent.invoke_tool(
            "stream_pc_camera",
            {"rtmp_url": "rtmp://evil.example/live", "stream_key": "secretkey12"},
        )
        self.assertFalse(refused["ok"])
        self.assertIn("Bad arguments", refused["error"])
        self.assertNotIn("secretkey12", json.dumps(refused))

        with self.assertRaises(AssertionError):
            video.stream_pc_camera(seconds=5)
        self.assertFalse(video._pc_on)
        self.assertIsNone(video._server)

        buffer = io.BytesIO()
        Image.new("RGB", (16, 16), (12, 34, 56)).save(buffer, format="JPEG")
        jpeg = buffer.getvalue()
        self.assertTrue(jpeg.startswith(b"\xff\xd8"))

        class FakeStdin:
            def __init__(self) -> None:
                self.chunks: list[bytes] = []

            def write(self, data: bytes) -> int:
                self.chunks.append(bytes(data))
                return len(data)

            def flush(self) -> None:
                return None

            def close(self) -> None:
                return None

        class FakeProc:
            def __init__(self, command: list[str]) -> None:
                self.command = command
                self.stdin = FakeStdin()
                self.returncode = None

            def poll(self) -> None:
                return None

            def wait(self, timeout: float | None = None) -> int:
                self.returncode = 0
                return 0

            def terminate(self) -> None:
                self.returncode = -1

            def kill(self) -> None:
                self.returncode = -9

        commands: list[list[str]] = []

        def fake_process(command: list[str]) -> FakeProc:
            self.assertIsInstance(command, list)
            commands.append(command)
            return FakeProc(command)

        sent: list[dict[str, object]] = []

        def transport(kind: str, payload: dict[str, object]) -> dict[str, object]:
            self.assertNotEqual(kind, "telegram_updates")
            sent.append({"kind": kind, "payload": payload})
            return {"ok": True}

        real_urlopen = urllib.request.urlopen

        def local_open(target: object, timeout: float = 15) -> object:
            url = str(getattr(target, "full_url", target))
            if "127.0.0.1" not in url:
                raise AssertionError("real network")
            return real_urlopen(target, timeout=timeout)

        gta5_agent.live_frame_override = lambda: jpeg
        gta5_agent.stream_process_override = fake_process
        gta5_agent.remote_transport_override = transport
        os.environ["TELEGRAM_BOT_TOKEN"] = "phone-token-value"
        os.environ["TELEGRAM_CHAT_ID"] = "42"
        try:
            with (
                mock.patch("subprocess.Popen", side_effect=AssertionError("real ffmpeg")),
                mock.patch("cv2.VideoCapture", side_effect=AssertionError("real webcam")),
                mock.patch("urllib.request.urlopen", side_effect=local_open),
            ):
                started = video.stream_pc_camera(seconds=30)
                self.assertTrue(started["ok"], started)
                self.assertFalse(started["rtmp"])
                self.assertFalse(started["mini_app"])
                self.assertIn("Mini Apps need", started["message"])
                self.assertTrue(started["telegram_sent"])
                self.assertEqual(commands, [])
                body = sent[0]["payload"]["body"]
                self.assertNotIn("reply_markup", body)
                self.assertIn("Mini Apps need", body["text"])
                self.assertNotIn("phone-token-value", json.dumps(body))
                page = f"http://127.0.0.1:{video._bound_port}/live/{video._token}/pc.jpg"
                with urllib.request.urlopen(page, timeout=2) as response:
                    shot = response.read()
                self.assertEqual(shot, jpeg)
                html_url = f"http://127.0.0.1:{video._bound_port}/live/{video._token}/pc"
                with urllib.request.urlopen(html_url, timeout=2) as response:
                    html = response.read().decode("utf-8")
                self.assertIn("Live PC Webcam", html)
                self.assertIn("pc.mjpg", html)
                looked = video.stream_pc_camera(action="look")
                self.assertTrue(looked["ok"], looked)
                self.assertEqual(looked["_screenshot_bytes"], jpeg)
                video.stop_live_feeds()
                self.assertIsNone(video._server)

                sent.clear()
                phone = video.stream_phone_camera(seconds=30)
                self.assertTrue(phone["ok"], phone)
                phone_page = f"http://127.0.0.1:{video._bound_port}/live/{video._token}/phone"
                with urllib.request.urlopen(phone_page, timeout=2) as response:
                    phone_html = response.read().decode("utf-8")
                self.assertIn("navigator.mediaDevices.getUserMedia", phone_html)
                self.assertIn("/phone/frame", phone_html)
                frame_url = f"http://127.0.0.1:{video._bound_port}/live/{video._token}/phone/frame"
                request = urllib.request.Request(
                    frame_url,
                    data=jpeg,
                    method="POST",
                    headers={"Content-Type": "image/jpeg"},
                )
                with urllib.request.urlopen(request, timeout=2) as response:
                    self.assertEqual(response.status, 200)
                seen = video.stream_phone_camera(action="look")
                self.assertTrue(seen["ok"], seen)
                self.assertEqual(seen["_screenshot_bytes"], jpeg)
                plain = urllib.request.Request(
                    frame_url,
                    data=b"this is not a jpeg file",
                    method="POST",
                )
                with self.assertRaises(urllib.error.HTTPError) as bad_image:
                    urllib.request.urlopen(plain, timeout=2)
                self.assertEqual(bad_image.exception.code, 400)
                bad_image.exception.close()
                wrong = frame_url.replace(video._token, "not-the-token-value")
                with self.assertRaises(urllib.error.HTTPError) as missing:
                    urllib.request.urlopen(
                        urllib.request.Request(wrong, data=jpeg, method="POST"),
                        timeout=2,
                    )
                self.assertEqual(missing.exception.code, 404)
                missing.exception.close()
                huge = socket.create_connection(("127.0.0.1", video._bound_port), timeout=2)
                huge.sendall(
                    (
                        f"POST /live/{video._token}/phone/frame HTTP/1.1\r\n"
                        "Host: 127.0.0.1\r\n"
                        f"Content-Length: {video.MAX_FRAME_BYTES + 1}\r\n"
                        "Connection: close\r\n\r\n"
                    ).encode("ascii")
                )
                rejected = huge.recv(80)
                huge.close()
                self.assertIn(b"413", rejected)
                self.assertEqual(video.stream_phone_camera(action="look")["_screenshot_bytes"], jpeg)
                video.stop_live_feeds()

                sent.clear()
                commands.clear()
                os.environ["TELEGRAM_RTMP_URL"] = "rtmp://live.example/live"
                os.environ["TELEGRAM_STREAM_KEY"] = "super-secret-key"
                os.environ["LIVE_PUBLIC_URL"] = "https://viewer.example"
                published = video.stream_pc_camera(seconds=30)
                self.assertTrue(published["ok"], published)
                self.assertTrue(published["rtmp"])
                self.assertTrue(published["mini_app"])
                self.assertNotIn("super-secret-key", json.dumps(published))
                self.assertNotIn("rtmp://live.example/live", json.dumps(published))
                self.assertIn("[redacted]", gta5_agent._scrub("failed super-secret-key"))
                self.assertEqual(len(commands), 1)
                self.assertEqual(commands[0][-3:], ["-f", "flv", "rtmp://live.example/live/super-secret-key"])
                self.assertNotIn("shell", commands[0])
                button = sent[-1]["payload"]["body"]["reply_markup"]["inline_keyboard"][0][0]
                self.assertEqual(button["text"], "📹 View Live PC Webcam")
                self.assertTrue(button["web_app"]["url"].startswith("https://viewer.example/live/"))
                self.assertNotIn("super-secret-key", json.dumps(sent[-1]["payload"]))
                video.stop_live_feeds()

                sent.clear()
                os.environ["LIVE_PUBLIC_URL"] = "http://viewer.example"
                os.environ.pop("TELEGRAM_RTMP_URL", None)
                os.environ.pop("TELEGRAM_STREAM_KEY", None)
                linked = video.stream_phone_camera(seconds=30)
                self.assertTrue(linked["ok"], linked)
                self.assertFalse(linked["mini_app"])
                self.assertIn("Mini Apps need", linked["message"])
                self.assertNotIn("reply_markup", sent[-1]["payload"]["body"])
                video.stop_live_feeds()

                os.environ["TELEGRAM_RTMP_URL"] = "https://evil.example/live"
                os.environ["TELEGRAM_STREAM_KEY"] = "super-secret-key"
                commands.clear()
                rejected_target = video.stream_pc_camera(seconds=30)
                self.assertFalse(rejected_target["ok"])
                self.assertEqual(commands, [])
                self.assertNotIn("super-secret-key", json.dumps(rejected_target))
                self.assertIsNone(video._server)

                replies: list[str] = []

                def reply(text: str) -> str:
                    replies.append(text)
                    return "One look is a single frame."

                gta5_agent.remote_reply_override = reply
                gta5_agent.live_frame_override = lambda: jpeg

                def updates(kind: str, payload: dict[str, object]) -> dict[str, object]:
                    if kind == "telegram_updates":
                        return {
                            "result": [
                                {
                                    "update_id": 3,
                                    "message": {
                                        "chat": {"id": 42},
                                        "text": "/pc_camera",
                                    },
                                },
                                {
                                    "update_id": 4,
                                    "message": {
                                        "chat": {"id": 42},
                                        "text": "look at me",
                                    },
                                },
                                {
                                    "update_id": 5,
                                    "message": {
                                        "chat": {"id": 99},
                                        "text": "/phone_camera",
                                    },
                                },
                            ]
                        }
                    return transport(kind, payload)

                os.environ.pop("TELEGRAM_RTMP_URL", None)
                os.environ.pop("TELEGRAM_STREAM_KEY", None)
                os.environ.pop("LIVE_PUBLIC_URL", None)
                sent.clear()
                gta5_agent.remote_transport_override = updates
                checked = bridge.poll_once()
                self.assertTrue(checked["ok"], checked)
                self.assertEqual(checked["replied"], 2)
                self.assertEqual(replies, ["look at me"])
                self.assertTrue(video._pc_on)
                self.assertFalse(video._phone_on)
                self.assertFalse(any(item["kind"] == "telegram_updates" for item in sent))
                video.stop_live_feeds()
        finally:
            os.environ.pop("TELEGRAM_RTMP_URL", None)
            os.environ.pop("TELEGRAM_STREAM_KEY", None)
            os.environ.pop("LIVE_PUBLIC_URL", None)
            os.environ.pop("TELEGRAM_BOT_TOKEN", None)
            os.environ.pop("TELEGRAM_CHAT_ID", None)
            video.stop_live_feeds()

    def test_gmail_sends_an_address_and_looks_up_a_name(self) -> None:
        mail = gta5_agent.gmail_mail
        contacts = [
            {"name": "John Doe", "email": "john.doe@example.com"},
            {"name": "John Smith", "email": "john.smith@example.com"},
            {"name": "Sarah", "email": "sarah@example.com"},
        ]
        gta5_agent.contacts_override = contacts
        sent: list[dict[str, object]] = []

        def transport(payload: dict[str, object]) -> dict[str, object]:
            self.assertNotIn("password", payload)
            self.assertNotIn("app-password-value", json.dumps(payload))
            sent.append(payload)
            return {"ok": True}

        gta5_agent.gmail_transport_override = transport
        os.environ["GMAIL_ADDRESS"] = "owner@example.com"
        os.environ["GMAIL_APP_PASSWORD"] = "app-password-value"
        try:
            with mock.patch("smtplib.SMTP", side_effect=AssertionError("real email")):
                direct = mail.gmail_send_message(
                    request="Send an email to john.doe@example.com saying the report is ready"
                )
                self.assertTrue(direct["ok"], direct)
                self.assertEqual(direct["message"], "Email successfully sent to john.doe@example.com.")
                self.assertEqual(sent[0]["to"], "john.doe@example.com")
                self.assertEqual(sent[0]["subject"], "The report is ready")
                self.assertEqual(sent[0]["body"], "the report is ready")
                self.assertNotIn("app-password-value", json.dumps(direct))

                sent.clear()
                named = mail.gmail_send_message(to="Sarah", body="hello there")
                self.assertTrue(named["ok"], named)
                self.assertEqual(named["to"], "sarah@example.com")
                self.assertEqual(named["subject"], "Hello there")
                self.assertEqual(len(sent), 1)

                sent.clear()
                many = mail.gmail_send_message(to="John", body="which John")
                self.assertFalse(many["ok"])
                self.assertTrue(many["needs_clarification"])
                self.assertEqual(len(many["matches"]), 2)
                self.assertEqual(sent, [])
                found = mail.people_contact_search("John")
                self.assertFalse(found["ok"])
                self.assertEqual(len(found["matches"]), 2)

                sent.clear()
                invalid = mail.gmail_send_message(to="john.doe@example.com\nBcc: other@evil.test", body="hi")
                self.assertFalse(invalid["ok"])
                self.assertTrue(invalid["needs_clarification"])
                self.assertEqual(sent, [])
                missing_name = mail.gmail_send_message(to="Alex", body="hi")
                self.assertFalse(missing_name["ok"])
                self.assertIn("could not find", missing_name["error"])
                self.assertEqual(sent, [])
                both = mail.gmail_send_message(
                    request="Send an email to a@b.co and c@d.co saying hi"
                )
                self.assertFalse(both["ok"])
                self.assertTrue(both["needs_clarification"])
                self.assertEqual(sent, [])

                secret = mail.gmail_send_message(
                    to="sarah@example.com",
                    body="the password is app-password-value",
                )
                self.assertFalse(secret["ok"])
                self.assertIn("saved secret", secret["error"])
                self.assertEqual(sent, [])
                self.assertIn("[redacted]", gta5_agent._scrub("app-password-value"))

                gta5_agent.begin_task_turn("Send an email to Sarah and update my spreadsheet")
                blocked = gta5_agent.invoke_tool(
                    "gmail_send_message",
                    {"to": "Sarah", "body": "hello"},
                )
                self.assertFalse(blocked["ok"])
                self.assertIn("create_task_plan", blocked["error"])
                self.assertEqual(sent, [])
                gta5_agent.begin_task_turn("Send an email to sarah@example.com saying hello")
                self.assertFalse(gta5_agent._request_needs_plan(gta5_agent._turn_request))
                self.assertFalse(
                    gta5_agent._request_needs_plan(
                        "Go to this link, log in, and download the latest data report"
                    )
                )
                refused = gta5_agent.invoke_tool(
                    "gmail_send_message",
                    {"to": "sarah@example.com", "body": "hi", "app_password": "app-password-value"},
                )
                self.assertFalse(refused["ok"])
                self.assertIn("Bad arguments", refused["error"])
                names = [item["name"] for item in gta5_agent.TOOL_DECLARATIONS]
                self.assertEqual(names[48], "desktop_ui_automation")
                self.assertEqual(names[53], "routine_macro_engine")
                self.assertNotIn("gmail_send_message", gta5_agent._PLAN_FREE_TOOLS)
                self.assertIn("gmail_send_message", gta5_agent.SYSTEM_PROMPT)
                self.assertIn("people_contact_search", gta5_agent.SYSTEM_PROMPT)

                gta5_agent.gmail_transport_override = None
                os.environ.pop("GMAIL_ADDRESS", None)
                os.environ.pop("GMAIL_APP_PASSWORD", None)
                quiet = mail.gmail_send_message(to="sarah@example.com", body="hi")
                self.assertFalse(quiet["ok"])
                self.assertIn("not set up", quiet["error"])
                self.assertEqual(sent, [])
        finally:
            os.environ.pop("GMAIL_ADDRESS", None)
            os.environ.pop("GMAIL_APP_PASSWORD", None)

    def test_telegram_voice_notes_run_without_a_chat_reply(self) -> None:
        bridge = gta5_agent.remote_bridge
        token = "phone-token-value"
        hook = "https://discord.com/api/webhooks/9/phone-hook-value"
        os.environ["TELEGRAM_BOT_TOKEN"] = token
        os.environ["TELEGRAM_CHAT_ID"] = "42"
        os.environ["DISCORD_WEBHOOK_URL"] = hook
        ogg = b"OggS" + b"\x00" * 20
        seen: list[tuple[str, dict[str, object]]] = []
        queue: list[list[dict[str, object]]] = []
        heard: list[str] = []
        file_path = "voice/file_15.ogg"
        reaction_error = {"on": False}

        def transport(kind: str, payload: dict[str, object]) -> dict[str, object]:
            public = {key: value for key, value in payload.items() if key != "data"}
            encoded = json.dumps(public)
            self.assertNotIn(token, encoded)
            self.assertNotIn(hook, encoded)
            seen.append((kind, payload))
            if kind == "telegram_updates":
                return {"result": queue.pop(0) if queue else []}
            if kind == "telegram_file":
                return {"ok": True, "result": {"file_path": file_path, "file_size": len(ogg)}}
            if kind == "telegram_download":
                return {"ok": True, "data": ogg}
            if kind == "telegram_reaction" and reaction_error["on"]:
                raise RuntimeError("REACTION_INVALID")
            return {"ok": True}

        def voice_message(
            update_id: int,
            chat_id: int = 42,
            caption: str = "please reply in the chat",
            duration: int = 3,
            file_id: str = "AwACAgIAAxkBVoiceNote01",
            message_id: int = 15,
        ) -> dict[str, object]:
            return {
                "update_id": update_id,
                "message": {
                    "message_id": message_id,
                    "chat": {"id": chat_id},
                    "text": caption,
                    "voice": {
                        "file_id": file_id,
                        "duration": duration,
                        "mime_type": "audio/ogg",
                        "file_size": len(ogg),
                    },
                },
            }

        def poll(batch: list[dict[str, object]]) -> dict[str, object]:
            bridge.reset_remote_bridge()
            seen.clear()
            queue[:] = [batch]
            with mock.patch("urllib.request.urlopen", side_effect=AssertionError("real network")):
                with mock.patch("urllib.request.build_opener", side_effect=AssertionError("real network")):
                    return bridge.poll_once()

        gta5_agent.remote_transport_override = transport
        gta5_agent.telegram_voice_transcriber_override = lambda data: (
            "send an email to sarah@example.com saying the report is ready"
            if data.startswith(b"OggS")
            else ""
        )
        ran: list[str] = []

        def fake_run(user_text: str, history: list[object], model: str, **kwargs: object) -> str:
            ran.append(user_text)
            return "This reply must not be sent."

        with mock.patch.object(gta5_agent, "run_agent", side_effect=fake_run):
            checked = poll([voice_message(11)])
        self.assertTrue(checked["ok"], checked)
        self.assertEqual(checked["replied"], 0)
        self.assertEqual(checked["voice"], 1)
        self.assertEqual(ran, ["send an email to sarah@example.com saying the report is ready"])
        kinds = [item[0] for item in seen]
        self.assertEqual(kinds, ["telegram_updates", "telegram_file", "telegram_download"])
        self.assertNotIn("telegram_send", kinds)
        dumped = json.dumps([item[1] for item in seen])
        self.assertNotIn("This reply must not be sent.", dumped)
        self.assertNotIn("please reply in the chat", dumped)
        self.assertIn("voice note", gta5_agent.SYSTEM_PROMPT.casefold())

        os.environ["TELEGRAM_VOICE_REACTION"] = "👍"
        with mock.patch.object(gta5_agent, "run_agent", side_effect=fake_run):
            reacted = poll([voice_message(12)])
        self.assertEqual(reacted["voice"], 1)
        self.assertEqual(seen[3][0], "telegram_reaction")
        self.assertEqual(seen[3][1]["body"]["reaction"], [{"type": "emoji", "emoji": "👍"}])
        self.assertNotIn("telegram_send", [item[0] for item in seen])

        os.environ["TELEGRAM_VOICE_REACTION"] = "hello"
        ran.clear()
        with mock.patch.object(gta5_agent, "run_agent", side_effect=fake_run):
            quiet = poll([voice_message(13)])
        self.assertEqual(quiet["voice"], 1)
        self.assertEqual(ran, ["send an email to sarah@example.com saying the report is ready"])
        self.assertNotIn("telegram_reaction", [item[0] for item in seen])
        self.assertNotIn("telegram_send", [item[0] for item in seen])

        os.environ["TELEGRAM_VOICE_REACTION"] = "👍"
        reaction_error["on"] = True
        ran.clear()
        with mock.patch.object(gta5_agent, "run_agent", side_effect=fake_run):
            with mock.patch("builtins.print"):
                failed_react = poll([voice_message(14)])
        self.assertEqual(failed_react["voice"], 1)
        self.assertEqual(len(ran), 1)
        self.assertIn("telegram_reaction", [item[0] for item in seen])
        self.assertNotIn("telegram_send", [item[0] for item in seen])
        reaction_error["on"] = False
        os.environ.pop("TELEGRAM_VOICE_REACTION", None)

        def remember(text: str) -> str:
            heard.append(text)
            return f"reply:{text}"

        gta5_agent.remote_reply_override = remember
        mixed = poll(
            [
                voice_message(15),
                {
                    "update_id": 16,
                    "message": {"message_id": 16, "chat": {"id": 42}, "text": "is the export done?"},
                },
            ]
        )
        self.assertEqual(mixed["replied"], 1)
        self.assertEqual(mixed["voice"], 1)
        self.assertEqual(
            heard,
            [
                "send an email to sarah@example.com saying the report is ready",
                "is the export done?",
            ],
        )
        sends = [item for item in seen if item[0] == "telegram_send"]
        self.assertEqual(len(sends), 1)
        self.assertEqual(sends[0][1]["body"]["text"], "reply:is the export done?")
        self.assertNotIn("reply:send an email", json.dumps(sends))

        ignored = poll([voice_message(17, chat_id=99)])
        self.assertEqual(ignored["voice"], 0)
        self.assertEqual(ignored["replied"], 0)
        self.assertEqual([item[0] for item in seen], ["telegram_updates"])

        file_path = "voice/../../.env"
        rejected = poll([voice_message(18)])
        self.assertEqual(rejected["voice"], 0)
        self.assertEqual([item[0] for item in seen], ["telegram_updates", "telegram_file"])
        self.assertNotIn("telegram_download", [item[0] for item in seen])
        self.assertNotIn("telegram_send", [item[0] for item in seen])
        file_path = "voice/file_15.ogg"

        saved_download = transport

        def bad_audio(kind: str, payload: dict[str, object]) -> dict[str, object]:
            if kind == "telegram_download":
                seen.append((kind, payload))
                return {"ok": True, "data": b"not-an-ogg-file!!!!"}
            return saved_download(kind, payload)

        gta5_agent.remote_transport_override = bad_audio
        heard.clear()
        not_ogg = poll([voice_message(19)])
        self.assertEqual(not_ogg["voice"], 0)
        self.assertEqual(heard, [])
        self.assertNotIn("telegram_send", [item[0] for item in seen])
        gta5_agent.remote_transport_override = transport

        too_long = poll([voice_message(20, duration=601)])
        self.assertEqual(too_long["voice"], 0)
        self.assertEqual([item[0] for item in seen], ["telegram_updates"])

        gta5_agent.telegram_voice_transcriber_override = lambda data: "..."
        heard.clear()
        silent = poll([voice_message(21)])
        self.assertEqual(silent["voice"], 0)
        self.assertEqual(heard, [])
        self.assertNotIn("telegram_send", [item[0] for item in seen])

        class _Part:
            def __init__(self, text: str) -> None:
                self.text = text
                self.thought = False

        class _Content:
            def __init__(self, text: str) -> None:
                self.parts = [_Part(text)]

        class _Candidate:
            def __init__(self, text: str) -> None:
                self.content = _Content(text)

        class _Response:
            def __init__(self, text: str) -> None:
                self.candidates = [_Candidate(text)]

        class _Models:
            def __init__(self) -> None:
                self.calls: list[dict[str, object]] = []

            def generate_content(self, **kwargs: object) -> _Response:
                self.calls.append(kwargs)
                return _Response("launch the background render")

        class _Client:
            def __init__(self, api_key: str) -> None:
                self.api_key = api_key
                self.models = _Models()

        holder: dict[str, _Client] = {}

        def client_factory(api_key: str) -> _Client:
            client = _Client(api_key)
            holder["client"] = client
            return client

        saved_key = os.environ.get("GEMINI_API_KEY")
        os.environ["GEMINI_API_KEY"] = "gemini-test-key"
        gta5_agent.telegram_voice_transcriber_override = None
        gta5_agent.remote_reply_override = None
        gta5_agent.genai_client_override = client_factory
        ran.clear()
        try:
            with mock.patch.object(bridge, "_local_whisper_text", return_value=None):
                with mock.patch.object(gta5_agent, "run_agent", side_effect=fake_run):
                    gemini = poll([voice_message(22)])
            self.assertEqual(gemini["voice"], 1)
            self.assertEqual(ran, ["launch the background render"])
            self.assertNotIn("telegram_send", [item[0] for item in seen])
            client = holder["client"]
            self.assertEqual(client.api_key, "gemini-test-key")
            contents = client.models.calls[0]["contents"]
            self.assertEqual(contents[1], "Transcribe this voice note. Return only the spoken words.")
            self.assertNotIn("gemini-test-key", json.dumps([item[1] for item in seen]))

            os.environ["PRIVACY_MODE"] = "1"
            ran.clear()
            with mock.patch.object(bridge, "_local_whisper_text", return_value=None):
                with mock.patch.object(gta5_agent, "run_agent", side_effect=fake_run):
                    private = poll([voice_message(23)])
            self.assertEqual(private["voice"], 0)
            self.assertEqual(ran, [])
            self.assertEqual(len(client.models.calls), 1)
            self.assertNotIn("telegram_send", [item[0] for item in seen])
        finally:
            os.environ.pop("PRIVACY_MODE", None)
            if saved_key is None:
                os.environ.pop("GEMINI_API_KEY", None)
            else:
                os.environ["GEMINI_API_KEY"] = saved_key
            gta5_agent.genai_client_override = _guard_genai

        fake_whisper = types.ModuleType("whisper")

        class _WhisperModel:
            def transcribe(self, path: str) -> dict[str, str]:
                raw = Path(path).read_bytes()
                self.raw = raw
                return {"text": "start the render"}

        def load_model(name: str) -> _WhisperModel:
            self.assertEqual(name, "base")
            return _WhisperModel()

        fake_whisper.load_model = load_model
        with mock.patch.dict(sys.modules, {"whisper": fake_whisper}):
            local = bridge._local_whisper_text(ogg)
        self.assertEqual(local, "start the render")
        self.assertFalse(list((gta5_agent.WORKSPACE / "scribe").glob("telegram-voice-*.ogg")))

        gta5_agent.remote_transport_override = None
        started = threading.Event()

        def fake_answer(text: str) -> str:
            self.assertEqual(text, "do the render")
            started.set()
            return "hidden reply"
        with mock.patch.object(bridge, "_answer", fake_answer):
            bridge._dispatch_voice_command("do the render")
            self.assertTrue(started.wait(2))

    def test_checkout_uses_env_paths_and_keeps_secrets_out_of_source(self) -> None:
        import agent_config

        example = (gta5_agent.APP_DIR / ".env.example").read_text(encoding="utf-8")
        self.assertNotIn("C:\\Users\\", example)
        self.assertNotIn("GameDrive", example)
        self.assertNotIn("Pedro", example)
        self.assertIn("GEMINI_API_KEY=\n", example)
        self.assertIn("ELEVENLABS_API_KEY=\n", example)
        self.assertIn("TELEGRAM_BOT_TOKEN=\n", example)
        self.assertIn("TELEGRAM_CHAT_ID=\n", example)
        self.assertIn("STORAGE_DIR=./storage\n", example)
        self.assertIn("EXTERNAL_DRIVE_PATH=\n", example)
        self.assertNotIn("AIza", example)
        self.assertNotIn("pedro", gta5_agent.SYSTEM_PROMPT.casefold())
        self.assertNotIn("elevenlabs", gta5_agent.SYSTEM_PROMPT.casefold())
        requirements = (gta5_agent.APP_DIR / "requirements.txt").read_text(encoding="utf-8")
        self.assertIn("python-dotenv", requirements)
        self.assertNotIn("\nelevenlabs", requirements.casefold())
        root = self.root / "fresh"
        made = agent_config.prepare_checkout(root)
        for name in ("logs", "data", "temp", "storage"):
            self.assertTrue((root / name).is_dir(), name)
        self.assertGreaterEqual(len(made["folders"]), 4)
        with mock.patch.dict(
            os.environ,
            {"GEMINI_API_KEY": "", "PRIVACY_MODE": "", "LOCAL_LLM": ""},
        ):
            self.assertEqual(agent_config.missing_settings(), ["GEMINI_API_KEY"])
        with mock.patch.dict(os.environ, {"PRIVACY_MODE": "1", "GEMINI_API_KEY": ""}):
            self.assertEqual(agent_config.missing_settings(), [])
        self.assertEqual(
            agent_config.split_drive_prefix("GameDrive/reports/sales.xlsx"),
            ("GameDrive", "reports/sales.xlsx"),
        )
        self.assertIsNone(agent_config.split_drive_prefix(r"C:\Users\someone\notes.txt"))
        blocked = gta5_agent.main(["--help"])
        self.assertEqual(blocked, 0)


def _voice_text(text: str, thought: bool = False) -> object:
    return types.SimpleNamespace(
        text=text,
        thought=thought,
        function_call=None,
        thought_signature=None,
    )


def _voice_call(name: str, args: dict[str, object], call_id: str) -> object:
    call = types.SimpleNamespace(name=name, args=args, id=call_id)
    return types.SimpleNamespace(
        text=None,
        thought=False,
        function_call=call,
        thought_signature=None,
    )



def _voice_chunk(*parts: object) -> object:
    content = types.SimpleNamespace(parts=list(parts))
    candidate = types.SimpleNamespace(content=content)
    return types.SimpleNamespace(candidates=[candidate], text=None)


def _pcm_frame(amplitude: int) -> bytes:
    sample = max(-32767, min(32767, amplitude))
    return struct.pack("<480h", *([sample] * 480))


def _missing_whisper() -> object:
    raise ImportError("no whisper")


def _whisper_must_not_run() -> object:
    raise AssertionError("Whisper should stay unused when Google returns text")


def _speech_module(
    google_text: str = "Open Excel",
    google: str = "ok",
    listen: str = "ok",
    microphone: str = "ok",
) -> type:
    class WaitTimeoutError(Exception):
        pass

    class UnknownValueError(Exception):
        pass

    class RequestError(Exception):
        pass

    class Microphone:
        def __init__(self) -> None:
            if microphone == "missing":
                raise OSError("No Default Input Device")
            if microphone == "pyaudio":
                raise AttributeError("Could not find PyAudio; check installation")

        def __enter__(self) -> object:
            return object()

        def __exit__(self, exc_type: object, exc: object, tb: object) -> bool:
            return False

    class Recognizer:
        def adjust_for_ambient_noise(self, source: object, duration: float = 0.3) -> None:
            return None

        def listen(
            self,
            source: object,
            timeout: float = 8,
            phrase_time_limit: float = 20,
        ) -> bytes:
            if listen == "timeout":
                raise WaitTimeoutError()
            return b"audio"

        def recognize_google(self, audio: object, language: str = "en-US") -> str:
            if google == "unknown":
                raise UnknownValueError()
            if google == "request":
                raise RequestError("offline")
            return google_text

        def recognize_whisper(self, audio: object) -> str:
            return "Open Excel"

    class SpeechModule:
        pass

    SpeechModule.WaitTimeoutError = WaitTimeoutError
    SpeechModule.UnknownValueError = UnknownValueError
    SpeechModule.RequestError = RequestError
    SpeechModule.Microphone = Microphone
    SpeechModule.Recognizer = Recognizer
    return SpeechModule


if __name__ == "__main__":
    unittest.main()
