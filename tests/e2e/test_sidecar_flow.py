"""The desktop app's whole path against the real sidecar: ffmpeg decoding, the
engine, the job database, the progress WebSocket and the PDF on disk.

The assertions are about what the user ends up with -- a PDF, how many pages
it has, what the report says -- not about pipeline internals.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from pypdf import PdfReader

from ._deps import need_module
from ._sidecar import read_progress_until

pytestmark = pytest.mark.e2e

connect = need_module("websockets.sync.client").connect


def test_video_to_pdf_through_the_sidecar(sidecar, synthetic_video: Path, tmp_path: Path):
    output_dir = tmp_path / "pdfs"

    with sidecar.client() as http:
        health = http.get("/api/health").json()
        assert health["missing_binaries"] == []
        assert Path(health["data_dir"]) == sidecar.data_dir

        job_id = sidecar.create_job(http, synthetic_video)

        # Creating the job already queues its analysis, and the progress
        # broker keeps no backlog: whatever is published before a socket
        # subscribes is gone. Opening the socket before triggering another run
        # guarantees a complete stream is seen -- it may belong to either run,
        # which is why the assertions below are about the shape of the
        # progress, not about which run produced it.
        with connect(sidecar.progress_url(job_id), open_timeout=10) as ws:
            assert http.post(f"/api/jobs/{job_id}/analyze").status_code == 200
            sidecar.wait_for_idle_worker(http, synthetic_video)
            messages = read_progress_until(ws, "done")
        assert all(0.0 <= m["pct"] <= 1.0 for m in messages)
        assert messages[-1]["pct"] == 1.0

        job = sidecar.wait_for_status(http, job_id, "analyzed")
        analysis = job["analysis"]
        assert analysis["advance_mode"] == "paginated"
        assert len(analysis["songs"]) == 1

        # The user nudges the detected region in the review screen.
        x0, y0, x1, y1 = analysis["region"]["bbox"]
        region = {"x0": x0 + 2, "y0": y0 + 2, "x1": x1 - 2, "y1": y1 - 2}
        patched = http.patch(f"/api/jobs/{job_id}/region", json={"region": region})
        assert patched.status_code == 200, patched.text
        assert patched.json()["overrides"]["region"] == region

        with connect(sidecar.progress_url(job_id), open_timeout=10) as ws:
            rendering = http.post(f"/api/jobs/{job_id}/render", json={"output_dir": str(output_dir)})
            assert rendering.status_code == 200, rendering.text
            read_progress_until(ws, "done")
        sidecar.wait_for_status(http, job_id, "rendered")

        report = http.get(f"/api/jobs/{job_id}/report")
    assert report.status_code == 200, report.text

    (song,) = report.json()["songs"]
    pdf = Path(song["path"])
    assert pdf.is_file()
    assert pdf.is_relative_to(output_dir)
    assert song["pages"] >= 2
    assert len(PdfReader(pdf).pages) == song["pages"]

    # The report always carries a continuity verdict. What it says depends on
    # OCR of the synthetic bar numbers, which is not reliable at this frame
    # size, so only its presence and the absence of a reported gap are
    # asserted -- never that continuity was verified.
    assert song["report"]["measure_continuity"]
    gaps = [issue for issue in song["report"]["measure_issues"] if issue["kind"] == "gap"]
    assert gaps == [], gaps
