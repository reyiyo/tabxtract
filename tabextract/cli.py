"""The CV engine's own CLI. Runs and is tested without the desktop app."""
from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from pathlib import Path

import click

from .pipeline import analyze as run_analyze
from .pipeline import render_all
from .profiles import save_profile
from .region import Region


def _json_default(obj):
    if is_dataclass(obj):
        return asdict(obj)
    if hasattr(obj, "value"):  # Enum
        return obj.value
    if hasattr(obj, "tolist"):  # numpy
        return obj.tolist()
    return str(obj)


def _dump(obj) -> str:
    return json.dumps(obj, default=_json_default, indent=2, ensure_ascii=False)


@click.group()
def main():
    """Tablature extraction engine: video -> printable A4 PDF."""


@main.command()
@click.argument("video", type=click.Path(exists=True, path_type=Path))
@click.option("--workdir", type=click.Path(path_type=Path), required=True)
@click.option("--profiles-dir", type=click.Path(path_type=Path), default=None)
def analyze(video: Path, workdir: Path, profiles_dir: Path | None):
    """Stages 1-4: region, advance mode and detected songs."""
    result, _cache = run_analyze(video, workdir, profiles_dir=profiles_dir)
    click.echo(_dump({
        "region": {
            "bbox": result.region.region.as_tuple(),
            "confidence": result.region.confidence,
            "instrument": result.region.instrument,
            "n_lines": result.region.n_lines,
            "low_res_warning": result.region.low_res_warning,
        },
        "advance_mode": result.advance.mode,
        "frame_count": result.frame_count,
        "songs": [
            {"index": s.index, "start_frame": s.start_frame, "end_frame": s.end_frame}
            for s in result.songs
        ],
        "matched_profile": result.matched_profile,
    }))


@main.command()
@click.argument("video", type=click.Path(exists=True, path_type=Path))
@click.option("--workdir", type=click.Path(path_type=Path), required=True)
@click.option("--profiles-dir", type=click.Path(path_type=Path), default=None)
@click.option("--region", "region_str", default=None, help="x0,y0,x1,y1 override")
@click.option("--titles", default=None, help='JSON {"0": "Title"}')
@click.option("--save-profile", "profile_name", default=None)
def render(video: Path, workdir: Path, profiles_dir: Path | None,
           region_str: str | None, titles: str | None, profile_name: str | None):
    """Run the whole pipeline: analyse and generate the PDFs."""
    analysis, cache = run_analyze(video, workdir, profiles_dir=profiles_dir)

    region_override = None
    if region_str:
        x0, y0, x1, y1 = (int(v) for v in region_str.split(","))
        region_override = Region(x0, y0, x1, y1)

    song_titles = {int(k): v for k, v in json.loads(titles).items()} if titles else None

    result = render_all(workdir, analysis, cache, region_override=region_override,
                         song_titles=song_titles)

    if profile_name and profiles_dir:
        from .sampling import probe_resolution
        w, h = probe_resolution(video)
        save_profile(profiles_dir, profile_name, w, h,
                      region_override or analysis.region.region, analysis.advance.mode)

    click.echo(_dump({
        "songs": [
            {
                "title": r.title,
                "pdf": str(r.pdf_path),
                "pages": len(r.layout.pages),
                "score": r.report.score,
                "measure_continuity": r.report.measure_continuity.summary,
                "notes": r.report.notes,
            }
            for r in result.songs
        ],
        "combined_pdf": str(result.combined_pdf_path) if result.combined_pdf_path else None,
    }))


if __name__ == "__main__":
    main()
