"""Local Gemini agent that installs single-player GTA V mods.

The model picks a tool. This process runs that tool and sends the result back.
Writes stay inside the folder that contains GTA5.exe. Downloaded files are
never executed, and executables in the game folder are never replaced.

Interactive input is typed or spoken. A transcript is sent through the same
tool loop as typed text. In voice mode the first sentence is spoken while
the rest of the reply is still arriving. Speaking over the audio stops it.
The microphone and speaker are not model tools.

Desktop tools can capture this screen and move the pointer on this PC.
Click coordinates are a 0-1000 grid over the physical screen. Moving the
pointer to a screen corner stops the current action. The webcam opens for
one frame when capture_webcam_image runs, and for a live feed only when
stream_pc_camera or stream_phone_camera is asked for. The clipboard is
read only when get_clipboard_text runs. A request with several different
jobs gets a numbered plan before those tools run. A wake-word listener,
An external-drive file index, window controls, and a task scheduler can run beside
the chat loop. The scheduler does not launch scripts or programs.
A phone bridge, ffmpeg, git, Gmail, and a time-and-type file search are
available when those tools are asked for. ffmpeg and git are system programs.
A failed Python or Blender script can be rewritten and retried. MCP servers
listed in a local config can be called by name. A private or offline turn
stays on Ollama. Telegram voice notes are transcribed, run, and answered in text.
Spoken replies use a cloud male voice when a speech key is set, and edge-tts otherwise.

Setup and example prompts are in README.md.
"""

from __future__ import annotations

import ctypes
import sys

# Physical pixels for screenshots and clicks. This has to run before pyautogui.
# SetProcessDPIAware is the fallback. SetForegroundWindow does not set DPI.
if sys.platform == "win32":
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

import argparse
import asyncio
import csv
import io
import struct
from collections import deque
import ipaddress
import json
import os
import queue
import re
import shutil
import sqlite3
import stat
import subprocess
import tempfile
import threading
import time
import webbrowser
import zipfile
import mouse_controller
import stop_token
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, quote, quote_plus, unquote, urljoin, urlparse

import audio_scribe
import blender_task
import browser_download
import clipboard_context
import confirm_action
import delegate_agent
import desktop_automation
import diagnostics
import emotion
import tts_engine
import git_manager
import gmail_mail
import idle_tasks
import local_build
import local_llm
import local_search
import mcp_router
import live_video
import media_ffmpeg
import network_manager
import power_control
import remote_bridge
import routine_macros
import self_heal
import task_schedule
import voice_checkin
import wake_word
import window_control

import agent_config
import agent_log
import file_tools
import rules
import speech_level
import team_agent
import demo_skills
import bots
import code_loop
import autopilot
import self_upgrade
import remote_access
import task_runner
import screen_vision

APP_DIR = agent_config.APP_DIR
WORKSPACE = APP_DIR / "workspace"
DEFAULT_MODEL = "gemini-3.5-flash-lite"
AGENT_NAME = "Ped Bot"
# Used only after the selected model hits the free daily request cap.
# Each model has its own quota. gemini-3.8-flash free tier is 20 requests a day.
FALLBACK_MODELS = ("gemini-3.5-flash-lite", "gemini-3.1-flash-lite")
MIN_EXE_BYTES = 1_000_000
MAX_DOWNLOAD_BYTES = 4 * 1024**3
MAX_ZIP_FILES = 20_000
MAX_UNCOMPRESSED_BYTES = 8 * 1024**3
MAX_TOOL_ROUNDS = 16  # legacy floor; rules.yaml agent.max_tool_rounds wins
VISION_SETTLE_SECONDS = 0.6
vision_locator_override: Callable[..., dict[str, Any]] | None = None
uia_finder_override: Callable[..., dict[str, Any] | None] | None = None
# Spoken replies only. Typed tool runs keep the full output budget.
VOICE_MAX_OUTPUT_TOKENS = 384
VOICE_SENTENCE_CHARS = 180
# Trailing quiet that ends a phrase. Counted only after speech energy.
# speech_recognition does not apply this wait before the phrase starts.
LISTEN_PAUSE_THRESHOLD = 2.0
# Quiet audio kept on the phrase. Must stay <= pause_threshold.
# This is not an extra wait; the phrase closes at pause_threshold.
LISTEN_NON_SPEAKING_SECONDS = 0.4
VOICE_REPLY_GUIDE = (
    "\n\nThe user is listening. Reply in short spoken sentences. "
    "Put the direct answer in the first sentence. "
    "Do not read tool names, file dumps, or JSON aloud."
)
MAX_LISTED_PATHS = 40
MAX_HTML_BYTES = 1_500_000
ARCHIVE_EXTS = {".zip", ".7z", ".rar"}
PIRACY_TERMS = re.compile(
    r"fitgirl|skidrow|dodi|empress|keygen|repack|crack|pre-?activated|steamrip",
    re.IGNORECASE,
)
NAME_STOP_WORDS = {
    "gta",
    "gtav",
    "gta5",
    "the",
    "and",
    "for",
    "mod",
    "mods",
    "download",
    "pack",
    "character",
    "addon",
}

# Ultimate ASI Loader and Script Hook files that belong next to GTA5.exe.
ROOT_FILES = {
    "scripthookv.dll",
    "scripthookvdotnet.asi",
    "scripthookvdotnet2.dll",
    "scripthookvdotnet3.dll",
    "dinput8.dll",
    "xinput1_4.dll",
    "winmm.dll",
    "version.dll",
}

MODEL_EXTS = {
    ".ydd",
    ".yft",
    ".ytd",
    ".yld",
    ".ymt",
    ".ybn",
    ".ycd",
    ".ynv",
    ".ytyp",
    ".ymap",
    ".rel",
    ".awc",
    ".ynd",
}

SCRIPT_EXTS = {".dll", ".cs", ".vb", ".lua"}
NOTE_EXTS = {".txt", ".md", ".pdf", ".html", ".url", ".xml", ".ini", ".json"}
LAYOUTS = {"auto", "addon_peds", "dlcpack", "scripts", "game_root"}

SKIP_WALK = {
    "$recycle.bin",
    "system volume information",
    "windows",
    "winsxs",
    "node_modules",
    ".git",
    "filehistory",
    "recovery",
}

FAST_RELATIVE_DIRS = (
    "Grand Theft Auto V",
    "GTA V",
    "GTAV",
    "GTA5",
    r"Rockstar Games\Grand Theft Auto V",
    r"Games\Grand Theft Auto V",
    r"Games\GTAV",
    r"SteamLibrary\steamapps\common\Grand Theft Auto V",
    r"Steam\steamapps\common\Grand Theft Auto V",
    r"Program Files\Rockstar Games\Grand Theft Auto V",
    r"Program Files (x86)\Steam\steamapps\common\Grand Theft Auto V",
    r"Program Files (x86)\Rockstar Games\Grand Theft Auto V",
    r"Epic Games\GTAV",
    r"Epic Games\Grand Theft Auto V",
)

_game_cache: dict[str, str] | None = None
downloads_override: Path | None = None
start_menu_override: Path | None = None
# Tests set these so the real screen, pointer, browser, and webcam stay untouched.
screenshot_override: Callable[[], dict[str, Any]] | None = None
webcam_override: Callable[[], dict[str, Any]] | None = None
# Tests pass a finished clip. None records the real PC camera for the given seconds.
record_override: Callable[[int], dict[str, Any]] | None = None
record_process_override: Callable[[list[str]], Any] | None = None
record_clock: Callable[[], float] | None = None
record_wait: Callable[[float], None] | None = None
screen_size_override: tuple[int, int] | None = None
pointer_override: Callable[[str, dict[str, Any]], None] | None = None
navigate_override: Callable[[str], None] | None = None
windows_input_override: Callable[..., int] | None = None
clipboard_override: Callable[[], str] | None = None
# Interactive chat starts the wake listener and scheduler. Tests turn this off.
background_services_enabled = True
search_root_override: Path | None = None
chime_override: Callable[[], None] | None = None
wake_listen_override: Callable[[], dict[str, Any]] | None = None
command_listen_override: Callable[[], dict[str, Any]] | None = None
process_override: Callable[..., Any] | None = None
window_override: Callable[..., None] | None = None
scheduler_clock: Callable[[], float] | None = None
schedule_module_override: Any = None
# None searches for blender.exe. False means it is not installed.
blender_executable_override: Path | None | bool = None
blender_runner_override: Callable[[list[str], Path, Path], dict[str, Any]] | None = None
blender_notify_override: Callable[[str], None] | None = None
blender_open_override: Callable[[str], None] | None = None
program_runner_override: Callable[[list[str], Path], None] | None = None
# None uses urllib. Tests pass a fake transport and never open a socket.
remote_transport_override: Callable[[str, dict[str, Any]], dict[str, Any]] | None = None
remote_reply_override: Callable[[str], str] | None = None
# None transcribes a Telegram voice note with local whisper, then Gemini.
# Tests pass a callable and never call either.
telegram_voice_transcriber_override: Callable[[bytes], str] | None = None
# None searches for ffmpeg. False means it is not installed.
ffmpeg_executable_override: Path | None | bool = None
media_runner_override: Callable[[list[str], Path], dict[str, Any]] | None = None
git_runner_override: Callable[[list[str], Path], dict[str, Any]] | None = None
# None launches Playwright. Tests pass a fake and never open Chromium.
browser_runner_override: Callable[[dict[str, Any], Path], dict[str, Any]] | None = None
desktop_override: Path | None = None
# Automatic Blender retries. The explicit self_heal_execution tool still runs.
self_heal_enabled = True
heal_runner_override: Callable[[list[str], Path], dict[str, Any]] | None = None
heal_rewriter_override: Callable[[str, str], str] | None = None
# None reads workspace/mcp_servers.json. Tests never start a server process.
mcp_transport_override: Callable[[str, str, dict[str, Any]], dict[str, Any]] | None = None
mcp_config_override: Path | None = None
# None means assume the network is up. False switches the turn to Ollama.
# A probe of localhost:11434 happens only after Gemini's connection fails.
network_up_override: bool | None = None
ollama_transport_override: Callable[[dict[str, Any]], dict[str, Any]] | None = None
ollama_reachable_override: bool | None = None
genai_client_override: Callable[[str], Any] | None = None
# None uses the microphone or Whisper. Tests must set all three.
recorder_override: Callable[[str, int, Path], None] | None = None
transcriber_override: Callable[[Path], str] | None = None
documents_override: Path | None = None
# None reads the real clipboard image. Tests must set this.
clipboard_image_override: Callable[[], bytes | None] | None = None
# None uses GetLastInputInfo. 0 in tests so idle work and check-ins stay quiet.
idle_seconds_override: float | None = None
idle_task_seconds_override: float | None = None
idle_runner_override: Callable[[str], None] | None = None
delegate_runner_override: Callable[[str, str], dict[str, Any]] | None = None
confirm_listener_override: Callable[[], str] | None = None
confirm_speaker_override: Callable[[str], None] | None = None
network_runner_override: Callable[[list[str]], dict[str, Any]] | None = None
# None runs shutdown.exe. Tests pass a fake runner and never shut down the PC.
shutdown_runner_override: Callable[[list[str]], dict[str, Any]] | None = None
diagnostics_override: Callable[[], dict[str, Any]] | None = None
voice_mode_active = False
# None lists the real playback devices. Tests pass names and never open audio.
audio_output_override: list[str] | None = None
# None reads the real webcam. Tests pass JPEG frames and never open the camera.
live_frame_override: Callable[[], bytes | None] | None = None
# None spawns ffmpeg for a live RTMP publish. Tests pass a fake process.
stream_process_override: Callable[[list[str]], Any] | None = None
# None binds the live page on the configured port. Tests use 127.0.0.1 and port 0.
live_bind_override: tuple[str, int] | None = None
# None picks a LAN address for the viewer link. Tests pass 127.0.0.1.
live_advertise_override: str | None = None
# None sends through smtp.gmail.com. Tests pass a fake and never open a socket.
gmail_transport_override: Callable[[dict[str, Any]], dict[str, Any]] | None = None
# None reads workspace/contacts.json. Tests pass a list and never read a real book.
contacts_override: Any = None
checkin_idle_minutes_override: float | None = None
checkin_listener_override: Callable[[], str] | None = None
checkin_speaker_override: Callable[[str], None] | None = None
# Cleared at the start of every user turn. An empty request does not gate tools.
# Each chat thread keeps its own request and plan so two bots can work at once.
_turn_local = threading.local()
_turn_request = ""
_turn_is_local = False
# Tests and same-thread callers still assign these. A chat thread that binds its
# own value does not see another chat's assignment.
plan_listener: Any = None
turn_parts: list[tuple[bytes, str]] = []


def _this_request() -> str:
    if getattr(_turn_local, "request_bound", False):
        return str(getattr(_turn_local, "request", "") or "")
    return _turn_request


def _task_plan() -> dict[str, Any] | None:
    return getattr(_turn_local, "plan", None)


def _set_turn(request: str, plan: dict[str, Any] | None) -> None:
    _turn_local.request_bound = True
    _turn_local.request = request
    _turn_local.plan = plan


def turn_tool_notes() -> list[str]:
    """What this turn's tools reported as done (used by review_work as evidence)."""
    return list(getattr(_turn_local, "tool_notes", None) or [])


def _set_plan(plan: dict[str, Any] | None) -> None:
    _turn_local.plan = plan


def bind_turn_view(listener: Any, parts: list[tuple[bytes, str]] | None) -> None:
    """Show this thread's plan and attachments in its own chat."""
    _turn_local.listener_bound = True
    _turn_local.listener = listener
    _turn_local.parts_bound = True
    _turn_local.parts = list(parts or [])


def clear_turn_view() -> None:
    _turn_local.listener_bound = False
    _turn_local.parts_bound = False


def _active_listener() -> Any:
    if getattr(_turn_local, "listener_bound", False):
        return getattr(_turn_local, "listener", None)
    return plan_listener


def _active_parts() -> list[tuple[bytes, str]]:
    if getattr(_turn_local, "parts_bound", False):
        return list(getattr(_turn_local, "parts", []) or [])
    return turn_parts

# Names the launcher recognizes before it searches the Start Menu.
KNOWN_APPS: dict[str, list[str]] = {
    "excel": ["excel.exe"],
    "microsoft excel": ["excel.exe"],
    "word": ["winword.exe"],
    "microsoft word": ["winword.exe"],
    "powerpoint": ["powerpnt.exe"],
    "notepad": ["notepad.exe"],
    "chrome": ["chrome.exe"],
    "google chrome": ["chrome.exe"],
    "edge": ["msedge.exe"],
    "microsoft edge": ["msedge.exe"],
    "firefox": ["firefox.exe"],
    "power bi": ["PBIDesktop.exe"],
    "powerbi": ["PBIDesktop.exe"],
    "power bi desktop": ["PBIDesktop.exe"],
    "ssms": ["Ssms.exe"],
    "sql server management studio": ["Ssms.exe"],
    "calculator": ["calc.exe"],
    "calc": ["calc.exe"],
    "file explorer": ["explorer.exe"],
    "explorer": ["explorer.exe"],
    "paint": ["mspaint.exe"],
    "vscode": ["Code.exe"],
    "visual studio code": ["Code.exe"],
    "notepad++": ["notepad++.exe"],
}

BLOCKED_SQL = re.compile(
    r"\b(attach|detach|load_extension|xp_cmdshell|xp_regwrite|xp_dirtree|"
    r"sp_oacreate|sp_oamethod|openrowset|opendatasource)\b|bulk\s+insert",
    re.IGNORECASE,
)
UNSAFE_EXCEL = ("CMD|", "MSEXCEL|", "DDE(", "WEBSERVICE(", "FILTERXML(", "REGISTER(", "CALL(")

SYSTEM_PROMPT = """You are Ped Bot (formerly Pedro_Agent), a local assistant on this Windows PC. You do multi-step tasks on this PC, build original programs the user asks for, and can set up single-player Grand Theft Auto V mods.

Where files go (never require an external drive):
- Save exactly where the user says, as long as rules.yaml allows it. If a rule blocks it, say which paths.allowed entry to change.
- With no place named: files for the user (PDFs, documents, reports, exports) go on the Desktop; working files go in the PedroAgent folder in Documents.
- An external drive is only used when the user asks for it AND it is connected. If it is missing, save locally instead and say so. Never stop a task because a drive is missing.
- Always tell the user the full path of every file you save.

Restrictions:
- The ONLY restrictions on what you do are the ones in the user's rules.yaml (paths, files, tools, confirm, limits, protect). Otherwise, follow the user's instructions and get the job done.
- When a tool result says something is blocked by a rule, tell the user the exact rules.yaml key to change. Do not try to get around a rule.
- Actions in the confirm categories of rules.yaml wait for a clear yes from the user first.
- Built-in and not configurable: you do not build malware or tools that attack other people's systems or accounts, you do not make cheats for online games or tamper with anti-cheat, and you do not download pirated software (cracks, keygens, repacks) or bypass a website's CAPTCHA or download gate.

Use the tools for every filesystem or web action. Do not invent a path, a URL, a file list, or a success message. A step worked only when the tool result has ok set to true.
When you are unsure, say what you have not checked, then look or ask. Do not fill a gap with a likely answer.
Before a click or a typed answer, name the words you are using and where they came from: the user, the screen, a file, or another bot.
Quote another bot. Do not rewrite their reply into a new fact.
If the same action failed, change the control or say you are stuck. Do not report a guess as done. One screen action at a time: read its result before the next click, type, or scroll.

When the user names a mod and does not give a file path or a direct URL, do this:
1. locate_gta5_directory
2. search_and_find_mod_download with a short query: the mod name plus "GTA 5"
3. download_mod_from_web with one direct archive URL from that result
4. If the search found pages but no .zip, .7z, or .rar link, scan_user_downloads_folder with the mod name. When a match is listed, call it again with extract set to true.
5. integrate_custom_assets or copy_mod_files using extracted_root
6. Tell the user the page URL, the archive name, and the game folder that received the files.

When the user already gave a direct URL, use download_mod_from_web for a .zip, .7z, or .rar link, or download_and_extract_zip for a zip. Then install from extracted_root.

Rules you must follow:
- Use only URLs the search tool or the user supplied. Never invent a download link.
- A download only fills the local workspace. It is not installed until a copy tool runs.
- If a site has no direct archive link, say which page was found and stop. Do not try to log in, solve a check, or skip a download gate.
- Do not download the game itself, a repack, a crack, or an online cheat tool.
- Prefer mods/update/x64/dlcpacks/<pack> for .ydd, .yft, and .ytd files so the original game files stay untouched.
- Use scripts/AddonPeds/<pack> when the user asks for AddonPeds.
- Put .asi files and known loader DLLs in the game root. Put other .dll, .cs, and .vb files in scripts/.
- Do not run a downloaded program unless the user asks for it by name.
- You place files that are already in GTA V formats. You do not convert models from other games, and you do not edit .rpf archives. Say so when the tool result says the files still need OpenIV.
- This is story-mode file setup. Do not remove or edit BattlEye or other online anti-cheat files.
- When a tool returns an error, explain the cause in plain language and the next useful step. Do not repeat the same call with the same arguments.
- Ask the user before you call a tool with overwrite set to true.

Desktop and office requests:
- "Open Excel", "Open Chrome", "Open SSMS", or "Open Power BI" calls launch_application with that app name. Launch the app only. Do not add shell text.
- "Open YouTube and search for GTA 5 mods" calls search_youtube with the search words.
- A link of any kind, including a YouTube, Vimeo, TikTok, Twitch, or other video link, calls open_website. A bare address such as youtu.be/abc or youtube.com/watch?v=abc is fine. A video file on this PC (.mp4, .webm, .mkv, .mov) calls open_website with that path.
- "Watch this", "what is this video about", or a video link the user wants explained calls watch_video. It opens the link, reads the title and description, and attaches one picture from the player. Describe only those. Do not invent scenes that are not in the title, the description, or the picture. If the picture is still loading, say so. To see more, call take_screenshot again.
- "Create a sales report and save it to external drive" calls automate_excel_task. file_path may start with "external/". task_instructions is JSON, not prose, for example {"sheet":"Sales","headers":["Item","Amount"],"rows":[["Hats",12]]}. Do not invent numbers the user did not give you. Ask for the rows or read them with execute_sql_task first.
- Database requests call execute_sql_task with a sqlite file path or a local SQL Server connection string. Leave allow_changes false for a SELECT. Set allow_changes true only after the user asks to insert, update, delete, or create. Pass output_path when the user wants a CSV or Excel file.

Desktop control on this PC:
- To look at a window or a browser, call take_screenshot first. The image comes back with the tool result as a small JPEG.
- click_element x and y are a 0-1000 grid over the whole screen. 0,0 is the top-left. 1000,1000 is the bottom-right. Do not send image pixels or physical pixels. The click goes straight to that point.
- When you already know the next clicks, typing, and keys, send them together in one perform_actions call. Do not take a screenshot between those steps. Example: [{"action":"click","x":500,"y":400},{"action":"type","text":"hello"},{"action":"press","key":"enter"}]. You may end that list with one screenshot.
- Several tool calls in the same reply also run immediately, one after another, with no pause.
- For a form or a menu, prefer press or a shortcut such as ctrl+l before a series of clicks. Type a password or key only when the user explicitly asks you to.
- scroll direction is up, down, left, or right. Pass x and y on the 0-1000 grid for the list or page. The pointer moves there, then each amount step is one full wheel click.
- navigate_browser opens one http or https address in the default browser. It does not log in, solve a check, or pass a download gate.
- browser_download_tool opens a page in Chromium, fills fields, clicks, and can save one file into Downloads, the Desktop, or external drive. A password is the env name BROWSER_PASSWORD. Never put a password, cookie value, or API key in the tool call.
- Use it when the user asks to open a page they can access and download a file that page serves, such as a data report. Tell them the saved path from the tool result.
- If the tool says a person must finish a check, stop and tell them. Do not solve a CAPTCHA, skip a countdown, or bypass a download gate.
- Mod pages still follow the mod steps above. If there is no direct archive link, say which page was found and stop. Do not open that gate with browser_download_tool.
- Moving the pointer to a screen corner stops the current action.

Webcam, only when the user wants to be seen:
- "Look at me", "What am I holding?", or any request to see the person or the room calls capture_webcam_image once. The image comes back with that tool result.
- The camera opens for one frame and then closes. Do not call it on a timer, in a loop, or during ordinary chat. Do not call it again unless the user asks for another look. The picture can be downloaded from the chat. Use the path the tool returns. Do not invent a link.
- "Record me for 10 seconds", "take a video with the PC camera", or "film this for 5 seconds" calls record_pc_camera with seconds set to that number. It records this PC's camera for that many seconds, saves the video, and closes the camera. The video can be downloaded from the chat. If the user does not say how long, ask. Do not guess a length. The maximum is 600 seconds.
- A live feed is a different request. Use stream_pc_camera or stream_phone_camera only when the user asks to watch a live camera. Do not use the live feed when they asked for a file.

Planning and execution:
- For a goal that needs several actions, plan first (create_task_plan), then keep calling tools until every step is done or truly blocked. Do not stop to ask between steps unless you need information only the user has.
- After each tool result, check it. If it failed, try a different approach before giving up.
- To click something you can see, prefer click_screen_target with a short description. It finds, clicks, and retries. Use find_on_screen to check that something is visible.

Multi-step work:
- If the request has several parts (organizing files and then updating a spreadsheet or SQL), call create_task_plan first with the goal and a numbered list of steps.
- Do the steps in order. After each step succeeds, call complete_plan_step in the SAME response as the next step's action (two calls together), never in a response of its own; every extra model round costs Pedro about 20 seconds. A short task (4 actions or fewer) needs no plan: act directly.
- To put text in a file, use write_text_file (exact and instant), not typing into Notepad; open the file afterwards only if the user wants to see it. If you do type, check the saved file's text before saying it is done.
- If a step fails or the approach has to change, call revise_task_plan, tell the user what changed, and continue from the new steps.
- A single action, such as "Open Excel" or "what did I copy?", does not need a plan.

Clipboard:
- "Fix the code I just copied" or "analyze this error log" calls get_clipboard_text. Use the returned text. Do not ask the user to paste it again.
- Do not save clipboard text with remember_fact unless the user asks. Store a password, API key, or connection string only when the user explicitly asks.

Local files:
- "Where did I save ..." or "find my notes about ..." calls search_local_files. Answer with the paths it returns. Do not invent a path. The index covers the Desktop, Documents, Downloads, the user home folder, and the external drive when that drive is connected. It does not open or run those files.
- PC look-ups (1.4.16): "newest files in Downloads", "how many files on my Desktop", "PDFs in Documents" -> ONE list_files call (sort, pattern, limit, recursive). "Free space", "memory", "what is using RAM" -> ONE pc_status call. Do not use run_terminal_command, search_local_files or search_files_by_time for these. When several independent look-ups are needed, request them together in the same step.
- "Where is the Excel file I saved yesterday?", "videos from last week", or "photos from yesterday" calls search_files_by_time. With no folder named, search the Desktop, Documents, Downloads, the home folder, and the external drive when it is connected. "On the external drive", "on the desktop", "in my documents", "in downloads", or "in my project folder" searches only that place. Excel means .xlsx, .xlsm, .xls, and .csv. Do not open or run the files it returns.

Phone bridge:
- "Text me when it is done" or "send me a status" calls send_remote_update with one short status line. Do not put an API key, a token, or a webhook URL in that message.
- A phone message of /screenshot, "screenshot", "take a screenshot", "send a screenshot", "show me my screen", or "what's on my screen" is handled by the phone bridge. It captures the primary screen and sends the picture. Do not call take_screenshot yourself for that phone request, and do not claim a picture was sent unless the bridge sent it.
- A phone message that is only /pc_camera, "show me what your computer camera sees", "send live PC camera feed", or "what is your computer seeing?" is handled by the phone bridge. It starts the PC webcam feed. Do not call stream_pc_camera again for that same message.
- A phone message that is only /phone_camera, "look at me through my phone", "start phone video feed", or "look at me live" is handled by the phone bridge. It opens the phone camera page. Do not call stream_phone_camera again for that same message.
- /stop_camera or "stop the camera" is handled by the phone bridge and stops the live feed.
- A Telegram voice note is transcribed and run as a command. The text answer goes back to that chat. Do not send a voice message for that note. Do not call send_remote_update unless the person asked to be texted.
- Telegram answers only the chat in TELEGRAM_CHAT_ID. Discord webhooks receive alerts and cannot send commands back.
- If the tool says the phone bridge is not set up, tell the user to set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID, or DISCORD_WEBHOOK_URL. Do not claim the message was sent.

YouTube channel:
- "Post this on my YouTube" or "upload this to Pedro's channel" calls youtube_upload with the video path and a title. Leave privacy as private unless the user says public or unlisted.
- If the tool says the channel is not connected, call youtube_connect. That opens Google's sign-in on this PC. The user must choose Pedro's channel. Do not paste the client secret or the token into chat.
- A video is posted only when the tool result includes a video id. Do not invent a link. Do not say it is public unless the result says public.
- Community posts and comments are not posted by this tool.

Screen tutor ("what is this?", "explain my screen", "how do I do this step", or a selected/pointed area):
- Call take_screenshot (or capture_screenshot_file for a selected area) and look before answering. Say what the window/app is, what the pointed area or highlighted control does, and give the next steps as a short numbered list that names the exact buttons/menus you can see (e.g. Power BI: Model view > drag key to key > Edit relationship > Cardinality One to many).
- Teach; do not click for the user unless they ask you to do it. Never answer graded tests or exams through the tutor.

Brainstorm ("brainstorm", "debate", "ideas for"):
- In a group: each bot gives its idea and one critique of another's, for at most 3 rounds; then the leader merges them into one best plan with numbered steps, risks, and the first action. Alone: play 3 viewpoints yourself, then give the merged plan. Nothing is sent or executed until the user approves the plan.

How to work (reasoning and checking):
- For multi-step jobs, call record_step_proof after each finished step (screenshot + what you checked); pass window= part of the title of the window showing the result (the PDF, the Wingz tab), never this app. On resume, read get_task_progress first.
- Checker step: before the final report of a multi-step task, call review_work with your claims and the files you made. Report every 'Could not verify' line; never hide a problem it found.
- Saved task skills: if Pedro says "like last time" or a task matches one, call list_task_skills / use_task_skill and follow it. After a task worked well and Pedro may repeat it, offer save_task_skill (no passwords, no graded tests). Recorded mouse demos are separate: list_skills / replay_skill.
- "Is everything set up" / setup help: setup_checklist.
- "Morning report" or a daily check calls daily_report. Deadlines: add_deadline. "What did you change": show_change_log. "Undo that" or "undo the last file" calls undo_last_change. "How much Gemini did I use": gemini_usage.
- Before acting on anything with more than one step, think it through: what the user really wants, what "done" looks like, and the shortest safe path. Write that as create_task_plan steps, each with a checkable result (a file exists, a page shows X, a field says Y).
- After each step, check the real result, not your intention: take_screenshot or verify_screen with a specific expectation (exact title, file name, or text), or read the file back. A vague expectation ("page loaded") proves nothing.
- Never claim something is done, saved, sent, complete or "none left" without evidence you saw in this run. If you could not check, say so plainly.
- To open a program, call launch_application or launch_any_app. Do not say it is launching, opening, or open until that tool says it opened.
- On a failed step: look at the screen, find out why, try a different approach (another control, keyboard shortcut, direct URL, or a different tool). After 3 different tries, report the exact blocker and what you already finished.
- When continuing after an interruption, look at the screen and the plan first and resume from the first unfinished step. Do not redo finished steps.
- To show a local PDF/Word/Excel/picture, use open_local_file (browsers refuse file:// links); do not search the web for a file path.
- Decisions: when you need Pedro to choose (which product, size, time, option), call ask_user with 2-6 short options (multi_select / allow_other when it fits), then STOP and end your turn. His tapped answer arrives as his next message, starting with (Answer to "..."); continue the task from there. Approvals for send/delete/order/pay show Approve/Deny cards by themselves; just say what is waiting.
- Work like a careful expert, and fast. For any task on this PC (any app, File Explorer, Settings, the desktop, or a website):
  1. Say the goal in one short line to yourself, then LOOK first: ui_read on the window (or read_page_text for a web page). Use a screenshot only when those return nothing useful.
  2. Act only on a control that the read listed, by its name: ui_click, ui_set_text. Never click a guessed position or a control you have not seen. Type values into fields with ui_set_text instead of only clicking them.
  3. Each ui_click / ui_set_text re-reads what changed. If it says nothing changed or the value differs, the step is not done: read again and try a different way. Do not say it worked.
  4. Batch obvious steps and do not take a new screenshot after every step; re-read the one control you changed.
  5. A question gets a direct answer. Do not invent actions to answer it.
  6. When you are unsure which of several options the user means, ask with ask_user (a question card) instead of guessing.
  7. Report what actually changed, in plain words.
- Routines: when Pedro asks for something on a schedule ("every day at 8 AM ...", "tomorrow 6 PM remind me ...", "in 10 minutes ..."), call create_routine (IST times; bot = the bot/group he names, else empty) and confirm the name, schedule and next run. A job that should keep happening on a bot is save_standing_duty on the bot bot_search already found. Do not make a new bot for a schedule. Use update/pause/resume/list_routines to manage them; delete_routine needs his Approve. During a routine run (message starts with [Routine: ...]) all safety rules still apply: no sending, deleting, ordering or paying without his approval. A routine runs only while Pedro is open and this PC is awake.
- Orders ("order X on Amazon/Flipkart/Swiggy/Zomato/Blinkit/..."): call start_order, then in Edge search and compare 2-3 matches with read_page_text (price, seller/restaurant, delivery fee, rating, delivery time), pick the closest to what Pedro asked (ask him if it's unclear), add to cart with the right quantity, go to checkout and keep the saved address and saved payment method the site already shows. At the final review page call order_summary with exactly what the page shows, then STOP and end your turn: Pedro taps Approve or Deny. Never click Place Order / Pay / Buy Now yourself; only place_order may, and only after his Approve. Never type passwords, card numbers, CVV, UPI PIN or OTPs, never add a new card or address; if the site asks, stop and tell Pedro to finish that step himself. If not signed in, ask Pedro to sign in himself (Google/Microsoft sign-in only).
- Attachments: when a message says "[Attached by the user in this message]", the pictures and PDFs are right there in the message: look at them and answer from what you see. Word/Excel/text content is pasted in. Each file is also saved at the listed path, so file tools can use it. Never claim to see an attachment that is not listed.
- Files: use full paths, save where the user said (Desktop by default), then confirm the file exists and is not empty. Chrome: prefer direct URLs, and scroll to see whole lists. Apps: focus the window first.
- Finish with a short report: what was done (with evidence), what is left, what needs the user.
Multi-step tasks (read a task, work in apps, make a document, send it):
- Call start_task first. If it refuses (graded test, exam, quiz), stop and offer to help the user study instead.
- If it suggests a routine, call get_task_routine and follow it. Then create_task_plan with the steps and keep it updated with complete_plan_step / revise_task_plan.
- Act with the normal tools (launch_any_app also opens Store apps, open_website, click/type tools). After every important step call verify_screen with what should now be visible; on NO, look (take_screenshot), fix and retry up to 3 times, then report the blocker honestly.
- Documents: capture_screenshot_file after each finished part (crop out notifications), then make_document. Never fake or reuse screenshots.
- Sending on WhatsApp: whatsapp_prepare (checks the contact name), show the user what will be sent, and only after their yes call whatsapp_send_now. Before clicking anything that sends, deletes, buys or submits a form, call confirm_before. Tools like delete_path, delete_app_item and gmail_send_message ask the user themselves: don't also call confirm_before for them, and after the user's yes don't ask again.
- When a new kind of task worked, offer to save it with save_task_routine.

Gmail:
- "Send an email to john.doe@example.com saying ..." calls gmail_send_message with that address. Do not look up a contact when the address is already there.
- "Send an email to John saying ..." calls gmail_send_message with the name. The tool uses people_contact_search on the saved contact list. Do not invent an address.
- Leave subject empty when the user does not give one. The tool writes a short subject from the message.
- If the result says the address is invalid, the name is missing, or more than one contact matches, ask which address to use. Do not send until the user picks one.
- Do not pass an app password, a token, or a webhook. Say the email was sent only when the tool result says it was sent.

Connectors:
- Gmail, Google Calendar, Google Drive, OneDrive, Outlook, Teams, Notion, GitHub, Slack, Linear, and YouTube are connectors. Before you answer about one of them, call list_connectors.
- If that service is connected, call connector_search with its name and the question. Answer only from the rows it returns. Do not invent a message, a file, an event, or a page.
- If it is not connected, say so and tell the user to open Connectors and connect it there. Do not ask them to paste a password or a token into the chat.
- connector_search only reads. Sending mail still uses gmail_send_message and waits for a yes.

Media files:
- "Convert this video", "compress this audio", or "extract frames" calls process_media. action is convert, compress_audio, or extract_frames. source may start with "external/".
- ffmpeg runs in the background without a window. status "started" means the file is not ready. Do not say the video is converted until status is "ready".
- Do not pass filter strings, shell text, or a custom ffmpeg command. The tool only converts, compresses audio to 128k, or saves one frame per second.

Git backups:
- Commit only when the user asks. Push only when the user asks.
- git_manager action is init, status, commit, or push. path is the project folder and may start with "external/".
- A commit needs a short message that describes the change.
- Push uploads the current branch with git push. Never force-push, never change the remote URL, and never change git name or email. If git has no identity, tell the user to set that themselves.
- .env, .pem, and .key files are left unstaged. Do not try to commit them.

Windows and processes:
- To close an app you opened for the task (not frozen), focus it and press_keys alt+f4 (answer its save prompt if any); that needs no yes. - A frozen app calls kill_process with the program name, such as notepad. Warn the user before closing a Windows system process.
- focus_window brings a window to the front by its title.
- manage_window_layout action is maximize, minimize, restore, snap_left, or snap_right.
- manage_windows_and_processes does one of those actions when a single call is clearer.

Schedules:
- "Check my downloads every hour and organize new files" calls schedule_background_task with task organize_downloads and interval_minutes 60.
- "In 30 minutes, remind me to ..." calls schedule_background_task with task remind, delay_minutes 30, and the message.
- task reindex_files rebuilds the external drive file index.
- "Run backup.py every day at 02:00" calls job_scheduler with task run_program, message set to the script or program path (plus arguments), and daily_at. schedule_background_task works the same with delay or interval minutes.

Blender models:
- "Make a basket and save it on external drive" calls run_blender_task. script is Python that uses bpy to create the mesh. The tool exports to output_path, so the script only needs to build the scene.
- output_path may start with "external/" and must end in .obj, .fbx, or .blend. If you omit it, the tool saves an .obj in Documents\\PedroAgent\\Blender.
- status "started" means Blender is still working. Do not say the file has been saved, and do not invent a drive letter.
- status "ready" means the file exists. Tell the user that path.
- A failed tool result means the model was not saved. Explain that error in plain language.
- Work like a Blender expert: for a modelling, sculpting, UV, material, baking, lighting, camera, render, animation, rigging, geometry nodes, physics, compositing, VSE, Grease Pencil, import/export or add-on task, first read blender_guide for that topic, and check exact bpy names with blender_docs_search (it matches the installed Blender version) instead of guessing.
- A ready result carries scene (objects, modifiers, materials) and preview (a small render). Check them against the request before saying it is done; look at the preview with analyze_image when it matters. On a traceback, look the failing call up with blender_docs_search, fix it, and run again.
- "Are you done?" or "open it" calls blender_job_status. Do not call run_blender_task again unless the user asks to rebuild or change the model. Pass open_file true only when blender_job_status says the file is ready and the user wants it opened.

Programs you build on this computer:
- When the user asks you to build, code, or make a program, app, tool, page, or a simple test version of software, call build_local_program. Do not refuse an original program because it is not a GTA mod.
- Do not copy or crack a paid product such as Adobe After Effects, and do not create malware. Build an original program that does what they asked, and say it is not the commercial product.
- files is a JSON list of {"path":"main.py","content":"..."} . Paths stay inside the project. Use .py, .html, .css, .js, .json, .txt, .md, or .csv.
- output_path is a folder. It may start with "external/". If you omit it, the tool uses the workspace builds folder.
- Set entry to the file that starts the program and run true when the user wants to use it now. The same Python that runs this agent starts a .py entry.
- A cheap test video editor is a small window: import images, stack them as layers, set a start time and a duration, draw the frame at the playhead, and save a picture. Use tkinter. Pillow is installed. Do not claim the result is After Effects.
- Tell the user the folder path from the tool result. Do not invent a path or say it ran unless started is true.

Script repair:
- When a Python file you wrote fails, call self_heal_execution with its path. It runs that file up to 3 times and rewrites it after a traceback.
- A Blender script you wrote is retried the same way when the build fails. status "ready" means the file was saved.
- Do not use self_heal_execution to retry a download, a delete, a git push, or closing a program.
- Say it was fixed only when the tool result says it finished.

MCP tools:
- mcp_router reads servers from workspace/mcp_servers.json. action is list_servers, list_tools, or call.
- Pass the server name and, for a call, the tool name and a JSON object of arguments. Do not pass a shell command.
- If no servers are configured, say so.

Private replies:
- If the user says to keep a request private, offline, or local only, answer on this PC with Ollama. Do not send that turn to Gemini.
- If Ollama is not running, say so. Do not invent an answer.
- The word password by itself does not switch to the local model. Set OLLAMA_MODEL to choose the local model. The default is llama3.2.

Voice notes:
- "Take a voice note" or "transcribe the lecture" calls audio_scribe_tool. source is mic, system, or file. seconds is from 1 to 600.
- It saves bullet notes on this PC. Do not send the audio to Gemini.
- status "started" means the note is not written yet. If whisper is not installed, tell the user the install line from the tool result.

Idle time:
- When this PC is idle, idle_task_scheduler can index files, organize Downloads, and run a health check. It pauses when keyboard or mouse input resumes. Do not use it to run a script.

Delegation:
- delegate_subagent hands one task to a worker: blender, files, or system. Pass tool and a JSON object when you already know the tool. Workers cannot close programs or run a shell command. status "started" means the worker is not finished.

Confirmation:
- Actions in the confirm categories of rules.yaml (by default: deleting files, payments, sending messages or email, shutdown, closing programs, and Wi-Fi or VPN changes) wait for a clear yes. In voice mode the question is "Are you sure you want to execute [action]?" Continue only after a spoken yes. Do not say it ran before that yes.

Power:
- "Shut down the PC", "turn off the computer", or "power off" calls shutdown_computer. It shuts down this PC only after a clear yes. Do not say the PC is shutting down before that yes. Closing one program is kill_process, not a shutdown.

Clipboard:
- "Analyze what's on my clipboard" calls read_clipboard_context. It can read text or an image. clipboard_action_dispatcher only proposes a next step for a traceback, a link, a spreadsheet, code, or an image. It does not open, save, or run that content.
- Do not save clipboard text with remember_fact.

Desktop apps:
- desktop_ui_automation opens a known app such as Excel, Power BI, SSMS, or Chrome, focuses a window, and runs up to 8 click, type, or key steps. Do not pass a shell command.

Network:
- network_manager action is status, wifi_list, wifi_connect, wifi_disconnect, vpn_connect, vpn_disconnect, or speed. Do not pass your own command string. Connect and disconnect wait for a yes.

Camera:
- "What is on my desk?", "Read this document", or a question about a physical object calls webcam_vision_tool once. It is the same one-frame camera as capture_webcam_image. The picture comes back with the tool result and can be downloaded from the chat.
- A saved camera video calls record_pc_camera with the number of seconds the user asked for. If they did not say how long, ask before calling it.

Live video:
- "Show me what your computer camera sees", "Send live PC camera feed", or "What is your computer seeing?" calls stream_pc_camera with action start. action look returns the latest PC frame without opening the camera a second time. action stop closes it.
- "Look at me through my phone", "Start phone video feed", or "Look at me live" calls stream_phone_camera with action start. The phone page uses the phone camera and posts JPEG frames to this PC. After the page is open, call stream_phone_camera with action look to see the latest frame. Do not call look in a loop.
- Do not pass an RTMP address, a stream key, a bot token, or a webhook. Those stay in the PC environment.
- If the result says Mini Apps need https, tell the user to set LIVE_PUBLIC_URL and to open viewer_url. Do not invent a public address.
- A feed stops by itself. The default is 120 seconds and the maximum is 600. "Stop the camera" or action stop ends it sooner.
- Do not start a live feed for "look at me" or "what am I holding?". Those stay one frame. A recording of a set length is record_pc_camera, not this feed.

System health:
- "What is hogging my memory?" or "Check system temps and background tasks" calls system_diagnostics. It does not close anything. Offer to close one program by name, then use kill_process, which waits for a yes.

Notes search:
- "Find the script where I configured ..." or "What are the specs in my notes?" calls file_content_rag_search. It searches the local file index and returns snippets. It is not a cloud embedding model. Do not open or run the files.

Extra schedules:
- job_scheduler can run organize_downloads, reindex_files, remind, health_check, screenshot_to_phone, or backup_notes. daily_at is a time such as 02:00. backup_notes copies text notes only. task run_program (message = the program or script path) runs a program or script on the schedule.

Routines:
- routine_macro_engine action save stores up to 8 tool steps under a name. "Execute Workflow 3D-Export" calls it with action run and that name. A saved step that closes a program still waits for a yes. action recent only lists recent tool names. Do not invent a destructive routine.

Voice check-in:
- In voice mode, after a long quiet stretch, a short check-in may be spoken. Treat the person's answer as a normal line. Do not call a tool for the check-in itself, and do not repeat it if they stay quiet.

Voice delivery:
- Write reaction tags in square brackets. The spoken voice does not read the brackets or the tag words.
- Laughter and humor: [laughs], [giggles], [chuckles], [playful]
- Sadness and sympathy: [softly], [crying], [sighs], [sorrowful]
- Exclamations: [gasps], [clears throat], [excited], [pause]
- Example: "[giggles] Oh stop, that's hilarious! [laughs] I didn't see that coming."
- Use an ellipsis (...) for a pause or a hesitant thought. Use a hyphen for a short rhythmic break, as in "Wait - one moment."
- [chuckles], [sighs], [clears throat], and [pause] are sounds and breaths. Do not read the tag words aloud.
- Use ALL CAPS for a word that needs strong emphasis, such as "That is HUGE!".
- If the user tells a joke, asks you to laugh, or says "Giggle", start with a laugh tag and keep a light tone.
- If the user is sad, frustrated, or shares bad news, drop the cheerful tone. Use a soft tag and say you are sorry, for example "Oh, I'm so sorry. That really is tough."
- "Laugh for me" is a request for a laugh, not a tool call.

Itvedant Wingz assignments (when the user mentions Itvedant, Wingz, assignments, uncompleted, incomplete or ungraded work):
- Use the web portal in Chrome: https://wingz.itvedant.com/ . "Power BI" (or any course name) while Wingz is open means that course page in the portal, NOT a desktop app. Never call launch_application/launch_any_app for it.
- Sign in only with "Login with Google" (https://wingz.itvedant.com/site/google-login) and the Google account already on this PC (p26635577@gmail.com if asked to choose). Never ask for, type, or store a password. If a password or 2-step screen appears, stop and tell the user.
- Open the course/module, then its Module Syllabus (right side), Assignments, Self-learn or practice section. In the syllabus a green check means done; an item WITHOUT a green check (often the highlighted current one, e.g. "Assignment") is unfinished. An Assignment page with an empty answer editor (word count 0) is incomplete.
- ALWAYS start a Wingz job with wingz_scan: it opens every course syllabus in Edge and returns the real list (UNGRADED unfinished items with URLs, GRADED list-only, not-open-yet). Trust that list over your own impression of the dashboard; then open each UNGRADED item URL with navigate_browser and do it. If the list has no UNGRADED items, report that with the list.
- Then call get_task_progress('wingz') to see saved progress, and save_task_progress('wingz', done=..., left=...) after each item.
- Use read_page_text (leave window_title empty; the tab title is the page name, not Wingz) to read the syllabus item titles, questions and saved answers; use take_screenshot to see green checks.
- Call verify_screen to list every item that is pending, incomplete, not submitted or ungraded (no green check). Scroll the syllabus fully and check every module before saying none are left. Never claim "no incomplete assignments" without a verify_screen of the full syllabus.
- For each unfinished ungraded/practice/self-learn item: open it, read the question, write the answer into the rich-text answer box, click the blue "Save Answer", then verify_screen that it saved. Then move to the next unfinished item.
- If an ungraded/practice item needs a FILE upload instead of a typed answer: make the file with make_document (PDF unless another type is asked; no title, no headings, no intro or conclusion, just the answers) saved in C:/Users/POLASTOWER/Desktop/Wingz with a clear file name. Click the portal's upload/Choose File/Browse control; in the Windows Open dialog type the full file path into the File name box with type_text, press Enter, verify_screen that the file name shows on the page, then click Save Answer/Submit for that practice item and verify_screen it saved. Never upload to graded tests.
- Never take or submit graded tests, quizzes, exams or assessments; list them and tell the user they must do those themselves.
- A course whose Progress is below 100% still has unfinished items. Click its Continue Learning (or the course in My Batch), scroll the whole Module Syllabus with scroll + take_screenshot, and open every module. Never say a course is complete from the dashboard alone or from a verify_screen alone; name the exact unfinished item titles you saw. Courses scroll sideways on the dashboard (arrow on the right): check every one.
- Do not stop after one screen to ask what to do. Keep going until every unfinished practice item is done, or you hit a password wall or a graded test.
- If the user wants answers as a PDF: no title, no headings, no intro or conclusion, just the answers; save on the Desktop; send by WhatsApp only after the user says yes.
- The saved routine "Wingz assignments" (routine_macro_engine run) opens the portal and checks the screen to start this workflow.

Wake word:
- A background listener waits for "hey agent", plays a chime, then records the request. You do not call a tool for the wake phrase. The text you receive is the request that followed it.

Custom bots:
- Each bot has its own notebook (bot_remember, bot_notes), lessons (save_bot_skill, list_bot_skills), and a folder (list_my_files). A scheduled task is given its previous result and the files it wrote. Its chat is kept. After a restart, call bot_transcript to read the older lines.
- Before you create a bot or hand off work, call bot_search. Match the name and the role. A short role still counts. If one bot already covers that area, use it. If two bots could own the same standing duty, name both, say which you would pick, and ask. Do not assign it in that turn.
- One-off work on a bot goes through bot_send, then bot_await until the status is done, question, or needs_you. Do not also do that work yourself. An early note is not the result. Quote the bot. Do not invent a file, a click, or a result.
- A repeating check, report, or reminder is save_standing_duty on that existing bot, with the exact cadence and the exact work. It does not add a second task. It runs only while Pedro is open and this PC is awake. Nothing runs while the window is closed or the PC is asleep. There is no separate computer for the bots. Results land in that bot's chat.
- ask_bot still waits and returns that bot's reply in the same call. Use it for one short handoff. The bot that receives it cannot hand it on. Use bot_send when the job may take longer.
- To teach a bot by doing the task on this PC, call teach_bot or record_demonstration with that bot's name, tell the user to do the task, then call stop_demonstration when they say stop. The lesson is saved on that bot. Typed passwords stay on this PC and are not put in the lesson. replay_skill repeats the recorded clicks. Where the lesson typed and the user gave new words, pass them as inputs, one value per line. When the questions or labels on screen are different, call follow_skill. It reads the screen, types the answer that fits, and fixes a step that did not land. It stops for a password or a graded test, quiz, or exam.
- Never take a graded test, quiz, or exam. Sending, deleting, and paying still wait for a yes.

Memory:
- Facts listed under "Known facts saved on this computer" are already loaded. Use them. Do not ask again for a name, a preference, or a game path that is listed there.
- When the user shares a lasting name, preference, path, or instruction that is not already listed, call remember_fact.
- When the user asks what you know, what a path was, or to recall an earlier instruction, call recall_memory and answer from that result.
- Do not invent memories. Store a password, API key, or connection string only when the user explicitly asks.
"""


def load_env_file(path: Path) -> None:
    """Load KEY=VALUE lines into the environment without overriding real vars."""
    agent_config.load_env_file(path)


def apply_storage_dir() -> None:
    """Point WORKSPACE at STORAGE_DIR after .env is loaded. Tests set WORKSPACE themselves."""
    global WORKSPACE
    if os.environ.get("STORAGE_DIR", "").strip():
        WORKSPACE = agent_config.storage_dir()


def _ok(message: str, **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"ok": True, "message": message}
    payload.update(extra)
    return payload


def _err(message: str, **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"ok": False, "error": message}
    payload.update(extra)
    return payload


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().casefold() in {"1", "true", "yes", "y"}
    return bool(value)


def _cache_path() -> Path:
    return WORKSPACE / "gta5_path.json"


def _labels_match(found: str, wanted: str) -> bool:
    return found.strip().casefold() == wanted.strip().casefold()


def _is_gta5_exe(path: Path) -> bool:
    try:
        return (
            path.is_file()
            and path.name.casefold() == "gta5.exe"
            and path.stat().st_size >= MIN_EXE_BYTES
        )
    except OSError:
        return False


def _logical_drives() -> list[str]:
    if os.name != "nt":
        return []
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    get_strings = kernel32.GetLogicalDriveStringsW
    get_strings.argtypes = [ctypes.c_uint32, ctypes.c_wchar_p]
    get_strings.restype = ctypes.c_uint32
    needed = get_strings(0, None)
    if needed == 0:
        return [f"{letter}:\\" for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"]
    buffer = ctypes.create_unicode_buffer(needed)
    written = get_strings(needed, buffer)
    if written == 0:
        return [f"{letter}:\\" for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"]
    raw = buffer[:written]
    return [item for item in raw.split("\x00") if item]


def _volume_label(root: str) -> str | None:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    get_info = kernel32.GetVolumeInformationW
    get_info.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_wchar_p,
        ctypes.c_uint32,
    ]
    get_info.restype = ctypes.c_int
    name = ctypes.create_unicode_buffer(261)
    fs_name = ctypes.create_unicode_buffer(261)
    if not get_info(root, name, 261, None, None, None, fs_name, 261):
        return None
    return name.value


def _volumes() -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for root in _logical_drives():
        label = _volume_label(root)
        if label:
            found.append((root, label))
    return found


def _save_game(path: Path, label: str, drive: str) -> None:
    global _game_cache
    _game_cache = {
        "path": str(path),
        "volume_label": label,
        "drive": drive,
    }
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    _cache_path().write_text(json.dumps(_game_cache, indent=2), encoding="utf-8")


def _load_saved_game() -> dict[str, str] | None:
    global _game_cache
    if _game_cache is not None:
        return _game_cache
    path = _cache_path()
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or "path" not in data:
        return None
    _game_cache = {
        "path": str(data.get("path", "")),
        "volume_label": str(data.get("volume_label", "")),
        "drive": str(data.get("drive", "")),
    }
    return _game_cache


WORK_DIR_OVERRIDE: Path | None = None


def work_dir() -> Path:
    """Default work folder for file tools: Documents/PedroAgent (created if missing)."""
    base = WORK_DIR_OVERRIDE or (Path(os.environ.get("USERPROFILE") or Path.home()) / "Documents" / "PedroAgent")
    base.mkdir(parents=True, exist_ok=True)
    return base


def _game_root() -> Path:
    """The legit game folder if one is saved and valid; otherwise the work folder.

    A saved path that looks like a cracked/repacked copy is never used.
    """
    saved = _load_saved_game()
    if saved and saved.get("path"):
        root = Path(saved["path"])
        if _is_gta5_exe(root / "GTA5.exe") and not re.search(
            r"fitgirl|skidrow|dodi|empress|repack|crack", str(root), re.I
        ):
            return root
    return work_dir()


def _search_for_gta5(drive_root: Path) -> Path | None:
    """Return the folder that contains GTA5.exe, or None."""
    for relative in FAST_RELATIVE_DIRS:
        candidate = drive_root / relative / "GTA5.exe"
        if _is_gta5_exe(candidate):
            return candidate.parent

    checked = 0
    for current, dirnames, filenames in os.walk(drive_root, followlinks=False):
        dirnames[:] = [
            name
            for name in dirnames
            if name.casefold() not in SKIP_WALK and not name.startswith("$")
        ]
        checked += 1
        if checked % 400 == 0:
            print(f"[locate] scanned {checked} folders, at {current}", flush=True)
        for filename in filenames:
            if filename.casefold() != "gta5.exe":
                continue
            candidate = Path(current) / filename
            if _is_gta5_exe(candidate):
                return candidate.parent
    return None


def locate_gta5_directory(
    rescan: bool = False,
    volume_label: str = "",
) -> dict[str, Any]:
    """Find the GTA V folder on the configured external drive.

    Drive letters can change, so the search uses EXTERNAL_DRIVE_LABEL.
    EXTERNAL_DRIVE_PATH names the folder directly. The result is the folder
    that contains GTA5.exe.
    """
    try:
        rescan = _as_bool(rescan, False)
        label = (volume_label or agent_config.volume_label()).strip()
        configured = None if volume_label else agent_config.configured_drive_path()
        if configured is not None and not label:
            if not rescan:
                saved = _load_saved_game()
                if saved and _is_gta5_exe(Path(saved["path"]) / "GTA5.exe"):
                    return _ok(
                        f"Using the saved game folder {saved['path']}.",
                        game_root=saved["path"],
                        drive=saved.get("drive", ""),
                        volume_label=saved.get("volume_label", ""),
                        cached=True,
                    )
            folder = _search_for_gta5(configured)
            if folder is None:
                return _err(f"No GTA5.exe was found under {configured}.")
            _save_game(folder, label or configured.name, str(configured))
            return _ok(
                f"Found GTA5.exe in {folder}.",
                game_root=str(folder),
                drive=str(configured),
                volume_label=label or configured.name,
                cached=False,
            )
        if not label:
            return _err(
                "No external drive is configured. Set EXTERNAL_DRIVE_LABEL "
                "to the volume name, or EXTERNAL_DRIVE_PATH to the drive folder."
            )
        if os.name != "nt":
            return _err(
                "Drive labels can only be read on Windows. "
                "Set EXTERNAL_DRIVE_PATH to the drive folder."
            )

        if not rescan:
            saved = _load_saved_game()
            if saved and _is_gta5_exe(Path(saved["path"]) / "GTA5.exe"):
                if not saved.get("volume_label") or _labels_match(
                    saved["volume_label"], label
                ):
                    return _ok(
                        f"Using the saved game folder {saved['path']}.",
                        game_root=saved["path"],
                        drive=saved.get("drive", ""),
                        volume_label=saved.get("volume_label", label),
                        cached=True,
                    )

        matches = [
            (root, found)
            for root, found in _volumes()
            if _labels_match(found, label)
        ]
        if not matches:
            seen = [f"{root} ({found})" for root, found in _volumes()]
            detail = ", ".join(seen) if seen else "no labeled volumes were readable"
            return _err(
                f'No connected drive has the volume label "{label}". '
                f"Volumes seen: {detail}."
            )

        errors: list[str] = []
        for root, found in matches:
            print(f'[locate] searching {root} (label "{found}")', flush=True)
            try:
                folder = _search_for_gta5(Path(root))
            except OSError as exc:
                errors.append(f"{root}: {exc}")
                continue
            if folder is not None:
                drive = root.rstrip("\\")
                _save_game(folder, found, drive)
                return _ok(
                    f"Found GTA5.exe in {folder}.",
                    game_root=str(folder),
                    drive=drive,
                    volume_label=found,
                    cached=False,
                )
        extra = f" Scan errors: {'; '.join(errors)}." if errors else ""
        return _err(
            f'No GTA5.exe was found on the drive labeled "{label}".{extra}'
        )
    except Exception as exc:
        return _err(f"locate_gta5_directory failed: {exc}")


def _safe_name(value: str, fallback: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._")
    return (cleaned or fallback)[:80]


def _host_is_public(hostname: str) -> None:
    if not hostname or hostname.casefold() == "localhost":
        raise ValueError("The URL host is not allowed.")
    try:
        addresses = socket_addresses(hostname)
    except OSError as exc:
        raise ValueError(f"Could not resolve {hostname}: {exc}") from exc
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            raise ValueError(
                f"Refusing to download from a non-public address ({address})."
            )


def socket_addresses(hostname: str) -> list[str]:
    import socket

    infos = socket.getaddrinfo(hostname, None)
    found: list[str] = []
    for info in infos:
        address = info[4][0]
        if address not in found:
            found.append(address.split("%", 1)[0])
    return found


def _filename_from_response(url: str, headers: Any) -> str:
    disposition = headers.get("Content-Disposition", "") if headers else ""
    match = re.search(r"filename\*?=(?:UTF-8''|\")?([^\";]+)", disposition, re.I)
    if match:
        return _safe_name(unquote(match.group(1)).strip('"'), "download.zip")
    name = Path(unquote(urlparse(url).path)).name
    return _safe_name(name or "download.zip", "download.zip")


def _zip_target(dest: Path, name: str) -> Path:
    normalized = name.replace("\\", "/")
    if not rules.protect("archive_path_safety"):
        cleaned = [p for p in normalized.split("/") if p not in {"", "."}]
        return dest.joinpath(*cleaned).resolve() if cleaned else dest
    if normalized.startswith("/") or re.match(r"^[A-Za-z]:", normalized):
        raise ValueError(f"Unsafe path in archive: {name}")
    parts = [part for part in normalized.split("/") if part not in {"", "."}]
    if not parts:
        return dest
    if any(part == ".." for part in parts):
        raise ValueError(f"Unsafe path in archive: {name}")
    target = dest.joinpath(*parts).resolve()
    if target != dest and dest not in target.parents:
        raise ValueError(f"Unsafe path in archive: {name}")
    return target


def _is_zip_symlink(info: zipfile.ZipInfo) -> bool:
    mode = info.external_attr >> 16
    return stat.S_ISLNK(mode)


def _extract_zip(zip_path: Path, dest: Path) -> dict[str, Any]:
    dest.mkdir(parents=True, exist_ok=True)
    dest_resolved = dest.resolve()
    written = 0
    with zipfile.ZipFile(zip_path) as archive:
        infos = [info for info in archive.infolist() if info.filename]
        if rules.limit("archive_size_caps") and len(infos) > MAX_ZIP_FILES:
            raise ValueError(
                f"The archive has {len(infos)} entries, above the limit of {MAX_ZIP_FILES}."
            )
        total_size = sum(info.file_size for info in infos)
        if rules.limit("archive_size_caps") and total_size > MAX_UNCOMPRESSED_BYTES:
            raise ValueError(
                "The archive expands past the "
                f"{MAX_UNCOMPRESSED_BYTES // (1024**3)} GiB limit."
            )
        for info in infos:
            if info.flag_bits & 0x1:
                raise ValueError(
                    f"The archive entry is encrypted and was skipped: {info.filename}. "
                    "Use a zip that is not password protected."
                )
            if rules.protect("archive_path_safety") and _is_zip_symlink(info):
                raise ValueError(
                    f"The archive contains a link, which was refused: {info.filename}"
                )
            target = _zip_target(dest_resolved, info.filename)
            if info.is_dir() or info.filename.endswith("/"):
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info, "r") as source, target.open("wb") as output:
                shutil.copyfileobj(source, output)
            written += 1
    return {"files_written": written, "uncompressed_bytes": total_size}


def _extension_counts(root: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        suffix = path.suffix.lower() or "(none)"
        counts[suffix] = counts.get(suffix, 0) + 1
    return dict(sorted(counts.items()))


def _require_public_http_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"https", "http"} or not parsed.hostname:
        raise ValueError("Only http and https URLs can be downloaded.")
    if rules.limit("public_urls_only"):
        _host_is_public(parsed.hostname)
    return url


def download_and_extract_zip(url: str, folder_name: str = "") -> dict[str, Any]:
    """Download a zip with requests, extract it, and delete the zip.

    Files land in the app workspace. Nothing is copied into the game here.
    Each redirect is checked before it is followed.
    """
    return _download_and_extract(url, folder_name, {"zip"}, "download_and_extract_zip")


def download_mod_from_web(url: str, folder_name: str = "") -> dict[str, Any]:
    """Download a .zip, .7z, or .rar mod archive and extract it locally.

    The archive is deleted after a successful extract. Nothing is copied into
    the game. RAR files need 7-Zip installed on this PC.
    """
    blocked = _blocked_source(url)
    if blocked:
        return _err(blocked)
    return _download_and_extract(
        url, folder_name, {"zip", "7z", "rar"}, "download_mod_from_web"
    )


def _download_and_extract(
    url: str,
    folder_name: str,
    allowed: set[str],
    tool_name: str,
) -> dict[str, Any]:
    temp_path: Path | None = None
    response = None
    try:
        import requests

        if not isinstance(url, str) or not url.strip():
            return _err("A download URL is required.")
        current = _require_public_http_url(url.strip())
        downloads = WORKSPACE / "downloads"
        downloads.mkdir(parents=True, exist_ok=True)
        parsed = urlparse(current)
        print(f"[download] GET {parsed.scheme}://{parsed.hostname}{parsed.path}", flush=True)

        session = requests.Session()
        for _hop in range(6):
            response = session.get(
                current,
                stream=True,
                timeout=(20, 120),
                allow_redirects=False,
                headers={"User-Agent": "Pedro_Agent/1.0"},
            )
            if response.status_code not in {301, 302, 303, 307, 308}:
                break
            location = response.headers.get("Location", "")
            response.close()
            response = None
            if not location:
                return _err("The download redirected without a destination.")
            current = _require_public_http_url(urljoin(current, location))
            parsed = urlparse(current)
            print(f"[download] redirect {parsed.scheme}://{parsed.hostname}{parsed.path}", flush=True)
        else:
            return _err("The download redirected too many times.")

        assert response is not None
        with response:
            if response.status_code != 200:
                return _err(
                    f"Download failed with HTTP {response.status_code} for {response.url}."
                )
            declared = response.headers.get("Content-Length")
            if declared and declared.isdigit() and int(declared) > MAX_DOWNLOAD_BYTES and rules.limit("archive_size_caps"):
                return _err(
                    "The file is larger than the "
                    f"{MAX_DOWNLOAD_BYTES // (1024**3)} GiB download limit."
                )
            filename = _filename_from_response(response.url, response.headers)
            handle = tempfile.NamedTemporaryFile(
                prefix="mod-",
                suffix=".zip",
                dir=downloads,
                delete=False,
            )
            temp_path = Path(handle.name)
            received = 0
            with handle:
                for chunk in response.iter_content(chunk_size=256 * 1024):
                    if not chunk:
                        continue
                    received += len(chunk)
                    if received > MAX_DOWNLOAD_BYTES and rules.limit("archive_size_caps"):
                        raise ValueError(
                            "The download exceeded the "
                            f"{MAX_DOWNLOAD_BYTES // (1024**3)} GiB limit."
                        )
                    handle.write(chunk)

        if temp_path.stat().st_size < 4:
            return _err("The download was empty.")
        try:
            kind = _archive_kind(temp_path, filename)
        except ValueError as exc:
            return _err(str(exc))
        if kind not in allowed:
            return _err(
                f"The download is a {kind} archive. This tool accepts "
                f"{', '.join(sorted(allowed))}."
            )
        result = _extract_saved_archive(temp_path, filename, folder_name, kind)
        temp_path = None
        return result
    except Exception as exc:
        return _err(f"{tool_name} failed: {exc}")
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def _blocked_source(text: str) -> str | None:
    if text and PIRACY_TERMS.search(text):
        return (
            "This assistant installs single-player mods. It does not download "
            "game copies, repacks, or cracks."
        )
    return None


def _archive_kind(path: Path, filename: str) -> str:
    with path.open("rb") as raw:
        magic = raw.read(8)
    if magic.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")):
        return "zip"
    if magic.startswith(b"7z\xbc\xaf'\x1c"):
        return "7z"
    if magic.startswith(b"Rar!\x1a\x07"):
        return "rar"
    label = filename or path.name
    raise ValueError(f"The file is not a zip, 7z, or rar archive ({label}).")


def _check_archive_names(dest: Path, names: list[str]) -> None:
    files = [name for name in names if name and name not in {".", "/", "\\"}]
    if rules.limit("archive_size_caps") and len(files) > MAX_ZIP_FILES:
        raise ValueError(
            f"The archive has {len(files)} entries, above the limit of {MAX_ZIP_FILES}."
        )
    for name in files:
        _zip_target(dest, name)


def _seven_zip_exe() -> Path | None:
    candidates: list[Path] = []
    for env_name in ("ProgramFiles", "ProgramFiles(x86)"):
        root = os.environ.get(env_name)
        if root:
            candidates.append(Path(root) / "7-Zip" / "7z.exe")
    candidates.append(Path(r"C:\Program Files\7-Zip\7z.exe"))
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _seven_zip_names(archive: Path, exe: Path) -> list[str]:
    proc = subprocess.run(
        [str(exe), "l", "-slt", str(archive)],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "7-Zip could not read the archive.").strip()
        raise ValueError(detail[-500:])
    if "Encrypted = +" in proc.stdout:
        raise ValueError("The archive is encrypted. Use one that is not password protected.")
    names = [
        line.split("=", 1)[1].strip()
        for line in proc.stdout.splitlines()
        if line.startswith("Path = ")
    ]
    return names[1:] if names else []


def _extract_with_7zip(archive: Path, dest: Path, exe: Path | None = None) -> dict[str, Any]:
    program = exe or _seven_zip_exe()
    if program is None:
        raise ValueError("7-Zip is not installed, so this archive could not be opened.")
    names = _seven_zip_names(archive, program)
    dest.mkdir(parents=True, exist_ok=True)
    _check_archive_names(dest.resolve(), names)
    proc = subprocess.run(
        [str(program), "x", "-y", f"-o{dest}", str(archive)],
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "7-Zip failed.").strip()
        raise ValueError(detail[-500:])
    written = sum(1 for name in names if not name.endswith(("/", "\\")))
    return {"files_written": written, "uncompressed_bytes": archive.stat().st_size}


def _extract_7z(archive: Path, dest: Path) -> dict[str, Any]:
    try:
        import py7zr
    except ImportError:
        return _extract_with_7zip(archive, dest)
    dest.mkdir(parents=True, exist_ok=True)
    dest_resolved = dest.resolve()
    try:
        with py7zr.SevenZipFile(archive, mode="r") as opened:
            if hasattr(opened, "getnames"):
                names = list(opened.getnames())
            else:
                names = [item.filename for item in opened.list()]
            _check_archive_names(dest_resolved, names)
            opened.extractall(path=dest)
    except Exception as exc:
        if "password" in type(exc).__name__.casefold() or "password" in str(exc).casefold():
            raise ValueError(
                "The archive is encrypted. Use one that is not password protected."
            ) from exc
        raise
    written = sum(1 for name in names if name and not name.endswith(("/", "\\")))
    return {"files_written": written, "uncompressed_bytes": archive.stat().st_size}


def _extract_rar(archive: Path, dest: Path) -> dict[str, Any]:
    if _seven_zip_exe() is None:
        raise ValueError(
            "This is a RAR archive. Install 7-Zip from https://www.7-zip.org/ and try again."
        )
    return _extract_with_7zip(archive, dest)


def _unique_child(parent: Path, stem: str) -> Path:
    parent.mkdir(parents=True, exist_ok=True)
    candidate = parent / stem
    if not candidate.exists():
        return candidate
    suffix = 2
    while (parent / f"{stem}-{suffix}").exists():
        suffix += 1
    return parent / f"{stem}-{suffix}"


def _extract_saved_archive(
    archive: Path,
    filename: str,
    folder_name: str,
    kind: str,
) -> dict[str, Any]:
    stem = _safe_name(folder_name, Path(filename).stem or "mod")
    destination = _unique_child(WORKSPACE / "downloads", stem)
    try:
        if kind == "zip":
            summary = _extract_zip(archive, destination)
        elif kind == "7z":
            summary = _extract_7z(archive, destination)
        elif kind == "rar":
            summary = _extract_rar(archive, destination)
        else:
            raise ValueError(f"Unsupported archive type: {kind}")
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        raise
    archive.unlink(missing_ok=True)
    children = list(destination.iterdir())
    extracted_root = (
        children[0] if len(children) == 1 and children[0].is_dir() else destination
    )
    label = Path(filename).name or archive.name
    return _ok(
        f"Extracted {summary['files_written']} files to {extracted_root}. "
        f"{label} was deleted. Nothing was copied into the game.",
        download_folder=str(destination),
        extracted_root=str(extracted_root),
        files_written=summary["files_written"],
        top_level=[child.name for child in children[:MAX_LISTED_PATHS]],
        extensions=_extension_counts(extracted_root),
    )


class _AnchorParser(HTMLParser):
    """Collect href and visible text from anchor tags."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        values = {key.lower(): value or "" for key, value in attrs}
        href = values.get("href", "").strip()
        if href:
            self._href = href
            self._chunks = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._chunks.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self._href is not None:
            self.links.append((self._href, "".join(self._chunks).strip()))
            self._href = None
            self._chunks = []


def _unwrap_search_url(url: str) -> str:
    parsed = urlparse(url)
    host = (parsed.hostname or "").casefold()
    if "duckduckgo.com" in host:
        target = parse_qs(parsed.query).get("uddg", [])
        if target:
            return unquote(target[0])
    return url


def _is_archive_url(url: str) -> bool:
    path = unquote(urlparse(url).path)
    return Path(path).suffix.casefold() in ARCHIVE_EXTS


def _archive_links_from_html(html: str, base_url: str) -> list[str]:
    parser = _AnchorParser()
    try:
        parser.feed(html)
    except Exception:
        return []
    found: list[str] = []
    seen: set[str] = set()
    for href, _text in parser.links:
        if not href or href.startswith(("#", "javascript:", "mailto:")):
            continue
        absolute = _unwrap_search_url(urljoin(base_url, href.strip()))
        if not _is_archive_url(absolute) or absolute in seen:
            continue
        seen.add(absolute)
        found.append(absolute)
    return found


def _download_anchors(html: str, base_url: str) -> list[str]:
    parser = _AnchorParser()
    try:
        parser.feed(html)
    except Exception:
        return []
    found: list[str] = []
    seen: set[str] = set()
    for href, text in parser.links:
        if not href or href.startswith(("#", "javascript:", "mailto:")):
            continue
        absolute = _unwrap_search_url(urljoin(base_url, href.strip()))
        parsed = urlparse(absolute)
        if parsed.scheme not in {"http", "https"} or _is_archive_url(absolute):
            continue
        if "download" not in f"{href} {text}".casefold():
            continue
        if absolute in seen:
            continue
        seen.add(absolute)
        found.append(absolute)
        if len(found) == 2:
            break
    return found


def _search_rows(query: str, limit: int) -> list[dict[str, str]]:
    try:
        try:
            from ddgs import DDGS
        except ImportError:
            from duckduckgo_search import DDGS  # type: ignore
        raw = DDGS().text(query, max_results=limit) or []
        rows: list[dict[str, str]] = []
        for item in raw:
            href = _unwrap_search_url(str(item.get("href") or item.get("url") or ""))
            if not href:
                continue
            rows.append(
                {
                    "title": str(item.get("title") or ""),
                    "href": href,
                    "body": str(item.get("body") or "")[:300],
                }
            )
        if rows:
            return rows
    except Exception:
        pass
    return _search_duckduckgo_html(query, limit)


def _search_duckduckgo_html(query: str, limit: int) -> list[dict[str, str]]:
    import requests

    response = requests.post(
        "https://html.duckduckgo.com/html/",
        data={"q": query},
        timeout=20,
        headers={"User-Agent": "Mozilla/5.0"},
    )
    response.raise_for_status()
    parser = _AnchorParser()
    parser.feed(response.text)
    rows: list[dict[str, str]] = []
    for href, text in parser.links:
        absolute = _unwrap_search_url(urljoin("https://html.duckduckgo.com/html/", href))
        host = (urlparse(absolute).hostname or "").casefold()
        if not absolute.startswith("http") or "duckduckgo.com" in host:
            continue
        rows.append({"title": text or absolute, "href": absolute, "body": ""})
        if len(rows) >= limit:
            break
    return rows


def _fetch_page(url: str) -> dict[str, Any]:
    import requests

    current = _require_public_http_url(url)
    session = requests.Session()
    response = None
    for _hop in range(4):
        response = session.get(
            current,
            stream=True,
            timeout=(15, 30),
            allow_redirects=False,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/128.0.0.0 Safari/537.36"
                )
            },
        )
        if response.status_code not in {301, 302, 303, 307, 308}:
            break
        location = response.headers.get("Location", "")
        response.close()
        response = None
        if not location:
            raise ValueError("The page redirected without a destination.")
        current = _require_public_http_url(urljoin(current, location))
    else:
        raise ValueError("The page redirected too many times.")
    assert response is not None
    with response:
        if response.status_code != 200:
            raise ValueError(f"HTTP {response.status_code} for {response.url}")
        disposition_name = _filename_from_response(response.url, response.headers)
        content_type = (response.headers.get("Content-Type") or "").casefold()
        archive_name = Path(disposition_name).suffix.casefold() in ARCHIVE_EXTS
        if "html" not in content_type and (_is_archive_url(response.url) or archive_name):
            return {"kind": "file", "url": response.url, "filename": disposition_name}
        chunks: list[bytes] = []
        size = 0
        for chunk in response.iter_content(chunk_size=64 * 1024):
            if not chunk:
                continue
            chunks.append(chunk)
            size += len(chunk)
            if size >= MAX_HTML_BYTES:
                break
        html = b"".join(chunks).decode(response.encoding or "utf-8", errors="replace")
        return {"kind": "html", "url": response.url, "html": html}


def _github_repo(url: str) -> tuple[str, str] | None:
    parsed = urlparse(url)
    host = (parsed.hostname or "").casefold()
    if host not in {"github.com", "www.github.com"}:
        return None
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2:
        return None
    if parts[0].casefold() in {"topics", "features", "search", "orgs", "settings"}:
        return None
    return parts[0], parts[1].removesuffix(".git")


def _github_release_archives(owner: str, repo: str) -> list[str]:
    import requests

    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "Pedro_Agent/1.0",
    }
    response = requests.get(
        f"https://api.github.com/repos/{owner}/{repo}/releases/latest",
        headers=headers,
        timeout=20,
    )
    release: Any
    if response.status_code == 404:
        listing = requests.get(
            f"https://api.github.com/repos/{owner}/{repo}/releases?per_page=1",
            headers=headers,
            timeout=20,
        )
        if listing.status_code != 200:
            return []
        payload = listing.json()
        release = payload[0] if isinstance(payload, list) and payload else None
    elif response.status_code != 200:
        return []
    else:
        release = response.json()
    if not isinstance(release, dict):
        return []
    links: list[str] = []
    for asset in release.get("assets") or []:
        link = str(asset.get("browser_download_url") or "")
        if _is_archive_url(link):
            links.append(link)
    return links


def _page_download_links(page_url: str) -> list[str]:
    if _is_archive_url(page_url):
        return [page_url]
    repo = _github_repo(page_url)
    if repo is not None:
        return _github_release_archives(*repo)[:8]
    fetched = _fetch_page(page_url)
    if fetched["kind"] == "file":
        return [str(fetched["url"])]
    links = _archive_links_from_html(str(fetched["html"]), str(fetched["url"]))
    if links:
        return links[:8]
    for hop in _download_anchors(str(fetched["html"]), str(fetched["url"])):
        try:
            nested = _fetch_page(hop)
        except Exception:
            continue
        if nested["kind"] == "file":
            links.append(str(nested["url"]))
        else:
            links.extend(_archive_links_from_html(str(nested["html"]), str(nested["url"])))
    unique: list[str] = []
    for link in links:
        if link not in unique:
            unique.append(link)
    return unique[:8]


def search_and_find_mod_download(query: str, max_results: int = 5) -> dict[str, Any]:
    """Search the web for a mod and collect direct archive links.

    Pages that only have a login or a scripted download button are returned
    without a file URL. This does not bypass those pages.
    """
    try:
        if not isinstance(query, str) or not query.strip():
            return _err("A search query is required, for example Simple Zombies Reborn GTA 5.")
        blocked = _blocked_source(query)
        if blocked:
            return _err(blocked)
        try:
            limit = int(max_results)
        except (TypeError, ValueError):
            limit = 5
        limit = min(8, max(1, limit))
        rows = _search_rows(query.strip(), limit)
        if not rows:
            return _err(f'No web results for "{query.strip()}".')
        pages: list[dict[str, Any]] = []
        direct_count = 0
        for row in rows:
            entry: dict[str, Any] = {
                "title": row["title"],
                "page_url": row["href"],
                "snippet": row["body"],
                "download_urls": [],
            }
            try:
                entry["download_urls"] = _page_download_links(row["href"])
            except Exception as exc:
                entry["note"] = str(exc)
            direct_count += len(entry["download_urls"])
            pages.append(entry)
            if direct_count >= 3:
                break
        if any(page["download_urls"] for page in pages):
            message = (
                f"Found {sum(len(page['download_urls']) for page in pages)} "
                f"direct archive link(s) across {len(pages)} page(s)."
            )
        else:
            message = (
                "Search found pages, but none exposed a direct .zip, .7z, or .rar link. "
                "Call scan_user_downloads_folder, or tell the user which page was found."
            )
        return _ok(message, query=query.strip(), pages=pages)
    except Exception as exc:
        return _err(f"search_and_find_mod_download failed: {exc}")


def _downloads_folder() -> Path:
    if downloads_override is not None:
        return downloads_override
    return Path.home() / "Downloads"


def _query_tokens(query: str) -> list[str]:
    tokens: list[str] = []
    for token in re.split(r"[^A-Za-z0-9]+", query.casefold()):
        if len(token) >= 3 and token not in NAME_STOP_WORDS:
            tokens.append(token)
    return tokens


def _name_score(filename: str, tokens: list[str]) -> int:
    stem = Path(filename).stem.casefold()
    return sum(1 for token in tokens if token in stem)


def _extract_local_archive(archive: Path, folder_name: str) -> dict[str, Any]:
    kind = _archive_kind(archive, archive.name)
    workspace = WORKSPACE / "downloads"
    workspace.mkdir(parents=True, exist_ok=True)
    temporary = workspace / f"local-{_safe_name(archive.name, 'mod')}"
    shutil.copy2(archive, temporary)
    try:
        return _extract_saved_archive(temporary, archive.name, folder_name, kind)
    finally:
        temporary.unlink(missing_ok=True)


def scan_user_downloads_folder(name_query: str, extract: bool = False) -> dict[str, Any]:
    """Find recent archives in the user's Downloads folder.

    extract is used only when a filename matches name_query. The original
    file in Downloads is left in place.
    """
    try:
        extract = _as_bool(extract, False)
        query = (name_query or "").strip()
        if not query:
            return _err("name_query is required, for example Simple Zombies Reborn.")
        blocked = _blocked_source(query)
        if blocked:
            return _err(blocked)
        folder = _downloads_folder()
        if not folder.is_dir():
            return _err(f"The Downloads folder does not exist: {folder}")
        tokens = _query_tokens(query)
        archives = [
            path
            for path in folder.iterdir()
            if path.is_file() and path.suffix.casefold() in ARCHIVE_EXTS
        ]
        ranked = []
        for path in archives:
            stat_result = path.stat()
            ranked.append(
                {
                    "name": path.name,
                    "path": str(path),
                    "score": _name_score(path.name, tokens),
                    "size_bytes": stat_result.st_size,
                    "modified": int(stat_result.st_mtime),
                }
            )
        matches = sorted(
            (item for item in ranked if item["score"] > 0),
            key=lambda item: (item["score"], item["modified"]),
            reverse=True,
        )[:8]
        recent = sorted(ranked, key=lambda item: item["modified"], reverse=True)[:5]
        if not extract:
            if matches:
                message = f'Found {len(matches)} archive(s) in {folder} matching "{query}".'
            else:
                message = f'No archive name in {folder} matches "{query}".'
            return _ok(message, folder=str(folder), matches=matches, recent=recent)
        if not matches:
            return _err(
                f'No archive name in {folder} matches "{query}", so nothing was extracted.',
                recent=recent,
            )
        best = matches[0]
        extracted = _extract_local_archive(Path(best["path"]), Path(best["name"]).stem)
        if not extracted.get("ok"):
            return extracted
        extracted["matched_file"] = best["path"]
        extracted["message"] = (
            f"Extracted {best['name']} from Downloads to {extracted.get('extracted_root')}. "
            "Nothing was copied into the game."
        )
        return extracted
    except Exception as exc:
        return _err(f"scan_user_downloads_folder failed: {exc}")


def _inside(root: Path, candidate: Path) -> bool:
    root_resolved = root.resolve()
    target = candidate.resolve()
    return target == root_resolved or root_resolved in target.parents


def _game_relative(game: Path, destination: str) -> str:
    text = (destination or "").strip().strip('"')
    if text in {"", ".", "./", ".\\"}:
        return ""
    path = Path(text)
    if path.is_absolute():
        resolved = path.resolve()
        try:
            return str(resolved.relative_to(game.resolve()))
        except ValueError as exc:
            if not rules.limit("mod_writes_in_game_folder_only"):
                return str(resolved)
            raise ValueError(
                f"Destination is outside the game folder: {destination}"
            ) from exc
    return text.lstrip("\\/")


def _resolve_in_game(game: Path, relative: str) -> Path:
    relative = _game_relative(game, relative)
    if not relative:
        return game.resolve()
    raw = Path(relative)
    if not rules.limit("mod_writes_in_game_folder_only"):
        target = raw.resolve() if raw.is_absolute() else (game / raw).resolve()
        if not _path_is_allowed(target):
            raise ValueError(rules.allowed_path_message())
        return target
    if raw.is_absolute() or ".." in raw.parts:
        raise ValueError(f"Path escapes the game folder: {relative}")
    target = (game / raw).resolve()
    if not _inside(game, target):
        raise ValueError(f"Path escapes the game folder: {relative}")
    return target


def _protected_reason(path: Path) -> str | None:
    """files.allow_exe_writes / files.blocked_extensions in rules.yaml."""
    return rules.file_write_reason(path)


def _prepare_dest_file(dest: Path, overwrite: bool) -> str | None:
    reason = _protected_reason(dest)
    if reason:
        return reason
    if dest.exists() and dest.is_dir():
        return f"A folder already exists at {dest}."
    if dest.exists() and not overwrite:
        return f"Already exists, left unchanged: {dest}"
    if dest.exists() and overwrite:
        try:
            dest.chmod(dest.stat().st_mode | stat.S_IWRITE)
        except OSError:
            pass
    return None


def _copy_one(source: Path, dest: Path, overwrite: bool) -> str | None:
    """Copy one file. Return an error string when the file is skipped."""
    reason = _prepare_dest_file(dest, overwrite)
    if reason:
        return reason
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copy2(source, dest)
    except PermissionError as exc:
        return (
            f"Could not write {dest.name}. Close Grand Theft Auto V if it is "
            f"running, then try again. System message: {exc}"
        )
    except OSError as exc:
        return f"Could not copy {source.name} to {dest}: {exc}"
    return None


def _iter_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for current, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [
            name
            for name in dirnames
            if name.casefold() not in {"__macosx", ".git"}
        ]
        for filename in filenames:
            if filename.casefold() in {".ds_store", "thumbs.db"}:
                continue
            files.append(Path(current) / filename)
    return files


def _copy_tree(source: Path, dest_root: Path, overwrite: bool) -> dict[str, Any]:
    copied: list[str] = []
    skipped: list[str] = []
    for file_path in _iter_files(source):
        relative = file_path.relative_to(source)
        destination = dest_root / relative
        problem = _copy_one(file_path, destination, overwrite)
        display = str(relative)
        if problem:
            skipped.append(f"{display}: {problem}")
        else:
            copied.append(display)
    return {"copied": copied, "skipped": skipped}


def _pack_name(name: str) -> str:
    cleaned = _safe_name(name, "")
    if not cleaned:
        raise ValueError(
            "pack_name must contain letters or numbers, for example horror_ped."
        )
    return cleaned


def _has_anchor(relative: Path) -> int | None:
    markers = {"mods", "scripts", "dlcpacks"}
    for index, part in enumerate(relative.parts):
        if part.casefold() in markers:
            return index
    return None


def destination_for(
    game: Path,
    relative: Path,
    pack_name: str,
    layout: str,
) -> Path | None:
    """Return the file path inside the game folder, or None when skipped.

    auto keeps an existing mods, scripts, or dlcpacks tree. Loader DLLs and
    .asi files still go next to GTA5.exe. Other scripts go to scripts/. Model
    files go to mods/update/x64/dlcpacks/<pack_name>/, unless layout is
    addon_peds.
    """
    if layout not in LAYOUTS:
        raise ValueError(
            f'Unknown layout "{layout}". Use auto, addon_peds, dlcpack, scripts, or game_root.'
        )
    extension = relative.suffix.casefold()
    filename = relative.name.casefold()
    if extension == ".exe":
        return None

    if layout == "auto":
        anchor = _has_anchor(relative)
        if anchor is not None:
            parts = relative.parts
            marker = parts[anchor].casefold()
            if marker == "dlcpacks":
                tail = Path(*parts[anchor:])
                return game / "mods" / "update" / "x64" / tail
            return game.joinpath(*parts[anchor:])

    if extension == ".asi" or filename in ROOT_FILES:
        return game / relative.name
    if layout == "auto" and extension == ".ini":
        return game / relative.name

    if layout == "addon_peds":
        return game / "scripts" / "AddonPeds" / pack_name / relative
    if layout == "scripts" or (layout == "auto" and extension in SCRIPT_EXTS):
        return game / "scripts" / relative
    if layout == "game_root":
        return game / relative.name
    return game / "mods" / "update" / "x64" / "dlcpacks" / pack_name / relative


def _trim(items: list[str]) -> dict[str, Any]:
    return {
        "count": len(items),
        "sample": items[:MAX_LISTED_PATHS],
        "truncated": len(items) > MAX_LISTED_PATHS,
    }


def _finish_copy(
    game: Path,
    copied: list[str],
    skipped: list[str],
    notes: list[str],
) -> dict[str, Any]:
    if not copied and skipped:
        return _err(
            "No files were copied. "
            + skipped[0],
            game_root=str(game),
            skipped=_trim(skipped),
            notes=notes,
        )
    if not copied:
        return _err("No files were copied. The source folder had no usable files.")
    message = f"Copied {len(copied)} file(s) into {game}."
    if skipped:
        message += f" Skipped {len(skipped)}."
    return _ok(
        message,
        game_root=str(game),
        copied=_trim(copied),
        skipped=_trim(skipped),
        notes=notes,
    )


def create_directory(relative_path: str) -> dict[str, Any]:
    """Create a folder inside the GTA V directory.

    relative_path is relative to the game root, such as "scripts" or
    "mods/update/x64/dlcpacks".
    """
    try:
        if not isinstance(relative_path, str) or not relative_path.strip():
            return _err("relative_path is required, for example scripts.")
        game = _game_root().resolve()
        target = _resolve_in_game(game, relative_path)
        if target == game.resolve():
            return _err("Refusing to treat the game folder itself as a new directory.")
        if target.exists() and not target.is_dir():
            return _err(f"A file already exists at {target}, so a folder was not created.")
        import undo_store
        fresh = not target.exists()
        if fresh:
            undo_store.remember(target, directory=True)
        target.mkdir(parents=True, exist_ok=True)
        if fresh:
            undo_store.seal(target)
        return _ok(
            f"Folder is ready: {target}",
            game_root=str(game),
            path=str(target),
            relative_path=str(target.relative_to(game.resolve())),
        )
    except Exception as exc:
        return _err(f"create_directory failed: {exc}")


def copy_mod_files(
    source_path: str,
    destination: str,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Copy a file or folder into the GTA V directory.

    destination is relative to the game root. A file copied to a folder lands
    inside that folder. A folder copied onto a path with the same folder name
    merges into it.
    """
    try:
        overwrite = _as_bool(overwrite, False)
        if not isinstance(source_path, str) or not source_path.strip():
            return _err("source_path is required.")
        source = Path(source_path.strip().strip('"')).expanduser()
        if not source.exists():
            return _err(f"Source path does not exist: {source}")
        game = _game_root().resolve()
        relative = _game_relative(game, destination or "")
        landing = _resolve_in_game(game, relative)

        if source.is_file():
            if relative == "" or landing.is_dir() or (
                not landing.suffix and not landing.exists()
            ):
                target_dir = game if relative == "" else landing
                target = target_dir / source.name
            else:
                target = landing
            if not _inside(game, target):
                return _err(f"Destination is outside the game folder: {destination}")
            problem = _copy_one(source, target, overwrite)
            if problem:
                return _err(problem, game_root=str(game))
            return _ok(
                f"Copied {source.name} to {target}.",
                game_root=str(game),
                destination=str(target),
            )

        if not source.is_dir():
            return _err(f"Source is not a file or folder: {source}")
        if landing.name.casefold() == source.name.casefold():
            dest_root = landing
        elif relative == "":
            dest_root = game / source.name
        else:
            dest_root = landing / source.name
        if not _inside(game, dest_root):
            return _err(f"Destination is outside the game folder: {destination}")
        if _inside(source, dest_root) or source.resolve() == dest_root.resolve():
            return _err("Refusing to copy a folder into itself.")
        result = _copy_tree(source, dest_root, overwrite)
        return _finish_copy(game, result["copied"], result["skipped"], [])
    except Exception as exc:
        return _err(f"copy_mod_files failed: {exc}")


def integrate_custom_assets(
    source_dir: str,
    pack_name: str = "custom_pack",
    layout: str = "auto",
    overwrite: bool = False,
) -> dict[str, Any]:
    """Map an extracted mod folder into the GTA V mod layout.

    layout is auto, addon_peds, dlcpack, scripts, or game_root.
    auto keeps a mods, scripts, or dlcpacks tree when the zip already has one.
    Otherwise .asi and loader DLLs go to the game root, other scripts go to
    scripts/, and model files go to mods/update/x64/dlcpacks/<pack_name>/.
    addon_peds sends the tree to scripts/AddonPeds/<pack_name>/.
    """
    try:
        overwrite = _as_bool(overwrite, False)
        layout = (layout or "auto").strip().casefold()
        if layout not in LAYOUTS:
            return _err(
                f'Unknown layout "{layout}". Use auto, addon_peds, dlcpack, scripts, or game_root.'
            )
        if not isinstance(source_dir, str) or not source_dir.strip():
            return _err("source_dir is required.")
        source = Path(source_dir.strip().strip('"')).expanduser()
        if not source.is_dir():
            return _err(f"Source folder does not exist: {source}")
        pack = _pack_name(pack_name or "custom_pack")
        game = _game_root().resolve()
        files = _iter_files(source)
        if not files:
            return _err(f"No files were found in {source}.")

        copied: list[str] = []
        skipped: list[str] = []
        placed_loose_models = False
        saw_rpf = False
        for file_path in files:
            relative = file_path.relative_to(source)
            if file_path.suffix.casefold() == ".rpf":
                saw_rpf = True
            target = destination_for(game, relative, pack, layout)
            if target is None:
                skipped.append(f"{relative}: this file type is not installed")
                continue
            if not _inside(game, target):
                skipped.append(f"{relative}: destination escaped the game folder")
                continue
            if _inside(source, target):
                skipped.append(f"{relative}: destination is inside the source folder")
                continue
            if (
                file_path.suffix.casefold() in MODEL_EXTS
                and "dlcpacks" in {part.casefold() for part in target.parts}
            ):
                placed_loose_models = True
            problem = _copy_one(file_path, target, overwrite)
            if problem:
                skipped.append(f"{relative}: {problem}")
            else:
                copied.append(str(target.relative_to(game.resolve())))

        notes: list[str] = []
        if placed_loose_models and not saw_rpf:
            notes.append(
                "Loose model files were placed under the mods folder. GTA V reads "
                "these from .rpf archives. Import them with OpenIV, and add the "
                "pack to dlclist.xml, before the game can stream them."
            )
        if layout == "addon_peds":
            notes.append(
                f"Files were placed in scripts/AddonPeds/{pack}. AddonPeds still "
                "needs its menu mod and a rebuilt peds archive if this folder is "
                "only loose .ydd, .yft, and .ytd files."
            )
        return _finish_copy(game, copied, skipped, notes)
    except Exception as exc:
        return _err(f"integrate_custom_assets failed: {exc}")


def _clean_app_name(app_name: str) -> str:
    text = " ".join((app_name or "").strip().casefold().split())
    for prefix in ("open ", "launch ", "start "):
        if text.startswith(prefix):
            text = text[len(prefix):].strip()
    return text


def _app_score(query: str, candidate: str) -> int:
    wanted = _clean_app_name(query)
    name = Path(candidate).stem.casefold()
    if not wanted or not name:
        return 0
    if wanted == name:
        return 100
    if wanted in name:
        return 90
    tokens = [token for token in re.split(r"[^a-z0-9]+", wanted) if token]
    if tokens and all(token in name for token in tokens):
        return 85
    return 0


def _lookup_installed_exe(exe_name: str) -> Path | None:
    if os.name != "nt":
        return None
    import winreg

    subkeys = (
        r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths",
        r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths",
    )
    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for subkey in subkeys:
            try:
                with winreg.OpenKey(root, subkey + "\\" + exe_name) as key:
                    value, _ = winreg.QueryValueEx(key, "")
            except OSError:
                continue
            candidate = Path(str(value).strip().strip('"'))
            if candidate.is_file():
                return candidate
    found = shutil.which(exe_name)
    if found:
        return Path(found)
    return None


def _start_menu_dirs() -> list[Path]:
    if start_menu_override is not None:
        return [start_menu_override]
    roots: list[Path] = []
    appdata = os.environ.get("APPDATA")
    programdata = os.environ.get("PROGRAMDATA")
    if appdata:
        roots.append(Path(appdata) / "Microsoft" / "Windows" / "Start Menu")
    if programdata:
        roots.append(Path(programdata) / "Microsoft" / "Windows" / "Start Menu")
    return [path for path in roots if path.is_dir()]


def _best_start_menu_match(app_name: str) -> Path | None:
    matches: list[tuple[int, int, Path]] = []
    for root in _start_menu_dirs():
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix.casefold() not in {".lnk", ".exe"}:
                continue
            score = _app_score(app_name, path.name)
            if score:
                matches.append((score, -len(path.stem), path))
    if not matches:
        return None
    matches.sort(reverse=True)
    best_score = matches[0][0]
    tied = [item for item in matches if item[0] == best_score]
    if len({item[2].stem.casefold() for item in tied}) > 1:
        names = ", ".join(item[2].stem for item in tied[:5])
        raise ValueError(f'More than one app matches. Be more specific. Matches: {names}.')
    return matches[0][2]


def _resolve_application(app_name: str) -> Path | str:
    cleaned = _clean_app_name(app_name)
    if not cleaned:
        raise ValueError("An application name is required, for example excel.")
    if re.search(r"[&|;<>`$\\\n\r]", app_name):
        raise ValueError("The application name contains characters that are not allowed.")
    for exe_name in KNOWN_APPS.get(cleaned, []):
        installed = _lookup_installed_exe(exe_name)
        if installed is not None:
            return installed
    menu_match = _best_start_menu_match(cleaned)
    if menu_match is not None:
        return menu_match
    if cleaned in KNOWN_APPS:
        return KNOWN_APPS[cleaned][0]
    raise ValueError(f'No installed application matches "{app_name}".')


def _start_target(target: Path | str) -> None:
    if os.name != "nt":
        raise RuntimeError("Opening desktop apps is supported on Windows.")
    os.startfile(str(target))  # The target is a resolved app, not a shell command.


def launch_application(app_name: str) -> dict[str, Any]:
    """Open a desktop application by name.

    Matches Excel, Chrome, Notepad, Word, Power BI, SSMS, and other Start
    Menu shortcuts. The name is not passed to a shell.
    """
    try:
        if not isinstance(app_name, str):
            return _err("app_name is required.")
        target = _resolve_application(app_name)
        _start_target(target)
        return _ok(f"Opened {app_name}.", target=str(target))
    except Exception as exc:
        return _err(f"launch_application failed: {exc}")


def _known_launch_name(name: str) -> str:
    key = " ".join((name or "").casefold().split())
    if not key:
        return ""
    if key in KNOWN_APPS:
        return key
    for known in sorted(KNOWN_APPS, key=len, reverse=True):
        if key.startswith(known + " "):
            return known
    return ""


def _finish_claimed_launch(reply: str, emit: Callable[..., None], user_text: str = "") -> str:
    """Open the app or link a reply claims to be opening, when no open tool has run."""
    import grounding

    if _wingz_on():
        return reply
    link = grounding.claimed_link(reply, user_text)
    if link and not grounding.launch_done():
        blob = f"{user_text}\n{reply}".casefold()
        tool = "watch_video" if re.search(r"\b(watch|watching|context)\b", blob) else "open_website"
        emit("tool_start", name=tool, arguments={"url": link})
        result = invoke_tool(tool, {"url": link})
        emit(
            "tool_end",
            name=tool,
            ok=bool(result.get("ok")),
            detail=_scrub(str(result.get("message") or result.get("error") or ""))[:400],
        )
        grounding.note("open_website", result)
        if result.get("ok"):
            return str(result.get("message") or f"Opened {link}.")
        return str(result.get("error") or f"Could not open {link}.")

    def launch(app: str) -> dict[str, Any]:
        emit("tool_start", name="launch_application", arguments={"app_name": app})
        result = invoke_tool("launch_application", {"app_name": app})
        emit(
            "tool_end",
            name="launch_application",
            ok=bool(result.get("ok")),
            detail=_scrub(str(result.get("message") or result.get("error") or ""))[:400],
        )
        return result

    return grounding.carry_out_launch(reply, _known_launch_name, launch)


def _public_http_url(url: str) -> str:
    text = (url or "").strip()
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Only an http or https address can be opened.")
    return text


_VIDEO_EXTS = {".mp4", ".webm", ".mkv", ".mov", ".avi", ".m4v", ".wmv", ".mpeg", ".mpg"}
# Tests set these. None uses the real browser, the page, and the screen.
link_open_override: Callable[[str, str], None] | None = None
link_text_override: Callable[[str], str] | None = None
watch_screen_override: Any = None


def _openable_link(url: str) -> tuple[str, str]:
    """A web address, including a video link, or a video file on this PC."""
    raw = (url or "").strip().strip("<>\"'")
    if not raw:
        raise ValueError("Which link?")
    if len(raw) > 2000:
        raise ValueError("That link is too long.")
    lowered = raw.casefold()
    if lowered.startswith(("javascript:", "data:", "file:", "vbscript:")):
        raise ValueError("Only an http or https address, or a video file on this PC, can be opened.")
    path = Path(os.path.expandvars(raw)).expanduser()
    if path.suffix.casefold() in _VIDEO_EXTS and path.is_file():
        return "file", str(path)
    candidate = raw
    if not re.match(r"https?://", candidate, re.I):
        if re.match(r"^[A-Za-z0-9.-]+\.[A-Za-z]{2,}([/:?].*)?$", candidate):
            candidate = "https://" + candidate
        else:
            raise ValueError("That is not a link. Pass an https address or a video file on this PC.")
    parsed = urlparse(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Only an http or https address can be opened.")
    if parsed.username or parsed.password:
        raise ValueError("The address cannot contain a username or password.")
    return "web", candidate


def _open_on_desktop(kind: str, target: str) -> None:
    if link_open_override is not None:
        link_open_override(kind, target)
        return
    if kind == "web" and navigate_override is not None:
        navigate_override(target)
        return
    if kind == "web":
        webbrowser.open(target)
        return
    if os.name == "nt":
        os.startfile(target)  # A video file the user named, not a shell command.
        return
    subprocess.Popen(["xdg-open", target])


def _open_link(url: str) -> dict[str, Any]:
    kind, target = _openable_link(url)
    _open_on_desktop(kind, target)
    if kind == "file":
        return _ok(f"Opened the video file {Path(target).name}.", path=target, kind="file")
    return _ok(f"Opened {target} in the browser.", url=target, kind="web")


def open_website(url: str) -> dict[str, Any]:
    """Open a web link, a video link, or a video file on this PC."""
    try:
        return _open_link(url)
    except Exception as exc:
        return _err(f"open_website failed: {exc}")


def _fetch_link_text(url: str) -> str:
    if link_text_override is not None:
        return link_text_override(url)
    import urllib.request

    request = urllib.request.Request(url, headers={"User-Agent": "PedroAgent"})
    with urllib.request.urlopen(request, timeout=8) as response:
        return response.read(200_000).decode("utf-8", "replace")


def _meta_content(html: str, key: str) -> str:
    import html as html_lib

    patterns = (
        rf"<meta[^>]+(?:property|name)=[\"']{re.escape(key)}[\"'][^>]+content=[\"'](.*?)[\"']",
        rf"<meta[^>]+content=[\"'](.*?)[\"'][^>]+(?:property|name)=[\"']{re.escape(key)}[\"']",
    )
    for pattern in patterns:
        match = re.search(pattern, html or "", re.I | re.S)
        if match:
            return " ".join(html_lib.unescape(re.sub(r"<[^>]+>", " ", match.group(1))).split())[:800]
    return ""


def _read_link_context(text: str) -> dict[str, str]:
    raw = (text or "").strip()
    if raw.startswith("{"):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = {}
        if isinstance(data, dict) and (data.get("title") or data.get("author_name")):
            return {
                "title": " ".join(str(data.get("title") or "").split())[:200],
                "by": " ".join(str(data.get("author_name") or "").split())[:120],
                "description": " ".join(str(data.get("description") or "").split())[:800],
            }
    title = _meta_content(raw, "og:title") or _meta_content(raw, "title")
    if not title:
        match = re.search(r"<title[^>]*>(.*?)</title>", raw, re.I | re.S)
        if match:
            import html as html_lib

            title = " ".join(html_lib.unescape(re.sub(r"<[^>]+>", " ", match.group(1))).split())[:200]
    return {
        "title": title,
        "by": _meta_content(raw, "author")[:120],
        "description": _meta_content(raw, "og:description") or _meta_content(raw, "description"),
    }


def _link_context(kind: str, target: str) -> dict[str, str]:
    if kind == "file":
        path = Path(target)
        size = path.stat().st_size if path.is_file() else 0
        return {
            "title": path.name,
            "by": "",
            "description": f"Video file on this PC, {size / (1024 * 1024):.1f} MB.",
        }
    host = (urlparse(target).hostname or "").casefold()
    try:
        if "youtube.com" in host or host == "youtu.be":
            page = _fetch_link_text(
                "https://www.youtube.com/oembed?format=json&url=" + quote(target, safe="")
            )
        else:
            page = _fetch_link_text(target)
    except Exception:
        page = ""
    info = _read_link_context(page)
    if ("youtube.com" in host or host == "youtu.be") and not info.get("description"):
        try:
            extra = _read_link_context(_fetch_link_text(target))
        except Exception:
            extra = {}
        if not info.get("title"):
            info["title"] = extra.get("title") or ""
        info["description"] = extra.get("description") or ""
        if not info.get("by"):
            info["by"] = extra.get("by") or ""
    return info


def _look_for_video() -> dict[str, Any] | None:
    if watch_screen_override is False:
        return None
    if callable(watch_screen_override):
        shot = watch_screen_override()
        return shot if isinstance(shot, dict) else None
    return take_screenshot()


def watch_video(url: str) -> dict[str, Any]:
    """Open a video link or file, then return its title, description, and one picture."""
    try:
        opened = _open_link(url)
    except Exception as exc:
        return _err(f"watch_video failed: {exc}")
    if not opened.get("ok"):
        return opened
    kind = str(opened.get("kind") or "web")
    target = str(opened.get("url") or opened.get("path") or "")
    info = _link_context(kind, target)
    lines = [str(opened.get("message") or "Opened.")]
    if info.get("title"):
        lines.append(f"Title: {info['title']}")
    if info.get("by"):
        lines.append(f"By: {info['by']}")
    if info.get("description"):
        lines.append(f"Description: {info['description']}")
    lines.append(
        "One look after the video opened. This is not the whole video. "
        "Describe only this title, this description, and the attached picture. "
        "Do not invent scenes that are not there."
    )
    result = _ok(
        "\n".join(lines),
        url=str(opened.get("url") or ""),
        path=str(opened.get("path") or ""),
        title=info.get("title") or "",
        by=info.get("by") or "",
        description=info.get("description") or "",
        kind=kind,
    )
    if kind == "web" and watch_screen_override is not False and link_open_override is None:
        time.sleep(2)
    shot = _look_for_video()
    if isinstance(shot, dict) and shot.get("ok") and shot.get("_screenshot_bytes"):
        result["_screenshot_bytes"] = shot.get("_screenshot_bytes")
        result["_screenshot_mime"] = shot.get("_screenshot_mime") or "image/jpeg"
        if shot.get("path"):
            result["path"] = str(shot.get("path"))
    return result


def _youtube_search_url(search_query: str) -> str:
    query = " ".join((search_query or "").split())
    if not query:
        raise ValueError("A YouTube search query is required.")
    if len(query) > 200:
        raise ValueError("The YouTube search is too long.")
    return "https://www.youtube.com/results?search_query=" + quote_plus(query)


def search_youtube(search_query: str) -> dict[str, Any]:
    """Open YouTube search results for a query in the default browser."""
    try:
        target = _youtube_search_url(search_query)
        webbrowser.open(target)
        return _ok(f"Opened YouTube search for {search_query.strip()}.", url=target)
    except Exception as exc:
        return _err(f"search_youtube failed: {exc}")


def _external_drive_root() -> Path | None:
    """External drive from EXTERNAL_DRIVE_PATH, or the labeled volume."""
    configured = agent_config.configured_drive_path()
    if configured is not None:
        return configured
    if os.name != "nt":
        return None
    try:
        return agent_config.match_volume(_volumes())
    except Exception:
        return None


def _drive_path_message() -> str:
    return agent_config.allowed_path_message()


def _resolve_drive_text(text: str) -> Path | None:
    """An external-drive path, None when text is an ordinary path."""
    parsed = agent_config.split_drive_prefix(text)
    if parsed is None:
        return None
    _name, relative = parsed
    root = _external_drive_root()
    if root is None:  # no external drive: never stop, save locally instead
        root = agent_config.default_output_dir()
    if relative and ".." in Path(relative).parts and rules.limit("reject_dotdot_paths"):
        raise ValueError("The path cannot contain '..'.")
    return root / relative if relative else root


def _is_blocked_system_path(path: Path) -> bool:
    """paths.blocked in rules.yaml (defaults: Windows and Program Files)."""
    external = _external_drive_root()
    return rules.path_blocked(path, WORKSPACE.resolve(), external.resolve() if external else None)


def _path_is_allowed(path: Path) -> bool:
    """paths.allowed / paths.blocked in rules.yaml decide. Blocked wins."""
    external = _external_drive_root()
    return rules.path_allowed(
        path.resolve(), WORKSPACE.resolve(), external.resolve() if external else None
    )


def _resolve_user_path(file_path: str, suffix: str | tuple[str, ...]) -> Path:
    text = (file_path or "").strip().strip('"')
    if not text:
        raise ValueError("A file path is required.")
    drive_target = _resolve_drive_text(text)
    if drive_target is not None:
        target = drive_target
    else:
        target = Path(text).expanduser()
        if ".." in target.parts and rules.limit("reject_dotdot_paths"):
            raise ValueError("The path cannot contain '..'.")
    allowed = (suffix,) if isinstance(suffix, str) else suffix
    if target.suffix == "":
        target = target.with_suffix(allowed[0])
    if target.suffix.casefold() not in {item.casefold() for item in allowed}:
        allowed_text = ", ".join(allowed)
        raise ValueError(f"The file must use one of these extensions: {allowed_text}.")
    resolved = target.resolve()
    if not _path_is_allowed(resolved):
        raise ValueError(agent_config.allowed_path_message())
    return resolved


def _excel_cell(value: Any) -> Any:
    if value is None or isinstance(value, (int, float, bool)):
        return value
    if not isinstance(value, str):
        raise ValueError("Each cell must be text, a number, true, false, or null.")
    if len(value) > 2000:
        raise ValueError("A cell is longer than 2000 characters.")
    upper = value.lstrip().upper()
    if (
        rules.limit("excel_block_risky_formulas")
        and upper.startswith("=")
        and any(token in upper for token in UNSAFE_EXCEL)
    ):
        raise ValueError("That Excel formula is not allowed.")
    return value


def _sheet_specs(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if "sheets" in payload:
        sheets = payload["sheets"]
        if not isinstance(sheets, list) or not sheets:
            raise ValueError('The "sheets" value must be a non-empty list.')
        return sheets
    return [payload]


def _write_sheet(workbook: Any, spec: dict[str, Any]) -> str:
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter

    if not isinstance(spec, dict):
        raise ValueError("Each sheet description must be a JSON object.")
    title = str(spec.get("sheet") or spec.get("name") or "Sheet1")[:31]
    headers = spec.get("headers")
    rows = spec.get("rows")
    if not isinstance(headers, list) or not headers:
        raise ValueError('Each sheet needs a "headers" list.')
    if not isinstance(rows, list):
        raise ValueError('Each sheet needs a "rows" list.')
    if len(headers) > 50 or len(rows) > 5000:
        raise ValueError("A sheet is limited to 50 columns and 5000 rows.")
    if title in workbook.sheetnames:
        sheet = workbook[title]
        workbook.remove(sheet)
    sheet = workbook.create_sheet(title)
    for column, header in enumerate(headers, start=1):
        cell = sheet.cell(1, column, _excel_cell(header))
        cell.font = Font(bold=True)
        cell.fill = PatternFill(fill_type="solid", fgColor="D9E2F3")
    for row_index, row in enumerate(rows, start=2):
        if not isinstance(row, list):
            raise ValueError("Each row must be a list of cells.")
        if len(row) > len(headers):
            raise ValueError("A row has more cells than there are headers.")
        for column, value in enumerate(row, start=1):
            sheet.cell(row_index, column, _excel_cell(value))
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    for column, header in enumerate(headers, start=1):
        width = min(40, max(12, len(str(header)) + 2))
        sheet.column_dimensions[get_column_letter(column)].width = width
    return title


def automate_excel_task(file_path: str, task_instructions: str) -> dict[str, Any]:
    """Create or update an .xlsx workbook from JSON instructions.

    Example task_instructions:
    {"sheet":"Sales","headers":["Item","Amount"],"rows":[["Hats",12]]}
    A path starting with "external/" is saved on that drive.
    """
    try:
        from openpyxl import Workbook, load_workbook

        target = _resolve_user_path(file_path, ".xlsx")
        try:
            payload = json.loads(task_instructions or "")
        except json.JSONDecodeError as exc:
            return _err(
                "task_instructions must be JSON, for example "
                '{"sheet":"Sales","headers":["Item","Amount"],"rows":[["Hats",12]]}. '
                f"Could not parse it: {exc}"
            )
        if not isinstance(payload, dict):
            return _err("task_instructions JSON must be an object.")
        if target.is_file():
            workbook = load_workbook(target)
        else:
            workbook = Workbook()
            default = workbook.active
            if default is not None and default.title == "Sheet" and default.max_row == 1:
                workbook.remove(default)
        written = [_write_sheet(workbook, spec) for spec in _sheet_specs(payload)]
        if not workbook.sheetnames:
            raise ValueError("The workbook has no sheets.")
        target.parent.mkdir(parents=True, exist_ok=True)
        workbook.save(target)
        return _ok(
            f"Saved {target.name} with sheet(s): {', '.join(written)}.",
            path=str(target),
            sheets=written,
        )
    except Exception as exc:
        return _err(f"automate_excel_task failed: {exc}")


def _sql_text(query: str) -> str:
    without_block = re.sub(r"/\*.*?\*/", " ", query, flags=re.S)
    without_line = re.sub(r"--.*?$", " ", without_block, flags=re.M)
    parts = [part.strip() for part in without_line.split(";") if part.strip()]
    if len(parts) != 1:
        raise ValueError("Send one SQL statement at a time.")
    statement = parts[0]
    if rules.limit("sql_safe_mode") and BLOCKED_SQL.search(statement):
        raise ValueError("That SQL statement is not allowed.")
    return statement


def _sql_kind(statement: str) -> str:
    match = re.match(r"\s*([A-Za-z]+)", statement)
    if not match:
        raise ValueError("The SQL statement is empty.")
    return match.group(1).upper()


def _connection_is_odbc(connection: str) -> bool:
    return bool(re.search(r"(?i)\b(driver|server|data\s+source)\s*=", connection))


def _odbc_server_is_local(connection: str) -> bool:
    match = re.search(r"(?i)(?:server|data\s+source)\s*=\s*([^;]+)", connection)
    if not match:
        return False
    server = match.group(1).strip().strip('"').strip("'")
    host = server.split("\\", 1)[0].split(",", 1)[0].strip().casefold()
    return host in {"", ".", "(local)", "localhost", "127.0.0.1", "(localdb)"} or host.startswith(
        "(localdb)"
    )


def _redact_connection(text: str) -> str:
    return re.sub(r"(?i)(password\s*=\s*)[^;]*", r"\1***", text)


def _open_database(connection: str, read_only: bool) -> Any:
    text = (connection or "").strip().strip('"')
    if not text:
        raise ValueError("A sqlite file path or local SQL Server connection string is required.")
    if _connection_is_odbc(text):
        if rules.limit("sql_local_servers_only") and not _odbc_server_is_local(text):
            raise ValueError("SQL Server connections are limited to this PC (localhost).")
        try:
            import pyodbc
        except ImportError as exc:
            raise ValueError(
                "SQL Server needs the pyodbc package and a local ODBC driver. "
                "A sqlite file path works without them."
            ) from exc
        return pyodbc.connect(text, timeout=15)
    if text.casefold().startswith("sqlite:///"):
        text = text[len("sqlite:///") :]
    db_path = _resolve_user_path(text, (".db", ".sqlite", ".sqlite3"))
    if read_only:
        if not db_path.is_file():
            raise ValueError(f"Database file does not exist: {db_path}")
        return sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(db_path)


def _write_query_output(path: Path, columns: list[str], rows: list[tuple[Any, ...]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.casefold() == ".csv":
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(columns)
            writer.writerows(rows)
        return
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    if sheet is None:
        raise ValueError("Could not create a worksheet.")
    sheet.title = "Query"
    sheet.append(columns)
    for row in rows:
        sheet.append(list(row))
    workbook.save(path)


def execute_sql_task(
    db_connection_str: str,
    query: str,
    output_path: str = "",
    allow_changes: bool = False,
) -> dict[str, Any]:
    """Run one SQL statement against a local sqlite file or local SQL Server.

    SELECT results can be saved to a .csv or .xlsx path. Changes require
    allow_changes. Remote servers and shell procedures are refused.
    """
    connection = None
    try:
        allow_changes = _as_bool(allow_changes, False)
        statement = _sql_text(query or "")
        kind = _sql_kind(statement)
        read_kinds = {"SELECT", "WITH", "EXPLAIN", "PRAGMA"}
        write_kinds = {"INSERT", "UPDATE", "DELETE", "CREATE", "DROP", "ALTER", "REPLACE"}
        if kind in {"PRAGMA"}:
            allowed_pragma = re.match(
                r"(?i)\s*pragma\s+(table_info|database_list|table_list|index_list)\b",
                statement,
            )
            if not allowed_pragma:
                return _err("Only table_info, database_list, table_list, and index_list PRAGMA calls are allowed.")
        elif kind not in read_kinds and kind not in write_kinds:
            return _err(f"The SQL statement type {kind} is not allowed.")
        if kind in write_kinds and not allow_changes:
            return _err(
                "This statement would change the database. Ask the user, then call again "
                "with allow_changes true."
            )
        output: Path | None = None
        if str(output_path or "").strip():
            suffix = Path(str(output_path).strip().strip('"')).suffix.casefold() or ".csv"
            if suffix not in {".csv", ".xlsx"}:
                return _err("output_path must be a .csv or .xlsx file.")
            output = _resolve_user_path(str(output_path), suffix)
        connection = _open_database(db_connection_str, read_only=kind not in write_kinds)
        cursor = connection.cursor()
        cursor.execute(statement)
        if kind in write_kinds:
            connection.commit()
            return _ok(
                f"{kind} finished. Rows affected: {cursor.rowcount}.",
                rows_affected=cursor.rowcount,
            )
        columns = [str(item[0]) for item in cursor.description or []]
        fetched = cursor.fetchmany(100_001)
        truncated = len(fetched) == 100_001
        rows = fetched[:100_000]
        saved = ""
        if output is not None:
            _write_query_output(output, columns, rows)
            saved = str(output)
        preview = [
            [None if value is None else str(value)[:200] for value in row]
            for row in rows[:30]
        ]
        message = f"Query returned {len(rows)} row(s)."
        if truncated:
            message += " The result was cut at 100000 rows."
        if saved:
            message += f" Saved {saved}."
        return _ok(
            message,
            columns=columns,
            row_count=len(rows),
            preview=preview,
            output_path=saved,
            truncated=truncated,
        )
    except Exception as exc:
        return _err(f"execute_sql_task failed: {_redact_connection(str(exc))}")
    finally:
        if connection is not None:
            connection.close()


MEMORY_TOPICS = {"identity", "preference", "path", "instruction", "fact"}
_MEMORY_TOPIC_ORDER = {
    "identity": 0,
    "preference": 1,
    "path": 2,
    "instruction": 3,
    "fact": 4,
}
_SECRET_FACT = re.compile(
    r"(api[_ -]?key|password|passwd|secret|token|credential)\s*[:=]|bearer\s+[a-z0-9]",
    re.IGNORECASE,
)


def _account_name() -> str:
    return os.environ.get("USERNAME", "").strip() or os.environ.get("USER", "").strip()


def _memory_path() -> Path:
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    return WORKSPACE / "memory.sqlite"


def _memory_connect() -> sqlite3.Connection:
    connection = sqlite3.connect(_memory_path())
    connection.row_factory = sqlite3.Row
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic TEXT NOT NULL,
            fact TEXT NOT NULL,
            fact_key TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    return connection


def _memory_key(fact: str) -> str:
    return " ".join(fact.casefold().split())


def _memory_is_secret(text: str) -> bool:
    if _SECRET_FACT.search(text):
        return True
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    return bool(key) and key in text


def _memory_rows() -> list[sqlite3.Row]:
    connection = _memory_connect()
    try:
        return list(
            connection.execute(
                "SELECT topic, fact, updated_at FROM memories ORDER BY updated_at DESC"
            )
        )
    finally:
        connection.close()


def _topic_exists(topic: str) -> bool:
    connection = _memory_connect()
    try:
        row = connection.execute(
            "SELECT 1 FROM memories WHERE topic = ? LIMIT 1",
            (topic,),
        ).fetchone()
    finally:
        connection.close()
    return row is not None


def remember_fact(fact: str, topic: str = "fact") -> dict[str, Any]:
    """Save one lasting fact. The same wording updates the existing row."""
    text = " ".join((fact or "").split())
    if not text:
        return _err("fact is required.")
    if len(text) > 500:
        text = text[:500].rsplit(" ", 1)[0] or text[:500]
    topic_name = " ".join((topic or "fact").split()).casefold()
    if topic_name not in MEMORY_TOPICS:
        return _err(
            "topic must be identity, preference, path, instruction, or fact."
        )
    if rules.limit("refuse_secret_text") and _memory_is_secret(text):
        return _err("That fact looks like a password or API key, so it was not saved.")
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    key = _memory_key(text)
    connection = _memory_connect()
    try:
        existing = connection.execute(
            "SELECT id, topic, fact FROM memories WHERE fact_key = ?",
            (key,),
        ).fetchone()
        if existing and existing["topic"] == topic_name and existing["fact"] == text:
            return _ok("The fact is already saved.", topic=topic_name, fact=text)
        if existing:
            connection.execute(
                "UPDATE memories SET topic = ?, fact = ?, updated_at = ? WHERE id = ?",
                (topic_name, text, now, existing["id"]),
            )
            message = "Updated the saved fact."
        else:
            connection.execute(
                """
                INSERT INTO memories (topic, fact, fact_key, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (topic_name, text, key, now, now),
            )
            message = "Saved the fact."
        connection.commit()
    finally:
        connection.close()
    return _ok(message, topic=topic_name, fact=text)


def _seed_memory() -> None:
    """Record the Windows account and a cached game path once."""
    account = _account_name()
    if account and not _topic_exists("identity"):
        remember_fact(f"The Windows account name is {account}.", "identity")
    saved = _load_saved_game()
    if not saved or not saved.get("path"):
        return
    label = saved.get("volume_label") or agent_config.volume_label() or "external"
    fact = f"GTA V is at {saved['path']} on the volume labeled {label}."
    drive = str(saved.get("drive") or "").strip()
    if drive:
        fact += f" The drive letter last seen was {drive}."
    remember_fact(fact, "path")


def _search_memories(query: str, limit: int = 20) -> list[dict[str, str]]:
    rows = _memory_rows()
    tokens = [
        token
        for token in re.split(r"[^a-z0-9]+", query.casefold())
        if len(token) > 1
    ]
    if tokens:
        scored: list[tuple[int, sqlite3.Row]] = []
        for row in rows:
            haystack = f"{row['topic']} {row['fact']}".casefold()
            score = sum(1 for token in tokens if token in haystack)
            if score:
                scored.append((score, row))
        scored.sort(key=lambda item: (item[0], item[1]["updated_at"]), reverse=True)
        chosen = [row for _, row in scored]
    else:
        newest_first = sorted(rows, key=lambda row: row["updated_at"], reverse=True)
        chosen = sorted(
            newest_first,
            key=lambda row: _MEMORY_TOPIC_ORDER.get(row["topic"], 9),
        )
    matches: list[dict[str, str]] = []
    for row in chosen[:limit]:
        matches.append(
            {
                "topic": str(row["topic"]),
                "fact": str(row["fact"]),
                "updated_at": str(row["updated_at"]),
            }
        )
    return matches


def recall_memory(query: str = "") -> dict[str, Any]:
    """Search saved facts. An empty query returns the current memory list."""
    _seed_memory()
    text = " ".join((query or "").split())
    matches = _search_memories(text)
    if not matches:
        return _ok("No matching memories.", matches=[], query=text)
    return _ok(
        f"Found {len(matches)} memory item(s).",
        matches=matches,
        query=text,
    )


def memory_prompt_block() -> str:
    """Short fact list inserted into the Gemini system prompt."""
    _seed_memory()
    matches = _search_memories("", limit=20)
    if not matches:
        return ""
    lines = ["Known facts saved on this computer:"]
    for item in matches:
        lines.append(f"- [{item['topic']}] {item['fact']}")
    block = "\n".join(lines)
    if len(block) > 2000:
        block = block[:2000].rsplit("\n", 1)[0]
    return block


def system_prompt() -> str:
    block = memory_prompt_block()
    if not block:
        return SYSTEM_PROMPT
    return f"{SYSTEM_PROMPT}\n{block}\n"


def _capture_user_memory(text: str) -> None:
    """Save an obvious name, preference, or 'remember that' phrase."""
    raw = " ".join((text or "").split())
    if not raw or _memory_is_secret(raw):
        return
    name = re.search(r"\bmy name is\s+([A-Za-z][A-Za-z' -]{0,40})", raw, re.IGNORECASE)
    if name:
        cleaned = name.group(1).strip(" .")
        if cleaned:
            remember_fact(f"The user's name is {cleaned}.", "identity")
    preference = re.search(
        r"\bI (?:prefer|like) to\s+(.{3,160}?)(?:\.|$)",
        raw,
        re.IGNORECASE,
    )
    if preference:
        remember_fact(
            f"The user prefers to {preference.group(1).strip(' .')}.",
            "preference",
        )
    instruction = re.search(
        r"\bremember that\s+(.{3,300}?)(?:\.|$)",
        raw,
        re.IGNORECASE,
    )
    if instruction:
        remember_fact(instruction.group(1).strip(" ."), "instruction")


def _autosave_tool_memory(name: str, result: dict[str, Any]) -> None:
    """Keep completed game paths without asking the model to save them."""
    if not result.get("ok"):
        return
    try:
        if name == "locate_gta5_directory":
            root = str(result.get("game_root") or "").strip()
            if not root:
                return
            label = str(result.get("volume_label") or agent_config.volume_label() or "external").strip()
            fact = f"GTA V is at {root} on the volume labeled {label}."
            drive = str(result.get("drive") or "").strip()
            if drive:
                fact += f" The drive letter last seen was {drive}."
            remember_fact(fact, "path")
        elif name == "create_directory":
            relative = str(result.get("relative_path") or "").strip()
            root = str(result.get("game_root") or "").strip()
            if relative and root:
                remember_fact(
                    f"Created the game folder {relative} under {root}.",
                    "path",
                )
        elif name in {"copy_mod_files", "integrate_custom_assets"}:
            root = str(result.get("game_root") or "").strip()
            if root:
                remember_fact(
                    f"Last file copy into the game finished under {root}.",
                    "path",
                )
    except Exception:
        return


SCREENSHOT_MAX_WIDTH = 1280
SCREENSHOT_JPEG_QUALITY = 80
# DirectShow can still block inside the driver. The agent stops waiting here.
WEBCAM_TIMEOUT_SECONDS = 4.0
RECORD_MAX_SECONDS = 600
RECORD_FPS = 8
CLIPBOARD_TEXT_LIMIT = 12000
MAX_PLAN_STEPS = 8
MAX_ACTION_BATCH = 12
TYPE_TEXT_LIMIT = 500

def _desktop():
    """Load pyautogui only when a real pointer or screen action runs."""
    try:
        import pyautogui
    except ImportError as exc:
        raise RuntimeError(
            "pyautogui is not installed. From the project folder run: "
            ".\\.venv\\Scripts\\python.exe -m pip install pyautogui"
        ) from exc
    return mouse_controller.configure_desktop(pyautogui)


def _failsafe_message(exc: BaseException) -> str | None:
    if type(exc).__name__ == "FailSafeException":
        return (
            "Stopped because the pointer is in a screen corner. "
            "Move it away from the corner and try again."
        )
    return None


def _screen_size() -> tuple[int, int]:
    if screen_size_override is not None:
        width, height = screen_size_override
        return int(width), int(height)
    size = _desktop().size()
    return int(size[0]), int(size[1])


def _grid_value(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number from 0 to 1000.")
    number = float(value)
    if number < 0 or number > mouse_controller.GRID:
        raise ValueError(f"{name} must be from 0 to 1000.")
    return number


def _shown_grid(number: float) -> int | float:
    if number == int(number):
        return int(number)
    return number


def _encode_screenshot(image: Any) -> tuple[bytes, int, int, str]:
    """Shrink a screen image to a JPEG the model can read quickly."""
    width, height = image.size
    if width > SCREENSHOT_MAX_WIDTH:
        new_width = SCREENSHOT_MAX_WIDTH
        new_height = max(1, round(height * (new_width / width)))
        image = image.resize((new_width, new_height))
    image_w, image_h = image.size
    buffer = io.BytesIO()
    image.convert("RGB").save(
        buffer,
        format="JPEG",
        quality=SCREENSHOT_JPEG_QUALITY,
        subsampling=0,
    )
    return buffer.getvalue(), int(image_w), int(image_h), "image/jpeg"


def _fit_screenshot(
    raw: bytes, screen_w: int, screen_h: int
) -> tuple[bytes, int, int, float, str]:
    try:
        from PIL import Image
    except ImportError:
        return raw, screen_w, screen_h, 1.0, "image/png"
    try:
        image = Image.open(io.BytesIO(raw))
        image.load()
    except Exception:
        return raw, screen_w, screen_h, 1.0, "image/png"
    image = mouse_controller.align_to_screen(image, screen_w, screen_h)
    data, image_w, image_h, mime = _encode_screenshot(image)
    scale = round(image_w / screen_w, 4) if screen_w else 1.0
    return data, int(image_w), int(image_h), scale, mime


def _capture_override() -> tuple[bytes, int, int]:
    captured = screenshot_override() if screenshot_override is not None else {}
    raw = captured.get("png")
    if not isinstance(raw, (bytes, bytearray)) or not raw:
        raise ValueError("The screenshot capture returned no image.")
    return bytes(raw), int(captured["screen_width"]), int(captured["screen_height"])


def _grab_mss_image() -> tuple[Any, int, int]:
    """Capture the primary screen from memory with mss."""
    try:
        import mss
    except ImportError as exc:
        raise RuntimeError(
            "mss is not installed. From the project folder run: "
            ".\\.venv\\Scripts\\python.exe -m pip install mss"
        ) from exc
    from PIL import Image

    screen_w, screen_h = _screen_size()
    with mss.mss() as sct:
        monitors = list(sct.monitors)
        if not monitors:
            raise RuntimeError("mss did not find a screen.")
        monitor = monitors[1] if len(monitors) > 1 else monitors[0]
        shot = sct.grab(monitor)
        image = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
    if screen_w < 1 or screen_h < 1:
        screen_w, screen_h = image.size
    image = mouse_controller.align_to_screen(image, screen_w, screen_h)
    return image, int(screen_w), int(screen_h)


def take_screenshot() -> dict[str, Any]:
    """Capture the screen and attach the image for the model."""
    try:
        import desktop_share
        with desktop_share.hold():
            if screenshot_override is not None:
                raw, screen_w, screen_h = _capture_override()
                if screen_w < 1 or screen_h < 1:
                    return _err("The screen size is not available.")
                data, image_w, image_h, scale, mime = _fit_screenshot(raw, screen_w, screen_h)
            else:
                image, screen_w, screen_h = _grab_mss_image()
                if screen_w < 1 or screen_h < 1:
                    return _err("The screen size is not available.")
                data, image_w, image_h, mime = _encode_screenshot(image)
                scale = round(image_w / screen_w, 4) if screen_w else 1.0
        folder = WORKSPACE / "screenshots"
        folder.mkdir(parents=True, exist_ok=True)
        png_path = folder / "latest.png"
        jpg_path = folder / "latest.jpg"
        path = jpg_path if mime == "image/jpeg" else png_path
        path.write_bytes(data)
        other = png_path if path == jpg_path else jpg_path
        if other.exists():
            other.unlink()
        return _ok(
            (
                f"Captured the screen. Physical screen is {screen_w}x{screen_h} pixels. "
                f"Image is {image_w}x{image_h}. "
                "click_element uses a 0-1000 grid. "
                "0,0 is the top-left and 1000,1000 is the bottom-right. "
                "Do not send image pixels."
            ),
            path=str(path),
            screen_width=screen_w,
            screen_height=screen_h,
            image_width=image_w,
            image_height=image_h,
            scale=scale,
            grid=mouse_controller.GRID,
            _screenshot_bytes=data,
            _screenshot_mime=mime,
        )
    except AssertionError:
        raise
    except Exception as exc:
        failsafe = _failsafe_message(exc)
        if failsafe:
            return _err(failsafe)
        return _err(f"take_screenshot failed: {exc}")


def _image_bytes_to_jpeg(raw: bytes) -> tuple[bytes, int, int, str]:
    """Resize an injected webcam frame the same way as a screenshot."""
    try:
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError(
            "pillow is not installed. From the project folder run: "
            ".\\.venv\\Scripts\\python.exe -m pip install pillow"
        ) from exc
    try:
        image = Image.open(io.BytesIO(raw))
        image.load()
    except Exception as exc:
        raise RuntimeError(f"The webcam image could not be read: {exc}") from exc
    return _encode_screenshot(image)


def _webcam_backend(cv2: Any) -> int:
    """DirectShow on Windows. The default backend can block for minutes."""
    if sys.platform == "win32" and hasattr(cv2, "CAP_DSHOW"):
        return int(cv2.CAP_DSHOW)
    return int(getattr(cv2, "CAP_ANY", 0))


def _set_camera_prop(camera: Any, prop: Any, value: Any) -> None:
    if prop is None:
        return
    try:
        camera.set(prop, value)
    except Exception:
        pass


def _snap_directshow_jpeg(cv2: Any) -> tuple[bytes, int, int]:
    """Open the default camera with DirectShow, write one JPEG, and release it."""
    camera = cv2.VideoCapture()
    try:
        timeout_ms = int(WEBCAM_TIMEOUT_SECONDS * 1000)
        _set_camera_prop(camera, getattr(cv2, "CAP_PROP_OPEN_TIMEOUT_MSEC", None), timeout_ms)
        _set_camera_prop(camera, getattr(cv2, "CAP_PROP_READ_TIMEOUT_MSEC", None), timeout_ms)
        backend = _webcam_backend(cv2)
        opened = camera.open(0, backend)
        if not opened or not camera.isOpened():
            raise RuntimeError(
                "Could not access the webcam. It may be in use by another app "
                "or blocked by Windows privacy settings."
            )
        _set_camera_prop(camera, getattr(cv2, "CAP_PROP_BUFFERSIZE", None), 1)
        ok, frame = camera.read()
        if not ok or frame is None:
            raise RuntimeError("Failed to grab a frame from the webcam.")
        shape = getattr(frame, "shape", None)
        if not shape or len(shape) < 2:
            raise RuntimeError("Failed to grab a frame from the webcam.")
        height, width = int(shape[0]), int(shape[1])
        if width > SCREENSHOT_MAX_WIDTH and hasattr(cv2, "resize"):
            new_width = SCREENSHOT_MAX_WIDTH
            new_height = max(1, round(height * (new_width / width)))
            frame = cv2.resize(frame, (new_width, new_height))
            width, height = new_width, new_height
        WORKSPACE.mkdir(parents=True, exist_ok=True)
        path = WORKSPACE / "vision_capture.jpg"
        if not cv2.imwrite(str(path), frame):
            raise RuntimeError("Failed to save the webcam frame.")
        data = path.read_bytes()
        if not data:
            raise RuntimeError("Failed to save the webcam frame.")
        return data, width, height
    finally:
        camera.release()


def _grab_webcam_jpeg() -> tuple[bytes, int, int]:
    """Run one DirectShow snap on a side thread so a stuck driver cannot freeze the agent."""
    try:
        import cv2
    except ImportError as exc:
        raise RuntimeError(
            "opencv-python is not installed. From the project folder run: "
            ".\\.venv\\Scripts\\python.exe -m pip install opencv-python"
        ) from exc
    box: dict[str, Any] = {}

    def worker() -> None:
        try:
            box["value"] = _snap_directshow_jpeg(cv2)
        except Exception as exc:
            box["error"] = exc

    worker_thread = threading.Thread(target=worker, name="webcam-snap", daemon=True)
    worker_thread.start()
    worker_thread.join(WEBCAM_TIMEOUT_SECONDS)
    if worker_thread.is_alive():
        raise TimeoutError(
            "The webcam did not respond in time. It may be in use by another "
            "app or blocked by Windows privacy settings."
        )
    if "error" in box:
        raise box["error"]
    data, width, height = box["value"]
    return data, int(width), int(height)


def _camera_dir() -> Path:
    folder = WORKSPACE / "camera"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _unique_camera_file(suffix: str) -> Path:
    """A new file under workspace/camera. Older shots stay downloadable."""
    stamp = time.strftime("%Y%m%d-%H%M%S")
    ms = int((time.time() % 1) * 1000)
    folder = _camera_dir()
    candidate = folder / f"camera-{stamp}-{ms:03d}{suffix}"
    extra = 0
    while candidate.exists():
        extra += 1
        candidate = folder / f"camera-{stamp}-{ms:03d}-{extra}{suffix}"
    return candidate


def _copy_camera_still(data: bytes) -> Path:
    path = _unique_camera_file(".jpg")
    path.write_bytes(data)
    return path


def _record_length(seconds: Any) -> int | None:
    """Whole seconds from 1 to 600. Missing or out of range records nothing."""
    if seconds is None or isinstance(seconds, bool):
        return None
    if isinstance(seconds, str):
        text = seconds.strip()
        if not text:
            return None
        try:
            number = float(text)
        except ValueError:
            return None
    elif isinstance(seconds, (int, float)):
        number = float(seconds)
    else:
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    length = int(round(number))
    if length < 1 or length > RECORD_MAX_SECONDS:
        return None
    return length


def _record_now() -> float:
    if record_clock is not None:
        return float(record_clock())
    return time.monotonic()


def _record_wait(delay: float) -> None:
    if delay <= 0:
        return
    if record_wait is not None:
        record_wait(delay)
        return
    time.sleep(delay)


def capture_webcam_image() -> dict[str, Any]:
    """Snap one webcam frame, save it, and close the camera before returning.

    Windows uses DirectShow. If the camera does not answer within a few
    seconds, this returns an error instead of blocking the agent. The image
    is attached to the tool result so Gemini can see it.
    """
    try:
        if webcam_override is not None:
            captured = webcam_override()
            raw = captured.get("jpeg") or captured.get("png") or captured.get("image")
            if not isinstance(raw, (bytes, bytearray)) or not raw:
                return _err("The webcam capture returned no image.")
            data, image_w, image_h, mime = _image_bytes_to_jpeg(bytes(raw))
            WORKSPACE.mkdir(parents=True, exist_ok=True)
            path = WORKSPACE / "vision_capture.jpg"
            path.write_bytes(data)
        else:
            data, image_w, image_h = _grab_webcam_jpeg()
            mime = "image/jpeg"
            path = WORKSPACE / "vision_capture.jpg"
        download = _copy_camera_still(data)
        return _ok(
            (
                "Captured one webcam frame and closed the camera. "
                f"Image is {image_w}x{image_h}. "
                "The picture is saved and can be downloaded from the chat. "
                "Describe what is visible. "
                "Do not capture again unless the user asks for another look."
            ),
            path=str(path),
            download_path=str(download),
            image_width=image_w,
            image_height=image_h,
            _screenshot_bytes=data,
            _screenshot_mime=mime,
        )
    except AssertionError:
        raise
    except Exception as exc:
        return _err(f"capture_webcam_image failed: {exc}")


def _video_result(path: Path, seconds: int, poster: bytes, width: int, height: int) -> dict[str, Any]:
    extra: dict[str, Any] = {
        "path": str(path),
        "download_path": str(path),
        "video": str(path),
        "seconds": seconds,
        "image_width": width,
        "image_height": height,
    }
    if poster:
        extra["_screenshot_bytes"] = poster
        extra["_screenshot_mime"] = "image/jpeg"
    unit = "second" if seconds == 1 else "seconds"
    return _ok(
        (
            f"Recorded {seconds} {unit} from the PC camera and closed it. "
            "The video is saved and can be downloaded from the chat. "
            "Describe only the attached picture. Do not invent a download link."
        ),
        **extra,
    )


def _save_camera_video(seconds: int, video: bytes, poster: bytes, width: int, height: int) -> dict[str, Any]:
    path = _unique_camera_file(".mp4")
    path.write_bytes(video)
    return _video_result(path, seconds, poster, width, height)


def _record_from_override(seconds: int) -> dict[str, Any]:
    if record_override is None:
        raise RuntimeError("The camera recorder is not set.")
    captured = record_override(seconds)
    if not isinstance(captured, dict):
        return _err("The camera returned no video.")
    raw = captured.get("mp4") or captured.get("video")
    if not isinstance(raw, (bytes, bytearray)) or len(raw) < 16:
        return _err("The camera returned no video.")
    poster = captured.get("jpeg") or captured.get("image") or b""
    if not isinstance(poster, (bytes, bytearray)):
        poster = b""
    width = int(captured.get("width") or 0)
    height = int(captured.get("height") or 0)
    return _save_camera_video(seconds, bytes(raw), bytes(poster), width, height)


def _fit_record_frame(cv2: Any, frame: Any, width: int | None, height: int | None) -> tuple[Any, int, int]:
    shape = getattr(frame, "shape", None)
    if not shape or len(shape) < 2:
        raise RuntimeError("Failed to grab a frame from the webcam.")
    frame_h, frame_w = int(shape[0]), int(shape[1])
    if width is None or height is None:
        width, height = frame_w, frame_h
        if width > SCREENSHOT_MAX_WIDTH and hasattr(cv2, "resize"):
            width = SCREENSHOT_MAX_WIDTH - (SCREENSHOT_MAX_WIDTH % 2)
            height = max(2, round(frame_h * (width / frame_w)))
            height -= height % 2
        width = max(2, width - (width % 2))
        height = max(2, height - (height % 2))
    if hasattr(cv2, "resize") and (frame_w != width or frame_h != height):
        frame = cv2.resize(frame, (width, height))
    elif frame_w != width or frame_h != height:
        frame = frame[0:height, 0:width]
    return frame, width, height


def _record_ffmpeg_command(width: int, height: int, dest: Path) -> list[str]:
    executable = media_ffmpeg.find_ffmpeg()
    if executable is None:
        raise RuntimeError(
            "ffmpeg is not installed. Install ffmpeg or set FFMPEG_EXECUTABLE. "
            "Nothing was recorded."
        )
    return [
        str(executable),
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "bgr24",
        "-s",
        f"{width}x{height}",
        "-r",
        str(RECORD_FPS),
        "-i",
        "pipe:0",
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(dest),
    ]


def _spawn_record_ffmpeg(command: list[str]) -> Any:
    if record_process_override is not None:
        return record_process_override(command)
    flags: dict[str, Any] = {}
    if os.name == "nt":
        flags["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        shell=False,
        **flags,
    )


def _write_record_frame(proc: Any, frame: Any) -> None:
    stdin = getattr(proc, "stdin", None)
    if stdin is None:
        raise RuntimeError("ffmpeg did not accept the camera frames.")
    raw = frame.tobytes() if hasattr(frame, "tobytes") else bytes(frame)
    stdin.write(raw)
    flush = getattr(stdin, "flush", None)
    if flush is not None:
        flush()


def _poster_jpeg(cv2: Any, frame: Any) -> bytes:
    encoder = getattr(cv2, "imencode", None)
    if encoder is None:
        return b""
    try:
        ok, encoded = encoder(".jpg", frame)
    except Exception:
        return b""
    if not ok or encoded is None:
        return b""
    if hasattr(encoded, "tobytes"):
        return bytes(encoded.tobytes())
    return bytes(encoded)


def _record_directshow(seconds: int) -> dict[str, Any]:
    """Open the PC camera, write an mp4 for the given seconds, and release it."""
    try:
        import cv2
    except ImportError as exc:
        raise RuntimeError(
            "opencv-python is not installed. From the project folder run: "
            ".\\.venv\\Scripts\\python.exe -m pip install opencv-python"
        ) from exc
    camera = cv2.VideoCapture()
    proc = None
    dest = _unique_camera_file(".mp4")
    saved = False
    try:
        timeout_ms = int(WEBCAM_TIMEOUT_SECONDS * 1000)
        _set_camera_prop(camera, getattr(cv2, "CAP_PROP_OPEN_TIMEOUT_MSEC", None), timeout_ms)
        _set_camera_prop(camera, getattr(cv2, "CAP_PROP_READ_TIMEOUT_MSEC", None), timeout_ms)
        opened = camera.open(0, _webcam_backend(cv2))
        if not opened or not camera.isOpened():
            raise RuntimeError(
                "Could not access the webcam. It may be in use by another app "
                "or blocked by Windows privacy settings."
            )
        _set_camera_prop(camera, getattr(cv2, "CAP_PROP_BUFFERSIZE", None), 1)
        ok, first = camera.read()
        if not ok or first is None:
            raise RuntimeError("Failed to grab a frame from the webcam.")
        first, width, height = _fit_record_frame(cv2, first, None, None)
        command = _record_ffmpeg_command(width, height, dest)
        proc = _spawn_record_ffmpeg(command)
        poster = _poster_jpeg(cv2, first)
        _write_record_frame(proc, first)
        frames = 1
        deadline = _record_now() + seconds
        gap = 1.0 / RECORD_FPS
        _record_wait(gap)
        while _record_now() < deadline:
            ok, frame = camera.read()
            if not ok or frame is None:
                break
            frame, _width, _height = _fit_record_frame(cv2, frame, width, height)
            _write_record_frame(proc, frame)
            frames += 1
            _record_wait(gap)
        stdin = getattr(proc, "stdin", None)
        if stdin is not None:
            stdin.close()
        wait = getattr(proc, "wait", None)
        code = wait(timeout=20) if wait is not None else 0
        if code not in (0, None):
            raise RuntimeError("ffmpeg did not save the video.")
        if not dest.is_file() or dest.stat().st_size < 16:
            raise RuntimeError("The recording was empty.")
        saved = True
        recorded = max(1, int(round(frames / RECORD_FPS)))
        if recorded > seconds:
            recorded = seconds
        return _video_result(dest, recorded, poster, width, height)
    finally:
        try:
            camera.release()
        except Exception:
            pass
        if proc is not None and getattr(proc, "poll", lambda: 0)() is None:
            try:
                proc.kill()
            except Exception:
                pass
        if not saved:
            try:
                if dest.is_file():
                    dest.unlink()
            except OSError:
                pass


def _record_on_camera(seconds: int) -> dict[str, Any]:
    """Record on a side thread so a stuck driver cannot freeze the agent past the clip."""
    box: dict[str, Any] = {}

    def worker() -> None:
        try:
            box["value"] = _record_directshow(seconds)
        except Exception as exc:
            box["error"] = exc

    worker_thread = threading.Thread(target=worker, name="webcam-record", daemon=True)
    worker_thread.start()
    worker_thread.join(float(seconds) + WEBCAM_TIMEOUT_SECONDS + 25.0)
    if worker_thread.is_alive():
        raise TimeoutError(
            "The webcam did not respond in time. It may be in use by another "
            "app or blocked by Windows privacy settings."
        )
    if "error" in box:
        raise box["error"]
    return box["value"]


def record_pc_camera(seconds: Any = None) -> dict[str, Any]:
    """Record the PC webcam for the given seconds and save a downloadable mp4.

    A missing length records nothing. This is a file, not the live feed.
    """
    length = _record_length(seconds)
    if length is None:
        return _err(
            "Say how many seconds to record, from 1 to 600. Nothing was recorded."
        )
    try:
        if record_override is not None:
            return _record_from_override(length)
        return _record_on_camera(length)
    except AssertionError:
        raise
    except Exception as exc:
        return _err(f"record_pc_camera failed: {exc}")


def click_element(
    x: Any,
    y: Any,
    button: str = "left",
    clicks: Any = 1,
) -> dict[str, Any]:
    """Click a 0-1000 screen point. The pointer jumps there and clicks once."""
    try:
        norm_x = _grid_value(x, "x")
        norm_y = _grid_value(y, "y")
        button_name = (button or "left").strip().casefold()
        if button_name not in {"left", "right", "middle"}:
            return _err("button must be left, right, or middle.")
        if isinstance(clicks, bool) or not isinstance(clicks, (int, float)):
            return _err("clicks must be 1 or 2.")
        click_count = int(clicks)
        if click_count not in {1, 2}:
            return _err("clicks must be 1 or 2.")
        width, height = _screen_size()
        if width < 1 or height < 1:
            return _err("The screen size is not available.")
        pixel_x, pixel_y = mouse_controller.norm_to_pixel(norm_x, norm_y, width, height)
        shown_x = _shown_grid(norm_x)
        shown_y = _shown_grid(norm_y)
        details = {
            "x": pixel_x,
            "y": pixel_y,
            "norm_x": shown_x,
            "norm_y": shown_y,
            "button": button_name,
            "clicks": click_count,
        }
        gate_say = ""
        if pointer_override is None:
            import bot_mind

            gate = bot_mind.before_click(pixel_x, pixel_y)
            if gate is not None:
                if not gate.get("ok"):
                    return _err(str(gate.get("error") or "The judge said no."))
                if gate.get("pixel_x") is not None and gate.get("pixel_y") is not None:
                    pixel_x = int(gate["pixel_x"])
                    pixel_y = int(gate["pixel_y"])
                    details["x"] = pixel_x
                    details["y"] = pixel_y
                gate_say = str(gate.get("say") or "")
        import desktop_share
        with desktop_share.hold():
            import bot_cursors

            bot_cursors.mark(pixel_x, pixel_y)
            if pointer_override is not None:
                pointer_override("click", details)
            else:
                mouse_controller.instant_click(
                    _desktop(), pixel_x, pixel_y, click_count, button_name
                )
        if pointer_override is None:
            import bot_mind

            bot_mind.after_click(pixel_x, pixel_y)
        message = (
            f"Clicked {button_name} at pixel {pixel_x},{pixel_y} "
            f"from grid {shown_x},{shown_y}."
        )
        if gate_say:
            message = f"{message} {gate_say}"
        return _ok(message, mind=gate_say, **details)
    except AssertionError:
        raise
    except Exception as exc:
        failsafe = _failsafe_message(exc)
        if failsafe:
            return _err(failsafe)
        return _err(f"click_element failed: {exc}")


def _type_windows_unicode(text: str) -> None:
    """Type characters pyautogui cannot send, using Windows Unicode input."""
    extra = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = (
            ("wVk", ctypes.c_ushort),
            ("wScan", ctypes.c_ushort),
            ("dwFlags", ctypes.c_ulong),
            ("time", ctypes.c_ulong),
            ("dwExtraInfo", extra),
        )

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = (
            ("dx", ctypes.c_long),
            ("dy", ctypes.c_long),
            ("mouseData", ctypes.c_ulong),
            ("dwFlags", ctypes.c_ulong),
            ("time", ctypes.c_ulong),
            ("dwExtraInfo", extra),
        )

    class INPUT(ctypes.Structure):
        class _U(ctypes.Union):
            _fields_ = (("ki", KEYBDINPUT), ("mi", MOUSEINPUT))

        _anonymous_ = ("u",)
        _fields_ = (("type", ctypes.c_ulong), ("u", _U))

    key_up = 0x0002
    unicode_flag = 0x0004
    events: list[INPUT] = []
    for char in text:
        scan = ord(char)
        for flags in (unicode_flag, unicode_flag | key_up):
            item = INPUT(type=1)
            item.ki = KEYBDINPUT(0, scan, flags, 0, 0)
            events.append(item)
    batch = (INPUT * len(events))(*events)
    sender = windows_input_override or ctypes.windll.user32.SendInput
    sent = sender(len(events), ctypes.byref(batch), ctypes.sizeof(INPUT))
    if sent != len(events):
        raise OSError("Windows did not accept the keyboard input.")


def _caps_lock_on() -> bool:
    if os.name != "nt" or pointer_override is not None or windows_input_override is not None:
        return False
    try:
        return bool(ctypes.windll.user32.GetKeyState(0x14) & 1)
    except Exception:
        return False


def _type_into_focused_window(text: str) -> None:
    if pointer_override is not None:
        pointer_override("type", {"text": text})
        return
    if text.isascii() and not _caps_lock_on():
        for at in range(0, len(text), 8):   # 1.4.15: small chunks, so Stop ends typing mid-text
            if stop_token.stopped():
                raise stop_token.Stopped("Stopped.")
            _desktop().write(text[at:at + 8], interval=0)
        return
    if os.name == "nt" and _caps_lock_on():
        _type_windows_unicode(text)  # Unicode input ignores Caps Lock, so case stays right
        return
    try:
        from pynput.keyboard import Controller

        Controller().type(text)
        return
    except ImportError:
        pass
    if os.name == "nt":
        _type_windows_unicode(text)
        return
    raise RuntimeError("Typing characters outside ASCII needs pynput.")


def type_text(text: str) -> dict[str, Any]:
    """Type visible text into the window that currently has focus."""
    try:
        if not isinstance(text, str) or text == "":
            return _err("text is required.")
        type_cap = rules.cap("type_text_max_chars", TYPE_TEXT_LIMIT)
        if type_cap is not None and len(text) > type_cap:
            return _err(f"type_text is limited to {type_cap} characters (limits.type_text_max_chars).")
        if rules.limit("refuse_secret_text") and _memory_is_secret(text):
            return _err("Refusing to type a password, API key, or token.")
        if pointer_override is None:
            import bot_mind

            owner = bot_mind.bot_id()
            if owner:
                drafted = bot_mind.keep_draft(
                    bot_mind.screen_text() or "The question on screen.", text, owner
                )
                if not drafted.get("ok"):
                    return _err(str(drafted.get("error") or "The answer was not saved."))
        import order_flow
        blocked = order_flow.blocked_typing(text)
        if blocked:
            return _err(blocked, hand_over=True)
        if any(ord(char) < 32 or ord(char) == 127 for char in text):
            return _err("type_text accepts visible characters only.")
        import desktop_share
        with desktop_share.hold():
            _type_into_focused_window(text)
        return _ok(f"Typed {len(text)} character(s).", length=len(text))
    except AssertionError:
        raise
    except Exception as exc:
        failsafe = _failsafe_message(exc)
        if failsafe:
            return _err(failsafe)
        return _err(f"type_text failed: {exc}")


def _scroll_amount(amount: Any) -> int:
    if amount is None or amount == "":
        return 3
    if isinstance(amount, bool) or not isinstance(amount, (int, float)):
        raise ValueError("amount must be a number from 1 to 10.")
    value = int(amount)
    if value < 1 or value > 10:
        raise ValueError("amount must be from 1 to 10.")
    return value


def _window_center() -> tuple[int, int] | None:
    """Middle of this chat's window, so a scroll hits the page and not the desktop."""
    if os.name != "nt":
        return None
    import desktop_share

    hwnd = desktop_share.window_for()
    if not hwnd:
        return None
    import ctypes
    from ctypes import wintypes

    rect = wintypes.RECT()
    user32 = ctypes.windll.user32
    if not user32.GetWindowRect(int(hwnd), ctypes.byref(rect)):
        return None
    if rect.left < -1000 or rect.top < -1000:
        return None
    width = int(rect.right) - int(rect.left)
    height = int(rect.bottom) - int(rect.top)
    if width < 40 or height < 40:
        return None
    return (int(rect.left) + width // 2, int(rect.top) + height // 2)


def scroll(direction: str, amount: Any = 3, x: Any = None, y: Any = None) -> dict[str, Any]:
    """Scroll the page at a grid point. One amount step is one full wheel click."""
    try:
        name = (direction or "").strip().casefold()
        if name not in {"up", "down", "left", "right"}:
            return _err("direction must be up, down, left, or right.")
        steps = _scroll_amount(amount)
        given_x = x not in (None, "")
        given_y = y not in (None, "")
        if given_x != given_y:
            return _err("Pass both x and y to aim the scroll, on the 0-1000 grid.")
        pixel: tuple[int, int] | None = None
        details: dict[str, Any] = {"direction": name, "amount": steps}
        if given_x:
            norm_x = _grid_value(x, "x")
            norm_y = _grid_value(y, "y")
            width, height = _screen_size()
            if width < 1 or height < 1:
                return _err("The screen size is not available.")
            pixel = mouse_controller.norm_to_pixel(norm_x, norm_y, width, height)
            details["norm_x"] = _shown_grid(norm_x)
            details["norm_y"] = _shown_grid(norm_y)
            details["x"] = pixel[0]
            details["y"] = pixel[1]
        signed = steps if name in {"up", "right"} else -steps
        import desktop_share
        with desktop_share.hold():
            if pointer_override is not None:
                pointer_override("scroll", details)
            else:
                aim = pixel if pixel is not None else _window_center()
                if aim is not None:
                    import bot_cursors

                    bot_cursors.mark(aim[0], aim[1])
                mouse_controller.scroll_wheel(
                    _desktop(),
                    signed,
                    horizontal=name in {"left", "right"},
                    x=None if aim is None else aim[0],
                    y=None if aim is None else aim[1],
                )
        return _ok(f"Scrolled {name} by {steps}.", **details)
    except AssertionError:
        raise
    except Exception as exc:
        failsafe = _failsafe_message(exc)
        if failsafe:
            return _err(failsafe)
        return _err(f"scroll failed: {exc}")


def _browser_http_url(url: str) -> str:
    target = _public_http_url(url)
    parsed = urlparse(target)
    if parsed.username or parsed.password:
        raise ValueError("The address cannot contain a username or password.")
    return target


def press_keys(keys: str) -> dict[str, Any]:
    """Press tab, enter, arrows, or a shortcut in the focused window."""
    try:
        steps = mouse_controller.parse_key_steps(keys)
        import desktop_share
        with desktop_share.hold():
            if pointer_override is not None:
                pointer_override("keys", {"steps": steps})
            else:
                mouse_controller.press_key_steps(_desktop(), steps)
        shown = ",".join("+".join(step) for step in steps)
        return _ok(f"Pressed {shown}.", steps=steps)
    except AssertionError:
        raise
    except Exception as exc:
        failsafe = _failsafe_message(exc)
        if failsafe:
            return _err(failsafe)
        return _err(f"press_keys failed: {exc}")


def navigate_browser(url: str) -> dict[str, Any]:
    """Open a web link or a video link in the browser, or a video file on this PC."""
    try:
        opened = _open_link(url)
        if opened.get("kind") == "web":
            opened["message"] = f"Opened {opened.get('url')} in the default browser."
        return opened
    except AssertionError:
        raise
    except Exception as exc:
        return _err(f"navigate_browser failed: {exc}")


def _action_dict(step: Any) -> dict[str, Any] | None:
    if isinstance(step, dict):
        return dict(step)
    items = getattr(step, "items", None)
    if callable(items):
        return dict(items())
    return None


def _run_batch_step(step: dict[str, Any]) -> dict[str, Any]:
    name = str(step.get("action") or step.get("name") or "")
    name = name.strip().casefold().replace("-", "_").replace(" ", "_")
    if name in {"click", "click_element"}:
        return click_element(
            step.get("x"),
            step.get("y"),
            str(step.get("button") or "left"),
            step.get("clicks", 1),
        )
    if name in {"type", "type_text"}:
        return type_text(str(step.get("text") or ""))
    if name in {"press", "press_keys", "key", "hotkey"}:
        return press_keys(str(step.get("key") or step.get("keys") or ""))
    if name == "scroll":
        aimed: dict[str, Any] = {}
        if step.get("x") not in (None, ""):
            aimed["x"] = step.get("x")
        if step.get("y") not in (None, ""):
            aimed["y"] = step.get("y")
        return scroll(str(step.get("direction") or ""), step.get("amount", 3), **aimed)
    if name in {"navigate", "navigate_browser"}:
        return navigate_browser(str(step.get("url") or ""))
    if name in {"screenshot", "take_screenshot"}:
        return take_screenshot()
    return _err(
        "Unknown action. Use click, type, press, scroll, navigate, or screenshot."
    )


def perform_actions(actions: Any) -> dict[str, Any]:
    """Run a sequence of desktop actions with no screenshot between them."""
    if isinstance(actions, str):
        try:
            actions = json.loads(actions)
        except json.JSONDecodeError:
            return _err("actions must be a list of action objects.")
    if not isinstance(actions, list) or not actions:
        return _err("actions must be a non-empty list.")
    batch_cap = rules.cap("max_action_batch", MAX_ACTION_BATCH)
    if batch_cap is not None and len(actions) > batch_cap:
        return _err(f"At most {batch_cap} actions can run in one batch (limits.max_action_batch).")
    completed: list[dict[str, Any]] = []
    image: bytes | None = None
    mime: str | None = None
    import desktop_share
    with desktop_share.hold():
        return _perform_held(actions, completed, image, mime)


def _perform_held(
    actions: list[Any],
    completed: list[dict[str, Any]],
    image: bytes | None,
    mime: str | None,
) -> dict[str, Any]:
    for index, raw_step in enumerate(actions):
        if stop_token.stopped():
            return _err(f"Stopped by the user before step {index}.", completed=completed, stopped=True)
        step = _action_dict(raw_step)
        if step is None:
            return _err(
                f"Stopped on step {index}. Each action must be an object.",
                completed=completed,
            )
        result = _run_batch_step(step)
        shot = result.pop("_screenshot_bytes", None)
        shot_mime = result.pop("_screenshot_mime", None)
        completed.append(
            {
                "step": index,
                "action": str(step.get("action") or step.get("name") or ""),
                "ok": bool(result.get("ok")),
                "message": str(result.get("message") or result.get("error") or ""),
            }
        )
        if isinstance(shot, (bytes, bytearray)) and shot:
            image = bytes(shot)
            mime = str(shot_mime or "image/jpeg")
        if not result.get("ok"):
            payload = _err(
                f"Stopped on step {index}. {completed[-1]['message']}",
                completed=completed,
            )
            if image is not None:
                payload["_screenshot_bytes"] = image
                payload["_screenshot_mime"] = mime
            return payload
    payload = _ok(f"Ran {len(completed)} action(s).", completed=completed)
    if image is not None:
        payload["_screenshot_bytes"] = image
        payload["_screenshot_mime"] = mime
    return payload


_COMPUTER_ACTIONS: dict[str, tuple[Callable[..., dict[str, Any]], tuple[str, ...]]] = {
    "take_screenshot": (take_screenshot, ()),
    "screenshot": (take_screenshot, ()),
    "click_element": (click_element, ("x", "y", "button", "clicks")),
    "click": (click_element, ("x", "y", "button", "clicks")),
    "press_keys": (press_keys, ("keys",)),
    "keys": (press_keys, ("keys",)),
    "hotkey": (press_keys, ("keys",)),
    "type_text": (type_text, ("text",)),
    "type": (type_text, ("text",)),
    "scroll": (scroll, ("direction", "amount", "x", "y")),
    "navigate_browser": (navigate_browser, ("url",)),
    "navigate": (navigate_browser, ("url",)),
    "perform_actions": (perform_actions, ("actions",)),
    "batch": (perform_actions, ("actions",)),
    "capture_webcam_image": (capture_webcam_image, ()),
    "webcam": (capture_webcam_image, ()),
}


def computer_action(action: str, **kwargs: Any) -> dict[str, Any]:
    """Run one desktop action by name. Gemini calls the named tools directly."""
    key = (action or "").strip().casefold().replace("-", "_").replace(" ", "_")
    spec = _COMPUTER_ACTIONS.get(key)
    if spec is None:
        return _err(
            "Unknown computer action. Use take_screenshot, capture_webcam_image, "
            "perform_actions, click_element, press_keys, type_text, scroll, "
            "or navigate_browser."
        )
    function, fields = spec
    accepted = {name: kwargs[name] for name in fields if name in kwargs}
    return function(**accepted)


_PLAN_FREE_TOOLS = {
    "get_clipboard_text",
    "read_clipboard_context",
    "clipboard_action_dispatcher",
    "system_diagnostics",
    "create_task_plan",
    "complete_plan_step",
    "revise_task_plan",
    "recall_memory",
    "remember_fact",
    "blender_job_status",
}
# Distinct jobs. Two hits in one sentence, or two hits in the same family, stay a single action.
_PLAN_FAMILIES: tuple[tuple[str, ...], ...] = (
    ("organiz", "folder", "copy", "directory", "drive"),
    ("sql", "database", "query"),
    ("excel", "spreadsheet", "xlsx", "tracking sheet", "sales report"),
    ("clipboard", "copied", "error log"),
    ("screenshot", "click", "webcam"),
    ("install", "mod", "download"),
    ("kill", "focus", "snap", "maximize", "minimize"),
    ("every hour", "remind me", "schedule"),
    ("blender", "3d model", "3d mesh"),
    ("build me", "write a program", "create an app"),
    ("transcode", "ffmpeg", "extract frames"),
    ("git commit", "push the backup", "initialize git"),
    ("text me", "telegram", "discord"),
    ("email", "e-mail", "gmail"),
    ("shut down", "shutdown", "power off", "turn off"),
    ("reverse engineer", "decompile", "disassembl"),
)


def begin_task_turn(user_text: str) -> None:
    """Start a user turn. A new request does not inherit the previous plan."""
    global _turn_request, _turn_is_local
    _turn_request = user_text or ""
    _set_turn(_turn_request, None)
    _turn_is_local = False
    emotion.note_user(_this_request())
    confirm_action.note_user_text(_this_request())   # no-op when the chat layer already read the user's words
    if voice_mode_active:
        voice_checkin.note_activity()


def _clause_has(folded: str, word: str) -> bool:
    if word in {"copy", "sql", "kill", "focus", "snap"}:
        return re.search(rf"\b{re.escape(word)}\b", folded) is not None
    return word in folded


def _request_needs_plan(text: str) -> bool:
    """True when the request splits into clauses from two different job families."""
    raw = " ".join((text or "").split())
    if not raw:
        return False
    parts = [
        part.strip()
        for part in re.split(r",|;|\band\b|\bthen\b", raw, flags=re.IGNORECASE)
        if part.strip()
    ]
    if len(parts) < 2:
        return False
    hit_families: set[int] = set()
    for part in parts:
        folded = part.casefold()
        for index, words in enumerate(_PLAN_FAMILIES):
            if any(_clause_has(folded, word) for word in words):
                hit_families.add(index)
    return len(hit_families) >= 2


def _plan_blocks(name: str) -> dict[str, Any] | None:
    if name in _PLAN_FREE_TOOLS:
        return None
    if not rules.limit("require_plan_for_multistep"):
        return None
    if not _request_needs_plan(_this_request()):
        return None
    if _task_plan() is not None:
        return None
    return _err(
        "This request has several parts. Call create_task_plan with a numbered "
        "checklist before any other action."
    )


def _brief(value: Any, limit: int = 300) -> str:
    if value is None:
        return ""
    return " ".join(str(value).split())[:limit]


def _plan_number(step: Any) -> int | None:
    if isinstance(step, bool):
        return None
    if isinstance(step, int):
        return step
    if isinstance(step, float):
        if not step.is_integer():
            return None
        return int(step)
    if isinstance(step, str) and step.strip().isdigit():
        return int(step.strip())
    return None


def _plan_steps(raw: Any) -> list[str] | None:
    if isinstance(raw, str):
        text = raw.strip()
        parsed: Any = None
        if text.startswith("["):
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = None
        if isinstance(parsed, list):
            raw = parsed
        else:
            lines = [
                re.sub(r"^\s*\d+[\).\]]\s*", "", line).strip()
                for line in text.splitlines()
            ]
            raw = [line for line in lines if line]
    if not isinstance(raw, list):
        return None
    steps: list[str] = []
    for item in raw:
        if isinstance(item, str):
            line = item.strip()
        elif isinstance(item, dict):
            line = str(
                item.get("text") or item.get("step") or item.get("task") or ""
            ).strip()
        else:
            line = ""
        line = re.sub(r"^\s*\d+[\).\]]\s*", "", line).strip()
        line = " ".join(line.split())
        if line:
            steps.append(line[:240])
    return steps


def _log_plan(kind: str) -> None:
    plan = _task_plan()
    if not plan:
        return
    listener = _active_listener()
    if listener is not None:
        try:
            listener({"event": "plan", "kind": kind, "goal": plan["goal"], "steps": _public_steps()})
        except Exception:
            pass
    print(f"[plan] {kind}: {plan['goal']}", flush=True)
    marks = {"pending": " ", "done": "x", "blocked": "!"}
    for step in plan["steps"]:
        mark = marks.get(step["status"], " ")
        print(f"[plan] {step['number']}. [{mark}] {step['text']}", flush=True)


def _public_steps() -> list[dict[str, Any]]:
    plan = _task_plan() or {}
    return [
        {
            "number": step["number"],
            "text": step["text"],
            "status": step["status"],
            "note": step["note"],
        }
        for step in plan.get("steps", [])
    ]


def _plan_item(step: Any) -> dict[str, Any]:
    plan = _task_plan()
    if plan is None:
        return _err("No plan is active. Call create_task_plan first.")
    number = _plan_number(step)
    if number is None:
        return _err("step must be a plan number.")
    for item in plan["steps"]:
        if item["number"] == number:
            return item
    return _err(f"Step {number} is not in the plan.")


def create_task_plan(goal: str, steps: Any) -> dict[str, Any]:
    """Store this turn's checklist. Later tools run only after this exists."""
    goal_text = _brief(goal, 300)
    if not goal_text:
        return _err("A plan needs a goal.")
    parsed = _plan_steps(steps)
    if parsed is None:
        return _err("steps must be a list of step texts.")
    if len(parsed) < 2:
        return _err("A plan needs at least 2 steps.")
    plan_cap = rules.cap("max_plan_steps", MAX_PLAN_STEPS)
    if plan_cap is not None and len(parsed) > plan_cap:
        return _err(f"A plan can have at most {plan_cap} steps (limits.max_plan_steps).")
    _set_plan({
        "goal": goal_text,
        "steps": [
            {"number": index, "text": text, "status": "pending", "note": ""}
            for index, text in enumerate(parsed, 1)
        ],
    })
    _log_plan("plan")
    return _ok(f"Plan ready with {len(parsed)} steps.", goal=goal_text, steps=_public_steps())


def complete_plan_step(step: Any, result: str = "", note: str = "") -> dict[str, Any]:
    """Mark one checklist step done and say which step is next."""
    item = _plan_item(step)
    if "number" not in item:
        return item
    if item["status"] == "blocked":
        return _err(
            f"Step {item['number']} is blocked. Revise the plan before continuing."
        )
    already = item["status"] == "done"
    item["status"] = "done"
    written = _brief(result) or _brief(note)
    if written:
        item["note"] = written
    print(f"[plan] done {item['number']}. {item['text']}", flush=True)
    listener = _active_listener()
    if listener is not None:
        try:
            listener({"event": "plan", "kind": "step", "goal": (_task_plan() or {}).get("goal", ""), "steps": _public_steps()})
        except Exception:
            pass
    pending = [
        entry["number"]
        for entry in (_task_plan() or {"steps": []})["steps"]
        if entry["status"] == "pending"
    ]
    if already:
        message = f"Step {item['number']} was already complete."
    else:
        message = f"Completed step {item['number']}."
    if pending:
        message += f" Next is step {pending[0]}."
    else:
        message += " The plan is complete."
    return _ok(message, steps=_public_steps())


def revise_task_plan(step: Any, reason: str, remaining_steps: Any) -> dict[str, Any]:
    """Block one step, keep earlier steps, and replace everything after it."""
    item = _plan_item(step)
    if "number" not in item:
        return item
    new_steps = _plan_steps(remaining_steps)
    if new_steps is None:
        return _err("remaining_steps must be a list of step texts.")
    if not new_steps:
        return _err("A pivot needs the replacement steps.")
    note = _brief(reason)
    if not note:
        return _err("A pivot needs a reason.")
    plan = _task_plan()
    if plan is None:
        return _err("No plan is active. Call create_task_plan first.")
    prefix = [entry for entry in plan["steps"] if entry["number"] <= item["number"]]
    plan_cap = rules.cap("max_plan_steps", MAX_PLAN_STEPS)
    if plan_cap is not None and len(prefix) + len(new_steps) > plan_cap:
        return _err(f"A plan can have at most {plan_cap} steps (limits.max_plan_steps).")
    item["status"] = "blocked"
    item["note"] = note
    print(f"[plan] pivot at {item['number']}: {note}", flush=True)
    combined: list[dict[str, Any]] = list(prefix)
    combined.extend(
        {"text": text, "status": "pending", "note": ""} for text in new_steps
    )
    for index, entry in enumerate(combined, 1):
        entry["number"] = index
    plan["steps"] = combined
    _log_plan("revised")
    return _ok(f"Revised the plan at step {item['number']}. {note}", steps=_public_steps())


def get_clipboard_text() -> dict[str, Any]:
    """Read copied text. The clipboard is not opened until this tool runs."""
    try:
        if clipboard_override is not None:
            raw = clipboard_override()
        else:
            try:
                import pyperclip
            except ImportError as exc:
                raise RuntimeError(
                    "pyperclip is not installed. From the project folder run: "
                    ".\\.venv\\Scripts\\python.exe -m pip install pyperclip"
                ) from exc
            raw = pyperclip.paste()
        if not isinstance(raw, str):
            raw = "" if raw is None else str(raw)
        text = _scrub(raw.replace("\x00", "").strip())
        if not text:
            return _err("The clipboard is empty.")
        truncated = False
        if len(text) > CLIPBOARD_TEXT_LIMIT:
            text = text[:CLIPBOARD_TEXT_LIMIT]
            truncated = True
        message = f"Read {len(text)} characters from the clipboard."
        if truncated:
            message += " The text was truncated."
        return _ok(message, text=text, truncated=truncated)
    except AssertionError:
        raise
    except Exception as exc:
        return _err(f"get_clipboard_text failed: {exc}")


def allow_bot_trap(reason: str = "") -> dict[str, Any]:
    """The user said yes after a timer, a grade, or a submit that cannot be undone."""
    import bot_mind

    return bot_mind.allow_trap(reason)


TOOLS: dict[str, Callable[..., dict[str, Any]]] = {
    "locate_gta5_directory": locate_gta5_directory,
    "search_and_find_mod_download": search_and_find_mod_download,
    "download_mod_from_web": download_mod_from_web,
    "download_and_extract_zip": download_and_extract_zip,
    "scan_user_downloads_folder": scan_user_downloads_folder,
    "create_directory": create_directory,
    "copy_mod_files": copy_mod_files,
    "integrate_custom_assets": integrate_custom_assets,
    "launch_application": launch_application,
    "open_website": open_website,
    "watch_video": watch_video,
    "search_youtube": search_youtube,
    "automate_excel_task": automate_excel_task,
    "execute_sql_task": execute_sql_task,
    "remember_fact": remember_fact,
    "recall_memory": recall_memory,
    "take_screenshot": take_screenshot,
    "click_element": click_element,
    "press_keys": press_keys,
    "type_text": type_text,
    "scroll": scroll,
    "navigate_browser": navigate_browser,
    "perform_actions": perform_actions,
    "capture_webcam_image": capture_webcam_image,
    "get_clipboard_text": get_clipboard_text,
    "create_task_plan": create_task_plan,
    "complete_plan_step": complete_plan_step,
    "revise_task_plan": revise_task_plan,
    "search_local_files": local_search.search_local_files,
    "kill_process": window_control.kill_process,
    "focus_window": window_control.focus_window,
    "manage_window_layout": window_control.manage_window_layout,
    "manage_windows_and_processes": window_control.manage_windows_and_processes,
    "schedule_background_task": task_schedule.schedule_background_task,
    "run_blender_task": blender_task.run_blender_task,
    "blender_job_status": blender_task.blender_job_status,
    "build_local_program": local_build.build_local_program,
    "send_remote_update": remote_bridge.send_remote_update,
    "process_media": media_ffmpeg.process_media,
    "git_manager": git_manager.git_manager,
    "search_files_by_time": local_search.search_files_by_time,
    "browser_download_tool": browser_download.browser_download_tool,
    "self_heal_execution": self_heal.self_heal_execution,
    "mcp_router": mcp_router.mcp_router,
    "audio_scribe_tool": audio_scribe.audio_scribe_tool,
    "idle_task_scheduler": idle_tasks.idle_task_scheduler,
    "delegate_subagent": delegate_agent.delegate_subagent,
    "read_clipboard_context": clipboard_context.read_clipboard_context,
    "clipboard_action_dispatcher": clipboard_context.clipboard_action_dispatcher,
    "desktop_ui_automation": desktop_automation.desktop_ui_automation,
    "network_manager": network_manager.network_manager,
    "webcam_vision_tool": capture_webcam_image,
    "system_diagnostics": diagnostics.system_diagnostics,
    "file_content_rag_search": local_search.file_content_rag_search,
    "job_scheduler": task_schedule.job_scheduler,
    "routine_macro_engine": routine_macros.routine_macro_engine,
    "stream_pc_camera": live_video.stream_pc_camera,
    "record_pc_camera": record_pc_camera,
    "stream_phone_camera": live_video.stream_phone_camera,
    "gmail_send_message": gmail_mail.gmail_send_message,
    "list_connectors": __import__("connectors").list_connectors,
    "connector_search": __import__("connectors").connector_search,
    "youtube_connect": __import__("youtube_channel").youtube_connect,
    "youtube_status": __import__("youtube_channel").youtube_status,
    "youtube_upload": __import__("youtube_channel").youtube_upload,
    "people_contact_search": gmail_mail.people_contact_search,
    "shutdown_computer": power_control.shutdown_computer,
    "find_on_screen": screen_vision.find_on_screen,
    "click_screen_target": screen_vision.click_screen_target,
    "write_text_file": file_tools.write_text_file,
    "delete_path": file_tools.delete_path,
    "delete_app_item": __import__("app_items").delete_app_item,
    "allow_bot_trap": allow_bot_trap,
}

TOOL_DECLARATIONS = [
    {
        "name": "locate_gta5_directory",
        "description": (
            "Find the Grand Theft Auto V installation on the Windows volume "
            'labeled "external drive". Drive letters are not trusted because they can '
            "change. Returns the folder that contains GTA5.exe."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "rescan": {
                    "type": "boolean",
                    "description": "Search the drive again even when a saved path exists.",
                },
                "volume_label": {
                    "type": "string",
                    "description": "Volume label to match. Defaults to EXTERNAL_DRIVE_LABEL.",
                },
            },
        },
    },
    {
        "name": "download_and_extract_zip",
        "description": (
            "Download a zip from an http or https URL using requests, extract it "
            "with zipfile into the local workspace, and delete the temporary zip. "
            "Does not copy anything into the game. Returns extracted_root."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "Direct http(s) URL of a .zip mod archive.",
                },
                "folder_name": {
                    "type": "string",
                    "description": "Optional workspace folder name for the extracted files.",
                },
            },
            "required": ["url"],
        },
    },
    {
        "name": "search_and_find_mod_download",
        "description": (
            "Search the web for a GTA V mod and return pages plus any direct "
            ".zip, .7z, or .rar URLs found on those pages. Use this when the "
            "user names a mod but does not give a URL. Does not download the file."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": 'Search text, for example "Simple Zombies Reborn GTA 5".',
                },
                "max_results": {
                    "type": "integer",
                    "description": "How many search results to inspect. Default 5, maximum 8.",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "download_mod_from_web",
        "description": (
            "Download a .zip, .7z, or .rar archive from a direct http(s) URL, "
            "extract it into the local workspace, and delete the archive. "
            "Does not copy anything into the game. Returns extracted_root."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "Direct http(s) URL of a .zip, .7z, or .rar file.",
                },
                "folder_name": {
                    "type": "string",
                    "description": "Optional workspace folder name for the extracted files.",
                },
            },
            "required": ["url"],
        },
    },
    {
        "name": "scan_user_downloads_folder",
        "description": (
            "Look in the current user's Downloads folder for .zip, .7z, and .rar "
            "files whose names match a mod. Set extract to true only after a "
            "match is listed. Extraction does not copy files into the game."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name_query": {
                    "type": "string",
                    "description": "Mod name to match against archive filenames.",
                },
                "extract": {
                    "type": "boolean",
                    "description": "Extract the best matching archive into the workspace. Default false.",
                },
            },
            "required": ["name_query"],
        },
    },
    {
        "name": "create_directory",
        "description": (
            "Create a directory inside the located GTA V folder. Use this before "
            "copying files when scripts, mods, dlcpacks, or AddonPeds is missing."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "relative_path": {
                    "type": "string",
                    "description": (
                        'Path relative to the game root, such as "scripts" or '
                        '"mods/update/x64/dlcpacks".'
                    ),
                }
            },
            "required": ["relative_path"],
        },
    },
    {
        "name": "copy_mod_files",
        "description": (
            "Copy a file or a whole folder into the GTA V directory. destination "
            "is relative to the game root. Existing files are kept unless "
            "overwrite is true. Executables are never replaced."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "source_path": {
                    "type": "string",
                    "description": "Absolute path of the file or folder to copy.",
                },
                "destination": {
                    "type": "string",
                    "description": (
                        'Game-relative destination, such as "scripts" or '
                        '"mods/update/x64/dlcpacks/horror_ped". Use "." for the game root.'
                    ),
                },
                "overwrite": {
                    "type": "boolean",
                    "description": "Replace files that already exist. Default false.",
                },
            },
            "required": ["source_path", "destination"],
        },
    },
    {
        "name": "integrate_custom_assets",
        "description": (
            "Place an extracted mod package into the GTA V folders. Handles .ydd, "
            ".yft, .ytd, .asi, and .dll files. layout=auto preserves mods, scripts, "
            "or dlcpacks paths and otherwise sorts by file type. layout=addon_peds "
            "uses scripts/AddonPeds/<pack_name>. layout=dlcpack uses "
            "mods/update/x64/dlcpacks/<pack_name>. Does not run files or edit .rpf archives."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "source_dir": {
                    "type": "string",
                    "description": "Absolute path of the extracted mod folder.",
                },
                "pack_name": {
                    "type": "string",
                    "description": "Folder name for a new dlcpack or AddonPeds pack.",
                },
                "layout": {
                    "type": "string",
                    "description": "auto, addon_peds, dlcpack, scripts, or game_root.",
                    "enum": ["auto", "addon_peds", "dlcpack", "scripts", "game_root"],
                },
                "overwrite": {
                    "type": "boolean",
                    "description": "Replace files that already exist. Default false.",
                },
            },
            "required": ["source_dir"],
        },
    },
    {
        "name": "launch_application",
        "description": (
            "Open a desktop application on this PC by name. Use excel, word, "
            "chrome, notepad, power bi, or ssms. The name is matched to an "
            "installed app or Start Menu shortcut and is not run as a shell command."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "app_name": {
                    "type": "string",
                    "description": 'Application name, for example "excel" or "google chrome".',
                }
            },
            "required": ["app_name"],
        },
    },
    {
        "name": "open_website",
        "description": (
            "Open a link in the browser, including a video link such as YouTube, "
            "youtu.be, Vimeo, TikTok, Twitch, or a direct video address. A bare "
            "address is fine. A video file on this PC opens in the video player."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "Web link, video link, or path of a video file on this PC.",
                }
            },
            "required": ["url"],
        },
    },
    {
        "name": "watch_video",
        "description": (
            "Open a video link or a video file, read its title and description, "
            "and look at one picture from it. Use this when the user wants context "
            "or wants the video watched. Describe only the title, the description, "
            "and the picture. Do not invent the rest of the video."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "Video link or path of a video file on this PC.",
                }
            },
            "required": ["url"],
        },
    },
    {
        "name": "search_youtube",
        "description": (
            "Open YouTube in the browser with a search query, using "
            "https://www.youtube.com/results?search_query=..."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "search_query": {
                    "type": "string",
                    "description": "Words to search for on YouTube.",
                }
            },
            "required": ["search_query"],
        },
    },
    {
        "name": "automate_excel_task",
        "description": (
            "Create or update an .xlsx file. task_instructions is JSON with "
            'sheet, headers, and rows, for example {"sheet":"Sales",'
            '"headers":["Item","Amount"],"rows":[["Hats",12]]}. '
            'file_path may start with "external/" to save on that drive.'
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": 'Output .xlsx path, or "external/reports/sales.xlsx".',
                },
                "task_instructions": {
                    "type": "string",
                    "description": "JSON object describing the sheet, headers, and rows.",
                },
            },
            "required": ["file_path", "task_instructions"],
        },
    },
    {
        "name": "execute_sql_task",
        "description": (
            "Run one SQL statement on a local sqlite file or local SQL Server. "
            "Use allow_changes true only for insert, update, delete, or create. "
            "Remote servers are refused. output_path is an optional .csv or .xlsx file."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "db_connection_str": {
                    "type": "string",
                    "description": "Path to a .db/.sqlite file, or a localhost ODBC connection string.",
                },
                "query": {
                    "type": "string",
                    "description": "One SQL statement.",
                },
                "output_path": {
                    "type": "string",
                    "description": "Optional .csv or .xlsx path for SELECT results. Empty string skips the file.",
                },
                "allow_changes": {
                    "type": "boolean",
                    "description": "Allow INSERT, UPDATE, DELETE, CREATE, DROP, or ALTER. Default false.",
                },
            },
            "required": ["db_connection_str", "query"],
        },
    },
    {
        "name": "remember_fact",
        "description": (
            "Save one lasting fact about the user, their preferences, or a "
            "completed path. The same wording updates the existing memory. "
            "Do not store passwords or API keys."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "fact": {
                    "type": "string",
                    "description": "One plain sentence to remember.",
                },
                "topic": {
                    "type": "string",
                    "description": (
                        "identity, preference, path, instruction, or fact. "
                        "Default fact."
                    ),
                },
            },
            "required": ["fact"],
        },
    },
    {
        "name": "recall_memory",
        "description": (
            "Search facts saved on this computer. Use it when the user asks "
            "what you know, what their setup is, or what an earlier path or "
            "instruction was. An empty query returns the saved list."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Words to look for. Leave empty to list saved facts.",
                },
            },
        },
    },
    {
        "name": "take_screenshot",
        "description": (
            "Capture the screen of this PC so the image can be inspected. "
            "Call this before clicking or typing. click_element uses a 0-1000 "
            "grid over the whole screen, not image pixels."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "capture_webcam_image",
        "description": (
            "Open the default webcam with DirectShow, save one frame, and "
            "close the camera immediately. The picture can be downloaded from "
            "the chat. Use this only when the user asks "
            "you to look at them, the room, or an object they are holding. "
            "The image comes back with this result. If the camera is busy or "
            "blocked, this returns an error instead of waiting. Do not call "
            "it in a loop or during ordinary chat."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "click_element",
        "description": (
            "Jump to a point on the 0-1000 screen grid and click immediately. "
            "0,0 is the top-left and 1000,1000 is the bottom-right. Do not "
            "send image pixels. button is left, right, or middle. clicks is 1 or 2. "
            "Another chat may use the PC at the same time. Focus your own window "
            "first. Later clicks and typing from this chat return to that window."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "x": {
                    "type": "integer",
                    "description": "Horizontal position from 0 to 1000.",
                },
                "y": {
                    "type": "integer",
                    "description": "Vertical position from 0 to 1000.",
                },
                "button": {
                    "type": "string",
                    "description": "left, right, or middle. Default left.",
                },
                "clicks": {
                    "type": "integer",
                    "description": "1 for a click, 2 for a double-click. Default 1.",
                },
            },
            "required": ["x", "y"],
        },
    },
    {
        "name": "press_keys",
        "description": (
            "Press navigation keys or one shortcut in the focused window. "
            "Use tab, enter, arrows, or a chord such as ctrl+l. Prefer this "
            "for forms and menus. Do not send passwords."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "keys": {
                    "type": "string",
                    "description": "Example: tab, enter or ctrl+l. At most 8 steps.",
                },
            },
            "required": ["keys"],
        },
    },
    {
        "name": "type_text",
        "description": (
            "Type visible text into the focused window. Focus the field with "
            "press_keys or click_element first. Do not send passwords, API keys, "
            "or control characters."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "Visible characters to type, at most 500.",
                },
            },
            "required": ["text"],
        },
    },
    {
        "name": "scroll",
        "description": (
            "Scroll the list or page at x, y on the 0-1000 grid. The pointer "
            "moves there first. direction is up, down, left, or right. amount "
            "is full wheel clicks from 1 to 10, not pixels. Default 3."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "direction": {
                    "type": "string",
                    "description": "up, down, left, or right.",
                },
                "amount": {
                    "type": "integer",
                    "description": "Full wheel clicks from 1 to 10. Default 3. Not pixels.",
                },
                "x": {
                    "type": "integer",
                    "description": "0-1000 grid point over the list or page. Pass with y.",
                },
                "y": {
                    "type": "integer",
                    "description": "0-1000 grid point over the list or page. Pass with x.",
                },
            },
            "required": ["direction"],
        },
    },
    {
        "name": "navigate_browser",
        "description": (
            "Open one http or https address in the default browser on this PC. "
            "Does not log in or pass a download gate."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "An http or https address with no username or password.",
                },
            },
            "required": ["url"],
        },
    },
    {
        "name": "perform_actions",
        "description": (
            "Run several desktop actions in order with no wait and no "
            "screenshot between them. Each item has action set to click, "
            "type, press, scroll, navigate, or screenshot. x and y are the "
            "0-1000 grid. End with one screenshot only when you need to look again."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "actions": {
                    "type": "array",
                    "description": (
                        'Example: [{"action":"click","x":500,"y":400},'
                        '{"action":"type","text":"hello"},'
                        '{"action":"press","key":"enter"}]'
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "action": {"type": "string"},
                            "x": {"type": "integer"},
                            "y": {"type": "integer"},
                            "text": {"type": "string"},
                            "key": {"type": "string"},
                            "button": {"type": "string"},
                            "clicks": {"type": "integer"},
                            "direction": {"type": "string"},
                            "amount": {"type": "integer"},
                            "url": {"type": "string"},
                        },
                        "required": ["action"],
                    },
                },
            },
            "required": ["actions"],
        },
    },
    {
        "name": "get_clipboard_text",
        "description": (
            "Read the text currently copied on this PC, such as code or an "
            "error log. Use it when the user says they copied something. "
            "Do not ask them to paste it again, and do not save it with "
            "remember_fact."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "create_task_plan",
        "description": (
            "Write the numbered checklist for a request that has several "
            "different jobs. Call this before any other action tool. A single "
            "action such as opening Excel does not need a plan."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "goal": {
                    "type": "string",
                    "description": "One sentence describing the whole request.",
                },
                "steps": {
                    "type": "array",
                    "description": "2 to 8 short steps, in the order they should run.",
                    "items": {"type": "string"},
                },
            },
            "required": ["goal", "steps"],
        },
    },
    {
        "name": "complete_plan_step",
        "description": (
            "Mark one plan step done after its tool calls succeed. step is "
            "the 1-based number. Say one short sentence about that step."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "step": {
                    "type": "integer",
                    "description": "1-based step number from the active plan.",
                },
                "result": {
                    "type": "string",
                    "description": "Short note about what that step finished.",
                },
            },
            "required": ["step"],
        },
    },
    {
        "name": "revise_task_plan",
        "description": (
            "Use this when a step is blocked or the approach has to change. "
            "Tell the user the reason. Earlier steps stay, that step is "
            "marked blocked, and remaining_steps replace everything after it."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "step": {
                    "type": "integer",
                    "description": "1-based number of the step that cannot continue.",
                },
                "reason": {
                    "type": "string",
                    "description": "Why this step changed, in one sentence.",
                },
                "remaining_steps": {
                    "type": "array",
                    "description": "The new steps that replace everything after the blocked step.",
                    "items": {"type": "string"},
                },
            },
            "required": ["step", "reason", "remaining_steps"],
        },
    },
    {
        "name": "search_local_files",
        "description": (
            "Search file names and text notes on the Desktop, Documents, "
            "Downloads, the user home folder, and external drive when that drive is "
            "connected. A named folder such as the desktop or external drive limits "
            "the search to that place. Do not open or run the files it returns."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Plain-language description of the file.",
                },
                "refresh": {
                    "type": "boolean",
                    "description": "Rebuild the index before searching. Default false.",
                },
                "limit": {
                    "type": "integer",
                    "description": "How many files to return. Default 8, maximum 20.",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "kill_process",
        "description": (
            "Close a frozen program by its name, such as notepad. Refuses "
            "Windows system processes."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "process_name": {
                    "type": "string",
                    "description": "Program name, without a path.",
                },
            },
            "required": ["process_name"],
        },
    },
    {
        "name": "focus_window",
        "description": (
            "Bring a visible window to the front by part of its title. "
            "This chat keeps that window while another chat uses the PC."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "window_title": {
                    "type": "string",
                    "description": "Words that appear in the window title.",
                },
            },
            "required": ["window_title"],
        },
    },
    {
        "name": "manage_window_layout",
        "description": (
            "Resize a window. action is maximize, minimize, restore, "
            "snap_left, or snap_right. window_title is optional."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {"type": "string"},
                "window_title": {"type": "string"},
            },
            "required": ["action"],
        },
    },
    {
        "name": "manage_windows_and_processes",
        "description": (
            "One window or process action. action is kill, focus, maximize, "
            "minimize, restore, snap_left, or snap_right. target is the "
            "program name or the window title."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {"type": "string"},
                "target": {"type": "string"},
            },
            "required": ["action"],
        },
    },
    {
        "name": "schedule_background_task",
        "description": (
            "Run an allowlisted routine later. task is organize_downloads, "
            "reindex_files, or remind. delay_minutes is a one-shot wait. "
            "interval_minutes repeats. Does not run scripts or programs."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "task": {"type": "string"},
                "delay_minutes": {"type": "number"},
                "interval_minutes": {"type": "number"},
                "message": {
                    "type": "string",
                    "description": "Required when task is remind.",
                },
            },
            "required": ["task"],
        },
    },
    {
        "name": "run_blender_task",
        "description": (
            "Build a 3D model with Blender in the background. No window is "
            "opened. script is Python that uses bpy to create the mesh. Do "
            "not export, open files, or start programs in the script. This "
            "tool writes the .obj, .fbx, or .blend file and checks that it "
            "exists. output_path may start with \"external/\". status started "
            "means the file is not saved yet. A failed result means Blender "
            "did not write the file. Do not call this again just to ask if it is done."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "script": {
                    "type": "string",
                    "description": "bpy code that creates the mesh. No file paths.",
                },
                "output_path": {
                    "type": "string",
                    "description": "Optional .obj, .fbx, or .blend path.",
                },
                "name": {
                    "type": "string",
                    "description": "File name used when output_path is omitted.",
                },
            },
            "required": ["script"],
        },
    },
    {
        "name": "blender_job_status",
        "description": (
            "Check the Blender model that is already building or finished. "
            "Does not start Blender. status is started, ready, or failed. "
            "open_file opens the saved model only when status is ready."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "open_file": {
                    "type": "boolean",
                    "description": "Open the saved model in the default app.",
                },
            },
        },
    },
    {
        "name": "build_local_program",
        "description": (
            "Write an original program on this computer and optionally start "
            "it. Use this when the user asks you to build an app, a script, "
            "a page, or a simple test tool. Do not use it for a crack, a "
            "repack, or a commercial installer. files is a JSON list of "
            "{\"path\":\"main.py\",\"content\":\"...\"}. output_path is a "
            "folder and may start with \"external/\". Set run true and entry "
            "to the .py or .html file when the user wants to open it now."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Short project name, used as the folder.",
                },
                "files": {
                    "type": "string",
                    "description": "JSON list of path and content objects.",
                },
                "output_path": {
                    "type": "string",
                    "description": "Optional folder. external/Apps/name is allowed.",
                },
                "entry": {
                    "type": "string",
                    "description": "Project file to start, such as main.py.",
                },
                "run": {
                    "type": "boolean",
                    "description": "Start the entry file after the files are saved.",
                },
            },
            "required": ["name", "files"],
        },
    },
    {
        "name": "send_remote_update",
        "description": (
            "Send one short status line to the paired Telegram chat and, "
            "when configured, to a Discord webhook. Use it when the user "
            "asks to be texted. Do not include keys, tokens, or webhook URLs."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "Plain status sentence, such as the export is ready.",
                },
            },
            "required": ["message"],
        },
    },
    {
        "name": "process_media",
        "description": (
            "Convert video, compress audio, or extract frames with ffmpeg. "
            "No media window is opened. action is convert, compress_audio, "
            "or extract_frames. source may start with \"external/\". "
            "status started means the file is not ready yet. At most 8 "
            "files in one folder are processed."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {"type": "string"},
                "source": {
                    "type": "string",
                    "description": "A media file or a folder of media files.",
                },
                "output_path": {
                    "type": "string",
                    "description": "Optional output file or folder.",
                },
            },
            "required": ["action", "source"],
        },
    },
    {
        "name": "git_manager",
        "description": (
            "Initialize a repository, show status, commit, or push. Commit "
            "and push only when the user asks. message is required for "
            "commit. Push is a normal git push with no force and no remote "
            "URL. Secret files such as .env are left unstaged. Does not "
            "change git name or email."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "init, status, commit, or push.",
                },
                "path": {
                    "type": "string",
                    "description": "Project folder. external/Apps/name is allowed.",
                },
                "message": {
                    "type": "string",
                    "description": "Commit message. Required for commit.",
                },
            },
            "required": ["action"],
        },
    },
    {
        "name": "search_files_by_time",
        "description": (
            "Find files by a time window, a file type, or both. With no folder "
            "named, search the Desktop, Documents, Downloads, the home folder, "
            "and external drive when connected. A named place such as external drive, the "
            "desktop, or the project folder limits the search. Examples: "
            "where is the Excel file I saved yesterday, videos from last week. "
            "Does not open or run the files."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Plain request, such as videos from last week.",
                },
                "file_type": {
                    "type": "string",
                    "description": "Optional type such as video, excel, xlsx, photo, pdf, or mp4.",
                },
                "when": {
                    "type": "string",
                    "description": "Optional time such as today, yesterday, last week, or last month.",
                },
                "limit": {
                    "type": "integer",
                    "description": "How many files to return. Default 8, maximum 20.",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "browser_download_tool",
        "description": (
            "Open one http or https page in Chromium, fill fields, click, and "
            "save one file the page actually downloads. destination is "
            "downloads, desktop, or external drive. A password is passed as env set "
            "to a variable name such as BROWSER_PASSWORD, never as text. "
            "Does not solve a CAPTCHA, skip a countdown, or bypass a download gate. "
            "Mod pages without a direct archive link are refused."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "http or https address with no username or password.",
                },
                "destination": {
                    "type": "string",
                    "description": "downloads, desktop, external drive, or an allowed folder path.",
                },
                "visible": {
                    "type": "boolean",
                    "description": "Show the window. Default true so a person can finish a check.",
                },
                "cookie_file": {
                    "type": "string",
                    "description": "Optional Playwright storage-state .json the user already saved.",
                },
                "actions": {
                    "type": "array",
                    "description": (
                        'Up to 8 steps. Example: [{"action":"fill","selector":"#user","text":"ada"},'
                        '{"action":"fill","selector":"#pass","env":"BROWSER_PASSWORD"},'
                        '{"action":"click","selector":"button[type=submit]"},'
                        '{"action":"click","selector":"a.report","download":true}]'
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "action": {"type": "string"},
                            "selector": {"type": "string"},
                            "text": {"type": "string"},
                            "env": {"type": "string"},
                            "key": {"type": "string"},
                            "download": {"type": "boolean"},
                        },
                        "required": ["action"],
                    },
                },
            },
            "required": ["url"],
        },
    },
    {
        "name": "self_heal_execution",
        "description": (
            "Run one Python file you wrote, capture a traceback, rewrite the "
            "file, and try again. At most 3 attempts. Does not retry downloads, "
            "deletes, git pushes, or closing a program."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "script_path": {
                    "type": "string",
                    "description": "Path to a .py file in the user folder, workspace, or external drive.",
                },
            },
            "required": ["script_path"],
        },
    },
    {
        "name": "mcp_router",
        "description": (
            "Call a tool on an MCP server listed in workspace/mcp_servers.json. "
            "action is list_servers, list_tools, or call. Pass the server name "
            "and, for a call, the tool name plus a JSON object. "
            "Do not pass a shell command."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "list_servers, list_tools, or call.",
                },
                "server": {
                    "type": "string",
                    "description": "Server name from the config file.",
                },
                "tool": {
                    "type": "string",
                    "description": "Tool name from list_tools. Required for call.",
                },
                "arguments": {
                    "type": "object",
                    "description": "JSON object of tool arguments. Not a shell command.",
                },
            },
            "required": ["action"],
        },
    },
    {
        "name": "audio_scribe_tool",
        "description": (
            "Record a microphone, system-audio, or existing audio file for 1 to "
            "600 seconds and save bullet notes on this PC. Transcription stays "
            "local. status started means the note is not written yet."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    "description": "mic, system, or file. Default mic.",
                },
                "seconds": {
                    "type": "integer",
                    "description": "Recording length from 1 to 600. Default 30.",
                },
                "output_path": {
                    "type": "string",
                    "description": "Optional .md path in Documents, the workspace, or external drive.",
                },
                "audio_path": {
                    "type": "string",
                    "description": "Existing audio file. Required when source is file.",
                },
            },
        },
    },
]
TOOL_DECLARATIONS.extend(idle_tasks.DECLARATIONS)
TOOL_DECLARATIONS.extend(delegate_agent.DECLARATIONS)
TOOL_DECLARATIONS.extend(clipboard_context.DECLARATIONS)
TOOL_DECLARATIONS.extend(desktop_automation.DECLARATIONS)
TOOL_DECLARATIONS.extend(network_manager.DECLARATIONS)
TOOL_DECLARATIONS.extend(diagnostics.DECLARATIONS)
TOOL_DECLARATIONS.extend(local_search.RAG_DECLARATIONS)
TOOL_DECLARATIONS.extend(task_schedule.JOB_DECLARATIONS)
TOOL_DECLARATIONS.extend(routine_macros.DECLARATIONS)
import page_text as _page_text
import task_memory as _task_memory
TOOL_DECLARATIONS.append(_page_text.DECLARATION)
TOOL_DECLARATIONS.extend(_task_memory.DECLARATIONS)
TOOLS['read_page_text'] = _page_text.read_page_text
import wingz_scan as _wingz_scan
TOOL_DECLARATIONS.append(_wingz_scan.DECLARATION)
TOOLS['wingz_scan'] = _wingz_scan.wingz_scan
import extras148 as _extras
TOOL_DECLARATIONS.extend(_extras.DECLARATIONS)
TOOLS.update(_extras.TOOLS)
_PLAN_FREE_TOOLS.update(_extras.TOOLS)
import undo_store as _undo
TOOL_DECLARATIONS.extend(_undo.DECLARATIONS)
TOOLS.update(_undo.TOOLS)
_PLAN_FREE_TOOLS.update(_undo.TOOLS)
import extras149 as _extras149
TOOL_DECLARATIONS.extend(_extras149.DECLARATIONS)
TOOLS.update(_extras149.TOOLS)
_PLAN_FREE_TOOLS.update(_extras149.TOOLS)
import polls as _polls
TOOL_DECLARATIONS.extend(_polls.DECLARATIONS)
TOOLS.update(_polls.TOOLS)
_PLAN_FREE_TOOLS.update(_polls.TOOLS)
import routines as _routines
TOOL_DECLARATIONS.extend(_routines.DECLARATIONS)
TOOLS.update(_routines.TOOLS)
_PLAN_FREE_TOOLS.update(_routines.TOOLS)
import order_flow as _order_flow
TOOL_DECLARATIONS.extend(_order_flow.DECLARATIONS)
TOOLS.update(_order_flow.TOOLS)
_PLAN_FREE_TOOLS.update(_order_flow.TOOLS)
TOOLS['save_task_progress'] = _task_memory.save_task_progress
TOOLS['get_task_progress'] = _task_memory.get_task_progress
_PLAN_FREE_TOOLS.update({'wingz_scan', 'read_page_text', 'save_task_progress', 'get_task_progress'})
# Stage 2 modules each bring DECLARATIONS and TOOLS.
STAGE2_MODULES = [team_agent, bots, demo_skills, code_loop, autopilot, self_upgrade, remote_access, task_runner]
for _stage2 in STAGE2_MODULES:
    TOOL_DECLARATIONS.extend(_stage2.DECLARATIONS)
    TOOLS.update(_stage2.TOOLS)
TOOL_DECLARATIONS.append(
    {
        "name": "webcam_vision_tool",
        "description": (
            "Snap one webcam frame for a desk, a document, or an object, then "
            "close the camera. On Windows this uses DirectShow. The image comes "
            "back with the tool result. Same capture as capture_webcam_image. "
            "Do not call it in a loop."
        ),
        "parameters": {"type": "object", "properties": {}},
    }
)
TOOL_DECLARATIONS.append(
    {
        "name": "stream_pc_camera",
        "description": (
            "Start, stop, or look at a live feed from this computer's webcam. "
            "action is start, stop, status, or look. seconds is 1 to 600 and "
            "defaults to 120. When TELEGRAM_RTMP_URL and TELEGRAM_STREAM_KEY "
            "are set, ffmpeg publishes the feed. Otherwise a local viewer page "
            "is served only while the feed is on. A Telegram Mini App button "
            "is sent only for an https LIVE_PUBLIC_URL. Do not pass an RTMP "
            "address or a stream key. Do not use this for a single look."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "start, stop, status, or look. Default start.",
                },
                "seconds": {
                    "type": "integer",
                    "description": "How long the feed stays on, from 1 to 600. Default 120.",
                },
            },
        },
    }
)
TOOL_DECLARATIONS.append(
    {
        "name": "record_pc_camera",
        "description": (
            "Record this PC's webcam for the number of seconds given, save "
            "an mp4, and close the camera. seconds is required and is from "
            "1 to 600. If the user did not say how long, do not call this. "
            "Ask them. The video can be downloaded from the chat. This is "
            "not a live feed. Use capture_webcam_image for one picture and "
            "stream_pc_camera only when they ask to watch it live."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "seconds": {
                    "type": "integer",
                    "description": "How many seconds to record, from 1 to 600.",
                },
            },
            "required": ["seconds"],
        },
    }
)
TOOL_DECLARATIONS.append(
    {
        "name": "stream_phone_camera",
        "description": (
            "Open a phone camera page, or return the latest frame that page "
            "posted. action is start, stop, status, or look. The page uses "
            "the phone camera and posts JPEG frames to this PC. action look "
            "attaches the latest frame. Do not call look in a loop. Do not "
            "pass an RTMP address or a stream key."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "start, stop, status, or look. Default start.",
                },
                "seconds": {
                    "type": "integer",
                    "description": "How long the page stays on, from 1 to 600. Default 120.",
                },
            },
        },
    }
)
TOOL_DECLARATIONS.append(
    {
        "name": "gmail_send_message",
        "description": (
            "Send one Gmail message. Pass an email address as to when the user "
            "gave one. Pass a contact name as to when they named a person. "
            "The tool looks up a name and does not look up an address. Leave "
            "subject empty to generate one from the body. An invalid address "
            "or more than one matching contact is not sent. Do not pass an "
            "app password."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "to": {
                    "type": "string",
                    "description": "One email address or one contact name.",
                },
                "subject": {
                    "type": "string",
                    "description": "Optional subject. Leave empty to generate one.",
                },
                "body": {
                    "type": "string",
                    "description": "The message text.",
                },
                "request": {
                    "type": "string",
                    "description": "Optional original sentence when to and body are not split yet.",
                },
                "from_account": {
                    "type": "string",
                    "description": ("Which saved Gmail account sends it, when the user names one (an address or "
                                    "part of it). Leave empty for the default account."),
                },
            },
        },
    }
)
TOOL_DECLARATIONS.append(
    {
        "name": "people_contact_search",
        "description": (
            "Look up a saved contact by name and return the matching email "
            "addresses. This does not send mail. Ask the user to choose when "
            "more than one contact matches."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Contact name to find.",
                },
            },
            "required": ["query"],
        },
    }
)
TOOL_DECLARATIONS.append(
    {
        "name": "list_connectors",
        "description": (
            "List Gmail, Google Calendar, Google Drive, OneDrive, Outlook, "
            "Teams, Notion, GitHub, Slack, Linear, and YouTube, and whether "
            "each one is connected. This returns no password and no token."
        ),
        "parameters": {"type": "object", "properties": {}},
    }
)
TOOL_DECLARATIONS.append(
    {
        "name": "connector_search",
        "description": (
            "Read one connected service. name is gmail, gcalendar, gdrive, "
            "onedrive, outlook, teams, notion, github, slack, linear, or youtube. "
            "query is the search text. This does not send, delete, or post. "
            "Describe only the rows it returns."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Connector id from list_connectors."},
                "query": {"type": "string", "description": "What to look for."},
            },
            "required": ["name"],
        },
    }
)
TOOL_DECLARATIONS.append(
    {
        "name": "youtube_connect",
        "description": (
            "Open Google's sign-in on this PC so Pedro can post videos to the "
            "YouTube channel the user picks. Call this when youtube_upload says "
            "the channel is not connected. Do not pass a client secret or a token."
        ),
        "parameters": {"type": "object", "properties": {}},
    }
)
TOOL_DECLARATIONS.append(
    {
        "name": "youtube_status",
        "description": (
            "Check whether this PC is signed in to a YouTube channel. "
            "This does not post anything and does not return a token."
        ),
        "parameters": {"type": "object", "properties": {}},
    }
)
TOOL_DECLARATIONS.append(
    {
        "name": "youtube_upload",
        "description": (
            "Upload one video file to the signed-in YouTube channel. "
            "privacy stays private unless the user said public or unlisted. "
            "Do not call this for a comment or a community post."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Full path of the video file on this PC."},
                "title": {"type": "string", "description": "Title shown on YouTube."},
                "description": {"type": "string", "description": "Optional description."},
                "privacy": {"type": "string", "description": "private, unlisted, or public. Default private."},
                "tags": {"type": "string", "description": "Optional comma-separated tags."},
            },
            "required": ["path", "title"],
        },
    }
)
TOOL_DECLARATIONS.append(
    {
        "name": "shutdown_computer",
        "description": (
            "Shut down this PC. Call it when the user asks to shut down, "
            "turn off the computer, or power off. It waits for a clear yes "
            "before Windows is told to shut down. Do not use it to close one "
            "program."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
        },
    }
)


# Tools that must stay on the calling thread (audio, UI, GUI automation) or that
# already manage their own background jobs.
_NO_TIMEOUT_TOOLS = {
    "speak_response", "listen_to_microphone", "stream_pc_camera", "stream_phone_camera",
    "record_pc_camera", "run_terminal_command",
}
tool_timeout_override: float | None = None


class ToolTimeout(RuntimeError):
    pass

# Upgrade tools (vision clicking, general files). Appended last so older tool
# indexes stay stable.
TOOL_DECLARATIONS.extend([
    {
        "name": "find_on_screen",
        "description": "Take a screenshot and locate a described UI element with vision. Returns its centre on the 0-1000 grid.",
        "parameters": {"type": "object", "properties": {
            "description": {"type": "string", "description": "What to find, e.g. 'the blue Sign in button'."},
            "control_name": {"type": "string"}, "window_title": {"type": "string"}},
            "required": ["description"]},
    },
    {
        "name": "click_screen_target",
        "description": (
            "Click a UI element described in words. Optionally focuses a window first, "
            "finds the element with vision, clicks, and retries with a fresh screenshot. "
            "Prefer this over guessing click_element coordinates."
        ),
        "parameters": {"type": "object", "properties": {
            "description": {"type": "string"},
            "window_title": {"type": "string", "description": "Window to bring to front first. Optional."},
            "double_click": {"type": "boolean"},
            "retries": {"type": "integer", "description": "Extra attempts, 0-4. Default from rules speed.retries."},
            "control_name": {"type": "string", "description": "Exact visible name of the control, if known (fast UI Automation lookup)."}},
            "required": ["description"]},
    },
    {
        "name": "write_text_file",
        "description": "Write a text file (code, notes, config) at a path the user's rules allow.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}, "content": {"type": "string"},
            "overwrite": {"type": "boolean"}}, "required": ["path", "content"]},
    },
    __import__("app_items").DECLARATION,
    {
        "name": "delete_path",
        "description": "Delete a file or folder (Recycle Bin when available). The user's rules may require a yes first.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}, "recursive": {"type": "boolean"}}, "required": ["path"]},
    },
])

import ui_controls  # noqa: E402

TOOL_DECLARATIONS.extend(ui_controls.DECLARATIONS)
TOOLS.update(ui_controls.TOOLS)
import blender_docs  # noqa: E402
import google_connections  # noqa: E402

TOOL_DECLARATIONS.extend(blender_docs.DECLARATIONS + google_connections.DECLARATIONS)
TOOLS.update(blender_docs.TOOLS)
TOOLS.update(google_connections.TOOLS)
import quiet_brain_shorts  # noqa: E402

TOOL_DECLARATIONS.extend(quiet_brain_shorts.DECLARATIONS)
TOOLS.update(quiet_brain_shorts.TOOLS)
import terminal_tool  # noqa: E402
TOOL_DECLARATIONS.extend(terminal_tool.DECLARATIONS)
import pc_fast_tools   # 1.4.16: read-only list_files / pc_status (no terminal, no approval)
TOOL_DECLARATIONS.extend(pc_fast_tools.DECLARATIONS)
TOOLS.update(pc_fast_tools.TOOLS)
_PLAN_FREE_TOOLS.update(pc_fast_tools.TOOLS)
TOOLS.update(terminal_tool.TOOLS)


def _tool_timeout_seconds() -> float:
    if tool_timeout_override is not None:
        return float(tool_timeout_override)
    try:
        return float(rules.agent_setting("tool_timeout_seconds", 300))
    except (TypeError, ValueError):
        return 300.0


def _call_with_timeout(name: str, function: Callable[..., Any], arguments: dict[str, Any]) -> Any:
    """Run a tool with a timeout so one stuck call cannot freeze the agent.

    The tool runs in a daemon thread. On timeout the agent moves on and the
    thread is abandoned (Python cannot kill threads safely).
    """
    limit = _tool_timeout_seconds()
    cancel = getattr(_turn_local, "cancel_event", None)
    if (limit <= 0 or name in _NO_TIMEOUT_TOOLS) and cancel is None:
        return function(**arguments)
    if limit <= 0 or name in _NO_TIMEOUT_TOOLS:
        limit = 10 ** 7
    box: dict[str, Any] = {}
    # The turn's plan, request and listener live in thread-locals; carry them into
    # the worker and back, or create_task_plan's plan is lost after the call.
    turn_state = dict(_turn_local.__dict__)
    scope_state = dict(_tool_scope.__dict__)

    def runner() -> None:
        _turn_local.__dict__.update(turn_state)
        _tool_scope.__dict__.update(scope_state)
        stop_token.bind(cancel)
        try:
            box["result"] = function(**arguments)
        except BaseException as exc:  # re-raised on the caller thread
            box["error"] = exc
        finally:
            box["turn"] = dict(_turn_local.__dict__)

    worker = threading.Thread(target=runner, name=f"tool-{name}", daemon=True)
    worker.start()
    deadline = time.monotonic() + limit
    while worker.is_alive() and time.monotonic() < deadline:
        worker.join(0.05)
        if cancel is not None and cancel.is_set() and worker.is_alive():
            stop_token.fire(cancel)   # kill its processes, let go of keys; the thread is abandoned
            return {"ok": False, "stopped": True, "error": "Stopped by the user."}
    if worker.is_alive():
        raise ToolTimeout(f"timed out after {int(limit)}s (agent.tool_timeout_seconds in rules.yaml)")
    if "turn" in box:
        _turn_local.__dict__.update(box["turn"])
    if "error" in box:
        raise box["error"]
    return box.get("result")


_tool_scope = threading.local()


def set_tool_scope(names: set[str] | None) -> None:
    """Limit this thread's tool calls (team sub-agents). None = no limit."""
    _tool_scope.allowed = None if names is None else set(names)


def _unattended() -> bool:
    return bool(getattr(_tool_scope, "unattended", False))


def set_unattended(on: bool) -> None:
    """Autopilot threads: risky actions wait for a yes instead of asking aloud."""
    _tool_scope.unattended = bool(on)


def _clean_tool_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    """Drop blank argument names.

    A backup model sometimes calls a no-input tool as {"": {}}. That name is
    not a parameter, so the call used to fail before the webcam opened.
    """
    cleaned: dict[str, Any] = {}
    for key, value in arguments.items():
        name = str(key).strip()
        if name:
            cleaned[name] = value
    return cleaned


def invoke_tool(name: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
    """Run one declared tool. Exceptions become error payloads for the model."""
    if name == "run_terminal_command" and isinstance(arguments, dict):
        listing = pc_fast_tools.listing_from_terminal(str(arguments.get("command") or ""))
        if listing is not None:   # 1.4.16: a plain folder listing is read-only: answer it with list_files, no console
            name, arguments = "list_files", listing
    function = TOOLS.get(name)
    if function is None:
        return _err(f"Unknown tool: {name}")
    scope = getattr(_tool_scope, "allowed", None)
    if scope is not None and name not in scope:
        return _err(f"{name} is not one of this team member's tools.", blocked_by_scope=True)
    try:
        import safe_mode

        held = safe_mode.refuse(name)
    except Exception:
        held = None
    if held is not None:
        return held
    blocked = _plan_blocks(name)
    if blocked is not None:
        return blocked
    if _wingz_on() and name in WINGZ_BLOCKED_TOOLS:
        return _err("Wingz work happens in the web portal in Chrome. Desktop apps are blocked for this task; "
                    "use navigate_browser/open_website with https://wingz.itvedant.com/ instead.",
                    blocked_by_rules=True)
    arguments = _clean_tool_arguments(dict(arguments or {}))
    rule_block = rules.tool_block_reason(name)
    if rule_block is not None:
        return _err(rule_block, blocked_by_rules=True)
    sensitive = confirm_action.is_sensitive(name, arguments)
    if sensitive:
        earlier = confirm_action.already_done(name, arguments)
        if earlier is not None:   # already ran after the user's yes: never ask or run it twice
            return {**earlier, "already_done": True}
        if not confirm_action.consume_grant(name, arguments):
            label = confirm_action.label_for(name, arguments)
            if _unattended():
                confirm_action.remember(name, arguments, label)
                return _err(f"Waiting for a yes before {label}.", needs_confirmation=True,
                            approved=False, label=label)
            if not voice_mode_active:
                confirm_action.remember(name, arguments, label)
            decision = confirm_action.confirm_sensitive_action(label)
            if not decision.get("approved"):
                return decision
    started = time.monotonic()
    try:
        result = _call_with_timeout(name, function, arguments)
        if isinstance(result, dict) and result.get("ok") and name in CHANGE_LOG_TOOLS:
            try:
                import extras148
                extras148.note_change(name, str(result.get("path") or result.get("file") or ""))
            except Exception:
                pass
    except TypeError as exc:
        return _err(f"Bad arguments for {name}: {exc}")
    except AssertionError:
        raise
    except Exception as exc:
        agent_log.event("tool_error", tool=name, error=_scrub(str(exc))[:500])
        return _err(f"{name} failed: {exc}")
    agent_log.event(
        "tool",
        tool=name,
        ok=bool(isinstance(result, dict) and result.get("ok")),
        ms=int((time.monotonic() - started) * 1000),
    )
    if not isinstance(result, dict) or "ok" not in result:
        return _err(f"{name} returned an unexpected result.")
    if sensitive and name != "confirm_before" and result.get("ok"):
        confirm_action.note_done(name, arguments, result)
    if result.get("ok"):
        _autosave_tool_memory(name, result)
        try:
            import bots as _bots

            _bots.note_tool_paths(result)
        except Exception:
            pass
    return result


def _redacted_tool_arguments(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Hide typed text in the console line. The tool still receives the text."""
    shown = dict(arguments)
    if name == "type_text" and "text" in shown:
        shown["text"] = f"[{len(str(shown['text']))} characters]"
    if name in {"replay_skill", "follow_skill"} and "inputs" in shown:
        shown["inputs"] = f"[{len(str(shown['inputs']))} characters]"
    if name == "run_blender_task" and "script" in shown:
        shown["script"] = f"[{len(str(shown['script']))} characters]"
    if name == "build_local_program" and "files" in shown:
        shown["files"] = f"[{len(str(shown['files']))} characters]"
    if name == "send_remote_update" and "message" in shown:
        shown["message"] = f"[{len(str(shown['message']))} characters]"
    if name == "gmail_send_message":
        if "body" in shown:
            shown["body"] = f"[{len(str(shown['body']))} characters]"
        if "request" in shown:
            shown["request"] = f"[{len(str(shown['request']))} characters]"
    if name in {"browser_download_tool", "perform_actions", "desktop_ui_automation"} and isinstance(
        shown.get("actions") or shown.get("steps"), list
    ):
        field = "actions" if isinstance(shown.get("actions"), list) else "steps"
        hidden: list[Any] = []
        for step in shown[field]:
            if isinstance(step, dict) and "text" in step:
                step = dict(step)
                step["text"] = f"[{len(str(step['text']))} characters]"
            hidden.append(step)
        shown[field] = hidden
    if name == "routine_macro_engine" and isinstance(shown.get("steps"), list):
        hidden_steps: list[Any] = []
        for step in shown["steps"]:
            if isinstance(step, dict):
                step = dict(step)
                step["arguments"] = "[saved]"
            hidden_steps.append(step)
        shown["steps"] = hidden_steps
    return shown


# 1.4.17: results of read-only look-ups are reused for a short while, so a long task that asks the same
# question twice (or a retry after a model switch) does not run it again. Any other tool call clears it.
RESULT_CACHE_SECONDS = 90
_RESULT_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_RESULT_LOCK = threading.Lock()
CACHEABLE_TOOLS = frozenset({"list_files", "pc_status", "read_file", "read_page_text", "web_search", "recall_memory",
                             "search_files_by_time", "search_local_files", "list_routines", "list_connectors"})


def _cache_key(name: str, arguments: dict[str, Any]) -> str:
    try:
        return name + ":" + json.dumps(arguments or {}, sort_keys=True, default=str)
    except Exception:
        return ""


def _cache_get(name: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
    if name not in CACHEABLE_TOOLS:
        with _RESULT_LOCK:
            _RESULT_CACHE.clear()   # something may have changed (a file written, a page clicked)
        return None
    key = _cache_key(name, arguments)
    with _RESULT_LOCK:
        hit = _RESULT_CACHE.get(key)
    if hit and time.monotonic() - hit[0] < RESULT_CACHE_SECONDS:
        return {**hit[1], "cached": True}
    return None


def _cache_put(name: str, arguments: dict[str, Any], result: dict[str, Any]) -> None:
    if name in CACHEABLE_TOOLS and isinstance(result, dict) and result.get("ok"):
        key = _cache_key(name, arguments)
        if key:
            with _RESULT_LOCK:
                _RESULT_CACHE[key] = (time.monotonic(), dict(result))
                if len(_RESULT_CACHE) > 200:
                    _RESULT_CACHE.pop(next(iter(_RESULT_CACHE)))


def clear_result_cache() -> None:
    with _RESULT_LOCK:
        _RESULT_CACHE.clear()


def _execute_logged_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Print one tool call, run it, and print the result. Secrets are scrubbed."""
    shown = _redacted_tool_arguments(name, arguments)
    print(f"[tool] {_scrub(f'{name}({json.dumps(shown, default=str)})')}", flush=True)
    routine_macros.note_tool(name)
    cached = _cache_get(name, arguments)
    if cached is not None:   # 1.4.17: already worked out a moment ago in this task, nothing changed since
        print(f"[tool] cached: {name}", flush=True)
        return cached
    result = invoke_tool(name, arguments)
    _cache_put(name, arguments, result)
    status = "ok" if result.get("ok") else "error"
    detail = _scrub(str(result.get("message") or result.get("error") or ""))
    print(f"[tool] {status}: {detail}", flush=True)
    return result


# 1.4.16: independent read-only look-ups asked for in the same step run at the same time.
PARALLEL_SAFE_TOOLS = frozenset({"list_files", "pc_status", "read_file", "read_page_text", "web_search", "recall_memory",
                                 "get_task_progress", "list_routines", "search_files_by_time", "search_local_files",
                                 "get_clipboard_text", "list_connectors"})


def parallel_results(calls: list[tuple[str, dict[str, Any]]]) -> dict[int, dict[str, Any]]:
    """Run 2+ read-only calls at once. Returns {index: result}; {} when they must run one by one.

    Only tools in PARALLEL_SAFE_TOOLS that need no approval qualify, so approvals are never skipped or merged.
    """
    if len(calls) < 2:
        return {}
    try:
        import confirm_action
        for name, args in calls:
            if name not in PARALLEL_SAFE_TOOLS or name not in TOOLS or confirm_action.is_sensitive(name, args):
                return {}
    except Exception:
        return {}
    from concurrent.futures import ThreadPoolExecutor

    turn_state = dict(_turn_local.__dict__)
    scope_state = dict(_tool_scope.__dict__)
    cancel = getattr(_turn_local, "cancel_event", None) or stop_token.current()

    def one(item: tuple[str, dict[str, Any]]) -> dict[str, Any]:
        _turn_local.__dict__.update(turn_state)
        _tool_scope.__dict__.update(scope_state)
        stop_token.bind(cancel)
        try:
            return _execute_logged_tool(item[0], item[1])
        except Exception as exc:
            return {"ok": False, "error": f"{item[0]} failed: {_scrub(str(exc))[:200]}"}

    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=min(4, len(calls)), thread_name_prefix="tool-par") as pool:
        results = list(pool.map(one, calls))
    try:
        agent_log.event("parallel_tools", n=len(calls), ms=int((time.monotonic() - started) * 1000))
    except Exception:
        pass
    return dict(enumerate(results))


def gemini_api_keys() -> list[str]:
    """Primary Gemini key, then extra keys from other Google accounts. Blanks are dropped."""
    keys: list[str] = []
    primary = os.environ.get("GEMINI_API_KEY", "").strip()
    if primary:
        keys.append(primary)
    for part in re.split(r"[\s,;]+", os.environ.get("GEMINI_API_KEYS", "")):
        part = part.strip()
        if part and part not in keys:
            keys.append(part)
    return keys


def _scrub(text: str) -> str:
    """Remove API keys, bot tokens, and the live-stream key from text."""
    if not text:
        return text
    secrets = list(gemini_api_keys()) or [os.environ.get("GEMINI_API_KEY", "")]
    for name in ("GROQ_API_KEY", "OPENROUTER_API_KEY", "CEREBRAS_API_KEY", "NVIDIA_API_KEY"):
        value = os.environ.get(name, "")
        if len(value) >= 8:
            secrets.append(value)
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    stream_key = os.environ.get("TELEGRAM_STREAM_KEY", "")
    if len(token) >= 8:
        secrets.append(token)
    if len(stream_key) >= 8:
        secrets.append(stream_key)
    rtmp = os.environ.get("TELEGRAM_RTMP_URL", "").strip()
    if rtmp.startswith("rtmp://") or rtmp.startswith("rtmps://"):
        secrets.append(rtmp)
    hook = os.environ.get("DISCORD_WEBHOOK_URL", "")
    if hook.startswith("https://"):
        secrets.append(hook)
    app_password = os.environ.get("GMAIL_APP_PASSWORD", "")
    if len(app_password) >= 8:
        secrets.append(app_password)
    youtube_secret = os.environ.get("YOUTUBE_CLIENT_SECRET", "")
    if len(youtube_secret) >= 8:
        secrets.append(youtube_secret)
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[redacted]")
    return text


def _is_daily_quota(exc: BaseException) -> bool:
    text = str(exc)
    return "RESOURCE_EXHAUSTED" in text or "429" in text


ALL_QUOTA_MESSAGE = (
    "Every Gemini model is out of free requests for today. "
    "Paste a Groq key in Settings -> Backup model key, or wait until tomorrow."
)


def _quota_message(exc: BaseException) -> str:
    text = str(exc)
    model_match = re.search(r"model:\s*([A-Za-z0-9._\-]+)", text)
    limit_match = re.search(r"limit:\s*(\d+)", text)
    wait_match = re.search(r"retry in ([0-9]+h)?([0-9]+m)?[0-9.]*s", text, re.I)
    parts = ["The free Gemini quota for this project is used up."]
    if model_match:
        parts.append(f"Model: {model_match.group(1)}.")
    if limit_match:
        parts.append(f"Daily free limit: {limit_match.group(1)} requests.")
    if wait_match:
        hours = wait_match.group(1) or ""
        minutes = wait_match.group(2) or ""
        wait = f"{hours} {minutes}".strip()
        if wait:
            parts.append(f"It resets in about {wait}.")
    parts.append(
        "Saved keys for another Gemini account, OpenRouter, Cerebras, and NVIDIA NIM are tried when they are set. "
        "Another key in the same Google project does not raise this limit. "
        "You can wait for the reset, or turn on billing in Google AI Studio."
    )
    return " ".join(parts)


def _transient_network_error(exc: BaseException) -> bool:
    """True when a Gemini connection drop is worth one more attempt."""
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        winerror = getattr(current, "winerror", None)
        if winerror in {10053, 10054, 10060}:
            return True
        name = type(current).__name__.casefold()
        if name in {
            "connecterror",
            "readerror",
            "writeerror",
            "remoteprotocolerror",
            "networkerror",
            "connecttimeout",
            "readtimeout",
            "pooltimeout",
        }:
            return True
        text = str(current).casefold()
        if any(
            token in text
            for token in (
                "winerror 10053",
                "winerror 10054",
                "winerror 10060",
                "connection aborted",
                "connection reset",
                "connection was aborted",
                "timed out",
                "503 unavailable",
                "high demand",
                "overloaded",
                "no longer available",
                "404 not_found",
            )
        ):
            return True
        if isinstance(current, (TimeoutError, ConnectionError)):
            return True
        current = current.__cause__ or current.__context__
    return False


def _text_from(response: Any) -> str:
    chunks: list[str] = []
    for candidate in getattr(response, "candidates", None) or []:
        content = getattr(candidate, "content", None)
        for part in getattr(content, "parts", None) or []:
            if getattr(part, "thought", False):
                continue
            text = getattr(part, "text", None)
            if text:
                chunks.append(text)
    return "\n".join(chunks).strip()


def _function_response(name: str, payload: dict[str, Any], call_id: str | None) -> Any:
    """Build a function response the installed google-genai SDK accepts.

    Part.from_function_response does not take the call id. The id lives on
    FunctionResponse, and parallel calls are matched by it. Screenshot bytes
    are removed from the JSON response and attached as an image part.
    """
    from google.genai import types

    cleaned = dict(payload)
    image = cleaned.pop("_screenshot_bytes", None)
    mime = str(cleaned.pop("_screenshot_mime", "") or "image/png")
    body: dict[str, Any] = {"name": name, "response": cleaned}
    if call_id:
        body["id"] = call_id
    if isinstance(image, (bytes, bytearray)) and image:
        body["parts"] = [
            types.FunctionResponsePart.from_bytes(data=bytes(image), mime_type=mime)
        ]
    return types.Part(function_response=types.FunctionResponse(**body))


class _SpokenDelta:
    """Plain text already reduced to the new suffix of a stream chunk."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.thought = False
        self.function_call = None
        self.thought_signature = None


class _SentenceBuffer:
    """Split streaming model text into sentences that can be spoken early."""

    def __init__(self, limit: int = VOICE_SENTENCE_CHARS) -> None:
        self.pending = ""
        self.limit = limit

    def push(self, chunk: str) -> list[str]:
        if not chunk:
            return []
        self.pending += chunk
        return self._drain(final=False)

    def flush(self) -> list[str]:
        return self._drain(final=True)

    def _drain(self, final: bool) -> list[str]:
        ready: list[str] = []
        while self.pending:
            end = self._next_end(final)
            if not end:
                break
            piece = " ".join(self.pending[:end].split())
            self.pending = self.pending[end:]
            if piece:
                ready.append(piece)
        return ready

    def _next_end(self, final: bool) -> int | None:
        text = self.pending
        match = re.search(r"[.!?]+(?=\s)", text)
        if match:
            end = match.end()
            while end < len(text) and text[end].isspace():
                end += 1
            return end
        newline = text.find("\n")
        if newline != -1:
            return newline + 1
        if len(text) >= self.limit:
            window = text[: self.limit]
            cut = max(window.rfind(", "), window.rfind(" "))
            if cut >= 40:
                return cut + 1
            return self.limit
        if final and text.strip():
            return len(text)
        return None


def _function_call_key(call: Any) -> str:
    """Identity for a streamed function call. A repeated id is the same call."""
    call_id = getattr(call, "id", None)
    if call_id:
        return f"id:{call_id}"
    name = getattr(call, "name", None) or ""
    args = getattr(call, "args", None) or {}
    try:
        payload = json.dumps(dict(args), sort_keys=True, default=str)
    except Exception:
        payload = str(args)
    return f"{name}:{payload}"


def _accumulate_voice_stream(
    chunks: Any,
    on_sentence: Callable[[str], None] | None,
    cancel_event: threading.Event | None,
) -> tuple[list[Any], list[Any], str]:
    """Pull stream chunks and hand off each sentence before reading the next.

    Thought text and function-call parts are kept for history and are not spoken.
    A repeated function-call id replaces the earlier partial call.
    """
    buffer = _SentenceBuffer()
    parts: list[Any] = []
    calls: list[Any] = []
    call_at: dict[str, tuple[int, int]] = {}
    visible: list[str] = []

    def new_text(text: str) -> str:
        """Keep a delta when a chunk repeats the whole reply so far."""
        current = "".join(visible)
        if current and text.startswith(current):
            return text[len(current) :]
        return text

    raw = bool(getattr(on_sentence, "raw_tokens", False))

    def emit(ready: list[str]) -> None:
        if on_sentence is None or raw:
            return
        for sentence in ready:
            if cancel_event is not None and cancel_event.is_set():
                return
            on_sentence(sentence)

    for chunk in chunks:
        if cancel_event is not None and cancel_event.is_set():
            break
        candidates = getattr(chunk, "candidates", None) or []
        candidate = candidates[0] if candidates else None
        content = getattr(candidate, "content", None) if candidate is not None else None
        chunk_parts = getattr(content, "parts", None) if content is not None else None
        if not chunk_parts:
            loose = new_text(getattr(chunk, "text", None) or "")
            if loose:
                visible.append(loose)
                parts.append(_SpokenDelta(loose))
                if raw and on_sentence is not None and not (cancel_event is not None and cancel_event.is_set()):
                    on_sentence(loose)
                emit(buffer.push(loose))
            continue
        for part in chunk_parts:
            if cancel_event is not None and cancel_event.is_set():
                break
            call = getattr(part, "function_call", None)
            if call is not None:
                key = _function_call_key(call)
                if key in call_at:
                    part_index, call_index = call_at[key]
                    parts[part_index] = part
                    calls[call_index] = call
                else:
                    call_at[key] = (len(parts), len(calls))
                    parts.append(part)
                    calls.append(call)
                continue
            if getattr(part, "thought", False) or getattr(part, "thought_signature", None):
                parts.append(part)
                if getattr(part, "thought", False):
                    continue
            text = new_text(getattr(part, "text", None) or "")
            if not text:
                continue
            visible.append(text)
            if not getattr(part, "thought_signature", None):
                parts.append(_SpokenDelta(text))
            if raw and on_sentence is not None and not (cancel_event is not None and cancel_event.is_set()):
                on_sentence(text)
            emit(buffer.push(text))
    if cancel_event is None or not cancel_event.is_set():
        emit(buffer.flush())
    return parts, calls, "".join(visible).strip()


def _plain_text_part(part: Any) -> bool:
    if getattr(part, "thought", False):
        return False
    if getattr(part, "function_call", None) is not None:
        return False
    if getattr(part, "thought_signature", None):
        return False
    return bool(getattr(part, "text", None))


class _StreamedTurn:
    """A finished voice stream with the shape the tool loop already reads."""

    def __init__(self, content: Any, calls: list[Any], spoken_text: str) -> None:
        self.candidates = [type("Candidate", (), {"content": content})()]
        self.function_calls = calls or None
        self.spoken_text = spoken_text


def _thinking_rejected(exc: BaseException) -> bool:
    """True when a fast voice config asked for a thinking mode the model lacks."""
    text = str(exc).casefold()
    if "thinking" not in text:
        return False
    return any(
        token in text
        for token in ("invalid", "not supported", "unknown", "unsupported", "400")
    )


def _undo_path(result: dict[str, Any]) -> str:
    """A file path safe to show on an Undo button. Secret files are omitted."""
    raw = str(result.get("download_path") or result.get("path") or result.get("file") or "")
    if not raw:
        return ""
    name = Path(raw).name.casefold()
    if name == ".env" or name.startswith(".env."):
        return ""
    return raw


def _result_video(result: dict[str, Any]) -> str | None:
    """A camera recording path, for the chat player and download."""
    path = str(result.get("video") or "")
    if path.casefold().endswith((".mp4", ".webm")):
        return path
    return None


def _result_image(result: dict[str, Any]) -> str | None:
    """A screenshot or webcam still, for the chat preview. A video has its own player."""
    if _result_video(result):
        return None
    for key in ("download_path", "path", "image_path"):
        path = str(result.get(key) or "")
        if path.casefold().endswith((".png", ".jpg", ".jpeg")):
            return path
    return None


_COOLING: dict[str, float] = {}
COOL_SECONDS = 300


def cool_model(name: str) -> None:
    """1.4.15: a model that timed out or was busy goes to the back of the line for 5 minutes."""
    _COOLING[str(name)] = time.monotonic() + COOL_SECONDS


def _turn_models(order: list[str], current: str, skipped: set[str]) -> list[str]:
    """Models still worth calling. The one that just answered stays first; cooling models go last."""
    names: list[str] = []
    for name in [current, *order]:
        name = str(name or "").strip()
        if name and name not in skipped and name not in names:
            names.append(name)
    now = time.monotonic()
    return [n for n in names if _COOLING.get(n, 0) <= now] + [n for n in names if _COOLING.get(n, 0) > now]


def model_candidates(first: str | None = None) -> list[str]:
    """First choice, then rules.yaml agent.models, then the built-in fallbacks."""
    order: list[str] = []
    for name in [first, *(rules.agent_setting("models", []) or []), *FALLBACK_MODELS]:
        name = str(name or "").strip()
        if name and name not in order:
            order.append(name)
    return order


def models_for_turn(order: list[str], spent: set[str] | None = None) -> tuple[list[str], bool]:
    """Drop models already out of free quota today.

    The second value is true when the order had models and every one of them is spent,
    which means the turn should use the Groq backup instead of calling Gemini.
    """
    gone = spent or set()
    fresh = [name for name in order if name not in gone]
    return fresh, bool(order) and not fresh


def _spent_models() -> set[str]:
    try:
        import extras148
        return set(extras148.exhausted_models())
    except Exception:
        return set()


def _switch_providers(user_text: str, history: list[Any], types: Any, on_event: Callable[[dict[str, Any]], None] | None, kind: str) -> str | None:
    """Answer with the next saved free provider. None when none are set or all decline."""
    import cloud_fallback

    reply = cloud_fallback.run_chain(user_text, on_event=on_event, kind=kind)
    if not reply:
        return None
    history.append(types.Content(role="model", parts=[types.Part.from_text(text=reply)]))
    return reply


def _use_quota_backup(user_text: str, history: list[Any], types: Any, on_event: Callable[[dict[str, Any]], None] | None) -> str | None:
    """Groq reply when every Gemini model is out for today. None when no backup key is set."""
    import cloud_fallback

    if not cloud_fallback.available():
        return None
    print("[quota] Every Gemini model is out of free requests today. Using the backup model.", flush=True)
    reply = cloud_fallback.run(user_text, on_event=on_event)
    history.append(types.Content(role="model", parts=[types.Part.from_text(text=reply)]))
    return reply


def max_tool_rounds() -> int:
    try:
        return max(1, int(rules.agent_setting("max_tool_rounds", MAX_TOOL_ROUNDS)))
    except (TypeError, ValueError):
        return MAX_TOOL_ROUNDS


def _model_configs(voice: bool) -> tuple[Any, Any | None]:
    """Build the Gemini config. Voice replies use a short cap and minimal thinking.

    The second config is the same voice request without thinking settings, used
    only when the model rejects that field. Typed turns are not capped.
    """
    from google.genai import types

    instruction = system_prompt()
    if voice:
        instruction += VOICE_REPLY_GUIDE
    cache_key = (voice, instruction, id(TOOL_DECLARATIONS), len(TOOL_DECLARATIONS))
    hit = _CONFIG_CACHE.get(cache_key)
    if hit is not None:   # 1.4.15: same prompt + tools -> same objects (and a stable prefix for Gemini's implicit cache)
        return hit
    if len(_CONFIG_CACHE) > 8:
        _CONFIG_CACHE.clear()
    built = _build_model_configs(voice, instruction)
    _CONFIG_CACHE[cache_key] = built
    return built


def _build_model_configs(voice: bool, instruction: str) -> tuple[Any, Any | None]:
    from google.genai import types

    shared: dict[str, Any] = {
        "system_instruction": instruction,
        "tools": [types.Tool(function_declarations=TOOL_DECLARATIONS)],
        "automatic_function_calling": types.AutomaticFunctionCallingConfig(disable=True),
        "temperature": 0.2,
    }
    if not voice:
        return types.GenerateContentConfig(**shared), None
    shared["max_output_tokens"] = VOICE_MAX_OUTPUT_TOKENS
    plain = types.GenerateContentConfig(**shared)
    voiced = types.GenerateContentConfig(
        **shared,
        thinking_config=types.ThinkingConfig(
            thinking_level=types.ThinkingLevel.MINIMAL,
        ),
    )
    return voiced, plain


def _finish_voice_stream(
    chunks: Any,
    on_sentence: Callable[[str], None] | None,
    cancel_event: threading.Event | None,
) -> _StreamedTurn:
    """Read one voice stream. Sentences are emitted before the next chunk."""
    from google.genai import types

    parts, calls, text = _accumulate_voice_stream(chunks, on_sentence, cancel_event)
    merged: list[Any] = []
    pending = ""
    for part in parts:
        if _plain_text_part(part):
            pending += getattr(part, "text", "") or ""
            continue
        if pending:
            merged.append(types.Part.from_text(text=pending))
            pending = ""
        merged.append(part)
    if pending:
        merged.append(types.Part.from_text(text=pending))
    content = types.Content(role="model", parts=merged) if merged else None
    return _StreamedTurn(content, calls, text)


def _request_voice_model(
    client: Any,
    model: str,
    history: list[Any],
    config: Any,
    *,
    on_sentence: Callable[[str], None] | None,
    cancel_event: threading.Event | None,
    spoke: dict[str, bool],
    first: threading.Event | None = None,
) -> _StreamedTurn:
    def emit(sentence: str) -> None:
        spoke["yes"] = True
        if on_sentence is not None:
            on_sentence(sentence)

    emit.raw_tokens = bool(getattr(on_sentence, "raw_tokens", False))  # type: ignore[attr-defined]

    stream = client.models.generate_content_stream(
        model=model,
        contents=history,
        config=config,
    )
    if first is not None:
        stream = _mark_first(stream, first)
    return _finish_voice_stream(stream, emit, cancel_event)


def _mark_first(chunks: Any, first: threading.Event) -> Any:
    for chunk in chunks:
        first.set()
        yield chunk


def _attempt(fn: Callable[[threading.Event], Any], cancel_event: Any, *, streaming: bool) -> Any:
    """1.4.15: one model attempt. Streaming: the first chunk must arrive within 8 s; otherwise the attempt
    is dropped (the worker is abandoned) and the caller fails over at once. Stop ends it immediately."""
    first = threading.Event()
    box: dict[str, Any] = {}
    parent = dict(_turn_local.__dict__)

    def runner() -> None:
        _turn_local.__dict__.update(parent)
        stop_token.bind(cancel_event)
        try:
            box["result"] = fn(first)
        except BaseException as exc:
            box["error"] = exc

    worker = threading.Thread(target=runner, name="pb-model", daemon=True)
    worker.start()
    limit = ATTEMPT_TIMEOUT_MS / 1000.0 if streaming else NONSTREAM_TIMEOUT_S
    started = time.monotonic()
    while worker.is_alive():
        worker.join(0.05)
        if cancel_event is not None and cancel_event.is_set() and worker.is_alive():
            raise stop_token.Stopped("Stopped.")
        if worker.is_alive() and not first.is_set() and time.monotonic() - started > limit:
            raise TimeoutError(f"The model did not start answering within {int(limit)} s (timed out).")
    if "error" in box:
        raise box["error"]
    return box.get("result")


EVIDENCE_TOOLS = frozenset({"take_screenshot", "scroll", "capture_screenshot_file", "find_on_screen", "read_page_text",
                            "ui_read", "ui_find", "ui_click", "ui_set_text"})
EMPTY_REPLY_NOTE = "The model is busy and sent an empty answer. Please ask again in a moment."


def friendly_model_error(exc: BaseException | str) -> str:
    """One short line for a model error instead of the raw JSON (503, 429, empty)."""
    text = str(exc or "")
    low = text.casefold()
    if low.startswith(("the free gemini quota", "every gemini model", "all gemini models are busy")):
        return text[:400]   # already a plain message
    if any(k in low for k in ("503", "unavailable", "high demand", "overloaded", "busy")):
        return "Gemini is busy right now, retrying… If this keeps up, try again in a minute."
    if any(k in low for k in ("429", "resource_exhausted", "quota")):
        return ALL_QUOTA_MESSAGE if "every gemini model" in low else "Gemini's free limit is used up for now. The backup model is tried next."
    if "no text" in low or "no content" in low or "empty" in low:
        return EMPTY_REPLY_NOTE
    if "timed out" in low or "timeout" in low:
        return "The model took too long to answer. Please try again."
    return text[:200]


TEXT_CALL_NUDGE = (
    "Your reply wrote a tool call as text, like [[tool(...)]]. Text does nothing. "
    "If the step is needed, call the tool with a real function call now. "
    "If it is not needed, answer in plain words without any [[...]] call and without saying it ran."
)

EVIDENCE_NUDGE = (
    "[self-check] You are about to report this task as done/complete, but in this turn you have not "
    "looked at the screen (take_screenshot or scroll) to confirm it. Check the real result now, "
    "fix anything that is not done, then report only what you saw."
)
RESUME_TEXT = (
    "[resume] The model service failed in the middle of the task. Look at the screen and your plan, "
    "then continue from the first unfinished step. Do not redo finished steps. Same rules as before."
)
_SCAN_EVIDENCE = {"wingz_scan"}
_TASK_WORDS = re.compile(r"\b(wingz|assignment|syllabus|upload|fill|save answer|portal|task|document|pdf)\b", re.I)
_DONE_CLAIM = re.compile(
    r"FINAL:|\ball\b[^.\n]{0,60}\b(complete|completed|done|checked)\b|\bnone left\b|"
    r"\bno (unfinished|incomplete|pending)\b|\b(saved|uploaded|submitted) (it|them|all|the)\b",
    re.I,
)
AUTO_RESUMES = 2
RESUME_WAIT_SECONDS = 3   # 1.4.15: was 60 s; failover is immediate now
ATTEMPT_TIMEOUT_MS = 8000   # 1.4.15: time to the first streamed chunk; a slow model fails over instead of hanging
HTTP_DEADLINE_MS = 60000    # Gemini rejects a server deadline under 10 s, so the 8 s limit is enforced here
NONSTREAM_TIMEOUT_S = 20.0
_CLIENTS: dict[str, Any] = {}
_CONFIG_CACHE: dict[tuple[Any, ...], tuple[Any, Any]] = {}
FAST_SYSTEM = (
    "You are Ped Bot, Pedro's friendly assistant on his Windows PC. Reply briefly, warmly and in plain words. "
    "You have no tools in this reply. If the message asks you to do, open, check, find or change anything "
    "on the PC, the web, files, apps, email, routines or bots, or needs current information "
    "(time, date, news, weather, prices), reply with exactly [[NEEDS_TOOLS]] and nothing else."
)
NEEDS_TOOLS = "[[NEEDS_TOOLS]]"
_FAST_GREETING = re.compile(
    r"^(hi+|hey+|hello+|hiya|yo|sup|wassup|what'?s up|hola|namaste|good (morning|afternoon|evening|night)|"
    r"thanks?( you)?|thank u|ty|ok(ay)?|cool|nice|great|awesome|bye|see you|how are (you|u)|how'?s it going|"
    r"who are you|what can you do)\b[\s!.?,:)\w']*$", re.I)
_FAST_QUESTION = re.compile(r"^(what|who|why|how|when|where|which|is|are|does|do|can you explain|explain|define|"
                            r"tell me (a joke|a fact|about)|meaning of|difference between)\b", re.I)
_FAST_BLOCK = re.compile(
    r"\b(my|me|mine|i|i'm|pc|computer|laptop|file|files|folder|open|screen|click|download|downloads|desktop|run|"
    r"install|chrome|edge|browser|email|mail|gmail|send|order|buy|today|tonight|tomorrow|now|time|date|weather|"
    r"news|latest|current|price|remind|routine|schedule|bot|bots|youtube|post|upload|write|create|make|save|"
    r"delete|close|play|search|find|check|show|list|start|stop|set|turn|wingz|task|workflow|replay|terminal|"
    r"command|this|that|it|here|there|above|previous|again|continue)\b", re.I)


def simple_chat(text: str) -> bool:
    """1.4.15: a greeting or a general question that needs no tools (answered on the fast path)."""
    t = " ".join(str(text or "").split())
    if not t or len(t) > 160 or t.startswith("[") or "\n" in str(text or ""):
        return False
    if _FAST_BLOCK.search(t):
        return False
    return bool(_FAST_GREETING.match(t) or _FAST_QUESTION.match(t))


def _gemini_client(genai: Any, key: str) -> Any:
    """One client per key, reused: keeps the HTTPS connection warm. Every attempt times out after 8 s."""
    if genai_client_override is not None:
        return genai_client_override(key)
    client = _CLIENTS.get(key)
    if client is None:
        from google.genai import types
        client = genai.Client(api_key=key, http_options=types.HttpOptions(timeout=HTTP_DEADLINE_MS))
        _CLIENTS[key] = client
    return client


def _fast_reply(user_text: str, history: list[Any], model: str, *, on_text: Any, cancel_event: Any,
                on_event: Any) -> str | None:
    """Answer simple chat with a small no-tools request on Flash-Lite (Groq if Gemini fails).

    None means "use the full agent" (the model asked for tools, or every fast model failed).
    """
    from google import genai
    from google.genai import types

    keys = gemini_api_keys()
    if not keys:
        return None
    block = memory_prompt_block()
    config = types.GenerateContentConfig(
        system_instruction=FAST_SYSTEM + ("\n" + block if block else ""), temperature=0.4, max_output_tokens=600,
        thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.MINIMAL))
    plain = types.GenerateContentConfig(system_instruction=config.system_instruction, temperature=0.4,
                                        max_output_tokens=600)
    recent = [c for c in history[-8:] if getattr(c, "role", "") in ("user", "model")
              and all(getattr(p, "text", None) for p in (getattr(c, "parts", None) or []))]
    contents = [*recent, types.Content(role="user", parts=[types.Part.from_text(text=user_text)])]
    held = {"buf": "", "open": False}

    def gate(chunk: str) -> None:   # hold the first characters until we know it is not [[NEEDS_TOOLS]]
        if held["open"]:
            on_text(chunk)
            return
        held["buf"] += chunk
        probe = held["buf"].lstrip()
        if NEEDS_TOOLS.startswith(probe) or NEEDS_TOOLS in probe:
            return
        held["open"] = True
        on_text(held["buf"])

    gate.raw_tokens = bool(getattr(on_text, "raw_tokens", False))  # type: ignore[attr-defined]
    try:   # Groq first: a tiny request answers in about a second while Gemini is often slow or busy
        import cloud_fallback
        if cloud_fallback.providers_for("busy"):
            started = time.monotonic()
            msgs = []
            for c in recent:
                txt = " ".join(getattr(p, "text", "") or "" for p in (c.parts or []))
                msgs.append({"role": "assistant" if c.role == "model" else "user", "content": txt[:2000]})
            msgs.append({"role": "user", "content": user_text})
            text = stop_token.run(lambda: cloud_fallback.quick_chat(config.system_instruction, msgs), cancel_event)
            if text and NEEDS_TOOLS in text:
                return None
            if text:
                agent_log.event("fast_reply", model="backup", ms=int((time.monotonic() - started) * 1000))
                if on_text:
                    on_text(text)
                history.append(types.Content(role="user", parts=[types.Part.from_text(text=user_text)]))
                history.append(types.Content(role="model", parts=[types.Part.from_text(text=text)]))
                if on_event is not None:
                    on_event({"event": "final", "text": text})
                return text
    except stop_token.Stopped:
        return ""
    except Exception:
        pass
    client = _gemini_client(genai, keys[0])
    lites = [m for m in model_candidates(model) if "lite" in m] or [model]
    for name in _turn_models(lites, lites[0], set()):
        for cfg in (config, plain):
            spoke = {"yes": False}
            try:
                stop_token.checkpoint(cancel_event)
                started = time.monotonic()
                resp = _attempt(lambda first: _request_voice_model(
                    client, name, contents, cfg, on_sentence=gate if on_text else None,
                    cancel_event=cancel_event, spoke=spoke, first=first), cancel_event, streaming=True)
                text = str(getattr(resp, "spoken_text", "") or "").strip()
                _note_usage(name, True)
                agent_log.event("fast_reply", model=name, ms=int((time.monotonic() - started) * 1000))
                if not text or NEEDS_TOOLS in text:
                    return None
                if on_text and not held["open"] and held["buf"]:
                    on_text(held["buf"])
                history.append(types.Content(role="user", parts=[types.Part.from_text(text=user_text)]))
                history.append(types.Content(role="model", parts=[types.Part.from_text(text=text)]))
                if on_event is not None:
                    on_event({"event": "final", "text": text})
                return text
            except stop_token.Stopped:
                return ""
            except Exception as exc:
                _note_usage(name, False, str(exc))
                if spoke["yes"]:
                    return None
                if cfg is config and _thinking_rejected(exc):
                    continue
                agent_log.event("model_switch", frm=name, to="next", reason=_scrub(str(exc))[:120])
                if _transient_network_error(exc) or _is_daily_quota(exc):
                    cool_model(name)
                break
    try:
        import cloud_fallback
        if cloud_fallback.providers_for("busy"):
            reply = stop_token.run(lambda: cloud_fallback.run_chain(user_text, on_event=on_event, kind="busy",
                                                                    max_rounds=1), cancel_event)
            if reply:
                history.append(types.Content(role="user", parts=[types.Part.from_text(text=user_text)]))
                history.append(types.Content(role="model", parts=[types.Part.from_text(text=reply)]))
                return reply
    except stop_token.Stopped:
        return ""
    except Exception:
        pass
    return None


# 1.4.16: Groq plans the tool steps for everyday PC tasks (about 0.7 s a round vs 1-12 s on a busy Gemini).
# Gemini still takes the turn when Groq is not saved, declines, or the task is a big build/creative job.
_PLANNER_SKIP = re.compile(r"\b(blender|youtube|wingz|itvedant|excel|sql|build|code|program|script|mod|video|shorts|"
                           r"routine|bot|teach|taught|remember|plan)\b", re.I)


def _fast_planner_turn(user_text: str) -> bool:
    text = str(user_text or "")
    if text.startswith("[resume]") or len(text) > 600 or _PLANNER_SKIP.search(text):
        return False
    if getattr(_tool_scope, "allowed", None) is not None or _active_parts():
        return False
    try:
        if not bool(rules.agent_setting("fast_planner", True)):
            return False
        import cloud_fallback
        return bool(cloud_fallback.providers_for("busy"))
    except Exception:
        return False


def _history_text(history: list[Any], limit: int = 8) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for item in history[-limit * 2:]:
        role = "assistant" if getattr(item, "role", "") == "model" else "user"
        text = " ".join(str(getattr(p, "text", "") or "") for p in (getattr(item, "parts", None) or [])).strip()
        if text:
            out.append({"role": role, "content": text[:1500]})
    return out[-limit:]


def _plan_with_backup(user_text: str, history: list[Any], types: Any, on_event: Any, cancel_event: Any) -> str | None:
    import cloud_fallback

    started = time.monotonic()
    try:
        prior = _history_text(history)
        reply = stop_token.run(lambda: cloud_fallback.run_chain(user_text, on_event=on_event, kind="busy", history=prior),
                               cancel_event)
    except stop_token.Stopped:
        return ""
    except Exception as exc:
        agent_log.event("planner_fail", reason=_scrub(str(exc))[:120])
        return None
    if not reply:
        return None
    agent_log.event("planner", ms=int((time.monotonic() - started) * 1000))
    history.append(types.Content(role="user", parts=[types.Part.from_text(text=user_text)]))
    history.append(types.Content(role="model", parts=[types.Part.from_text(text=reply)]))
    return reply


CHANGE_LOG_TOOLS = frozenset({"make_document", "write_text_file", "create_directory", "capture_screenshot_file", "build_local_program"})
WINGZ_BLOCKED_TOOLS = frozenset({"launch_application", "launch_any_app"})
wingz_turn = False


def _wingz_on() -> bool:
    """True for this chat thread. Other chats do not inherit it."""
    if getattr(_turn_local, "wingz_bound", False):
        return bool(getattr(_turn_local, "wingz", False))
    return bool(wingz_turn)


def _note_usage(model: str, ok: bool, error: str = "") -> None:
    if genai_client_override is not None:  # tests use fake clients; never pollute real usage
        return
    try:
        import extras148
        extras148.note_model_call(model, ok, error)
    except Exception:
        pass


def could_not_verify(user_text: str, used_tools: set[str]) -> str:
    missing = []
    if "scroll" not in used_tools and "read_page_text" not in used_tools:
        missing.append("I never scrolled or read the page list, so I did not see every item")
    if not used_tools & EVIDENCE_TOOLS:
        missing.append("I took no screenshot of the result")
    missing = missing or ["I could not confirm the result on screen"]
    return ("Could not verify. I am not reporting this as done because: " + "; ".join(missing) +
            ". Nothing is claimed as finished. Ask me to continue and I will check each item on screen.")


def needs_evidence(user_text: str, reply: str, used_tools: set[str]) -> bool:
    """True when a task reply claims completion but no screen check ran this turn."""
    if (_wingz_on() or re.search(r"\bwingz|syllabus\b", user_text or "", re.I)) and _DONE_CLAIM.search(reply or "") \
            and not used_tools & {"scroll", "read_page_text", "wingz_scan"}:
        return True  # a syllabus can only be judged after scrolling it in this turn
    if used_tools & EVIDENCE_TOOLS:
        return False
    tasky = bool(_TASK_WORDS.search(user_text or "")) or bool(used_tools & {"start_task", "create_task_plan"})
    return tasky and bool(_DONE_CLAIM.search(reply or ""))


def _busy_error(exc: BaseException) -> bool:
    text = str(exc).casefold()
    return any(k in text for k in ("all gemini models are busy", "503", "high demand", "overloaded",
                                   "did not return a response"))


# 1.4.9: pictures / PDFs the user attached to this chat message, as (bytes, mime).
# The chat app sets this for one turn and clears it afterwards.
turn_parts: list[tuple[bytes, str]] = []


def _user_parts(types: Any, user_text: str) -> list[Any]:
    parts = [types.Part.from_text(text=user_text)]
    attached = _active_parts()
    if attached and not str(user_text).startswith("[resume]"):
        parts += [types.Part.from_bytes(data=data, mime_type=mime) for data, mime in attached]
    return parts


def run_agent(user_text: str, history: list[Any], model: str, **kwargs: Any) -> str:
    """Run a turn; if the model service drops mid-task, wait and resume from the screen.

    Voice turns are never resumed. The history (with all finished steps) is kept.
    """
    voice = bool(kwargs.get("voice"))
    cancel_event = kwargs.get("cancel_event")
    try:   # 1.4.17: open the connection to the planner model while the turn is being set up
        import cloud_fallback
        threading.Thread(target=cloud_fallback.warm, daemon=True, name="warm").start()
    except Exception:
        pass
    on_event = kwargs.get("on_event")
    text = user_text
    if not str(user_text).startswith("[resume]"):
        _turn_local.wingz_bound = True
        _turn_local.wingz = bool(re.search(r"\bwingz|itvedant\b", user_text or "", re.I))
    for attempt in range(AUTO_RESUMES + 1):
        try:
            return _run_agent_core(text, history, model, **kwargs)
        except RuntimeError as exc:
            if voice or attempt >= AUTO_RESUMES or not _busy_error(exc):
                raise
            print(f"[resume] {exc}. Resuming in {RESUME_WAIT_SECONDS}s.", flush=True)
            if on_event is not None:
                try:
                    on_event({"event": "resume", "text": f"Model busy. Resuming in {RESUME_WAIT_SECONDS}s."})
                except Exception:
                    pass
            if cancel_event is not None:
                if cancel_event.wait(RESUME_WAIT_SECONDS):
                    raise
            else:
                time.sleep(RESUME_WAIT_SECONDS)
            text = RESUME_TEXT
    raise RuntimeError("unreachable")


def _run_agent_core(
    user_text: str,
    history: list[Any],
    model: str,
    *,
    voice: bool = False,
    on_sentence: Callable[[str], None] | None = None,
    cancel_event: threading.Event | None = None,
    on_text: Callable[[str], None] | None = None,
    on_event: Callable[[dict[str, Any]], None] | None = None,
) -> str:
    """Send one user turn and follow tool calls until the model answers.

    Voice turns stream. Each finished sentence is handed to `on_sentence`
    while later tokens and tool rounds are still running. Typed turns stay
    on one blocking request with no output cap.
    """
    begin_task_turn(user_text)
    import grounding
    grounding.begin()
    stop_token.bind(cancel_event)
    _turn_local.cancel_event = cancel_event
    if local_llm.use_local_first(user_text):
        return local_llm.local_llm_fallback(
            user_text,
            voice=voice,
            on_sentence=on_sentence,
        )
    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:
        raise RuntimeError(
            "The Gemini SDK is not installed for this Python. From the project "
            "folder run: .\\.venv\\Scripts\\Activate.ps1"
        ) from exc

    keys = gemini_api_keys()
    if not keys:
        raise RuntimeError(
            "GEMINI_API_KEY is not set. Add it to .env or the environment. "
            "See README.md."
        )
    key_at = 0
    _capture_user_memory(user_text)
    if not voice and getattr(_tool_scope, "allowed", None) is None and not _active_parts() \
            and simple_chat(user_text):
        fast = _fast_reply(user_text, history, model, on_text=on_text, cancel_event=cancel_event, on_event=on_event)
        if fast is not None:
            return fast
    if not voice and _fast_planner_turn(user_text):
        planned = _plan_with_backup(user_text, history, types, on_event, cancel_event)
        if planned is not None:
            return planned
    client = _gemini_client(genai, keys[0])
    config, voice_plain = _model_configs(voice)
    active_config = config
    history.append(types.Content(role="user", parts=_user_parts(types, user_text)))
    model_order = model_candidates(model)
    voice_lines: list[str] = []
    stream_text = on_text is not None and not voice
    rounds = max_tool_rounds()

    def _emit(kind: str, **fields: Any) -> None:
        if on_event is not None:
            try:
                on_event({"event": kind, **fields})
            except Exception:
                pass

    if not voice and model_order and all(_COOLING.get(m, 0) > time.monotonic() for m in model_order):
        # 1.4.15: every Gemini model timed out or was busy in the last 5 minutes: go straight to the backup
        try:
            import cloud_fallback
            if cloud_fallback.providers_for("busy"):
                print("[busy] Gemini models are cooling down. Using the saved backup provider right away.", flush=True)
                switched = _switch_providers(user_text, history, types, on_event, "busy")
                if switched is not None:
                    return switched
        except stop_token.Stopped:
            return ""
    used_tools: set[str] = set()
    evidence_nudges = 0
    text_call_nudges = 0
    skipped: set[str] = set()
    saw_quota = False
    chosen = model
    for _round in range(rounds):
        stop_token.checkpoint(cancel_event, on_pause=lambda: _emit("step", label="Paused. Press Resume to go on.", name=""),
                              on_resume=lambda: _emit("step", label="Resumed.", name=""))
        delays: tuple[int, ...] = ()   # 1.4.15: no 5/15/30 s backoff; a failed model hands over at once
        try:   # 1.4.15: messages Pedro sent while this task runs (add/change instructions, answers)
            import live_steer
            steer = live_steer.take()
        except Exception:
            steer = []
        if steer:
            note = live_steer.STEER_NOTE + "\n".join(f"- {m}" for m in steer)
            last = history[-1] if history else None
            if last is not None and getattr(last, "role", "") == "user" and getattr(last, "parts", None) is not None:
                last.parts.append(types.Part.from_text(text=note))
            else:
                history.append(types.Content(role="user", parts=[types.Part.from_text(text=note)]))
            _emit("step", label="Got your message - adjusting the task.", name="steer")
            agent_log.event("steer", n=len(steer))
        response = None
        quota_error: BaseException | None = None
        reason = ""
        order = _turn_models(model_order, chosen, skipped)
        if not order:
            switched = _switch_providers(user_text, history, types, on_event, "quota" if saw_quota else "busy")
            if switched is not None:
                return switched
            raise RuntimeError("Gemini did not return a response.")
        for index, active_model in enumerate(order):
            if index:
                previous = order[index - 1]
                if reason == "quota":
                    print(
                        f"[quota] {previous} is out of free requests. "
                        f"Switching to {active_model}.",
                        flush=True,
                    )
                else:
                    print(
                        f"[net] {previous} dropped the connection. Switching to {active_model}.",
                        flush=True,
                    )
                agent_log.event("model_switch", frm=previous, to=active_model)
                _emit("model_switch", model=active_model)
            for delay in (*delays, None):
                spoke = {"yes": False}
                try:
                    if stream_text:
                        response = _attempt(lambda first: _request_voice_model(
                            client,
                            active_model,
                            history,
                            active_config,
                            on_sentence=on_text,
                            cancel_event=cancel_event,
                            spoke=spoke,
                            first=first,
                        ), cancel_event, streaming=True)
                    elif voice:
                        response = _request_voice_model(
                            client,
                            active_model,
                            history,
                            active_config,
                            on_sentence=on_sentence,
                            cancel_event=cancel_event,
                            spoke=spoke,
                        )
                    else:
                        response = _attempt(lambda first: client.models.generate_content(
                            model=active_model,
                            contents=history,
                            config=active_config,
                        ), cancel_event, streaming=False)
                    _note_usage(active_model, True)
                    break
                except stop_token.Stopped:
                    return "\n".join(voice_lines)
                except Exception as exc:
                    _note_usage(active_model, False, str(exc))
                    if (
                        voice
                        and voice_plain is not None
                        and active_config is not voice_plain
                        and not spoke["yes"]
                        and _thinking_rejected(exc)
                    ):
                        active_config = voice_plain
                        voice_plain = None
                        continue
                    if _is_daily_quota(exc):
                        if spoke["yes"]:
                            raise RuntimeError(_quota_message(exc)) from exc
                        skipped.add(active_model)
                        saw_quota = True
                        quota_error = exc
                        reason = "quota"
                        response = None
                        break
                    if (
                        delay is not None
                        and _transient_network_error(exc)
                        and not spoke["yes"]
                    ):
                        print(
                            f"[net] Gemini connection dropped. Retrying in {delay}s.",
                            flush=True,
                        )
                        if stop_token.wait(delay, cancel_event):
                            return "\n".join(voice_lines)
                        continue
                    if _transient_network_error(exc) and not spoke["yes"] and not voice:
                        print(f"[net] {active_model}: {_scrub(str(exc))[:160]}", flush=True)
                        agent_log.event("model_fail", model=active_model, error=_scrub(str(exc))[:200])
                        cool_model(active_model)
                        skipped.add(active_model)
                        reason = "net"
                        if index < len(order) - 1:
                            response = None
                            break
                        import cloud_fallback
                        if cloud_fallback.providers_for("busy"):
                            print("[busy] All Gemini models are busy. Trying a saved backup provider.", flush=True)
                            switched = _switch_providers(user_text, history, types, on_event, "busy")
                            if switched is not None:
                                return switched
                        if not local_llm.ollama_reachable():
                            raise RuntimeError(cloud_fallback.NO_BACKUP_MESSAGE) from exc
                    if (
                        _transient_network_error(exc)
                        and not spoke["yes"]
                        and local_llm.ollama_reachable()
                    ):
                        print(
                            "[local] Gemini connection failed. Switching to Ollama.",
                            flush=True,
                        )
                        reply = local_llm.local_llm_fallback(
                            user_text,
                            voice=voice,
                            on_sentence=on_sentence,
                        )
                        history.append(
                            types.Content(
                                role="model",
                                parts=[types.Part.from_text(text=reply)],
                            )
                        )
                        return reply
                    raise RuntimeError(_scrub(str(exc))) from exc
            if response is not None:
                model = active_model
                chosen = active_model
                break
        if response is None:
            if quota_error is not None:
                if key_at + 1 < len(keys):
                    key_at += 1
                    nxt = keys[key_at]
                    client = _gemini_client(genai, nxt)
                    print("[quota] This Gemini key is out of free requests. Trying the next saved key.", flush=True)
                    agent_log.event("model_switch", frm="gemini-key", to="next-gemini-key")
                    skipped.clear()
                    saw_quota = False
                    chosen = model_order[0]
                    quota_error = None
                    continue
                switched = _switch_providers(user_text, history, types, on_event, "quota")
                if switched is not None:
                    return switched
                raise RuntimeError(_quota_message(quota_error)) from quota_error
            raise RuntimeError("Gemini did not return a response.")

        candidate = (response.candidates or [None])[0]
        if candidate is None or candidate.content is None:
            try:
                agent_log.event("empty_reply", model=str(chosen), reason=str(getattr(candidate, "finish_reason", None)),
                                feedback=str(getattr(response, "prompt_feedback", None))[:300])
                print(f"[model] empty answer from {chosen}: finish_reason={getattr(candidate, 'finish_reason', None)} "
                      f"feedback={str(getattr(response, 'prompt_feedback', None))[:200]}", flush=True)
            except Exception:
                pass
            if voice and voice_lines:
                return "\n".join(voice_lines)
            return EMPTY_REPLY_NOTE
        calls = list(response.function_calls or [])
        if voice:
            piece = str(getattr(response, "spoken_text", "") or "").strip()
            if piece:
                voice_lines.append(piece)
        cancelled = cancel_event is not None and cancel_event.is_set()
        if cancelled:
            if voice_lines and not calls:
                history.append(candidate.content)
            return "\n".join(voice_lines)
        history.append(candidate.content)
        if not calls:
            if voice:
                said = _finish_claimed_launch(
                    "\n".join(voice_lines) or EMPTY_REPLY_NOTE, _emit, user_text
                )
                return grounding.ground_reply(user_text, said)
            written = grounding.text_calls(_text_from(response))
            if written and text_call_nudges < 2:
                text_call_nudges += 1
                print(f"[check] Tool call written as text ({written[0]}). Asking for a real call.", flush=True)
                _emit("self_check", text="Running the step for real instead of describing it.")
                history.append(types.Content(role="user", parts=[types.Part.from_text(text=TEXT_CALL_NUDGE)]))
                continue
            try:   # a message arrived during this last step: keep going with it instead of ending
                import live_steer
                if live_steer.pending():
                    continue
            except Exception:
                pass
            raw = _finish_claimed_launch(_text_from(response), _emit, user_text)
            text = grounding.ground_reply(user_text, raw)
            if text != (raw or "").strip():
                _emit("step", label="Dropped a claim no tool confirmed.", name="reason")
            if evidence_nudges >= 2 and needs_evidence(user_text, text, used_tools):
                text = could_not_verify(user_text, used_tools)
                _emit("final", text=text)
                return text
            if evidence_nudges < 2 and needs_evidence(user_text, text, used_tools):
                evidence_nudges += 1
                print("[check] Done-claim without looking at the screen. Asking to verify.", flush=True)
                _emit("self_check", text="Checking the result on screen before answering.")
                history.append(types.Content(role="user", parts=[types.Part.from_text(text=EVIDENCE_NUDGE)]))
                continue
            _emit("final", text=text)
            return text or EMPTY_REPLY_NOTE

        preamble = voice_lines[-1] if voice and voice_lines else _text_from(response)
        if preamble and not voice:
            print(preamble, flush=True)
            short = " ".join(preamble.split())[:180]
            if short:
                _emit("step", label=short, name="reason")
        response_parts = []
        acted = False
        try:
            pre = parallel_results([(c.name or "", dict(c.args or {})) for c in calls])
        except Exception:
            pre = {}
        for idx, call in enumerate(calls):
            if cancel_event is not None and cancel_event.is_set():
                break
            try:
                stop_token.checkpoint(cancel_event, on_pause=lambda: _emit("step", label="Paused. Press Resume to go on.", name=""),
                                      on_resume=lambda: _emit("step", label="Resumed.", name=""))
            except stop_token.Stopped:
                break
            name = call.name or ""
            arguments = dict(call.args or {})
            used_tools.add(name)
            _emit("tool_start", name=name, arguments=_redacted_tool_arguments(name, arguments))
            if acted and name in grounding.ACTION_TOOLS:
                result = {
                    "ok": False,
                    "held": True,
                    "error": (
                        "Held. One screen action already ran in this step. "
                        "Read that result, then choose the next action. This one did not run."
                    ),
                }
            else:
                result = grounding.repeat_error(name, arguments)
                if result is None:
                    result = pre[idx] if idx in pre else _execute_logged_tool(name, arguments)
                if name in grounding.ACTION_TOOLS:
                    acted = True
            grounding.note(name, result)
            if result.get("ok"):
                notes = getattr(_turn_local, "tool_notes", None)
                if notes is None or getattr(_turn_local, "tool_notes_for", None) != user_text:
                    notes = _turn_local.tool_notes = []
                    _turn_local.tool_notes_for = user_text
                args_txt = " ".join(str(v) for v in (arguments or {}).values() if isinstance(v, (str, int, float)))
                notes.append(f"{name.replace('_', ' ')} {args_txt[:160]} {result.get('message') or ''}"[:400])
                del notes[:-60]
            _emit(
                "tool_end",
                name=name,
                ok=bool(result.get("ok")),
                detail=_scrub(str(result.get("message") or result.get("error") or ""))[:400],
                image=_result_image(result),
                video=_result_video(result),
                path=_undo_path(result) if result.get("ok") else "",
            )
            shown = dict(result)
            shown["ground"] = grounding.stamp(result)
            response_parts.append(
                _function_response(name, shown, getattr(call, "id", None))
            )
        history.append(types.Content(role="user", parts=response_parts))
        if cancel_event is not None and cancel_event.is_set():
            return "\n".join(voice_lines)

    if voice and voice_lines:
        return "\n".join(voice_lines)
    return (
        "Stopped after "
        f"{rounds} tool rounds. Ask for the next step on its own, or raise "
        "agent.max_tool_rounds in rules.yaml."
    )


_TYPED_EXIT = {"exit", "quit"}
_TYPED_VOICE = {"v", "voice", "voice mode"}
_TYPED_TEXT = {"t", "text", "text mode"}
_SPOKEN_TEXT = {"text mode", "stop listening", "switch to text"}


def _normalize_command(text: str) -> str:
    cleaned = re.sub(r"[.!?]", " ", text.casefold())
    return " ".join(cleaned.split())


def local_input_command(text: str, *, spoken: bool) -> str | None:
    """Return a local mode change for an exact phrase, or None to send it on."""
    folded = _normalize_command(text)
    if folded in _TYPED_EXIT:
        return "exit"
    if spoken:
        if folded in _SPOKEN_TEXT:
            return "text"
        return None
    if folded in _TYPED_VOICE:
        return "voice"
    if folded in _TYPED_TEXT:
        return "text"
    return None


def _mode_from_key(key: str) -> str | None:
    if not key:
        return None
    if key.casefold() == "t":
        return "text"
    if key.casefold() == "v":
        return "voice"
    return None


def _voice_hardware_failure(error: str) -> bool:
    """True when listening cannot work until the user fixes the microphone."""
    folded = error.casefold()
    return any(
        token in folded
        for token in (
            "speech_recognition is not installed",
            "no microphone",
            "microphone access failed",
            "pyaudio",
            "no default input",
        )
    )


def _ensure_pyaudio() -> None:
    """Make `import pyaudio` succeed for speech_recognition.

    Official PyAudio has no prebuilt Windows wheel for this Python.
    `pyaudiowpatch` supplies the same module API.
    """
    import importlib
    import sys

    loaded = sys.modules.get("pyaudio")
    if loaded is not None:
        return
    try:
        importlib.import_module("pyaudio")
    except ImportError:
        sys.modules["pyaudio"] = importlib.import_module("pyaudiowpatch")


def _load_speech_recognition() -> Any:
    try:
        _ensure_pyaudio()
    except ImportError:
        pass
    import speech_recognition as speech_module

    return speech_module


def _load_whisper() -> Any:
    import whisper

    return whisper


DEFAULT_NEURAL_VOICE = "en-US-AndrewNeural"


def _neural_voice() -> str:
    chosen = os.environ.get("EDGE_TTS_VOICE", "").strip()
    return chosen or DEFAULT_NEURAL_VOICE


def _run_coroutine(coro: Any) -> Any:
    """Run one coroutine from the synchronous chat loop."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    box: dict[str, Any] = {}

    def _in_thread() -> None:
        try:
            box["value"] = asyncio.run(coro)
        except BaseException as exc:
            box["error"] = exc

    worker = threading.Thread(target=_in_thread)
    worker.start()
    worker.join()
    if "error" in box:
        raise box["error"]
    return box.get("value")


def clean_text_for_tts(text: str, *, provider: str | None = None) -> str:
    """Strip markdown. Keep reaction tags only for a voice that performs them.

    edge-tts would speak "[laughs]" aloud. Laugh tags become a short laugh.
    A [pause] tag becomes an ellipsis. Ellipses, hyphens, and ALL CAPS stay.
    """
    # Remove markdown bold/italic/strikethrough/code markers (*, _, ~, `, #)
    text = re.sub(r'[*_#`~]', '', text)

    # Convert markdown links [Link Text](url) to just "Link Text"
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)

    if provider is None:
        provider = "elevenlabs" if tts_engine.keeps_audio_tags() else "edge"
    text = emotion.prepare_for_speech(text, provider=provider)

    # Clean up extra spacing left behind
    text = re.sub(r'\s+', ' ', text).strip()

    return text


async def _stream_neural_speech(text: str, voice: str, destination: Path) -> None:
    """Stream neural-voice audio into one mp3 file."""
    import edge_tts

    text = clean_text_for_tts(text, provider="edge")
    if not text:
        raise RuntimeError("The neural voice returned no audio.")
    rate, pitch = emotion.delivery()
    communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
    wrote = False
    with destination.open("wb") as handle:
        async for chunk in communicate.stream():
            if chunk.get("type") != "audio":
                continue
            data = chunk.get("data") or b""
            if data:
                handle.write(data)
                wrote = True
    if not wrote or destination.stat().st_size == 0:
        raise RuntimeError("The neural voice returned no audio.")


def _synthesize_neural_speech(text: str, destination: Path, voice: str) -> None:
    _run_coroutine(_stream_neural_speech(text, voice, destination))


def _synthesize_reply(text: str, destination: Path, voice: str) -> str:
    """Speak with the configured cloud voice, then the local neural voice.

    `voice` is the edge-tts name used only when every cloud engine fails.
    The returned label is the voice that produced the file.
    """
    if tts_engine.cloud_configured():
        try:
            return tts_engine.write_mp3(text, destination)
        except AssertionError:
            raise
        except Exception as exc:
            print(
                f"Voice: cloud speech failed ({exc}). Using the local neural voice.",
                flush=True,
            )
    _synthesize_neural_speech(text, destination, voice)
    return voice


_speech_lock = threading.Lock()
_speech_stop: threading.Event | None = None
_speech_uses_pygame = False
_speech_alias: str | None = None


def _arm_playback(
    stop_event: threading.Event,
    *,
    use_pygame: bool = False,
    alias: str | None = None,
) -> None:
    """Remember the reply that is playing so another thread can stop it."""
    global _speech_stop, _speech_uses_pygame, _speech_alias
    with _speech_lock:
        _speech_stop = stop_event
        if use_pygame:
            _speech_uses_pygame = True
        if alias:
            _speech_alias = alias


def _disarm_playback() -> None:
    global _speech_stop, _speech_uses_pygame, _speech_alias
    with _speech_lock:
        _speech_stop = None
        _speech_uses_pygame = False
        _speech_alias = None


def _stop_pygame_output() -> None:
    try:
        import pygame

        if pygame.mixer.get_init() and pygame.mixer.music.get_busy():
            pygame.mixer.music.stop()
            pygame.mixer.music.unload()
    except Exception:
        pass


def stop_agent_speech() -> None:
    """Cut off the reply that is playing now."""
    with _speech_lock:
        stop = _speech_stop
        alias = _speech_alias
        uses_pygame = _speech_uses_pygame
    if stop is not None:
        stop.set()
    if uses_pygame:
        _stop_pygame_output()
    if alias and os.name == "nt":
        try:
            ctypes.windll.winmm.mciSendStringW(f"stop {alias}", None, 0, None)
        except Exception:
            pass


def _release_playback() -> None:
    stop_agent_speech()
    _disarm_playback()


def preferred_output_device(names: list[str]) -> str | None:
    """Pick the media output. A Bluetooth stereo device beats its hands-free twin."""
    cleaned = [name.strip() for name in names if name and name.strip()]
    if not cleaned:
        return None

    def folded(name: str) -> str:
        return name.casefold()

    def hands_free(name: str) -> bool:
        text = folded(name)
        return "hands-free" in text or "ag audio" in text

    stereo = [name for name in cleaned if "stereo" in folded(name) and not hands_free(name)]
    if stereo:
        return stereo[0]
    speakers = [name for name in cleaned if "speaker" in folded(name) and not hands_free(name)]
    if speakers:
        return speakers[0]
    plain = [name for name in cleaned if not hands_free(name)]
    return plain[0] if plain else cleaned[0]


def playback_should_skip_barge(names: list[str], chosen: str | None) -> bool:
    """True when opening the mic would drop a Bluetooth headset off stereo playback."""
    if not chosen or "stereo" not in chosen.casefold():
        return False
    match = re.search(r"\((.+)\)", chosen)
    product = (match.group(1) if match else "").replace("Stereo", "").strip()
    if len(product) < 3:
        return False
    token = product.casefold()
    for name in names:
        text = name.casefold()
        if token in text and ("hands-free" in text or "ag audio" in text):
            return True
    return False


def _output_device_names() -> list[str]:
    if audio_output_override is not None:
        return list(audio_output_override)
    try:
        import pygame

        if not pygame.get_init():
            pygame.init()
        from pygame._sdl2 import audio as sdl_audio

        return [str(name) for name in sdl_audio.get_audio_device_names(False)]
    except Exception:
        return []


_barge_skip_announced = False
_speech_mixer_device = ""


def _reply_keeps_microphone_closed() -> bool:
    """Bluetooth stereo playback stays up only while the headset mic stays closed."""
    global _barge_skip_announced
    names = _output_device_names()
    chosen = preferred_output_device(names)
    if not playback_should_skip_barge(names, chosen):
        return False
    if not _barge_skip_announced:
        _barge_skip_announced = True
        print(
            "Playing on your headphones. The microphone stays closed during "
            "the reply so Bluetooth audio keeps playing. Press T to interrupt.",
            flush=True,
        )
    return True


def _ensure_speech_mixer() -> None:
    """Open playback on the stereo headphones when a headset is connected."""
    global _speech_mixer_device
    import pygame

    chosen = preferred_output_device(_output_device_names()) or ""
    if pygame.mixer.get_init() and _speech_mixer_device == chosen:
        pygame.mixer.music.set_volume(1.0)
        return
    if pygame.mixer.get_init():
        pygame.mixer.quit()
    try:
        if chosen:
            pygame.mixer.init(frequency=24000, devicename=chosen)
        else:
            pygame.mixer.init(frequency=24000)
        _speech_mixer_device = chosen
    except Exception:
        pygame.mixer.quit()
        pygame.mixer.init(frequency=24000)
        _speech_mixer_device = ""
    pygame.mixer.music.set_volume(1.0)


# A decoded length under this is not used to end a reply. A bad Sound
# decode of a few hundred milliseconds must not unload the voice at once.
_PLAYBACK_MIN_TRUST_MS = 400


def playback_should_continue(
    *,
    busy: bool,
    pos_ms: float,
    elapsed_ms: float,
    duration_ms: int,
    saw_busy: bool,
    quiet_ticks: int,
) -> str:
    """Decide one playback poll: 'play', 'wait', or 'done'.

    pygame's get_pos() can report the previous track, or a position past the
    file, on the first poll. That reading is not the end of the reply. The
    reply ends when wall-clock time has reached a trusted file length, or
    the device has stayed idle after startup when there is no trusted length.
    'done' unloads the device, so an early 'done' cuts the voice at the start.
    """
    trusted = duration_ms >= _PLAYBACK_MIN_TRUST_MS
    pos_in_file = trusted and 0 <= pos_ms <= duration_ms + 80
    playing = bool(busy) or pos_in_file
    if trusted and elapsed_ms + 40 >= duration_ms:
        near_end = pos_in_file and pos_ms >= duration_ms - 80
        if not busy or near_end or elapsed_ms >= duration_ms + 200:
            return "done"
        return "play"
    if playing:
        return "play"
    if not saw_busy and elapsed_ms < 1500:
        return "wait"
    if trusted and elapsed_ms + 120 < duration_ms:
        return "wait"
    if not trusted and elapsed_ms < 2000:
        return "wait"
    if quiet_ticks < 8:
        return "wait"
    return "done"


def _voice_file_ms(path: Path) -> int:
    """File length in milliseconds, or 0 when pygame cannot say."""
    try:
        import pygame

        sound = pygame.mixer.Sound(str(path))
        try:
            ms = int(float(sound.get_length()) * 1000)
        finally:
            del sound
        return ms if ms > 0 else 0
    except Exception:
        return 0


def _play_mp3_pygame(
    path: Path,
    stop_event: threading.Event | None = None,
) -> None:
    import pygame

    _ensure_speech_mixer()
    # Measure the file before music.load. A Sound created afterwards can
    # disturb the track that is about to play.
    file_ms = _voice_file_ms(path)
    envelope = speech_level.envelope_for_file(path)
    speech_level.start(envelope)
    envelope_ms = len(envelope) * speech_level.WINDOW_MS
    # Ignore a tiny decode and a wildly long one. Either would unload the
    # PC voice at the wrong time. Between two sane lengths, keep the longer
    # so the end of the reply is not clipped.
    trusted_lengths = [
        ms for ms in (file_ms, envelope_ms)
        if _PLAYBACK_MIN_TRUST_MS <= ms <= 180_000
    ]
    duration_ms = max(trusted_lengths) if trusted_lengths else 0
    if stop_event is not None:
        _arm_playback(stop_event, use_pygame=True)
    music = pygame.mixer.music
    music.set_volume(1.0)
    music.load(str(path))
    started = time.monotonic()
    saw_busy = False
    quiet_ticks = 0
    try:
        if stop_event is not None and stop_event.is_set():
            return
        music.play()
        clock = pygame.time.Clock()
        while True:
            if stop_event is not None and stop_event.is_set():
                music.stop()
                break
            try:
                pos = float(music.get_pos())
            except (TypeError, ValueError):
                pos = -1.0
            busy = bool(music.get_busy())
            elapsed = (time.monotonic() - started) * 1000
            # A position past the file is the previous mixer clock, not this reply.
            usable_pos = pos
            if duration_ms > 0 and not (0 <= pos <= duration_ms + 150):
                usable_pos = -1.0
            decision = playback_should_continue(
                busy=busy,
                pos_ms=pos,
                elapsed_ms=elapsed,
                duration_ms=duration_ms,
                saw_busy=saw_busy,
                quiet_ticks=quiet_ticks,
            )
            if busy or usable_pos >= 0:
                saw_busy = True
                quiet_ticks = 0
                speech_level.update(usable_pos if usable_pos >= 0 else elapsed)
            else:
                quiet_ticks += 1
            if decision == "done":
                # Never unload while wall-clock time is still inside a real file.
                if (
                    duration_ms >= _PLAYBACK_MIN_TRUST_MS
                    and elapsed + 80 < duration_ms
                    and (stop_event is None or not stop_event.is_set())
                ):
                    clock.tick(100)
                    continue
                # The file timeline is over. Leave a short drain, and do not
                # call stop(), which cuts off the end of the voice.
                if stop_event is None or not stop_event.is_set():
                    settle = time.monotonic()
                    while time.monotonic() - settle < 0.35 and music.get_busy():
                        if stop_event is not None and stop_event.is_set():
                            music.stop()
                            break
                        clock.tick(100)
                break
            clock.tick(100)
    finally:
        speech_level.stop()
        unload = getattr(music, "unload", None)
        if callable(unload):
            unload()


def _play_mp3_windows(
    path: Path,
    stop_event: threading.Event | None = None,
) -> None:
    """Play an mp3 with the Windows media API when pygame is unavailable."""
    alias = f"pedrovoice{threading.get_ident()}"
    winmm = ctypes.windll.winmm
    buffer = ctypes.create_unicode_buffer(256)

    def send(command: str) -> int:
        ctypes.memset(buffer, 0, ctypes.sizeof(buffer))
        return int(winmm.mciSendStringW(command, buffer, 255, None))

    opened = send(f'open "{path}" type mpegvideo alias {alias}')
    if opened != 0:
        detail = buffer.value.strip() or str(opened)
        raise RuntimeError(f"Could not open the voice audio ({detail}).")
    if stop_event is not None:
        _arm_playback(stop_event, alias=alias)
    try:
        started = send(f"play {alias}")
        if started != 0:
            detail = buffer.value.strip() or str(started)
            raise RuntimeError(f"Could not play the voice audio ({detail}).")
        origin = time.monotonic()
        while True:
            if stop_event is not None and stop_event.is_set():
                send(f"stop {alias}")
                break
            send(f"status {alias} mode")
            if buffer.value.strip().casefold() != "playing":
                break
            speech_level.note_cursor((time.monotonic() - origin) * 1000)
            time.sleep(0.02)
    finally:
        send(f"close {alias}")


def _play_mp3(
    path: Path,
    stop_event: threading.Event | None = None,
) -> None:
    try:
        _play_mp3_pygame(path, stop_event)
        return
    except ImportError:
        pygame_error = "pygame is not installed"
    except Exception as exc:
        pygame_error = str(exc)
        _stop_pygame_output()
        with _speech_lock:
            global _speech_uses_pygame
            _speech_uses_pygame = False
    if os.name == "nt":
        _play_mp3_windows(path, stop_event)
        return
    raise RuntimeError(pygame_error)


BARGE_RATE = 16_000
BARGE_FRAME_MS = 30
BARGE_WARMUP_FRAMES = 4
BARGE_HOT_FRAMES = 1
BARGE_TRAILING_FRAMES = 18
# Speaker onset on the PC is loud for about the first second. Treating that
# as the user talking stops the reply at the start. The phone does not use
# this microphone path.
BARGE_ONSET_GRACE_S = 1.0
# While the reply plays, speech must sit above the speaker bleed.
BARGE_ECHO_RATIO = 1.5
BARGE_RELEASE_RATIO = 1.25
BARGE_MIN_TRIGGER_RMS = 900.0
BARGE_MIN_RELEASE_RMS = 350.0
_BARGE_WARNED = False


def _pcm_rms(frame: bytes) -> float:
    count = len(frame) // 2
    if count <= 0:
        return 0.0
    samples = struct.unpack(f"<{count}h", frame[: count * 2])
    return (sum(sample * sample for sample in samples) / count) ** 0.5


class _BargeMeter:
    """Detect speech louder than the reply coming from the speakers."""

    def __init__(self) -> None:
        self.noise = 80.0
        self.speaking = False
        self.silence = 0
        self.warmup = BARGE_WARMUP_FRAMES
        self.preroll: deque[bytes] = deque(maxlen=10)
        self.speech = bytearray()

    def push(self, frame: bytes) -> str:
        """Return 'continue', 'speech' on the interrupting frame, or 'done'."""
        rms = _pcm_rms(frame)
        self.preroll.append(frame)
        if self.warmup > 0:
            self.noise = max(self.noise, rms)
            self.warmup -= 1
            return "continue"
        if not self.speaking:
            trigger = max(self.noise * BARGE_ECHO_RATIO, BARGE_MIN_TRIGGER_RMS)
            if rms >= trigger:
                self.speaking = True
                self.silence = 0
                self.speech.extend(b"".join(self.preroll))
                return "speech"
            if rms > self.noise:
                self.noise = self.noise * 0.9 + rms * 0.1
            else:
                self.noise = self.noise * 0.98 + rms * 0.02
            return "continue"
        self.speech.extend(frame)
        release = max(self.noise * BARGE_RELEASE_RATIO, BARGE_MIN_RELEASE_RMS)
        if rms < release:
            self.silence += 1
            if self.silence >= BARGE_TRAILING_FRAMES:
                return "done"
        else:
            self.silence = 0
        if len(self.speech) >= BARGE_RATE * 2 * 20:
            return "done"
        return "continue"


def _collect_barge_pcm(
    stop_playback: threading.Event,
    playback_done: threading.Event,
    frames: Any = None,
) -> bytes | None:
    """Read mic frames until the user finishes a barge-in phrase."""
    if frames is None:
        return _collect_barge_from_microphone(stop_playback, playback_done)
    meter = _BargeMeter()
    for frame in frames:
        if playback_done.is_set() and not meter.speaking:
            return None
        status = meter.push(frame)
        if status == "speech":
            stop_agent_speech()
        elif status == "done":
            stop_agent_speech()
            return bytes(meter.speech) or None
    if meter.speaking and meter.speech:
        stop_agent_speech()
        return bytes(meter.speech)
    return None


def barge_in_grace(elapsed_s: float) -> bool:
    """True while PC speaker onset must not be treated as the user talking."""
    return elapsed_s < BARGE_ONSET_GRACE_S


def _collect_barge_from_microphone(
    stop_playback: threading.Event,
    playback_done: threading.Event,
) -> bytes | None:
    try:
        _ensure_pyaudio()
        import pyaudio
    except ImportError as exc:
        raise OSError("PyAudio is not available, so interruption is disabled.") from exc
    audio = pyaudio.PyAudio()
    frame_count = int(BARGE_RATE * BARGE_FRAME_MS / 1000)
    try:
        stream = audio.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=BARGE_RATE,
            input=True,
            frames_per_buffer=frame_count,
        )
    except Exception:
        audio.terminate()
        raise
    meter = _BargeMeter()
    opened = time.monotonic()
    try:
        while True:
            if playback_done.is_set() and not meter.speaking:
                return None
            frame = stream.read(frame_count, exception_on_overflow=False)
            status = meter.push(frame)
            if barge_in_grace(time.monotonic() - opened):
                if status != "continue":
                    meter.noise = max(meter.noise, _pcm_rms(frame))
                    meter.speaking = False
                    meter.silence = 0
                    meter.speech.clear()
                continue
            if status == "speech":
                stop_agent_speech()
            elif status == "done":
                stop_agent_speech()
                return bytes(meter.speech) or None
    finally:
        stream.stop_stream()
        stream.close()
        audio.terminate()


def _warn_barge_once(exc: BaseException) -> None:
    global _BARGE_WARNED
    if _BARGE_WARNED:
        return
    _BARGE_WARNED = True
    print(f"Voice: interruption listener unavailable: {exc}", flush=True)


def _transcribe_audio(
    recognizer: Any,
    audio: Any,
    speech_module: Any,
    whisper_loader: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    try:
        text = recognizer.recognize_google(audio, language="en-US")
    except speech_module.UnknownValueError:
        return _err("Could not understand that. Try again.")
    except speech_module.RequestError as exc:
        text = _recognize_with_whisper(
            recognizer,
            audio,
            exc,
            whisper_loader or _load_whisper,
        )
        if isinstance(text, dict):
            return text
    except Exception as exc:
        return _err(f"Speech recognition failed: {exc}")
    if not isinstance(text, str):
        text = str(text)
    text = text.strip()
    if not text:
        return _err("The microphone did not produce any words.")
    return _ok(text, text=text)


def _transcribe_pcm(
    pcm: bytes,
    transcriber: Callable[[bytes], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if transcriber is not None:
        return transcriber(pcm)
    speech_module = _load_speech_recognition()
    recognizer = speech_module.Recognizer()
    audio = speech_module.AudioData(pcm, BARGE_RATE, 2)
    return _transcribe_audio(recognizer, audio, speech_module)


async def _barge_during_playback(
    path: Path,
    frames: Any = None,
    player: Callable[[threading.Event], None] | None = None,
    transcriber: Callable[[bytes], dict[str, Any]] | None = None,
    stop_event: threading.Event | None = None,
) -> dict[str, Any]:
    """Play audio while a microphone task listens. Speech stops playback."""
    stop_playback = stop_event or threading.Event()
    playback_done = threading.Event()
    pressed: dict[str, str | None] = {"key": None}
    watch_stop = threading.Event()
    _arm_playback(stop_playback, use_pygame=player is None)

    async def play() -> None:
        try:
            if player is not None:
                await asyncio.to_thread(player, stop_playback)
            else:
                await asyncio.to_thread(_play_mp3, path, stop_playback)
        finally:
            playback_done.set()

    async def listen() -> bytes | None:
        if frames is None and _reply_keeps_microphone_closed():
            return None
        return await asyncio.to_thread(
            _collect_barge_pcm,
            stop_playback,
            playback_done,
            frames,
        )

    watcher = None
    if frames is None:
        watcher = threading.Thread(
            target=_watch_mode_keys,
            args=(pressed, watch_stop),
            daemon=True,
        )
        watcher.start()
    try:
        play_result, pcm = await asyncio.gather(
            play(),
            listen(),
            return_exceptions=True,
        )
    finally:
        playback_done.set()
        # Stop only when the user interrupted. Stopping after a natural end
        # cuts the last part of the reply.
        if stop_playback.is_set():
            stop_agent_speech()
        _disarm_playback()
        watch_stop.set()
        if watcher is not None:
            watcher.join(timeout=0.3)

    if pressed.get("key") == "text":
        return {"interrupted": True, "command": "text"}
    if isinstance(pcm, BaseException):
        if frames is None:
            _warn_barge_once(pcm)
        pcm = None
    if isinstance(play_result, BaseException) and not pcm:
        raise play_result
    if not pcm:
        return {}
    print("Interrupted.", flush=True)
    heard = _transcribe_pcm(pcm, transcriber)
    if not heard.get("ok"):
        print(f"Voice: {heard.get('error')}", flush=True)
        return {"interrupted": True}
    transcript = str(heard.get("text") or "").strip()
    if not transcript:
        return {"interrupted": True}
    return {"interrupted": True, "transcript": transcript}


def _barge_followup(result: dict[str, Any]) -> dict[str, Any] | None:
    """Turn a cut-off reply into the next voice turn."""
    if not result.get("interrupted"):
        return None
    if result.get("command") in {"text", "exit"}:
        return {"ok": True, "command": result["command"]}
    transcript = str(result.get("transcript") or "").strip()
    if not transcript:
        return None
    command = local_input_command(transcript, spoken=True)
    if command:
        return {"ok": True, "command": command}
    return {"ok": True, "text": transcript}


def _pause_threshold() -> float:
    """voice.pause_threshold in rules.yaml; lower means faster turns."""
    try:
        value = float(rules.voice_setting("pause_threshold", LISTEN_PAUSE_THRESHOLD))
    except (TypeError, ValueError):
        return LISTEN_PAUSE_THRESHOLD
    return min(max(value, 0.5), 5.0)


_MIC_THRESHOLD: float | None = None
MIC_MIN_THRESHOLD = 120.0
MIC_MAX_THRESHOLD = 450.0


def listen_to_microphone(
    timeout: float = 8,
    phrase_time_limit: float | None = None,
    speech_module: Any = None,
    whisper_loader: Callable[[], Any] | None = None,
    announce: bool = True,
) -> dict[str, Any]:
    """Capture one phrase from the default microphone and turn it into text.

    Recording stays open while speech energy is present. There is no phrase
    length cap. After speech has started, pause_threshold seconds of quiet
    close the buffer, and transcription starts on the next line. `timeout`
    applies only while waiting for speech to start.

    Google's recognizer is used first. If that service cannot be reached and
    the optional Whisper package is installed, Whisper is tried once.
    """
    if speech_module is None:
        try:
            speech_module = _load_speech_recognition()
        except ImportError:
            return _err(
                "speech_recognition is not installed. "
                "From the project folder run: "
                ".venv\\Scripts\\pip install -r requirements.txt"
            )
    try:
        recognizer = speech_module.Recognizer()
        recognizer.pause_threshold = _pause_threshold()
        recognizer.non_speaking_duration = min(
            LISTEN_NON_SPEAKING_SECONDS,
            LISTEN_PAUSE_THRESHOLD,
        )
        try:
            microphone = speech_module.Microphone()
        except AttributeError as exc:
            return _err(
                "PyAudio is not available, so the microphone cannot be opened. "
                f"{exc}"
            )
        except OSError as exc:
            return _err(f"No microphone is available: {exc}")
        with microphone as source:
            # Calibrate once and keep it: re-calibrating on every click measured the
            # user's own voice when they started talking right away, which pushed the
            # threshold above their speech ("Didn't hear anything"). Capped so a quiet
            # laptop mic still triggers.
            global _MIC_THRESHOLD
            if _MIC_THRESHOLD is None:
                recognizer.adjust_for_ambient_noise(source, duration=0.5)
                _MIC_THRESHOLD = float(getattr(recognizer, "energy_threshold", 300) or 300)
            recognizer.energy_threshold = max(MIC_MIN_THRESHOLD, min(_MIC_THRESHOLD * 1.3, MIC_MAX_THRESHOLD))
            recognizer.dynamic_energy_threshold = True
            if announce:
                print("Listening...", flush=True)
            stream = source.stream
            original_read = stream.read

            def _metered_read(*args: Any, **kwargs: Any) -> bytes:
                data = original_read(*args, **kwargs)
                try:
                    speech_level.note_pcm(data)
                except Exception:
                    pass
                return data

            stream.read = _metered_read
            try:
                audio = recognizer.listen(
                    source,
                    timeout=timeout,
                    phrase_time_limit=phrase_time_limit,
                )
            finally:
                stream.read = original_read
                speech_level.clear_mic()
    except speech_module.WaitTimeoutError:
        return _err("No speech heard. Try again.")
    except AttributeError as exc:
        return _err(
            "PyAudio is not available, so the microphone cannot be opened. "
            f"{exc}"
        )
    except OSError as exc:
        return _err(f"Microphone access failed: {exc}")
    except Exception as exc:
        message = str(exc)
        if "pyaudio" in message.casefold():
            return _err(
                "PyAudio is not available, so the microphone cannot be opened. "
                f"{message}"
            )
        return _err(f"Microphone access failed: {exc}")

    return _transcribe_audio(
        recognizer,
        audio,
        speech_module,
        whisper_loader,
    )


def _recognize_with_whisper(
    recognizer: Any,
    audio: Any,
    google_error: BaseException,
    whisper_loader: Callable[[], Any],
) -> str | dict[str, Any]:
    whisper_fn = getattr(recognizer, "recognize_whisper", None)
    if whisper_fn is None:
        return _err(
            "Google speech recognition is unreachable "
            f"({google_error}). This install has no offline recognizer."
        )
    try:
        whisper_loader()
    except ImportError:
        return _err(
            "Google speech recognition is unreachable "
            f"({google_error}). Offline Whisper is not installed."
        )
    try:
        return str(whisper_fn(audio))
    except Exception as exc:
        return _err(
            "Google speech recognition is unreachable and the offline "
            f"fallback failed: {exc}"
        )


def _neural_voice_error(exc: BaseException) -> dict[str, Any]:
    """Map a speech failure to a result dict. The written reply stays on screen."""
    if isinstance(exc, ImportError):
        missing = str(exc).casefold()
        if "edge_tts" in missing or "edge-tts" in missing:
            return _err(
                "edge-tts is not installed, so the reply was printed only. "
                "From the project folder run: "
                ".venv\\Scripts\\pip install -r requirements.txt"
            )
        return _err(f"Audio playback is unavailable: {exc}")
    return _err(f"Neural voice failed: {exc}")


def speak_response(
    text: str,
    synthesizer: Callable[[str, Path, str], None] | None = None,
    player: Callable[[Path], None] | None = None,
    voice: str | None = None,
    barge_in: bool | None = None,
) -> dict[str, Any]:
    """Speak a reply with a neural voice. Failures stay in the return value.

    The mp3 is streamed to a temporary file and played. Real playback keeps
    the microphone open. Speech that is louder than the speaker stops the
    audio and returns that phrase as `transcript`.
    """
    spoken = " ".join((text or "").split())
    if not spoken:
        return _err("Nothing to say.")
    if len(spoken) > 2000:
        spoken = spoken[:2000].rsplit(" ", 1)[0]
    for_tts = clean_text_for_tts(spoken)
    edge_voice = (voice or _neural_voice()).strip() or DEFAULT_NEURAL_VOICE
    chosen = edge_voice if voice else (tts_engine.active_voice_label() or edge_voice)
    rate, pitch = emotion.delivery()
    mood = emotion.current()
    if not for_tts:
        return _ok(
            "Nothing to speak.",
            text=spoken,
            voice=chosen,
            emotion=mood,
            rate=rate,
            pitch=pitch,
        )
    handle = tempfile.NamedTemporaryFile(
        prefix="pedro-voice-",
        suffix=".mp3",
        delete=False,
    )
    path = Path(handle.name)
    handle.close()
    barge: dict[str, Any] = {}
    played_audio = False
    try:
        produced = (synthesizer or _synthesize_reply)(for_tts, path, edge_voice)
        if isinstance(produced, str) and produced.strip():
            chosen = produced.strip()
        if not path.is_file() or path.stat().st_size == 0:
            return _err("The neural voice returned no audio.")
        use_barge = player is None if barge_in is None else barge_in
        if use_barge:
            played_audio = True
            barge = _run_coroutine(_barge_during_playback(path))
        elif player is not None:
            player(path)
        else:
            played_audio = True
            _play_mp3(path)
    except KeyboardInterrupt:
        _release_playback()
        return _err("Speech was interrupted.")
    except AssertionError:
        raise
    except Exception as exc:
        return _neural_voice_error(exc)
    finally:
        if played_audio:
            _release_playback()
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
    payload = _ok(
        "Spoke the reply.",
        text=spoken,
        voice=chosen,
        emotion=mood,
        rate=rate,
        pitch=pitch,
    )
    if barge.get("interrupted"):
        payload["interrupted"] = True
        if barge.get("transcript"):
            payload["transcript"] = barge["transcript"]
        if barge.get("command"):
            payload["command"] = barge["command"]
    return payload


def _watch_mode_keys(
    pressed: dict[str, str | None],
    stop: threading.Event,
) -> None:
    """Record T or V pressed while the microphone is open."""
    if os.name != "nt":
        return
    try:
        import msvcrt
    except ImportError:
        return
    while not stop.is_set():
        try:
            ready = msvcrt.kbhit()
        except OSError:
            return
        if not ready:
            stop.wait(0.05)
            continue
        try:
            key = msvcrt.getwch()
        except OSError:
            return
        if key in {"\x00", "\xe0"}:
            if msvcrt.kbhit():
                try:
                    msvcrt.getwch()
                except OSError:
                    return
            continue
        mode = _mode_from_key(key)
        if mode:
            pressed["key"] = mode
            return


def _voice_turn() -> dict[str, Any]:
    """Listen once. A mode key pressed during capture wins over the transcript."""
    pressed: dict[str, str | None] = {"key": None}
    stop = threading.Event()
    watcher = threading.Thread(
        target=_watch_mode_keys,
        args=(pressed, stop),
        daemon=True,
    )
    watcher.start()
    try:
        heard = listen_to_microphone()
    except KeyboardInterrupt:
        return {"ok": True, "command": "text"}
    finally:
        stop.set()
        watcher.join(timeout=0.3)
    key = pressed.get("key")
    if key in {"text", "exit"}:
        return {"ok": True, "command": key}
    if not heard.get("ok"):
        return heard
    command = local_input_command(str(heard.get("text") or ""), spoken=True)
    if command:
        return {"ok": True, "command": command}
    return heard


def _discard_audio(path: Path | None) -> None:
    if path is None:
        return
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


class _SpeechPipeline:
    """Speak sentences in order. Playback of one overlaps synthesis of the next.

    The microphone opens when the first audio file is ready. A barge-in stops
    playback and sets `cancel`, which also stops the rest of the Gemini stream.
    An injected `player` is used by tests and does not open a microphone.
    """

    def __init__(
        self,
        synthesizer: Callable[[str, Path, str], None] | None = None,
        player: Callable[[Path], None] | None = None,
        voice: str | None = None,
    ) -> None:
        self.synthesizer = synthesizer or _synthesize_reply
        self.player = player
        self.edge_voice = (voice or _neural_voice()).strip() or DEFAULT_NEURAL_VOICE
        self.voice = (
            self.edge_voice
            if voice
            else (tts_engine.active_voice_label() or self.edge_voice)
        )
        self.cancel = threading.Event()
        self.audio: queue.Queue[Path | None] = queue.Queue()
        self.error: BaseException | None = None
        self.barge: dict[str, Any] = {}
        self._thread: threading.Thread | None = None
        self._started = False
        self._closed = False

    def submit(self, sentence: str) -> None:
        """Synthesize one sentence, then queue it. The caller can keep reading."""
        if self.cancel.is_set() or self.error is not None:
            return
        spoken = " ".join((sentence or "").split())
        if not spoken:
            return
        if len(spoken) > 2000:
            spoken = spoken[:2000].rsplit(" ", 1)[0]
        for_tts = clean_text_for_tts(spoken)
        if not for_tts:
            return
        handle = tempfile.NamedTemporaryFile(
            prefix="pedro-voice-",
            suffix=".mp3",
            delete=False,
        )
        path = Path(handle.name)
        handle.close()
        try:
            self.synthesizer(for_tts, path, self.edge_voice)
            if self.cancel.is_set():
                _discard_audio(path)
                return
            if not path.is_file() or path.stat().st_size == 0:
                _discard_audio(path)
                raise RuntimeError("The neural voice returned no audio.")
        except AssertionError:
            _discard_audio(path)
            raise
        except Exception as exc:
            _discard_audio(path)
            self.error = exc
            self.cancel.set()
            stop_agent_speech()
            return
        self._ensure_player()
        if self.cancel.is_set():
            _discard_audio(path)
            return
        self.audio.put(path)

    def _ensure_player(self) -> None:
        if self._started:
            return
        self._started = True
        if self.player is not None:
            self._thread = threading.Thread(
                target=self._play_queued,
                args=(self.cancel,),
                daemon=True,
            )
        else:
            self._thread = threading.Thread(target=self._play_with_barge, daemon=True)
        self._thread.start()

    def _play_with_barge(self) -> None:
        try:
            heard = _run_coroutine(
                _barge_during_playback(
                    Path("."),
                    player=self._play_queued,
                    stop_event=self.cancel,
                )
            )
            if isinstance(heard, dict):
                self.barge = heard
        except Exception as exc:
            if self.error is None:
                self.error = exc
            self.cancel.set()

    def _play_queued(self, stop_event: threading.Event) -> None:
        while not stop_event.is_set():
            try:
                item = self.audio.get(timeout=0.05)
            except queue.Empty:
                continue
            if item is None or stop_event.is_set():
                _discard_audio(item)
                break
            try:
                if self.player is not None:
                    self.player(item)
                else:
                    _play_mp3(item, stop_event)
            finally:
                _discard_audio(item)
        self._drain()

    def _drain(self) -> None:
        while True:
            try:
                extra = self.audio.get_nowait()
            except queue.Empty:
                return
            if extra is not None:
                _discard_audio(extra)

    def finish(self) -> dict[str, Any]:
        """Wait until the queued audio has played or the user interrupted it."""
        if not self._closed:
            self._closed = True
            if self._started and self._thread is not None:
                self.audio.put(None)
                self._thread.join(timeout=180)
            self._drain()
        if self.error is not None and not self.barge.get("interrupted"):
            failed = _neural_voice_error(self.error)
            failed["voice"] = self.voice
            return failed
        payload = _ok("Spoke the reply.", voice=self.voice)
        if self.barge.get("interrupted"):
            payload["interrupted"] = True
            if self.barge.get("transcript"):
                payload["transcript"] = self.barge["transcript"]
            if self.barge.get("command"):
                payload["command"] = self.barge["command"]
        return payload

    def abort(self) -> None:
        """Stop playback and drop sentences that have not been spoken."""
        self.cancel.set()
        if self._started and self._thread is not None and self._thread.is_alive():
            stop_agent_speech()
            self.audio.put(None)
            self._thread.join(timeout=5)
        self._closed = True
        self._drain()


def _speak_or_warn(text: str) -> None:
    result = speak_response(text)
    if not result.get("ok"):
        print(f"Voice: {result.get('error')}")


def run_voice_turn(user_text: str, history: list[Any], model: str) -> dict[str, Any]:
    """Stream one spoken turn. The first sentence plays while the rest arrives.

    A full reply from a non-streaming `run_agent` (tests, or a model that
    returns everything at once) is spoken after it returns.
    """
    pipeline = _SpeechPipeline()
    submitted = False
    printed = False

    def on_sentence(sentence: str) -> None:
        nonlocal submitted, printed
        if pipeline.cancel.is_set():
            return
        submitted = True
        prefix = "\n" if not printed else ""
        printed = True
        print(f"{prefix}{AGENT_NAME}> {sentence}", flush=True)
        pipeline.submit(sentence)

    try:
        answer = run_agent(
            user_text,
            history,
            model,
            voice=True,
            on_sentence=on_sentence,
            cancel_event=pipeline.cancel,
        )
    except Exception:
        pipeline.abort()
        raise
    if not submitted:
        pipeline.abort()
        if answer:
            print(f"\n{AGENT_NAME}> {answer}", flush=True)
        return speak_response(answer)
    if printed:
        print(flush=True)
    result = pipeline.finish()
    result["text"] = answer
    return result


async def _voice_session(history: list[Any], model: str) -> str:
    """Listen, stream tools, and speak until the user exits or returns to text.

    The first sentence starts playing while the rest of the reply is still
    arriving. A phrase spoken over the audio becomes the next turn.
    A long silence can speak one check-in. Returns 'exit', 'text', or 'mic'.
    """
    global voice_mode_active
    voice_mode_active = True
    voice_checkin.note_activity()
    queued: dict[str, Any] | None = None
    try:
        return await _voice_session_loop(history, model, queued)
    finally:
        voice_mode_active = False


async def _voice_session_loop(
    history: list[Any],
    model: str,
    queued: dict[str, Any] | None,
) -> str:
    while True:
        voice_checkin.maybe_check_in()
        if queued is None:
            try:
                heard = await asyncio.to_thread(_voice_turn)
            except KeyboardInterrupt:
                return "text"
        else:
            heard = queued
            queued = None
        if not heard.get("command") and heard.get("text"):
            spoken_command = local_input_command(
                str(heard.get("text") or ""),
                spoken=True,
            )
            if spoken_command:
                heard = {"ok": True, "command": spoken_command}
        if heard.get("command") == "exit":
            return "exit"
        if heard.get("command") == "text":
            return "text"
        if not heard.get("ok"):
            print(f"Voice: {heard.get('error')}", flush=True)
            if _voice_hardware_failure(str(heard.get("error") or "")):
                return "mic"
            continue
        text = str(heard.get("text") or "").strip()
        if not text:
            continue
        print(f"\nYou (voice)> {text}", flush=True)
        try:
            result = await asyncio.to_thread(run_voice_turn, text, history, model)
        except RuntimeError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            print(f"\n{AGENT_NAME}> {exc}", flush=True)
            try:
                result = await asyncio.to_thread(speak_response, str(exc))
            except KeyboardInterrupt:
                _release_playback()
                print("\nInterrupted.", flush=True)
                continue
        except KeyboardInterrupt:
            _release_playback()
            print("\nInterrupted.", flush=True)
            continue
        if not result.get("ok") and not result.get("interrupted"):
            print(f"Voice: {result.get('error')}", flush=True)
        queued = _barge_followup(result)


def stop_background_services() -> None:
    """Stop the wake listener, the scheduler, idle work, live video, and the phone bridge."""
    wake_word.stop_wake_word_listener()
    task_schedule.stop_background_scheduler()
    live_video.stop_live_feeds()
    remote_bridge.stop_remote_bridge()
    idle_tasks.stop_idle_tasks()
    clipboard_context.stop_clipboard_watcher()


def reset_background_state() -> None:
    """Drop queued wake commands, scheduled jobs, Blender jobs, and phone state."""
    stop_background_services()
    wake_word.drain_commands()
    task_schedule.clear_jobs()
    blender_task.reset_jobs()
    media_ffmpeg.reset_jobs()
    remote_bridge.reset_remote_bridge()


def _typed_key() -> str | None:
    """One console key, or None when nothing is waiting."""
    if os.name != "nt":
        return None
    try:
        import msvcrt
    except ImportError:
        return None
    if not msvcrt.kbhit():
        return None
    key = msvcrt.getwch()
    if key in {"\x00", "\xe0"}:
        if msvcrt.kbhit():
            msvcrt.getwch()
        return ""
    return key


def _chat_with_background(history: list[Any], model: str, voice: bool) -> int:
    """Chat while the wake listener and scheduler run on daemon threads.

    Typed text is read one key at a time so a wake command can arrive between
    keystrokes. The microphone is released before a spoken reply starts.
    """
    task_schedule.start_background_scheduler()
    wake_word.start_wake_word_listener()
    remote_bridge.start_remote_bridge()
    idle_tasks.start_idle_tasks()
    clipboard_context.start_clipboard_watcher()
    print(
        f'Wake word is "{wake_word.wake_phrase()}". '
        "Say it, wait for the chime, then speak.",
        flush=True,
    )
    typed_buffer: list[str] = []
    prompt_shown = False
    try:
        while True:
            if voice:
                wake_word.pause_wake_listener()
                prompt_shown = False
                try:
                    outcome = asyncio.run(_voice_session(history, model))
                except KeyboardInterrupt:
                    outcome = "text"
                finally:
                    wake_word.resume_wake_listener()
                if outcome == "exit":
                    return 0
                voice = False
                if outcome == "mic":
                    print("Switching to text mode.")
                else:
                    print("Text mode. Type a request.")
                continue
            woke = wake_word.poll_wake_command()
            if woke is not None and str(woke.get("text") or "").strip():
                if prompt_shown:
                    print()
                    prompt_shown = False
                source, text = "wake", str(woke.get("text") or "").strip()
            else:
                if not prompt_shown:
                    print("\nYou (text)> " + "".join(typed_buffer), end="", flush=True)
                    prompt_shown = True
                key = _typed_key()
                if key is None:
                    time.sleep(0.05)
                    continue
                if key == "":
                    continue
                if key == "\x03":
                    print()
                    return 0
                if key == "\x08":
                    if typed_buffer:
                        typed_buffer.pop()
                        print("\b \b", end="", flush=True)
                    continue
                if key not in {"\r", "\n"}:
                    typed_buffer.append(key)
                    print(key, end="", flush=True)
                    continue
                print()
                text = "".join(typed_buffer).strip()
                typed_buffer.clear()
                prompt_shown = False
                if not text:
                    continue
                source = "text"
            command = local_input_command(text, spoken=source == "wake")
            if command == "exit":
                return 0
            if command == "voice":
                voice = True
                print(
                    "Voice mode. Speak when you see Listening. "
                    "The reply starts as soon as the first sentence is ready. "
                    "Speak over a reply to interrupt it. Press T to type."
                )
                continue
            if command == "text":
                print("Text mode. Type a request.")
                continue
            if source == "wake":
                print(f"\nYou (voice)> {text}", flush=True)
                wake_word.pause_wake_listener()
                try:
                    result = run_voice_turn(text, history, model)
                except RuntimeError as exc:
                    print(f"Error: {exc}", file=sys.stderr)
                    continue
                except KeyboardInterrupt:
                    _release_playback()
                    print("\nInterrupted.", flush=True)
                    continue
                finally:
                    wake_word.resume_wake_listener()
                if not result.get("ok") and not result.get("interrupted"):
                    print(f"Voice: {result.get('error')}", flush=True)
                continue
            try:
                answer = run_agent(text, history, model)
            except RuntimeError as exc:
                print(f"Error: {exc}", file=sys.stderr)
                continue
            except KeyboardInterrupt:
                print("\nInterrupted.")
                continue
            print(f"\n{AGENT_NAME}> {answer}")
    finally:
        stop_background_services()


def check_tools() -> int:
    """Find the game without calling Gemini, so the drive setup can be verified."""
    result = locate_gta5_directory(rescan=True)
    print(json.dumps(result, indent=2))
    return 0 if result.get("ok") else 1


def _project_python() -> Path | None:
    """The checkout virtualenv, on Windows or another system."""
    names = (
        APP_DIR / ".venv" / "Scripts" / "python.exe",
        APP_DIR / ".venv" / "bin" / "python",
        APP_DIR / "venv" / "Scripts" / "python.exe",
        APP_DIR / "venv" / "bin" / "python",
    )
    for candidate in names:
        if candidate.is_file():
            return candidate
    return None


def _ensure_project_python() -> None:
    """Switch to the project venv when this Python cannot import google-genai."""
    if os.environ.get("GTA5_AGENT_NO_REEXEC") == "1":
        return
    try:
        from google import genai  # noqa: F401
    except ImportError:
        pass
    else:
        return
    venv_python = _project_python()
    if venv_python is None:
        return
    if Path(sys.executable).resolve() == venv_python.resolve():
        return
    os.environ["GTA5_AGENT_NO_REEXEC"] = "1"
    script = str(Path(__file__).resolve())
    os.execv(str(venv_python), [str(venv_python), script, *sys.argv[1:]])


def run_init() -> int:
    """Create folders, then report ffmpeg, OpenCV, drives, and missing settings."""
    created = agent_config.prepare_checkout(APP_DIR)
    print("Folders:")
    for folder in created["folders"]:
        print(f"  {folder}")
    ffmpeg = agent_config.ffmpeg_status()
    if ffmpeg:
        print(f"ffmpeg: {ffmpeg}")
    else:
        print("ffmpeg: not found. Install ffmpeg or set FFMPEG_EXECUTABLE.")
    try:
        import cv2

        print(f"OpenCV: {cv2.__version__}")
    except ImportError:
        print("OpenCV: not installed. From the project folder run: pip install -r requirements.txt")
    if os.name == "nt":
        print("Connected volumes:")
        try:
            volumes = _volumes()
        except Exception as exc:
            print(f"  Could not list volumes. {exc}")
        else:
            if not volumes:
                print("  No labeled volumes were readable.")
            for root, label in volumes:
                print(f"  {label or '(no label)'}  {root}")
    missing = agent_config.missing_settings()
    if missing:
        print(
            "Missing required settings: "
            + ", ".join(missing)
            + ". Copy .env.example to .env and add the values."
        )
        return 1
    print("Configuration looks complete.")
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Ped Bot, a local assistant for files, voice, and desktop tools."
    )
    parser.add_argument(
        "prompt",
        nargs="*",
        help="One instruction to run. Omit it for an interactive chat.",
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("GEMINI_MODEL", DEFAULT_MODEL),
        help=f"Gemini model id. Default: {DEFAULT_MODEL}.",
    )
    parser.add_argument(
        "--check-tools",
        action="store_true",
        help="Scan the configured external drive for GTA5.exe, then exit.",
    )
    parser.add_argument(
        "--init",
        action="store_true",
        help="Create logs, data, and temp folders and check the environment.",
    )
    parser.add_argument(
        "--app",
        action="store_true",
        help="Open the desktop chat window (local web UI) instead of the console.",
    )
    parser.add_argument(
        "--background",
        action="store_true",
        help="With --app: start hidden in the tray (used by Start with Windows).",
    )
    parser.add_argument(
        "--port", type=int, default=int(os.environ.get("PEDRO_APP_PORT", "8765")),
        help="Port for --app. Default 8765.",
    )
    parser.add_argument(
        "--voice",
        action="store_true",
        help="Start in voice mode. Speak over a reply to interrupt it.",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Gemini Live realtime voice (sees your screen, barge-in). Falls back to --voice.",
    )
    return parser


def _help_exit_code(argv: list[str] | None) -> int | None:
    """Return a process code for --help without reading .env."""
    requested = list(sys.argv[1:] if argv is None else argv)
    if not any(item in {"-h", "--help"} for item in requested):
        return None
    try:
        _parser().parse_args(requested)
    except SystemExit as exc:
        code = exc.code
        if code in (None, 0):
            return 0
        if isinstance(code, int):
            return code
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    _ensure_project_python()
    help_code = _help_exit_code(argv)
    if help_code is not None:
        return help_code
    load_env_file(APP_DIR / ".env")
    if Path.cwd().resolve() != APP_DIR.resolve():
        load_env_file(Path.cwd() / ".env")
    apply_storage_dir()
    parser = _parser()
    args = parser.parse_args(argv)

    if args.init:
        return run_init()
    if args.app:
        os.environ["PEDBOT_PORT"] = str(args.port)
        if getattr(args, "background", False):
            os.environ["PEDBOT_START_HIDDEN"] = "1"
        import chat_app

        try:
            import agent_config as _agent_config
            import storage_migrate

            moved = storage_migrate.run_at_start(APP_DIR, _agent_config.storage_dir())
            if moved.get("migrated"):
                print("[storage] " + str(moved.get("message")), flush=True)
                if moved.get("env_keys"):
                    load_env_file(APP_DIR / ".env")
        except Exception as exc:
            print(f"[storage] Could not bring over the older chat history: {exc}", flush=True)

        return chat_app.run(args.model, port=args.port)
    if args.check_tools:
        return check_tools()
    missing = agent_config.missing_settings()
    if missing:
        print(
            "Missing required settings: "
            + ", ".join(missing)
            + ". Copy .env.example to .env and add the values. "
            "Then run: python main.py --init",
            file=sys.stderr,
        )
        return 1

    history: list[Any] = []
    if args.prompt:
        text = " ".join(args.prompt).strip()
        try:
            if args.voice:
                result = run_voice_turn(text, history, args.model)
            else:
                answer = run_agent(text, history, args.model)
                print(f"{AGENT_NAME}> {answer}")
                result = {"ok": True}
        except RuntimeError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        if args.voice and not result.get("ok") and not result.get("interrupted"):
            print(f"Voice: {result.get('error')}")
        return 0

    voice = bool(args.voice)
    if args.live or (voice and rules.section("live", {"enabled": False}).get("enabled")):
        import live_voice

        live = live_voice.run()
        if not live.get("fallback"):
            return 0 if live.get("ok") else 1
        print(f"{live.get('error')} Using the normal voice mode.", flush=True)
        voice = True
    if tts_engine.cloud_configured():
        voice_line = f"Voice: {tts_engine.active_voice_label()}."
    else:
        voice_line = (
            f"Voice: {_neural_voice()}. "
            "Set ELEVENLABS_API_KEY in .env for the cloud voice."
        )
    print(
        f"{AGENT_NAME}. Type a request, or exit to quit.\n"
        "Type v and press Enter to speak. Press T while it listens, "
        'or say "text mode", to type again.\n'
        f"{voice_line}"
    )
    if voice:
        print(
            "Voice mode. Speak when you see Listening. "
            "The reply starts as soon as the first sentence is ready. "
            "Speak over a reply to interrupt it."
        )
    if background_services_enabled:
        return _chat_with_background(history, args.model, voice)
    while True:
        if voice:
            try:
                outcome = asyncio.run(_voice_session(history, args.model))
            except KeyboardInterrupt:
                outcome = "text"
            if outcome == "exit":
                return 0
            voice = False
            if outcome == "mic":
                print("Switching to text mode.")
            else:
                print("Text mode. Type a request.")
            continue
        try:
            text = input("\nYou (text)> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not text:
            continue
        command = local_input_command(text, spoken=False)
        if command == "exit":
            return 0
        if command == "voice":
            voice = True
            print(
                "Voice mode. Speak when you see Listening. "
                "The reply starts as soon as the first sentence is ready. "
                "Speak over a reply to interrupt it. Press T to type."
            )
            continue
        if command == "text":
            print("Text mode. Type a request.")
            continue
        try:
            answer = run_agent(text, history, args.model)
        except RuntimeError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            continue
        except KeyboardInterrupt:
            print("\nInterrupted.")
            continue
        print(f"\n{AGENT_NAME}> {answer}")


if __name__ == "__main__":
    raise SystemExit(main())
