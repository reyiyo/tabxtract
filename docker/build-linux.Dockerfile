# TabXtract - extracts tablature from video and rebuilds it as a PDF.
# Copyright (C) 2026 TabXtract contributors
# Licensed under the GNU General Public License v3 or later. See LICENSE.
#
# Toolchain image for building the Linux artifacts without installing
# anything on the development machine.
#
# Linux only. The .dmg needs macOS with Xcode and the .msi needs Windows:
# beyond Tauri's bundler, PyInstaller does not cross-compile, so the sidecar
# has to be frozen on the target platform. For those two, the path is
# .github/workflows/release.yml.
#
# The artifact's architecture is the Docker daemon's. On an Apple Silicon Mac
# that means arm64; for x86_64 you have to pass --platform linux/amd64, which
# runs emulated and is far slower.
FROM rust:1-slim-bookworm

# Node 24 (LTS): bookworm ships 18, and an extra repo is not worth it.
COPY --from=node:24-bookworm-slim /usr/local/bin /usr/local/bin
COPY --from=node:24-bookworm-slim /usr/local/lib/node_modules /usr/local/lib/node_modules

# Bookworm already ships Python 3.11, the version the engine asks for.
RUN apt-get update && apt-get install -y --no-install-recommends \
      libwebkit2gtk-4.1-dev \
      libgtk-3-dev \
      libsoup-3.0-dev \
      libjavascriptcoregtk-4.1-dev \
      libayatana-appindicator3-dev \
      librsvg2-dev \
      libssl-dev \
      patchelf \
      build-essential \
      pkg-config \
      python3 \
      python3-venv \
      python3-dev \
      binutils \
      ca-certificates \
      curl \
      file \
      rsync \
      xz-utils \
    && rm -rf /var/lib/apt/lists/*

# The AppImage bundler runs linuxdeploy, which cannot mount itself without
# FUSE. Self-extraction is the supported way out inside a container.
ENV APPIMAGE_EXTRACT_AND_RUN=1

# Everything heavy and cacheable lives in /cache, which the wrapper mounts as
# a volume: without it, every run recompiles the whole Tauri tree.
ENV CARGO_HOME=/cache/cargo \
    CARGO_TARGET_DIR=/cache/target \
    npm_config_cache=/cache/npm

WORKDIR /build
CMD ["bash", "/src/scripts/build-linux.sh"]
