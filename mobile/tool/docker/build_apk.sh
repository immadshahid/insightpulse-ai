#!/bin/sh
# Build the release APK in Linux and copy it to /out.
# Mount the app read-only at /src, an output folder at /out, and your signing key at
# /root/.android/debug.keystore (so the APK's SHA-1 matches the one in Firebase).
# Extra arguments go to `flutter build apk`, e.g. --dart-define=API_BASE_URL=http://10.0.2.2:8000
set -e
mkdir -p /work
cd /src
tar --exclude=./build --exclude=./.dart_tool --exclude=./android/.gradle --exclude=./android/local.properties \
  -cf - . | (cd /work && tar xf -)
cd /work
flutter pub get >/dev/null
flutter build apk --release "$@"
cp build/app/outputs/flutter-apk/app-release.apk /out/InsightPulse.apk
echo "APK written to /out/InsightPulse.apk"
