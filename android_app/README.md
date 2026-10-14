# Pedro Agent – Android app

Thin native client (Java WebView) for the Pedro Agent remote server (`remote_access.py`, port 8766, via Cloudflare tunnel). The brain stays on the PC.

Build: `./build.sh` (needs Android SDK build-tools 35 + platform 35 and JDK 17). The signing keystore lives outside the repo (`~/.pedro-agent-release.jks`).
