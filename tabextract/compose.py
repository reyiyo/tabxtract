"""Stage 5 - Compositing. Per-pixel median across every frame covering each
area: the most valuable technique in the pipeline (failure mode 2). With no
colour assumptions, it removes the cursor, note highlights and misaligned
frames in a single pass.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

from .advance import AdvanceMode
from .cursor import detect_page_wraps, track_cursor
from .region import Region
from .sampling import FrameCache

BAND = 200
MIN_CONTRIBUTORS = 3
PAPER_VALUE = 170          # same "paper" threshold region.py uses
MIN_PAPER_FRACTION = 0.5   # below this the page is not a tab (see compose_paginated)
TEMPLATE_HALF = 120
MIN_TEMPLATE_HALF = 8
MAX_TEMPLATE_FRAC = 6      # the template never covers more than 2/6 = 1/3 of the region's side
MATCH_CONFIDENCE_MIN = 0.6


@dataclass
class BandInfo:
    y0: int
    y1: int
    n_contributors: int
    low_confidence: bool


@dataclass
class ScrollOffsets:
    """Accumulated offsets per frame, plus the pairs that could not be measured.

    `unresolved` is not cosmetic: every pair listed there is content that may
    have been lost without leaving a trace in the PDF (see
    `compute_scroll_offsets`), so it travels all the way to the verification
    report.
    """
    values: list[int]
    unresolved: list[int] = field(default_factory=list)
    fallback_pairs: list[int] = field(default_factory=list)

    # Compatibility with the earlier usage, which was a bare list.
    def __iter__(self):
        return iter(self.values)

    def __len__(self) -> int:
        return len(self.values)

    def __getitem__(self, i):
        return self.values[i]


@dataclass
class ScrollComposite:
    canvas: np.ndarray  # grayscale, full height x region width
    offsets: list[int]
    bands: list[BandInfo] = field(default_factory=list)


@dataclass
class PageComposite:
    index: int
    canvas: np.ndarray
    frame_range: tuple[int, int]
    n_contributors: int
    low_confidence: bool
    paper_fraction: float = 1.0
    is_transition: bool = False


def _region_gray(cache: FrameCache, region: Region, i: int) -> np.ndarray:
    return cv2.cvtColor(region.crop(cache[i]), cv2.COLOR_BGR2GRAY)


def compute_scroll_offsets(cache: FrameCache, region: Region,
                            horizontal: bool = False) -> ScrollOffsets:
    """Template matching of a strip against the next frame, accumulating
    offsets. `horizontal` transposes the problem, since horizontal scroll is
    symmetric to vertical.

    When template matching does not reach the confidence threshold, it is NOT
    assumed that the content did not move. Assuming 0 is the one answer that
    guarantees losing content if it did move, and it does so silently:
    `check_overlap_scroll` compares `max(diff(offsets))` against the visible
    window, and a step pinned at 0 makes the diffs SMALLER, so the check
    passes anyway and the PDF comes out looking fine with a piece missing.

    The template is taken from the BOTTOM strip of the previous frame, not the
    middle one: in a forward scroll the content moves up, so the bottom is
    exactly what is still visible in the next frame, while the top leaves the
    screen. Taking it from the bottom, the maximum measurable displacement is
    `L - template_height` instead of `L/2 - template_height/2`.

    Measured on the scroll test video: with the region cropped by hand, a real
    367px jump matched with confidence 0.590 against a 0.60 threshold and was
    discarded entirely. `phaseCorrelate` -- an independent estimator, in the
    frequency domain -- returned 367.3 for that same pair. That is why it is
    used as a second opinion before giving up.
    """
    n = len(cache)

    def get(i: int) -> np.ndarray:
        g = _region_gray(cache, region, i)
        return g.T if horizontal else g

    prev = get(0)
    L = prev.shape[0]  # height (or width when horizontal, after transposing)
    half = _template_half(L)
    base = L - 2 * half   # row where the template starts inside the previous frame
    off = [0]
    cum = 0
    unresolved: list[int] = []
    fallback: list[int] = []
    for i in range(1, n):
        cur = get(i)
        t = prev[base:, :]
        res = cv2.matchTemplate(cur, t, cv2.TM_CCOEFF_NORMED)
        _, mx, _, loc = cv2.minMaxLoc(res)
        d = base - loc[1]

        if mx < MATCH_CONFIDENCE_MIN:
            shift = _phase_shift_along_axis(prev, cur)
            if 0 <= shift < L:
                d = shift
                fallback.append(i - 1)
            else:
                d = 0
                unresolved.append(i - 1)
        elif d < 0:
            # Content never moves backwards in a scroll; a negative value with
            # good confidence is a spurious match, not real motion.
            d = 0

        cum += d
        off.append(cum)
        prev = cur
    return ScrollOffsets(values=off, unresolved=unresolved, fallback_pairs=fallback)


def _template_half(L: int) -> int:
    """Half the template height, bounded so there is room left to search in.

    The template is searched inside a frame of `L` rows, so the maximum
    detectable displacement is exactly how much free space is left: a template
    covering almost the whole frame cannot measure more than a few px. With
    the original `min(120, L//2 - 1)`, a region 180px tall produced a template
    of 178 rows and a range of 1px: any real jump measured as 0 -- and with
    HIGH confidence at that (0.94 measured), because the template still
    matched well in its one possible position, so neither the confidence
    threshold nor the fallback noticed. Content lost in silence.
    """
    if L <= 4:
        return 1
    return max(MIN_TEMPLATE_HALF, min(TEMPLATE_HALF, L // MAX_TEMPLATE_FRAC))


def _phase_shift_along_axis(prev: np.ndarray, cur: np.ndarray) -> int:
    """Forward displacement between two crops, via phase correlation. They
    arrive already transposed when the scroll is horizontal, so the axis of
    interest is always the vertical one."""
    (_dx, dy), _resp = cv2.phaseCorrelate(prev.astype(np.float32), cur.astype(np.float32))
    return int(round(-dy))


def compose_scroll(cache: FrameCache, region: Region, offsets: list[int] | ScrollOffsets,
                    horizontal: bool = False, band: int = BAND) -> ScrollComposite:
    n = len(cache)
    if isinstance(offsets, ScrollOffsets):
        offsets = offsets.values
    L = region.height if not horizontal else region.width
    other = region.width if not horizontal else region.height
    total = offsets[-1] + L

    canvas = np.zeros((total, other), dtype=np.uint8)
    bands: list[BandInfo] = []

    def get(i: int) -> np.ndarray:
        g = _region_gray(cache, region, i)
        return g.T if horizontal else g

    frame_cache: dict[int, np.ndarray] = {}

    def cached(i: int) -> np.ndarray:
        if i not in frame_cache:
            frame_cache[i] = get(i)
            if len(frame_cache) > 64:
                frame_cache.pop(next(iter(frame_cache)))
        return frame_cache[i]

    for y0 in range(0, total, band):
        y1 = min(y0 + band, total)
        idx = [i for i in range(n) if offsets[i] <= y0 and offsets[i] + L >= y1]

        if len(idx) < MIN_CONTRIBUTORS:
            idx_any = [i for i in range(n) if offsets[i] < y1 and offsets[i] + L > y0]
            if idx_any:
                stack = np.stack([
                    _slice_band(cached(i), offsets[i], y0, y1, L) for i in idx_any
                ])
                canvas[y0:y1] = np.max(stack, axis=0)
            bands.append(BandInfo(y0, y1, len(idx_any), True))
            continue

        stack = np.stack([cached(i)[y0 - offsets[i]: y1 - offsets[i]] for i in idx])
        canvas[y0:y1] = np.median(stack, axis=0).astype(np.uint8)
        bands.append(BandInfo(y0, y1, len(idx), False))

    if horizontal:
        canvas = canvas.T
    return ScrollComposite(canvas=canvas, offsets=offsets, bands=bands)


def _slice_band(img: np.ndarray, off: int, y0: int, y1: int, L: int) -> np.ndarray:
    """Crop the part of `img` falling inside [y0,y1), padding with white where
    the frame does not reach. Used only in the low-confidence fallback, when
    no frame covers the whole band."""
    lo = max(y0, off)
    hi = min(y1, off + L)
    out = np.full((y1 - y0, img.shape[1]), 255, dtype=np.uint8)
    if hi > lo:
        out[lo - y0: hi - y0] = img[lo - off: hi - off]
    return out


def compose_paginated(cache: FrameCache, region: Region) -> list[PageComposite]:
    """Composite one page per cursor sweep.

    Pages that are not tablature get flagged, not dropped: in a multi-song
    video the crossing from one song to the next is a crossfade, and the
    frames in between are mostly the background footage. If the cursor wrap
    lands there, those frames form their own "page group" and composite into a
    near-black rectangle that then prints as a solid band in the PDF.

    The criterion is the same one that defines the region in the first place:
    a tablature page is paper, that is, mostly light. Measured on the 5-song
    video: real pages 0.93-0.98 paper, transition pages 0.00-0.04. The
    threshold sits in between, far from both.

    They are flagged rather than deleted so page detection itself is left
    alone (failure mode 1: the page count comes from the cursor wrap, never
    from content) and so the verification layer can report how many were
    discarded instead of having them vanish silently.
    """
    n = len(cache)
    samples = track_cursor(cache, region, indices=list(range(n)))
    boundaries = detect_page_wraps(samples, region.width)
    if not boundaries:
        boundaries = [0]

    pages: list[PageComposite] = []
    for pi, start in enumerate(boundaries):
        end = boundaries[pi + 1] if pi + 1 < len(boundaries) else n
        frame_idx = list(range(start, end))
        # Drop the first and last frame of the group: partial transitions.
        interior = frame_idx[1:-1] if len(frame_idx) > 2 else frame_idx

        low_conf = len(interior) < MIN_CONTRIBUTORS
        use = interior if not low_conf else frame_idx

        stack = np.stack([_region_gray(cache, region, i) for i in use])
        if low_conf:
            canvas = np.max(stack, axis=0)
        else:
            canvas = np.median(stack, axis=0).astype(np.uint8)

        paper_fraction = float((canvas > PAPER_VALUE).mean())

        pages.append(PageComposite(
            index=pi,
            canvas=canvas,
            frame_range=(start, end - 1),
            n_contributors=len(use),
            low_confidence=low_conf,
            paper_fraction=paper_fraction,
            is_transition=paper_fraction < MIN_PAPER_FRACTION,
        ))
    return pages


def compose(cache: FrameCache, region: Region, mode: AdvanceMode):
    if mode == AdvanceMode.PAGINATED:
        return compose_paginated(cache, region)
    horizontal = mode == AdvanceMode.SCROLL_HORIZONTAL
    offsets = compute_scroll_offsets(cache, region, horizontal=horizontal)
    return compose_scroll(cache, region, offsets, horizontal=horizontal)
