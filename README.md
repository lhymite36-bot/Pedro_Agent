# Pedro_Agent

Pedro_Agent is a local command-line agent that uses the Gemini API with function calling.
You describe a setup step in plain text. Gemini chooses one of the local tools:
find the game on the external drive you configure, search for a mod, download a
zip, 7z, or rar, create folders, and copy mod files into that install.

The agent only writes inside the folder that contains `GTA5.exe`. It does not
run downloaded programs, replace `GTA5.exe` or any other `.exe`, or edit `.rpf`
archives. With no speech key, the spoken voice is the male neural voice
`en-US-AndrewNeural`. Set `ELEVENLABS_API_KEY` for the cloud male voice.

## Install

### 1. Prerequisites

- Python 3.10 or newer
- [FFmpeg](https://ffmpeg.org/) on your PATH, or `FFMPEG_EXECUTABLE` in `.env`
- OpenCV, installed by the package list below (`opencv-python`). The Windows wheel includes the libraries. On Linux, install the OpenGL packages your distribution documents for that wheel.
- Optional: [7-Zip](https://www.7-zip.org/) for `.rar` files, Git, and Blender for headless modeling

### 2. Clone the repository and create a virtual environment

```powershell
git clone https://github.com/lhymite36-bot/Pedro_Agent.git
cd Pedro_Agent
python -m venv .venv
```

Windows:

```powershell
.venv\Scripts\Activate.ps1
```

macOS and Linux:

```bash
python -m venv .venv
source .venv/bin/activate
```

`venv` works as well as `.venv`. If `google-genai` is missing, the program
restarts itself with the interpreter in `.venv` or `venv` (`Scripts` on
Windows, `bin` on other systems).

### 3. Install the Python packages

```powershell
pip install -r requirements.txt
```

`pyproject.toml` lists the same packages. Install from `requirements.txt`.

On Windows, install the Playwright browser once if you want page downloads:

```powershell
python -m playwright install chromium
```

### 4. Set up `.env`

```powershell
copy .env.example .env
```

macOS and Linux: `cp .env.example .env`

Open `.env` and set `GEMINI_API_KEY` to a key from
[Google AI Studio](https://aistudio.google.com/apikey). The key stays in `.env`
or in the environment. It is not written into the source.

Spoken replies use a deep male voice when `ELEVENLABS_API_KEY` is set.
`VOICE_ID` swaps that voice. Leave it empty for George
(`JBFqnCBsd6RMkjVDRZzb`). Adam is `pNInz6obpgDQGcFmaJgB`. Drew is
`29vD33N1CtxCmqQRPOHJ`. The model is `eleven_v3` unless `ELEVENLABS_MODEL`
is `eleven_multilingual_v2`. `eleven_v3` performs tags such as `[chuckles]`,
`[sighs]`, `[clears throat]`, and `[pause]`. Stability is 0.38, similarity
is 0.80, style is 0.20, and speaker boost is on. `CARTESIA_API_KEY` uses
Cartesia Sonic when the primary voice is missing or fails. `DEEPGRAM_API_KEY`
uses Deepgram Aura-2 Orion after that. With no speech key, replies stay on
edge-tts.

Point the agent at your own external drive with either the volume name or a
folder:

```env
EXTERNAL_DRIVE_LABEL=YourVolumeName
EXTERNAL_DRIVE_PATH=
```

`python main.py --init` lists Windows volume names on this PC so you can copy
one into `EXTERNAL_DRIVE_LABEL`. On other systems, set `EXTERNAL_DRIVE_PATH`
to the drive folder.

`STORAGE_DIR=./storage` is the example default for a new clone. Leave
`STORAGE_DIR` unset to keep using `workspace/`.

Telegram, Discord, Gmail, and live-video keys are optional. Leave them empty
to keep those features off. A missing `GEMINI_API_KEY` stops an online chat
with a message that names the setting, unless `PRIVACY_MODE=1` or
`LOCAL_LLM=1`.

### 5. Run the agent

Create `logs/`, `data/`, and `temp/`, then check ffmpeg, OpenCV, and `.env`:

```powershell
python main.py --init
```

Find the game without calling Gemini:

```powershell
python main.py --check-tools
```

Start the assistant:

```powershell
python main.py
```

`python gta5_agent.py` is the same program.

Type a request at `You (text)>`. Type `v` and press Enter to speak into the
default microphone. Press `T` while it is listening, or say `text mode`, to
type again. Say or type `exit` to quit. Start in voice mode with:

```powershell
python main.py --voice
```

A spoken request is transcribed and sent through the same Gemini tool loop as
typed text. Saying "Open Excel" calls `launch_application` the same way typing
it does. The microphone stays open while you are still talking. After you
stop, it waits 2 seconds of quiet, then sends the transcript straight to
Gemini. There is no maximum phrase length.

In voice mode the reply is spoken one sentence at a time. With
`ELEVENLABS_API_KEY` set, that voice is the male voice in `VOICE_ID`
(George when `VOICE_ID` is empty). Cartesia Sonic or Deepgram Aura-2 is
used when that key is set and the primary voice does not answer. With no
speech key, the voice is the male neural voice `en-US-AndrewNeural`
(`edge-tts`). The first finished sentence starts playing while Gemini is
still writing the rest. Each sentence is a temporary mp3 played with
`pygame`. The microphone stays open while that audio plays. Speaking over
the reply stops the audio, drops any sentences that have not played yet,
transcribes what you said, and sends it through the same tool loop. While
the reply plays, the microphone uses a higher volume threshold so the
speakers are less likely to interrupt it. Headphones, or a microphone close
to you, still make that more reliable. Press `T` during playback to stop
it and type instead.

Voice replies use the fast flash-lite model with a short output cap and
minimal thinking, so the first sentence arrives quickly. Typed requests
keep the full tool-calling budget.
`requirements.txt` installs `pygame-ce`, which provides `import pygame`.
The official `pygame` package has no prebuilt wheel for this Python.
Set `EDGE_TTS_VOICE` to another local neural voice, such as
`en-US-ChristopherNeural`, when no speech key is set. If speech or playback
fails, the written reply stays on screen.

Speech-to-text uses `speech_recognition` and the `pyaudio` module, then
Google's recognizer. If Google cannot be reached and the optional
`openai-whisper` package is already installed, that offline recognizer is
tried once. A missing microphone or missing audio package prints the reason
and returns to text mode. Speaker failures print the reason and leave the
written reply on screen.

`requirements.txt` installs `pyaudiowpatch`. The official `PyAudio` package has
no prebuilt wheel for this Python on Windows, so it would need Microsoft C++
build tools. On startup the assistant registers `pyaudiowpatch` as `pyaudio`,
which is the module `speech_recognition` imports.

One instruction, then exit:

```powershell
python main.py "Find my GTA V folder on the external drive and create a scripts folder"
```

## Example requests

Find the install:

```text
Install Simple Zombies Reborn
```

The assistant searches the web, downloads a direct `.zip`, `.7z`, or `.rar`
link when one is published on the page, extracts it, and copies the files into
the game folder. If the page has no direct file link, it looks in your
Downloads folder for a matching archive. RAR files need [7-Zip](https://www.7-zip.org/).

Find the install:

```text
Find the Grand Theft Auto V folder on the external drive.
```

Create folders the copy step will need:

```text
Create scripts, mods/update/x64/dlcpacks, and scripts/AddonPeds in the game folder.
```

Download, then install. Use a zip you trust. The download lands in
`workspace/downloads` and is not copied into the game until you say so:

```text
Download https://example.com/addon-ped.zip and show me what was extracted.
Do not copy it into the game yet.
```

```text
Install the extracted pack as an AddonPeds folder named horror_ped.
```

```text
Copy the extracted dlc pack into mods/update/x64/dlcpacks/horror_ped.
Do not overwrite files that are already there.
```

Script Hook layout the tools use:

| Files | Where they are copied |
| --- | --- |
| `ScriptHookV.dll`, `dinput8.dll`, other known loader DLLs, `*.asi` | Game folder, next to `GTA5.exe` |
| Other `*.dll`, `*.cs`, `*.vb` | `scripts\` |
| `*.ydd`, `*.yft`, `*.ytd`, and other model files | `mods\update\x64\dlcpacks\<pack>\` |
| Same model files when you ask for AddonPeds | `scripts\AddonPeds\<pack>\` |

If the zip already contains `mods`, `scripts`, or `dlcpacks`, `auto` layout
keeps that structure. Model files go under `mods\` so the original game files
stay in place.

GTA V streams models from `.rpf` archives. This assistant copies loose files
and whole folders. It does not pack them into an `.rpf` and it does not add a
`dlclist.xml` entry. When a pack is loose `.ydd`, `.yft`, or `.ytd` files,
import them with OpenIV before the game can use them. Converting a character
from another game into those formats has to be done before you point this
assistant at the folder.

Close the game before copying. If a file is locked, the tool returns that
error and Gemini will tell you what failed.

## Tools

- `locate_gta5_directory` finds the volume named by `EXTERNAL_DRIVE_LABEL`, or the folder in `EXTERNAL_DRIVE_PATH`, then finds `GTA5.exe`.
- `search_and_find_mod_download` searches the web and collects direct `.zip`, `.7z`, and `.rar` links.
- `download_mod_from_web` downloads one of those archives, extracts it, and deletes the archive.
- `scan_user_downloads_folder` checks your Downloads folder when a page has no direct file link.
- `download_and_extract_zip` downloads an http(s) zip with `requests`, rejects path-escape entries, extracts with `zipfile`, and deletes the zip.
- `create_directory` creates a folder under the game root.
- `copy_mod_files` copies a file or folder into a game-relative path.
- `integrate_custom_assets` maps a mod folder onto `scripts`, `scripts/AddonPeds`, the game root, or `mods/update/x64/dlcpacks`.
- `launch_application` opens an installed app such as Excel, Chrome, Notepad, Power BI, or SSMS.
- `open_website` opens an http or https address in the browser.
- `search_youtube` opens a YouTube search.
- `take_screenshot` captures this screen with `mss`, saves a JPEG in `workspace/screenshots/`, and sends that smaller image back to Gemini.
- `capture_webcam_image` opens the default webcam, saves one JPEG at `workspace/vision_capture.jpg`, sends that image to Gemini, and closes the camera. A single look does not stream.
- `click_element` jumps to a point on a 0-1000 grid and clicks. 0,0 is the top-left. 1000,1000 is the bottom-right.
- `press_keys` presses tab, enter, arrows, or a shortcut such as `ctrl+l`.
- `type_text` types into the focused window. It will not type a password or an API key.
- `scroll` scrolls up, down, left, or right.
- `navigate_browser` opens an http or https address in the default browser.
- `perform_actions` runs a list of clicks, typing, and keys in one turn, with no screenshot between them.
- `automate_excel_task` writes an `.xlsx` file from JSON instructions. A path can start with `external/`.
- `execute_sql_task` runs one statement on a local sqlite file or local SQL Server and can save the rows to CSV or Excel.
- `remember_fact` saves a name, preference, path, or instruction in `workspace/memory.sqlite`.
- `recall_memory` searches those saved facts.
- `get_clipboard_text` reads text you already copied, such as code or an error log.
- `create_task_plan` writes a numbered checklist before a request that has several different jobs.
- `complete_plan_step` marks one of those steps done.
- `revise_task_plan` marks a step blocked, says why the plan changed, and replaces the steps that follow.

Saved facts are added to Gemini's system prompt at the start of each turn.
The Windows account name is stored the first time memory is read. A successful
game search stores the GTA V folder. Saying "my name is ...", "I prefer to ...",
or "remember that ..." stores that sentence too. Passwords and API keys are
not saved. The database stays in `workspace/`, which is gitignored.

`take_screenshot`, `perform_actions`, `click_element`, `press_keys`,
`type_text`, `scroll`, and `navigate_browser` share the `computer_action`
engine in `mouse_controller.py`. Screenshots come from `mss` and are sent
as a JPEG at most 1280 pixels wide. The process sets Windows per-monitor
DPI awareness at startup so the screenshot and `pyautogui` use the same
physical pixels. A click coordinate is on a 0-1000 grid, then converted to
those pixels. The pointer jumps there and clicks. It does not glide, and
`pyautogui.PAUSE` is 0. A form or a menu should go out as one
`perform_actions` list, for example click, type, then press enter, instead
of a new screenshot after every key. `pynput` types characters that are not
ASCII. Move the pointer into a corner of the screen to stop an action.
`navigate_browser` opens the address in the default browser. It does not
log in or pass a download gate.

`browser_download_tool` opens one http or https page in Chromium. It can
fill a field, click, and save one file the page downloads into Downloads,
the Desktop, or the external drive. Put a site password in `BROWSER_PASSWORD` and
pass that name as `env`. The window stays visible unless you ask for
headless. If a check appears, finish it in the window. The tool does not
solve a CAPTCHA, skip a countdown, or bypass a download gate. A mod page
with no direct archive link is still refused. Install the browser once
with `python -m playwright install chromium` from the virtual environment.

`self_heal_execution` reruns a Python file the assistant wrote. On a traceback
it rewrites that file and tries again, up to 3 times. Headless Blender builds
do the same when a script fails. It does not retry a download, a delete, a
git push, or closing a program.

`mcp_router` calls a tool on a server you listed in `workspace/mcp_servers.json`
(or the file in `MCP_CONFIG`). The assistant passes the server name, the tool
name, and a JSON object. It does not pass a shell command. Example:

```json
{"servers":{"notes":{"command":"python","args":["-m","notes_server"]}}}
```

A request that says to keep something private, offline, or local only is
answered on this PC with Ollama at `127.0.0.1:11434`. Gemini stays the default.
Set `OLLAMA_MODEL` to pick the local model (`llama3.2` if you leave it empty).
Set `PRIVACY_MODE=1` or `LOCAL_LLM=1` to keep every turn local. The word
password by itself does not switch models. If Ollama is not running, the
assistant says so.

`audio_scribe_tool` records the microphone or system audio for 1 to 600
seconds, or reads an audio file you already have, and saves bullet notes in
Documents, the workspace, or the external drive. Transcription stays on this PC. Install
it only if you want that feature:
`python -m pip install openai-whisper` inside the virtual environment.

While the PC is idle, the assistant can index files, organize Downloads, and
run a health check. That work pauses as soon as you use the keyboard or mouse.
`delegate_subagent` can hand one task to a Blender, file, or system worker.
Closing a program, or connecting or disconnecting Wi-Fi or VPN, waits for a
clear yes. In voice mode it asks out loud and continues only after you say yes.

`read_clipboard_context` reads copied text or an image.
`clipboard_action_dispatcher` only suggests what to do with a traceback, a
link, a spreadsheet, code, or a picture. It does not open or run it.
`desktop_ui_automation` uses the existing click and key tools inside a known
app such as Excel, Power BI, or Chrome. `network_manager` can show the
network, test speed, or switch a profile you already configured. It does not
accept a command string. `webcam_vision_tool` is the same one-frame camera as
`capture_webcam_image`, for a desk, a document, or an object.
`system_diagnostics` reports CPU, memory, and large processes. It does not
close them.

`file_content_rag_search` answers from the local file index, including text
inside docx notes. It is SQLite FTS, not a cloud embedding model.
`job_scheduler` can run those safe tasks once, on a repeat, or every day at a
time such as 02:00. A backup copies text notes only, not the game and not a
program. `routine_macro_engine` saves up to 8 tool steps under a name such as
`3D-Export` and plays them back through the normal tools.

In voice mode, a long quiet stretch can speak one short check-in. If you
answer, it acknowledges you. If you stay quiet, it does not ask again until
you have been active and then idle again. `CHECKIN_IDLE_MINUTES` is clamped
between 15 and 30. `IDLE_TASK_SECONDS` defaults to 300.

Replies can include reaction tags such as `[laughs]`, `[giggles]`,
`[softly]`, and `[sighs]`. An ellipsis is a pause. A word in ALL CAPS is
emphasis, as in "That is HUGE!". The printed reply keeps the tags. The voice
is `en-US-AndrewNeural` until a speech key is set. That local voice would
read the brackets aloud, so they are removed before audio and a laugh tag
becomes a short laugh. `eleven_v3` keeps the tags when its key is set.

`capture_webcam_image` is separate from the screen tools. Say "look at me"
or "what am I holding?" and the assistant calls it once. On Windows the
camera opens through DirectShow, one frame is saved, and the camera closes
before Gemini describes the picture. If the camera is busy or blocked by
Windows privacy settings, the tool returns an error within a few seconds
instead of freezing. It is not opened at startup and it is not left running.
Ask again when you want another picture.

A live feed is a separate request. From the paired Telegram chat, `/pc_camera`,
"show me what your computer camera sees", "send live PC camera feed", or
"what is your computer seeing?" starts the PC webcam. `/phone_camera`,
"look at me through my phone", "start phone video feed", or "look at me live"
opens a phone page. That page uses the phone camera and posts JPEG frames
back to this PC. It does not open a WebRTC call. `/stop_camera` or
"stop the camera" ends the feed. A feed also stops on its own. The default
is 120 seconds and the maximum is 600.

If `TELEGRAM_RTMP_URL` and `TELEGRAM_STREAM_KEY` are both set, ffmpeg
publishes the PC webcam to that Telegram live stream. The model cannot
pass the address or the key. Leave both empty to use the local viewer
instead. The viewer listens only while a feed is on. `LIVE_VIDEO_PORT`
defaults to 8765. A Telegram Mini App button is sent only when
`LIVE_PUBLIC_URL` is an https address that reaches this PC. An http address
is sent as a link, and the reply says Mini Apps need https.

Say "fix the code I just copied" or "analyze this error log" and the assistant
calls `get_clipboard_text`. `pyperclip` is not used until that tool runs.
Copied text goes to Gemini for that turn and is not written into memory.

A request such as "Organize my external drive, pull sales data from SQL, and
update my tracking sheet" has to start with `create_task_plan`. The checklist
is printed with a `[plan]` prefix. The assistant then uses the normal tools
in order, marks each step complete, and calls `revise_task_plan` when a step
has to change. "Open Excel" or "what did I copy?" stays a single action and
does not need a plan. Voice mode already speaks each short update while the
tool loop continues.

Say "hey agent", wait for the short chime, then speak a request. The wake
listener runs beside the chat and leaves the microphone free while a voice
reply is playing. Set `WAKE_PHRASE` to use a different phrase.

`search_local_files` indexes file names and text notes on the Desktop,
Documents, Downloads, your user folder, and the external drive when that drive is
connected. "Where did I save that zombie mod backup from last month?" uses
those words and prefers files from that period. The index is
`workspace/file_index.sqlite`. It does not open or run anything it finds.

`shutdown_computer` shuts down this PC after a clear yes. In text mode the
next message has to be yes. In voice mode it asks "Are you sure you want to
execute shut down this PC?" and continues only after a spoken yes.

`kill_process` closes a program by name, such as `notepad`. Windows system
processes are refused. `focus_window` brings a window forward.
`manage_window_layout` can maximize, minimize, restore, or snap a window
left or right. `manage_windows_and_processes` is the same set of actions
in one call.

`schedule_background_task` runs `organize_downloads`, `reindex_files`, or
`remind` after a delay or on a repeat. "Check my downloads every hour"
sorts loose files into folders and leaves programs where they are. A request
to run a script or a program is refused. The scheduler thread keeps going
while the chat is open.

`run_blender_task` builds a mesh with Blender's `bpy` and runs
`blender -b -P` so no Blender window opens. The tool adds the export, then
checks that the `.obj`, `.fbx`, or `.blend` file exists and is not empty.
A path may start with `external/`. A result of `started` means the file is
not saved yet. If Blender fails immediately, the tool returns that error.
When a longer job finishes, a `[blender]` line reports the saved file or the
console error, and the same sentence is spoken if nothing else is playing.
`blender_job_status` answers "are you done?" without starting another build.
Set `BLENDER_EXECUTABLE` when `blender.exe` is not on PATH.

`build_local_program` writes an original program you asked for into a folder
under your user profile, the workspace, or the external drive. It does not install
Adobe After Effects or any other commercial product. A request for a simple
test editor becomes a small local program. Set `run` when you want that
program started with this agent's Python.

`search_files_by_time` answers "where is the Excel file I saved yesterday?"
and "videos from last week". With no folder named, it checks the Desktop,
Documents, Downloads, your user folder, and the external drive when that drive is
connected. "On the external drive" or "in my project folder" searches only that place.
It matches a calendar window, a file type such as Excel `.xlsx`, or both,
and it does not open those files. Word search still uses `search_local_files`.

`process_media` runs `ffmpeg` in the background for convert, audio
compress, or one frame per second. A path may start with `external/`.
`started` means the file is not ready yet. Install ffmpeg, or set
`FFMPEG_EXECUTABLE`. No filter text is accepted from the chat.

`git_manager` can init a folder, show status, commit, or push. Commit and
push only when you ask. `.env`, `.pem`, and `.key` files stay unstaged.
Push is a normal `git push` with no force and no remote URL. The agent
does not change your git name or email. git must already be installed.

Set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` to text the agent from
that one Telegram chat while you are away. Other chats are ignored.
`DISCORD_WEBHOOK_URL` receives status alerts only. `send_remote_update`
sends one status line. A finished Blender job sends the same alert when
either channel is configured. Text `/screenshot`, "screenshot",
"take a screenshot", "send a screenshot", "show me my screen", or
"what's on my screen" and the bridge sends a picture of the primary
monitor to that chat, then deletes the temporary file. The capture runs
beside the chat, so a Blender job keeps going.
A voice note in that chat is downloaded, transcribed, and run as a command.
The text answer is sent back in that chat. The bridge does not send a voice
message. Leave `TELEGRAM_VOICE_REACTION` empty for no reaction, or set it to
👍 or 🤖 to add one. Transcription uses a local whisper install when one is
already present, and otherwise Gemini. Whisper is not installed for you.
Restart the agent after you set those variables. Leave them empty to keep
the bridge off.

`gmail_send_message` sends one email through Gmail. An address such as
`john.doe@example.com` is used as given. A name such as John is looked up
in `workspace/contacts.json`. That file is a list of `{"name","email"}`
objects. If the address is invalid, the name is missing, or more than one
contact matches, nothing is sent and the assistant asks which address to
use. A missing subject is written from the first line of the message.
Set `GMAIL_ADDRESS` and `GMAIL_APP_PASSWORD` (an app password, not the
normal password). The password is not a tool argument and is not printed.

Every tool returns `{ "ok": true/false, ... }`. Failures are sent back to
Gemini as normal tool results so the next reply can explain them.

## What stays on your computer

`.env`, `workspace/`, `storage/`, `logs/`, `data/`, `temp/`, SQLite files, screenshots, and audio recordings are listed in `.gitignore`. A fresh clone has no conversation history and no file index. Search uses SQLite full-text search. Chroma is not used.

A path can start with `external/`, `drive/`, or the name in `EXTERNAL_DRIVE_LABEL`.

## Tests

```powershell
python -m unittest discover -s tests -t .
```
