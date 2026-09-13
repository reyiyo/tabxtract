# -*- mode: python ; coding: utf-8 -*-
# TabXtract - extracts tablature from video and rebuilds it as a PDF.
# Copyright (C) 2026 TabXtract contributors
# Licensed under the GNU General Public License v3 or later.
"""PyInstaller spec for the sidecar.

onedir mode: it starts considerably faster than onefile, which unpacks the
whole bundle on every run. In a desktop app that shows up as time to first
screen.
"""
from PyInstaller.utils.hooks import collect_submodules

hiddenimports = [
    # The wrapper imports `server` at runtime; the rest of the package comes
    # in through here.
    *collect_submodules("server"),
    # uvicorn loads its workers by name at runtime, so static analysis does
    # not see them.
    *collect_submodules("uvicorn"),
    "websockets",
    "websockets.legacy",
    "anyio",
    # cv2/numpy/scipy are covered by PyInstaller's own hooks.
]

excludes = [
    # yt-dlp is NOT frozen: it is resolved as an updatable external binary.
    # See server/ytdlp.py.
    "yt_dlp",
    # Leftovers from the web version: if any of these slips in, it is a bug.
    "celery",
    "redis",
    "kombu",
    # Dead weight in a GUI-less backend.
    "tkinter",
    "matplotlib",
    "pytest",
    "IPython",
]

a = Analysis(
    # The entry point is wrapped on purpose: PyInstaller runs the script as
    # __main__ with no parent package and server/'s relative imports break.
    ["sidecar_entry.py"],
    pathex=[".."],
    binaries=[],
    datas=[],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="tabxtract-server",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="tabxtract-server",
)
