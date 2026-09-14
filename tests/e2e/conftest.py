"""Fixtures for the end-to-end tests: a real video file and a real sidecar."""
from __future__ import annotations

import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

from tabextract.binaries import ffmpeg_bin
from tabextract.sampling import SAMPLE_FPS
from tests.synthetic import paginated_video, write_frames

from ._deps import need_binary, need_module
from ._sidecar import Sidecar, running_sidecar

# The fewest pages that lay out to more than one A4 sheet.
N_PAGES = 12


@pytest.fixture(scope="session")
def synthetic_video(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A real video file, generated at test time from tests/synthetic.py."""
    ffmpeg = need_binary(ffmpeg_bin())
    root = tmp_path_factory.mktemp("video")
    frames_dir = root / "frames"
    write_frames(paginated_video(n_pages=N_PAGES), frames_dir)

    video = root / "paged.mkv"
    # Lossless on purpose. yuv420p, the usual default, halves the chroma
    # resolution and smears the thin staff lines, so the engine would analyse
    # something other than what the generator drew. ffv1 in bgr0 keeps every
    # pixel. The frame rate equals the engine's sampling rate, so each
    # generated frame is exactly one analysed frame.
    subprocess.run(
        [ffmpeg, "-y", "-loglevel", "error", "-framerate", str(SAMPLE_FPS),
         "-i", str(frames_dir / "frame_%06d.png"),
         "-c:v", "ffv1", "-pix_fmt", "bgr0", str(video)],
        check=True,
    )
    shutil.rmtree(frames_dir)  # ~100 MB of noisy PNGs, no longer needed
    return video


@pytest.fixture(scope="module")
def sidecar(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Sidecar]:
    """One sidecar per test module; tests in a module create their own jobs."""
    for module in ("fastapi", "uvicorn", "websockets", "httpx"):
        need_module(module)
    with running_sidecar(tmp_path_factory.mktemp("sidecar")) as running:
        yield running
