@echo off
rem Pedro Agent portable setup / repair. Plain batch file you can read: it finds
rem Python 3.10-3.14, creates .venv, installs requirements.txt, and makes a launcher.
rem It downloads nothing except Python packages from pypi.org via pip.
setlocal
set "AUTO="
if /i "%~1"=="/auto" set "AUTO=1"
cd /d "%~dp0"
title Ped Bot setup
echo Ped Bot setup in %CD%
set "PY="
rem The installer ships its own python.org Python in .\python (not the Microsoft Store one,
rem which makes Windows show a Python icon on the taskbar instead of Ped Bot).
if exist "%~dp0python\python.exe" set "PY="%~dp0python\python.exe""
if defined PY if exist ".venv\pyvenv.cfg" ( findstr /i /c:"%~dp0python" ".venv\pyvenv.cfg" >nul || ( echo Rebuilding .venv on the bundled Python... & rd /s /q ".venv" ) )
for %%V in (3.12 3.13 3.14 3.11 3.10) do (
  if not defined PY ( py -%%V -c "import sys" >nul 2>&1 && set "PY=py -%%V" )
)
if not defined PY (
  python -c "import sys; assert (3,10) <= sys.version_info[:2] <= (3,14)" >nul 2>&1 && set "PY=python"
)
if not defined PY (
  echo.
  echo Python 3.12 is needed. Opening python.org - install it and tick "Add python.exe to PATH",
  echo then run setup.bat again.
  start "" https://www.python.org/downloads/release/python-3127/
  pause
  exit /b 1
)
echo Using %PY%
rem 1.5.10 fix: an embeddable Python ships pythonXY._pth, which isolates it (no site, no pip, no venv).
if exist "%~dp0python\python.exe" for %%F in ("%~dp0python\python*._pth") do ren "%%~fF" "%%~nxF.disabled"
if not exist ".venv\Scripts\python.exe" (
  %PY% -m venv .venv
  if not exist ".venv\Scripts\python.exe" ( %PY% -m venv --without-pip .venv || goto fail )
)
".venv\Scripts\python.exe" -m pip --version >nul 2>&1 || ".venv\Scripts\python.exe" -m ensurepip --upgrade >nul 2>&1
".venv\Scripts\python.exe" -m pip --version >nul 2>&1 || call :getpip
".venv\Scripts\python.exe" -m pip --version >nul 2>&1 || goto fail
".venv\Scripts\python.exe" -m pip install --upgrade pip --disable-pip-version-check -q
echo Installing packages (a few minutes the first time)...
rem Core packages first, so one optional package that fails cannot leave the app unable to start.
".venv\Scripts\python.exe" -m pip install "pyyaml>=6.0" --disable-pip-version-check -q || goto fail
".venv\Scripts\python.exe" -m pip install -r requirements.txt --disable-pip-version-check
if errorlevel 1 (
  echo Some optional packages did not install. Retrying each one so the rest still work...
  for /f "usebackq eol=# tokens=*" %%R in ("requirements.txt") do ".venv\Scripts\python.exe" -m pip install "%%R" --disable-pip-version-check -q
)
".venv\Scripts\python.exe" -c "import yaml" || goto fail
if not exist ".env" copy ".env.example" ".env" >nul
for %%D in (storage logs data temp) do if not exist "%%D" mkdir "%%D"
if not exist "rules.yaml" copy "rules.default.yaml" "rules.yaml" >nul
if exist "Start Pedro Agent.cmd" del "Start Pedro Agent.cmd"
> "Start Ped Bot.cmd" echo @start "" "%%~dp0.venv\Scripts\pythonw.exe" "%%~dp0main.py" --app
rem "ped" terminal command: a tiny launcher in WindowsApps, which is already on the user PATH.
if exist "%LOCALAPPDATA%\Microsoft\WindowsApps\" > "%LOCALAPPDATA%\Microsoft\WindowsApps\ped.cmd" echo @"%~dp0.venv\Scripts\python.exe" "%~dp0ped.py" %%*
echo.
echo Done. Double-click "Start Ped Bot.cmd" in this folder to open the app.
echo On first start it asks for your free Gemini API key.
if not defined AUTO pause
exit /b 0
:getpip
echo pip is missing, bootstrapping it with get-pip.py...
set "GETPIP=%~dp0python\get-pip.py"
if not exist "%GETPIP%" ( set "GETPIP=%TEMP%\pedbot-get-pip.py" & curl.exe -fsSL -o "%TEMP%\pedbot-get-pip.py" https://bootstrap.pypa.io/get-pip.py )
".venv\Scripts\python.exe" "%GETPIP%" --disable-pip-version-check -q
exit /b 0
:fail
echo Setup failed. Check your internet connection and run setup.bat again.
if not defined AUTO pause
exit /b 1
