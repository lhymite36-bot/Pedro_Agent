; Pedro_Agent Windows installer (per-user, no admin needed). Build: makensis installer/PedroAgent.nsi
Unicode true
!define APP "Pedro Agent"
!define VER "1.2.0"
!include "MUI2.nsh"
Name "${APP}"
OutFile "..\dist\PedroAgent-Setup-${VER}.exe"
InstallDir "$LOCALAPPDATA\PedroAgent"
RequestExecutionLevel user
SetCompressor /SOLID lzma
!define MUI_ICON "pedro.ico"
!define MUI_UNICON "pedro.ico"
!define MUI_FINISHPAGE_RUN
!define MUI_FINISHPAGE_RUN_FUNCTION StartApp
!define MUI_FINISHPAGE_RUN_TEXT "Start Pedro Agent now"
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"

Function StartApp
  SetOutPath "$INSTDIR"
  Exec '"$INSTDIR\.venv\Scripts\pythonw.exe" "$INSTDIR\main.py" --app'
FunctionEnd

Section "Install"
  SetOutPath "$INSTDIR"
  File /r /x .git /x .github /x dist /x tests /x android_app /x "*.pyc" /x __pycache__ /x rules.yaml /x .env /x storage /x workspace /x docs "..\*.*"
  ; keep the user's own settings on upgrade
  IfFileExists "$INSTDIR\rules.yaml" +2 0
  CopyFiles /SILENT "$INSTDIR\rules.default.yaml" "$INSTDIR\rules.yaml"
  DetailPrint "Setting up Python and packages (this can take a few minutes)..."
  nsExec::ExecToLog 'powershell -NoProfile -ExecutionPolicy Bypass -File "$INSTDIR\installer\setup.ps1" -AppDir "$INSTDIR"'
  Pop $0
  StrCmp $0 "0" +2 0
  MessageBox MB_ICONEXCLAMATION "Setup hit a problem (code $0). Check your internet, then use Start menu > Pedro Agent > Repair."
  CreateDirectory "$SMPROGRAMS\${APP}"
  CreateShortCut "$SMPROGRAMS\${APP}\${APP}.lnk" "$INSTDIR\.venv\Scripts\pythonw.exe" '"$INSTDIR\main.py" --app' "$INSTDIR\installer\pedro.ico" 0 SW_SHOWNORMAL "" "Your PC assistant"
  CreateShortCut "$SMPROGRAMS\${APP}\Repair ${APP}.lnk" "powershell.exe" '-NoProfile -ExecutionPolicy Bypass -File "$INSTDIR\installer\setup.ps1" -AppDir "$INSTDIR"'
  CreateShortCut "$SMPROGRAMS\${APP}\Uninstall ${APP}.lnk" "$INSTDIR\Uninstall.exe"
  CreateShortCut "$DESKTOP\${APP}.lnk" "$INSTDIR\.venv\Scripts\pythonw.exe" '"$INSTDIR\main.py" --app' "$INSTDIR\installer\pedro.ico" 0
  WriteUninstaller "$INSTDIR\Uninstall.exe"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\PedroAgent" "DisplayName" "${APP}"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\PedroAgent" "DisplayVersion" "${VER}"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\PedroAgent" "UninstallString" '"$INSTDIR\Uninstall.exe"'
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\PedroAgent" "DisplayIcon" "$INSTDIR\installer\pedro.ico"
  WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\PedroAgent" "NoModify" 1
SectionEnd

Section "Uninstall"
  Delete "$DESKTOP\${APP}.lnk"
  RMDir /r "$SMPROGRAMS\${APP}"
  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\PedroAgent"
  MessageBox MB_YESNO|MB_ICONQUESTION "Also delete your chats, bots, groups, keys (.env) and rules?$\n$\nChoose No to keep them for a later reinstall." IDYES wipe
    RMDir /r "$INSTDIR\.venv"
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
