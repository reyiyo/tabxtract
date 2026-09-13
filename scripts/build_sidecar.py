#!/usr/bin/env python3
# TabXtract - extracts tablature from video and rebuilds it as a PDF.
# Copyright (C) 2026 TabXtract contributors
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See <https://www.gnu.org/licenses/>.
"""Freeze the backend with PyInstaller and leave it where Tauri bundles it.

Usage:
    python scripts/build_sidecar.py --target x86_64-unknown-linux-gnu

The result is a directory (onedir) in `src-tauri/sidecar/`, which
`tauri.conf.json` includes as a bundle resource. `externalBin` is not used
because that list only takes single files and a onedir is a directory;
onefile would sidestep that at the cost of unpacking itself on every launch,
which is exactly what this project does not want.

PyInstaller does not cross-compile: every platform freezes its own, on its own
runner.
"""
from __future__ import annotations

import argparse
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "scripts" / "tabxtract-server.spec"
OUT_DIR = ROOT / "src-tauri" / "sidecar"

HOST_TRIPLES = {
    ("Darwin", "arm64"): "aarch64-apple-darwin",
    ("Darwin", "x86_64"): "x86_64-apple-darwin",
    ("Linux", "x86_64"): "x86_64-unknown-linux-gnu",
    ("Linux", "aarch64"): "aarch64-unknown-linux-gnu",
    ("Windows", "AMD64"): "x86_64-pc-windows-msvc",
}


def host_triple() -> str | None:
    return HOST_TRIPLES.get((platform.system(), platform.machine()))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", default=None, help="target triple to build")
    parser.add_argument("--targets", default=None,
                        help="space-separated list (only one is accepted: "
                             "PyInstaller does not cross-compile)")
    parser.add_argument("--skip-check", action="store_true",
                        help="do not start the frozen binary to verify it")
    args = parser.parse_args()

    requested = [t for t in (args.targets or args.target or "").split() if t]
    host = host_triple()
    if len(requested) > 1:
        print(f"error: {len(requested)} targets requested ({', '.join(requested)}). "
              "PyInstaller only freezes for the platform it runs on; use one "
              "runner per architecture.", file=sys.stderr)
        return 2
    if requested and host and requested[0] != host:
        print(f"error: target {requested[0]} requested on a {host} host.", file=sys.stderr)
        return 2

    target = requested[0] if requested else (host or "unknown")
    print(f"freezing the sidecar for {target}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    staged = OUT_DIR / "tabxtract-server"
    shutil.rmtree(staged, ignore_errors=True)

    subprocess.run(
        [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
         "--distpath", str(OUT_DIR),
         "--workpath", str(ROOT / "build" / "pyinstaller"),
         str(SPEC)],
        check=True, cwd=SPEC.parent,
    )

    binary = staged / ("tabxtract-server.exe" if sys.platform == "win32" else "tabxtract-server")
    if not binary.is_file():
        print(f"error: PyInstaller did not produce {binary}", file=sys.stderr)
        return 1

    size_mb = sum(f.stat().st_size for f in staged.rglob("*") if f.is_file()) / 1e6
    print(f"done: {staged} ({size_mb:.0f} MB)")

    if not args.skip_check:
        return check_frozen(binary)
    return 0


def check_frozen(binary: Path) -> int:
    """Start the binary and wait for the handshake.

    PyInstaller happily produces binaries missing a dynamic import that only
    blow up on startup; without this check that failure shows up on the user's
    machine.
    """
    import json

    proc = subprocess.Popen([str(binary)], stdout=subprocess.PIPE,
                            stdin=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        line = proc.stdout.readline().strip() if proc.stdout else ""
        if not line.startswith("TABXTRACT_READY "):
            stderr = proc.stderr.read()[:4000] if proc.stderr else ""
            print(f"error: the frozen binary did not emit the handshake.\n{stderr}",
                  file=sys.stderr)
            return 1
        info = json.loads(line.removeprefix("TABXTRACT_READY "))
        print(f"handshake ok: port {info['port']}")
        return 0
    finally:
        proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
