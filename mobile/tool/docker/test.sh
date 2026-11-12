#!/bin/sh
# Copy the app (read-only mount at /src) to a scratch folder, then analyze and test it.
# Usage: docker run --rm -v "<repo>/mobile:/src:ro" insightpulse-flutter:3.47.9 sh /src/tool/docker/test.sh
set -e
mkdir -p /work
cd /src
tar --exclude=./build --exclude=./.dart_tool --exclude=./android/.gradle -cf - . | (cd /work && tar xf -)
cd /work
flutter pub get >/dev/null
flutter analyze
flutter test "$@"
