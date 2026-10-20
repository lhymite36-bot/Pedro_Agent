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
if not exist ".venv\Scripts\python.exe" ( %PY% -m venv .venv || goto fail )
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
echo.
echo Done. Double-click "Start Ped Bot.cmd" in this folder to open the app.
echo On first start it asks for your free Gemini API key.
if not defined AUTO pause
exit /b 0
:fail
echo Setup failed. Check your internet connection and run setup.bat again.
if not defined AUTO pause
exit /b 1
