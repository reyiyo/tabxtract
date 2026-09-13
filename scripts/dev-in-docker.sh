#!/usr/bin/env bash
# TabXtract - extracts tablature from video and rebuilds it as a PDF.
# Copyright (C) 2026 TabXtract contributors
# Licensed under the GNU General Public License v3 or later. See LICENSE.
#
# Runs a command inside the development container (docker/dev.Dockerfile)
# with the repository mounted at /src. Usage:
#
#   scripts/dev-in-docker.sh                       # interactive shell
#   scripts/dev-in-docker.sh pytest -q             # engine tests
#   scripts/dev-in-docker.sh npm test              # frontend tests
#   scripts/dev-in-docker.sh tabextract analyze test-videos/x.mp4 --workdir work
#
# The first run creates the venv and runs `npm ci`; later runs reuse both
# from the named volumes. Pass PORT=... to publish a container port, which
# `python -m server --port PORT` needs to be reached from the host browser.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE=tabxtract-dev
CACHE=tabxtract-dev-cache
MODULES=tabxtract-dev-node-modules

docker build -q -f "$ROOT/docker/dev.Dockerfile" -t "$IMAGE" "$ROOT/docker" >/dev/null
docker volume create "$CACHE" >/dev/null
docker volume create "$MODULES" >/dev/null

PUBLISH=()
if [ -n "${PORT:-}" ]; then
  PUBLISH=(-p "127.0.0.1:$PORT:$PORT")
fi

TTY=()
if [ -t 0 ]; then
  TTY=(-it)
fi

# Bootstrap once per volume: the venv from pyproject.toml, node_modules from
# the lock. Both are skipped when they already exist.
BOOTSTRAP='
if [ ! -x /cache/venv/bin/python ]; then
  echo ">> creating the Python environment (first run only)"
  python -m venv /cache/venv && pip install -q -e ".[dev,desktop,build]"
fi
if [ ! -f node_modules/.package-lock.json ]; then
  echo ">> installing node modules (first run only)"
  npm ci --silent
fi
'

if [ $# -eq 0 ]; then
  set -- bash
fi

# ${arr[@]+"${arr[@]}"}: the macOS bash (3.2) treats an empty array as an
# unbound variable under `set -u`; this expands to nothing instead of failing.
docker run --rm ${TTY[@]+"${TTY[@]}"} ${PUBLISH[@]+"${PUBLISH[@]}"} \
  -v "$ROOT:/src" \
  -v "$CACHE:/cache" \
  -v "$MODULES:/src/node_modules" \
  -e TABXTRACT_DATA_DIR=/cache/appdata \
  "$IMAGE" bash -c "$BOOTSTRAP"'exec "$@"' -- "$@"
