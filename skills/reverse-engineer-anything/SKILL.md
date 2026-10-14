---
name: reverse-engineer-anything
description: Reverse engineer native, managed, Electron/JavaScript, packaged, firmware, and browser targets with REA. Use shipped-artifact or requested runtime evidence to explain features, compare versions, decompile code, or guide a reconstruction. Skip REA for ordinary source-repository architecture analysis.
metadata:
  version: "39"
---

# REA

Pedro_Agent calls REA through `mcp_router` with server `rea`. Do not pass a
shell command. List tools first when the inventory is unknown.

Use REA when a claim depends on a shipped binary or package, decompilation,
passive application runtime evidence, or comparison with behavior not
established by available source. For ordinary analysis of a complete source
repository, use normal repository tools and do not run REA.

Refuse game copies, repacks, cracks, BattlEye, and `.rpf` archives.

## Connect only when needed

If REA tools are available, proceed directly to the target. Do not run
diagnostics before every investigation. Prefer an existing `rea` CLI. When
none is installed, `npx -y rea-agents@latest` can stand in.

## Route the target first

Choose the first tool from the target the user supplied.

- ASAR or extracted JavaScript/Electron tree: `analyze_javascript_application`.
- Archive/package member inventory (ZIP/APK/IPA/MSIX/AppX or DMG): `open_binary`
  with the supplied local path; use `inspect_artifact` when its graph helps.
- Android APK code: `inspect_android_package`, then focused Android tools.
- Managed PE/CLI assembly: `inspect_managed_artifact`.
- Firmware image: `inspect_firmware_regions` when advertised.
- Native executable, library, or analysis database: `open_binary`, then focused
  analysis tools; call `binary_overview` when metadata is useful.
- Explicit local WebAssembly artifact: `inspect_wasm_artifact`.
- User-owned browser page already open: `list_browser_targets`.
- User-owned Electron runtime already open: `list_electron_targets`.

If the user says only "my app" without a name or path, ask which app before
searching. Never choose an example app on the user's behalf.

Call `mcp_router` with action `list_tools` and server `rea` when the connected
inventory is unknown. Then `call` with the tool name and a JSON object.
`close_binary` when the investigation is complete.

## Work summary-first

Start with the default result and its evidence. For a large JavaScript
application, call `analyze_javascript_application` with `"detail": "summary"`.
Every conclusion must distinguish observations, inferences, and unknowns.
Never imply that static analysis observed execution.

Within the user's requested investigation, call available analysis tools
directly through `mcp_router`. Follow the host's access requirements. Do not
use REA to bypass a download gate, solve a CAPTCHA, or recover license keys.
