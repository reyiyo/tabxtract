"""Converts the engine's results (dataclasses holding numpy arrays) into
JSON-safe dicts for the history. Pixels are never serialised: images are
served as files, not through the API.

On the desktop the PDFs are written into the output directory the user chose,
so what travels to the frontend is the absolute path rather than a download
URL: the app opens them with the system viewer."""
from __future__ import annotations

from pathlib import Path

from tabextract.pipeline import AnalysisResult, RenderResult


def serialize_analysis(analysis: AnalysisResult) -> dict:
    return {
        "region": {
            "bbox": list(analysis.region.region.as_tuple()),
            "confidence": analysis.region.confidence,
            "instrument": analysis.region.instrument,
            "n_lines": analysis.region.n_lines,
            "low_res_warning": analysis.region.low_res_warning,
        },
        "advance_mode": analysis.advance.mode.value,
        "frame_count": analysis.frame_count,
        "songs": [
            {"index": s.index, "start_frame": s.start_frame, "end_frame": s.end_frame}
            for s in analysis.songs
        ],
        "matched_profile": analysis.matched_profile,
    }


def serialize_render(result: RenderResult, output_dir: Path) -> dict:
    return {
        "songs": [
            {
                "index": r.song.index,
                "title": r.title,
                "pages": len(r.layout.pages),
                "path": str(output_dir / r.pdf_path.name),
                "report": {
                    "score": r.report.score,
                    "measure_continuity": r.report.measure_continuity.summary,
                    "measure_issues": [
                        {"system_index": i.system_index, "kind": i.kind,
                         "from_measure": i.from_measure, "to_measure": i.to_measure}
                        for i in r.report.measure_continuity.issues
                    ],
                    "low_confidence_systems": r.report.low_confidence_systems,
                    "overlap_ok": r.report.overlap.ok if r.report.overlap.applicable else None,
                    "cuts_on_ink": r.report.cuts_on_ink,
                    "discarded_ink_flag": r.report.discarded_ink_flag,
                    "notes": r.report.notes,
                },
            }
            for r in result.songs
        ],
        "combined_path": (
            str(output_dir / result.combined_pdf_path.name)
            if result.combined_pdf_path else None
        ),
        "output_dir": str(output_dir),
    }
