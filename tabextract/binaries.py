# TabXtract - extracts tablature from video and rebuilds it as a PDF.
# Copyright (C) 2026 TabXtract contributors
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See <https://www.gnu.org/licenses/>.
"""Resolution of the external binaries the engine shells out to.

The engine knows nothing about Tauri or how the app is packaged: it only
reads environment variables. Whoever does the packaging (the desktop sidecar)
resolves "PATH first, bundled copy otherwise" and exports the result here.
Without those variables the behaviour is the usual one: look on PATH.
"""
from __future__ import annotations

import os
import shutil


def ffmpeg_bin() -> str:
    return os.environ.get("TABEXTRACT_FFMPEG") or "ffmpeg"


def ffprobe_bin() -> str:
    return os.environ.get("TABEXTRACT_FFPROBE") or "ffprobe"


def tesseract_bin() -> str | None:
    """Path to the tesseract binary, or None to let pytesseract search PATH."""
    return os.environ.get("TABEXTRACT_TESSERACT") or None


def configure_tesseract() -> None:
    """Apply TABEXTRACT_TESSERACT to pytesseract when it is set.

    Called when `verify` is imported. It is idempotent, and it does not fail
    when the variable points at something missing: the useful failure is the
    one tesseract raises when it runs, with its own message, not an
    ImportError at import time.
    """
    explicit = tesseract_bin()
    if not explicit:
        return
    import pytesseract

    pytesseract.pytesseract.tesseract_cmd = explicit


def missing_binaries() -> list[str]:
    """Diagnostic: which external binaries cannot be resolved.

    ffmpeg and ffprobe are required. tesseract is not: without it the
    bar-number continuity check is lost and the rest of the pipeline runs
    unchanged, so it appears in this list as a warning, not as a blocker.
    """
    missing = []
    candidates = [("ffmpeg", ffmpeg_bin()), ("ffprobe", ffprobe_bin()),
                  ("tesseract", tesseract_bin() or "tesseract")]
    for name, path in candidates:
        if not (os.path.isfile(path) or shutil.which(path)):
            missing.append(name)
    return missing
