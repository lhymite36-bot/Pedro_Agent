$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$javaHome = "C:\Program Files\JetBrains\PyCharm 2025.3.3\jbr"
$env:JAVA_HOME = $javaHome
$env:Path = "$javaHome\bin;" + $env:Path
$sdk = Join-Path $env:LOCALAPPDATA "Android\Sdk"
$bt = Join-Path $sdk "build-tools\36.1.0"
$jar = Join-Path $sdk "platforms\android-36.1\android.jar"
if (-not (Test-Path $jar)) { $jar = Join-Path $sdk "platforms\android-36\android.jar" }
if (-not (Test-Path "$bt\aapt2.exe")) { throw "Android build-tools 36.1.0 missing" }
if (-not (Test-Path $jar)) { throw "android.jar missing" }

& python "$PSScriptRoot\generate_config.py"
if ($LASTEXITCODE -ne 0) { throw "generate_config.py failed" }

$build = Join-Path $PSScriptRoot "build"
if (Test-Path $build) { Remove-Item $build -Recurse -Force }
New-Item -ItemType Directory -Path "$build\gen","$build\obj","$build\res","$build\dex","$build\assets\web" | Out-Null
# 1.5.13: phone-only mode runs the same web UI as the PC, bundled from app_static
Copy-Item "$PSScriptRoot\..\app_static\*" "$build\assets\web" -Recurse -Force
Copy-Item "$PSScriptRoot\res\raw\phone_core.js","$PSScriptRoot\phone_web\phone_shim.js" "$build\assets\web" -Force

& "$bt\aapt2.exe" compile --dir "$PSScriptRoot\res" -o "$build\res\res.zip"
if ($LASTEXITCODE -ne 0) { throw "aapt2 compile failed" }
& "$bt\aapt2.exe" link -I $jar --manifest "$PSScriptRoot\AndroidManifest.xml" -A "$build\assets" -o "$build\unsigned.apk" --java "$build\gen" "$build\res\res.zip" --min-sdk-version 24 --target-sdk-version 35 --version-code 19 --version-name "1.7.2"
if ($LASTEXITCODE -ne 0) { throw "aapt2 link failed" }

$sources = Get-ChildItem "$PSScriptRoot\src","$build\gen" -Recurse -Filter "*.java" | ForEach-Object { $_.FullName }
& javac --release 11 -classpath $jar -d "$build\obj" @sources
if ($LASTEXITCODE -ne 0) { throw "javac failed" }

$classes = Get-ChildItem "$build\obj" -Recurse -Filter "*.class" | ForEach-Object { $_.FullName }
& "$bt\d8.bat" --min-api 24 --lib $jar --output "$build\dex" @classes
if ($LASTEXITCODE -ne 0) { throw "d8 failed" }

Copy-Item "$build\unsigned.apk" "$build\u2.apk" -Force
python -c "import zipfile; z=zipfile.ZipFile(r'$build\u2.apk','a'); z.write(r'$build\dex\classes.dex','classes.dex'); z.close()"
& "$bt\zipalign.exe" -f -p 4 "$build\u2.apk" "$build\aligned.apk"
if ($LASTEXITCODE -ne 0) { throw "zipalign failed" }

$ks = Join-Path $env:USERPROFILE ".pedro-agent-release.jks"
if (-not (Test-Path $ks)) {
  & keytool -genkeypair -keystore $ks -alias pedro -keyalg RSA -keysize 2048 -validity 10000 -storepass pedroagent -keypass pedroagent -dname "CN=Pedro Agent"
}
& "$bt\apksigner.bat" sign --ks $ks --ks-pass pass:pedroagent --out "$build\PedroAgent.apk" "$build\aligned.apk"
if ($LASTEXITCODE -ne 0) { throw "apksigner failed" }
& "$bt\apksigner.bat" verify "$build\PedroAgent.apk"
Get-Item "$build\PedroAgent.apk" | Select-Object FullName, Length, LastWriteTime
