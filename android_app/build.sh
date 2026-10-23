#!/bin/bash
set -e
cd "$(dirname "$0")"
SDK=${ANDROID_HOME:-$HOME/Android/Sdk}; BT=$SDK/build-tools/35.0.0; AJ=$SDK/platforms/android-35/android.jar
JAVA_HOME=${JAVA_HOME:-$HOME/jdk17}; export PATH=$JAVA_HOME/bin:$PATH
rm -rf build && mkdir -p build/gen build/obj build/res build/dex
$BT/aapt2 compile --dir res -o build/res/res.zip
$BT/aapt2 link -I $AJ --manifest AndroidManifest.xml -o build/unsigned.apk --java build/gen build/res/res.zip --min-sdk-version 24 --target-sdk-version 35 --version-code 2 --version-name 1.1.0
javac -source 11 -target 11 -classpath $AJ -d build/obj $(find src build/gen -name '*.java') 2>&1 | grep -v "bootstrap\|^1 warning\|source value\|target value\|To suppress" || true
$BT/d8 --min-api 24 --lib $AJ --output build/dex $(find build/obj -name '*.class')
cp build/unsigned.apk build/u2.apk && python3 -c "import zipfile;zipfile.ZipFile('build/u2.apk','a').write('build/dex/classes.dex','classes.dex')"
$BT/zipalign -f -p 4 build/u2.apk build/aligned.apk
KS=${KEYSTORE:-$HOME/.pedro-agent-release.jks}
[ -f "$KS" ] || keytool -genkeypair -keystore "$KS" -alias pedro -keyalg RSA -keysize 2048 -validity 10000 -storepass "${KS_PASS:-pedroagent}" -keypass "${KS_PASS:-pedroagent}" -dname "CN=Pedro Agent"
$BT/apksigner sign --ks "$KS" --ks-pass pass:${KS_PASS:-pedroagent} --out build/PedroAgent.apk build/aligned.apk
$BT/apksigner verify build/PedroAgent.apk && ls -la build/PedroAgent.apk
