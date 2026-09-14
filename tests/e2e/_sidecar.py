"""The sidecar as a separate process, the way the desktop app runs it.

It is found through the same stdout handshake Tauri reads, and every helper
waits on observable state -- job status, progress messages -- with a deadline,
never on a fixed sleep.
"""
from __future__ import annotations

import json
import os
import queue
import secrets
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
STARTUP_TIMEOUT = 30.0
JOB_TIMEOUT = 120.0
POLL_INTERVAL = 0.2

OWN_TOKEN: Any = object()  # sentinel: authenticate with the sidecar's own token


@dataclass
class Sidecar:
    port: int
    token: str
    token_header: str
    data_dir: Path
    stderr_path: Path

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def client(self, token: str | None = OWN_TOKEN):
        import httpx

        headers = {}
        chosen = self.token if token is OWN_TOKEN else token
        if chosen is not None:
            headers[self.token_header] = chosen
        return httpx.Client(base_url=self.base_url, headers=headers, timeout=15.0)

    def progress_url(self, job_id: str, token: str | None = OWN_TOKEN) -> str:
        """The WebSocket carries the token in the query, as the frontend does:
        browsers cannot set headers on it."""
        url = f"ws://127.0.0.1:{self.port}/api/jobs/{job_id}/progress"
        chosen = self.token if token is OWN_TOKEN else token
        return url if chosen is None else f"{url}?token={chosen}"

    def stderr_tail(self, lines: int = 40) -> str:
        text = self.stderr_path.read_text(errors="replace") if self.stderr_path.exists() else ""
        return "--- sidecar stderr (tail) ---\n" + "\n".join(text.splitlines()[-lines:])

    def create_job(self, http, video: Path) -> str:
        response = http.post("/api/jobs", json={"path": str(video)})
        assert response.status_code == 200, response.text
        return response.json()["id"]

    def wait_for_status(self, http, job_id: str, wanted: str, timeout: float = JOB_TIMEOUT) -> dict:
        deadline = time.monotonic() + timeout
        job: dict = {}
        while time.monotonic() < deadline:
            job = http.get(f"/api/jobs/{job_id}").json()
            if job["status"] == wanted:
                return job
            if job["status"] == "failed" and wanted != "failed":
                pytest.fail(f"job {job_id} failed: {job['error']}\n{self.stderr_tail()}")
            time.sleep(POLL_INTERVAL)
        pytest.fail(f"job {job_id} did not reach '{wanted}' within {timeout:.0f}s "
                    f"(last status: {job.get('status')})\n{self.stderr_tail()}")

    def wait_for_idle_worker(self, http, video: Path) -> None:
        """Block until everything already queued on the processing pool has run.

        The pool has a single worker and runs jobs in submission order, so a
        job submitted now can only finish after all of them. Waiting for it is
        a deterministic barrier where polling a status is not: a job analysed
        twice reads "analyzed" in the gap between its two runs.
        """
        barrier = self.create_job(http, video)
        self.wait_for_status(http, barrier, "analyzed")
        http.delete(f"/api/jobs/{barrier}")


def read_progress_until(ws, stage: str, timeout: float = JOB_TIMEOUT) -> list[dict]:
    """Read progress messages until one with `stage` arrives; return them all."""
    messages: list[dict] = []
    deadline = time.monotonic() + timeout
    while (remaining := deadline - time.monotonic()) > 0:
        try:
            raw = ws.recv(timeout=remaining)
        except TimeoutError:
            break
        message = json.loads(raw)
        messages.append(message)
        if message["stage"] == stage:
            return messages
    pytest.fail(f"no '{stage}' progress message within {timeout:.0f}s; "
                f"received stages {[m['stage'] for m in messages]}")


def _read_handshake(proc: subprocess.Popen, prefix: str, stderr_path: Path) -> dict:
    """Read stdout until the handshake line, with a deadline.

    A pump thread owns stdout for the life of the process: reading it with a
    timeout needs one, and it keeps the pipe drained so the sidecar never
    blocks on a full buffer.
    """
    lines: queue.Queue[str | None] = queue.Queue()

    def pump() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            lines.put(line)
        lines.put(None)

    threading.Thread(target=pump, daemon=True).start()
    deadline = time.monotonic() + STARTUP_TIMEOUT
    while (remaining := deadline - time.monotonic()) > 0:
        try:
            line = lines.get(timeout=remaining)
        except queue.Empty:
            break
        if line is None:
            pytest.fail(f"the sidecar exited before the handshake\n{stderr_path.read_text()[-4000:]}")
        if line.startswith(prefix):
            return json.loads(line[len(prefix):])
    pytest.fail(f"no handshake within {STARTUP_TIMEOUT:.0f}s\n{stderr_path.read_text()[-4000:]}")


def _wait_healthy(sidecar: Sidecar, proc: subprocess.Popen) -> None:
    import httpx

    deadline = time.monotonic() + STARTUP_TIMEOUT
    with sidecar.client() as http:
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                pytest.fail(f"the sidecar exited with {proc.returncode}\n{sidecar.stderr_tail()}")
            try:
                if http.get("/api/health").status_code == 200:
                    return
            except httpx.TransportError:
                pass
            time.sleep(POLL_INTERVAL)
    pytest.fail(f"/api/health did not answer within {STARTUP_TIMEOUT:.0f}s\n{sidecar.stderr_tail()}")


@contextmanager
def running_sidecar(root: Path) -> Iterator[Sidecar]:
    """Start `python -m server`, isolated under `root`, and stop it afterwards.

    TABXTRACT_DATA_DIR and TMPDIR point inside `root`, so the run never
    touches the user's job history, preferences or temp directory.
    """
    from server.__main__ import HANDSHAKE_PREFIX
    from server.main import TOKEN_HEADER

    data_dir, tmp_dir = root / "data", root / "tmp"
    data_dir.mkdir()
    tmp_dir.mkdir()
    stderr_path = root / "sidecar-stderr.log"
    token = secrets.token_urlsafe(24)
    env = {**os.environ, "TABXTRACT_DATA_DIR": str(data_dir), "TMPDIR": str(tmp_dir)}

    with open(stderr_path, "w") as stderr:
        # stdin is a pipe on purpose: the sidecar exits when it closes, so a
        # killed pytest does not leave an orphaned server behind.
        proc = subprocess.Popen(
            [sys.executable, "-m", "server", "--port", "0", "--token", token],
            cwd=REPO_ROOT, env=env, text=True,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=stderr,
        )
    try:
        info = _read_handshake(proc, HANDSHAKE_PREFIX, stderr_path)
        assert info["token"] == token, "the handshake must echo the token it was given"
        sidecar = Sidecar(port=info["port"], token=info["token"], token_header=TOKEN_HEADER,
                          data_dir=data_dir, stderr_path=stderr_path)
        _wait_healthy(sidecar, proc)
        yield sidecar
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        if proc.stdin:
            proc.stdin.close()
