# Pedro_Agent setup: finds or installs Python 3.12 (per-user), makes .venv,
# installs the requirements and creates your .env. Safe to run again (repair).
param([string]$AppDir = (Split-Path -Parent $PSScriptRoot))
$ErrorActionPreference = 'Stop'
Set-Location $AppDir
Write-Host "Pedro_Agent setup in $AppDir" -ForegroundColor Cyan

function Find-Python {
    foreach ($c in @('py -3.12', 'py -3.11', 'py -3', 'python')) {
        $exe, $arg = $c.Split(' ', 2)
        try {
            $v = & $exe $arg -c "import sys;print('%d.%d'%sys.version_info[:2]);print(sys.executable)" 2>$null
            # 3.10-3.12 only: some packages have no wheels for newer Pythons yet
            if ($LASTEXITCODE -eq 0 -and $v -and [version]$v[0] -ge [version]'3.10' -and [version]$v[0] -le [version]'3.14') { return $v[1] }
        } catch {}
    }
    $local = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'
    if (Test-Path $local) { return $local }
    return $null
}

$py = Find-Python
if (-not $py) {
    Write-Host "Python not found. Installing Python 3.12 for this user (free, from python.org)..." -ForegroundColor Yellow
    $ok = $false
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        # winget is Microsoft's own installer; shown, not silent
        winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
        $ok = $LASTEXITCODE -eq 0
    }
    if (-not $ok) {
        # never download and run an .exe silently: open python.org and let the user install it
        Write-Host "Please install Python 3.12 from the page that just opened (tick 'Add python.exe to PATH'), then run 'Repair Pedro Agent'." -ForegroundColor Yellow
        Start-Process 'https://www.python.org/downloads/release/python-3127/'
        Read-Host 'Press Enter after Python is installed'
    }
    $py = Find-Python
    if (-not $py) { throw "Python install failed. Install Python 3.12 from python.org, then run 'Repair Pedro Agent' from the Start menu." }
}
Write-Host "Using Python: $py"

if (-not (Test-Path '.venv\Scripts\python.exe')) { & $py -m venv .venv; if ($LASTEXITCODE) { throw 'Could not create .venv' } }
$vpy = Join-Path $AppDir '.venv\Scripts\python.exe'
& $vpy -m pip install --upgrade pip --disable-pip-version-check -q
Write-Host "Installing packages (a few minutes the first time)..."
& $vpy -m pip install -r requirements.txt --disable-pip-version-check
if ($LASTEXITCODE) { throw 'pip install failed. Check your internet connection and run Repair.' }
Write-Host "Optional: browser automation needs Chromium. Run '.venv\Scripts\python -m playwright install chromium' later if you use it."

if (-not (Test-Path '.env')) { Copy-Item '.env.example' '.env' }
foreach ($d in 'storage', 'logs', 'data', 'temp') { New-Item -ItemType Directory -Force $d | Out-Null }
Write-Host "Done! Open 'Pedro Agent' from your Desktop. On first start it asks for your free Gemini API key." -ForegroundColor Green
