@echo off
rem Pedro Agent portable setup / repair. Plain batch file you can read: it finds
rem Python 3.10-3.12, creates .venv, installs requirements.txt, and makes a launcher.
rem It downloads nothing except Python packages from pypi.org via pip.
setlocal
cd /d "%~dp0"
title Pedro Agent setup
echo Pedro Agent setup in %CD%
set "PY="
for %%V in (3.12 3.11 3.10) do (
  if not defined PY ( py -%%V -c "import sys" >nul 2>&1 && set "PY=py -%%V" )
)
if not defined PY (
  python -c "import sys; assert (3,10) <= sys.version_info[:2] <= (3,12)" >nul 2>&1 && set "PY=python"
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
".venv\Scripts\python.exe" -m pip install -r requirements.txt --disable-pip-version-check || goto fail
if not exist ".env" copy ".env.example" ".env" >nul
for %%D in (storage logs data temp) do if not exist "%%D" mkdir "%%D"
if not exist "rules.yaml" copy "rules.default.yaml" "rules.yaml" >nul
> "Start Pedro Agent.cmd" echo @start "" "%%~dp0.venv\Scripts\pythonw.exe" "%%~dp0main.py" --app
echo.
echo Done. Double-click "Start Pedro Agent.cmd" in this folder to open the app.
echo On first start it asks for your free Gemini API key.
pause
exit /b 0
:fail
echo Setup failed. Check your internet connection and run setup.bat again.
pause
exit /b 1
