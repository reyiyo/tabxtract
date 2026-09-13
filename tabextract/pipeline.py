"""Orchestrator: wires the six pipeline stages together. No FastAPI
dependency - the whole thing runs from the CLI."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .advance import AdvanceMode, AdvanceResult, classify_advance_mode
from .compose import compose_paginated, compose_scroll, compute_scroll_offsets
from .layout import (
    LayoutResult,
    build_systems_from_pages,
    build_systems_from_scroll,
    layout_song,
    render_song,
)
from .profiles import Profile, match_profile
from .region import Region, RegionResult, detect_region
from .sampling import FrameCache, extract_frames, probe_resolution
from .songs import SongSegment, segment_songs
from .verify import VerificationReport, build_report

# stage, 0..1 fraction, message for the user. The desktop GUI forwards these
# over a WebSocket; the CLI passes nothing and the pipeline stays quiet.
StageFn = Callable[[str, float, str], None]


def _noop(stage: str, pct: float, message: str) -> None:
    pass


@dataclass
class AnalysisResult:
    region: RegionResult
    advance: AdvanceResult
    songs: list[SongSegment]
    frame_count: int
    matched_profile: str | None = None


@dataclass
class SongRenderResult:
    song: SongSegment
    title: str
    layout: LayoutResult
    report: VerificationReport
    pdf_path: Path


@dataclass
class RenderResult:
    songs: list[SongRenderResult]
    combined_pdf_path: Path | None


def analyze(video_path: Path, workdir: Path, profiles_dir: Path | None = None,
            progress: StageFn | None = None) -> tuple[AnalysisResult, FrameCache]:
    emit = progress or _noop
    frames_dir = workdir / "frames"
    emit("sampling", 0.02, "decoding the video at 2 fps")
    paths = extract_frames(
        video_path, frames_dir,
        progress=lambda f: emit("sampling", 0.02 + 0.38 * f, "decoding the video at 2 fps"),
    )
    cache = FrameCache(paths)

    profile: Profile | None = None
    if profiles_dir is not None:
        w, h = probe_resolution(video_path)
        profile = match_profile(profiles_dir, w, h)

    emit("region", 0.45, "locating the tablature region")
    if profile is not None:
        region_obj = profile.region_obj()
        from .region import RegionResult
        region_result = RegionResult(
            region=region_obj, confidence=1.0, n_lines=0,
            instrument="(perfil)", low_res_warning=region_obj.width < 800,
        )
        advance_result = AdvanceResult(mode=AdvanceMode(profile.mode))
    else:
        region_result = detect_region(cache)
        emit("advance", 0.7, "classifying the advance mode")
        advance_result = classify_advance_mode(cache, region_result.region)

    emit("songs", 0.85, "looking for song boundaries")
    songs = segment_songs(cache, region_result.region)
    emit("done", 1.0, f"{len(songs)} song(s), {advance_result.mode.value} mode")

    return AnalysisResult(
        region=region_result,
        advance=advance_result,
        songs=songs,
        frame_count=len(cache),
        matched_profile=profile.name if profile else None,
    ), cache


def render_song_range(cache: FrameCache, region: Region, mode: AdvanceMode,
                       title: str, out_path: Path) -> tuple[LayoutResult, VerificationReport]:
    if mode == AdvanceMode.PAGINATED:
        pages = compose_paginated(cache, region)
        bands = build_systems_from_pages(pages)
        layout = layout_song(bands)
        report = build_report(layout.bands, mode, None, region, None, None, None)
        dropped = [p.frame_range for p in pages if p.is_transition]
        if dropped:
            report.notes.append(
                f"{len(dropped)} page(s) discarded as song-to-song transitions "
                f"rather than tablature (frames {dropped})")
    else:
        horizontal = mode == AdvanceMode.SCROLL_HORIZONTAL
        offsets = compute_scroll_offsets(cache, region, horizontal=horizontal)
        composite = compose_scroll(cache, region, offsets.values, horizontal=horizontal)
        bands, blocks, cut_ys = build_systems_from_scroll(composite.canvas)
        layout = layout_song(bands)
        report = build_report(layout.bands, mode, offsets, region, composite.canvas, blocks, cut_ys)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    render_song(title, layout, str(out_path))
    return layout, report


def render_all(workdir: Path, analysis: AnalysisResult, cache: FrameCache,
                region_override: Region | None = None,
                song_titles: dict[int, str] | None = None,
                song_boundaries: list[tuple[int, int]] | None = None,
                progress: StageFn | None = None) -> RenderResult:
    emit = progress or _noop
    region = region_override or analysis.region.region
    mode = analysis.advance.mode
    titles = song_titles or {}

    songs = analysis.songs
    if song_boundaries is not None:
        songs = [SongSegment(index=i, start_frame=a, end_frame=b)
                 for i, (a, b) in enumerate(song_boundaries)]

    out_dir = workdir / "output"
    out_dir.mkdir(parents=True, exist_ok=True)

    results: list[SongRenderResult] = []
    for n, song in enumerate(songs):
        title = titles.get(song.index, f"Song {song.index + 1}")
        emit("compose", 0.05 + 0.9 * n / max(len(songs), 1),
             f"compositing and laying out: {title}")
        sub_cache = cache.slice(song.start_frame, song.end_frame)
        # Leading dots are stripped so a title cannot produce a hidden file.
        safe_name = "".join(c if c.isalnum() or c in " -_" else "_" for c in title).strip(" .") or f"song_{song.index+1}"
        pdf_path = out_dir / f"{song.index + 1:02d} - {safe_name}.pdf"
        layout, report = render_song_range(sub_cache, region, mode, title, pdf_path)
        results.append(SongRenderResult(song=song, title=title, layout=layout, report=report, pdf_path=pdf_path))

    combined_path = None
    if len(results) > 1:
        emit("compose", 0.97, "merging the combined PDF")
        combined_path = out_dir / "combined.pdf"
        _merge_pdfs([r.pdf_path for r in results], combined_path)

    emit("done", 1.0, f"{len(results)} PDF(s) generated")

    return RenderResult(songs=results, combined_pdf_path=combined_path)


def _merge_pdfs(paths: list[Path], out_path: Path) -> None:
    from pypdf import PdfWriter

    writer = PdfWriter()
    for p in paths:
        writer.append(str(p))
    with open(out_path, "wb") as f:
        writer.write(f)
