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
import json
import os
import platform
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
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
    """Start the binary and wait for the handshake and a healthy API.

    PyInstaller happily produces binaries missing a dynamic import that only
    blow up on startup; without this check that failure shows up on the user's
    machine. The handshake alone is not enough: it is printed before the app
    module is imported, so a bundle missing FastAPI's dependencies still emits
    it and then dies.

    ffmpeg is not required on PATH here: the release runners for macOS and
    Windows do not install it, and the app resolves the bundled copy itself.
    """
    try:
        health = start_and_verify(binary, require_binaries=False)
    except SidecarCheckError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"handshake and /api/health ok (version {health['version']}, "
          f"missing binaries: {health['missing_binaries'] or 'none'})")
    return 0


class SidecarCheckError(RuntimeError):
    pass


HANDSHAKE_PREFIX = "TABXTRACT_READY "
STARTUP_TIMEOUT = 60.0


def start_and_verify(binary: Path, require_binaries: bool, timeout: float = STARTUP_TIMEOUT) -> dict:
    """Start a sidecar binary, wait for its handshake and a healthy /api/health.

    Shared by the build-time check above and by check_installed_bundle.py, so
    the startup protocol is written once. Returns the health payload; raises
    SidecarCheckError with the process's stderr on any failure. The process
    is always stopped before returning.
    """
    sys.path.insert(0, str(ROOT))  # `server` lives in the repo, not in site-packages
    from server.__main__ import HANDSHAKE_PREFIX as SERVER_PREFIX
    from server.main import TOKEN_HEADER

    assert SERVER_PREFIX == HANDSHAKE_PREFIX

    with tempfile.TemporaryDirectory() as tmp, open(Path(tmp) / "stderr.log", "w+") as stderr:
        # A throwaway data dir: the check must not write logs or a database
        # into the runner's home, and must not read a stale one either.
        env = {**os.environ, "TABXTRACT_DATA_DIR": str(Path(tmp) / "data")}
        # stdin is a pipe so the sidecar's watchdog stops it if this process
        # dies; stderr goes to a file so a chatty process never fills a pipe.
        proc = subprocess.Popen([str(binary)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=stderr, text=True, env=env)

        def failure(message: str) -> SidecarCheckError:
            stderr.flush()
            stderr.seek(0)
            return SidecarCheckError(f"{message}\n--- sidecar stderr (tail) ---\n{stderr.read()[-4000:]}")

        try:
            lines: queue.Queue[str | None] = queue.Queue()

            def pump() -> None:
                assert proc.stdout is not None
                for line in proc.stdout:
                    lines.put(line)
                lines.put(None)

            threading.Thread(target=pump, daemon=True).start()

            deadline = time.monotonic() + timeout
            info = None
            while info is None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise failure(f"no handshake within {timeout:.0f}s")
                try:
                    line = lines.get(timeout=remaining)
                except queue.Empty:
                    continue
                if line is None:
                    raise failure(f"the sidecar exited with {proc.wait()} before the handshake")
                if line.startswith(HANDSHAKE_PREFIX):
                    info = json.loads(line[len(HANDSHAKE_PREFIX):])

            request = urllib.request.Request(f"http://127.0.0.1:{info['port']}/api/health",
                                             headers={TOKEN_HEADER: info["token"]})
            while True:
                if proc.poll() is not None:
                    raise failure(f"the sidecar exited with {proc.returncode} after the handshake")
                try:
                    with urllib.request.urlopen(request, timeout=5) as response:
                        health = json.loads(response.read())
                    break
                except (urllib.error.URLError, ConnectionError):
                    if time.monotonic() > deadline:
                        raise failure(f"/api/health did not answer within {timeout:.0f}s") from None
                    time.sleep(0.2)

            if health.get("ok") is not True:
                raise failure(f"/api/health did not report ok: {health}")
            if require_binaries and health.get("missing_binaries"):
                raise failure(f"missing binaries: {health['missing_binaries']}")
            return health
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()


if __name__ == "__main__":
    raise SystemExit(main())
