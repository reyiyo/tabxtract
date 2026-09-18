"""Fixtures for the end-to-end tests: a real video file and a real sidecar."""
from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from tabextract.binaries import ffmpeg_bin
from tests.synthetic_video import write_video

from ._deps import need_binary, need_module
from ._sidecar import Sidecar, running_sidecar


@pytest.fixture(scope="session")
def synthetic_video(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A real video file, generated at test time from tests/synthetic.py."""
    need_binary(ffmpeg_bin())
    return write_video(tmp_path_factory.mktemp("video") / "paged.mkv")


@pytest.fixture(scope="module")
def sidecar(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Sidecar]:
    """One sidecar per test module; tests in a module create their own jobs."""
    for module in ("fastapi", "uvicorn", "websockets", "httpx"):
        need_module(module)
    with running_sidecar(tmp_path_factory.mktemp("sidecar")) as running:
        yield running
