#!/usr/bin/env bash
# Fetch the bundled Windows Python for the installer (full python.org layout from NuGet:
# includes venv + ensurepip and no ._pth file, unlike the "embeddable" zip).
set -euo pipefail
cd "$(dirname "$0")/.."
VER="${PY_VER:-3.12.7}"
tmp="$(mktemp -d)"
curl -fsSL -o "$tmp/py.nupkg" "https://www.nuget.org/api/v2/package/python/$VER"
(cd "$tmp" && unzip -q py.nupkg)
rm -rf python && cp -r "$tmp/tools" python
rm -f python/*._pth
curl -fsSL -o python/get-pip.py https://bootstrap.pypa.io/get-pip.py
rm -rf "$tmp"
echo "python/ ready ($VER)"
