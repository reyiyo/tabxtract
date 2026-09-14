"""Edge cases of the local API, each decided explicitly against the real sidecar."""
from __future__ import annotations

from pathlib import Path

import pytest

from ._deps import need_module
from ._sidecar import read_progress_until

pytestmark = pytest.mark.e2e

connect = need_module("websockets.sync.client").connect
InvalidStatus = need_module("websockets.exceptions").InvalidStatus

UNKNOWN_ID = "0" * 32  # well-formed, never issued


@pytest.mark.parametrize("method, suffix, body", [
    ("GET", "", None),
    ("POST", "/analyze", None),
    ("PATCH", "/region", {}),
    ("POST", "/render", {}),
    ("GET", "/report", None),
])
def test_unknown_job_is_not_found(sidecar, method, suffix, body):
    with sidecar.client() as http:
        response = http.request(method, f"/api/jobs/{UNKNOWN_ID}{suffix}", json=body)
    assert response.status_code == 404, response.text


def test_malformed_job_id_is_rejected_by_validation(sidecar):
    """Job ids also name a temporary directory, so only uuid4 hex gets past
    path validation. That answers 422, before any lookup could say 404."""
    with sidecar.client() as http:
        assert http.get("/api/jobs/not-a-job-id").status_code == 422


def test_delete_and_cancel_of_an_unknown_job_are_idempotent(sidecar):
    with sidecar.client() as http:
        assert http.delete(f"/api/jobs/{UNKNOWN_ID}").status_code == 200
        assert http.post(f"/api/jobs/{UNKNOWN_ID}/cancel").status_code == 200
        assert http.get(f"/api/jobs/{UNKNOWN_ID}").status_code == 404


@pytest.mark.parametrize("token", [None, "not-the-token"])
def test_http_without_the_token_is_unauthorised(sidecar, token):
    with sidecar.client(token=token) as http:
        response = http.get("/api/health")
    assert response.status_code == 401
    assert response.json() == {"detail": "invalid token"}


@pytest.mark.parametrize("token", [None, "not-the-token"])
def test_websocket_without_the_token_is_refused_at_the_handshake(sidecar, token):
    """TokenMiddleware closes with 4401 before accepting the socket. uvicorn
    turns a close before accept into a rejected handshake, so what a client
    observes is HTTP 403 -- a 4401 close frame never reaches it."""
    with pytest.raises(InvalidStatus) as refused:
        with connect(sidecar.progress_url(UNKNOWN_ID, token=token), open_timeout=10):
            pass
    assert refused.value.response.status_code == 403


def test_analyze_triggered_twice_converges_and_still_renders(sidecar, synthetic_video: Path, tmp_path: Path):
    """Creating a job starts its analysis, so an explicit analyze right after
    it queues a second run. Their status writes interleave (the second run
    marks the job "queued" while the first is still analysing), so only the
    end state is asserted: analysed without error, and renderable."""
    with sidecar.client() as http:
        job_id = sidecar.create_job(http, synthetic_video)
        assert http.post(f"/api/jobs/{job_id}/analyze").status_code == 200
        sidecar.wait_for_idle_worker(http, synthetic_video)

        job = sidecar.wait_for_status(http, job_id, "analyzed")
        assert job["error"] is None

        rendering = http.post(f"/api/jobs/{job_id}/render", json={"output_dir": str(tmp_path)})
        assert rendering.status_code == 200, rendering.text
        rendered = sidecar.wait_for_status(http, job_id, "rendered")
    assert rendered["render"]["songs"][0]["pages"] >= 2


def test_cancelling_a_queued_job_then_analysing_it_again(sidecar, synthetic_video: Path):
    with sidecar.client() as http:
        blocker = sidecar.create_job(http, synthetic_video)
        target = sidecar.create_job(http, synthetic_video)

        with connect(sidecar.progress_url(target), open_timeout=10) as ws:
            assert http.post(f"/api/jobs/{target}/cancel").status_code == 200
            # Determinism is checked, not assumed: the single worker is busy
            # with the blocker, so the cancel must have landed while the
            # target was still waiting. If the blocker had already finished,
            # this fails loudly instead of the test passing by luck.
            assert http.get(f"/api/jobs/{target}").json()["status"] == "queued", (
                "the blocker finished before the cancel landed; the test's premise no longer holds")
            messages = read_progress_until(ws, "cancelled")
        assert messages[-1]["message"] == "job cancelled"

        sidecar.wait_for_status(http, target, "cancelled")
        sidecar.wait_for_status(http, blocker, "analyzed")

        # Queuing a job again clears its cancellation.
        assert http.post(f"/api/jobs/{target}/analyze").status_code == 200
        sidecar.wait_for_status(http, target, "analyzed")
