#!/usr/bin/env bash
# TabXtract - extracts tablature from video and rebuilds it as a PDF.
# Copyright (C) 2026 TabXtract contributors
# Licensed under the GNU General Public License v3 or later. See LICENSE.
#
# Builds the Linux artifacts in a container and leaves them in
# dist-artifacts/. Usage:
#
#   scripts/build-in-docker.sh              # .deb
#   scripts/build-in-docker.sh deb,appimage # both
#
# Needs around 8 GB free: the image is ~2.5 GB and the cargo and release-target
# caches another ~5 GB. The cache lives in a volume named
# tabxtract-build-cache; remove it with `docker volume rm tabxtract-build-cache`.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE=tabxtract-build-linux
CACHE=tabxtract-build-cache
BUNDLES="${1:-deb}"

docker build -f "$ROOT/docker/build-linux.Dockerfile" -t "$IMAGE" "$ROOT/docker"
docker volume create "$CACHE" >/dev/null

docker run --rm \
  -e BUNDLES="$BUNDLES" \
  -v "$ROOT:/src" \
  -v "$CACHE:/cache" \
  "$IMAGE"
