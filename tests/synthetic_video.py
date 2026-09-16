"""A real video file built from the synthetic frames.

Shared by the Python end-to-end tests and the browser ones, so both drive the
app with the same material. Also runnable on its own:

    python -m tests.synthetic_video /tmp/paged.mkv --pages 12

which prints a JSON line with the path and the frame size.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

from tabextract.binaries import ffmpeg_bin
from tabextract.sampling import SAMPLE_FPS

from .synthetic import FRAME_H, FRAME_W, paginated_video, write_frames

# The fewest pages that lay out to more than one A4 sheet.
DEFAULT_PAGES = 12


def write_video(destination: Path, n_pages: int = DEFAULT_PAGES) -> Path:
    """Encode a paged tablature video, losslessly.

    yuv420p, the usual default, halves the chroma resolution and smears the
    thin staff lines, so the engine would analyse something other than what
    the generator drew. ffv1 in bgr0 keeps every pixel. The frame rate equals
    the engine's sampling rate, so each generated frame is exactly one
    analysed frame.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    frames_dir = destination.parent / f"{destination.stem}-frames"
    write_frames(paginated_video(n_pages=n_pages), frames_dir)
    subprocess.run(
        [ffmpeg_bin(), "-y", "-loglevel", "error", "-framerate", str(SAMPLE_FPS),
         "-i", str(frames_dir / "frame_%06d.png"),
         "-c:v", "ffv1", "-pix_fmt", "bgr0", str(destination)],
        check=True,
    )
    shutil.rmtree(frames_dir)  # ~100 MB of noisy PNGs, no longer needed
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--pages", type=int, default=DEFAULT_PAGES)
    args = parser.parse_args()
    video = write_video(args.destination, args.pages)
    print(json.dumps({"path": str(video), "width": FRAME_W, "height": FRAME_H,
                      "pages": args.pages}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
