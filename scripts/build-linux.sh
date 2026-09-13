#!/usr/bin/env bash
# TabXtract - extracts tablature from video and rebuilds it as a PDF.
# Copyright (C) 2026 TabXtract contributors
# Licensed under the GNU General Public License v3 or later. See LICENSE.
#
# Runs INSIDE the container from docker/build-linux.Dockerfile.
# From the host it is invoked through scripts/build-in-docker.sh.
set -euo pipefail

SRC=/src
BUILD=/build
BUNDLES="${BUNDLES:-deb}"

# The tree is copied rather than built on the mount: that way the build does
# not clobber the host's node_modules (which holds macOS binaries) or leave a
# target/ on top of it, and the heavy directories stay out.
echo ">> copying the source tree"
rsync -a --delete \
  --exclude .git --exclude node_modules --exclude .venv \
  --exclude data --exclude test-videos --exclude reference-pdfs \
  --exclude dist-artifacts --exclude 'src-tauri/target' \
  "$SRC/" "$BUILD/"
cd "$BUILD"

# The venv lives in the cache: reinstalling opencv and scipy on every run is
# several minutes for nothing.
if [ ! -x /cache/venv/bin/python ]; then
  echo ">> creating the Python environment"
  python3 -m venv /cache/venv
fi
/cache/venv/bin/pip install --quiet --upgrade pip
/cache/venv/bin/pip install --quiet --require-hashes -r requirements/sidecar.txt
/cache/venv/bin/pip install --quiet --no-deps -e .

echo ">> freezing the sidecar (PyInstaller onedir + verification start)"
/cache/venv/bin/python scripts/build_sidecar.py

echo ">> downloading the native binaries"
/cache/venv/bin/python scripts/fetch_native_deps.py

echo ">> frontend dependencies"
npm ci

echo ">> icons"
npx tauri icon src-tauri/icons/source.png

echo ">> Tauri build ($BUNDLES)"
npm run tauri build -- --bundles "$BUNDLES"

echo ">> copying artifacts into dist-artifacts/"
OUT="$SRC/dist-artifacts"
mkdir -p "$OUT"
find "${CARGO_TARGET_DIR:-target}/release/bundle" \
     -type f \( -name '*.deb' -o -name '*.AppImage' -o -name '*.rpm' \) \
     -exec cp -v {} "$OUT/" \;
ls -lh "$OUT"
