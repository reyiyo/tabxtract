# TabXtract - extracts tablature from video and rebuilds it as a PDF.
# Copyright (C) 2026 TabXtract contributors
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See <https://www.gnu.org/licenses/>.
"""Paths and preferences for the desktop app.

Tauri passes the data directory in `TABXTRACT_DATA_DIR`. When the sidecar runs
on its own (development, or `python -m server`) it falls back to each
platform's standard directory, so the state is the same with and without the
GUI.

What persists -- history, profiles, preferences -- lives in the data
directory. What is intermediate -- frames, downloaded videos -- lives in temp
and is deleted when the job finishes: it is hundreds of MB per video.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

APP_NAME = "TabXtract"

DEFAULT_PREFERENCES: dict[str, Any] = {
    # Output directory remembered between sessions; asked for once.
    "output_dir": None,
    # Update check. The user has to be able to turn it off.
    "updates_enabled": True,
    # First-run legal notice: shown once.
    "legal_notice_acknowledged": False,
    # Default maximum height for URL downloads: no audio is needed, and above
    # 1080p the engine scales back down anyway.
    "youtube_max_height": 1080,
}


def app_data_dir() -> Path:
    explicit = os.environ.get("TABXTRACT_DATA_DIR")
    if explicit:
        base = Path(explicit)
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / APP_NAME
    elif os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / APP_NAME
    else:
        xdg = os.environ.get("XDG_DATA_HOME")
        base = (Path(xdg) if xdg else Path.home() / ".local" / "share") / APP_NAME
    base.mkdir(parents=True, exist_ok=True)
    return base


def log_path() -> Path:
    return app_data_dir() / "tabxtract.log"


def db_path() -> Path:
    return app_data_dir() / "tabxtract.sqlite3"


def profiles_dir() -> Path:
    d = app_data_dir() / "profiles"
    d.mkdir(parents=True, exist_ok=True)
    return d


def bin_dir() -> Path:
    """Binaries the user can update without waiting for a release (today only
    yt-dlp). It has to live outside the bundle: on macOS and Windows the app
    directory is read-only or signed."""
    d = app_data_dir() / "bin"
    d.mkdir(parents=True, exist_ok=True)
    return d


def temp_root() -> Path:
    d = Path(tempfile.gettempdir()) / "tabxtract"
    d.mkdir(parents=True, exist_ok=True)
    return d


def job_workdir(job_id: str) -> Path:
    d = temp_root() / job_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def _preferences_path() -> Path:
    return app_data_dir() / "preferences.json"


def load_preferences() -> dict[str, Any]:
    path = _preferences_path()
    prefs = dict(DEFAULT_PREFERENCES)
    if path.exists():
        try:
            prefs.update(json.loads(path.read_text()))
        except (json.JSONDecodeError, OSError):
            # A corrupt file must not stop the app from starting: it is
            # ignored and the next save rewrites it.
            pass
    return prefs


def save_preferences(patch: dict[str, Any]) -> dict[str, Any]:
    prefs = load_preferences()
    prefs.update({k: v for k, v in patch.items() if k in DEFAULT_PREFERENCES})
    _preferences_path().write_text(json.dumps(prefs, indent=2))
    return prefs
