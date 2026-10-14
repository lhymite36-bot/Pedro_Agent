# Pedro_Agent

Pedro_Agent is a local command-line agent that uses the Gemini API with function calling.
You describe a setup step in plain text. Gemini chooses one of the local tools:
find the game on the external drive you configure, search for a mod, download a
zip, 7z, or rar, create folders, and copy mod files into that install.

Every restriction comes from **you**, in `rules.yaml` (see "Your rules" below).
Out of the box the agent is permissive: it can write anywhere, write `.exe`
files, schedule scripts and programs, and has no size or step caps. It still
asks before deleting, paying, sending messages and shutting down, and the
`protect:` switches stop accidents such as deleting a drive root or the
agent's own code. Every old built-in limit is a switch under `limits:`.

**Not configurable, on purpose:** no malware or attacks on other people's
systems or accounts, no online-game cheats or anti-cheat tampering, no pirated
software (cracks, keygens, repacks), and no CAPTCHA or download-gate bypassing.
**Gemini's own safety filters** also apply to every reply. They run on
Google's side and nothing in this project can switch them off, so a request
can still be declined by the model even when your rules allow it. With no speech key, the spoken voice is the male neural voice
`en-US-AndrewNeural`. Set `ELEVENLABS_API_KEY` for the cloud male voice.

## What's new (Stage 2)

Everything below follows `rules.yaml` (blocked tools, paths, confirm categories). New sections: `team`, `skills`, `code`, `live`, `upgrade`, `remote`.

### Custom bots (sidebar → Bots → +)
Create, edit and delete as many bots as you like. Each has a name, colour, avatar style, role/system prompt, optional model,
allowed tools (none ticked = all tools your rules allow), an optional per-bot rules override (JSON merged over rules.yaml for that
bot only) and tasks: one-off (▶ runs it now) or scheduled (every N minutes / daily at HH:MM). Each bot has its own chat thread.
Bots are saved as `storage/bots/<id>.json`. The main agent can hand work to a bot ("ask Inbox Helper to …" → `ask_bot`).
Scheduled tasks run while the chat app is open and are **unattended**: anything in your confirm categories waits for your "yes"
(in the chat app or Telegram) instead of running.

### Agent team (`run_team`)
"Use the team to …": a planner splits the goal into sub-tasks for coder, browser, files and research agents that run in parallel
threads (each limited to its own tools), then a reviewer checks the result and may send one sub-task back. `team:` in rules.yaml.

### Learn by demonstration
"Record a skill called export-invoice" → do the task → "stop recording". Mouse, keys and screenshots are turned into
`skills/export-invoice/SKILL.md` (Gemini vision summary) and `actions.json`. "Replay skill export-invoice" plays it back; **Esc stops**.
Typed text stays in actions.json on your PC and is not sent to Gemini (`protect.skill_typing_stays_local`).

### Code engineer (`code_engineer`)
"Build a CSV cleaner in ~/projects/csvtool with tests": writes files, runs the tests, feeds failures back, repeats up to
`code.max_iterations`, and commits with git when tests pass (if the folder is a git repo; secret files stay unstaged).

### Autopilot (`autopilot.yaml`)
Watch Gmail (IMAP with your app password, read-only), Telegram messages, a folder, or a web page, and run a prompt (or a bot)
when something new happens. Set `enabled: true`, then restart the chat app or say "start autopilot". The first check only records
what is already there. Risky actions wait for your yes; results go to Telegram when `notify: true`.

### Gemini Live voice (optional)
`python main.py --live` (or `live.enabled: true` to make `--voice` try it first): realtime talk, the model sees a screen frame
every second, talking over it interrupts (barge-in), and it can call the agent's tools. Use headphones. If Live is unavailable
(no key, no model access, no mic library) it falls back to the normal voice mode automatically.

### Self-upgrade (`self_upgrade`)
"What keeps failing?" reads `storage/logs/agent.jsonl`. "Propose a fix for X" asks Gemini for a corrected module, tests it in a
temporary copy of the project, and saves the diff in `storage/upgrades/<id>/`. It is only applied after you say yes
(confirm category `self_upgrade`), the old file is backed up, and "roll back upgrade <id>" restores it.

### Avatar mouth sync
The avatar's mouth now follows the real loudness of the spoken reply (edge-tts through pygame; Gemini Live audio too).
The Windows MCI fallback player has no level data, so there the mouth uses a smooth simulated motion.

### Phone app + Live PC (remote access) — OFF by default
A phone layout (bottom nav: Chats, Bots, Live, Settings) that installs on Android as an app (PWA), plus a **Live PC** page that
shows your screen (MJPEG stream or JPEG frames, 0.5–5 fps, adjustable) and a feed of what the agent is doing.

Security:
* Off unless `remote.enabled: true`. It runs on its own port (8766, bound to 127.0.0.1); the normal app on 8765 refuses any
  host name other than localhost, so it can never be exposed by mistake.
* Every page, API call and video frame needs a sign-in cookie (HttpOnly, SameSite=Strict, Secure over https, 12 h).
  You sign in with the long random token in `storage/remote_token.txt` (created on first start) or, optionally, a PIN of 6–12
  digits in `.env` as `REMOTE_PIN=`. 5 wrong tries lock an address out for 5 minutes; 30 in total block sign-in until restart.
* View-only by default. Clicking/typing from the phone needs `remote.allow_control: true` **and** a "yes" on the phone
  ("Allow control", confirm category `remote_control`), which opens control for `control_minutes`. Rules can't be edited remotely.
* To start over with a new token, delete `storage/remote_token.txt`.

Setup (free):
1. In rules.yaml set `remote: enabled: true`. Start the app: `python main.py --app`. On the PC, `http://127.0.0.1:8766` shows the sign-in page.
2. Reach it from anywhere — pick one:
   * **Cloudflare quick tunnel** (no account): `winget install Cloudflare.cloudflared`, set `remote: tunnel: cloudflared`.
     Each start gets a new `https://….trycloudflare.com` address. It is printed in the console and sent to your Telegram
     (sign-in link with the token after `#`, so it is never sent to the server or the tunnel logs).
   * **Tailscale** (private network, free personal plan): install Tailscale on the PC and phone, sign in to both, then on the PC
     run `tailscale serve --bg 8766`. Put the `https://<pc>.<tailnet>.ts.net` address in `remote: public_url:` to get it on Telegram.
3. On the phone open the link in Chrome, sign in, then menu → **Add to Home screen** / Install app.
Don't share the link or token; anyone with them can see your screen.

## What's new (v2 upgrade)

- **Chat app**: `python main.py --app` opens a chat window (local web page on
  127.0.0.1:8765, or its own window when `pywebview` is installed) with
  streaming replies, live tool activity, saved chat history, a Stop button
  that also cuts off speech, a "Speak replies" switch, model picker, and a
  Settings page that edits `rules.yaml`.
- **Your rules** (`rules.yaml`) replace the hardcoded limits. See below.
- **Smarter loop**: up to `agent.max_tool_rounds` steps per request (default
  30, was 16), a plan-then-execute prompt, and automatic fallback through the
  free Gemini models listed in `agent.models` when one hits its quota.
- **Vision clicking**: `click_screen_target("the blue Sign in button")`
  screenshots, finds the element with Gemini vision, optionally focuses a
  window first, clicks, and retries. `find_on_screen` checks visibility.
- **File tools**: `write_text_file` and `delete_path` (Recycle Bin when
  `send2trash` is installed; asks first by default).
- **Reliability**: every tool runs with a timeout (`agent.tool_timeout_seconds`)
  and is logged as JSON lines to `workspace/logs/agent.jsonl` with timings.
- **Voice**: shorter end-of-turn pause (`voice.pause_threshold`, default 1.2 s,
  was 2 s) for faster turns. Barge-in and the wake word are unchanged.

### Voice in the chat app and faster clicking (v2.1)

- **🎤 Talk** (or hold Space when not typing) records one phrase with the same
  free local recogniser as console voice mode. **Hands-free** listens again
  after every reply. **Wake word** runs the background listener for the wake
  phrase (`WAKE_PHRASE`, default "hey agent").
- **Auto-speak replies** speaks each sentence as it streams. Stop, or just
  talking over it, cuts it off; what you said is sent as the next message.
  The default comes from `voice.auto_speak` in rules.yaml.
- **Faster screen control**: buttons are looked up by name with Windows UI
  Automation first (install `uiautomation` or `pywinauto`), then vision.
  Screenshots for vision are shrunk to 1024 px JPEG and sent to the fastest
  flash-lite model with thinking off, and the Gemini client is reused between
  calls. A click is checked by a quick pixel diff instead of a second vision
  call. Window handles are cached, pyautogui has no built-in pauses, and every
  wait is set in the `speed:` section of rules.yaml.

## Your rules (rules.yaml)

Edit `rules.yaml` next to `main.py`, or use Settings in the chat app. Changes
apply on the next tool call. Set `RULES_FILE` to use a different file;
`rules.json` with the same keys also works.

```yaml
paths:
  allowed: ["~", "{workspace}", "{external}"]   # "*" = everywhere
  blocked: ["?:/Windows", "?:/Program Files", "?:/Program Files (x86)"]
files:
  allow_exe_writes: false
  blocked_extensions: []
tools:
  allowed: []        # empty = all tools
  blocked: []        # e.g. ["kill_process"]
confirm:
  enabled: true      # false = never ask
  categories: [delete, payment, send_message, power, kill_process, network]
  extra_tools: []
agent:
  models: [gemini-3.5-flash-lite, gemini-3.1-flash-lite, gemini-2.5-flash, gemini-2.5-flash-lite]
  max_tool_rounds: 30
  tool_timeout_seconds: 300
voice:
  pause_threshold: 1.2
```

See the `limits:` and `protect:` sections in `rules.yaml` for every former
built-in limit, each documented on its line and OFF by default (protect: ON).

Blocked always wins over allowed. Patterns accept `*` and `?` wildcards.
When the agent asks "are you sure?", reply `yes` (text) or say yes (voice).

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
name, and a JSON object. It does not pass a shell command. Reverse engineering
uses the `rea` server. Install the CLI with `npm install --global rea-agents`,
then `python main.py --init` writes that server into the config if it is
missing. `python main.py --init` also prints `rea --help`. Routing notes are
in `skills/reverse-engineer-anything/SKILL.md`. Example:

```json
{"servers":{"rea":{"command":"npx","args":["-y","rea-agents@latest","--mcp"]}}}
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
