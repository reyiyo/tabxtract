# TabXtract - extracts tablature from video and rebuilds it as a PDF.
# Copyright (C) 2026 TabXtract contributors
# Licensed under the GNU General Public License v3 or later. See LICENSE.
#
# Development image: Python 3.11, Node 24, ffmpeg and tesseract, and nothing
# else. It runs the engine, its tests, the linters, the frontend checks and
# the local backend without installing any of that on the host.
#
# It does NOT build installers. The Linux bundles come from
# build-linux.Dockerfile; the macOS and Windows ones need their own OS.
#
# Used through scripts/dev-in-docker.sh, which mounts the repository and
# keeps node_modules and the Python packages in a named volume so they never
# collide with the host's own copies.
FROM python:3.11-slim-bookworm

COPY --from=node:24-bookworm-slim /usr/local/bin /usr/local/bin
COPY --from=node:24-bookworm-slim /usr/local/lib/node_modules /usr/local/lib/node_modules

RUN apt-get update && apt-get install -y --no-install-recommends \
      ffmpeg \
      tesseract-ocr \
      libgl1 \
      libglib2.0-0 \
      git \
      ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# The venv and the npm cache live in /cache (a volume); node_modules is a
# separate volume mounted over /src/node_modules so the host's copy, built
# for another OS, is never touched.
ENV VIRTUAL_ENV=/cache/venv \
    PATH=/cache/venv/bin:$PATH \
    npm_config_cache=/cache/npm \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /src
CMD ["bash"]
