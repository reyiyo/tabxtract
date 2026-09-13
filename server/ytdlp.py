# TabXtract - extracts tablature from video and rebuilds it as a PDF.
# Copyright (C) 2026 TabXtract contributors
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See <https://www.gnu.org/licenses/>.
"""URL ingestion with yt-dlp.

yt-dlp is invoked as an external binary, never frozen inside the PyInstaller
bundle: YouTube breaks yt-dlp every few weeks and the user has to be able to
update it without waiting for a release of ours. The resolution order puts the
user-updated copy in the data directory first, because that directory is
writable, unlike the app bundle.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import bin_dir

# No audio: the engine only looks at pixels, and video-only shrinks the download.
DEFAULT_FORMAT = "bv*[height<={h}]/b[height<={h}]/bv*/b"

RELEASE_ASSET = {
    "darwin": "yt-dlp_macos",
    "win32": "yt-dlp.exe",
}
LATEST_RELEASE = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/{asset}"

UPDATE_HINT = ("If the video exists and is public, the likeliest cause is an "
               "out-of-date yt-dlp: YouTube changes often and breaks it. Try "
               "'Update yt-dlp' in Preferences.")


class YtdlpError(RuntimeError):
    """A download error already translated into something the user can act on."""

    def __init__(self, message: str, kind: str, hint: str = "") -> None:
        super().__init__(message)
        self.kind = kind
        self.hint = hint


class YtdlpMissing(YtdlpError):
    def __init__(self) -> None:
        super().__init__(
            "yt-dlp was not found.", "missing",
            "The app ships with it bundled; if you got here, try 'Update yt-dlp' in "
            "Preferences to download a copy into the data directory.")


@dataclass
class VideoFormat:
    format_id: str
    height: int | None
    fps: float | None
    ext: str
    filesize: int | None
    note: str


@dataclass
class VideoInfo:
    url: str
    title: str
    duration: float | None
    uploader: str | None
    thumbnail: str | None
    formats: list[VideoFormat]


def _user_copy() -> Path:
    name = "yt-dlp.exe" if os.name == "nt" else "yt-dlp"
    return bin_dir() / name


def resolve_binary() -> str | None:
    """User-updated copy > the one bundled with the app > PATH."""
    user = _user_copy()
    if user.is_file():
        return str(user)
    bundled = os.environ.get("TABXTRACT_YTDLP")
    if bundled and Path(bundled).is_file():
        return bundled
    return shutil.which("yt-dlp")


def _binary() -> str:
    found = resolve_binary()
    if found is None:
        raise YtdlpMissing()
    return found


def version() -> dict[str, Any]:
    binary = resolve_binary()
    if binary is None:
        return {"available": False, "version": None, "path": None, "updatable": True}
    out = subprocess.run([binary, "--version"], capture_output=True, text=True, errors="replace", check=False)
    return {
        "available": out.returncode == 0,
        "version": out.stdout.strip() or None,
        "path": binary,
        "updatable": True,
    }


def _classify(stderr: str) -> YtdlpError:
    low = stderr.lower()
    if "private video" in low:
        return YtdlpError("The video is private.", "private",
                          "Only the account owner can watch it. If you have the file, "
                          "open it as a local file instead.")
    if "age" in low and ("confirm your age" in low or "age-restricted" in low or "age restricted" in low):
        return YtdlpError("The video is age-restricted.", "age_restricted",
                          "YouTube requires a signed-in session for it, and this app "
                          "handles no credentials. Download it separately and open it "
                          "as a local file.")
    if "video unavailable" in low or "removed by the uploader" in low or "does not exist" in low:
        return YtdlpError("The video is not available.", "unavailable",
                          "It may have been deleted, or be blocked in your country. "
                          "Check the URL.")
    if ("sign in to confirm" in low or "nsig extraction" in low or "unable to extract" in low
            or "http error 403" in low or "player response" in low):
        return YtdlpError("YouTube refused the download.", "outdated", UPDATE_HINT)
    tail = stderr.strip().splitlines()[-1] if stderr.strip() else "no detail"
    return YtdlpError(f"The download failed: {tail}", "unknown", UPDATE_HINT)


def normalize_url(url: str) -> str:
    """Only http(s) links reach yt-dlp.

    A bare "youtube.com/watch?v=..." gets https:// prepended, as a browser
    would. Anything else is refused: another scheme (file://) would have
    yt-dlp read local files. The call sites also put `--` before the URL,
    because a value starting with "-" is otherwise parsed as an option, and
    `--exec` runs arbitrary commands.
    """
    candidate = url.strip()
    if "://" not in candidate:
        candidate = "https://" + candidate
    parts = urllib.parse.urlsplit(candidate)
    if parts.scheme.lower() not in ("http", "https") or not parts.netloc:
        raise YtdlpError("That does not look like a video link.", "invalid_url",
                         "Paste an address starting with https://.")
    return candidate


def _expected_sha256(sums: str, asset: str) -> str:
    for line in sums.splitlines():
        digest, _, name = line.strip().partition("  ")
        if name == asset:
            return digest.lower()
    raise YtdlpError(f"The yt-dlp release publishes no checksum for {asset}.", "update_failed")


def probe(url: str) -> VideoInfo:
    """Metadata and available tracks, before downloading a single byte."""
    url = normalize_url(url)
    out = subprocess.run(
        [_binary(), "--ignore-config", "-J", "--no-playlist", "--no-warnings", "--", url],
        capture_output=True, text=True, errors="replace", check=False,
    )
    if out.returncode != 0:
        raise _classify(out.stderr)
    info = json.loads(out.stdout)

    formats: list[VideoFormat] = []
    for f in info.get("formats", []):
        if f.get("vcodec") in (None, "none"):
            continue  # audio only
        formats.append(VideoFormat(
            format_id=str(f.get("format_id")),
            height=f.get("height"),
            fps=f.get("fps"),
            ext=f.get("ext") or "",
            filesize=f.get("filesize") or f.get("filesize_approx"),
            note=f.get("format_note") or "",
        ))
    # Best quality first, and one entry per height: the quality selector in
    # the UI is a list of resolutions, not of codecs.
    formats.sort(key=lambda f: (f.height or 0, f.fps or 0), reverse=True)
    seen: set[int | None] = set()
    unique: list[VideoFormat] = []
    for f in formats:
        if f.height in seen:
            continue
        seen.add(f.height)
        unique.append(f)

    return VideoInfo(
        url=url,
        title=info.get("title") or url,
        duration=info.get("duration"),
        uploader=info.get("uploader"),
        thumbnail=info.get("thumbnail"),
        formats=unique,
    )


def download(url: str, dest_dir: Path, format_id: str | None = None,
             max_height: int = 1080,
             progress: Callable[[float, str], None] | None = None,
             should_cancel: Callable[[], bool] | None = None) -> Path:
    """Download the video into `dest_dir` and return the file path.

    `progress` receives (0..1 fraction, text). If `should_cancel` returns True
    the process is killed: a long download has to be cancellable.
    """
    url = normalize_url(url)
    dest_dir.mkdir(parents=True, exist_ok=True)
    selector = format_id or DEFAULT_FORMAT.format(h=max_height)
    cmd = [
        _binary(), "--ignore-config", "--no-playlist", "--no-warnings", "--newline",
        "-f", selector,
        "--progress-template", "download:TABX %(progress.downloaded_bytes)s "
                               "%(progress.total_bytes)s %(progress.total_bytes_estimate)s",
        "-o", str(dest_dir / "source.%(ext)s"),
        "--", url,
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, errors="replace")
    assert proc.stdout is not None
    cancelled = False
    for line in proc.stdout:
        if should_cancel is not None and should_cancel():
            cancelled = True
            proc.kill()
            break
        if not line.startswith("TABX ") or progress is None:
            continue
        _, done, total, estimate = line.split()
        try:
            downloaded = float(done)
            size = float(total if total not in ("NA", "None") else estimate)
        except ValueError:
            continue
        if size > 0:
            progress(min(downloaded / size, 1.0),
                     f"downloading: {downloaded / 1e6:.0f} of {size / 1e6:.0f} MB")

    stderr = proc.stderr.read() if proc.stderr else ""
    code = proc.wait()
    if cancelled:
        shutil.rmtree(dest_dir, ignore_errors=True)
        raise YtdlpError("Download cancelled.", "cancelled")
    if code != 0:
        raise _classify(stderr)

    files = sorted(dest_dir.glob("source.*"))
    if not files:
        raise YtdlpError("yt-dlp exited cleanly but left no file behind.", "unknown",
                         UPDATE_HINT)
    return files[0]


def update() -> dict[str, Any]:
    """Update yt-dlp without touching the app bundle.

    Frozen with PyInstaller there is no pip and no writable site-packages, so
    the official binary is downloaded into the data directory, which is where
    `resolve_binary` looks first. Running from source there is a pip, and
    using it there avoids leaving two different copies lying around.
    """
    if not getattr(sys, "frozen", False) and shutil.which("pip"):
        out = subprocess.run([sys.executable, "-m", "pip", "install", "-U", "yt-dlp"],
                             capture_output=True, text=True, errors="replace", check=False)
        if out.returncode != 0:
            raise YtdlpError(f"pip failed: {out.stderr.strip().splitlines()[-1:]}", "update_failed")
        return {"method": "pip", **version()}

    asset = RELEASE_ASSET.get(sys.platform, "yt-dlp")
    target = _user_copy()
    tmp = target.with_suffix(target.suffix + ".part")
    digest = hashlib.sha256()
    try:
        with urllib.request.urlopen(LATEST_RELEASE.format(asset="SHA2-256SUMS"), timeout=60) as resp:
            expected = _expected_sha256(resp.read().decode(), asset)
        with urllib.request.urlopen(LATEST_RELEASE.format(asset=asset), timeout=60) as resp, \
                open(tmp, "wb") as f:
            for chunk in iter(lambda: resp.read(1 << 20), b""):
                digest.update(chunk)
                f.write(chunk)
    except OSError as exc:
        tmp.unlink(missing_ok=True)
        raise YtdlpError(f"Could not download yt-dlp: {exc}", "update_failed",
                         "Check your internet connection.") from exc
    # The binary is about to be executed, so a truncated or tampered download
    # must never replace the working copy. The checksum comes from the same
    # release: it catches corruption and mirror tampering, not a compromised
    # release.
    if digest.hexdigest() != expected:
        tmp.unlink(missing_ok=True)
        raise YtdlpError("The downloaded yt-dlp does not match its published checksum, "
                         "so it was discarded.", "update_failed",
                         "Try again in a few minutes: a new release may have been "
                         "published mid-download.")
    tmp.replace(target)
    target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return {"method": "download", **version()}
