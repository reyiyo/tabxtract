# TabXtract - extracts tablature from video and rebuilds it as a PDF.
# Copyright (C) 2026 TabXtract contributors
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See <https://www.gnu.org/licenses/>.
"""Job execution on threads.

A single user on a single machine needs no job queue: two thread pools are
enough. The processing pool has a single worker on purpose: two simultaneous analyses on the user's machine
fight over the CPU and finish later than they would in series. Downloads get
their own pool because they are waiting on the network, not on CPU.
"""
from __future__ import annotations

import logging
import re
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import cv2

from tabextract.advance import AdvanceMode, AdvanceResult
from tabextract.pipeline import AnalysisResult, render_all
from tabextract.pipeline import analyze as engine_analyze
from tabextract.profiles import save_profile
from tabextract.region import Region, RegionResult
from tabextract.sampling import FrameCache
from tabextract.songs import SongSegment

from . import db, ytdlp
from .config import job_workdir, load_preferences, profiles_dir
from .progress import broker
from .serialize import serialize_analysis, serialize_render

log = logging.getLogger(__name__)

_processing = ThreadPoolExecutor(max_workers=1, thread_name_prefix="tabx-job")
_downloads = ThreadPoolExecutor(max_workers=2, thread_name_prefix="tabx-dl")

_cancelled: set[str] = set()
_cancel_lock = threading.Lock()


class Cancelled(RuntimeError):
    pass


def request_cancel(job_id: str) -> None:
    with _cancel_lock:
        _cancelled.add(job_id)


def is_cancelled(job_id: str) -> bool:
    with _cancel_lock:
        return job_id in _cancelled


def _clear_cancel(job_id: str) -> None:
    with _cancel_lock:
        _cancelled.discard(job_id)


def shutdown() -> None:
    _processing.shutdown(wait=False, cancel_futures=True)
    _downloads.shutdown(wait=False, cancel_futures=True)


def _emitter(job_id: str):
    """The engine's progress callback, which doubles as the cancellation point.

    The engine calls this between stages and during decoding, so raising here
    stops the job without the engine needing to know anything about
    cancellation.
    """
    def emit(stage: str, pct: float, message: str) -> None:
        if is_cancelled(job_id):
            raise Cancelled()
        broker.publish(job_id, stage, pct, message)

    return emit


# ffmpeg opens every run with its version, its build and one line per library.
# When the failure is an argument error those banner lines are most of the
# output, so the tail would be library versions instead of the reason.
_BANNER = re.compile(r"^(ffmpeg|ffprobe) version |^built with |^configuration: |^lib\w+\s+\d")


def _stderr_tail(exc: BaseException, max_lines: int = 4, max_chars: int = 400) -> str:
    """The last meaningful lines of a failed subprocess's stderr, or "".

    CalledProcessError carries the output the caller captured, but str() drops
    it: a failing ffmpeg reaches the user as a bare exit code and the reason it
    printed is thrown away.
    """
    raw = getattr(exc, "stderr", None)
    if not raw:
        return ""
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", "replace")
    lines = [line.strip() for line in raw.strip().splitlines() if line.strip()]
    # Falling back to the unfiltered lines keeps a banner-only stderr visible
    # rather than reporting nothing at all.
    lines = [line for line in lines if not _BANNER.match(line)] or lines
    return " / ".join(lines[-max_lines:])[:max_chars]


def _fail(job_id: str, exc: BaseException) -> None:
    if isinstance(exc, Cancelled):
        db.update_job(job_id, status="cancelled", error=None)
        broker.publish(job_id, "cancelled", 1.0, "job cancelled")
        return
    hint = getattr(exc, "hint", "")
    message = " ".join(p for p in (str(exc), _stderr_tail(exc), hint) if p).strip()
    # The traceback goes to the log file, which is what a bug report attaches.
    log.error("job %s failed: %s", job_id, message, exc_info=exc)
    db.update_job(job_id, status="failed", error=message)
    broker.publish(job_id, "error", 1.0, message, kind=getattr(exc, "kind", "error"))


# --------------------------------------------------------------------------
# URL download
# --------------------------------------------------------------------------

def submit_download(job_id: str, url: str, format_id: str | None) -> None:
    _clear_cancel(job_id)
    db.update_job(job_id, status="downloading", error=None)
    _downloads.submit(_run_download, job_id, url, format_id)


def _run_download(job_id: str, url: str, format_id: str | None) -> None:
    try:
        prefs = load_preferences()
        dest = job_workdir(job_id) / "source"
        broker.publish(job_id, "download", 0.0, "connecting to the video server")
        path = ytdlp.download(
            url, dest, format_id=format_id,
            max_height=int(prefs.get("youtube_max_height") or 1080),
            progress=lambda frac, text: broker.publish(job_id, "download", frac, text),
            should_cancel=lambda: is_cancelled(job_id),
        )
        db.update_job(job_id, status="ready", local_path=str(path))
        broker.publish(job_id, "download", 1.0, "download complete")
        # Analysis goes back to the single-worker pool: it is CPU, not network.
        submit_analyze(job_id)
    except ytdlp.YtdlpError as exc:
        if exc.kind == "cancelled":
            _fail(job_id, Cancelled())
        else:
            _fail(job_id, exc)
    except Exception as exc:  # noqa: BLE001 - the job state is the error report
        _fail(job_id, exc)


# --------------------------------------------------------------------------
# Analysis
# --------------------------------------------------------------------------

def submit_analyze(job_id: str) -> None:
    _clear_cancel(job_id)
    db.update_job(job_id, status="queued", error=None)
    _processing.submit(_run_analyze, job_id)


def _run_analyze(job_id: str) -> None:
    try:
        job = db.get_job(job_id)
        if job is None:
            return
        source = job.get("local_path")
        if not source or not Path(source).exists():
            raise FileNotFoundError(
                f"the source video was not found ({source or 'no path'}). "
                "If this is a job from the history, the file may have moved.")

        db.update_job(job_id, status="analyzing")
        workdir = job_workdir(job_id)
        analysis, _cache = engine_analyze(
            Path(source), workdir, profiles_dir=profiles_dir(),
            progress=_emitter(job_id),
        )
        db.update_job(job_id, status="analyzed", analysis=serialize_analysis(analysis))
    except Exception as exc:  # noqa: BLE001
        _fail(job_id, exc)


# --------------------------------------------------------------------------
# Render
# --------------------------------------------------------------------------

def submit_render(job_id: str, region: dict | None, songs: list[dict] | None,
                  save_profile_name: str | None, output_dir: str | None) -> None:
    _clear_cancel(job_id)
    db.update_job(job_id, status="queued_render", error=None)
    _processing.submit(_run_render, job_id, region, songs, save_profile_name, output_dir)


def _rehydrate_analysis(job: dict[str, Any]) -> AnalysisResult:
    a = job["analysis"]
    return AnalysisResult(
        region=RegionResult(
            region=Region(*a["region"]["bbox"]),
            confidence=a["region"]["confidence"],
            n_lines=a["region"]["n_lines"],
            instrument=a["region"]["instrument"],
            low_res_warning=a["region"]["low_res_warning"],
        ),
        advance=AdvanceResult(mode=AdvanceMode(a["advance_mode"])),
        songs=[SongSegment(index=s["index"], start_frame=s["start_frame"],
                           end_frame=s["end_frame"]) for s in a["songs"]],
        frame_count=a["frame_count"],
        matched_profile=a.get("matched_profile"),
    )


def _safe_dir_name(name: str) -> str:
    # Leading dots are stripped too: a title of "." or ".hidden" must not
    # resolve to the output directory itself or to a hidden folder.
    cleaned = "".join(c if c.isalnum() or c in " -_." else "_" for c in name).strip(" .")
    return cleaned[:80] or "tabxtract"


def _publish_output(job_title: str, staged: Path, output_dir: Path) -> Path:
    """Move the PDFs from the temporary directory to the one the user chose.

    Each job gets its own folder: a 5-song video is 6 PDFs, and mixing them
    with the previous job's in one folder is worse than having subfolders.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / _safe_dir_name(job_title)
    suffix = 2
    while target.exists():
        target = output_dir / f"{_safe_dir_name(job_title)} ({suffix})"
        suffix += 1
    shutil.move(str(staged), str(target))
    return target


def _run_render(job_id: str, region_override: dict | None, songs_override: list[dict] | None,
                save_profile_name: str | None, output_dir: str | None) -> None:
    workdir = job_workdir(job_id)
    try:
        job = db.get_job(job_id)
        if job is None or not job.get("analysis"):
            raise RuntimeError("this job has no previous analysis")

        db.update_job(job_id, status="rendering")
        paths = sorted((workdir / "frames").glob("frame_*.png"))
        if not paths:
            raise RuntimeError("no frames left for this job; analyse it again")
        cache = FrameCache(paths)
        analysis = _rehydrate_analysis(job)

        region = (Region(region_override["x0"], region_override["y0"],
                         region_override["x1"], region_override["y1"])
                  if region_override else None)
        boundaries = ([(s["start_frame"], s["end_frame"]) for s in songs_override]
                      if songs_override else None)
        titles = ({s["index"]: s["title"] for s in songs_override if s.get("title")}
                  if songs_override else None)

        result = render_all(workdir, analysis, cache, region_override=region,
                            song_titles=titles, song_boundaries=boundaries,
                            progress=_emitter(job_id))

        if save_profile_name:
            frame = cv2.imread(str(cache.paths[0]))
            if frame is None:
                raise RuntimeError("could not re-read the first frame to save the profile")
            h, w = frame.shape[:2]
            save_profile(profiles_dir(), save_profile_name, w, h,
                         region or analysis.region.region, analysis.advance.mode)

        prefs = load_preferences()
        chosen = output_dir or prefs.get("output_dir")
        if not chosen:
            raise RuntimeError("no output directory has been chosen")
        final_dir = _publish_output(job["title"], workdir / "output", Path(chosen))

        db.update_job(job_id, status="rendered", output_dir=str(final_dir),
                      render=serialize_render(result, final_dir))
        broker.publish(job_id, "done", 1.0, f"done: {final_dir}")
        # The frames are hundreds of MB and are no longer needed.
        shutil.rmtree(workdir, ignore_errors=True)
    except Exception as exc:  # noqa: BLE001
        _fail(job_id, exc)
