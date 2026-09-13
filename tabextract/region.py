"""Stage 2 - Detection of the region containing the tablature."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

import cv2
import numpy as np

from .geometry import close_short_gaps_1d, infer_instrument, staff_line_groups
from .sampling import FrameCache

N_SAMPLES = 40
LOW_RES_WARNING_WIDTH = 800
ROW_PAPER_THRESH = 0.5
COL_PAPER_THRESH = 0.5
STABILITY_TOLERANCE_FRAC = 0.03  # a sample "agrees" when within 3% of the frame size


@dataclass
class Region:
    x0: int
    y0: int
    x1: int
    y1: int

    @property
    def width(self) -> int:
        return self.x1 - self.x0

    @property
    def height(self) -> int:
        return self.y1 - self.y0

    def as_tuple(self) -> tuple[int, int, int, int]:
        return (self.x0, self.y0, self.x1, self.y1)

    def crop(self, frame: np.ndarray) -> np.ndarray:
        return frame[self.y0:self.y1, self.x0:self.x1]


@dataclass
class RegionResult:
    region: Region
    confidence: float
    n_lines: int
    instrument: str
    low_res_warning: bool


def _paper_mask(bgr: np.ndarray, sat_thresh: int = 40, val_thresh: int = 170) -> np.ndarray:
    """Ink on paper: near-white, low saturation."""
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    s, v = hsv[:, :, 1], hsv[:, :, 2]
    return (s < sat_thresh) & (v > val_thresh)


def _largest_run(mask_1d: np.ndarray) -> tuple[int, int] | None:
    """Longest contiguous run of True in a 1D boolean array."""
    best = None
    start = None
    for i, v in enumerate(mask_1d.tolist() + [False]):
        if v and start is None:
            start = i
        elif not v and start is not None:
            if best is None or (i - start) > (best[1] - best[0]):
                best = (start, i)
            start = None
    return best


def _candidate_bbox(bgr: np.ndarray) -> tuple[tuple[int, int, int, int], int] | None:
    """The region is, first of all, the largest and most stable rectangle of
    paper (near-white, low saturation) in the frame. The ink inside that
    rectangle varies frame to frame (a note, a bar), so it is NOT used to
    define the edges -- only to confirm there is a staff inside, and for the
    instrument metadata."""
    paper = _paper_mask(bgr)
    h, w = paper.shape

    # A barline, or a full staff, can cross the entire height/width of the
    # band with solid ink a few pixels wide: without closing those short gaps
    # they fragment what is really one continuous run of paper.
    row_gap = max(10, round(0.015 * h))
    col_gap = max(10, round(0.015 * w))

    row_frac = paper.mean(axis=1)
    row_run = _largest_run(close_short_gaps_1d(row_frac > ROW_PAPER_THRESH, row_gap))
    if row_run is None:
        return None
    y0, y1 = row_run
    if y1 - y0 < 20:
        return None

    col_frac = paper[y0:y1, :].mean(axis=0)
    col_run = _largest_run(close_short_gaps_1d(col_frac > COL_PAPER_THRESH, col_gap))
    if col_run is None:
        return None
    x0, x1 = col_run
    if x1 - x0 < 20:
        return None

    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    band_paper = paper[y0:y1, x0:x1]
    masked_gray = np.where(band_paper, gray[y0:y1, x0:x1], 255).astype(np.uint8)
    groups = staff_line_groups(masked_gray)
    if not groups:
        return None

    n_lines = max(g["n_lines"] for g in groups)
    return (x0, y0, x1, y1), n_lines


def detect_region(cache: FrameCache, n_samples: int = N_SAMPLES) -> RegionResult:
    n = len(cache)
    sample_idx = sorted(set(np.linspace(0, n - 1, min(n_samples, n)).astype(int).tolist()))

    boxes: list[tuple[int, int, int, int]] = []
    line_counts: list[int] = []
    for i in sample_idx:
        found = _candidate_bbox(cache[i])
        if found is None:
            continue
        bbox, n_lines = found
        boxes.append(bbox)
        line_counts.append(n_lines)

    if not boxes:
        raise ValueError("no tablature region could be detected in the sampled frames")

    arr = np.array(boxes)
    median_box = np.median(arr, axis=0)

    # Confidence: the fraction of samples whose bbox agrees with the median.
    # The physical region is fixed, so large disagreement means a source that
    # moves or zooms, or a spurious detection in some frames.
    frame_h, frame_w = cache[sample_idx[0]].shape[:2]
    tol = STABILITY_TOLERANCE_FRAC * max(frame_w, frame_h)
    agree = np.all(np.abs(arr - median_box) <= tol, axis=1)
    confidence = float(agree.sum()) / len(sample_idx)

    region = Region(*(int(round(v)) for v in median_box))
    n_lines = Counter(line_counts).most_common(1)[0][0] if line_counts else 0

    return RegionResult(
        region=region,
        confidence=round(confidence, 3),
        n_lines=n_lines,
        instrument=infer_instrument(n_lines),
        low_res_warning=region.width < LOW_RES_WARNING_WIDTH,
    )
