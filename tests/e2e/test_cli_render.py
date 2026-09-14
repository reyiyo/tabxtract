"""The engine's own CLI on a real video file: the path with no server at all."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from pypdf import PdfReader

pytestmark = pytest.mark.e2e


def test_cli_render_writes_the_pdf_into_the_workdir(synthetic_video: Path, tmp_path: Path):
    workdir = tmp_path / "work"

    proc = subprocess.run(
        [sys.executable, "-m", "tabextract.cli", "render", str(synthetic_video), "--workdir", str(workdir)],
        capture_output=True, text=True, timeout=300,
    )
    assert proc.returncode == 0, proc.stderr[-4000:]

    (song,) = json.loads(proc.stdout)["songs"]
    pdf = Path(song["pdf"])
    assert pdf.is_file()
    assert pdf.parent == workdir / "output"
    assert song["pages"] >= 2
    assert len(PdfReader(pdf).pages) == song["pages"]
    # Presence only: the verdict's content depends on OCR of synthetic bar
    # numbers, which is not reliable at this frame size.
    assert song["measure_continuity"]
