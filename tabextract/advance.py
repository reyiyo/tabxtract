"""Stage 3 - Advance-mode classification (vertical/horizontal scroll or paged)."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

import cv2
import numpy as np

from .region import Region
from .sampling import FrameCache

STATIC_THRESHOLD_PX = 2.0  # below this, a displacement counts as noise

# Stepwise-scroll detection (see the _coherent_axis docstring): a source can
# scroll in jerks -- it stays still while the cursor sweeps one system, then
# jumps several hundred px at once. The median |d| of that signal is 0, since
# the vast majority of pairs are static, so the median criterion above would
# classify it as paged.
EVENT_MIN_PX = 2.0
EVENT_MIN_FRAC = 0.02      # a significant event moves >=2% of the region's side
MIN_EVENTS = 4             # fewer than this is noise, not an advance pattern
COHERENCE_MIN = 0.85       # fraction of events that share a sign
#
# Events are counted by SIGN rather than weighted by magnitude
# (|sum(d)|/sum(|d|)): a single bad phaseCorrelate reading is large by
# definition, so weighting by magnitude gives that one outlier the weight of
# several real events. Measured on the three test videos:
#     paged  (1080p):  by sign 0.667 | weighted 0.557
#     scroll (1080p):  by sign 1.000 | weighted 1.000
#     scroll (360p):   by sign 0.947 | weighted 0.775  <- one spurious +149px
#                      event out of 19; weighted falls below the threshold,
#                      by sign it does not.


class AdvanceMode(str, Enum):
    SCROLL_VERTICAL = "scroll_vertical"
    SCROLL_HORIZONTAL = "scroll_horizontal"
    PAGINATED = "paginated"


@dataclass
class AdvanceResult:
    mode: AdvanceMode
    dx: list[float] = field(default_factory=list)
    dy: list[float] = field(default_factory=list)
    median_abs_dx: float = 0.0
    median_abs_dy: float = 0.0
    coherence: float = 0.0      # directionality of the dominant axis (0-1)
    n_events: int = 0           # significant displacements on that axis


def _phase_shift(a: np.ndarray, b: np.ndarray) -> tuple[float, float]:
    (dx, dy), _response = cv2.phaseCorrelate(a.astype(np.float32), b.astype(np.float32))
    return dx, dy


def _coherent_axis(dxs: list[float], dys: list[float],
                    width: int, height: int) -> tuple[str | None, float, int]:
    """Tell a stepwise scroll from a paged video by the *directionality* of the
    large displacements, not their frequency.

    A real scroll always pushes content the same way: its significant
    displacements share a sign, in jumps or continuously. Coherence is the
    fraction of those events that share a sign. A page turn is not a
    translation -- `phaseCorrelate` over two different pages returns an
    arbitrary vector, so those displacements come out with mixed signs.

    Only the dominant axis is evaluated (the one accumulating the most total
    displacement): in a paged video the other axis usually has a few spurious
    events that happen to share a sign, and looking at it would give a false
    positive.

    Returns (axis | None, coherence, event_count).
    """
    axes = {
        "x": (np.array(dxs, dtype=np.float64), width),
        "y": (np.array(dys, dtype=np.float64), height),
    }
    dominant = max(axes, key=lambda k: np.abs(axes[k][0]).sum())
    values, size = axes[dominant]

    significant = np.abs(values) > max(EVENT_MIN_PX, EVENT_MIN_FRAC * size)
    n_events = int(significant.sum())
    if n_events < MIN_EVENTS:
        return None, 0.0, n_events

    events = values[significant]
    coherence = float(max((events > 0).sum(), (events < 0).sum()) / n_events)
    if coherence < COHERENCE_MIN:
        return None, coherence, n_events
    return dominant, coherence, n_events


def classify_advance_mode(cache: FrameCache, region: Region, max_pairs: int = 200) -> AdvanceResult:
    n = len(cache)
    if n < 2:
        raise ValueError("at least 2 frames are needed to classify the advance mode")

    pair_idx = sorted(set(np.linspace(0, n - 2, min(max_pairs, n - 1)).astype(int).tolist()))

    dxs: list[float] = []
    dys: list[float] = []
    for i in pair_idx:
        a = cv2.cvtColor(region.crop(cache[i]), cv2.COLOR_BGR2GRAY)
        b = cv2.cvtColor(region.crop(cache[i + 1]), cv2.COLOR_BGR2GRAY)
        dx, dy = _phase_shift(a, b)
        dxs.append(dx)
        dys.append(dy)

    med_dx = float(np.median(np.abs(dxs)))
    med_dy = float(np.median(np.abs(dys)))

    axis, coherence, n_events = _coherent_axis(dxs, dys, region.width, region.height)

    if med_dy > STATIC_THRESHOLD_PX and med_dy >= med_dx:
        mode = AdvanceMode.SCROLL_VERTICAL
    elif med_dx > STATIC_THRESHOLD_PX and med_dx > med_dy:
        mode = AdvanceMode.SCROLL_HORIZONTAL
    elif axis == "y":
        # Both medians ~0, but the large jumps all go the same way: this is a
        # stepwise scroll, not a paged video.
        mode = AdvanceMode.SCROLL_VERTICAL
    elif axis == "x":
        mode = AdvanceMode.SCROLL_HORIZONTAL
    else:
        # Both medians ~0 and no directionality: most pairs are static, with
        # periodic discontinuities (page turns).
        mode = AdvanceMode.PAGINATED

    return AdvanceResult(mode=mode, dx=dxs, dy=dys, median_abs_dx=med_dx,
                          median_abs_dy=med_dy, coherence=coherence, n_events=n_events)
