"""Stage 4 - Playback cursor detection.

No fixed colour is assumed (in one test video the cursor was orange, in
another green). Detection is structural: the tab region is near-white and low
saturation (see region.py), so any narrow band of anomalous saturation
against that background is a cursor candidate, whatever its hue.
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from .region import Region
from .sampling import FrameCache

WRAP_FRACTION = 0.3  # jumping back > 30% of the region width means a new page


@dataclass
class CursorSample:
    frame_idx: int
    x: int
    strength: float


def _saturation_column_profile(bgr_crop: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(bgr_crop, cv2.COLOR_BGR2HSV)
    sat = hsv[:, :, 1].astype(np.float32)
    # Per-frame adaptive threshold: anomalous means several sigmas above the
    # median background saturation, which should be ~0 over paper.
    baseline = float(np.median(sat))
    spread = float(np.std(sat)) + 1e-6
    anomaly = sat > (baseline + max(3 * spread, 25))
    return anomaly.sum(axis=0).astype(np.float64)


def detect_cursor_x(bgr_crop: np.ndarray) -> tuple[int, float] | None:
    col = _saturation_column_profile(bgr_crop)
    if col.max() <= 0:
        return None
    x = int(col.argmax())
    strength = float(col[x])
    return x, strength


def track_cursor(cache: FrameCache, region: Region, indices: list[int] | None = None) -> list[CursorSample]:
    idxs = indices if indices is not None else list(range(len(cache)))
    samples: list[CursorSample] = []
    for i in idxs:
        found = detect_cursor_x(region.crop(cache[i]))
        if found is None:
            continue
        x, strength = found
        samples.append(CursorSample(frame_idx=i, x=x, strength=strength))
    return samples


def detect_page_wraps(samples: list[CursorSample], region_width: int,
                       wrap_fraction: float = WRAP_FRACTION) -> list[int]:
    """Return the frame_idx values where a new page starts (first included).

    A new page begins when the cursor jumps backwards by more than
    `wrap_fraction` of the region width (Failure mode 1: the advance signal is
    the cursor wrap, never content similarity).
    """
    if not samples:
        return []
    threshold = wrap_fraction * region_width
    boundaries = [samples[0].frame_idx]
    for prev, cur in zip(samples, samples[1:]):
        if cur.x < prev.x - threshold:
            boundaries.append(cur.frame_idx)
    return boundaries
