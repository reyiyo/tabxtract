# TabXtract - extracts tablature from video and rebuilds it as a PDF.
# Copyright (C) 2026 TabXtract contributors
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See <https://www.gnu.org/licenses/>.
"""In-process progress broadcasting.

The heavy work runs in threads and the
subscribers are WebSockets on the event loop, so `publish` crosses that
boundary with `call_soon_threadsafe`. There is no buffer and no state
recovery: if nobody is listening the message is lost, and the UI finds out
anyway from the job state.
"""
from __future__ import annotations

import asyncio
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

QUEUE_MAXSIZE = 256


class ProgressBroker:
    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue]] = {}
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    @contextmanager
    def subscribe(self, job_id: str) -> Iterator[asyncio.Queue]:
        queue: asyncio.Queue = asyncio.Queue(maxsize=QUEUE_MAXSIZE)
        self._subscribers.setdefault(job_id, set()).add(queue)
        try:
            yield queue
        finally:
            subs = self._subscribers.get(job_id)
            if subs is not None:
                subs.discard(queue)
                if not subs:
                    self._subscribers.pop(job_id, None)

    def publish(self, job_id: str, stage: str, pct: float, message: str,
                **extra: Any) -> None:
        """Callable from any thread."""
        payload = {"stage": stage, "pct": pct, "message": message,
                   "ts": time.time(), **extra}
        loop = self._loop
        if loop is None or not self._subscribers.get(job_id):
            return
        loop.call_soon_threadsafe(self._deliver, job_id, payload)

    def _deliver(self, job_id: str, payload: dict[str, Any]) -> None:
        for queue in list(self._subscribers.get(job_id, ())):
            try:
                queue.put_nowait(payload)
            except asyncio.QueueFull:
                # A slow consumer must not stall the pipeline, so the message
                # is dropped. The next one carries a higher pct anyway.
                pass


broker = ProgressBroker()
