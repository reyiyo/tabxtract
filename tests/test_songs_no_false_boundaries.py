"""The MAD z-score is relative: it measures how far a frame departs from the
typical variation, no matter how small that variation is. When nothing outside
the region really moves (a screen capture, where the only external element is
a near-static playback bar), the typical variation is compression noise and
any flicker becomes a huge outlier, so the detector invents songs where there
is only one."""
import cv2
import numpy as np

from tabextract.region import Region
from tabextract.songs import segment_songs

from .synthetic import REGION, make_frame
from .test_advance_stepwise_scroll import _MemoryCache


def _region():
    x0, y0, x1, y1 = REGION
    return Region(x0, y0, x1, y1)


def _screen_capture_frames(n: int) -> list[np.ndarray]:
    """A single song in a web app.

    Nothing outside the region moves: only a playback bar growing in discrete
    steps. That is exactly the condition that broke the detector -- most
    consecutive pairs are IDENTICAL, so the typical variation is near zero and
    the smallest step becomes a huge z-score outlier.
    """
    rng = np.random.default_rng(7)
    tab = make_frame(1, region=REGION)
    x0, y0, x1, y1 = REGION
    frames = []
    for i in range(n):
        f = np.full((540, 960, 3), 245, dtype=np.uint8)
        f[y0:y1, x0:x1] = tab[y0:y1, x0:x1]
        # The bar advances every 10 frames, not a little on every frame.
        cv2.rectangle(f, (20, 520), (20 + 7 * (i // 10), 526), (0, 120, 255), -1)
        # Minimal compression noise, on a handful of scattered pixels.
        ys = rng.integers(0, 540, size=12)
        xs = rng.integers(0, 960, size=12)
        f[ys, xs] = 244
        frames.append(f)
    return frames


def test_static_ui_outside_region_does_not_manufacture_songs():
    frames = _screen_capture_frames(120)

    songs = segment_songs(_MemoryCache(frames), _region())

    assert len(songs) == 1, (
        f"a playback bar is not a song boundary; {len(songs)} were detected"
    )
    assert (songs[0].start_frame, songs[0].end_frame) == (0, 119)


def test_real_title_change_is_still_detected():
    """Control: the absolute floor must not hide a real transition."""
    x0, y0, x1, y1 = REGION
    frames = []
    for seed in (3, 91):  # two completely different "title cards"
        for _ in range(60):
            frames.append(make_frame(1, title_seed=seed, region=REGION))

    songs = segment_songs(_MemoryCache(frames), _region())

    assert len(songs) == 2
    assert songs[1].start_frame == 60
