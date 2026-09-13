"""Required regression test: a synthetic video with N pages, some visually
identical because of repeated riffs, must detect N pages -- not fewer --
because the advance signal is the cursor wrap, never content similarity
(failure mode 1)."""
from pathlib import Path

from tabextract.compose import compose_paginated
from tabextract.cursor import detect_page_wraps, track_cursor
from tabextract.region import Region
from tabextract.sampling import FrameCache

from .synthetic import REGION, paginated_video, write_frames


def _cache(frames, tmp_path) -> FrameCache:
    paths = write_frames(frames, tmp_path / "frames")
    return FrameCache(paths)


def test_wrap_detection_finds_all_pages_despite_duplicate_content(tmp_path: Path):
    n_pages = 10
    duplicates = {2, 6}  # these pages repeat the previous page's bar number
    frames = paginated_video(n_pages=n_pages, duplicate_pages=duplicates)
    cache = _cache(frames, tmp_path)
    region = Region(*REGION)

    samples = track_cursor(cache, region, indices=list(range(len(cache))))
    boundaries = detect_page_wraps(samples, region.width)

    assert len(boundaries) == n_pages


def test_median_compose_produces_n_pages_even_with_identical_pairs(tmp_path: Path):
    n_pages = 6
    frames = paginated_video(n_pages=n_pages, duplicate_pages={3})
    cache = _cache(frames, tmp_path)
    region = Region(*REGION)

    pages = compose_paginated(cache, region)

    assert len(pages) == n_pages
