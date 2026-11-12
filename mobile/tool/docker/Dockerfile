# Flutter 3.47.9 for running the app's tests (and builds) in Linux, e.g. on Windows PCs
# where Smart App Control blocks Flutter's own test runner.
#   docker build -t insightpulse-flutter:3.47.9 mobile/tool/docker
FROM ghcr.io/cirruslabs/flutter:stable

ARG FLUTTER_VERSION=3.47.9
RUN git clone --depth 1 --branch ${FLUTTER_VERSION} https://github.com/flutter/flutter.git /opt/flutter-pinned \
    && git config --global --add safe.directory /opt/flutter-pinned
ENV PATH="/opt/flutter-pinned/bin:${PATH}"

# Download the Dart SDK and test artifacts once, at build time.
RUN flutter --disable-analytics && flutter --version \
    && flutter create --platforms=android /tmp/warmup >/dev/null \
    && cd /tmp/warmup && flutter test >/dev/null && rm -rf /tmp/warmup
