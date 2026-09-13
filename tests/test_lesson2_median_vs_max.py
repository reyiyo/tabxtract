"""Failure mode 2: one misaligned frame must not contaminate the final
result. The median leaves it in the minority; the per-pixel maximum (which
picks the LIGHTEST value of each pixel, not the darkest) can erase real ink if
that single frame shows it white by mistake -- which is exactly why max is
reserved for bands with fewer than 3 contributors."""
import cv2
import numpy as np

from tabextract.compose import compose_paginated
from tabextract.region import Region
from tabextract.sampling import FrameCache

from .synthetic import N_STRINGS, REGION, STRING_GAP, paginated_video, write_frames

MEASURES_PER_PAGE = 5


def _barline_pixel(region=REGION, n_measures=MEASURES_PER_PAGE, m=2):
    x0, y0, x1, y1 = region
    string_top = y0 + 20
    measure_w = (x1 - x0 - 40) // n_measures
    bx = x0 + 20 + m * measure_w
    by = string_top + (N_STRINGS - 1) * STRING_GAP // 2
    return bx, by


def test_median_survives_single_frame_erasure(tmp_path):
    frames = paginated_video(n_pages=1, measures_per_page=MEASURES_PER_PAGE, steps_per_page=9)
    bx, by = _barline_pixel()

    # One interior frame mistakenly "erases" the real barline.
    erased = frames[4].copy()
    cv2.rectangle(erased, (bx - 4, by - 20), (bx + 4, by + 20), (255, 255, 255), -1)
    frames[4] = erased

    paths = write_frames(frames, tmp_path / "frames")
    cache = FrameCache(paths)
    region = Region(*REGION)

    pages = compose_paginated(cache, region)
    assert len(pages) == 1
    canvas = pages[0].canvas

    gx, gy = bx - region.x0, by - region.y0
    patch = canvas[gy - 3:gy + 3, gx - 3:gx + 3]
    assert patch.mean() < 150, "the real barline must survive the median despite the erased frame"


def test_max_would_have_lost_the_real_ink(tmp_path):
    """Control: confirms the scenario exercises the real failure mode 2 bug.
    If max (the lightest value) were used instead of the median, a single
    white frame is enough to erase ink every other frame shows."""
    frames = paginated_video(n_pages=1, measures_per_page=MEASURES_PER_PAGE, steps_per_page=9)
    bx, by = _barline_pixel()

    erased = frames[4].copy()
    cv2.rectangle(erased, (bx - 4, by - 20), (bx + 4, by + 20), (255, 255, 255), -1)
    frames[4] = erased

    region = Region(*REGION)
    grays = [cv2.cvtColor(region.crop(f), cv2.COLOR_BGR2GRAY) for f in frames[1:-1]]
    stack = np.stack(grays)
    maxed = np.max(stack, axis=0)  # this is what compose_paginated must NOT use

    gx, gy = bx - region.x0, by - region.y0
    patch = maxed[gy - 3:gy + 3, gx - 3:gx + 3]
    assert patch.mean() > 200, "the per-pixel max lets one frame's spurious white through"
