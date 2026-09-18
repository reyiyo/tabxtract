"""A progress socket the client closed must not keep the sidecar alive.

The handler used to wait only on the broker's queue, so a client that went
away was noticed on the next published message -- never, for a job that
published no more. The task and its subscription stayed, and uvicorn's
graceful shutdown waited for them: terminating the sidecar hung. Tauri
terminates it on window close, so that is a window that closes over a process
that stays.
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from ._deps import need_module
from ._sidecar import running_sidecar

pytestmark = pytest.mark.e2e

connect = need_module("websockets.sync.client").connect

UNKNOWN_ID = "0" * 32  # any id subscribes; this test needs no job at all
SHUTDOWN_BUDGET = 10.0


def test_a_closed_progress_socket_does_not_delay_shutdown(tmp_path: Path):
    root = tmp_path / "sidecar"
    root.mkdir()
    with running_sidecar(root) as sidecar:
        # Opened and closed cleanly, the way leaving a progress screen does.
        with connect(sidecar.progress_url(UNKNOWN_ID), open_timeout=10):
            pass

        started = time.monotonic()
        sidecar.proc.terminate()
        sidecar.proc.wait(timeout=SHUTDOWN_BUDGET)
        assert time.monotonic() - started < SHUTDOWN_BUDGET
