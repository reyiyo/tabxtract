"""A stepwise scroll (the view holds still and then jumps) has a median |dy|
of 0, exactly like a paged video. What tells them apart is not the frequency
of the motion but its DIRECTION: a scroll always pushes content the same way,
while a page turn is not a translation, so its apparent displacement comes out
with mixed signs."""

from tabextract.advance import AdvanceMode, classify_advance_mode
from tabextract.region import Region
from tabextract.sampling import FrameCache

from .synthetic import REGION, paginated_video, stepwise_scrolling_video


class _MemoryCache(FrameCache):
    """FrameCache over frames already in memory, without touching disk."""

    def __init__(self, frames):
        self._frames = frames
        super().__init__(paths=[None] * len(frames))

    def _read(self, idx):
        return self._frames[idx]


def _region():
    x0, y0, x1, y1 = REGION
    return Region(x0, y0, x1, y1)


def test_stepwise_scroll_is_not_classified_as_paginated():
    frames = stepwise_scrolling_video(n_steps=72, dy_per_jump=90, hold=6)
    result = classify_advance_mode(_MemoryCache(frames), _region())

    assert result.median_abs_dy < 2.0, (
        "the generator has to produce a signal whose MEDIAN is ~0: otherwise "
        "the test does not exercise the case that motivated the fix"
    )
    assert result.mode == AdvanceMode.SCROLL_VERTICAL
    assert result.coherence >= 0.85
    assert result.n_events >= 4


def test_paginated_video_stays_paginated():
    frames = paginated_video(n_pages=6, steps_per_page=6)
    result = classify_advance_mode(_MemoryCache(frames), _region())

    assert result.mode == AdvanceMode.PAGINATED
