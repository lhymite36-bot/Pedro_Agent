<p align="center"><img src="docs/icon.png" width="120" alt="Pedro Agent icon"></p>

# Pedro_Agent

Your own AI assistant for Windows. Chat or talk to it, let it work on your PC, make custom bots and put them in group chats, and reach it from your phone. You only need a free Gemini API key.

<p align="center">
  <a href="https://github.com/lhymite36-bot/Pedro_Agent/releases/download/v1.2.0-windows/PedroAgent-Setup-1.2.0.exe"><img alt="Download for Windows" src="https://img.shields.io/badge/Download%20for%20Windows-PedroAgent--Setup--1.2.0.exe-5b6cff?style=for-the-badge&logo=windows"></a>
  &nbsp;
  <a href="https://github.com/lhymite36-bot/Pedro_Agent/releases/download/android-v1.2.0/PedroAgent-1.2.0.apk"><img alt="Android app" src="https://img.shields.io/badge/Android%20app-APK%201.2.0-3ad29f?style=for-the-badge&logo=android"></a>
</p>

![Group chat](docs/group-picture-chat.png)

## Set up in 3 steps

1. **Download and run** `PedroAgent-Setup-1.2.0.exe` (button above). No admin rights needed. If Windows SmartScreen warns you, click *More info → Run anyway* (the installer is not code-signed).
2. **Wait for setup.** It installs Python 3.12 if you don't have it, then the packages (a few minutes, needs internet). It adds *Pedro Agent* to your Desktop and Start menu.
3. **Open Pedro Agent and paste your free Gemini API key** (get one at https://aistudio.google.com/apikey). Telegram is optional. Keys are saved only in the `.env` file on your PC.

## What you get

- Chat and voice assistant that can work on your PC. Risky actions (delete, pay, send, shut down…) ask you first.
- **Multi-step tasks, end to end**: ask for things like "read the assignment in Chrome, do it in Power BI, make a PDF with screenshots and send it to a classmate on WhatsApp". It plans a live checklist, works in your apps (Store apps too), checks each step on screen with vision and retries, takes real screenshots, builds a PDF or Word file on your Desktop, and stages WhatsApp Web messages (it checks the contact name and **asks before sending**). Finished tasks can be saved as reusable routines. It refuses graded tests and exams. Works from chat, voice, the phone app and Telegram.
- **Custom bots** with their own role, colour, avatar, tools and scheduled tasks.
- **Groups**: put bots in a room with a purpose. Your message goes to the room; the coordinator answers and hands parts to members with @mentions, or you @mention a bot (or `@all`) directly.
- **Group pictures**: upload a photo from your PC or phone (crop with zoom/position) or pick a preset avatar and colour.
- **Delete anything you made**: trash icons on chats, bots and groups (hover on PC, always shown on phone), plus *Clear all chats* in Settings. Every delete asks first; Pedro_Agent itself can't be deleted. Deleting a bot removes it from its groups; deleting a group keeps its bots.
- **Phone app** (Android APK above) and a Live PC view. Off by default. Turn on `remote.enabled` in `rules.yaml` (needs the free `cloudflared`). The phone finds your PC's link automatically.

![Group editor](docs/group-picture-editor.png)

## Safe defaults

- `rules.yaml` decides what the agent may do. It ships with safe defaults: it writes only in your user folder and its workspace, and confirmations are on.
- Autopilot, Gemini Live voice and remote/phone access are **off** until you turn them on.
- Nothing personal is in this repo. Your chats, bots, groups, keys and tokens stay on your PC (`storage/`, `.env`).

## Update, repair, uninstall

- **Update:** run a newer installer over the old one. Your settings are kept.
- **Repair:** Start menu → Pedro Agent → *Repair Pedro Agent* (re-runs setup).
- **Uninstall:** Windows *Apps* list or Start menu → *Uninstall Pedro Agent*. It asks whether to keep your chats and keys.

## For developers

```powershell
git clone https://github.com/lhymite36-bot/Pedro_Agent.git
cd Pedro_Agent
powershell -ExecutionPolicy Bypass -File installer\setup.ps1
.venv\Scripts\python.exe main.py --app
```

Build the installer with NSIS: `makensis installer/PedroAgent.nsi` (output in `dist/`). Full feature notes: [docs/DETAILS.md](docs/DETAILS.md).
