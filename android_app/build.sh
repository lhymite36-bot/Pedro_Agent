#!/bin/bash
set -e
cd "$(dirname "$0")"
SDK=${ANDROID_HOME:-$HOME/Android/Sdk}; BT=$SDK/build-tools/35.0.0; AJ=$SDK/platforms/android-35/android.jar
JAVA_HOME=${JAVA_HOME:-$HOME/jdk17}; export PATH=$JAVA_HOME/bin:$PATH
rm -rf build && mkdir -p build/gen build/obj build/res build/dex
$BT/aapt2 compile --dir res -o build/res/res.zip
$BT/aapt2 link -I $AJ --manifest AndroidManifest.xml -o build/unsigned.apk --java build/gen build/res/res.zip --min-sdk-version 24 --target-sdk-version 35 --version-code ${VERSION_CODE:-10505} --version-name ${VERSION_NAME:-1.5.5} -A assets
javac -source 11 -target 11 -classpath $AJ -d build/obj $(find src build/gen -name '*.java') 2>&1 | grep -v "bootstrap\|^1 warning\|source value\|target value\|To suppress" || true
$BT/d8 --min-api 24 --lib $AJ --output build/dex $(find build/obj -name '*.class')
cp build/unsigned.apk build/u2.apk && python3 -c "import zipfile;zipfile.ZipFile('build/u2.apk','a').write('build/dex/classes.dex','classes.dex')"
$BT/zipalign -f -p 4 build/u2.apk build/aligned.apk
# Signing key: the Ped Bot release keystore (1.4.14+). CI gets it from GitHub Actions secrets;
# it is never generated here and never committed.
KS=${KEYSTORE:?set KEYSTORE to the release keystore path}
[ -f "$KS" ] || { echo "Keystore not found: $KS" >&2; exit 1; }
: "${KS_PASS:?set KS_PASS}"; export KEY_PASS="${KEY_PASS:-$KS_PASS}"
$BT/apksigner sign --ks "$KS" --ks-key-alias "${KEY_ALIAS:-pedbot}" --ks-pass env:KS_PASS --key-pass env:KEY_PASS --out build/PedBot.apk build/aligned.apk
$BT/apksigner verify --print-certs build/PedBot.apk | grep -i 'SHA-256' && ls -la build/PedBot.apk
