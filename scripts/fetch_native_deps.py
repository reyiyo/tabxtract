#!/usr/bin/env python3
# TabXtract - extracts tablature from video and rebuilds it as a PDF.
# Copyright (C) 2026 TabXtract contributors
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See <https://www.gnu.org/licenses/>.
"""Download the native binaries that ship with the app.

They go into `src-tauri/native/`, which `tauri.conf.json` includes as a
resource. At runtime the Tauri shell looks for each one on the user's PATH
first and only then here (see src-tauri/src/main.rs).

What gets downloaded and why:

- **ffmpeg and ffprobe**: static builds. On Linux and Windows they come from
  BtbN (GPL, which is no problem for a GPL-3.0 app); on macOS from
  martin-riedl.de. If it cannot be resolved the script fails: without ffmpeg
  the app opens and decodes nothing.

Every download is pinned to a fixed version and checked against a SHA-256
recorded in this file before anything is written: these binaries ship inside
the app and run on the user's machine, so HTTPS to the host is not enough.
- **yt-dlp**: the official binary, not frozen with PyInstaller. The "Update
  yt-dlp" button later replaces this copy with a newer one in the user's data
  directory, which is writable.
- **eng.traineddata** from `tessdata_fast`, for the bar-number OCR.
  `osd.traineddata` is NOT included: it detects orientation and script, which
  this project does not use.

The tesseract binary itself cannot be downloaded from one source covering all
three platforms: it is taken from the runner's PATH with
--tesseract-from-path. On macOS and Windows that copy is not relocatable, so
it is not bundled there at all; the app uses the system tesseract and, when
there is none, degrades without that verification check.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import os
import platform
import shutil
import stat
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NATIVE = ROOT / "src-tauri" / "native"

# To bump a pin, change the URL and paste the new digest: GitHub shows it on
# each release asset, and martin-riedl.de publishes a .sha256 next to each zip.
#
# ffmpeg is the release branch (9.0), not master: it decodes videos downloaded
# from the internet, so it gets the builds that receive security backports.
#
# BtbN publishes static GPL builds for Linux and Windows, one archive with both
# binaries. Its daily builds are pruned after a couple of weeks but the last
# one of each month is kept, so the pin points at one of those. It has nothing
# for macOS: those come from martin-riedl.de, static builds, one zip per binary.
BTBN = "https://github.com/BtbN/FFmpeg-Builds/releases/download/autobuild-2026-08-31-13-27/{name}"
MARTIN_RIEDL = "https://ffmpeg.martin-riedl.de/download/macos/{build}/{name}.zip"

# (archive kind, url, sha256) per platform.
FFMPEG_SOURCES: dict[tuple[str, str], list[tuple[str, str, str]]] = {
    ("Linux", "x86_64"): [
        ("tar.xz", BTBN.format(name="ffmpeg-n9.0.1-11-ge47273f4d9-linux64-gpl-9.0.tar.xz"),
         "182c1b509720e939bb47bfb47dc29cc0c298640401128e3dce8627d10707eb5a")],
    ("Linux", "aarch64"): [
        ("tar.xz", BTBN.format(name="ffmpeg-n9.0.1-11-ge47273f4d9-linuxarm64-gpl-9.0.tar.xz"),
         "e2dd447c8a47849c5812d87e54a47b20ae0f3603d38989440f4a5fe1af8755b1")],
    ("Windows", "AMD64"): [
        ("zip", BTBN.format(name="ffmpeg-n9.0.1-11-ge47273f4d9-win64-gpl-9.0.zip"),
         "ec9db2cda1f5894ab95446076ad8bf49379db4b53c02e778ad3b49adf91fec83")],
    ("Darwin", "arm64"): [
        ("zip", MARTIN_RIEDL.format(build="arm64/1787073674_9.0.1", name="ffmpeg"),
         "8287a1b2229e05eb41859f073e18e6c52c60a778f2f5e6881070fe51b79407fe"),
        ("zip", MARTIN_RIEDL.format(build="arm64/1787073674_9.0.1", name="ffprobe"),
         "102a26b8940a053298d9929bfaae71e4b6ef65ba5f19a99a88c433108560741a")],
    ("Darwin", "x86_64"): [
        ("zip", MARTIN_RIEDL.format(build="amd64/1787081194_9.0.1", name="ffmpeg"),
         "5bdead62ff504ab9b447cc72b212c4fb481e3f7de5877d427a51bee8136dda40"),
        ("zip", MARTIN_RIEDL.format(build="amd64/1787081194_9.0.1", name="ffprobe"),
         "34511bbcf1988ad2886023bf5ace4f44cf62e6defeb3d194d6f7619e5b061f7f")],
}

# yt-dlp_macos is a universal2 binary; the separate _legacy build for Intel no
# longer exists. The in-app updater moves past this pin on its own.
YTDLP_URL = "https://github.com/yt-dlp/yt-dlp/releases/download/2026.08.19/{asset}"
YTDLP_ASSETS: dict[tuple[str, str], tuple[str, str]] = {
    ("Darwin", "arm64"): ("yt-dlp_macos", "0f192b7ec147ab6288885d6351d9ab67367640029b4377576ef46dd79cf7b202"),
    ("Darwin", "x86_64"): ("yt-dlp_macos", "0f192b7ec147ab6288885d6351d9ab67367640029b4377576ef46dd79cf7b202"),
    ("Windows", "AMD64"): ("yt-dlp.exe", "66674953fe251b89f4d08c5f0e35e0728679bd67ab3d7d05c0562af101dd3e7a"),
    ("Linux", "x86_64"): ("yt-dlp_linux", "58162f9bfdc27458ea47bfcb311cf47028f17d8154a8bf7d689861d46399230a"),
    ("Linux", "aarch64"): ("yt-dlp_linux_aarch64",
                           "b16e4dab368a816cd05d477d698a605a6ae87ccee1c8ffd38fa21d7254141fcc"),
}

TESSDATA_URL = ("https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/"
                "87416418657359cb625c412a48b6e1d6d41c29bd/eng.traineddata")
TESSDATA_SHA256 = "60babc04af8477eaea5877fd0b1e67c1d1b46fa1d1ce8f8a7be384279ace2e54"

BINARY_NAMES = ("ffmpeg", "ffprobe")


def _download(url: str, sha256: str) -> bytes:
    print(f"  downloading {url}")
    with urllib.request.urlopen(url, timeout=300) as resp:
        blob = resp.read()
    actual = hashlib.sha256(blob).hexdigest()
    if actual != sha256:
        raise SystemExit(
            f"error: checksum mismatch for {url}\n  expected {sha256}\n  got      {actual}\n"
            "Nothing from it was written. If the pin was bumped on purpose, update the digest.")
    return blob


def _make_executable(path: Path) -> None:
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _extract_named(blob: bytes, kind: str, wanted: tuple[str, ...], dest: Path) -> list[str]:
    """Pull the files whose base name is in `wanted` out of a tar/zip."""
    found = []
    if kind == "zip":
        archive = zipfile.ZipFile(io.BytesIO(blob))
        members = [(m, Path(m).name) for m in archive.namelist()]
        for member, name in members:
            base = name[:-4] if name.endswith(".exe") else name
            if base in wanted:
                target = dest / name
                target.write_bytes(archive.read(member))
                _make_executable(target)
                found.append(name)
    else:
        tar = tarfile.open(fileobj=io.BytesIO(blob), mode="r:xz")
        for entry in tar.getmembers():
            if not entry.isfile():
                continue
            name = Path(entry.name).name
            if name in wanted:
                extracted = tar.extractfile(entry)
                if extracted is None:
                    continue
                target = dest / name
                target.write_bytes(extracted.read())
                _make_executable(target)
                found.append(name)
    return found


def fetch_ffmpeg(dest: Path, from_path: str | None) -> None:
    if from_path:
        source = Path(from_path)
        for name in BINARY_NAMES:
            candidate = source if source.is_file() else source / name
            if not candidate.is_file():
                print(f"  warning: {name} not found in {source}", file=sys.stderr)
                continue
            shutil.copy2(candidate, dest / candidate.name)
            _make_executable(dest / candidate.name)
            print(f"  copied {candidate}")
        return

    key = (platform.system(), platform.machine())
    sources = FFMPEG_SOURCES.get(key)
    if sources is None:
        raise SystemExit(
            f"error: no known ffmpeg source for {key}. Pass --ffmpeg-from-path "
            "with a static build, or --skip ffmpeg if you know the app will find "
            "it on PATH.")

    found: list[str] = []
    for kind, url, sha256 in sources:
        found += _extract_named(_download(url, sha256), kind, BINARY_NAMES, dest)
    print(f"  ffmpeg: {sorted(found) or 'nothing extracted'}")


def fetch_ytdlp(dest: Path) -> None:
    pinned = YTDLP_ASSETS.get((platform.system(), platform.machine()))
    if pinned is None:
        print("  warning: no yt-dlp binary for this platform", file=sys.stderr)
        return
    asset, sha256 = pinned
    name = "yt-dlp.exe" if os.name == "nt" else "yt-dlp"
    target = dest / name
    target.write_bytes(_download(YTDLP_URL.format(asset=asset), sha256))
    _make_executable(target)
    print(f"  yt-dlp: {target.name}")


def fetch_tessdata(dest: Path) -> None:
    tessdata = dest / "tessdata"
    tessdata.mkdir(parents=True, exist_ok=True)
    (tessdata / "eng.traineddata").write_bytes(_download(TESSDATA_URL, TESSDATA_SHA256))
    size = (tessdata / "eng.traineddata").stat().st_size / 1e6
    print(f"  tessdata: eng.traineddata ({size:.1f} MB, no osd)")


def copy_tesseract(dest: Path, from_path: str | None) -> None:
    """Copy the tesseract binary, only when explicitly asked for.

    Copying the runner's tesseract works on Linux, where the .deb declares it
    as a dependency anyway, but on macOS and Windows the binary is dynamically
    linked against libtesseract and leptonica: copying only the executable
    produces something that does not start on the user's machine and, worse,
    gives the impression the OCR is bundled. So nothing is copied there unless
    whoever packages passes a build they know is relocatable.

    Without tesseract the engine degrades: the bar-number continuity check is
    lost and the PDF comes out all the same.
    """
    if from_path is None and platform.system() in ("Darwin", "Windows"):
        print("  tesseract: not bundled on this platform (the system binary is "
              "not relocatable). The bar-number check reports as unavailable when "
              "the user has no tesseract installed.")
        return

    source = Path(from_path) if from_path else None
    if source is None:
        found = shutil.which("tesseract")
        source = Path(found) if found else None
    if source is None or not source.is_file():
        print("  warning: no tesseract binary. The app will use the system one "
              "and, failing that, reports the bar-number check as unavailable.",
              file=sys.stderr)
        return
    target = dest / source.name
    shutil.copy2(source, target)
    _make_executable(target)
    print(f"  tesseract: copied from {source}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ffmpeg-from-path", default=None,
                        help="directory (or binary) holding a ready static ffmpeg")
    parser.add_argument("--tesseract-from-path", default=None,
                        help="tesseract binary to copy; defaults to the one on PATH")
    parser.add_argument("--skip", nargs="*", default=[],
                        choices=["ffmpeg", "ytdlp", "tessdata", "tesseract"])
    args = parser.parse_args()

    NATIVE.mkdir(parents=True, exist_ok=True)
    print(f"native binaries -> {NATIVE}")

    if "ffmpeg" not in args.skip:
        fetch_ffmpeg(NATIVE, args.ffmpeg_from_path)
        # Without ffmpeg the app decodes nothing. A warning here gets lost in
        # the build noise and the failure only shows up on the user's machine,
        # with the app open and unable to process a single video.
        missing = [n for n in BINARY_NAMES
                   if not ((NATIVE / n).is_file() or (NATIVE / f"{n}.exe").is_file())]
        if missing:
            raise SystemExit(
                f"error: {', '.join(missing)} is required and was not bundled. "
                "Use --ffmpeg-from-path, or --skip ffmpeg when the package declares "
                "ffmpeg as a system dependency, as the .deb does.")
    if "ytdlp" not in args.skip:
        fetch_ytdlp(NATIVE)
    if "tessdata" not in args.skip:
        fetch_tessdata(NATIVE)
    if "tesseract" not in args.skip:
        copy_tesseract(NATIVE, args.tesseract_from_path)

    total = sum(f.stat().st_size for f in NATIVE.rglob("*") if f.is_file()) / 1e6
    print(f"total bundled: {total:.0f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
