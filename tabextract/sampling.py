"""Stage 1 - Frame sampling via ffmpeg."""
from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np

from .binaries import ffmpeg_bin, ffprobe_bin

ProgressFn = Callable[[float], None]

SAMPLE_FPS = 2
MAX_HEIGHT = 1080


def probe_resolution(video_path: Path) -> tuple[int, int]:
    out = subprocess.run(
        [
            ffprobe_bin(), "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-of", "csv=p=0:s=x", str(video_path),
        ],
        capture_output=True, text=True, check=True,
    )
    w, h = out.stdout.strip().split("x")
    return int(w), int(h)


def probe_duration(video_path: Path) -> float:
    """Duration in seconds, or 0.0 when the container does not declare it."""
    out = subprocess.run(
        [
            ffprobe_bin(), "-v", "error", "-show_entries", "format=duration",
            "-of", "csv=p=0", str(video_path),
        ],
        capture_output=True, text=True, check=False,
    )
    try:
        return float(out.stdout.strip())
    except ValueError:
        return 0.0


def extract_frames(video_path: Path, out_dir: Path, fps: int = SAMPLE_FPS,
                   progress: ProgressFn | None = None) -> list[Path]:
    """Extract frames into `out_dir` at `fps` frames per second.

    Native resolution. If the video is taller than 1080p it is scaled down to
    1080p (Failure mode 6: never scale up, only down).

    `progress` receives a 0..1 fraction of the decoding progress. On long
    videos this stage takes minutes, so the desktop app draws a bar from it;
    without a callback the behaviour is the usual one.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    existing = sorted(out_dir.glob("frame_*.png"))
    if existing:
        return existing

    w, h = probe_resolution(video_path)
    vf = f"fps={fps}"
    if h > MAX_HEIGHT:
        vf += f",scale=-2:{MAX_HEIGHT}"

    pattern = str(out_dir / "frame_%06d.png")
    # -fps_mode passthrough, not the older -vsync 0: ffmpeg 9 removed -vsync
    # and rejects the whole argument list, so the bundled build failed before
    # reading a single frame. The intent is the same - the fps filter already
    # decides the output rate, and nothing here may duplicate or drop frames.
    # -fps_mode needs ffmpeg >= 5.0; the bundle ships 9, and the .deb depends
    # on the distribution's ffmpeg, which is >= 5.1 everywhere the glibc floor
    # already allows.
    cmd = [
        ffmpeg_bin(), "-y", "-i", str(video_path),
        "-vf", vf, "-fps_mode", "passthrough",
        pattern,
    ]
    if progress is None:
        subprocess.run(cmd, capture_output=True, text=True, check=True)
    else:
        _run_with_progress(cmd, probe_duration(video_path), progress)
    return sorted(out_dir.glob("frame_*.png"))


def _run_with_progress(cmd: list[str], duration: float, progress: ProgressFn) -> None:
    """Run ffmpeg reading `-progress`, which writes `out_time_us=N` per line.

    When the container declares no duration there is no denominator for the
    percentage; in that case nothing is emitted and the bar stays
    indeterminate, which beats inventing a number.
    """
    proc = subprocess.Popen(
        [*cmd[:1], "-nostats", "-progress", "pipe:1", *cmd[1:]],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        key, _, value = line.strip().partition("=")
        if key in ("out_time_us", "out_time_ms") and duration > 0:
            scale = 1e6 if key == "out_time_us" else 1e3
            try:
                seconds = int(value) / scale
            except ValueError:
                continue
            progress(min(seconds / duration, 1.0))
    stderr = proc.stderr.read() if proc.stderr else ""
    if proc.wait() != 0:
        raise subprocess.CalledProcessError(proc.returncode, cmd, stderr=stderr)
    progress(1.0)


@dataclass
class FrameCache:
    """LRU cache of frames read from disk (870 frames do not fit in memory)."""

    paths: list[Path]
    max_cached: int = 64

    def __post_init__(self) -> None:
        self._reader = lru_cache(maxsize=self.max_cached)(self._read)

    def _read(self, idx: int) -> np.ndarray:
        img = cv2.imread(str(self.paths[idx]), cv2.IMREAD_COLOR)
        if img is None:
            raise OSError(f"could not read frame {self.paths[idx]}")
        return img

    def __len__(self) -> int:
        return len(self.paths)

    def __getitem__(self, idx: int) -> np.ndarray:
        return self._reader(idx)

    def gray(self, idx: int) -> np.ndarray:
        return cv2.cvtColor(self[idx], cv2.COLOR_BGR2GRAY)

    def slice(self, start: int, end_inclusive: int) -> FrameCache:
        return FrameCache(self.paths[start:end_inclusive + 1], max_cached=self.max_cached)
