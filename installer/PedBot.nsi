; Ped Bot (formerly Pedro Agent) Windows installer (per-user, no admin needed). Build: makensis installer/PedBot.nsi
; Upgrades in place: same folder, same uninstall entry, old "Pedro Agent" shortcuts removed, so only one app remains.
Unicode true
!define APP "Ped Bot"
!define OLDAPP "Pedro Agent"
!define VER "1.5.3"
!include "MUI2.nsh"
Name "${APP}"
BrandingText "${APP} ${VER} - open source, github.com/lhymite36-bot/Pedro_Agent"
VIProductVersion "${VER}.0"
VIAddVersionKey "ProductName" "${APP}"
VIAddVersionKey "ProductVersion" "${VER}"
VIAddVersionKey "FileVersion" "${VER}"
VIAddVersionKey "FileDescription" "${APP} installer (per-user, open source)"
VIAddVersionKey "CompanyName" "Ped Bot open-source project (github.com/lhymite36-bot/Pedro_Agent)"
VIAddVersionKey "Comments" "Open-source desktop AI assistant. Source code: https://github.com/lhymite36-bot/Pedro_Agent"
VIAddVersionKey "InternalName" "PedBot-Setup"
VIAddVersionKey "LegalCopyright" "Ped Bot project - github.com/lhymite36-bot/Pedro_Agent"
VIAddVersionKey "OriginalFilename" "PedBot-Setup-${VER}.exe"
OutFile "..\dist\PedBot-Setup-${VER}.exe"
InstallDir "$LOCALAPPDATA\PedroAgent"
RequestExecutionLevel user
SetCompressor /SOLID lzma
!define MUI_ICON "pedbot.ico"
!define MUI_UNICON "pedbot.ico"
Icon "pedbot.ico"
!define MUI_FINISHPAGE_RUN
!define MUI_FINISHPAGE_RUN_FUNCTION StartApp
!define MUI_FINISHPAGE_RUN_TEXT "Start Ped Bot now"
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"

Function .onInit
  ; the old or new app must be closed so its files can be replaced (shared single-instance lock)
  retry:
  System::Call 'kernel32::OpenMutexW(i 0x00100000, i 0, w "Local\PedroAgentSingleInstance") p .r0'
  IntCmp $0 0 free
  System::Call 'kernel32::CloseHandle(p r0)'
  MessageBox MB_RETRYCANCEL|MB_ICONINFORMATION "Pedro Agent / Ped Bot is running. Close it (or press Pause all, then close the window) and press Retry." IDRETRY retry
  Abort
  free:
FunctionEnd

Function StartApp
  SetOutPath "$INSTDIR"
  Exec '"$INSTDIR\.venv\Scripts\pythonw.exe" "$INSTDIR\main.py" --app'
FunctionEnd

Section "Install"
  SetOutPath "$INSTDIR"
  File /r /x .git /x .github /x dist /x tests /x android_app /x "*.pyc" /x __pycache__ /x rules.yaml /x .env /x storage /x workspace /x docs /x python "..\*.*"
  ; keep the user's own settings on upgrade
  SetOutPath "$INSTDIR\python"
  File /r "..\python\*.*"
  SetOutPath "$INSTDIR"
  DetailPrint "Setting up Python and packages in a visible window (this can take a few minutes)..."
  ; plain batch file in a visible window (no PowerShell, nothing hidden)
  ExecWait '"$SYSDIR\cmd.exe" /c ""$INSTDIR\setup.bat" /auto"' $0
  Push $0
  Pop $0
  StrCmp $0 "0" +2 0
  MessageBox MB_ICONEXCLAMATION "Setup hit a problem (code $0). Check your internet, then use Start menu > Ped Bot > Repair."
  ; one app only: remove the old Pedro Agent shortcuts and launcher
  Delete "$DESKTOP\${OLDAPP}.lnk"
  RMDir /r "$SMPROGRAMS\${OLDAPP}"
  Delete "$SMPROGRAMS\${OLDAPP}.lnk"
  Delete "$INSTDIR\Start Pedro Agent.cmd"
  CreateDirectory "$SMPROGRAMS\${APP}"
  CreateShortCut "$SMPROGRAMS\${APP}\${APP}.lnk" "$INSTDIR\.venv\Scripts\pythonw.exe" '"$INSTDIR\main.py" --app' "$INSTDIR\installer\pedbot.ico" 0 SW_SHOWNORMAL "" "Your PC assistant"
  CreateShortCut "$SMPROGRAMS\${APP}\Repair ${APP}.lnk" "$INSTDIR\setup.bat"
  CreateShortCut "$SMPROGRAMS\${APP}\Uninstall ${APP}.lnk" "$INSTDIR\Uninstall.exe"
  CreateShortCut "$DESKTOP\${APP}.lnk" "$INSTDIR\.venv\Scripts\pythonw.exe" '"$INSTDIR\main.py" --app' "$INSTDIR\installer\pedbot.ico" 0
  WriteUninstaller "$INSTDIR\Uninstall.exe"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\PedroAgent" "DisplayName" "${APP}"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\PedroAgent" "DisplayVersion" "${VER}"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\PedroAgent" "UninstallString" '"$INSTDIR\Uninstall.exe"'
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\PedroAgent" "DisplayIcon" "$INSTDIR\installer\pedbot.ico"
  WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\PedroAgent" "NoModify" 1
SectionEnd

Section "Uninstall"
  Delete "$DESKTOP\${APP}.lnk"
  RMDir /r "$SMPROGRAMS\${APP}"
  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\PedroAgent"
  Delete "$LOCALAPPDATA\Microsoft\WindowsApps\ped.cmd"
  MessageBox MB_YESNO|MB_ICONQUESTION "Also delete your chats, bots, groups, keys (.env) and rules?$\n$\nChoose No to keep them for a later reinstall." IDYES wipe
    RMDir /r "$INSTDIR\.venv"
    RMDir /r "$INSTDIR\python"
    Delete "$INSTDIR\*.py"
    RMDir /r "$INSTDIR\app_static"
    RMDir /r "$INSTDIR\installer"
    RMDir /r "$INSTDIR\skills"
    Delete "$INSTDIR\Uninstall.exe"
    Goto done
  wipe:
    RMDir /r "$INSTDIR"
  done:
SectionEnd
