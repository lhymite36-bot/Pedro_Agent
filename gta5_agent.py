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
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, quote_plus, unquote, urljoin, urlparse

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
AGENT_NAME = "Pedro_Agent"
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
_turn_request = ""
_task_plan: dict[str, Any] | None = None
_turn_is_local = False

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

SYSTEM_PROMPT = """You are Pedro_Agent, a local assistant on this Windows PC. You do multi-step tasks on this PC, build original programs the user asks for, and can set up single-player Grand Theft Auto V mods.

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
- "Open https://..." calls open_website. Only pass an http or https address.
- "Create a sales report and save it to external drive" calls automate_excel_task. file_path may start with "external/". task_instructions is JSON, not prose, for example {"sheet":"Sales","headers":["Item","Amount"],"rows":[["Hats",12]]}. Do not invent numbers the user did not give you. Ask for the rows or read them with execute_sql_task first.
- Database requests call execute_sql_task with a sqlite file path or a local SQL Server connection string. Leave allow_changes false for a SELECT. Set allow_changes true only after the user asks to insert, update, delete, or create. Pass output_path when the user wants a CSV or Excel file.

Desktop control on this PC:
- To look at a window or a browser, call take_screenshot first. The image comes back with the tool result as a small JPEG.
- click_element x and y are a 0-1000 grid over the whole screen. 0,0 is the top-left. 1000,1000 is the bottom-right. Do not send image pixels or physical pixels. The click goes straight to that point.
- When you already know the next clicks, typing, and keys, send them together in one perform_actions call. Do not take a screenshot between those steps. Example: [{"action":"click","x":500,"y":400},{"action":"type","text":"hello"},{"action":"press","key":"enter"}]. You may end that list with one screenshot.
- Several tool calls in the same reply also run immediately, one after another, with no pause.
- For a form or a menu, prefer press or a shortcut such as ctrl+l before a series of clicks. Type a password or key only when the user explicitly asks you to.
- scroll direction is up, down, left, or right.
- navigate_browser opens one http or https address in the default browser. It does not log in, solve a check, or pass a download gate.
- browser_download_tool opens a page in Chromium, fills fields, clicks, and can save one file into Downloads, the Desktop, or external drive. A password is the env name BROWSER_PASSWORD. Never put a password, cookie value, or API key in the tool call.
- Use it when the user asks to open a page they can access and download a file that page serves, such as a data report. Tell them the saved path from the tool result.
- If the tool says a person must finish a check, stop and tell them. Do not solve a CAPTCHA, skip a countdown, or bypass a download gate.
- Mod pages still follow the mod steps above. If there is no direct archive link, say which page was found and stop. Do not open that gate with browser_download_tool.
- Moving the pointer to a screen corner stops the current action.

Webcam, only when the user wants to be seen:
- "Look at me", "What am I holding?", or any request to see the person or the room calls capture_webcam_image once. The image comes back with that tool result.
- The camera opens for one frame and then closes. Do not call it on a timer, in a loop, or during ordinary chat. Do not call it again unless the user asks for another look.
- A live feed is a different request. Use stream_pc_camera or stream_phone_camera only when the user asks to watch a live camera.

Planning and execution:
- For a goal that needs several actions, plan first (create_task_plan), then keep calling tools until every step is done or truly blocked. Do not stop to ask between steps unless you need information only the user has.
- After each tool result, check it. If it failed, try a different approach before giving up.
- To click something you can see, prefer click_screen_target with a short description. It finds, clicks, and retries. Use find_on_screen to check that something is visible.

Multi-step work:
- If the request has several parts (organizing files and then updating a spreadsheet or SQL), call create_task_plan first with the goal and a numbered list of steps.
- Do the steps in order. After each step succeeds, call complete_plan_step. Say one short sentence about that step.
- If a step fails or the approach has to change, call revise_task_plan, tell the user what changed, and continue from the new steps.
- A single action, such as "Open Excel" or "what did I copy?", does not need a plan.

Clipboard:
- "Fix the code I just copied" or "analyze this error log" calls get_clipboard_text. Use the returned text. Do not ask the user to paste it again.
- Do not save clipboard text with remember_fact unless the user asks. Store a password, API key, or connection string only when the user explicitly asks.

Local files:
- "Where did I save ..." or "find my notes about ..." calls search_local_files. Answer with the paths it returns. Do not invent a path. The index covers the Desktop, Documents, Downloads, the user home folder, and the external drive when that drive is connected. It does not open or run those files.
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

Multi-step tasks (read a task, work in apps, make a document, send it):
- Call start_task first. If it refuses (graded test, exam, quiz), stop and offer to help the user study instead.
- If it suggests a routine, call get_task_routine and follow it. Then create_task_plan with the steps and keep it updated with complete_plan_step / revise_task_plan.
- Act with the normal tools (launch_any_app also opens Store apps, open_website, click/type tools). After every important step call verify_screen with what should now be visible; on NO, look (take_screenshot), fix and retry up to 3 times, then report the blocker honestly.
- Documents: capture_screenshot_file after each finished part (crop out notifications), then make_document. Never fake or reuse screenshots.
- Sending on WhatsApp: whatsapp_prepare (checks the contact name), show the user what will be sent, and only after their yes call whatsapp_send_now. Before clicking anything that sends, deletes, buys or submits a form, call confirm_before.
- When a new kind of task worked, offer to save it with save_task_routine.

Gmail:
- "Send an email to john.doe@example.com saying ..." calls gmail_send_message with that address. Do not look up a contact when the address is already there.
- "Send an email to John saying ..." calls gmail_send_message with the name. The tool uses people_contact_search on the saved contact list. Do not invent an address.
- Leave subject empty when the user does not give one. The tool writes a short subject from the message.
- If the result says the address is invalid, the name is missing, or more than one contact matches, ask which address to use. Do not send until the user picks one.
- Do not pass an app password, a token, or a webhook. Say the email was sent only when the tool result says it was sent.

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
- A frozen app calls kill_process with the program name, such as notepad. Warn the user before closing a Windows system process.
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
- Reverse engineering, decompilation, JavaScript/Electron unpacking, managed binary inspection, and native disassembly go through server "rea". Call list_tools on rea, then call the matching REA tool. Typical first tools: analyze_javascript_application for an ASAR or JS app, inspect_managed_artifact for a .NET assembly, open_binary for a native executable.
- Skip REA when the work is ordinary source in this project. Do not use REA on game copies, BattlEye, .rpf archives, cracks, or repacks.
- Routing notes live in skills/reverse-engineer-anything/SKILL.md. If no servers are configured, say so.

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
- "What is on my desk?", "Read this document", or a question about a physical object calls webcam_vision_tool once. It is the same one-frame camera as capture_webcam_image. The picture comes back with the tool result.

Live video:
- "Show me what your computer camera sees", "Send live PC camera feed", or "What is your computer seeing?" calls stream_pc_camera with action start. action look returns the latest PC frame without opening the camera a second time. action stop closes it.
- "Look at me through my phone", "Start phone video feed", or "Look at me live" calls stream_phone_camera with action start. The phone page uses the phone camera and posts JPEG frames to this PC. After the page is open, call stream_phone_camera with action look to see the latest frame. Do not call look in a loop.
- Do not pass an RTMP address, a stream key, a bot token, or a webhook. Those stay in the PC environment.
- If the result says Mini Apps need https, tell the user to set LIVE_PUBLIC_URL and to open viewer_url. Do not invent a public address.
- A feed stops by itself. The default is 120 seconds and the maximum is 600. "Stop the camera" or action stop ends it sooner.
- Do not start a live feed for "look at me" or "what am I holding?". Those stay one frame.

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

Wake word:
- A background listener waits for "hey agent", plays a chime, then records the request. You do not call a tool for the wake phrase. The text you receive is the request that followed it.

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


def _game_root() -> Path:
    saved = _load_saved_game()
    if not saved or not saved.get("path"):
        raise RuntimeError(
            "The game folder is not known yet. Call locate_gta5_directory first."
        )
    root = Path(saved["path"])
    if not _is_gta5_exe(root / "GTA5.exe"):
        raise RuntimeError(
            f"The saved game folder is no longer valid: {root}. "
            "Call locate_gta5_directory with rescan true."
        )
    return root


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
        target.mkdir(parents=True, exist_ok=True)
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


def _public_http_url(url: str) -> str:
    text = (url or "").strip()
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Only an http or https address can be opened.")
    return text


def open_website(url: str) -> dict[str, Any]:
    """Open an http or https address in the default browser."""
    try:
        target = _public_http_url(url)
        webbrowser.open(target)
        return _ok(f"Opened {target} in the browser.", url=target)
    except Exception as exc:
        return _err(f"open_website failed: {exc}")


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
        return _ok(
            (
                "Captured one webcam frame and closed the camera. "
                f"Image is {image_w}x{image_h}. "
                "Describe what is visible. "
                "Do not capture again unless the user asks for another look."
            ),
            path=str(path),
            image_width=image_w,
            image_height=image_h,
            _screenshot_bytes=data,
            _screenshot_mime=mime,
        )
    except AssertionError:
        raise
    except Exception as exc:
        return _err(f"capture_webcam_image failed: {exc}")


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
        if pointer_override is not None:
            pointer_override("click", details)
        else:
            mouse_controller.instant_click(
                _desktop(), pixel_x, pixel_y, click_count, button_name
            )
        return _ok(
            (
                f"Clicked {button_name} at pixel {pixel_x},{pixel_y} "
                f"from grid {shown_x},{shown_y}."
            ),
            **details,
        )
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


def _type_into_focused_window(text: str) -> None:
    if pointer_override is not None:
        pointer_override("type", {"text": text})
        return
    if text.isascii():
        _desktop().write(text, interval=0)
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
        if any(ord(char) < 32 or ord(char) == 127 for char in text):
            return _err("type_text accepts visible characters only.")
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


def scroll(direction: str, amount: Any = 3) -> dict[str, Any]:
    """Scroll the window under the pointer."""
    try:
        name = (direction or "").strip().casefold()
        if name not in {"up", "down", "left", "right"}:
            return _err("direction must be up, down, left, or right.")
        steps = _scroll_amount(amount)
        details = {"direction": name, "amount": steps}
        if pointer_override is not None:
            pointer_override("scroll", details)
        else:
            desktop = _desktop()
            signed = steps if name in {"up", "right"} else -steps
            if name in {"up", "down"}:
                desktop.scroll(signed)
            else:
                desktop.hscroll(signed)
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
    """Open an http or https address in the default browser on this PC."""
    try:
        target = _browser_http_url(url)
        if navigate_override is not None:
            navigate_override(target)
        else:
            webbrowser.open(target)
        return _ok(f"Opened {target} in the default browser.", url=target)
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
        return scroll(str(step.get("direction") or ""), step.get("amount", 3))
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
    for index, raw_step in enumerate(actions):
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
    "scroll": (scroll, ("direction", "amount")),
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
    global _turn_request, _task_plan, _turn_is_local
    _turn_request = user_text or ""
    _task_plan = None
    _turn_is_local = False
    emotion.note_user(_turn_request)
    confirm_action.note_user_text(_turn_request)
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
    if not _request_needs_plan(_turn_request):
        return None
    if _task_plan is not None:
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


plan_listener: Any = None  # chat_app sets this to stream the live checklist


def _log_plan(kind: str) -> None:
    plan = _task_plan
    if not plan:
        return
    if plan_listener is not None:
        try:
            plan_listener({"event": "plan", "kind": kind, "goal": plan["goal"], "steps": _public_steps()})
        except Exception:
            pass
    print(f"[plan] {kind}: {plan['goal']}", flush=True)
    marks = {"pending": " ", "done": "x", "blocked": "!"}
    for step in plan["steps"]:
        mark = marks.get(step["status"], " ")
        print(f"[plan] {step['number']}. [{mark}] {step['text']}", flush=True)


def _public_steps() -> list[dict[str, Any]]:
    plan = _task_plan or {}
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
    if _task_plan is None:
        return _err("No plan is active. Call create_task_plan first.")
    number = _plan_number(step)
    if number is None:
        return _err("step must be a plan number.")
    for item in _task_plan["steps"]:
        if item["number"] == number:
            return item
    return _err(f"Step {number} is not in the plan.")


def create_task_plan(goal: str, steps: Any) -> dict[str, Any]:
    """Store this turn's checklist. Later tools run only after this exists."""
    global _task_plan
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
    _task_plan = {
        "goal": goal_text,
        "steps": [
            {"number": index, "text": text, "status": "pending", "note": ""}
            for index, text in enumerate(parsed, 1)
        ],
    }
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
    if plan_listener is not None:
        try:
            plan_listener({"event": "plan", "kind": "step", "goal": (_task_plan or {}).get("goal", ""), "steps": _public_steps()})
        except Exception:
            pass
    pending = [
        entry["number"]
        for entry in (_task_plan or {"steps": []})["steps"]
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
    plan = _task_plan
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
    "stream_phone_camera": live_video.stream_phone_camera,
    "gmail_send_message": gmail_mail.gmail_send_message,
    "people_contact_search": gmail_mail.people_contact_search,
    "shutdown_computer": power_control.shutdown_computer,
    "find_on_screen": screen_vision.find_on_screen,
    "click_screen_target": screen_vision.click_screen_target,
    "write_text_file": file_tools.write_text_file,
    "delete_path": file_tools.delete_path,
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
        "description": "Open one http or https address in the default web browser.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "Full http or https address to open.",
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
            "close the camera immediately. Use this only when the user asks "
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
            "send image pixels. button is left, right, or middle. clicks is 1 or 2."
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
            "Scroll the window under the pointer. direction is up, down, left, "
            "or right. amount is a wheel step from 1 to 10."
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
                    "description": "Wheel steps from 1 to 10. Default 3.",
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
        "description": "Bring a visible window to the front by part of its title.",
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
            "and, for a call, the tool name plus a JSON object. Reverse "
            "engineering uses server rea. Do not pass a shell command."
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
    {
        "name": "delete_path",
        "description": "Delete a file or folder (Recycle Bin when available). The user's rules may require a yes first.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}, "recursive": {"type": "boolean"}}, "required": ["path"]},
    },
])


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
    if limit <= 0 or name in _NO_TIMEOUT_TOOLS:
        return function(**arguments)
    box: dict[str, Any] = {}

    def runner() -> None:
        try:
            box["result"] = function(**arguments)
        except BaseException as exc:  # re-raised on the caller thread
            box["error"] = exc

    worker = threading.Thread(target=runner, name=f"tool-{name}", daemon=True)
    worker.start()
    worker.join(limit)
    if worker.is_alive():
        raise ToolTimeout(f"timed out after {int(limit)}s (agent.tool_timeout_seconds in rules.yaml)")
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


def invoke_tool(name: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
    """Run one declared tool. Exceptions become error payloads for the model."""
    function = TOOLS.get(name)
    if function is None:
        return _err(f"Unknown tool: {name}")
    scope = getattr(_tool_scope, "allowed", None)
    if scope is not None and name not in scope:
        return _err(f"{name} is not one of this team member's tools.", blocked_by_scope=True)
    blocked = _plan_blocks(name)
    if blocked is not None:
        return blocked
    arguments = dict(arguments or {})
    rule_block = rules.tool_block_reason(name)
    if rule_block is not None:
        return _err(rule_block, blocked_by_rules=True)
    if confirm_action.is_sensitive(name, arguments):
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
    if result.get("ok"):
        _autosave_tool_memory(name, result)
    return result


def _redacted_tool_arguments(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Hide typed text in the console line. The tool still receives the text."""
    shown = dict(arguments)
    if name == "type_text" and "text" in shown:
        shown["text"] = f"[{len(str(shown['text']))} characters]"
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


def _execute_logged_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Print one tool call, run it, and print the result. Secrets are scrubbed."""
    shown = _redacted_tool_arguments(name, arguments)
    print(f"[tool] {_scrub(f'{name}({json.dumps(shown, default=str)})')}", flush=True)
    routine_macros.note_tool(name)
    result = invoke_tool(name, arguments)
    status = "ok" if result.get("ok") else "error"
    detail = _scrub(str(result.get("message") or result.get("error") or ""))
    print(f"[tool] {status}: {detail}", flush=True)
    return result


def _scrub(text: str) -> str:
    """Remove API keys, bot tokens, and the live-stream key from text."""
    if not text:
        return text
    secrets = [os.environ.get("GEMINI_API_KEY", "")]
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
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[redacted]")
    return text


def _is_daily_quota(exc: BaseException) -> bool:
    text = str(exc)
    return "RESOURCE_EXHAUSTED" in text or "429" in text


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
        "Another API key in the same Google project does not raise this limit. "
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

    def emit(ready: list[str]) -> None:
        if on_sentence is None:
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


def _result_image(result: dict[str, Any]) -> str | None:
    """A screenshot/webcam/image path in a tool result, for the chat preview."""
    path = str(result.get("path") or result.get("image_path") or "")
    if path.casefold().endswith((".png", ".jpg", ".jpeg")):
        return path
    return None


def model_candidates(first: str | None = None) -> list[str]:
    """First choice, then rules.yaml agent.models, then the built-in fallbacks."""
    order: list[str] = []
    for name in [first, *(rules.agent_setting("models", []) or []), *FALLBACK_MODELS]:
        name = str(name or "").strip()
        if name and name not in order:
            order.append(name)
    return order


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
) -> _StreamedTurn:
    def emit(sentence: str) -> None:
        spoke["yes"] = True
        if on_sentence is not None:
            on_sentence(sentence)

    stream = client.models.generate_content_stream(
        model=model,
        contents=history,
        config=config,
    )
    return _finish_voice_stream(stream, emit, cancel_event)


def run_agent(
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

    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY is not set. Add it to .env or the environment. "
            "See README.md."
        )
    _capture_user_memory(user_text)
    if genai_client_override is not None:
        client = genai_client_override(api_key)
    else:
        client = genai.Client(api_key=api_key)
    config, voice_plain = _model_configs(voice)
    active_config = config
    history.append(types.Content(role="user", parts=[types.Part.from_text(text=user_text)]))
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

    for _round in range(rounds):
        delays = (2, 5, 12)
        response = None
        quota_error: BaseException | None = None
        for index, active_model in enumerate(model_order):
            if index:
                print(
                    f"[quota] {model_order[index - 1]} is out of free requests. "
                    f"Switching to {active_model}.",
                    flush=True,
                )
                agent_log.event("model_switch", frm=model_order[index - 1], to=active_model)
                _emit("model_switch", model=active_model)
            for delay in (*delays, None):
                spoke = {"yes": False}
                try:
                    if stream_text:
                        response = _request_voice_model(
                            client,
                            active_model,
                            history,
                            active_config,
                            on_sentence=on_text,
                            cancel_event=cancel_event,
                            spoke=spoke,
                        )
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
                        response = client.models.generate_content(
                            model=active_model,
                            contents=history,
                            config=active_config,
                        )
                    break
                except Exception as exc:
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
                        quota_error = exc
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
                        time.sleep(delay)
                        continue
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
                break
        if response is None:
            if quota_error is not None:
                raise RuntimeError(_quota_message(quota_error)) from quota_error
            raise RuntimeError("Gemini did not return a response.")

        candidate = (response.candidates or [None])[0]
        if candidate is None or candidate.content is None:
            if voice and voice_lines:
                return "\n".join(voice_lines)
            return "Gemini returned no content for that request."
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
                return "\n".join(voice_lines) or "Gemini returned no text."
            text = _text_from(response)
            _emit("final", text=text)
            return text or "Gemini returned no text."

        preamble = voice_lines[-1] if voice and voice_lines else _text_from(response)
        if preamble and not voice:
            print(preamble, flush=True)
        response_parts = []
        for call in calls:
            name = call.name or ""
            arguments = dict(call.args or {})
            _emit("tool_start", name=name, arguments=_redacted_tool_arguments(name, arguments))
            result = _execute_logged_tool(name, arguments)
            _emit(
                "tool_end",
                name=name,
                ok=bool(result.get("ok")),
                detail=_scrub(str(result.get("message") or result.get("error") or ""))[:400],
                image=_result_image(result),
            )
            response_parts.append(
                _function_response(name, result, getattr(call, "id", None))
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


def _play_mp3_pygame(
    path: Path,
    stop_event: threading.Event | None = None,
) -> None:
    import pygame

    _ensure_speech_mixer()
    if stop_event is not None:
        _arm_playback(stop_event, use_pygame=True)
    music = pygame.mixer.music
    music.set_volume(1.0)
    music.load(str(path))
    speech_level.start(speech_level.envelope_for_file(path))
    try:
        if stop_event is not None and stop_event.is_set():
            return
        music.play()
        clock = pygame.time.Clock()
        while music.get_busy():
            if stop_event is not None and stop_event.is_set():
                break
            speech_level.update(music.get_pos())
            clock.tick(100)
    finally:
        speech_level.stop()
        music.stop()
        unload = getattr(music, "unload", None)
        if callable(unload):
            unload()


def _play_mp3_windows(
    path: Path,
    stop_event: threading.Event | None = None,
) -> None:
    """Play an mp3 with the Windows media API when pygame is unavailable."""
    alias = f"gta5voice{threading.get_ident()}"
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
        while True:
            if stop_event is not None and stop_event.is_set():
                send(f"stop {alias}")
                break
            send(f"status {alias} mode")
            if buffer.value.strip().casefold() != "playing":
                break
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
    try:
        while True:
            if playback_done.is_set() and not meter.speaking:
                return None
            frame = stream.read(frame_count, exception_on_overflow=False)
            status = meter.push(frame)
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
            recognizer.adjust_for_ambient_noise(source, duration=0.3)
            if announce:
                print("Listening...", flush=True)
            audio = recognizer.listen(
                source,
                timeout=timeout,
                phrase_time_limit=phrase_time_limit,
            )
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
        prefix="gta5-voice-",
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
            prefix="gta5-voice-",
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
    mcp_router.ensure_rea_server()
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
    rea = agent_config.rea_status()
    print(f"REA: {rea.get('message') or 'not checked.'}")
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
        description="Pedro_Agent, a local assistant for files, voice, and desktop tools."
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
        import chat_app

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
    if shutil.which("rea"):
        rea_line = "REA: rea is on PATH. Reverse engineering uses mcp_router server rea."
    elif shutil.which("npx"):
        rea_line = "REA: npx is available. Reverse engineering uses mcp_router server rea."
    else:
        rea_line = "REA: not found. Install with npm install --global rea-agents."
    print(
        f"{AGENT_NAME}. Type a request, or exit to quit.\n"
        "Type v and press Enter to speak. Press T while it listens, "
        'or say "text mode", to type again.\n'
        f"{voice_line}\n"
        f"{rea_line}"
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
